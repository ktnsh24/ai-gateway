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

> **Read this first if you're new to the gateway.** This explains, in plain English with worked examples, what really happens when someone calls `POST /v1/embeddings`. It assumes you've read (or skimmed) the [Completions Walkthrough](./completions-endpoint-explained.md#plain-english-walkthrough-start-here) — the courier, the front desk, and the boarding-pass concept are the same here. This section just covers what's *different* about embeddings.

### What is an embedding, really?

Imagine you give a courier a sentence — say, *"The capital of France is Paris"* — and ask him to file it on a giant map of meanings. The courier returns with a piece of paper covered in numbers: a list of, say, 1,536 floating-point numbers like `[0.0123, -0.4567, 0.8910, …]`. That list is the embedding. It's the **GPS coordinate of the sentence's meaning** on a high-dimensional map.

Two sentences that mean similar things ("The capital of France is Paris" and "Paris is France's capital") get GPS coordinates that are *close together* on the map. Two unrelated sentences ("The capital of France is Paris" and "Pasta is best with garlic") get coordinates that are *far apart*. That's the whole magic — once your text is a coordinate, similarity becomes geometry.

What are these vectors used for? Three things mostly:

- **Vector stores.** RAG systems shelve documents by their embeddings, then search by computing distances.
- **Semantic cache.** The gateway's own (currently dormant) semantic cache uses embeddings to spot "this question means the same thing as that question".
- **Classification.** Categorise an email as spam by checking which category-vector it's nearest to.

So the embeddings endpoint is the **GPS-coordinate writer**. Text in, coordinates out. No conversation, no creativity, no `temperature` — it's a pure function of the text.

### How the request travels through the gateway

Same front desk as completions: CORS doorman → request logger (boarding pass + stopwatch) → optional API-key bouncer. Once you're inside, the embeddings handler is **simpler than completions**. It has only **three steps**, not five:

```
1. Rate limit  →  2. Provider call  →  3. Cost log
```

There is **no cache step**, neither read nor write. Why? Because embeddings are what *builds* the cache in the first place — caching the cache-key would be circular. Every embedding request runs the text through fresh.

### Step 1 — Rate limit (same notebook, different page entries)

The rate limiter runs exactly the same way as for completions: same notebook, same Redis key shape (`gw:rate:<your-api-key>`), same fixed-window logic. **Important consequence:** embedding calls and chat-completion calls **share the same quota bucket per API key**. If your limit is 60 per minute and you're already up to 55 chat calls this minute, you only have 5 embedding calls left before the gate slams shut.

> **Courier version.** It's the same quota notebook for every kind of delivery. The dispatcher doesn't care if today's slip is a "please write me a poem" letter or a "please put GPS coordinates on this sentence" letter — they all count towards your minute's allowance.

If the limiter says no, you get `429 rate_limit_exceeded` and the request stops here. No provider call, no cost row.

### Step 2 — Provider call (the GPS-coordinate writer)

The router picks a provider and calls LiteLLM's `aembedding()` with the input text(s). And here's where embeddings differ sharply from completions: **there is no fallback path at all**. The completions router has Single, Fallback, Cost-optimised, and Round-robin strategies — embeddings have *only Single*, regardless of what the strategy setting says.

In plain English: if the chosen provider's embedding endpoint is down, the request fails with `502 embedding_provider_error`. There is no "try AWS, then Azure" safety net for embeddings the way there is for chat. This is a known gap — embedding traffic tends to be tolerant of retries (it's idempotent — same input gives the same vector), so adding fallback here would be safe and useful, but the code doesn't do it today.

There's a second quirk worth knowing: the underlying `router.embedding()` method *accepts* a `preferred_provider` argument, but the route handler **never passes one in**. So even though the schema mentions per-request provider override is a gateway feature, **for embeddings specifically, that override is silently ignored**. Whatever provider the gateway is configured with, that's what runs. If you set `preferred_provider: "azure"` in the body, it'll be politely accepted by Pydantic and quietly thrown away.

**Concrete example.** Active provider is AWS Bedrock with `amazon.titan-embed-text-v2:0`. You send:

```json
{
  "model": "default",
  "input": ["The capital of France is Paris.", "The Eiffel Tower is in Paris."]
}
```

The gateway:

1. Picks AWS Bedrock (the configured single provider for embeddings).
2. Resolves `"default"` to `bedrock/amazon.titan-embed-text-v2:0`.
3. Sends both strings to Bedrock in one batch call.
4. Gets back two 1,024-dimensional float arrays (Titan v2's dimensionality).
5. Pairs them with their input indexes (`index: 0` and `index: 1`) so the caller knows which vector belongs to which sentence.

If you sent a single string instead of a list, the gateway wraps it in a list before calling LiteLLM, so the response shape is always `data: [...]` — even with one entry. Stable shape, easier client code.

### Step 3 — Cost log

Same ledger as completions. The handler asks LiteLLM to estimate the dollar cost, then writes one row to `usage_logs` with:

- `prompt_tokens` = the tokens in your input(s).
- `completion_tokens` = **always 0** (embeddings don't generate prose, so there's no completion).
- `provider` = whichever provider answered.
- `model` = the actual embedding model id (e.g. `bedrock/amazon.titan-embed-text-v2:0`).
- `cached` = always **false** for embeddings (there's no cache, so it can never be cached).

The same trap from the completions endpoint applies: **no `try/except` around the cost-log write**. If PostgreSQL is unreachable, the embedding call has already succeeded and the vectors are in memory — but the failed insert raises out of the handler and the user gets a `500 Internal Server Error`. They've been billed by the embedding provider and don't see their vectors.

### What goes back to the caller

A successful response looks like this (shortened — real vectors are hundreds of floats):

```jsonc
{
  "object": "list",
  "data": [
    { "embedding": [0.0123, -0.4567, 0.8910, /* … 1021 more numbers … */], "index": 0 },
    { "embedding": [0.1011, -0.1213, 0.1415, /* … 1021 more numbers … */], "index": 1 }
  ],
  "model": "bedrock/amazon.titan-embed-text-v2:0",
  "usage": { "prompt_tokens": 18, "total_tokens": 18 },
  "cost": { "estimated_cost_usd": 0.0000036, "provider": "aws", "model": "...", "cached": false },
  "gateway_latency_ms": 142.3
}
```

Notice what's *missing* compared to the completions response: there's no `cache_hit` field (because there's no cache), no `choices` block (because there's no generated text). The dimensionality of each `embedding` array depends on the model — for example:

| Model | Provider | Dimensionality |
| --- | --- | --- |
| `nomic-embed-text` | Local (Ollama) | 768 |
| `amazon.titan-embed-text-v2:0` | AWS Bedrock | 1,024 |
| `text-embedding-3-small` | Azure OpenAI | 1,536 |
| `text-embedding-3-large` | Azure OpenAI | 3,072 |

If you switch providers, **your existing vector store breaks**. A 1,536-dim vector and a 1,024-dim vector can't be compared at all — the math doesn't work. So if you re-embed a corpus with a different provider, you have to re-embed *everything* and rebuild the index. This isn't a gateway bug, it's just how embeddings work — but it's worth knowing because the gateway's "swap provider with one config flag" superpower has this asterisk attached for embedding traffic specifically.

### A small parsing curiosity

The request schema accepts `encoding_format: "float" | "base64"`. The Pydantic model parses both. **The handler ignores it — output is always a `float` array regardless.** If a client passes `"base64"` expecting compact base64-encoded vectors, they'll just receive the regular float arrays. Another small honesty gap between the schema and the implementation.

### The whole condition matrix in one table

| Scenario | Rate counter | Provider call | Cost row | Status |
| --- | --- | --- | --- | --- |
| Auth off (anonymous) | shared bucket | yes | yes | 200 |
| Auth on, bad key | — | — | — | 401/403 |
| Rate limit hit | +1 | — | — | 429 |
| Provider call ok | +1 | yes | yes | 200 |
| Provider call fails | +1 (no refund) | yes (failed) | no | 502 |
| Provider ok, cost-log DB down | +1 | yes (paid) | **failed** | 500 |
| `preferred_provider` set in body | +1 | yes (silently ignored — uses configured provider) | yes | 200 |
| `encoding_format: "base64"` set | +1 | yes | yes (output still `float` regardless) | 200 |

### The honest health check

These are the rough edges specific to the embeddings endpoint:

1. **No fallback whatsoever.** Even if the gateway is configured with the Fallback strategy, embeddings don't honour it. A single provider outage = a `502`. Cheap fix, not yet implemented.
2. **`preferred_provider` is silently ignored.** The router supports it but the route handler doesn't pass it through. Fixing this is a one-line change.
3. **`encoding_format: "base64"` is silently ignored.** Output is always `float`. Either implement base64 encoding or reject the field at validation time.
4. **Failed embedding calls still consume rate quota.** Same as completions — flaky provider eats your minute's allowance.
5. **Cost-log failures cause user-visible 500s.** Same trap as completions — no `try/except` around the ledger insert.
6. **Embedding dimensionality couples you to one provider.** Not a bug, but worth a heads-up: switching providers means re-embedding your whole corpus.

### TL;DR

- Embeddings are GPS coordinates for the meaning of text. Same input → same vector, every time.
- The pipeline is **rate limit → provider call → cost log**. No cache, no fallback, three steps total.
- Embedding calls and chat calls **share the same per-API-key rate-limit bucket**.
- A few documented features (per-request provider override, base64 encoding) are silently no-ops today.
- Cost-log database going down still breaks user requests — same shared trap as completions.

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
