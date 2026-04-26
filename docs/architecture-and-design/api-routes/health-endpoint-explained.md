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

> This walkthrough explains what really happens when a request hits `GET /health`. It is a public, unauthenticated endpoint that runs four sub-checks and assembles a response object — but contains several notable honesty gaps between what the response implies and what the code actually verifies.

---

### How the app is assembled at startup

The **Factory Method** builds all four components on `app.state` — `router`, `cache`, `rate_limiter`, `cost_tracker` — before the first request arrives. The health endpoint reads three of them: `cache`, `cost_tracker`, and `router`. If any of those components failed to assemble at startup, the health check will fail at the access point.

`/health` is listed in `PUBLIC_PATHS`, so the `APIKeyMiddleware` bouncer passes all requests through without checking an auth header. There is no rate limit on this endpoint.

> **Courier version.** The porch light is always on; the gate guard waves through the health inspector without asking for a pass. The inspector then looks around the depot and reads back what she sees — but some of her instruments have known calibration issues.

---

#### Step 1 — Redis probe

The handler calls `cache.stats()` and interprets the result to produce `redis_connected`:

| Cache implementation | `stats()` returns | `redis_ok` value |
| --- | --- | --- |
| `RedisSemanticCache` (Redis reachable) | `{"enabled": True, …}` | `True` |
| `InMemoryCache` | `{"enabled": True, …}` | `True` |
| `NoCache` | `{"enabled": False}` | `False` |

**Misleading result when cache is intentionally disabled.** `NoCache.stats()` returns `{"enabled": False}`, so `stats.get("enabled", True)` evaluates to `False`, and `redis_ok` becomes `False`. The response then shows `redis_connected: false` — which a monitoring tool will interpret as "Redis is down", when in fact Redis was simply never configured. There is no way to distinguish "Redis down" from "caching intentionally off" in the health response.

> **Courier version.** The inspector checks whether the pickup locker shelf is powered on. If the shelf was never installed (caching disabled), the inspector's report still says "shelf off" — the same reading as if the shelf is installed but broken. Two different situations; one reading.

---

#### Step 2 — PostgreSQL probe

The handler calls `cost_tracker.get_usage_summary(period="today")` and considers the database healthy if that call does not raise.

| Cost tracker implementation | Behaviour | `db_ok` value |
| --- | --- | --- |
| `PostgresCostTracker` (DB reachable) | Runs 3 SQL queries; returns data | `True` |
| `PostgresCostTracker` (DB unreachable) | Raises exception | `False` |
| `InMemoryCostTracker` | Returns in-memory data; does not raise | `True` |
| `NoCostTracker` | Returns `{"enabled": False}`; does not raise | `True` |

**Heavyweight probe.** `get_usage_summary(period="today")` runs three SQL queries — aggregate totals, group-by-model, and group-by-provider — on every health check. On a large `usage_logs` table, `/health` becomes slow because of this probe.

**Misleading result when cost tracking is disabled.** `NoCostTracker.get_usage_summary()` returns without raising, so `db_ok` becomes `True` — the response shows `database_connected: true` even when no database is configured.

> **Courier version.** The inspector checks the ledger by asking the clerk to run the full weekly summary. If the clerk has no ledger (cost tracking disabled), she hands back a blank page — the inspector marks "ledger: ok" because no error was raised. A proper probe would be "can you find the ledger book?" not "can you summarise last week?".

---

#### Step 3 — Models list

The handler calls `router.list_models()` and collects the model IDs into `models_available`. This is the same hardcoded in-memory read as the `/v1/models` endpoint. No live provider probing occurs.

`models_available` shows what the router is configured to know about, not what is currently responding. A provider outage is invisible here.

> **Courier version.** The inspector copies the wall roster into her report. If half the couriers called in sick, the roster still shows their names — the inspector has no way to check who is actually at their desk.

---

#### Step 4 — Response assembly

The handler assembles a `HealthStatus` object from the four probe results plus static fields.

**`status` field is hardcoded `"healthy"`.** The return statement is literally `status="healthy"` — it does not aggregate `redis_ok` and `db_ok`. A response with `redis_connected: false` and `database_connected: false` still returns `status: "healthy"`.

**`langfuse_connected` is not a probe.** The field is set to `settings.langfuse_enabled` — a boolean config flag. No ping to Langfuse is made. Setting `LANGFUSE_ENABLED=true` in the environment returns `langfuse_connected: true` even if Langfuse is unreachable.

**Worked example — degraded state that still reports healthy:**

| Probe | Reality | Value in response |
| --- | --- | --- |
| `status` | Redis down, Postgres down | `"healthy"` — hardcoded |
| `redis_connected` | Redis unreachable | `false` |
| `database_connected` | Postgres unreachable | `false` |
| `langfuse_connected` | Langfuse unreachable (but config says enabled) | `true` — config flag only |
| `models_available` | Provider offline | list still populated — hardcoded |

A Kubernetes liveness probe that only checks `status == "healthy"` will keep the pod in rotation even when both Redis and Postgres are down, leading to silent degraded behaviour across replicas.

> **Courier version.** The inspector files her report with a pre-stamped header that always says "DEPOT OPEN". The individual checkboxes below can all be ticked "problem", but the header never changes. A load balancer reading only the header will think the depot is fine.

---

### Condition matrix

| Scenario | `redis_connected` | `database_connected` | `langfuse_connected` | `status` field | HTTP status |
| --- | --- | --- | --- | --- | --- |
| All systems healthy | `true` | `true` | reflects config | `"healthy"` | 200 |
| Redis down, Postgres ok | `false` | `true` | reflects config | `"healthy"` | 200 |
| Redis disabled (NoCache) | `false` | `true` | reflects config | `"healthy"` | 200 |
| Postgres down | `true` | `false` | reflects config | `"healthy"` | 200 |
| Cost tracking disabled (NoCostTracker) | `true` | `true` | reflects config | `"healthy"` | 200 |
| Both Redis and Postgres down | `false` | `false` | reflects config | `"healthy"` | 200 |
| Langfuse unreachable but enabled in config | — | — | `true` | `"healthy"` | 200 |

---

### 🩺 Honest health check

1. **`status: "healthy"` is hardcoded regardless of probe results.** A monitoring tool that checks only the `status` field will never see a degraded signal. Fix: derive `status` from `redis_connected AND database_connected`; return `"degraded"` when any required component is down.
2. **Postgres probe is heavyweight (3 SQL queries per health check).** Using `get_usage_summary()` as a liveness probe is expensive; on a large `usage_logs` table this slows every health check. Fix: replace with a simple `SELECT 1` query or a dedicated lightweight ping method on the cost tracker.
3. **`langfuse_connected` reflects config, not connectivity.** It is not a real probe. Fix: add an HTTP ping to the Langfuse endpoint, or rename the field to `langfuse_enabled` to be honest about what it measures.
4. **`redis_connected: false` is ambiguous.** It means either "Redis is unreachable" or "caching is intentionally disabled". Fix: add a separate `cache_enabled` field so operators can distinguish configuration intent from operational failure.
5. **`database_connected: true` when cost tracking is disabled.** `NoCostTracker` does not raise, so the probe reports healthy. Fix: add a separate `cost_tracking_enabled` field alongside `database_connected`.
6. **`models_available` is a hardcoded list, not a live provider check.** Providers can be down while the list shows their models. Fix: add an optional live-probe mode, or document that this list reflects startup config only.

---

### TL;DR

- **Factory Method** wires all four components at startup; the health endpoint reads three of them (`cache`, `cost_tracker`, `router`).
- **Four probes**: Redis (via `cache.stats()`), Postgres (via a heavyweight 3-query `get_usage_summary()`), Langfuse (config flag only), and models list (hardcoded).
- **`status: "healthy"` is always hardcoded** — the probe results do not influence it; monitoring tools must check the boolean flags directly.
- **Ambiguous disabled-vs-down signals**: `NoCache` reports `redis_connected: false`; `NoCostTracker` reports `database_connected: true`.
- The endpoint always returns HTTP 200 — orchestrators expecting 5xx on unhealthy will never see it from this route.
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
