# Monitoring

> the gateway's logbook — what we record, where it goes, and how we read it. The gateway emits structured logs, request-scoped IDs, latency timings, optional LangFuse traces, and per-request cost rows; this page is the index that ties them all together.

> **Related docs:**
>
> - [Observability Deep Dive](../ai-engineering/observability-deep-dive.md) — middleware internals, request IDs, latency anatomy, LangFuse setup
> - [Cost Tracking Deep Dive](../ai-engineering/cost-tracking-deep-dive.md) — PostgreSQL row schema and rollup queries
> - [Health Endpoint](../architecture-and-design/api-routes/health-endpoint-explained.md) — the liveness + readiness probe
> - [Usage Endpoint](../architecture-and-design/api-routes/usage-endpoint-explained.md) — the read-side of the cost ledger
> - [Infrastructure Explained](../architecture-and-design/infra-explained.md) — CloudWatch / Container Apps log destinations

---

## Table of Contents

- [What We Monitor](#what-we-monitor)
- [Metrics Catalogue](#metrics-catalogue)
- [Dashboards](#dashboards)
- [Alerts](#alerts)
- [Log Aggregation](#log-aggregation)
- [Courier Explainer](#courier-explainer)

---

## What We Monitor

The gateway has four observability surfaces, each owned by a different code path:

| Surface | Source | Storage | Query path | 🚚 Courier |
|---------|--------|---------|------------|-----------|
| Structured request logs | `RequestLoggingMiddleware` (`src/middleware/logging.py`) emits one line per request via `loguru` | stdout/stderr → CloudWatch (AWS) / Container Apps log stream (Azure) | `aws logs tail` / `az containerapp logs show`, or scrape into a SIEM | Tachograph print-out from every courier delivery — method, path, status, latency, request id. |
| Per-request cost rows | `cost_tracker.log_request(...)` called by every route handler | PostgreSQL `request_log` table (or in-memory list when DB disabled) | `GET /v1/usage` aggregates; SQL clients for raw rows | Leather expense-ledger entry — courier, model type, token tally, USD, cached flag, latency. |
| Health probes | `GET /health` runs Redis + Postgres connectivity checks | Response payload (no persistence) | Load balancer / ECS / Container Apps health checks | Front-health indicator the operator peeks at; never written to the ledger. |
| Optional LLM traces | LangFuse SDK wired in `src/main.py` when `LANGFUSE_ENABLED=true` | LangFuse SaaS or self-hosted instance | LangFuse UI | Optional observability upgrade in the courier-stalls — only filming when the operator flips it on. |

The gateway does **not** currently expose a Prometheus `/metrics` endpoint (unlike rag-chatbot). Prometheus-style metrics are an open extension point — the cost rows in PostgreSQL and the request log lines in CloudWatch are the equivalent today.

- 🚚 **Courier:** Four signal feeds wired into the monitoring dashboard wall — tachograph tape, leather ledger, health indicator, and optional monitoring feed — together telling the operator whether the gateway is healthy, profitable, and on time.

---

## Metrics Catalogue

The actual emission code lives in [`observability-deep-dive.md`](../ai-engineering/observability-deep-dive.md) (sections 2–5). This catalogue lists what is captured per request and where to read it.

| Signal | Field / column | Emitted by | Read via | 🚚 Courier |
|--------|----------------|------------|----------|-----------|
| Request id | `request_id` (12 hex chars) | `RequestLoggingMiddleware` | Log line prefix `[abc123…]`, `X-Request-ID` response header, every cost row | The unique tachograph stamp burned onto a single delivery — use it to follow one courier end to end. |
| HTTP method + path | `request.method`, `request.url.path` | `RequestLoggingMiddleware` | Log line, e.g. `POST /v1/chat/completions → 200 (1523ms)` | Which dispatch window the courier walked up to and what kind of manifest they handed in. |
| Status code | `response.status_code` | `RequestLoggingMiddleware` | Log line | Red/green light at the end of the delivery — distinguishes a full delivery from a 429 or a 502. |
| Gateway latency (ms) | `gateway_latency_ms` (response) + `X-Gateway-Latency-Ms` header + log line | Both middleware and route handler | Response body, response header, log line, cost row | Total stopwatch from front-door arrival to receipt collection — covers cache, rate limit, courier delivery. |
| Cache hit flag | `cache_hit` (response) + `cached` (cost row) | `chat_completions` handler | Response body, `cost_by_provider` rollup keyed `cache` | Marks whether the pickup locker answered or a real courier was sent. |
| Provider used | `cost.provider`, log line `provider=…` | `chat_completions`, `create_embeddings` | Response body, log, cost row | Which depot the delivery actually came from — AWS depot, Azure hub, local environment, or the pickup locker. |
| Model used | `cost.model`, log line `model=…` | Same as above | Response body, log, cost row | Which model type carried the parcel, in LiteLLM `provider/model` format. |
| Tokens | `usage.prompt_tokens`, `completion_tokens`, `total_tokens` | LiteLLM response → handler | Response body, cost row | token tally — input chewed plus output burnt — used to price the delivery. |
| USD cost | `cost.estimated_cost_usd` | `litellm.completion_cost(...)` | Response body, cost row, `/v1/usage` rollup | Per-delivery line item ready for the monthly invoice. |

`/v1/usage` is the canonical read-side: it joins these per-row signals into per-key, per-window summaries (requests, tokens, USD, cache hit rate, by-model, by-provider).

---

## Dashboards

There is no shipped Grafana / CloudWatch dashboard JSON in the repo (yet). The recommended starter panels — built from the signals above — are:

| Panel | Source query / endpoint | What it tells you | 🚚 Courier |
|-------|------------------------|-------------------|-----------|
| Requests per minute | Log scan (`count(*) WHERE path LIKE '/v1/%'`) or `SELECT count(*) FROM request_log WHERE created_at > now() - interval '1 minute'` | Live throughput on the dispatch desk | Live tally of how many delivery slips the dispatcher is taking per minute. |
| Cache hit rate | `GET /v1/usage?period=today` → `cache_hit_rate` | How much load the pickup locker is absorbing | Share of the courier's questions the pickup locker answered without waking a courier. |
| Latency p50 / p95 / p99 | Log scan over `gateway_latency_ms` | Shape of the wait time distribution | Median delivery time vs the slow tail — flags one provider degrading the courier experience. |
| 429 rate | Log scan `WHERE status_code = 429` | How often rate limits bite | Number of times the gate slammed shut on a courier this hour. |
| 502 rate (provider failures) | Log scan `WHERE status_code = 502` | Upstream LLM provider health | Number of times every courier in the chosen depot was sick or unreachable. |
| USD per hour by provider | `SELECT provider, sum(estimated_cost_usd) FROM request_log GROUP BY provider, hour` | Spend trend by depot | Subtotal of the monthly fuel bill split across AWS, Azure, local, and pickup locker. |
| Health flags | `GET /health` polled every 30s | Boolean strip per dependency (Redis / Postgres / LangFuse) | Three health indicator lights side by side so the operator sees a red lamp at a glance. |

Once a dashboard JSON is added under `infra/aws/` or `infra/azure/`, link it here so the rest of this page becomes a copy-paste runbook.

---

## Alerts

Recommended alerting rules — the gateway itself does not ship these, but the underlying signals are all in place.

| Alert | Source | Rule | Severity | 🚚 Courier |
|-------|--------|------|----------|-----------|
| Gateway down | `/health` not 200 for 3 consecutive checks | Pager | High | Front-health indicator went out — wake an on-call to find out why the dispatcher stopped answering. |
| Redis unreachable | `/health` returns `redis_connected=false` for ≥5 min | Page | High | pickup locker shelf collapsed — semantic cache silently degraded to no-cache mode. |
| Postgres unreachable | `/health` returns `database_connected=false` for ≥5 min | Page | High | Expense ledger jammed — new cost rows are buffering in memory and may be lost on restart. |
| Provider failure rate | 502 rate > 5% over 10 min | Page | High | One in twenty courier deliveries is failing — the configured depot is unhealthy, consider failover. |
| Rate-limit storm | 429 rate > 20% over 10 min | Investigate | Medium | One courier is hammering the gate; verify it's expected or tighten that key's quota. |
| Cache hit rate collapse | `/v1/usage` `cache_hit_rate` drops below 0.05 for ≥1 hour | Investigate | Medium | pickup locker shelf has gone empty — a config change or TTL setting may have neutered the cache. |
| Daily spend overrun | `sum(estimated_cost_usd) > daily budget * 0.8` | Investigate | Medium | monthly fuel budget on track to overshoot — the AWS/Azure budget killer will fire if it actually does. |
| Budget killer fired | AWS Budget 100% notification / Azure Action Group | Page | High | Emergency on-call engineer has just unplugged every wing — a redeploy is required. |

Cloud-side alerts on AWS Budgets / Azure Consumption Budgets at 80% / 100% of EUR 5 are already provisioned by the Terraform — see [Infrastructure Explained → Cost Guardrails](../architecture-and-design/infra-explained.md#cost-guardrails).

---

## Log Aggregation

| Layer | AWS path | Azure path | 🚚 Courier |
|-------|---------|------------|-----------|
| Container stdout/stderr | CloudWatch Log Group `/ecs/${prefix}`, 30-day retention | Container Apps log stream (Log Analytics workspace if linked) | Tachograph tape rolls into the depot's log shed; stays there for thirty days then is shredded. |
| Per-request log lines | Same as above; one line per request with id, method, path, status, latency | Same | One line per delivery, prefixed with the request id so a courier query can be replayed end to end. |
| Per-request cost rows | RDS PostgreSQL `request_log` (managed by `cost_tracker.py`) | Azure PostgreSQL Flexible Server `request_log` | Leather expense ledger lives in the locked back office; rotate it manually for archival. |
| LangFuse traces (optional) | LangFuse SaaS / self-hosted | Same | Optional monitoring feed footage; only recorded when `LANGFUSE_ENABLED=true`. |

The CloudWatch / Container Apps log streams are the **first** place to look for any unexplained behaviour, because every gateway component (middleware, router, cache, rate limiter, cost tracker) routes through `loguru` and ends up there with the same `[request_id]` prefix.

---

## 🚚 Courier Explainer

Monitoring is the gateway's logbook — every delivery records method, path, status, latency, tokens and cost. Four feeds power it:

1. **Per-request log line** — the request-logging middleware writes one line per request (method, path, status, latency, request id) into the cloud's log stream (CloudWatch on AWS, Container Apps log stream on Azure) so any single delivery can be replayed end to end.
2. **Cost tab** — every route handler calls `cost_tracker.log_request(...)`, which writes one row to PostgreSQL with the API key, model, token count, USD cost, and whether the cache answered. `/v1/usage` reads this back in summary form.
3. **Health check** — `/health` exposes three live booleans (Redis reachable, Postgres reachable, LangFuse enabled) plus the active provider. Cloud probes pull this every few seconds.
4. **Optional per-call trace** — LangFuse, off by default, gives a per-LLM-call view in a hosted UI when the operator flips the switch.

The monitoring dashboard ships with no Grafana dashboards or Prometheus scrapes today; the catalogue and alert tables above describe the panels and rules that should sit on top of these existing feeds. Adding them is an extension exercise, not a refactor — every signal is already being emitted.
