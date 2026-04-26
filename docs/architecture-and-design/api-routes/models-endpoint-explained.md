# Models Endpoint — Deep Dive

> `GET /v1/models` — list every model the gateway can route to right now, in OpenAI-compatible format. Read-only, cheap, no LLM call.

> **Source file:** `src/routes/models.py`
>
> **Related docs:**
>
> - [API Contract](../api-contract.md) — full schema reference
> - [API Routes Overview](../api-routes-explained.md) — how all 5 routes fit together
> - [LiteLLM Deep Dive](../../ai-engineering/litellm-deep-dive.md) — where the model map comes from

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

> **Read this first if you're new to the gateway.** Same courier analogy as the [Completions Walkthrough](./completions-endpoint-explained.md#plain-english-walkthrough-start-here). This section just explains what's specific about the models endpoint.

### What is this endpoint for?

When a client wants to know "what models can I use through this gateway?", it asks `GET /v1/models`. The reply is a list of model identifiers grouped by provider — exactly the same shape OpenAI's API returns, so any OpenAI-compatible client (LangChain, the Python `openai` SDK, llama-index, etc.) can use this gateway as a drop-in replacement and discover models the same way.

> **Courier version.** This is the **roster pinned to the dispatcher's wall**. A courier walks up and asks "who's on shift today and what kind of deliveries can they handle?". The dispatcher reads back the wall.

### How it works

This is the simplest endpoint in the gateway. There's no pipeline, no rate limit, no cost log, no LLM call — just a synchronous in-memory read. The handler asks the router for its list of models and returns the result. Round trip is typically under 5 milliseconds.

The model list is **not fetched live from the providers**. It's hardcoded inside the router based on which providers are configured in the gateway's environment. So if AWS Bedrock has a temporary outage, this endpoint still returns the AWS model entry — the response reflects "what we *can* talk to", not "what's actually responding right now". For real liveness, use `/health`.

### What you get back

A response like this (shortened):

```jsonc
{
  "object": "list",
  "data": [
    { "id": "bedrock/anthropic.claude-3-sonnet", "owned_by": "anthropic", "provider": "aws",   "capabilities": ["chat", "completions"] },
    { "id": "bedrock/amazon.titan-embed-text-v2:0", "owned_by": "amazon", "provider": "aws",   "capabilities": ["embeddings"] },
    { "id": "azure/gpt-4",                          "owned_by": "openai", "provider": "azure", "capabilities": ["chat", "completions"] },
    { "id": "ollama/llama3",                        "owned_by": "meta",   "provider": "local", "capabilities": ["chat", "completions"] }
  ]
}
```

The `capabilities` field is **hardcoded by provider**: chat models get `["chat", "completions"]`, embedding models get `["embeddings"]`. There's no probing, no introspection — the list is what the router was wired to know about at startup.

### Quirks worth knowing

1. **Always returns 200, even if every provider is down.** The endpoint never calls the providers. So a green response here doesn't mean models actually work — it means they're configured.
2. **No filtering.** You can't ask "show me only chat models" or "only AWS models" — the client has to filter the array itself.
3. **No auth in the typical setup.** `/v1/models` is *not* in the `PUBLIC_PATHS` set, so when API keys are turned on it does require a Bearer token. Worth knowing if you wonder why your client gets 401 in dev-with-auth-on.
4. **Adding a new model means a code change.** The model map lives inside the router, not in config. So onboarding a new Bedrock model is a code edit + redeploy, not a config update.

### TL;DR

- "Roster on the wall" — read-only list of configured models, grouped by provider.
- No live probing, no rate limit, no cost. Sub-5ms response time.
- Returns 200 even if providers are unreachable (use `/health` for liveness).
- Hardcoded capability tags; no filter parameters; new models require a code change.

---

## Endpoint Summary

| Attribute | Value | 🚚 Courier |
|-----------|-------|-----------|
| Method | `GET` | A read-only roster check; the dispatcher just tells the courier which couriers are on shift, no slip required. |
| Path | `/v1/models` | OpenAI-shaped path so SDKs like the official `openai` Python client list models against this gateway with no patches. |
| Auth | Bearer token (when `API_KEYS_ENABLED=true`) | Even the roster is gated; the gate guard still wants a valid permission slip before showing the staff schedule. |
| Purpose | List the chat + embedding models the configured provider exposes today | The dispatcher's wall roster — every courier currently on duty and what parcel type they're certified to carry. |

---

## Request Schema

`GET` with no body and no query parameters. The handler signature is just `list_models(request: Request)`.

There is intentionally no filter (provider, capability, etc.) in this build — the response is always the full active roster.

---

## Response Schema

Pydantic model: `ModelListResponse` containing a list of `ModelInfo` entries.

| Field | Type | Description | 🚚 Courier |
|-------|------|-------------|-----------|
| `object` | `str` | Always `"list"` | Confirms the package is a list — matches the OpenAI client's expectation when iterating models. |
| `data` | `list[ModelInfo]` | One entry per available model | Every courier on the active roster gets exactly one row, no duplicates across capabilities. |
| `data[].id` | `str` | LiteLLM-format model id (`provider/model`) | Courier's depot name plus breed — what you would pass to `model=` on a completions or embeddings call. |
| `data[].object` | `str` | Always `"model"` | OpenAI-spec marker that this row describes a model, not a fine-tune or other resource. |
| `data[].created` | `int` | Unix timestamp set at row construction | Roster-print timestamp — when this listing was assembled, not when the courier was hired. |
| `data[].owned_by` | `str` | `"aws-bedrock"`, `"azure-openai"`, or `"ollama-local"` | Which depot owns the courier — useful when the courier is choosing between paid and free providers. |
| `data[].provider` | `str` | Cloud provider key: `aws`, `azure`, `local` | Short tag matching `preferred_provider` so the courier can pin a follow-up call to the same depot. |
| `data[].capabilities` | `list[str]` | E.g. `["chat"]` or `["embedding"]` | What parcel type the courier is licensed to carry — chat replies, vector scrolls, or both. |

The actual rows come from `LiteLLMRouter.list_models()`, which iterates the internal `_model_map` for the configured provider (single mode) or all known providers (fallback / round-robin / cost modes).

---

## Internal Flow

```
client → CORS middleware
       → RequestLoggingMiddleware  (assigns X-Request-ID, starts timer)
       → APIKeyMiddleware          (only if API_KEYS_ENABLED)
       → list_models() handler
            │
            ├─ 1. Pull llm_router from app.state
            │
            ├─ 2. raw_models = llm_router.list_models()
            │     ├─ reads self._model_map for the active provider
            │     ├─ emits one dict per (provider, model_type) combination
            │     │   with id, owned_by, provider, capabilities
            │     └─ no network call — pure in-memory enumeration
            │
            ├─ 3. Map each dict to ModelInfo(id=..., owned_by=...,
            │                                provider=..., capabilities=...)
            │
            └─ 4. Return ModelListResponse(data=models)
       ← RequestLoggingMiddleware  (sets X-Gateway-Latency-Ms, logs status)
       ← client
```

No rate limiter, no cache, no cost tracker — this route is pure metadata. Latency is normally a few milliseconds.

---

## Curl Example

```bash
curl -sS http://localhost:8100/v1/models \
  -H "Authorization: Bearer $GATEWAY_API_KEY" | jq '.data[] | {id, provider, capabilities}'
```

Sample output for a `local` provider deployment:

```json
{ "id": "ollama/llama3.2",         "provider": "local", "capabilities": ["chat"] }
{ "id": "ollama/nomic-embed-text", "provider": "local", "capabilities": ["embedding"] }
```

---

## Error Cases

| Status | `error` code | When it fires | 🚚 Courier |
|--------|--------------|---------------|-----------|
| `401` | `authentication_required` | `APIKeyMiddleware` saw no Bearer header on a protected path | Courier asked to see the roster without showing a permission slip; gate guard sends them away. |
| `403` | `forbidden` | Bearer token does not match a configured key | Slip was wrong colour — the gate guard refuses to even pull the staff schedule off the wall. |
| `500` | (default) | Unexpected exception inside `list_models()` (e.g. corrupted `_model_map`) | Gateway dropped the staff schedule; nothing the courier did wrong, but the dispatch desk has to recover. |

(There is no `429` here because the rate limiter is intentionally not invoked on the metadata route.)

---

## 🚚 Courier Explainer

This is the **roster of available couriers**. Ask "who's on shift?" and the gateway lists every courier (model) currently registered, which depot they belong to (AWS, Azure, local Ollama), and what parcel they carry (chat replies vs embeddings).

It is read-only and cheap: no courier is woken, no cache is opened, and no line is written to the cost tab. It exists so clients — and OpenAI-shaped libraries — can discover what they may ask for before sending a real shipping manifest to the [completions](completions-endpoint-explained.md) or [embeddings](embeddings-endpoint-explained.md) endpoints.
