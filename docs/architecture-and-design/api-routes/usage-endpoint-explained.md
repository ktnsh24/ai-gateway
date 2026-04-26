# Usage Endpoint — Deep Dive

> `GET /v1/usage` — read the cost ledger. Returns a per-API-key summary of requests, tokens, USD cost, cache hit rate, and breakdowns by model and provider for a chosen window.

> **Source file:** `src/routes/usage.py`
>
> **Related docs:**
>
> - [API Contract](../api-contract.md) — full schema reference
> - [API Routes Overview](../api-routes-explained.md) — how all 5 routes fit together
> - [Cost Tracking Deep Dive](../../ai-engineering/cost-tracking-deep-dive.md) — PostgreSQL schema and rollup queries
> - [Cost Analysis](../../ai-engineering/cost-analysis.md) — per-provider unit pricing

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

> This walkthrough explains what really happens when a request hits `GET /v1/usage`. It is a pure read endpoint — no LLM call, no cache, no rate limit check — just a structured query against the cost ledger.

---

### How the app is assembled at startup

The **Factory Method** builds the `cost_tracker` component on `app.state` using `create_cost_tracker(settings)`. Three possible implementations:

| Implementation | Backing store | Behaviour |
| --- | --- | --- |
| `PostgresCostTracker` | PostgreSQL `usage_logs` table | Runs real SQL queries; lazily creates the table on first use |
| `InMemoryCostTracker` | In-process Python list | Reduces the list on each call; resets on restart |
| `NoCostTracker` | None | Returns `{"enabled": False}` without raising |

If the factory fails and `cost_tracker` is never placed on `app.state`, requests to this endpoint fail at the first access.

> **Courier version.** The ledger clerk is hired at opening time. If PostgreSQL is reachable, she gets the leather book. If not, she gets a pocket notebook. If cost tracking is fully disabled, she is not hired at all — but she still answers the window and hands back a note that says "ledger not active".

---

#### Step 1 — Auth check

`/v1/usage` is not in `PUBLIC_PATHS`. The `APIKeyMiddleware` bouncer requires a valid `Authorization: Bearer <key>` header when auth is enabled. The extracted key is also used to filter the cost ledger — callers can only read their own rows.

In dev mode with auth disabled, every anonymous caller is treated as the master key. Because all anonymous dev requests write under the master key, the usage summary in this mode looks like an aggregate view of all traffic — it is not; it is everyone sharing one bucket.

> **Courier version.** You need your pass to open the ledger window. And the ledger clerk only shows you your own tab. In dev, everyone uses the same guest pass and accidentally reads the combined total of all guest journeys.

---

#### Step 2 — Period resolution

The `period` query parameter controls the time window. The implementation defines the boundaries as follows:

| `period` value | Time window | Boundary type |
| --- | --- | --- |
| `today` | UTC midnight of the current day to now | Exact midnight — not rolling |
| `week` | Last 7 days from now | Rolling |
| `month` | Last 30 days from now | Rolling |

`today` is the only period whose boundary is a fixed clock point (midnight UTC). `week` and `month` are rolling intervals from "now".

**UTC midnight trap.** An engineer in UTC+5:30 at 04:00 local time sees only 4 hours of "today" data, not their full business day. The UTC anchor affects anyone outside UTC.

**Worked example — period boundary comparison:**

| Caller's timezone | Local time | UTC time | `today` window |
| --- | --- | --- | --- |
| UTC | 15:00 | 15:00 UTC | 00:00–15:00 UTC (15 hours of data) |
| IST (UTC+5:30) | 10:30 | 05:00 UTC | 00:00–05:00 UTC (only 5 hours of data) |
| US/Pacific (UTC-8) | 10:00 | 18:00 UTC | 00:00–18:00 UTC (18 hours — spans overnight) |

> **Courier version.** The ledger only marks the boundary between "yesterday" and "today" at midnight Greenwich time. An engineer in Mumbai asking "what did we spend today?" at 10:30 AM local will only see the last 5 hours of UTC data — her day started 5.5 hours before UTC did.

---

#### Step 3 — Three SQL queries per call

When `PostgresCostTracker` is active, `get_usage_summary()` runs exactly three SQL queries against the `usage_logs` table, all filtered by `api_key` and the time window:

| Query | Purpose |
| --- | --- |
| 1 — Aggregate | `COUNT(*)`, `SUM(total_tokens)`, `SUM(estimated_cost_usd)`, `AVG(latency_ms)`, cache-hit fraction |
| 2 — Group by model | `GROUP BY model` — request count per model, sorted descending |
| 3 — Group by provider | `GROUP BY provider` — total USD per provider |

Three queries run on every usage request, with no caching of the result. On a small `usage_logs` table this is fast; on a large table without an index on `(api_key, created_at)` all three queries degrade to full table scans.

When `NoCostTracker` is active, `get_usage_summary()` returns `{"enabled": False}` without hitting any database. The handler constructs an empty summary object — there is no indication in the response that tracking is disabled, just zeroed-out fields.

> **Courier version.** The ledger clerk does three things when you ask for your totals: she counts your slips, adds up the costs by parcel type, then adds them up again by which post office handled each one. Three ledger-flips every time you ask, with no shortcuts.

---

### Condition matrix

| Scenario | Auth check | Period resolved | Queries run | Status |
| --- | --- | --- | --- | --- |
| Auth disabled, tracking enabled | skipped | yes | 3 SQL | 200 |
| Auth enabled, valid key, tracking enabled | passes | yes | 3 SQL | 200 |
| Auth enabled, missing key | 401 | — | — | 401 |
| Tracking disabled (`NoCostTracker`) | passes | yes | none (returns empty dict) | 200 (zeroed fields, no "disabled" flag) |
| Postgres down | passes | yes | fails | 500 |
| `period=today` from UTC+5:30 at 04:00 local | passes | yes (only 4h of UTC data) | 3 SQL | 200 (misleadingly short window) |

---

### 🩺 Honest health check

1. **`today` uses UTC midnight, not the caller's local midnight.** Engineers outside UTC see a truncated "today" that does not correspond to their business day. Fix: accept a `timezone` query parameter, or at minimum document the UTC assumption in the API response.
2. **Three SQL queries on every call with no result caching.** On a large unindexed `usage_logs` table, `/v1/usage` becomes slow. Fix: add a composite index on `(api_key, created_at)`, and consider caching the aggregate result at 60-second granularity.
3. **`NoCostTracker` returns zeroed data with no indication tracking is off.** A caller with cost tracking disabled gets zero totals and has no way to know whether their usage is truly zero or tracking was never active. Fix: add a `"tracking_enabled": false` field to the response when `NoCostTracker` is active.
4. **No global or admin view.** Every call is filtered to the calling key. Operators need direct database access for cross-key totals. Fix: add an admin endpoint or a separate reporting query that accepts an operator key.
5. **The `/health` endpoint uses this same `get_usage_summary()` call** as its Postgres liveness probe, running 3 SQL queries on every health check. Fix: replace the health probe with a lightweight `SELECT 1` query instead of a full aggregate.

---

### TL;DR

- **Read-only ledger query** — per-API-key, no LLM call, no cache, no rate limit.
- **Three SQL queries per call** (aggregate + by-model + by-provider); no result caching; degrade on large unindexed tables.
- **`today` = UTC midnight boundary** (fixed point); `week` and `month` are rolling intervals from now.
- **`NoCostTracker`** returns zeroed fields silently — no response signal that cost tracking is disabled.
- **Factory Method** selects the tracker implementation at startup based on Postgres reachability.
---

## Endpoint Summary

| Attribute | Value | 🚚 Courier |
|-----------|-------|-----------|
| Method | `GET` | A read against the ledger; the dispatcher reads totals, never adds a row from this route. |
| Path | `/v1/usage` | Custom gateway extension — not in the OpenAI spec — sitting next to the other `/v1` routes. |
| Auth | Bearer token (when `API_KEYS_ENABLED=true`) | Same gate guard as everywhere; the courier can only read their own ledger entries, not someone else's. |
| Purpose | Return aggregated request count, token tally, USD cost, cache hit rate for the caller's API key | Open the leather expense ledger to today, this week, or this month and read the running totals. |

---

## Request Schema

Single query parameter `period`, parsed into the `UsagePeriod` enum.

| Param | Type | Required | Default | Allowed | Description | 🚚 Courier |
|-------|------|----------|---------|---------|-------------|-----------|
| `period` | `UsagePeriod` (enum) | ❌ | `today` | `today`, `week`, `month` | Window over which the cost tracker rolls up rows | Sliding pane on the ledger — open it to today, the past week, or the current month before reading totals. |

The API key the totals belong to is taken from the `Authorization: Bearer …` header (same as every other route); no `api_key` query param exists.

---

## Response Schema

Pydantic model: `UsageResponse` wrapping a `UsageSummary`.

| Field | Type | Description | 🚚 Courier |
|-------|------|-------------|-----------|
| `summary.period` | `str` | Echo of the requested period (`today` / `week` / `month`) | Confirms which pane of the ledger was opened, useful when caching the response on the client side. |
| `summary.total_requests` | `int` | Count of deliveries logged for this key in the window | Total deliveries this courier sent through the dispatch desk in the chosen window, cache hits included. |
| `summary.total_tokens` | `int` | Sum of `prompt_tokens + completion_tokens` across rows | Total tokens carried — input fuel plus output fuel across every delivery the courier paid for. |
| `summary.total_cost_usd` | `float` | Sum of `estimated_cost_usd` | The running USD bill on the courier's tab; cached deliverys contribute zero. |
| `summary.cache_hit_rate` | `float` | Cached deliveries ÷ total deliveries, in `[0.0, 1.0]` | Share of the courier's deliveries the pickup locker answered without waking a courier — higher means cheaper monthly bill. |
| `summary.avg_latency_ms` | `float` | Mean `latency_ms` across rows | Average wall-clock time per delivery; useful to spot one provider degrading the courier's experience. |
| `summary.requests_by_model` | `dict[str,int]` | Trip count keyed by LiteLLM model id | Per-breed roster usage — which model types the courier leaned on most heavily this window. |
| `summary.cost_by_provider` | `dict[str,float]` | USD cost keyed by provider tag (`aws`, `azure`, `local`, `cache`) | Depot-by-depot subtotal — shows whether AWS, Azure, the local depot, or the pickup locker carried the biggest bill. |
| `api_key` | `str` | First 8 chars of the caller's key + `"..."` (masked) | Receipt header showing a redacted key fingerprint so the courier knows which tab they just read. |

---

## Internal Flow

```
client → CORS middleware
       → RequestLoggingMiddleware  (assigns X-Request-ID, starts timer)
       → APIKeyMiddleware          (only if API_KEYS_ENABLED)
       → get_usage() handler
            │
            ├─ 1. Pull cost_tracker, settings from app.state
            │
            ├─ 2. Extract Bearer token from Authorization header
            │     fallback to settings.master_api_key for dev calls
            │
            ├─ 3. cost_tracker.get_usage_summary(api_key=..., period=period.value)
            │     ├─ PostgresCostTracker → SELECT-with-aggregates against
            │     │   the request_log table, filtered by api_key + window
            │     └─ InMemoryCostTracker → reduces the in-memory list
            │
            ├─ 4. Construct UsageSummary(**summary_data)
            │
            └─ 5. Return UsageResponse(summary=..., api_key=key[:8] + "...")
       ← RequestLoggingMiddleware  (sets X-Gateway-Latency-Ms, logs status)
       ← client
```

No LLM call, no cache write, no rate limit check — this is purely a read against the cost ledger.

---

## Curl Example

```bash
curl -sS "http://localhost:8100/v1/usage?period=week" \
  -H "Authorization: Bearer $GATEWAY_API_KEY" | jq '.summary | {total_requests, total_cost_usd, cache_hit_rate, cost_by_provider}'
```

Sample response for a week of mixed traffic:

```json
{
  "total_requests": 142,
  "total_cost_usd": 0.0453,
  "cache_hit_rate": 0.23,
  "cost_by_provider": {
    "local": 0.0,
    "aws":   0.0453,
    "cache": 0.0
  }
}
```

---

## Error Cases

| Status | `error` code | When it fires | 🚚 Courier |
|--------|--------------|---------------|-----------|
| `401` | `authentication_required` | Missing Bearer header on protected path | Courier asked to read the ledger without a permission slip; gate guard sends them away before any rows are looked up. |
| `403` | `forbidden` | Bearer token unknown | Permission slip is forged — gate guard refuses to even open the leather ledger to look for the courier's tab. |
| `422` | (FastAPI default) | `period` query value is not in `today/week/month` | Gateway checked the slot the courier asked to open; it isn't a real ledger pane and the request is rejected. |
| `500` | (default) | `cost_tracker.get_usage_summary` raised (e.g. PostgreSQL down) | Ledger book is jammed shut — the database is unreachable so the dispatcher cannot tally anything for the courier. |

---

## 🚚 Courier Explainer

This endpoint reads the **cost tab**: the caller asks for today, this week, or this month, and the gateway tallies the rows for that window — how many requests, how many tokens, how many USD, how often the cache answered, and a per-app subtotal — and returns the totals.

Nothing is written, no courier is dispatched, and the response includes a masked fingerprint of the caller's key so they know which tab the totals belong to. The underlying query lives in `cost_tracker.get_usage_summary`; the on-disk schema is documented in the [Cost Tracking Deep Dive](../../ai-engineering/cost-tracking-deep-dive.md).
