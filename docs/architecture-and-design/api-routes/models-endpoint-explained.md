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

> This walkthrough explains what really happens when a request hits `GET /v1/models`. It is the simplest endpoint in the gateway — an in-memory read with no LLM call, no cache, and no cost log.

---

### How the app is assembled at startup

The **Factory Method** builds the `router` component on `app.state` using `create_router(settings)`. For now there is only one concrete implementation: `LiteLLMRouter`. During its own initialisation, the router builds `self._model_map` — a hardcoded dict keyed by provider, constructed entirely from settings values (model names, deployment names) read at startup time.

No live provider probing happens at this point. The map reflects what the gateway is configured to talk to, not what is currently reachable.

> **Courier version.** The roster is printed at depot opening time from the staffing file. If AWS has been removed from the file since last restart, the roster will not show AWS. If AWS is listed but their office burned down, the roster still shows AWS. The roster is a copy of the config, not a window onto the real world.

---

#### Step 1 — Auth check

`/v1/models` is not in `PUBLIC_PATHS`. When `auth_enabled=True`, the `APIKeyMiddleware` bouncer requires a valid `Authorization: Bearer <key>` header before the handler runs. Unlike `/health` and `/docs`, there is no bypass for this endpoint.

| Condition | Result |
| --- | --- |
| Auth disabled (default dev mode) | Handler runs unconditionally |
| Auth enabled, valid key | Handler runs |
| Auth enabled, missing or invalid key | 401 / 403 — handler never reached |

> **Courier version.** The staff roster is not posted on the outside wall — you need to show your pass to get inside and read it. The health light, by contrast, is visible from the street with no pass required.

---

#### Step 2 — `list_models()` call

The handler calls `router.list_models()`, which iterates `self._model_map` and emits one entry per (provider, model-type) combination. The call is pure in-memory — no network request, no database query, typical latency under 5 ms.

The model map is hardcoded at startup. The entries for AWS, Azure, and Local are all present regardless of whether those providers are currently reachable. There is no live probe; the response reflects the startup configuration, not current provider health.

**Worked example — what the map contains:**

| Provider | Chat model entry | Embedding model entry |
| --- | --- | --- |
| AWS Bedrock | `bedrock/anthropic.claude-3-sonnet` | `bedrock/amazon.titan-embed-text-v2:0` |
| Azure OpenAI | `azure/gpt-4` | `azure/text-embedding-3-small` |
| Local Ollama | `ollama/llama3` | `ollama/nomic-embed-text` |

The `capabilities` field is hardcoded by model type: chat models get `["chat", "completions"]`, embedding models get `["embeddings"]`. No introspection or probing determines this — it is declared in the router's init code.

> **Courier version.** The dispatcher reads the printed roster back to the customer. It lists every courier hired when the depot opened — whether they showed up for work today or not. The dispatcher does not check whether any of them are currently at their desk.

---

### Condition matrix

| Scenario | Auth check | `list_models()` | Status |
| --- | --- | --- | --- |
| Auth disabled | skipped | in-memory read | 200 |
| Auth enabled, valid key | passes | in-memory read | 200 |
| Auth enabled, missing key | 401 | — | 401 |
| Auth enabled, invalid key | 403 | — | 403 |
| All providers unreachable | passes | in-memory read (still returns all entries) | 200 |
| New model added to provider without restart | passes | in-memory read (not yet visible) | 200 (stale list) |

---

### 🩺 Honest health check

1. **Always returns HTTP 200 even if all providers are unreachable.** The endpoint never calls providers; a green response here means "configured", not "working". Fix: add an optional live-probe flag, or document explicitly that `/health` is the liveness check.
2. **Hardcoded list reflects startup config, not live state.** If a provider becomes unavailable after startup, the model list still includes its models. Fix: build the model map from a config file that can be hot-reloaded, or add a live-probe variant.
3. **No auth bypass — unlike `/health`, this endpoint requires auth when enabled.** Engineers expecting model discovery to be free-access will receive 401s in auth-on environments. Fix: document this clearly, or add `/v1/models` to `PUBLIC_PATHS` if model discovery should be public.
4. **Adding a new model requires a code change and redeploy.** The map lives inside the router's `__init__`, not in a config file. Fix: move the model map to a config file or environment variable.

---

### TL;DR

- **Factory Method** builds the router once at startup; `list_models()` reads a hardcoded in-memory dict — no network call, no live probe, sub-5ms latency.
- **Always returns HTTP 200** regardless of whether providers are reachable; use `/health` for liveness signals.
- **Requires auth** when auth is enabled — unlike `/health`, it is not a public path.
- The model map is a **snapshot of settings at startup time**, not a live view of what is currently responding.
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
