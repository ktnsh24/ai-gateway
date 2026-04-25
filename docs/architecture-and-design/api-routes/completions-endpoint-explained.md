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

- [Endpoint Summary](#endpoint-summary)
- [Request Schema](#request-schema)
- [Response Schema](#response-schema)
- [Internal Flow](#internal-flow)
- [Curl Example](#curl-example)
- [Error Cases](#error-cases)
- [Donkey Explainer](#donkey-explainer)

---

## Endpoint Summary

| Attribute | Value | 🫏 Donkey |
|-----------|-------|-----------|
| Method | `POST` | The courier hands a fresh delivery slip in at the dispatch desk; never a passive lookup. |
| Path | `/v1/chat/completions` | Same address as OpenAI's main delivery window so any OpenAI-shaped client talks to this stable unmodified. |
| Auth | Bearer token (when `API_KEYS_ENABLED=true`) | Stable's gate guard checks the courier's `Authorization: Bearer <key>` header before the slip even reaches the dispatcher. |
| Purpose | Run a chat completion through cache → LLM → ledger | The full main-window pipeline: pigeon-hole peek, donkey trip if needed, then a line written into the expense ledger. |

---

## Request Schema

Pydantic model: `ChatCompletionRequest` (`src/models.py`).

| Field | Type | Required | Default | Description | 🫏 Donkey |
|-------|------|----------|---------|-------------|-----------|
| `messages` | `list[ChatMessage]` | ✅ | — | Conversation messages with `role` and `content` | The actual delivery slip — the running conversation passed to whichever donkey ends up carrying this trip. |
| `model` | `str` | ❌ | `"default"` | Model identifier; `"default"` lets the gateway pick from the active provider | Donkey breed request; `"default"` lets the dispatch desk pick from the current roster instead of forcing a specific stall. |
| `temperature` | `float` | ❌ | `0.7` | Sampling temperature, 0.0–2.0 | Creativity dial: 0 = donkey sticks to the well-trodden path, 2 = donkey wanders into wildly improvised routes. |
| `max_tokens` | `int \| None` | ❌ | `None` | Cap on response tokens | Trip-length cap — the donkey is recalled to the stable once it has emitted this many cargo units, mid-sentence if needed. |
| `stream` | `bool` | ❌ | `false` | Enable streaming (currently parsed but server returns one shot) | Asks the donkey to deliver in instalments, but the dispatch desk in this build still buffers the full reply before handing it back. |
| `top_p` | `float` | ❌ | `1.0` | Nucleus sampling probability mass | Narrows the donkey's choice of next-step routes to the most probable few when set below 1. |
| `bypass_cache` | `bool` | ❌ | `false` | Skip the semantic cache for this request (gateway extension) | Tells the dispatcher to ignore the pigeon-hole shelf entirely and dispatch a live donkey even if a near-identical slip is filed. |
| `preferred_provider` | `str \| None` | ❌ | `None` | Force a specific provider: `aws`, `azure`, `local` (gateway extension) | Override the routing strategy for one trip — pick the AWS depot, Azure hub, or local barn explicitly. |

`ChatMessage` itself has just `role` (system/user/assistant) and `content`.

---

## Response Schema

Pydantic model: `ChatCompletionResponse`.

| Field | Type | Description | 🫏 Donkey |
|-------|------|-------------|-----------|
| `id` | `str` | `chatcmpl-<request_id>` (12 hex chars) | The tachograph stamp burned onto this completed trip; cross-references logs and ledger entries. |
| `object` | `str` | Always `"chat.completion"` | Confirms to the courier that a filled receipt — not an error slip — came back through the dispatch window. |
| `created` | `int` | Unix timestamp | Wall-clock moment the donkey handed the filled note back through the main delivery window. |
| `model` | `str` | LiteLLM-format model id (`provider/model`) | Names exactly which donkey breed and which far stable handled this run, so the ledger can attribute cost. |
| `choices` | `list[ChatChoice]` | Always one choice in this build | The single filled delivery note returned by the donkey — no n-best alternatives are produced. |
| `usage` | `UsageInfo` | `prompt_tokens`, `completion_tokens`, `total_tokens` | Cargo-unit tally: hay chewed reading the slip plus hay burnt writing the reply, used to price the trip. |
| `cost` | `CostInfo` | `estimated_cost_usd`, `provider`, `model`, `cached` | Line item ready for the expense ledger — provider stable, donkey breed, USD estimate, and a flag if pigeon-hole answered. |
| `cache_hit` | `bool` | `true` when the response came from semantic cache | Tells the courier the pigeon-hole had a pre-written reply and no donkey actually left the stable. |
| `gateway_latency_ms` | `float` | End-to-end gateway processing time | Total milliseconds from front-door arrival to the courier collecting the filled receipt — includes pigeon-hole and donkey time. |

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

| Status | `error` code | When it fires | 🫏 Donkey |
|--------|--------------|---------------|-----------|
| `401` | `authentication_required` | `APIKeyMiddleware` saw no `Authorization: Bearer …` header on a protected path | Courier showed up with no permission slip; gate guard refuses entry before the dispatch desk is even reached. |
| `403` | `forbidden` | Bearer token did not match `master_api_key` (or any configured key) | Slip was wrong colour — the gate guard recognises it as a forgery and turns the courier away at the door. |
| `422` | (FastAPI default) | Pydantic validation on `ChatCompletionRequest` failed (missing `messages`, bad `temperature` range, etc.) | Stable manager inspected the slip, found illegal cargo or wrong field shape, and rejected it before any donkey was harnessed. |
| `429` | `rate_limit_exceeded` | `rate_limiter.check(api_key)` returned `allowed=False` for the current minute window | Courier blew through their trip quota for this minute; dispatcher slams the gate until the window TTL expires. |
| `502` | `llm_provider_error` | `llm_router.chat_completion` raised after primary (and any fallback) provider failed | All registered stables said "no" — every donkey is sick, unreachable, or refused the cargo, and the chain ran out. |

---

## 🫏 Donkey Explainer

This is the **main delivery window** at the front of the dispatch desk. A courier (the API client) walks up with a written delivery slip (the `messages` array). Five things happen, in order, before the courier walks away with a reply:

1. **Gate guard** (`APIKeyMiddleware`) reads the courier's permission slip and either waves them through or sends them home.
2. **Trip-quota counter** (`rate_limiter`) checks the courier's tally board for this minute. One trip too many and the gate stays shut.
3. **Pigeon-hole shelf peek** (`cache`) — the dispatcher rifles through the pre-written reply shelf. If a near-identical slip was answered recently, hand the same note back instantly and write a zero-cost line in the ledger.
4. **Donkey dispatch** (`llm_router`) — pick a donkey from the active stable (AWS, Azure, or local barn). If the chosen donkey is sick and the routing strategy says `fallback`, harness the next one and try again.
5. **Expense ledger entry** (`cost_tracker`) — every trip, cached or live, gets one line: courier id, donkey breed, hay (tokens), USD cost, round-trip time.

The reply slip handed back includes everything the courier paid for — token tally, USD estimate, whether the pigeon-hole answered, and the full wall-clock time the stable took.
