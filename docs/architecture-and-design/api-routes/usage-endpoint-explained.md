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
