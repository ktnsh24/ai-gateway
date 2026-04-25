# Cost Tracking Deep Dive — AI Gateway

> **What:** Per-request usage logging with aggregation queries for cost dashboards
>
> **Why:** LLM costs are opaque — tracking per-request gives visibility and control
>
> **File:** `src/gateway/cost_tracker.py`

---

## Table of Contents

1. [Why Track LLM Costs?](#1-why-track-llm-costs)
2. [Cost Tracker Strategy Pattern](#2-cost-tracker-strategy-pattern)
3. [Database Schema](#3-database-schema)
4. [Logging Usage](#4-logging-usage)
5. [Aggregation Queries](#5-aggregation-queries)
6. [Cost Estimation](#6-cost-estimation)
7. [PostgreSQL Implementation](#7-postgresql-implementation)
8. [In-Memory Fallback](#8-in-memory-fallback)
9. [Dashboard API](#9-dashboard-api)
10. [Certification Relevance](#10-certification-relevance)
11. [Cross-References](#11-cross-references)

---

## 1. Why Track LLM Costs?

| Without Tracking | With Tracking | 🚚 Courier |
|-----------------|--------------|-----------|
| Monthly bill is a surprise | Real-time cost visibility | 🚚 Without the expense ledger the monthly depot bill is a shock; with it you see every tokens spent in real time. |
| No per-model breakdown | Know which models cost most | 🚚 Without the ledger you can't tell if the Claude courier or the GPT-4o courier is burning most of your budget. |
| No cache ROI measurement | Measure cache hit rate savings | 🚚 Without tracking you can't prove the pickup locker is saving money — the ledger shows exactly how many LLM calls it averted. |
| No per-user attribution | Cost allocation by API key | 🚚 Without the ledger every courier's API key looks identical — you can't bill individual teams for their courier usage. |
| Can't optimise routing | Data-driven provider selection | 🚚 Without ledger data the dispatch desk picks blindly; with it you can steer shipping manifests toward the cheapest healthy courier. |

### Cost Visibility Example

```
GET /v1/usage?period=today

Total: $4.23 today
├── bedrock/claude-3-5-sonnet: $3.89 (422 requests, 156K tokens)
├── azure/gpt-4o: $0.34 (18 requests, 12K tokens)
├── ollama/llama3.2: $0.00 (89 requests, 34K tokens)
└── Cache hits: 23% (saved ~$1.27)
```

---

## 2. Cost Tracker Strategy Pattern

```python
class BaseCostTracker(ABC):
 """Abstract interface for cost tracking."""

 @abstractmethod
 async def log_usage(
 self,
 model: str,
 provider: str,
 prompt_tokens: int,
 completion_tokens: int,
 total_tokens: int,
 estimated_cost_usd: float,
 cached: bool,
 request_id: str | None = None,
 api_key_hash: str | None = None,
 ) -> None: ...

 @abstractmethod
 async def get_usage_summary(self, period: str = "today") -> dict: ...

 @abstractmethod
 async def close(self) -> None: ...
```

### Implementations

| Class | Backend | Use Case | 🚚 Courier |
|-------|---------|----------|-----------|
| `PostgresCostTracker` | PostgreSQL | Production — persistent, queryable | 🚚 The cloud-hosted ledger that survives restarts and answers complex SQL queries about which couriers cost the most. |
| `InMemoryCostTracker` | Python list | Development — no PostgreSQL needed | 🚚 A scribbled in-RAM receipt pile for development — no leather ledger required, but all records vanish when the gateway restarts. |
| `NoCostTracker` | None | Testing — no tracking | 🚚 No ledger at all during testing — every courier delivery completes without writing a single expense entry to keep tests fast. |

### Factory

```python
def create_cost_tracker(settings: Settings) -> BaseCostTracker:
 if not settings.cost_tracking_enabled:
 return NoCostTracker()
 if settings.postgresql_url:
 try:
 return PostgresCostTracker(settings)
 except Exception:
 return InMemoryCostTracker()
 return InMemoryCostTracker()
```

---

## 3. Database Schema

```sql
CREATE TABLE IF NOT EXISTS usage_logs (
 id SERIAL PRIMARY KEY,
 timestamp TIMESTAMPTZ DEFAULT NOW(),
 model VARCHAR(100) NOT NULL,
 provider VARCHAR(50) NOT NULL,
 prompt_tokens INTEGER NOT NULL DEFAULT 0,
 completion_tokens INTEGER NOT NULL DEFAULT 0,
 total_tokens INTEGER NOT NULL DEFAULT 0,
 estimated_cost_usd DECIMAL(10, 6) NOT NULL DEFAULT 0,
 cached BOOLEAN NOT NULL DEFAULT FALSE,
 request_id VARCHAR(100),
 api_key_hash VARCHAR(64)
);

-- Indexes for efficient aggregation queries
CREATE INDEX IF NOT EXISTS idx_usage_logs_timestamp ON usage_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_usage_logs_model ON usage_logs(model);
CREATE INDEX IF NOT EXISTS idx_usage_logs_provider ON usage_logs(provider);
```

### Why These Indexes?

| Index | Query Pattern | Speed | 🚚 Courier |
|-------|--------------|-------|-----------|
| `idx_timestamp` | `WHERE timestamp >= '2024-01-01'` (period filtering) | O(log n) | 🚚 The timestamp index lets the ledger flip directly to today's receipts without scanning every delivery ever recorded. |
| `idx_model` | `GROUP BY model` (per-model breakdown) | O(log n) | 🚚 The model index groups all Claude receipts together so you can total the AWS depot courier's bill in one fast pass. |
| `idx_provider` | `GROUP BY provider` (per-provider breakdown) | O(log n) | 🚚 The provider index groups all receipts by depot so the dispatch desk can compare AWS depot and Azure hub totals instantly. |

---

## 4. Logging Usage

Every request (cached or not) is logged:

```python
async def log_usage(
 self,
 model: str,
 provider: str,
 prompt_tokens: int,
 completion_tokens: int,
 total_tokens: int,
 estimated_cost_usd: float,
 cached: bool,
 request_id: str | None = None,
 api_key_hash: str | None = None,
) -> None:
 async with self.engine.begin() as conn:
 await conn.execute(
 text("""
 INSERT INTO usage_logs
 (model, provider, prompt_tokens, completion_tokens,
 total_tokens, estimated_cost_usd, cached, request_id, api_key_hash)
 VALUES
 (:model, :provider, :prompt_tokens, :completion_tokens,
 :total_tokens, :estimated_cost_usd, :cached, :request_id, :api_key_hash)
 """),
 {
 "model": model,
 "provider": provider,
 "prompt_tokens": prompt_tokens,
 "completion_tokens": completion_tokens,
 "total_tokens": total_tokens,
 "estimated_cost_usd": estimated_cost_usd,
 "cached": cached,
 "request_id": request_id,
 "api_key_hash": api_key_hash,
 },
 )
```

### What Gets Logged

| Field | Source | Example | 🚚 Courier |
|-------|--------|---------|-----------|
| `model` | LiteLLM response | `"ollama/llama3.2"` | 🚚 The adapter stamps which specific courier made the delivery so the expense ledger can tally costs per model type. |
| `provider` | Config | `"local"` | 🚚 The provider name is written into the receipt so the ledger can separate AWS, Azure, and local bills. |
| `prompt_tokens` | LLM usage | `25` | 🚚 The number of tokens loaded into the shipping manifests before the courier sets off — the inbound leg of the delivery. |
| `completion_tokens` | LLM usage | `150` | 🚚 The number of tokens written back in the courier's reply — the outbound leg that usually costs five times more. |
| `total_tokens` | LLM usage | `175` | 🚚 Inbound plus outbound tokens combined — the single number used to cross-check the expense estimate on the receipt. |
| `estimated_cost_usd` | Cost table lookup | `0.000525` | 🚚 The dispatch desk looks up the depot's price list and writes the delivery's dollar cost onto the ledger receipt immediately. |
| `cached` | Cache check result | `false` | 🚚 A flag marking whether the pickup locker served the reply or a live courier was dispatched — essential for measuring cache ROI. |
| `request_id` | Middleware | `"req_abc123"` | 🚚 A unique tag stamped on every shipping manifests so the gateway's observability stack and ledger can trace a single delivery end-to-end. |
| `api_key_hash` | Auth middleware | `"a1b2c3..."` | 🚚 A hashed copy of the courier's API key so the ledger can attribute costs per team without storing the real key. |

---

## 5. Aggregation Queries

### Period Filtering

```python
def _get_period_filter(self, period: str) -> str:
 filters = {
 "today": "timestamp >= CURRENT_DATE",
 "week": "timestamp >= CURRENT_DATE - INTERVAL '7 days'",
 "month": "timestamp >= CURRENT_DATE - INTERVAL '30 days'",
 "all": "1=1", # no filter
 }
 return filters.get(period, filters["today"])
```

### Summary Query

```sql
SELECT
 COUNT(*) as total_requests,
 SUM(total_tokens) as total_tokens,
 SUM(estimated_cost_usd) as total_cost,
 AVG(CASE WHEN cached THEN 1.0 ELSE 0.0 END) as cache_hit_rate
FROM usage_logs
WHERE timestamp >= CURRENT_DATE
```

### Per-Model Breakdown

```sql
SELECT
 model,
 COUNT(*) as requests,
 SUM(total_tokens) as tokens,
 SUM(estimated_cost_usd) as cost
FROM usage_logs
WHERE timestamp >= CURRENT_DATE
GROUP BY model
ORDER BY cost DESC
```

### Per-Provider Breakdown

```sql
SELECT
 provider,
 COUNT(*) as requests,
 SUM(estimated_cost_usd) as cost
FROM usage_logs
WHERE timestamp >= CURRENT_DATE
GROUP BY provider
ORDER BY cost DESC
```

---

## 6. Cost Estimation

LLM costs are estimated based on published pricing:

```python
COST_PER_1K_TOKENS = {
 "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0": {
 "input": 0.003,
 "output": 0.015,
 },
 "azure/gpt-4o": {
 "input": 0.005,
 "output": 0.015,
 },
 "ollama/llama3.2": {
 "input": 0.0,
 "output": 0.0,
 },
}

def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
 pricing = COST_PER_1K_TOKENS.get(model, {"input": 0.0, "output": 0.0})
 input_cost = (prompt_tokens / 1000) * pricing["input"]
 output_cost = (completion_tokens / 1000) * pricing["output"]
 return round(input_cost + output_cost, 6)
```

### Pricing Table

| Model | Input ($/1K) | Output ($/1K) | Notes | 🚚 Courier |
|-------|-------------|---------------|-------|-----------|
| Claude 3.5 Sonnet (Bedrock) | $0.003 | $0.015 | AWS markup included | 🚚 The AWS depot's Claude courier charges three tenths of a cent per thousand inbound tokens and five times that on the reply. |
| GPT-4o (Azure) | $0.005 | $0.015 | Azure pricing | 🚚 The Azure hub's GPT-4o courier costs half a cent per thousand inbound tokens and matches Claude's output rate exactly. |
| llama3.2 (Ollama) | $0.000 | $0.000 | Self-hosted, free | 🚚 The local environment llama3.2 courier works for fuel alone — zero tokens charges because the gateway is fully self-hosted. |
| nomic-embed-text (Ollama) | $0.000 | $0.000 | Self-hosted, free | 🚚 The local GPS-coordinate writer also works free — it runs in the same local environment and never touches a cloud depot's front door. |
| Titan Embed V2 (Bedrock) | $0.0001 | — | Embedding only | 🚚 AWS depot's GPS-coordinate writer charges one tenth of a cent per thousand tokens — no output rate because embeddings don't reply. |

---

## 7. PostgreSQL Implementation

### Async SQLAlchemy

```python
class PostgresCostTracker(BaseCostTracker):
 def __init__(self, settings: Settings) -> None:
 self.engine = create_async_engine(
 settings.postgresql_url,
 pool_size=5,
 max_overflow=10,
 pool_pre_ping=True,
 )
```

### Connection Pool Settings

| Setting | Value | Why | 🚚 Courier |
|---------|-------|-----|-----------|
| `pool_size` | 5 | Enough for typical gateway load | 🚚 Five permanent leather-ledger quills stay open and ready so the dispatch desk doesn't queue up waiting to write receipts. |
| `max_overflow` | 10 | Handle burst traffic | 🚚 Up to ten extra quills can be borrowed during a rush of deliveries and returned once the surge passes. |
| `pool_pre_ping` | True | Detect stale connections | 🚚 Before writing a receipt the gateway pokes the ledger connection to confirm it's alive — no silent write failures. |

### Auto-Schema Creation

The table is created on first use:

```python
async def _ensure_table(self) -> None:
 async with self.engine.begin() as conn:
 await conn.execute(text(CREATE_TABLE_SQL))
```

No Alembic migration needed for this single table — it's idempotent (`CREATE TABLE IF NOT EXISTS`).

---

## 8. In-Memory Fallback

```python
class InMemoryCostTracker(BaseCostTracker):
 def __init__(self) -> None:
 self._logs: list[dict] = []

 async def log_usage(self, **kwargs) -> None:
 self._logs.append({**kwargs, "timestamp": datetime.utcnow()})

 async def get_usage_summary(self, period: str = "today") -> dict:
 filtered = self._filter_by_period(period)
 return {
 "total_requests": len(filtered),
 "total_tokens": sum(l["total_tokens"] for l in filtered),
 "total_cost_usd": sum(l["estimated_cost_usd"] for l in filtered),
 ...
 }
```

### Limitations

| Feature | PostgreSQL | In-Memory | 🚚 Courier |
|---------|-----------|-----------|-----------|
| Persistence | ✅ | ❌ | 🚚 The ledger survives gateway restarts; the in-RAM receipt pile is wiped the moment the gateway shuts down. |
| Complex queries | SQL | Python filtering | 🚚 The ledger answers rich SQL questions about per-courier costs; the RAM pile needs manual Python loops to answer the same thing. |
| Scale | Millions of rows | ~10K logs in memory | 🚚 The leather ledger holds millions of delivery receipts; the RAM pile spills over after ten thousand and must be managed carefully. |
| Concurrency | ACID transactions | Single-process | 🚚 The ledger handles multiple dispatch desks writing at once with ACID guarantees; the RAM pile is safe only in a single-process depot. |

---

## 9. Dashboard API

### `GET /v1/usage?period=today`

```json
{
 "period": "today",
 "total_requests": 529,
 "total_tokens": 182450,
 "total_cost_usd": 4.23,
 "cache_hit_rate": 0.23,
 "by_model": {
 "bedrock/anthropic.claude-3-5-sonnet-v2": {
 "requests": 422,
 "tokens": 156000,
 "cost_usd": 3.89
 },
 "azure/gpt-4o": {
 "requests": 18,
 "tokens": 12000,
 "cost_usd": 0.34
 },
 "ollama/llama3.2": {
 "requests": 89,
 "tokens": 34000,
 "cost_usd": 0.0
 }
 },
 "by_provider": {
 "aws": {"requests": 422, "cost_usd": 3.89},
 "azure": {"requests": 18, "cost_usd": 0.34},
 "local": {"requests": 89, "cost_usd": 0.0}
 }
}
```

---

## 10. Certification Relevance

| Cert Topic | Connection | 🚚 Courier |
|------------|------------|-----------|
| **AWS SAA-C03: RDS** | PostgreSQL on RDS, connection pooling | 🚚 RDS hosts the expense ledger in the cloud — connection pooling keeps quills warm for the SAA-C03 exam. |
| **AWS SAA-C03: Cost Explorer** | Usage tracking = custom cost explorer | 🚚 The custom expense ledger is a hand-built Cost Explorer — every delivery receipt feeds the same per-courier cost dashboard. |
| **AZ-305: PostgreSQL Flexible Server** | Azure database for cost storage | 🚚 Azure's Flexible Server hosts the expense ledger at the Azure hub — same schema, different cloud postal address. |
| **AZ-305: Cost Management** | Building custom cost dashboards | 🚚 Querying the ledger by courier, depot, and time period is the hands-on proof of AZ-305 cost-management principles. |

---

## 11. Cross-References

| Topic | Document | 🚚 Courier |
|-------|----------|-----------|
| Architecture overview | [Architecture](../architecture-and-design/architecture.md) | 🚚 The full system architecture showing where the expense ledger slots into the overall dispatch desk design. |
| API usage endpoint | [API Contract](../architecture-and-design/api-contract.md) | 🚚 The expense ledger window endpoint spec — what JSON the gateway returns when asked for today's courier spend. |
| Caching (cache hit tracking) | [Caching Deep Dive](caching-deep-dive.md) | 🚚 How the pickup locker hit flag gets written to the expense ledger so cache ROI is visible in the cost dashboard. |
| Rate limiting (same Redis) | [Rate Limiting Deep Dive](rate-limiting-deep-dive.md) | 🚚 The daily dispatch quota enforcer shares the same pickup locker shelf the expense ledger uses for Redis-backed persistence. |
| Observability | [Observability Deep Dive](observability-deep-dive.md) | 🚚 gateway's observability stack and tachograph complement the expense ledger — metrics and traces add context to every cost entry. |
| PostgreSQL setup | [Docker Compose Guide](../setup-and-tooling/docker-compose-guide.md) | 🚚 How to spin up the ledger container inside the local Docker Compose setup for local development. |
| Lab: Cost dashboard | [Labs Phase 2](../hands-on-labs/hands-on-labs-phase-2.md) | 🚚 Hands-on exercises that query the expense ledger and build a per-courier cost dashboard from real delivery receipts. |
