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
| Method | `GET` | A read-only roster check; the dispatcher just tells the courier which donkeys are on shift, no slip required. |
| Path | `/v1/models` | OpenAI-shaped path so SDKs like the official `openai` Python client list models against this gateway with no patches. |
| Auth | Bearer token (when `API_KEYS_ENABLED=true`) | Even the roster is gated; the gate guard still wants a valid permission slip before showing the staff schedule. |
| Purpose | List the chat + embedding models the configured provider exposes today | The dispatcher's wall roster — every donkey currently on duty and what cargo type they're certified to carry. |

---

## Request Schema

`GET` with no body and no query parameters. The handler signature is just `list_models(request: Request)`.

There is intentionally no filter (provider, capability, etc.) in this build — the response is always the full active roster.

---

## Response Schema

Pydantic model: `ModelListResponse` containing a list of `ModelInfo` entries.

| Field | Type | Description | 🫏 Donkey |
|-------|------|-------------|-----------|
| `object` | `str` | Always `"list"` | Confirms the package is a list — matches the OpenAI client's expectation when iterating models. |
| `data` | `list[ModelInfo]` | One entry per available model | Every donkey on the active roster gets exactly one row, no duplicates across capabilities. |
| `data[].id` | `str` | LiteLLM-format model id (`provider/model`) | Donkey's stable name plus breed — what you would pass to `model=` on a completions or embeddings call. |
| `data[].object` | `str` | Always `"model"` | OpenAI-spec marker that this row describes a model, not a fine-tune or other resource. |
| `data[].created` | `int` | Unix timestamp set at row construction | Roster-print timestamp — when this listing was assembled, not when the donkey was hired. |
| `data[].owned_by` | `str` | `"aws-bedrock"`, `"azure-openai"`, or `"ollama-local"` | Which stable owns the donkey — useful when the courier is choosing between paid and free providers. |
| `data[].provider` | `str` | Cloud provider key: `aws`, `azure`, `local` | Short tag matching `preferred_provider` so the courier can pin a follow-up call to the same stable. |
| `data[].capabilities` | `list[str]` | E.g. `["chat"]` or `["embedding"]` | What cargo type the donkey is licensed to carry — chat replies, vector scrolls, or both. |

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

| Status | `error` code | When it fires | 🫏 Donkey |
|--------|--------------|---------------|-----------|
| `401` | `authentication_required` | `APIKeyMiddleware` saw no Bearer header on a protected path | Courier asked to see the roster without showing a permission slip; gate guard sends them away. |
| `403` | `forbidden` | Bearer token does not match a configured key | Slip was wrong colour — the gate guard refuses to even pull the staff schedule off the wall. |
| `500` | (default) | Unexpected exception inside `list_models()` (e.g. corrupted `_model_map`) | Stable manager dropped the staff schedule; nothing the courier did wrong, but the dispatch desk has to recover. |

(There is no `429` here because the rate limiter is intentionally not invoked on the metadata route.)

---

## 🫏 Donkey Explainer

This is the **roster of available donkeys**. Ask "who's on shift?" and the gateway lists every donkey (model) currently registered, which stable they belong to (AWS, Azure, local Ollama), and what cargo they carry (chat replies vs embeddings).

It is read-only and cheap: no donkey is woken, no cache is opened, and no line is written to the cost tab. It exists so clients — and OpenAI-shaped libraries — can discover what they may ask for before sending a real delivery note to the [completions](completions-endpoint-explained.md) or [embeddings](embeddings-endpoint-explained.md) endpoints.
