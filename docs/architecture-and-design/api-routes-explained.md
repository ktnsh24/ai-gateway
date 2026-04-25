# API Routes — Index

> A 1-page index to every HTTP route the AI Gateway exposes. Click through to the per-endpoint deep dive for request/response schemas, internal flow, curl examples, and error tables.

> **Related docs:**
>
> - [API Contract](api-contract.md) — full schema reference in one document
> - [Architecture Overview](architecture.md) — how the routes sit inside the stable
> - [Pydantic Models Reference](../reference/pydantic-models.md) — exact field-level types

---

## All Routes at a Glance

| Method | Path | Auth | Purpose | Deep dive | 🫏 Donkey |
|--------|------|------|---------|-----------|-----------|
| `POST` | `/v1/chat/completions` | Bearer | Run a chat completion through cache → LLM → ledger | [completions-endpoint-explained.md](api-routes/completions-endpoint-explained.md) | The main delivery window — slip in, donkey trip if the pigeon-hole misses, line written in the expense ledger. |
| `POST` | `/v1/embeddings` | Bearer | Convert text into fixed-length vectors | [embeddings-endpoint-explained.md](api-routes/embeddings-endpoint-explained.md) | The GPS-coordinate writer — text in, scrolls of numbers out, ready for the warehouse shelf. |
| `GET` | `/v1/models` | Bearer | List the chat + embedding models on duty | [models-endpoint-explained.md](api-routes/models-endpoint-explained.md) | The roster pinned to the dispatcher's wall — every donkey on shift and what cargo they carry. |
| `GET` | `/v1/usage` | Bearer | Read the per-key cost & request rollups | [usage-endpoint-explained.md](api-routes/usage-endpoint-explained.md) | The expense-ledger reading window — open today, this week, or this month and tally the courier's tab. |
| `GET` | `/health` | **None** (public) | Combined liveness + readiness probe | [health-endpoint-explained.md](api-routes/health-endpoint-explained.md) | The front-porch lamp — watchman glances at it without knocking, sees the lights on the dispatch desk, pigeon-hole, and ledger. |

> Auth column reflects behaviour when `API_KEYS_ENABLED=true`. With auth disabled (the dev default), the gateway accepts unauthenticated calls on every `/v1/*` route and treats them as the master API key for cost-tracking purposes.

---

## Wiring

Routes are mounted in `src/main.py` via `app.include_router(...)` for each module under `src/routes/`. The order is `health → completions → embeddings → models → usage`. Two middlewares run on every request:

1. `RequestLoggingMiddleware` — assigns `X-Request-ID`, starts a wall-clock timer, attaches the `X-Gateway-Latency-Ms` header on the way out.
2. `APIKeyMiddleware` — only when `API_KEYS_ENABLED=true`; checks `Authorization: Bearer …` against the configured key set, with `/health`, `/docs`, `/redoc`, `/openapi.json` whitelisted.

Each route handler then pulls the gateway components it needs (`router`, `cache`, `rate_limiter`, `cost_tracker`) directly from `request.app.state`, which the lifespan hook in `src/main.py` populated at startup. There is no dependency-injection framework — the gateway uses FastAPI's built-in `app.state` pattern.

- 🫏 **Donkey:** Two checks run on every delivery note before any window opens it (timing and API-key auth); each window then reaches into the same shared shelf of gateway tools to do its job.

---

## Where to Read Next

- For OpenAI-compatibility schema details across all routes in one place → [API Contract](api-contract.md).
- For the gateway's internal pipeline (auth → rate limit → cache → LLM → cost) → [Architecture Overview](architecture.md).
- For per-request observability fields (`X-Request-ID`, `X-Gateway-Latency-Ms`, `cache_hit`, `cost`) → [Observability Deep Dive](../ai-engineering/observability-deep-dive.md).
