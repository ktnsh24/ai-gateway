# Cost Analysis — AI Gateway

> Per-service cost breakdown for AWS, Azure, and Local — including why we chose each service and what alternatives cost more.

**Related:** [Cost Tracking Deep Dive](cost-tracking-deep-dive.md) · [Architecture](../architecture-and-design/architecture.md)

## Table of Contents

- [Monthly Cost Summary](#monthly-cost-summary)
  - [Development (personal account)](#development-personal-account)
  - [Production (small scale)](#production-small-scale-1000-queriesdy)
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

| Service | AWS Cost/month | Azure Cost/month | Notes |
|---|---|---|---|
| LLM (pay-per-use) | ~$2–5 | ~$2–5 | Based on ~100 queries/day |
| Embeddings | ~$0.10 | ~$0.10 | For semantic cache similarity |
| Semantic Cache (Redis) | $0 (local) | $0 (local) | Run Redis in Docker |
| Cost Tracking (PostgreSQL) | $0 (local) | $0 (local) | Run PostgreSQL in Docker |
| Container Hosting | $0 (local) | $0 (local) | Run locally during development |
| **Total** | **~$2–5/month** | **~$2–5/month** | Mostly LLM token costs |

### Production (small scale: ~1000 queries/day)

| Service | AWS Cost/month | Azure Cost/month |
|---|---|---|
| LLM (routed via LiteLLM) | ~$50–100 | ~$40–80 |
| Embeddings (for cache) | ~$1–2 | ~$1–2 |
| Redis (ElastiCache / Azure Cache) | ~$15 (t3.micro) | ~$16 (C0 Basic) |
| PostgreSQL (RDS / Azure DB) | ~$15 (db.t3.micro) | ~$15 (B1ms) |
| Container Hosting | ~$30 (Fargate) | ~$20 (Container Apps) |
| **Total** | **~$115/month** | **~$95/month** |

> **Key insight:** The gateway itself is cheap — Redis and PostgreSQL are small instances. The LLM token costs dominate, which is exactly what the cost tracker monitors.

---

## Service-by-Service Breakdown

### LLM Inference (Routed via LiteLLM)

The gateway routes to multiple providers. Per-token costs are the same as V1 (rag-chatbot):

| | AWS Bedrock (Claude 3.5 Sonnet) | Azure OpenAI (GPT-4o) | Local (Ollama) |
|---|---|---|---|
| **Input tokens** | $0.003/1K | $0.0025/1K | **$0** |
| **Output tokens** | $0.015/1K | $0.01/1K | **$0** |
| **Per query (typical)** | ~$0.013 | ~$0.01 | **$0** |

**Gateway cost savings:**
- **Semantic cache:** ~30% fewer LLM calls for repeated/similar queries
- **Cost-optimised routing:** Route simple queries to cheaper models
- **Fallback routing:** Avoid expensive retries on failed providers

### Semantic Cache (Redis)

| Option | Cost/month | Persistence | Scales to zero? |
|---|---|---|---|
| **Docker (local)** | $0 | Restart = lost | N/A |
| **AWS ElastiCache (t3.micro)** | ~$15 | Yes | No |
| **Azure Cache for Redis (C0)** | ~$16 | Yes | No |
| **Upstash Redis (serverless)** | $0 (free: 10K cmd/day) | Yes | **Yes** |

**What we chose:**
- **Development:** Docker Redis (free, no cloud needed)
- **Production:** ElastiCache/Azure Cache (managed, persistent)
- **Budget alternative:** Upstash free tier (10K commands/day = ~300 queries)

### Cost Tracking Database (PostgreSQL)

| Option | Cost/month | Storage | Managed? |
|---|---|---|---|
| **Docker (local)** | $0 | Restart = lost | No |
| **AWS RDS (db.t3.micro)** | ~$15 | 20 GB | Yes |
| **Azure Database for PostgreSQL (B1ms)** | ~$15 | 32 GB | Yes |
| **Supabase (free tier)** | $0 (500 MB) | 500 MB | Yes |
| **In-memory (no persistence)** | $0 | None | N/A |

**What we chose:**
- **Development:** In-memory cost tracker (no PostgreSQL needed)
- **Production:** RDS/Azure PostgreSQL (managed, durable)
- **Budget alternative:** Supabase free tier (500 MB = months of usage logs)

### Rate Limiting

Rate limiting uses the same Redis instance as the cache — no additional cost.

---

## Cost Impact of Gateway Features

| Feature | Cloud Cost Impact | Token Savings |
|---|---|---|
| **Semantic cache (30% hit rate)** | +$15/month (Redis) | −30% LLM tokens (~$15–30/month) |
| **Rate limiting** | $0 (uses cache Redis) | Prevents runaway costs |
| **Cost tracking** | +$15/month (PostgreSQL) | Enables cost visibility |
| **Fallback routing** | $0 | Avoids failed requests ($0 wasted tokens) |
| **Cost-optimised routing** | $0 | Routes to cheapest provider |

**ROI at 1000 queries/day:**
- Cache saves ~$15–30/month in LLM tokens
- Redis costs ~$15/month
- **Net: break-even to +$15/month savings**
- Plus: visibility, rate control, and observability are invaluable

---

## What Alternatives Cost More

### Alternative 1: AWS API Gateway + Lambda instead of FastAPI

| | FastAPI on Fargate (our choice) | API Gateway + Lambda |
|---|---|---|
| **Architecture** | Single container | Serverless functions |
| **Min cost** | ~$30/month | ~$5/month (free tier) |
| **Latency** | ~10ms routing overhead | ~100–500ms (cold start) |
| **WebSocket support** | Yes (built-in) | Complex (API Gateway WS) |
| **State management** | In-process (Redis) | External only |

**Why FastAPI is better here:** The gateway is a long-running proxy — it holds Redis connections, caches state, and routes requests with low latency. Lambda cold starts (100–500ms) add unacceptable latency to every LLM call.

### Alternative 2: Kong/Tyk API Gateway instead of custom

| | Custom FastAPI gateway (our choice) | Kong/Tyk |
|---|---|---|
| **LLM-specific features** | Semantic cache, cost tracking | Generic rate limiting |
| **Cost** | ~$30/month (Fargate) | ~$50–200/month (managed) |
| **Customisation** | Full control | Plugin system |
| **Learning value** | High (built from scratch) | Low (managed service) |

**Why custom is better for a portfolio:** Building the gateway teaches rate limiting, caching, and cost tracking patterns. Kong/Tyk are great for production but don't demonstrate engineering skills.

### Alternative 3: Amazon Bedrock Guardrails instead of custom rate limiting

| | Custom rate limiter (our choice) | Bedrock Guardrails |
|---|---|---|
| **Per-API-key limits** | Yes | No (per-model only) |
| **Cost tracking** | Yes (per-request) | No |
| **Multi-provider** | Yes (AWS + Azure + Local) | AWS only |
| **Cost** | $0 (Redis) | $0 (included) |

**Why custom is better:** Bedrock Guardrails only works with Bedrock. Our gateway rate-limits across all providers with per-API-key granularity.

---

## Decision Summary

| Decision | Chosen | Alternative | Why chosen wins |
|---|---|---|---|
| Gateway framework | FastAPI (custom) | Kong/Tyk/AWS API Gateway | Full control, LLM-specific features, learning value |
| Cache | Redis (semantic) | None / DynamoDB | ~30% token savings, sub-ms lookup |
| Cost tracking | PostgreSQL (custom) | CloudWatch Metrics | Per-request granularity, queryable dashboards |
| Rate limiting | Redis (per-key) | Bedrock Guardrails | Multi-provider, per-API-key |
| Routing | LiteLLM | Direct API calls | Unified interface to 100+ providers |

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

| Provider | LLM Calls | Token Cost | Infrastructure | Total per Run |
|---|---|---|---|---|
| **Local (Ollama)** | ~20 | $0 | $0 (Docker) | **$0** |
| **AWS (Bedrock)** | ~20 | ~$0.26 | $0 (in-memory fallback) | **~$0.26** |
| **Azure (OpenAI)** | ~20 | ~$0.20 | $0 (in-memory fallback) | **~$0.20** |

> **Recommendation:** Run tests locally (Ollama = $0), then once on each cloud provider to verify routing. Total cloud cost: **~$0.50 one-time**.

---

## Budget Guard — Automatic Cost Protection

Both `infra/aws/` and `infra/azure/` include a **budget guard** (`budget.tf`) that automatically protects against runaway cloud costs.

### How it works

| Threshold | Action |
|---|---|
| **80% of limit (€4)** | Email warning sent to `alert_email` |
| **100% of limit (€5)** | Email + automatic resource kill switch triggered |

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
  default = 5  # €5 kill switch
}

variable "alert_email" {
  # Required — where budget warnings go
}
```

### ⚠️ Important caveat

Cloud cost reporting has a **6–24 hour lag**. The budget guard is your **safety net**, not your primary defense. Always run:

```bash
terraform destroy  # immediately after finishing labs
```
