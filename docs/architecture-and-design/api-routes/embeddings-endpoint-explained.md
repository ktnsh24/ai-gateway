# Embeddings Endpoint — Deep Dive

> `POST /v1/embeddings` — turn text into fixed-length vectors via the configured embedding model. Same auth + rate-limit pipeline as completions, but no semantic cache (embeddings are what *builds* the cache).

> **Source file:** `src/routes/embeddings.py`
>
> **Related docs:**
>
> - [API Contract](../api-contract.md) — full schema reference
> - [API Routes Overview](../api-routes-explained.md) — how all 5 routes fit together
> - [Caching Deep Dive](../../ai-engineering/caching-deep-dive.md) — how these embeddings power semantic cache
> - [LiteLLM Deep Dive](../../ai-engineering/litellm-deep-dive.md) — embedding model resolution per provider

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

> This walkthrough explains what really happens when a request hits `POST /v1/embeddings`. Read the [Completions Walkthrough](./completions-endpoint-explained.md#architecture-walkthrough-start-here) first — the startup assembly, middleware layers, and rate limiter are identical. This section covers only what is different about embeddings.

---

### How the app is assembled at startup

The same **Factory Method + Strategy Pattern** runs on startup, building four components on `app.state`:

| Component | Used by embeddings? | Notes |
| --- | --- | --- |
| `router` | Yes | Provides `embedding()` call |
| `cache` | No | Embeddings are what build the cache — caching them would be circular |
| `rate_limiter` | Yes | Same fixed-window counter as completions |
| `cost_tracker` | Yes | Same `usage_logs` write |

If any component fails to assemble and is left as `None` on `app.state`, requests fail at the first access.

> **Courier version.** Same depot setup as for letters — the dispatcher hires the same teams, opens the same notebook, unlocks the same ledger. The only difference: the GPS-coordinate writer does not need the pickup shelf (cache), because the whole point of coordinate-writing is to fill the shelf, not read from it.

---

### The three-layer front desk (middleware)

Identical to completions:

1. **CORSMiddleware** — stamps browser headers, never blocks.
2. **RequestLoggingMiddleware** — mints a 12-char hex request ID, starts a stopwatch, echoes `X-Request-ID` and `X-Gateway-Latency-Ms` in the response.
3. **APIKeyMiddleware** — optional bouncer, same four auth outcomes, same master-key fallback in dev.

See the [Completions Walkthrough](./completions-endpoint-explained.md#architecture-walkthrough-start-here) for the auth outcomes table.

---

### The three-step pipeline

Once past the front desk, the embeddings handler runs only three steps — no cache, no fallback:

```
1. Rate limit → 2. Provider call → 3. Cost log
```

---

#### Step 1 — Rate limit

Same **Fixed-Window Counter** algorithm as completions. Same three implementations (`RedisRateLimiter`, `InMemoryRateLimiter`, `NoRateLimiter`). Same counter key shape: `gw:rate:{api_key}`.

Embedding calls and chat-completion calls share the same per-key bucket. If the limit is 60/minute and 55 chat calls have already run, only 5 embedding calls remain in the window.

The same quota-burn bug applies: the counter increments before the provider call. A failed provider call is not refunded.

| Scenario | Counter | Status |
| --- | --- | --- |
| Under limit | +1 | proceeds to Step 2 |
| At or over limit | +1 | 429 — Steps 2 and 3 skipped |

> **Courier version.** The same notebook, the same page per customer, regardless of whether today's delivery is a letter or a GPS-coordinate job. Both types of job eat from the same tally.

---

#### Step 2 — Provider call

The router calls LiteLLM's `aembedding()` with the input text(s) and the resolved model ID. Here is where embeddings diverge sharply from completions: **there is no fallback path whatsoever**.

The completions handler wraps the LLM call in a try/except with a fallback attempt. The embedding handler has no such wrapper. If the provider's embedding endpoint is unreachable, the exception propagates immediately and the request fails with `502 embedding_provider_error`. There is no "try AWS, then Azure" fallback, even when the router strategy is `FALLBACK`.

**`preferred_provider` gap.** The request schema accepts `preferred_provider`. The router's `_resolve_provider()` method is called internally, so provider selection happens — but because there is no outer fallback chain, a `preferred_provider` value works for selecting the provider but provides no resilience. An unrecognised value logs a warning and uses the configured default.

**`encoding_format` is silently ignored.** The schema accepts `"float"` or `"base64"`. The handler always returns float arrays regardless of which value was sent. There is no validation rejection and no base64 encoding performed.

**Worked example — single-provider call:**

| Field | Value |
| --- | --- |
| Active provider | AWS Bedrock |
| Resolved model ID | `bedrock/amazon.titan-embed-text-v2:0` |
| Input | Two strings sent as a list |
| Result | Two float arrays, each with 1,024 dimensions |
| Fallback attempted | Never — no fallback exists for embeddings |

When a single string is passed as `input`, the handler wraps it in a list before calling LiteLLM, so the response shape is always `data: [...]` — stable regardless of whether one or many strings were sent.

> **Courier version.** The GPS-coordinate writer has only one office it knows how to call. If that office's phone is busy, the whole job fails — there is no backup office number. The completions courier has a second number to try; the GPS-coordinate writer does not.

---

#### Step 3 — Cost log

Same `PostgresCostTracker` write as completions. One row per request in `usage_logs` with:

| Field | Value for embeddings |
| --- | --- |
| `prompt_tokens` | token count of the input(s) |
| `completion_tokens` | always `0` — embeddings generate no prose |
| `cached` | always `False` — no cache exists for embeddings |
| `provider` | whichever provider answered |
| `model` | LiteLLM-format embedding model ID |

The same quiet-trap bug applies. There is no `try/except` around `cost_tracker.log_request()`. If Postgres is down, the embedding call succeeded and the cloud provider charged the account, but the handler raises an uncaught exception and the client receives `500 Internal Server Error`.

> **Courier version.** The same ledger entry, the same clerk with no safety net. The GPS-coordinate job is finished, the depot was billed, and if the ink jar is empty, the customer still gets a "sorry, error" note.

---

### Condition matrix

| Scenario | Rate counter | Provider call | Cost row | Status |
| --- | --- | --- | --- | --- |
| Auth off (anonymous) | shared bucket | yes | yes | 200 |
| Auth on, bad key | — | — | — | 401/403 |
| Rate limit hit | +1 | — | — | 429 |
| Provider call ok | +1 | yes | yes | 200 |
| Provider call fails | +1 (no refund) | yes (failed) | no | 502 |
| Provider ok, cost-log DB down | +1 | yes (paid) | **failed** | 500 |
| `preferred_provider` set in body | +1 | yes (provider selected, no fallback) | yes | 200 |
| `encoding_format: "base64"` set | +1 | yes | yes | 200 (output still float arrays) |

---

### 🩺 Honest health check

1. **No fallback for embeddings.** The completions handler has a full try/fallback chain; the embeddings handler has none. A single provider outage returns `502`. Fix: add the same try/except fallback wrapper used in the completions handler.
2. **`preferred_provider` provides selection but no resilience.** The field is accepted and the provider is selected, but if that provider fails, the request fails — there is no outer fallback. Fix: implement the same fallback chain as completions around the embedding call.
3. **`encoding_format: "base64"` is silently ignored.** Clients expecting base64-encoded vectors receive float arrays with no warning. Fix: implement base64 encoding or return a `422` for unsupported formats.
4. **Failed provider calls still consume rate quota.** The counter increments before the call and there is no rollback on failure. Fix: add rollback on known provider error.
5. **No `try/except` around `cost_tracker.log_request()`.** A Postgres outage causes HTTP 500 after a successful embedding call. Fix: wrap in try/except and return the response regardless.
6. **Embedding dimensionality couples callers to one provider.** Switching providers requires re-embedding the entire corpus and rebuilding the vector index. Not a code bug, but a significant operational risk that deserves a warning when the provider config changes.

---

### TL;DR

- Embeddings are GPS coordinates for the meaning of text: same input always produces the same vector.
- The pipeline is **rate limit → provider call → cost log** — three steps, no cache, no fallback.
- Embedding calls and chat calls **share the same per-key rate-limit bucket**.
- **`preferred_provider`** selects the provider but provides no fallback resilience; **`encoding_format: "base64"`** is silently ignored and always returns float arrays.
- The **quiet-trap cost-log bug** (no try/except around the ledger write) exists here too — a Postgres outage after a successful call returns 500 to the client.
---

## Endpoint Summary

| Attribute | Value | 🚚 Courier |
|-----------|-------|-----------|
| Method | `POST` | Courier hands in fresh text and walks away with a vector receipt; never a cached lookup. |
| Path | `/v1/embeddings` | OpenAI-compatible address so any embedding client (LangChain, LlamaIndex, etc.) talks to this depot unchanged. |
| Auth | Bearer token (when `API_KEYS_ENABLED=true`) | Gate guard checks the same `Authorization: Bearer <key>` header used by every other `/v1` route. |
| Purpose | Convert text(s) into floating-point vectors via the active embedding model | The depot's GPS-coordinate writer — text in, fixed-length coordinates out, ready to be shelved in a vector store. |

---

## Request Schema

Pydantic model: `EmbeddingRequest` (`src/models.py`).

| Field | Type | Required | Default | Description | 🚚 Courier |
|-------|------|----------|---------|-------------|-----------|
| `input` | `str \| list[str]` | ✅ | — | Single text or a batch of texts to embed | The text bundle handed to the GPS-coordinate writer; one string or a stack to encode multiple passages in one call. |
| `model` | `str` | ❌ | `"default"` | Embedding model id; `"default"` uses the configured embed model for the active provider | Selects which coordinate-writer courier to use; `"default"` lets the dispatcher pick the registered embedding model for this depot. |
| `encoding_format` | `str` | ❌ | `"float"` | `"float"` or `"base64"` (parsed but the gateway always returns `float` arrays) | Format the courier prefers; the dispatch desk currently only stamps coordinates as decimal numbers regardless of the request. |

---

## Response Schema

Pydantic model: `EmbeddingResponse`.

| Field | Type | Description | 🚚 Courier |
|-------|------|-------------|-----------|
| `object` | `str` | Always `"list"` | Confirms to the courier the package is a list of vectors, even if only one input was sent in. |
| `data` | `list[EmbeddingData]` | One entry per input, each with `embedding` (list of floats) and `index` | Each rolled-up coordinate scroll, indexed in the same order the texts were handed in for easy re-pairing. |
| `model` | `str` | LiteLLM-format embed model id used | Names exactly which coordinate-writer courier produced the scrolls, e.g. `bedrock/amazon.titan-embed-text-v2:0`. |
| `usage` | `UsageInfo` | `prompt_tokens` and `total_tokens` (no `completion_tokens` for embeddings) | Cargo-unit tally — only input fuel is consumed, since the coordinate-writer doesn't generate prose. |
| `cost` | `CostInfo` | Per-call USD estimate plus provider/model | Expense-ledger line item for the coordinate-writing trip; cached flag is always false here. |
| `gateway_latency_ms` | `float` | End-to-end gateway time | Total gateway-entrance-to-receipt time covering rate-limit check, provider call, and response serialisation. |

---

## Internal Flow

```
client → CORS middleware
       → RequestLoggingMiddleware  (assigns X-Request-ID, starts timer)
       → APIKeyMiddleware          (only if API_KEYS_ENABLED)
       → create_embeddings() handler
            │
            ├─ 1. Pull llm_router, rate_limiter, cost_tracker, settings from app.state
            │
            ├─ 2. Extract Bearer token, fall back to master_api_key for dev calls
            │
            ├─ 3. rate_limiter.check(api_key)
            │     └─ rejected → HTTPException(429)
            │
            ├─ 4. llm_router.embedding(input_text=body.input, model=body.model)
            │     ├─ resolves provider (single/fallback/cost — no round-robin for embed)
            │     ├─ calls LiteLLM embedding() with provider-prefixed model id
            │     └─ raises → HTTPException(502, embedding_provider_error)
            │
            ├─ 5. Build list[EmbeddingData] from response_obj.data, preserving index
            │
            ├─ 6. completion_cost(response_obj) via LiteLLM (best-effort; 0.0 on failure)
            │
            ├─ 7. cost_tracker.log_request(... completion_tokens=0 ...)
            │     writes one row tagged as an embedding call
            │
            └─ 8. Return EmbeddingResponse(data, model, usage, cost, latency_ms)
       ← RequestLoggingMiddleware  (sets X-Gateway-Latency-Ms, logs status)
       ← client
```

There is **no cache step** — embeddings are typically the *input* to a cache, not its output.

---

## Curl Example

```bash
curl -sS http://localhost:8100/v1/embeddings \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $GATEWAY_API_KEY" \
  -d '{
    "model": "default",
    "input": [
      "The capital of France is Paris.",
      "The Eiffel Tower is in Paris."
    ]
  }' | jq '.data[0].embedding | length'
```

The final `jq` pipe prints the embedding dimensionality (e.g. `768` for `nomic-embed-text`, `1024` for Titan v2, `1536` for `text-embedding-3-small`).

---

## Error Cases

| Status | `error` code | When it fires | 🚚 Courier |
|--------|--------------|---------------|-----------|
| `401` | `authentication_required` | Missing or non-Bearer `Authorization` header on protected path | Courier turned up without a permission slip; gate guard refuses entry before the coordinate-writer is even contacted. |
| `403` | `forbidden` | Bearer token does not match a configured key | Permission slip is forged — the gate guard recognises it and sends the courier back without looking at the text bundle. |
| `422` | (FastAPI default) | Pydantic rejected the body (missing `input`, wrong type, etc.) | Gateway inspected the text bundle, found it the wrong shape, and refused to harness any coordinate-writer at all. |
| `429` | `rate_limit_exceeded` | Per-key fixed-window quota hit for the current minute | Courier's daily dispatch quota is used up for this minute; gate stays shut even though the coordinate-writer is idle. |
| `502` | `embedding_provider_error` | LiteLLM `embedding()` raised (provider down, bad model id, network error) | The coordinate-writer's remote depot picked up but returned a broken receipt — no scrolls came back from the provider. |

---

## 🚚 Courier Explainer

The embeddings endpoint is the **GPS-coordinate writer**: hand it text and get back the vector (the GPS coordinates) for each input.

Why no cache here? Because embedding output **is what fills the cache in the first place** — caching the cache-key would be circular. Every request runs the text through fresh.

Auth and rate limiting still run, and every embedding request still gets a line on the cost tab so you can see how much of your monthly budget went to embeddings versus chat completions.
