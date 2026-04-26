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

> **Read this first if you're new to the gateway.** Same courier analogy as the [Completions Walkthrough](./completions-endpoint-explained.md#plain-english-walkthrough-start-here). This explains what's specific about the cost-and-usage endpoint.

### What is this endpoint for?

`GET /v1/usage` is the **read side of the cost ledger**. While every chat and embedding request *writes* a row to the ledger (Step 5 of the completions pipeline), this endpoint *reads* the ledger and returns a summary: how many requests today, how many tokens, how many dollars, what fraction was cached, broken down by model and provider.

> **Courier version.** This is the **expense-ledger window** at the depot. You walk up, ask "what did this account spend today?", and the clerk flips open the leather book, runs his finger down the right column, and reads back the totals.

### How it works

The handler is dead simple: it pulls the API key from the `Authorization` header (or falls back to the master key in dev), then asks the cost tracker for a summary of that key's activity over the requested period. There's **no pipeline, no rate limit, no LLM call** — just a database read.

In production the cost tracker is PostgreSQL, so a usage call runs three SQL queries against the `usage_logs` table:

1. **Aggregate row.** `COUNT(*)`, `SUM(total_tokens)`, `SUM(estimated_cost_usd)`, `AVG(latency_ms)`, and the cache-hit fraction (`SUM(CASE WHEN cached THEN 1 ELSE 0 END) / COUNT(*)`).
2. **Breakdown by model.** A `GROUP BY model` to count requests per model, sorted descending.
3. **Breakdown by provider.** A `GROUP BY provider` to sum dollars per provider.

All three are filtered by the time window and by the caller's API key (truncated to the first 32 characters — same truncation the writer uses).

### The `period` parameter — and what it really means

You can pass `?period=today` (default), `?period=week`, or `?period=month`. Here's the literal definition the code uses:

| `period` value | Time window |
| --- | --- |
| `today` | From midnight **UTC** of the current day to now |
| `week` | The last 7 days from now |
| `month` | The last 30 days from now |
| anything else | The last 1 day from now (a hidden default) |

A worked example. It's 02:00 in London (so 02:00 UTC, give or take). You hit `?period=today`. The window is from 00:00 UTC today to 02:00 UTC today — only the last two hours. If you're in IST (UTC+5:30), it's 07:30 in the morning at home but the window is still the last two hours of UTC. **`today` doesn't mean "today in your timezone"; it means "today in UTC".** This bites people from non-UTC zones who expect to see their full local-day activity.

`week` and `month` are *rolling* windows — they don't reset at the start of a calendar week or month. Asking on Tuesday afternoon for `week` gives you the previous Tuesday afternoon to now.

### The "you only see your own bill" rule

The endpoint **filters by your API key**. There's no admin view, no global "show me everyone's spend" mode. If you call this with key A you see A's totals; if you call with key B you see B's totals. That's a privacy-by-default choice and it's the right one for a multi-tenant gateway, but it does mean you cannot use this endpoint as the operator's overall cost dashboard.

For operator-wide views you'd query the `usage_logs` table directly in PostgreSQL — or build a separate admin endpoint. Today neither exists in the code.

### The dev-mode footgun

If API keys are turned off, the handler treats every anonymous caller as the master key. So `curl http://localhost:8100/v1/usage` in dev returns the **master key's totals** — which, because every anonymous request also wrote rows under the master key, includes basically everyone's traffic. It looks like an admin view but it isn't — it's just everybody using the same bucket.

### What you get back

```jsonc
{
  "summary": {
    "period": "today",
    "total_requests": 142,
    "total_tokens": 38_201,
    "total_cost_usd": 0.0421,
    "avg_latency_ms": 327.45,
    "cache_hit_rate": 0.18,
    "requests_by_model": {
      "azure/gpt-4": 87,
      "bedrock/anthropic.claude-3-sonnet": 41,
      "ollama/llama3": 14
    },
    "cost_by_provider": {
      "azure": 0.0398,
      "aws":   0.0023,
      "local": 0.0000
    }
  },
  "api_key": "sk-abcd12..."
}
```

The `api_key` field shows the first 8 characters followed by `...` — it's a sanity check ("yes, you're looking at the right key"), not a security exposure.

### Quirks worth knowing

1. **`today` means UTC midnight, not your local midnight.** Account for timezone offset when reading the number.
2. **Three SQL queries per call** — `COUNT/SUM` aggregate plus two `GROUP BY` breakdowns. Cheap on small tables, but worth indexing `(api_key, created_at)` if `usage_logs` grows large.
3. **No global/admin view** — every call is filtered to the calling key. Run SQL directly on `usage_logs` for operator-wide stats.
4. **API keys are truncated to 32 chars** before storage and lookup. If you happen to use two keys that share the first 32 chars, their bills will be merged.
5. **The cache-hit rate denominator is `COUNT(*)`**, not just LLM calls. So a window full of cache hits drives the rate towards 100% as you'd expect; a window with no traffic at all returns 0 rather than dividing by zero (the SQL uses `NULLIF`).
6. **`/health` calls this endpoint internally** (it does a `get_usage_summary(period="today")` to check the database is reachable). So a slow PostgreSQL slows down `/health` too.

### TL;DR

- Read-only window onto the cost ledger; **per-API-key**, never global.
- Time periods are UTC-based (`today` = since UTC midnight) and `week`/`month` are rolling 7/30 days.
- Three SQL queries per call: total, by model, by provider.
- Dev-mode anonymous calls share the master key, which can look like an admin view but isn't.
- For operator-wide totals, query the `usage_logs` table directly — no admin endpoint exists.

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
