# Health Endpoint — Deep Dive

> `GET /health` — single liveness + readiness probe. Reports gateway version, active provider, Redis connectivity, PostgreSQL connectivity, LangFuse flag, and the available model list.

> **Source file:** `src/routes/health.py`
>
> **Related docs:**
>
> - [API Contract](../api-contract.md) — full schema reference
> - [API Routes Overview](../api-routes-explained.md) — how all 5 routes fit together
> - [Observability Deep Dive](../../ai-engineering/observability-deep-dive.md) — request IDs, structured logging, latency

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
| Method | `GET` | A passive check on the dispatcher; the courier never hands in a slip, just looks at the lights. |
| Path | `/health` | Bare path, no `/v1` prefix, so platform probes (ECS, Container Apps, k8s) hit it without rewrites. |
| Auth | **None** — listed in `PUBLIC_PATHS` in `APIKeyMiddleware` | Front porch light is always on for monitoring tools; gate guard waves the probe through every time. |
| Purpose | Combined liveness + readiness: gateway up, Redis reachable, PostgreSQL reachable, model list resolvable | "Is the donkey awake?" check plus a peek at the pigeon-hole shelf and the ledger book to confirm both are within reach. |

> Note: there is currently a single `/health` route; no separate `/healthz` or `/readyz` paths are defined. The signal is a unified one.

---

## Request Schema

`GET` with no body, no query parameters, and (deliberately) no auth header required. The handler signature is `health_check(request: Request)`.

---

## Response Schema

Pydantic model: `HealthStatus` (`src/models.py`).

| Field | Type | Description | 🫏 Donkey |
|-------|------|-------------|-----------|
| `status` | `str` | Always `"healthy"` if the route returned (route never throws — failures are reported per-component) | Light on the dispatcher's desk: green means the dispatch desk itself is responsive, regardless of downstream. |
| `version` | `str` | Hard-coded `"0.1.0"` for this build | The dispatch-desk model number on the brass plate above the door — useful for confirming a deploy landed. |
| `provider` | `str` | Active `cloud_provider` (`aws` / `azure` / `local`) | Which stable the dispatcher is pointed at right now — the default depot for any donkey trip. |
| `redis_connected` | `bool` | `True` when `cache.stats()` reports `enabled=True` | Pigeon-hole shelf reachable — false means semantic cache is degraded to no-cache fallback. |
| `database_connected` | `bool` | `True` when `cost_tracker.get_usage_summary()` succeeds | Expense ledger reachable — false means cost rows are buffering in memory and may be lost on restart. |
| `langfuse_connected` | `bool` | Mirrors `settings.langfuse_enabled` (config flag, not a live probe) | Flag-only check that the optional LLM CCTV is wired in; does not actually ping LangFuse. |
| `models_available` | `list[str]` | LiteLLM model ids from `router.list_models()` | The roster the dispatcher would read to a courier hitting `/v1/models` right now. |

---

## Internal Flow

```
client → CORS middleware
       → RequestLoggingMiddleware  (assigns X-Request-ID, starts timer)
       → APIKeyMiddleware  → /health is in PUBLIC_PATHS → passes through unchecked
       → health_check() handler
            │
            ├─ 1. Pull settings, router_instance from app.state
            │
            ├─ 2. Probe Redis
            │     ├─ cache.stats() succeeds and reports enabled=True → redis_ok = True
            │     └─ exception or NoCache(enabled=False)             → redis_ok = False
            │
            ├─ 3. Probe PostgreSQL
            │     ├─ cost_tracker.get_usage_summary(period="today") succeeds → db_ok = True
            │     └─ exception                                                → db_ok = False
            │
            ├─ 4. Build models = [m["id"] for m in router_instance.list_models()]
            │
            └─ 5. Return HealthStatus(status="healthy", version, provider,
                                       redis_connected, database_connected,
                                       langfuse_connected, models_available)
       ← RequestLoggingMiddleware  (sets X-Gateway-Latency-Ms, logs status)
       ← client
```

The probes for Redis and PostgreSQL each swallow exceptions and report `False` — the route itself does not 5xx on a downstream outage, it just flips the relevant boolean.

---

## Curl Example

```bash
curl -sS http://localhost:8100/health | jq
```

Sample healthy response with the local Ollama provider and Docker Compose Redis + Postgres up:

```json
{
  "status": "healthy",
  "version": "0.1.0",
  "provider": "local",
  "redis_connected": true,
  "database_connected": true,
  "langfuse_connected": false,
  "models_available": ["ollama/llama3.2", "ollama/nomic-embed-text"]
}
```

A monitoring tool should treat the call as successful only if **all** of `status == "healthy"`, `redis_connected`, and `database_connected` are true. (LangFuse is optional and should not gate liveness.)

---

## Error Cases

| Status | `error` code | When it fires | 🫏 Donkey |
|--------|--------------|---------------|-----------|
| `200` | (none) | Always returned when the route runs end-to-end, even if probes flipped flags to `false` | Dispatcher answers the doorbell; some lights inside may be red but the front desk itself is still responsive. |
| `500` | (default) | Only on truly unexpected errors (e.g. `app.state` missing, framework-level failure) | Dispatcher slumped over the desk — not a downstream outage but the dispatch desk itself has crashed mid-probe. |

There is no `401` / `403` / `429` — the route bypasses the API-key middleware and is not rate-limited.

---

## 🫏 Donkey Explainer

The health route is the stable's "open for business" sign — a quick light-on/light-off check that load balancers, ECS health checks, and monitoring probes can hit without a key, without rate limiting, and without writing a cost line. It reports four things:

1. **Lights on?** — the gateway is responding, with version + active stable noted.
2. **Cache reachable?** — quick `cache.stats()` poke. Red if Redis is down; semantic cache then degrades to a no-cache pass-through.
3. **Cost tab reachable?** — a tiny `get_usage_summary` query. Red if PostgreSQL is down; new cost rows buffer in memory and risk loss on restart.
4. **Roster readable?** — the active donkey models so monitoring sees which would answer if a real call came in.

Because the route is intentionally tolerant (it never 5xxs on a downstream blip), monitoring should treat any one of `status != healthy`, `redis_connected = false`, or `database_connected = false` as a degraded signal worth waking a human for.
