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

> **Read this first if you're new to the gateway.** Same courier analogy as the [Completions Walkthrough](./completions-endpoint-explained.md#plain-english-walkthrough-start-here). This explains what's specific about the health endpoint.

### What is this endpoint for?

`GET /health` is the **"is the courier office open?"** check. Load balancers, Kubernetes liveness probes, and Docker healthchecks all hit this endpoint to decide whether the gateway is alive and able to serve traffic. It's also the easiest debugging tool — one curl tells you whether Redis and PostgreSQL are reachable from the gateway's pod.

> **Courier version.** This is the **porch lamp** at the depot, plus a quick wave through the back rooms: "Is the dispatcher at her desk? Are the pickup lockers powered on? Is the leather ledger book where it should be?" The reply is a single status card.

### How it works

There's no rate limit, no auth (it's in `PUBLIC_PATHS`), no logging beyond the standard request log, and no LLM call. The handler runs **four checks in sequence**:

1. **Redis check.** It calls the cache's `stats()` method. If the cache is the no-op variant (caching disabled), it reports `enabled: false`, which the handler takes as "Redis check failed". Otherwise a successful `stats()` call means Redis answered.
2. **PostgreSQL check.** It calls `cost_tracker.get_usage_summary(period="today")` and considers the database healthy if that call doesn't raise. **This is heavier than you'd expect** — it actually runs three SQL queries against `usage_logs` (total, by-model, by-provider). So a slow Postgres slows down `/health` proportionally.
3. **Langfuse flag.** This is **not a real connectivity check** — it just reads the `langfuse_enabled` config flag and reports its value. Setting `LANGFUSE_ENABLED=true` will make this report `true` even if Langfuse itself is unreachable.
4. **Models list.** It pulls the list of configured model IDs from the router (no probing — same hardcoded list as `/v1/models`).

### The big honest gotcha

Look carefully at the response shape:

```jsonc
{
  "status": "healthy",       // ← always "healthy", regardless of the checks below
  "version": "0.1.0",
  "provider": "aws",
  "redis_connected": false,  // ← can be false
  "database_connected": false, // ← can be false
  "langfuse_connected": true,  // ← reflects config, not connectivity
  "models_available": ["bedrock/anthropic.claude-3-sonnet", ...]
}
```

The top-level `status` field is **hardcoded to `"healthy"`**. It does not aggregate the connectivity flags below. So if Redis is down and Postgres is down, the response still says `status: "healthy"` and your load balancer thinks everything is fine. This is a real bug — not a stylistic choice. If you're using `/health` for liveness, you should configure your probe to also assert `redis_connected == true` and `database_connected == true`, not just `status == "healthy"`.

### A worked example

You hit `/health` while Redis is unreachable but Postgres is fine:

```jsonc
{
  "status": "healthy",
  "version": "0.1.0",
  "provider": "aws",
  "redis_connected": false,    // ← real signal
  "database_connected": true,
  "langfuse_connected": false,
  "models_available": [...]
}
```

A naive Kubernetes probe checking `status == "healthy"` keeps the pod in rotation even though caching and rate limiting are silently degrading to in-memory and producing inconsistent behaviour across replicas.

### Quirks worth knowing

1. **`status` is always `"healthy"`** regardless of the checks below it. Use the boolean flags, not the status string.
2. **The DB check runs three SQL queries** (it reuses `get_usage_summary`). On a large `usage_logs` table without indexes, `/health` itself can become slow.
3. **Langfuse "connected" really means "configured"** — no actual ping is made.
4. **Returns 200 even when checks fail.** The endpoint never returns a non-200 code. So orchestrators that interpret a 5xx as "unhealthy" will never see it from this endpoint.
5. **No version of "starting up" vs "ready"** — only one status. If the LLM router is still warming on first call, `/health` already says healthy.
6. **No auth** — the endpoint is publicly reachable. That's standard for liveness probes but means anyone hitting your gateway URL can read the model list and the connectivity state of your backends.

### TL;DR

- One endpoint, four checks (Redis, Postgres, Langfuse-flag, models list), no auth, no rate limit.
- Top-level `status` is **hardcoded `"healthy"`** — don't trust it; check the boolean flags instead.
- The Postgres check is heavy (three SQL queries) — be mindful on large `usage_logs` tables.
- Always returns 200, even on failure — load balancers expecting non-2xx for unhealthy won't trigger.

---

## Endpoint Summary

| Attribute | Value | 🚚 Courier |
|-----------|-------|-----------|
| Method | `GET` | A passive check on the dispatcher; the courier never hands in a slip, just looks at the lights. |
| Path | `/health` | Bare path, no `/v1` prefix, so platform probes (ECS, Container Apps, k8s) hit it without rewrites. |
| Auth | **None** — listed in `PUBLIC_PATHS` in `APIKeyMiddleware` | Front porch light is always on for monitoring tools; gate guard waves the probe through every time. |
| Purpose | Combined liveness + readiness: gateway up, Redis reachable, PostgreSQL reachable, model list resolvable | "Is the courier awake?" check plus a peek at the pickup locker shelf and the ledger book to confirm both are within reach. |

> Note: there is currently a single `/health` route; no separate `/healthz` or `/readyz` paths are defined. The signal is a unified one.

---

## Request Schema

`GET` with no body, no query parameters, and (deliberately) no auth header required. The handler signature is `health_check(request: Request)`.

---

## Response Schema

Pydantic model: `HealthStatus` (`src/models.py`).

| Field | Type | Description | 🚚 Courier |
|-------|------|-------------|-----------|
| `status` | `str` | Always `"healthy"` if the route returned (route never throws — failures are reported per-component) | Light on the dispatcher's desk: green means the dispatch desk itself is responsive, regardless of downstream. |
| `version` | `str` | Hard-coded `"0.1.0"` for this build | The dispatch-desk model number on the brass plate above the door — useful for confirming a deploy landed. |
| `provider` | `str` | Active `cloud_provider` (`aws` / `azure` / `local`) | Which depot the dispatcher is pointed at right now — the default depot for any delivery. |
| `redis_connected` | `bool` | `True` when `cache.stats()` reports `enabled=True` | Pickup locker shelf reachable — false means semantic cache is degraded to no-cache fallback. |
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

| Status | `error` code | When it fires | 🚚 Courier |
|--------|--------------|---------------|-----------|
| `200` | (none) | Always returned when the route runs end-to-end, even if probes flipped flags to `false` | Dispatcher answers the doorbell; some lights inside may be red but the front desk itself is still responsive. |
| `500` | (default) | Only on truly unexpected errors (e.g. `app.state` missing, framework-level failure) | Dispatcher slumped over the desk — not a downstream outage but the dispatch desk itself has crashed mid-probe. |

There is no `401` / `403` / `429` — the route bypasses the API-key middleware and is not rate-limited.

---

## 🚚 Courier Explainer

The health route is the gateway's "open for business" sign — a quick light-on/light-off check that load balancers, ECS health checks, and monitoring probes can hit without a key, without rate limiting, and without writing a cost line. It reports four things:

1. **Lights on?** — the gateway is responding, with version + active provider noted.
2. **Cache reachable?** — quick `cache.stats()` poke. Red if Redis is down; semantic cache then degrades to a no-cache pass-through.
3. **Cost tab reachable?** — a tiny `get_usage_summary` query. Red if PostgreSQL is down; new cost rows buffer in memory and risk loss on restart.
4. **Roster readable?** — the active models so monitoring sees which would answer if a real call came in.

Because the route is intentionally tolerant (it never 5xxs on a downstream blip), monitoring should treat any one of `status != healthy`, `redis_connected = false`, or `database_connected = false` as a degraded signal worth waking a human for.
