# Cost Analysis — AI Gateway

> Per-service cost breakdown for AWS, Azure, and Local — including why we chose each service and what alternatives cost more.

**Related:** [Cost Tracking Deep Dive](cost-tracking-deep-dive.md) · [Architecture](../architecture-and-design/architecture.md)

**Shared baseline:** [Cost Analysis Playbook (portfolio-level)](../../../../docs/shared/ai-engineering/cost-analysis-playbook.md)

## Table of Contents

- [Monthly Cost Summary](#monthly-cost-summary)
  - [Development (personal account)](#development-personal-account)
  - [Production (small scale)](#production-small-scale-1000-queriesday)
- [Service-by-Service Breakdown](#service-by-service-breakdown)
  - [LLM Inference (Routed via LiteLLM)](#llm-inference-routed-via-litellm)
  - [Semantic Cache (Redis)](#semantic-cache-redis)
  - [Cost Tracking Database (PostgreSQL)](#cost-tracking-database-postgresql)
  - [Rate Limiting](#rate-limiting)
- [Cost Impact of Gateway Features](#cost-impact-of-gateway-features)
- [What Alternatives Cost More](#what-alternatives-cost-more)
- [Decision Summary](#decision-summary)
- [How to Minimise Costs on Personal Account](#how-to-minimise-costs-on-personal-account)
- [Cost of Running Tests on Cloud](#cost-of-running-tests-on-cloud)
- [Budget Guard — Automatic Cost Protection](#budget-guard--automatic-cost-protection)

---

## Monthly Cost Summary

### Development (personal account)

| Service | AWS Cost/month | Azure Cost/month | Notes | 🚚 Courier |
|---|---|---|---|---|
| LLM (pay-per-use) | ~$2–5 | ~$2–5 | Based on ~100 queries/day | 🚚 Each courier delivery to the AWS or Azure depot costs two to five dollars a month at roughly a hundred shipping manifests a day. |
| Embeddings | ~$0.10 | ~$0.10 | For semantic cache similarity | 🚚 The GPS-coordinate writer charges a dime a month to turn shipping manifests into vectors the pickup locker can compare. |
| Semantic Cache (Redis) | $0 (local) | $0 (local) | Run Redis in Docker | 🚚 The pickup locker shelf runs free inside the local Docker Compose setup — no cloud depot bill during development. |
| Cost Tracking (PostgreSQL) | $0 (local) | $0 (local) | Run PostgreSQL in Docker | 🚚 The expense ledger runs free in Docker locally — no RDS or Azure DB charges while developing. |
| Container Hosting | $0 (local) | $0 (local) | Run locally during development | 🚚 The gateway (FastAPI) runs on the local machine during development — no cloud container-hosting bill. |
| **Total** | **~$2–5/month** | **~$2–5/month** | Mostly LLM token costs | 🚚 Almost the entire development bill is courier tokens — the pickup locker and ledger cost nothing when run locally. |

### Production (small scale: ~1000 queries/day)

| Service | AWS Cost/month | Azure Cost/month | 🚚 Courier |
|---|---|---|---|
| LLM (routed via LiteLLM) | ~$50–100 | ~$40–80 | 🚚 The LiteLLM adapter sends shipping manifests to whichever depot courier is cheapest — still the biggest line item at scale. |
| Embeddings (for cache) | ~$1–2 | ~$1–2 | 🚚 The GPS-coordinate writer charges one to two dollars a month at production volume to power the pickup locker's similarity checks. |
| Redis (ElastiCache / Azure Cache) | ~$15 (t3.micro) | ~$16 (C0 Basic) | 🚚 The managed pickup locker shelf at AWS or Azure hub costs about fifteen dollars a month for the smallest always-on instance. |
| PostgreSQL (RDS / Azure DB) | ~$15 (db.t3.micro) | ~$15 (B1ms) | 🚚 The cloud-hosted expense ledger runs fifteen dollars a month on the smallest managed database tier. |
| Container Hosting | ~$30 (Fargate) | ~$20 (Container Apps) | 🚚 Running the gateway on Fargate or Azure Container Apps costs twenty to thirty dollars a month at small scale. |
| **Total** | **~$115/month** | **~$95/month** | 🚚 The Azure hub is twenty dollars cheaper per month — mostly because the Azure providers charge less per token. |

> **Key insight:** The gateway itself is cheap — Redis and PostgreSQL are small instances. The LLM token costs dominate, which is exactly what the cost tracker monitors.

---

## Service-by-Service Breakdown

### LLM Inference (Routed via LiteLLM)

The gateway routes to multiple providers. Per-token costs are the same as V1 (rag-chatbot):

| | AWS Bedrock (Claude 3.5 Sonnet) | Azure OpenAI (GPT-4o) | Local (Ollama) | 🚚 Courier |
|---|---|---|---|---|
| **Input tokens** | $0.003/1K | $0.0025/1K | **$0** | 🚚 Loading tokens onto the courier before departure costs three tenths of a cent per thousand at AWS depot, nothing in the local environment. |
| **Output tokens** | $0.015/1K | $0.01/1K | **$0** | 🚚 Each tokens the courier writes in the reply costs one and a half cents per thousand at AWS depot, free at the local environment. |
| **Per query (typical)** | ~$0.013 | ~$0.01 | **$0** | 🚚 A typical shipping manifests round-trip costs about a penny at the AWS depot, slightly less at the Azure hub, and nothing in the local environment. |

**Gateway cost savings:**
- **Semantic cache:** ~30% fewer LLM calls for repeated/similar queries
- **Cost-optimised routing:** Route simple queries to cheaper models
- **Fallback routing:** Avoid expensive retries on failed providers

### Semantic Cache (Redis)

| Option | Cost/month | Persistence | Scales to zero? | 🚚 Courier |
|---|---|---|---|---|
| **Docker (local)** | $0 | Restart = lost | N/A | 🚚 The pickup locker shelf lives in the local Docker Compose setup for free but all pre-written replies disappear when the gateway restarts. |
| **AWS ElastiCache (t3.micro)** | ~$15 | Yes | No | 🚚 AWS's managed pickup locker shelf keeps pre-written replies alive across restarts but always runs even when no couriers are active. |
| **Azure Cache for Redis (C0)** | ~$16 | Yes | No | 🚚 The Azure hub's managed pickup locker shelf is one dollar pricier than AWS and also stays on around the clock. |
| **Upstash Redis (serverless)** | $0 (free: 10K cmd/day) | Yes | **Yes** | 🚚 Upstash's serverless pickup locker shelf scales to zero when idle and gives ten thousand free shelf lookups a day — ideal for light traffic. |

**What we chose:**
- **Development:** Docker Redis (free, no cloud needed)
- **Production:** ElastiCache/Azure Cache (managed, persistent)
- **Budget alternative:** Upstash free tier (10K commands/day = ~300 queries)

### Cost Tracking Database (PostgreSQL)

| Option | Cost/month | Storage | Managed? | 🚚 Courier |
|---|---|---|---|---|
| **Docker (local)** | $0 | Restart = lost | No | 🚚 The local expense ledger is free but every entry vanishes when the local Docker Compose setup shuts down. |
| **AWS RDS (db.t3.micro)** | ~$15 | 20 GB | Yes | 🚚 AWS's managed expense ledger holds twenty gigabytes of delivery receipts and handles backups without manual depot maintenance. |
| **Azure Database for PostgreSQL (B1ms)** | ~$15 | 32 GB | Yes | 🚚 The Azure hub's managed ledger is the same price as AWS but with thirty-two gigabytes — room for months of delivery receipts. |
| **Supabase (free tier)** | $0 (500 MB) | 500 MB | Yes | 🚚 Supabase's free ledger holds five hundred megabytes — enough for months of courier expense entries without paying a penny. |
| **In-memory (no persistence)** | $0 | None | N/A | 🚚 Expense entries are scribbled in RAM with no ledger at all — free and instant but lost forever when the gateway restarts. |

**What we chose:**
- **Development:** In-memory cost tracker (no PostgreSQL needed)
- **Production:** RDS/Azure PostgreSQL (managed, durable)
- **Budget alternative:** Supabase free tier (500 MB = months of usage logs)

### Rate Limiting

Rate limiting uses the same Redis instance as the cache — no additional cost.

---

## Cost Impact of Gateway Features

| Feature | Cloud Cost Impact | Token Savings | 🚚 Courier |
|---|---|---|---|
| **Semantic cache (30% hit rate)** | +$15/month (Redis) | −30% LLM tokens (~$15–30/month) | 🚚 The pickup locker shelf costs fifteen dollars a month but cuts courier tokens bills by up to thirty dollars — net positive at scale. |
| **Rate limiting** | $0 (uses cache Redis) | Prevents runaway costs | 🚚 The daily dispatch quota enforcer shares the same pickup locker shelf and adds nothing to the cloud bill while stopping runaway courier hiring. |
| **Cost tracking** | +$15/month (PostgreSQL) | Enables cost visibility | 🚚 The expense ledger costs fifteen dollars a month but turns every tokens into a visible, queryable line item. |
| **Fallback routing** | $0 | Avoids failed requests ($0 wasted tokens) | 🚚 When the primary courier is sick the dispatch desk tries the backup at no extra cost — zero tokens wasted on a failed delivery. |
| **Cost-optimised routing** | $0 | Routes to cheapest provider | 🚚 The dispatch desk silently ranks providers by price and sends each shipping manifest to the cheapest healthy courier available. |

**ROI at 1000 queries/day:**
- Cache saves ~$15–30/month in LLM tokens
- Redis costs ~$15/month
- **Net: break-even to +$15/month savings**
- Plus: visibility, rate control, and observability are invaluable

---

## What Alternatives Cost More

### Alternative 1: AWS API Gateway + Lambda instead of FastAPI

| | FastAPI on Fargate (our choice) | API Gateway + Lambda | 🚚 Courier |
|---|---|---|---|
| **Architecture** | Single container | Serverless functions | 🚚 The gateway lives in one long-running container; Lambda is a courier hired per delivery with no memory of the last journey. |
| **Min cost** | ~$30/month | ~$5/month (free tier) | 🚚 The always-on gateway costs thirty dollars a month; the serverless option is cheaper but cold-starts slow every first delivery. |
| **Latency** | ~10ms routing overhead | ~100–500ms (cold start) | 🚚 The gateway adds ten milliseconds of dispatch overhead; a cold Lambda courier can take half a second to wake up. |
| **WebSocket support** | Yes (built-in) | Complex (API Gateway WS) | 🚚 The gateway streams replies over a live connection natively; Lambda needs a separate API Gateway WebSocket adapter bolted on. |
| **State management** | In-process (Redis) | External only | 🚚 The gateway keeps the pickup locker connection warm in memory; a Lambda courier must re-open the shelf door on every delivery. |

**Why FastAPI is better here:** The gateway is a long-running proxy — it holds Redis connections, caches state, and routes requests with low latency. Lambda cold starts (100–500ms) add unacceptable latency to every LLM call.

### Alternative 2: Kong/Tyk API Gateway instead of custom

| | Custom FastAPI gateway (our choice) | Kong/Tyk | 🚚 Courier |
|---|---|---|---|
| **LLM-specific features** | Semantic cache, cost tracking | Generic rate limiting | 🚚 Our custom dispatch desk knows about pickup lockers and expense ledgers; Kong only knows how to count deliveries at the gateway door. |
| **Cost** | ~$30/month (Fargate) | ~$50–200/month (managed) | 🚚 Building our own dispatch desk on Fargate costs thirty dollars a month; renting Kong's managed switchboard costs up to two hundred. |
| **Customisation** | Full control | Plugin system | 🚚 We can rewire every part of the dispatch desk; Kong requires hunting for the right plugin before touching the routing logic. |
| **Learning value** | High (built from scratch) | Low (managed service) | 🚚 Wiring the dispatch desk by hand teaches caching, expense ledgers, and delivery quotas; clicking Kong buttons teaches nothing new. |

**Why custom is better for a portfolio:** Building the gateway teaches rate limiting, caching, and cost tracking patterns. Kong/Tyk are great for production but don't demonstrate engineering skills.

### Alternative 3: Amazon Bedrock Guardrails instead of custom rate limiting

| | Custom rate limiter (our choice) | Bedrock Guardrails | 🚚 Courier |
|---|---|---|---|
| **Per-API-key limits** | Yes | No (per-model only) | 🚚 Our daily dispatch quota tracks how many deliveries each courier's API key has used; Guardrails only counts deliveries per model type. |
| **Cost tracking** | Yes (per-request) | No | 🚚 The custom dispatch desk writes every delivery to the expense ledger; Bedrock Guardrails never open a ledger at all. |
| **Multi-provider** | Yes (AWS + Azure + Local) | AWS only | 🚚 The custom daily dispatch quota covers the AWS depot, Azure hub, and local environment; Guardrails only guards the AWS depot's front door. |
| **Cost** | $0 (Redis) | $0 (included) | 🚚 Both cost nothing extra — our quota enforcer shares the existing pickup locker shelf while Guardrails come bundled with Bedrock. |

**Why custom is better:** Bedrock Guardrails only works with Bedrock. Our gateway rate-limits across all providers with per-API-key granularity.

---

## Decision Summary

| Decision | Chosen | Alternative | Why chosen wins | 🚚 Courier |
|---|---|---|---|---|
| Gateway framework | FastAPI (custom) | Kong/Tyk/AWS API Gateway | Full control, LLM-specific features, learning value | 🚚 Building the gateway's dispatch desk by hand teaches caching, cost tabs, and rate limits — renting Kong teaches none of those skills. |
| Cache | Redis (semantic) | None / DynamoDB | ~30% token savings, sub-ms lookup | 🚚 The fast pickup locker shelf saves thirty percent of tokens costs and returns pre-written replies in under a millisecond. |
| Cost tracking | PostgreSQL (custom) | CloudWatch Metrics | Per-request granularity, queryable dashboards | 🚚 The custom ledger records every tokens per courier per delivery; CloudWatch only knows aggregate depot-level totals. |
| Rate limiting | Redis (per-key) | Bedrock Guardrails | Multi-provider, per-API-key | 🚚 The pickup locker shelf doubles as a daily dispatch quota enforcer for every courier key across all providers — Guardrails only guards one depot. |
| Routing | LiteLLM | Direct API calls | Unified interface to 100+ providers | 🚚 The LiteLLM adapter fits every courier with the same API interface — swapping the AWS depot for the Azure hub needs only one env var change. |

---

## How to Minimise Costs on Personal Account

1. **Run everything locally** — Docker Compose gives you Redis + PostgreSQL + Ollama for $0
2. **Use in-memory fallbacks** — The gateway auto-falls back to in-memory cache/rate-limiter/cost-tracker when Redis/PostgreSQL aren't available
3. **Use Ollama for development** — All LLM calls are $0
4. **Test with cloud only when needed** — One test run costs ~$0.50–1.00
5. **Set billing alerts** — AWS: $10/month budget, Azure: $10/month budget
6. **Never provision always-on instances** — Use pay-per-use or free tiers

---

## Cost of Running Tests on Cloud

| Provider | LLM Calls | Token Cost | Infrastructure | Total per Run | 🚚 Courier |
|---|---|---|---|---|---|
| **Local (Ollama)** | ~20 | $0 | $0 (Docker) | **$0** | 🚚 Twenty deliveries routed to the local courier cost nothing — the local Docker Compose setup runs everything free during test runs. |
| **AWS (Bedrock)** | ~20 | ~$0.26 | $0 (in-memory fallback) | **~$0.26** | 🚚 Twenty deliveries to the AWS depot courier burn about twenty-six cents in tokens with no cloud infra needed alongside. |
| **Azure (OpenAI)** | ~20 | ~$0.20 | $0 (in-memory fallback) | **~$0.20** | 🚚 Twenty deliveries to the Azure hub courier cost twenty cents in tokens — slightly cheaper than the AWS depot per test run. |

> **Recommendation:** Run tests locally (Ollama = $0), then once on each cloud provider to verify routing. Total cloud cost: **~$0.50 one-time**.

---

## Budget Guard — Automatic Cost Protection

Both `infra/aws/` and `infra/azure/` include a **budget guard** (`budget.tf`) that automatically protects against runaway cloud costs.

### How it works

| Threshold | Action | 🚚 Courier |
|---|---|---|
| **80% of limit (€4)** | Email warning sent to `alert_email` | 🚚 When the monthly expense ledger hits four euros the gateway master fires off a warning email before the kill switch arms itself. |
| **100% of limit (€5)** | Email + automatic resource kill switch triggered | 🚚 At five euros the ledger trips the emergency brake — an email fires and the automation stops all running couriers instantly. |

### AWS

- **AWS Budget** monitors tagged resources (`project=ai-gateway`)
- **SNS → Lambda** pipeline: at 100%, a Lambda function scales ECS to 0 and stops RDS instances
- File: `infra/aws/budget.tf` + `infra/aws/budget_killer_lambda/handler.py`

### Azure

- **Azure Consumption Budget** scoped to the resource group
- **Action Group → Automation Runbook**: at 100%, a PowerShell runbook deletes all resources in the resource group
- File: `infra/azure/budget.tf`

### Configuration

```hcl
variable "cost_limit_eur" {
 default = 5 # €5 kill switch
}

variable "alert_email" {
 # Required — where budget warnings go
}
```

### ⚠️ Important caveat

Cloud cost reporting has a **6–24 hour lag**. The budget guard is your **safety net**, not your primary defense. Always run:

```bash
terraform destroy # immediately after finishing labs
```
