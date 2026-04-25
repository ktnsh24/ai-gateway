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
