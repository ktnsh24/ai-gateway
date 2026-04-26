# Completions Endpoint — Deep Dive

> `POST /v1/chat/completions` — the main entry point. Every chat call to the gateway lands here, runs through auth, rate limit, semantic cache, LLM routing (with optional fallback), and cost logging.

> **Source file:** `src/routes/completions.py`
>
> **Related docs:**
>
> - [API Contract](../api-contract.md) — full schema reference
> - [API Routes Overview](../api-routes-explained.md) — how all 5 routes fit together
> - [Caching Deep Dive](../../ai-engineering/caching-deep-dive.md) — semantic cache internals
> - [Rate Limiting Deep Dive](../../ai-engineering/rate-limiting-deep-dive.md) — fixed-window counter
> - [Cost Tracking Deep Dive](../../ai-engineering/cost-tracking-deep-dive.md) — per-request log schema
> - [LiteLLM Deep Dive](../../ai-engineering/litellm-deep-dive.md) — universal harness routing

---

## Table of Contents

- [Architecture Walkthrough (Start Here)](#architecture-walkthrough-start-here)
- [Endpoint Summary](#endpoint-summary)
- [Request Schema](#request-schema)
- [Response Schema](#response-schema)
- [Internal Flow](#internal-flow)
- [Curl Example](#curl-example)
- [Error Cases](#error-cases)
- [Courier Explainer](#courier-explainer)

---

## Architecture Walkthrough (Start Here)

> This walkthrough explains what really happens when a request hits `POST /v1/chat/completions` — every design pattern, every algorithm, every branch, every known quirk. No code snippets, no file paths — patterns and trade-offs only.

---

### How the app is assembled at startup

Before the first request arrives, the application lifespan function runs a **Factory Method + Strategy Pattern** to build four components and store them on `app.state`:

| Component | Factory call | Possible implementations |
| --- | --- | --- |
| `router` | `create_router(settings)` | `LiteLLMRouter` (only one today) |
| `cache` | `create_cache(settings)` | `RedisSemanticCache`, `InMemoryCache`, `NoCache` |
| `rate_limiter` | `create_rate_limiter(settings)` | `RedisRateLimiter`, `InMemoryRateLimiter`, `NoRateLimiter` |
| `cost_tracker` | `create_cost_tracker(settings)` | `PostgresCostTracker`, `InMemoryCostTracker`, `NoCostTracker` |

Every implementation shares an abstract base class — the handler never knows which concrete class it is talking to. The factory picks the implementation by probing whether Redis and Postgres are actually reachable at startup time. If Redis is unreachable, it silently falls back to the in-memory variant. If startup fails catastrophically and a component is never built, requests fail the moment they try to access `app.state`.

> **Courier version.** Before the depot opens, the manager runs through a checklist. She tries to phone head office (Redis), tries to open the central ledger (Postgres), and hires whichever team is available. If the Redis phone line is dead, she substitutes a clerk with a pocket notebook. If all else fails and some desk is not staffed by opening time, every customer who walks up to that desk gets turned away.

---

### The three-layer front desk (middleware)

Every request — before it reaches any handler — walks through three middleware layers in order.

**Layer 1 — CORSMiddleware.** The polite doorman. He stamps browser-friendly `Access-Control-*` headers on every outbound response so a web page on a different origin can read the reply. He never blocks anything; he exists purely for browsers.

**Layer 2 — RequestLoggingMiddleware (the boarding pass).** The moment a request enters, the logger mints a 12-character hex request ID (`uuid4().hex[:12]`) and starts a stopwatch. Every log line for that request carries the ID, so you can trace the entire lifecycle with a single grep. On the way back out, the middleware stamps the response with `X-Request-ID` and `X-Gateway-Latency-Ms`.

**Layer 3 — APIKeyMiddleware (the optional bouncer).** Mounted only if `auth_enabled=True`. It reads the `Authorization: Bearer <key>` header and checks the key against configured keys. Public paths (`/health`, `/docs`, `/redoc`) bypass it entirely. When auth is off, every anonymous caller is treated as the master key — they all share one rate-limit bucket.

| What you show | What happens |
| --- | --- |
| No `Authorization` header | 401 — header missing |
| Non-Bearer scheme (`Authorization: Token abc`) | 401 — wrong format |
| `Authorization: Bearer ` (empty) | 401 — blank key |
| `Authorization: Bearer wrong-key` | 403 — key not on the list |
| `Authorization: Bearer right-key` | passes through |

---

### The five-step pipeline

Once past the front desk, the completions handler runs these five steps in order. Any step that fails stops the pipeline immediately.

```
1. Rate limit → 2. Cache check → 3. LLM call → 4. Cache write → 5. Cost log
```

---

#### Step 1 — Rate limit

**Algorithm: Fixed-Window Counter** (the source code comment says "sliding window" — this is incorrect; the implementation is fixed-window).

The rate limiter checks whether the API key has exceeded its quota for the current 60-second window. The counter key is `gw:rate:{api_key}`.

There are three implementations, decided at startup:

| Implementation | Mechanism | Multi-worker safe? |
| --- | --- | --- |
| `RedisRateLimiter` | `INCR key` then `EXPIRE key 60` on first request; atomic; counter lives in Redis | Yes |
| `InMemoryRateLimiter` | `dict[api_key → (count, window_start)]`; resets when `now − window_start ≥ 60s` | No — each worker has its own dict |
| `NoRateLimiter` | Always returns allowed — no counter at all | N/A |

**Worked example — rate limit timeline (limit = 5/minute):**

| Time (s) | Event | Counter value | Result |
| --- | --- | --- | --- |
| 0 | Request 1 | 1 | 200 |
| 15 | Request 2 | 2 | 200 |
| 59 | Request 5 | 5 | 200 |
| 59 | Request 6 | 6 | 429 — window still active |
| 61 | Window resets | 0 → 1 | 200 — fresh window |

**Burst quirk.** Because the window is fixed, a caller can fire 5 requests in the last second of window 1 and 5 more in the first second of window 2 — 10 requests in 2 seconds — without ever being rejected. This is the classic fixed-window double-burst: the limiter only looks at the current window's count, not the rate across the boundary.

**Quota-burn bug.** The counter increments before knowing whether the LLM will succeed. If the provider returns a 5xx, the increment is not rolled back. A flaky provider silently burns through customers' quotas.

If the limiter says no: the remaining steps are skipped and a `429 rate_limit_exceeded` is returned.

> **Courier version.** The dispatcher has a notebook with one page per customer. Every time a customer hands in a letter, she makes a tally mark — even before checking if the post office is open. When the page is full, the customer is told to come back next minute. The fixed-window trap: a clever customer can hand in five letters just before midnight and five more just after — ten letters in two minutes with only one page-full check.

---

#### Step 2 — Cache check

The cache is checked before any LLM call. The fingerprint used to identify the same request is computed as `SHA-256(json.dumps(messages, sort_keys=True))[:32]`. The `sort_keys=True` argument makes the fingerprint deterministic even if the caller changes the key ordering of message objects. The result is the first 32 hex characters of the SHA-256 digest.

**Worked example — fingerprint sensitivity:**

| Request | Messages (abbreviated) | Fingerprint | Result |
| --- | --- | --- | --- |
| A | `[{"role":"user","content":"What is 2+2?"}]` | `9f8d3a…` | MISS (first) |
| B | identical to A | `9f8d3a…` | HIT |
| C | `[{"role":"user","content":"what is 2+2?"}]` | `b41e09…` | MISS — lowercase `w` differs |
| D | `[{"role":"user","content":"What is 2+2 ?"}]` | `c772aa…` | MISS — trailing space differs |

Two cache implementations exist:

- `RedisSemanticCache`: stores entries under `gw:cache:exact:{hash}` and `gw:cache:semantic:{hash}`.
- `InMemoryCache`: plain dict with TTL timestamps — no active eviction policy; expired entries are deleted only when accessed, so a long-lived process accumulates stale entries (memory leak).

**Dead semantic path.** The handler calls `cache.get(messages, embedding=None)`. The cache class has a fully implemented semantic-match branch guarded by `if embedding:` — but because `embedding` is always `None`, that branch never executes. Only exact-match runs. The semantic cache is dead wiring.

**`bypass_cache: true`.** When set, the cache read is skipped (the caller always gets a fresh LLM response), but the cache write in Step 4 still runs — so the shelf is refreshed for other callers.

**On a cache hit:** the handler returns immediately and writes a zero-cost row to the cost tracker with `cached=True`. The LLM is never called.

> **Courier version.** The courier checks the shelf for a photocopy of this exact letter. The matching is pixel-perfect — a lowercase letter or an extra space creates a completely different photocopy. There is also a section of the shelf for "letters that mean roughly the same thing" (semantic cache), but the dispatcher never sends the courier to that section today — the wiring is there, the courier just never goes.

---

#### Step 3 — LLM routing

If no cache hit, the request goes to the router. The router picks a provider using one of four strategies:

| Strategy | Behaviour | Fallback on failure |
| --- | --- | --- |
| `SINGLE` | Always uses `settings.cloud_provider` | None — request fails |
| `ROUND_ROBIN` | `providers[call_count % len(providers)]`; increments counter | None — if chosen provider fails, request fails |
| `FALLBACK` | Try primary; on exception, try `settings.fallback_provider` once | One attempt at fallback |
| `COST_OPTIMISED` | Identical to `FALLBACK` in code — no actual cost-comparison logic exists | One attempt at fallback |

**Worked example — fallback routing:**

| Time | Event | Result |
| --- | --- | --- |
| 12:00:01 | Try primary (Azure) | 503 from Azure |
| 12:00:01 | Try fallback (AWS) | 200 |
| 12:00:02 | Reply sent to client | 200 OK — client never sees that fallback was used |

**Per-request override.** A caller can include `preferred_provider: "azure"` in the request body. The value resolves to a `CloudProvider` enum. An unrecognised value logs a warning and falls back to the strategy default.

**Fallback flag swallowed.** When fallback is used, the router returns `{"fallback": True}` in its result dict, but the completions handler never reads that key. The client always sees a plain 200 — the failover is invisible without reading server logs.

LiteLLM acts as a universal translator across all three providers. Provider model IDs are prefixed per-provider:

| Provider | Chat model ID format | Embedding model ID format |
| --- | --- | --- |
| AWS Bedrock | `bedrock/{model_id}` | `bedrock/{embed_model_id}` |
| Azure OpenAI | `azure/{deployment}` | `azure/{embed_deployment}` |
| Local Ollama | `ollama/{model}` | `ollama/{embed_model}` |

Cost estimate uses `litellm.completion_cost()`, which has pricing tables for Bedrock and Azure. For Ollama the estimate is always `$0.00` — no pricing data exists.

> **Courier version.** If the preferred post office is closed, the fallback strategy lets the dispatcher quietly re-route to the backup office — the customer gets their reply with no indication it was rerouted. The round-robin strategy rotates mechanically: if today's office is shut, tough luck. The "cost-optimised" badge sounds smart but it just does the same as fallback today.

---

#### Step 4 — Cache write

If the LLM call succeeded, the response is stored under the same fingerprint computed in Step 2. A TTL is applied so entries expire automatically.

Two implementation notes: `InMemoryCache` has no active eviction — the memory footprint grows until the process restarts or an expired entry is read and removed on-access. In a long-lived production process, this is a slow memory leak. The dead semantic path affects the write too: the semantic index is never written because `embedding=None` is always passed.

> **Courier version.** The courier files a photocopy of both the letter and the reply on the shelf with an "expires in N minutes" stamp. If the shelf uses pocket-notebooks (in-memory), old copies are never actively thrown out — they pile up until they are looked at and found stale.

---

#### Step 5 — Cost log

Every request — cache hit or live LLM call — ends with a write to the cost ledger. The `PostgresCostTracker` lazily creates the `usage_logs` table on first use via SQLAlchemy, then appends one row per request. The row captures: request ID, API key, model, provider, `prompt_tokens`, `completion_tokens`, `estimated_cost_usd`, `latency_ms`, `cached` flag, and UTC timestamp.

**Period boundaries** (relevant when reading usage summaries):

| Period | Boundary |
| --- | --- |
| `today` | UTC midnight of the current day — not the caller's local midnight |
| `week` | Rolling last 7 days from now |
| `month` | Rolling last 30 days from now |

**Quiet-trap bug.** There is no `try/except` around `cost_tracker.log_request()` in the handler. If Postgres is temporarily unreachable: the rate limit is incremented, the cache misses, the LLM succeeds (the cloud provider has been billed), the cache write succeeds — then the cost log raises an uncaught exception and the client receives `500 Internal Server Error`. The user sees a 500; the answer was computed; the cloud provider charged the account.

> **Courier version.** After every delivery, the courier writes the job in the leather ledger — cost, time, destination. The trap: the clerk holding the pen has no safety net. If the ink jar is empty (Postgres down), the whole job is declared failed and the courier hands the customer a "sorry, error" note — even though the letter was already delivered and the post office already charged the depot.

---

### Condition matrix

| Scenario | Rate counter | Cache read | LLM call | Cache write | Cost row | Status |
| --- | --- | --- | --- | --- | --- | --- |
| Auth off (anonymous) | shared bucket | yes | yes | yes | yes | 200 |
| Auth on, bad key | — | — | — | — | — | 401/403 |
| Rate limit hit | +1 | — | — | — | — | 429 |
| Cache hit | +1 | HIT | — | — | yes (cached=true, $0) | 200 |
| Cache miss, LLM ok | +1 | MISS | yes | yes | yes (real $) | 200 |
| Cache miss, primary fails, fallback ok | +1 | MISS | yes (twice) | yes | yes (real $) | 200 (fallback flag swallowed) |
| Cache miss, all providers fail | +1 (no refund) | MISS | yes (failed) | no | no | 502 |
| LLM ok, cost-log DB down | +1 | MISS | yes (paid) | yes | **failed** | 500 |
| `bypass_cache: true`, LLM ok | +1 | skipped | yes | yes (refreshes shelf) | yes | 200 |

---

### 🩺 Honest health check

1. **Semantic cache is never activated.** The handler passes `embedding=None` to every cache call, so the semantic branch in the cache class never runs. Only exact-match operates. Fix: compute the embedding before calling the cache and pass it in.
2. **Fixed-window counter is mis-labelled "sliding window" in the source.** The algorithm is a standard fixed-window; true sliding-window would require a sorted set in Redis. Fix: correct the comment, or replace INCR+EXPIRE with a sorted-set implementation.
3. **Failed LLM calls still consume rate quota.** The increment happens before the LLM call; there is no rollback on failure. Fix: add a rollback path or decrement on known LLM error.
4. **`COST_OPTIMISED` strategy is identical to `FALLBACK`.** No cost-comparison logic exists. Fix: implement cost-based selection or rename the strategy to avoid misleading operators.
5. **Fallback flag is swallowed.** The router returns `fallback: True` in its result but the handler never reads it. Clients and dashboards cannot observe failovers. Fix: surface the flag in the response or a structured log field.
6. **`InMemoryCache` leaks memory.** Expired entries accumulate and are only removed when accessed. Fix: add a background eviction loop or switch to a TTL-aware data structure.
7. **No `try/except` around `cost_tracker.log_request()`.** A Postgres outage causes HTTP 500 even after a successful LLM call. Fix: wrap in try/except, log the error, and return the response regardless.
8. **`today` period uses UTC midnight, not the caller's local midnight.** Engineers in non-UTC timezones see a truncated "today" window. Fix: accept a `timezone` parameter, or document the UTC assumption prominently.

---

### TL;DR

- **Factory Method + Strategy Pattern** wire four components (`router`, `cache`, `rate_limiter`, `cost_tracker`) at startup; implementations swap based on what is reachable (Redis, Postgres) without touching handler code.
- **Fixed-Window Counter** (not sliding window) enforces per-key rate limits; burst is possible at window boundaries; failed calls are not refunded.
- **Exact-match cache only** — the SHA-256 fingerprint with `sort_keys=True` is deterministic but case- and whitespace-sensitive; the semantic path is fully implemented but never activated by the handler.
- **Four routing strategies** (Single, Round-Robin, Fallback, Cost-Optimised) — Cost-Optimised is a no-op alias for Fallback; fallback transitions are invisible to clients.
- The biggest known fragilities: cost-log 500s on Postgres outage, swallowed fallback flag, and in-memory cache memory leak.
---

## Endpoint Summary

| Attribute | Value | 🚚 Courier |
|-----------|-------|-----------|
| Method | `POST` | The courier hands a fresh delivery slip in at the dispatch desk; never a passive lookup. |
| Path | `/v1/chat/completions` | Same address as OpenAI's main delivery window so any OpenAI-shaped client talks to this depot unmodified. |
| Auth | Bearer token (when `API_KEYS_ENABLED=true`) | The gate guard checks the courier's `Authorization: Bearer <key>` header before the slip even reaches the dispatcher. |
| Purpose | Run a chat completion through cache → LLM → ledger | The full main-window pipeline: pickup locker peek, delivery if needed, then a line written into the expense ledger. |

---

## Request Schema

Pydantic model: `ChatCompletionRequest` (`src/models.py`).

| Field | Type | Required | Default | Description | 🚚 Courier |
|-------|------|----------|---------|-------------|-----------|
| `messages` | `list[ChatMessage]` | ✅ | — | Conversation messages with `role` and `content` | The actual delivery slip — the running conversation passed to whichever courier ends up carrying this delivery. |
| `model` | `str` | ❌ | `"default"` | Model identifier; `"default"` lets the gateway pick from the active provider | Courier breed request; `"default"` lets the dispatch desk pick from the current roster instead of forcing a specific stall. |
| `temperature` | `float` | ❌ | `0.7` | Sampling temperature, 0.0–2.0 | Creativity dial: 0 = courier sticks to the well-trodden path, 2 = courier wanders into wildly improvised routes. |
| `max_tokens` | `int \| None` | ❌ | `None` | Cap on response tokens | Trip-length cap — the courier is recalled to the depot once it has emitted this many tokens, mid-sentence if needed. |
| `stream` | `bool` | ❌ | `false` | Enable streaming (currently parsed but server returns one shot) | Asks the courier to deliver in instalments, but the dispatch desk in this build still buffers the full reply before handing it back. |
| `top_p` | `float` | ❌ | `1.0` | Nucleus sampling probability mass | Narrows the courier's choice of next-step routes to the most probable few when set below 1. |
| `bypass_cache` | `bool` | ❌ | `false` | Skip the semantic cache for this request (gateway extension) | Tells the dispatcher to ignore the pickup locker shelf entirely and dispatch a live courier even if a near-identical slip is filed. |
| `preferred_provider` | `str \| None` | ❌ | `None` | Force a specific provider: `aws`, `azure`, `local` (gateway extension) | Override the routing strategy for one delivery — pick the AWS depot, Azure hub, or local depot explicitly. |

`ChatMessage` itself has just `role` (system/user/assistant) and `content`.

---

## Response Schema

Pydantic model: `ChatCompletionResponse`.

| Field | Type | Description | 🚚 Courier |
|-------|------|-------------|-----------|
| `id` | `str` | `chatcmpl-<request_id>` (12 hex chars) | The tachograph stamp burned onto this completed trip; cross-references logs and ledger entries. |
| `object` | `str` | Always `"chat.completion"` | Confirms to the courier that a filled receipt — not an error slip — came back through the dispatch window. |
| `created` | `int` | Unix timestamp | Wall-clock moment the courier handed the filled note back through the main delivery window. |
| `model` | `str` | LiteLLM-format model id (`provider/model`) | Names exactly which model type and which remote depot handled this run, so the ledger can attribute cost. |
| `choices` | `list[ChatChoice]` | Always one choice in this build | The single filled shipping manifest returned by the courier — no n-best alternatives are produced. |
| `usage` | `UsageInfo` | `prompt_tokens`, `completion_tokens`, `total_tokens` | Cargo-unit tally: fuel chewed reading the slip plus fuel burnt writing the reply, used to price the delivery. |
| `cost` | `CostInfo` | `estimated_cost_usd`, `provider`, `model`, `cached` | Line item ready for the expense ledger — provider depot, model type, USD estimate, and a flag if pickup locker answered. |
| `cache_hit` | `bool` | `true` when the response came from semantic cache | Tells the courier the pickup locker had a pre-written reply and no courier actually left the depot. |
| `gateway_latency_ms` | `float` | End-to-end gateway processing time | Total milliseconds from front-door arrival to the courier collecting the filled receipt — includes pickup locker and courier time. |

---

## Internal Flow

```
client → CORS middleware
       → RequestLoggingMiddleware  (assigns X-Request-ID, starts timer)
       → APIKeyMiddleware          (only if API_KEYS_ENABLED)
       → chat_completions() handler
            │
            ├─ 1. Pull settings, llm_router, cache, rate_limiter, cost_tracker
            │     from app.state (dependency injection without Depends())
            │
            ├─ 2. Extract Bearer token from Authorization header
            │     fallback to settings.master_api_key for unauthenticated dev calls
            │
            ├─ 3. rate_limiter.check(api_key)
            │     ├─ allowed=False  → raise HTTPException(429) with reset_in_seconds
            │     └─ allowed=True   → continue
            │
            ├─ 4. (unless bypass_cache=True) cache.get(messages_dicts)
            │     ├─ HIT  → log a cached entry to cost_tracker (cost=0, cached=True)
            │     │         return ChatCompletionResponse(cache_hit=True, ...)
            │     └─ MISS → continue
            │
            ├─ 5. llm_router.chat_completion(messages, model, temperature,
            │                                max_tokens, preferred_provider)
            │     ├─ resolves provider via routing strategy (single/round/fallback/cost)
            │     ├─ calls LiteLLM completion() with provider-prefixed model id
            │     ├─ on failure with FALLBACK strategy → tries next provider
            │     └─ raises on full exhaustion → HTTPException(502)
            │
            ├─ 6. completion_cost(completion_response) via LiteLLM
            │     → estimated USD cost for the call
            │
            ├─ 7. cache.put(messages_dicts, {content, model, usage})
            │     stores response keyed by message hash + embedding
            │
            ├─ 8. cost_tracker.log_request(request_id, api_key, model, provider,
            │                              tokens, cost, latency_ms, cached=False)
            │     writes one row to PostgreSQL (or in-memory list)
            │
            └─ 9. Return ChatCompletionResponse with cost / cache_hit / latency
       ← RequestLoggingMiddleware  (sets X-Gateway-Latency-Ms header, logs status)
       ← client
```

---

## Curl Example

```bash
curl -sS http://localhost:8100/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $GATEWAY_API_KEY" \
  -d '{
    "model": "default",
    "messages": [
      {"role": "system", "content": "You are a concise assistant."},
      {"role": "user",   "content": "What is the capital of France?"}
    ],
    "temperature": 0.2,
    "max_tokens": 64
  }' | jq
```

A second identical call within the cache TTL returns the same body with `"cache_hit": true` and `gateway_latency_ms` typically under 30 ms.

---

## Error Cases

| Status | `error` code | When it fires | 🚚 Courier |
|--------|--------------|---------------|-----------|
| `401` | `authentication_required` | `APIKeyMiddleware` saw no `Authorization: Bearer …` header on a protected path | Courier showed up with no permission slip; gate guard refuses entry before the dispatch desk is even reached. |
| `403` | `forbidden` | Bearer token did not match `master_api_key` (or any configured key) | Slip was wrong colour — the gate guard recognises it as a forgery and turns the courier away at the door. |
| `422` | (FastAPI default) | Pydantic validation on `ChatCompletionRequest` failed (missing `messages`, bad `temperature` range, etc.) | Gateway inspected the slip, found illegal parcel or wrong field shape, and rejected it before any courier was harnessed. |
| `429` | `rate_limit_exceeded` | `rate_limiter.check(api_key)` returned `allowed=False` for the current minute window | Courier blew through their daily dispatch quota for this minute; dispatcher slams the gate until the window TTL expires. |
| `502` | `llm_provider_error` | `llm_router.chat_completion` raised after primary (and any fallback) provider failed | All registered stables said "no" — every courier is sick, unreachable, or refused the parcel, and the chain ran out. |

---

## 🚚 Courier Explainer

This is the **main delivery window** of the gateway. A client hands in a shipping manifest (the `messages` array) and five things happen, in order, before the reply comes back:

1. **API-key auth** (`APIKeyMiddleware`) checks the caller's key and either lets them through or rejects them.
2. **Rate limit** (`rate_limiter`) checks the per-minute cap for this key. One request too many = 429.
3. **Cache check** (`cache`) — semantic cache lookup. If a near-identical note was answered recently, return the same reply instantly with a zero-cost line on the tab.
4. **LLM dispatch** (`llm_router`) — pick a courier from the active provider (AWS, Azure, or local Ollama). On `fallback` strategy, retry the next courier if the chosen one errors.
5. **Cost tab entry** (`cost_tracker`) — every request, cached or live, gets one row: API key, model, tokens, USD cost, round-trip time.

The reply includes everything the caller paid for — token counts, USD estimate, whether the cache answered, and the full wall-clock time the gateway took.
