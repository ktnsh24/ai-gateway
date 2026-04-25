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
- [Courier Explainer](#courier-explainer)

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
