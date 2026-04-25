# Architecture Overview — AI Gateway

> **Pattern:** Strategy Pattern with ABC interfaces and factory methods
>
> **Framework:** FastAPI + LiteLLM
>
> **Port:** 8100

---

## Table of Contents

1. [System Context](#1-system-context)
2. [Component Architecture](#2-component-architecture)
3. [Request Flow](#3-request-flow)
4. [Strategy Pattern Implementation](#4-strategy-pattern-implementation)
5. [Data Flow](#5-data-flow)
6. [Deployment Architecture](#6-deployment-architecture)
7. [Cross-References](#7-cross-references)

---

## 1. System Context

The AI Gateway sits between client applications and LLM providers, adding a unified API layer with caching, rate limiting, cost tracking, and observability.

```
┌──────────────────────────────────────────────────────────────┐
│                        Client Apps                           │
│  (RAG Chatbot, AI Agent, MCP Server, Multi-Agent System)     │
└────────────────────────────┬─────────────────────────────────┘
                             │ HTTP (OpenAI-compatible)
                             ▼
┌──────────────────────────────────────────────────────────────┐
│                      AI Gateway (:8100)                       │
│  ┌──────────┐  ┌────────────┐  ┌───────┐  ┌──────────────┐  │
│  │ Auth     │→ │ Rate Limit │→ │ Cache │→ │ LLM Router   │  │
│  │ Middleware│  │            │  │       │  │ (LiteLLM)    │  │
│  └──────────┘  └────────────┘  └───────┘  └──────┬───────┘  │
│                                                    │          │
│  ┌──────────────┐  ┌───────────────┐              │          │
│  │ Cost Tracker │← │ Observability │←─────────────┘          │
│  └──────────────┘  └───────────────┘                         │
└──────────────────────────────────────────────────────────────┘
         │                │                    │
         ▼                ▼                    ▼
┌──────────┐    ┌──────────────┐    ┌──────────────────────┐
│  Redis   │    │  PostgreSQL  │    │   LLM Providers      │
│ (Cache + │    │ (Cost logs)  │    │ ┌─────────────────┐  │
│  Rate    │    │              │    │ │ AWS Bedrock      │  │
│  Limit)  │    │              │    │ │ Azure OpenAI     │  │
│          │    │              │    │ │ Ollama (local)   │  │
└──────────┘    └──────────────┘    │ └─────────────────┘  │
                                    └──────────────────────┘
```

---

## 2. Component Architecture

### 2.1 Core Gateway Components

Each component follows the **Strategy Pattern**: an abstract base class (ABC) with multiple implementations, selected at runtime via a factory function.

| Component | ABC | Implementations | Factory | 🚚 Courier |
|-----------|-----|-----------------|---------|-----------|
| **LLM Router** | `BaseLLMRouter` | `LiteLLMRouter` | `create_router()` | 🚚 The dispatch desk that picks which courier takes the next delivery — LiteLLM provides the universal harness so any provider depot fits the same reins. |
| **Cache** | `BaseCache` | `RedisSemanticCache`, `InMemoryCache`, `NoCache` | `create_cache()` | 🚚 The pickup locker shelf swaps between Redis fast shelf, in-memory sticky notes, and a no-op discard — the factory picks based on env vars at boot. |
| **Rate Limiter** | `BaseRateLimiter` | `RedisRateLimiter`, `InMemoryRateLimiter`, `NoRateLimiter` | `create_rate_limiter()` | 🚚 The per-minute delivery cap swaps between Redis-backed distributed counting and single-process in-memory counting depending on whether Redis is reachable. |
| **Cost Tracker** | `BaseCostTracker` | `PostgresCostTracker`, `InMemoryCostTracker`, `NoCostTracker` | `create_cost_tracker()` | 🚚 The expense tab swaps between the PostgreSQL log, in-memory running totals, and a no-op sink used during testing. |

### 2.2 File Layout

```
src/
├── main.py              ← App factory + lifespan (init components)
├── config.py            ← Pydantic Settings (env vars → typed config)
├── models.py            ← Request/response Pydantic models
├── gateway/
│   ├── router.py        ← BaseLLMRouter → LiteLLMRouter
│   ├── cache.py         ← BaseCache → Redis/InMemory/No
│   ├── rate_limiter.py  ← BaseRateLimiter → Redis/InMemory/No
│   └── cost_tracker.py  ← BaseCostTracker → Postgres/InMemory/No
├── routes/
│   ├── completions.py   ← POST /v1/chat/completions
│   ├── embeddings.py    ← POST /v1/embeddings
│   ├── models.py        ← GET /v1/models
│   ├── usage.py         ← GET /v1/usage
│   └── health.py        ← GET /health
└── middleware/
    ├── auth.py          ← API key authentication
    └── logging.py       ← Request timing + IDs
```

---

## 3. Request Flow

### 3.1 Chat Completion Flow

```
POST /v1/chat/completions
│
├─ 1. APIKeyMiddleware (if enabled)
│     Check Bearer token against allowed keys
│     → 401 if invalid
│
├─ 2. RequestLoggingMiddleware
│     Generate request ID, start timer
│     Add X-Request-ID, X-Gateway-Latency-Ms headers
│
├─ 3. Rate Limiter Check
│     rate_limiter.check_rate_limit(api_key)
│     → 429 if exceeded
│
├─ 4. Semantic Cache Lookup
│     cache.get(messages)
│     Cache key = SHA-256(canonical JSON of messages + model + temperature)
│     If exact match → return cached response (cache_hit=true)
│     If semantic match (cosine sim > 0.92) → return cached
│
├─ 5. LLM Router
│     router.route_completion(request)
│     LiteLLM translates to provider-specific format:
│       aws    → bedrock/anthropic.claude-3-5-sonnet-v2
│       azure  → azure/gpt-4o
│       local  → ollama/llama3.2
│
├─ 6. Cache Store
│     cache.set(messages, response)
│     Store response with TTL (default 3600s)
│
├─ 7. Cost Tracking
│     cost_tracker.log_usage(model, provider, tokens, cost, cached)
│     INSERT INTO usage_logs
│
└─ 8. Return Response
      OpenAI-compatible + gateway extensions:
      {cost, cache_hit, gateway_latency_ms}
```

### 3.2 Fallback Routing

When `ROUTING_STRATEGY=fallback`:

```
Request → Try primary provider (e.g., AWS Bedrock)
              │
              ├─ Success → Return response
              │
              └─ Failure → Try fallback (e.g., Ollama)
                    │
                    ├─ Success → Return response
                    │
                    └─ Failure → 503 Service Unavailable
```

Fallback providers configured via `FALLBACK_PROVIDERS=aws,azure,local` (comma-separated, tried in order).

---

## 4. Strategy Pattern Implementation

### Why Strategy Pattern?

The gateway must support multiple backends for each concern (caching, rate limiting, cost tracking) without changing the route logic. The Strategy Pattern lets us:

1. **Swap implementations** via env vars — no code changes
2. **Add new backends** — just add a class implementing the ABC
3. **Test easily** — inject `InMemory*` or `No*` implementations
4. **Graceful degradation** — if Redis is unavailable, fall back to in-memory

### Pattern Structure

```python
# 1. Define the interface (ABC)
class BaseCache(ABC):
    @abstractmethod
    async def get(self, messages: list[dict]) -> dict | None: ...
    @abstractmethod
    async def set(self, messages: list[dict], response: dict) -> None: ...

# 2. Implement variants
class RedisSemanticCache(BaseCache): ...
class InMemoryCache(BaseCache): ...
class NoCache(BaseCache): ...

# 3. Factory selects implementation
def create_cache(settings: Settings) -> BaseCache:
    if not settings.cache_enabled:
        return NoCache()
    if settings.redis_url:
        return RedisSemanticCache(settings)
    return InMemoryCache(settings)

# 4. Route code uses the interface
async def chat_completions(request, cache: BaseCache):
    cached = await cache.get(request.messages)  # Works with ANY impl
```

### Component Dependencies

```
main.py (lifespan)
  ├── create_router(settings) → BaseLLMRouter
  ├── create_cache(settings) → BaseCache
  ├── create_rate_limiter(settings) → BaseRateLimiter
  └── create_cost_tracker(settings) → BaseCostTracker

All stored on app.state.* and accessed via dependency injection in routes.
```

---

## 5. Data Flow

### 5.1 Cache Key Generation

```python
# Exact match key (SHA-256)
key_data = json.dumps({
    "messages": messages,
    "model": model,
    "temperature": temperature
}, sort_keys=True)
cache_key = f"gateway:cache:{hashlib.sha256(key_data.encode()).hexdigest()}"

# Semantic match — embed the last user message, compare cosine similarity
embedding = embed(last_user_message)
for stored_key, stored_embedding in index:
    if cosine_similarity(embedding, stored_embedding) > 0.92:
        return stored_response
```

### 5.2 Cost Tracking Schema

```sql
CREATE TABLE IF NOT EXISTS usage_logs (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    model VARCHAR(100),
    provider VARCHAR(50),
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    estimated_cost_usd DECIMAL(10, 6),
    cached BOOLEAN DEFAULT FALSE,
    request_id VARCHAR(100),
    api_key_hash VARCHAR(64)
);

CREATE INDEX idx_usage_logs_timestamp ON usage_logs(timestamp);
CREATE INDEX idx_usage_logs_model ON usage_logs(model);
```

### 5.3 Rate Limiting Algorithm

Fixed-window counter using Redis `INCR` + `EXPIRE`:

```
Key: gateway:rate:{api_key_hash}:{window_minute}
Value: request count
TTL: 60 seconds (auto-cleanup)

Check: GET key → if count >= limit → 429
       else → INCR key → if new key → EXPIRE 60
```

---

## 6. Deployment Architecture

### 6.1 Local Development

```
docker compose up -d
├── app (FastAPI :8100)
├── redis (Redis 7 :6379)
├── pg (PostgreSQL 16 :5432)
└── langfuse (optional :3000)
```

### 6.2 AWS Production

```
VPC
├── Public Subnet
│   └── ALB → ECS Fargate (AI Gateway container)
├── Private Subnet
│   ├── ElastiCache Redis (t3.micro, 1 node)
│   └── RDS PostgreSQL 16 (t3.micro)
└── ECR (container registry)
```

### 6.3 Azure Production

```
Resource Group
├── Container App Environment
│   └── Container App (AI Gateway)
├── Azure Cache for Redis (Basic C0)
└── PostgreSQL Flexible Server (B1ms)
```

---

## 7. Cross-References

| Topic | Document | 🚚 Courier |
|-------|----------|-----------|
| Setup instructions | [Getting Started](../setup-and-tooling/getting-started.md) | 🚚 The getting-started guide walks through booting the portable stack and sending the first shipping manifest through the front door. |
| API specification | [API Contract](api-contract.md) | 🚚 The API contract lists every endpoint, field, and error code the gateway's front door accepts and returns to courier clients. |
| LiteLLM routing details | [LiteLLM Deep Dive](../ai-engineering/litellm-deep-dive.md) | 🚚 The LiteLLM deep dive explains how the universal harness translates one shipping manifest format into provider-specific dialects for each remote depot. |
| Caching implementation | [Caching Deep Dive](../ai-engineering/caching-deep-dive.md) | 🚚 The pickup locker deep dive covers how the gateway stores and retrieves pre-written replies using semantic cosine-similarity matching. |
| Rate limiting details | [Rate Limiting Deep Dive](../ai-engineering/rate-limiting-deep-dive.md) | 🚚 The daily-dispatch-quota deep dive explains the fixed-window counter, per-courier Redis keys, and the 429 response when the quota runs out. |
| Cost tracking details | [Cost Tracking Deep Dive](../ai-engineering/cost-tracking-deep-dive.md) | 🚚 The expense ledger deep dive covers how each delivery's token count is costed and persisted in the PostgreSQL leather-bound log. |
| Observability | [Observability Deep Dive](../ai-engineering/observability-deep-dive.md) | 🚚 The observability dashboard deep dive covers request logging middleware, tachograph IDs, latency headers, and the optional LangFuse CCTV upgrade. |
| Pydantic models | [Pydantic Models Reference](../reference/pydantic-models.md) | 🚚 The Pydantic reference lists every request and response parcel schema the gateway uses to validate shipping manifests and receipts. |
| Docker setup | [Docker Compose Guide](../setup-and-tooling/docker-compose-guide.md) | 🚚 The portable stack guide explains the Docker Compose file that spins up app, Redis, PostgreSQL, and optional LangFuse together. |
| Terraform | [Terraform Guide](../setup-and-tooling/terraform-guide.md) | 🚚 The infrastructure blueprints guide covers Terraform modules that provision AWS ECS, ElastiCache, RDS, and the Azure equivalents in production. |
