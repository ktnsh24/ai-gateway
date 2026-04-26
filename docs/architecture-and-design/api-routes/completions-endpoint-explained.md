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

- [Plain-English Walkthrough (Start Here)](#plain-english-walkthrough-start-here)
- [Endpoint Summary](#endpoint-summary)
- [Request Schema](#request-schema)
- [Response Schema](#response-schema)
- [Internal Flow](#internal-flow)
- [Curl Example](#curl-example)
- [Error Cases](#error-cases)
- [Courier Explainer](#courier-explainer)

---

## Plain-English Walkthrough (Start Here)

> **Read this section first if you're new to the gateway.** Everything below it (schemas, internal flow, error tables) is reference material that makes more sense once you have the mental picture from this section.

This walkthrough explains, in plain English with worked examples, what really happens when someone calls `POST /v1/chat/completions`. It uses a **courier** analogy throughout: think of the gateway as a busy city courier office that takes letters (your prompts), figures out which post office to send them to (AWS, Azure, Local), and brings the reply back. Wherever something gets technical, the courier shows up to keep it simple.

> *Note on the analogy.* Some earlier conversations called this the "donkey analogy" — courier and donkey are interchangeable in our docs. The point is: somebody picks up your letter, follows rules, and brings an answer back.

### The shape of the courier office

Before any clever work happens, every request walks through a small **front desk** made of three layers stacked on top of each other.

**Layer 1 — CORS.** This is the polite doorman who never refuses anyone. He just stamps the right browser-friendly stickers on the envelope on its way back out so a website in another tab can read the reply. You can forget he exists; he never blocks anything.

**Layer 2 — The request logger (the boarding pass).** The moment your request walks in, the logger does two things:

1. Mints a short random ID — twelve hex characters like `a3f9b2c1d4e7` — and pins it to the request like a boarding pass.
2. Starts a stopwatch.

That boarding pass shows up in every log line for that request. So when something goes wrong tomorrow, you grep for `a3f9b2c1d4e7` and you see the entire journey of that one letter from front desk to LLM and back. The stopwatch measures only what the gateway itself adds — not the LLM's own time. The boarding pass is also echoed back in two response headers: `X-Request-ID` and `X-Gateway-Latency-Ms`. So a curious client knows both *which* request this was and *how much overhead* the courier office added.

**Layer 3 — API-key check (the bouncer).** This layer is *optional* — it's only mounted if API keys are turned on in config. When it is mounted, it works like a bouncer at a club:

| What you show | What happens |
| --- | --- |
| Nothing — no `Authorization` header | **401 — "show me a card"** |
| `Authorization: Banana abc` (no `Bearer `) | **401 — "wrong format"** |
| `Authorization: Bearer ` (empty key) | **401 — "your card is blank"** |
| `Authorization: Bearer wrong-key` | **403 — "card's not on the list"** |
| `Authorization: Bearer right-key` | walks in |

Public paths like `/health` and `/docs` skip the bouncer entirely.

> **In dev, the bouncer is usually off.** When that happens the handler treats every anonymous caller as if they used the master key. The practical consequence: **everyone shares one rate-limit bucket**. If your local script burns through the limit, your colleague's script gets blocked too.

### Inside the office — the five-step pipeline

Once you're past the front desk, you arrive at the chat-completions handler, which is the courier's clipboard. The clipboard has five steps and they always run in this order:

```
1. Rate limit  →  2. Cache  →  3. LLM call  →  4. Cache write  →  5. Cost log
```

If any step says "stop", the steps after it don't run.

### Step 1 — The rate limiter (the courier's quota book)

Imagine the courier keeps a small notebook. Each customer (each API key) has one page. On that page he scratches a tally mark every time you send a letter. When the page fills up — say 60 marks — he refuses to take any more letters until the page resets. Every minute, he tears the page out and starts a fresh one. That's the **fixed-window counter**. Plain and effective.

The rate limiter has three personalities, decided once at startup:

- **"No rules" (disabled).** The courier doesn't even open the notebook. Every request is allowed. Useful for tests and local dev.
- **Redis (the proper notebook in head office).** When Redis is reachable, the notebook lives in Redis where every worker can read it. This is the production setup.
- **In-memory (the notebook in the courier's pocket).** If Redis is configured but unreachable at startup, the gateway silently falls back to keeping the notebook in the Python process's memory. **This is a trap.** With 4 workers, each worker has its own notebook, so your "60 per minute" effectively becomes "240 per minute".

**Concrete example.** You have a limit of 5 requests/minute. You send requests at times 0s, 10s, 20s, 30s, 40s — all five are allowed. The 6th request at 50s comes back with:

```
HTTP 429 Too Many Requests
Retry-After: 10
{ "error": "rate_limit_exceeded", "retry_in_seconds": 10 }
```

At 60s the Redis key vanishes and the next request starts fresh from 1.

**A quirk worth knowing:** the tally mark still gets added even on a rejected request. If a misbehaving client ignores the 429 and keeps hammering, the counter climbs to 61, 62, 100… It's harmless to Redis but you'll see big numbers in logs. The flip side: if your LLM call later fails for some other reason, **the tally mark is not erased**. A flaky provider can quietly burn through your customers' quotas without ever serving them an answer.

If the limiter says no, **everything below this point is skipped**: no cache lookup, no LLM call, no cost log. Just the tally and a 429.

### Step 2 — The cache (the courier's "I've seen this letter before" pile)

The courier keeps a stack of recently-answered letters on a shelf. When a new letter arrives, he checks the shelf first: "have I answered this exact letter recently? If yes, just hand back the same reply — no need to bother the post office." That's the cache. But "exact letter" is the important phrase, and the way it decides "exact" is where most surprises live.

**How the cache decides "is this the same letter?"** The cache turns the conversation messages into a fingerprint using SHA-256 — a math function that turns any text into a fixed-length string of letters and numbers. Two letters that are identical down to every comma produce the same fingerprint. Change one character and the fingerprint changes completely.

**Concrete example.** Suppose two users both ask the assistant the same question. Look carefully at what's "the same" and what isn't:

| Request | Messages | Fingerprint | Cache result |
| --- | --- | --- | --- |
| User A | `[{"role":"user","content":"What is 2+2?"}]` | `9f8d3a...` | MISS (first time) |
| User B (one second later) | `[{"role":"user","content":"What is 2+2?"}]` | `9f8d3a...` | **HIT** — same fingerprint |
| User C | `[{"role":"user","content":"what is 2+2?"}]` | `b41e09...` | MISS — lowercase `w` changed everything |
| User D | `[{"role":"user","content":"What is 2+2 ?"}]` | `c772aa...` | MISS — extra space changed everything |
| User E | `[{"role":"user","content":"What is 2 + 2?"}]` | `1d04b8...` | MISS — different spacing |

So the cache is **strict**. It only helps when callers send byte-identical messages. In practice this means it works brilliantly for things like a chatbot's "starter prompt" that gets sent on every page load, and barely at all for natural human typing.

> **Courier version.** Imagine the courier matches letters by photocopying them and laying the photocopy on the shelf. He compares pixel-by-pixel. If the new letter is in slightly different handwriting, or has an extra dot at the end, the photocopies won't match — even if a human would say they're "the same question".

**What the docs promise vs. what the code does.** The cache is *advertised* as a "semantic cache" — meaning it should match letters by *meaning*, not by exact text. The plan was: turn each prompt into an embedding (a list of numbers that captures meaning), and if the new prompt's embedding is more than 92% similar to a cached one, return the cached answer. **The code for that path exists. The handler doesn't use it.** When the handler calls the cache, it doesn't pass an embedding along, so only the exact-fingerprint path runs. The semantic branch is dead wiring as of today.

**Bypass.** A request can include `bypass_cache: true` in its body. When that's set, the cache *read* is skipped (you always get a fresh LLM answer) but the cache *write* still happens (the fresh answer refreshes the shelf for everyone else).

**On a cache hit** the handler returns the cached response and **still writes a row to the cost log** with zero tokens, zero dollars, and `cached=true`. That's how the dashboards later compute "what % of our traffic was cached?".

### Step 3 — The LLM router (the dispatch desk)

If we got past the cache without a hit, it's time to actually send the letter to a post office. The dispatch desk is the **router**, and it knows about three post offices:

- **AWS** (Bedrock — Anthropic, Llama, etc.)
- **Azure** (Azure OpenAI — GPT-4, GPT-3.5)
- **Local** (Ollama running on your laptop or a server)

The router sends the same letter format to all three thanks to LiteLLM, which acts as a universal translator. Whichever post office answers, the reply comes back in the same envelope shape.

**The four dispatch strategies:**

| Strategy | Behaviour | Courier version |
| --- | --- | --- |
| **Single** | Always primary. No backup. | "We only deal with the Royal Mail. If they're down, you wait." |
| **Fallback** | Try primary; if it fails, try fallback once. | "Try Royal Mail first. If they don't pick up, try DHL once. After that we give up." |
| **Cost-optimised** | Same fallback behaviour. The "cost optimisation" is mostly aspirational — no logic picks providers by price today. | Same as fallback, badged as cost-aware. |
| **Round-robin** | Cycle through AWS → Azure → Local. **No fallback** — if today's provider fails, the request fails. | "We rotate weekly between three couriers. If today's pick is down, sorry." |

**Concrete example of fallback.** Primary = Azure, fallback = AWS. Azure is having an outage:

```
12:00:01  → Try Azure              → fails (503)
12:00:01  → Try AWS                → succeeds
12:00:02  ← Reply returned to client (200 OK)
```

The client sees a normal 200. **They have no idea a failover happened**, because the router internally marks `fallback=true` but the handler never puts that flag in the response. Only the gateway logs show what happened. Known observability gap.

**Per-request override.** Any caller can ignore the strategy by including `preferred_provider: "azure"` (or `aws`, or `local`) in the body. That choice wins over the strategy.

**Cost estimate.** For Bedrock and Azure the dollar estimate is real (fractions of a cent based on LiteLLM's price tables). For Ollama (local) it's **always $0.00** because there's no pricing data. So your dashboards will under-count "real" cost if you route a lot of traffic to local.

**When everything fails** (single primary fails, or both primary and fallback fail), the handler returns 502. The original exception is logged but never shown to the client. **Reminder:** the rate-limit tally was already incremented in Step 1 and is *not* refunded.

### Step 4 — Cache write (filing the answer for next time)

If the LLM call succeeded, the handler writes the answer onto the shelf using the same fingerprint as in Step 2. The stored value is small: the assistant's reply text, the model name, and the token counts. A TTL is applied (a few minutes by default) so the shelf doesn't fill up forever. Same dead semantic-path as on the read side. The in-memory cache implementation never deletes expired entries, so in a long-lived production process that would be a slow memory leak.

### Step 5 — The cost log (the courier's ledger)

Every successful request — whether it was a cache hit or a real LLM call — finishes by writing a row to a ledger called `usage_logs`. The ledger has a personality picker too: PostgreSQL in production (schema created lazily), in-memory in dev, no-op for tests.

Each row captures: the boarding pass (request ID), the API key, the model, the provider, prompt and completion token counts, the dollar estimate, the gateway latency, whether it was a cache hit, and a UTC timestamp. The `/v1/usage` endpoint slices and dices this table to produce dashboards. **It's the single source of truth for "how much did this gateway spend yesterday?"**

**The quiet trap:** there's no `try/except` around the cost-log write in the handler. If PostgreSQL is unavailable for thirty seconds, every request during that window will pass the rate limiter (tally incremented), miss the cache, call the LLM successfully (you've been billed by AWS/Azure), try to write the cost row → fail, and the database error bubbles up to the client as a **500 Internal Server Error**. The user has effectively been charged but doesn't see the answer.

### The whole condition matrix in one table

| Scenario | Rate counter | Cache read | LLM call | Cache write | Cost row | Status |
| --- | --- | --- | --- | --- | --- | --- |
| Auth off (anonymous) | shared bucket | yes | yes | yes | yes | 200 |
| Auth on, bad key | — | — | — | — | — | 401/403 |
| Rate limit hit | +1 | — | — | — | — | 429 |
| Cache hit | +1 | HIT | — | — | yes (cached=true, $0) | 200 |
| Cache miss, LLM ok | +1 | MISS | yes | yes | yes (real $) | 200 |
| Cache miss, primary fails, fallback ok | +1 | MISS | yes (twice) | yes | yes (real $) | 200 (fallback flag swallowed) |
| Cache miss, all providers fail | +1 (no refund) | MISS | yes (failed) | no | no | 502 |
| Cache miss, LLM ok, cost-log DB down | +1 | MISS | yes (paid) | yes | **failed** | 500 |
| `bypass_cache: true`, LLM ok | +1 | skipped | yes | yes (refreshes shelf) | yes | 200 |

### The honest health check (what a code review would surface)

These are the rough edges worth knowing about — none are show-stoppers, but they're the kind of things you'd want to fix before a real production rollout:

1. **Semantic cache is advertised but not wired.** Today it only does exact-string matching. The embedding path is dead code.
2. **Failed LLM calls still consume rate quota.** A misbehaving provider can quietly DoS your users.
3. **No retry or circuit-breaker around providers.** Fallback is a single shot, not a retry loop with exponential backoff.
4. **In-memory rate limiter and cache don't share state across workers.** Fine in dev, dangerous at multi-worker scale.
5. **Cost-log failures cause user-visible 500s** even though the LLM call already succeeded and the answer is in memory.
6. **The `fallback=true` flag never reaches the client.** Observability gap — you can only see fallbacks happened by reading server logs.
7. **Cache stats reset on restart.** No persistent counter for "lifetime cache hit rate".
8. **Boundary burst on rate limiter.** A client can fire 60 requests in the last second of one window and 60 more in the first second of the next, bypassing the spirit of the limit. Acceptable trade-off; the provider's own rate limits are the backstop.

### TL;DR

- A request walks past three reception layers (CORS, logger, optional bouncer) and arrives at a five-step pipeline.
- The pipeline is **rate limit → cache → LLM → cache write → cost log**. Any step can stop the train.
- The cache is **strict** (exact-text match only — the "semantic" promise is unimplemented).
- The router has **four strategies** to pick a provider, plus a per-request override.
- The cost log is the **single source of truth** for spending, but it has no error handling so its database going down breaks user requests.
- The biggest fragilities to know: failed-call quota burn, swallowed fallback flag, and cost-log 500s.

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
