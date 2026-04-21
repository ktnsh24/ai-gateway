# AI Gateway — Central LLM Proxy

> **Phase 2** of the AI Engineering Portfolio — A production-grade LLM gateway that provides OpenAI-compatible API routing, semantic caching, rate limiting, and cost tracking across AWS Bedrock, Azure OpenAI, and local Ollama.

**Port:** 8100 · **Language:** Python 3.12 · **Framework:** FastAPI + LiteLLM

---

## Quick Links

### Getting Started

| Document | Description |
|---|---|
| [Getting Started](docs/setup-and-tooling/getting-started.md) | Prerequisites, installation, first run — step by step |
| [Docker Compose Guide](docs/setup-and-tooling/docker-compose-guide.md) | Full stack with Redis + PostgreSQL |
| [Terraform Guide](docs/setup-and-tooling/terraform-guide.md) | IaC for AWS + Azure deployment |
| [Debugging Guide](docs/setup-and-tooling/debugging-guide.md) | VS Code + PyCharm debugger setup |

### Architecture & Design

| Document | Description |
|---|---|
| [Architecture Overview](docs/architecture-and-design/architecture.md) | System design, data flow, gateway pipeline |
| [API Contract](docs/architecture-and-design/api-contract.md) | OpenAI-compatible API specification |

### AI Engineering

| Document | Description |
|---|---|
| [LiteLLM Deep Dive](docs/ai-engineering/litellm-deep-dive.md) | Unified LLM interface for 100+ providers |
| [Caching Deep Dive](docs/ai-engineering/caching-deep-dive.md) | Redis semantic cache with cosine similarity |
| [Rate Limiting Deep Dive](docs/ai-engineering/rate-limiting-deep-dive.md) | Fixed-window token bucket per API key |
| [Cost Tracking Deep Dive](docs/ai-engineering/cost-tracking-deep-dive.md) | PostgreSQL usage logging + dashboards |
| [Observability Deep Dive](docs/ai-engineering/observability-deep-dive.md) | Request tracing, LangFuse integration |
| [Cost Analysis](docs/ai-engineering/cost-analysis.md) | AWS vs Azure costs, alternatives, how to minimise spend |

### Hands-On Labs

| Document | Description |
|---|---|
| [Phase 1 — Foundation](docs/hands-on-labs/hands-on-labs-phase-1.md) | Setup, first request, provider switching |
| [Phase 2 — Production](docs/hands-on-labs/hands-on-labs-phase-2.md) | Caching, rate limiting, cost tracking |

### Testing & Reference

| Document | Description |
|---|---|
| [Testing Strategy & Inventory](docs/ai-engineering/testing.md) | All tests — unit, integration, E2E |
| [Pydantic Models](docs/reference/pydantic-models.md) | Every model explained — every field, why it exists |

---

## What Does This Project Do?

An **LLM API gateway** that sits between your applications and multiple LLM providers:

1. **Your app sends an OpenAI-format request** → the gateway authenticates, rate-limits, and checks cache
2. **Cache miss** → routes to the best LLM provider (Bedrock, Azure OpenAI, or Ollama)
3. **Response cached** → subsequent similar questions answered in <5ms
4. **Everything tracked** → tokens, cost, latency, cache hits logged to PostgreSQL

```
Client Request → API Key Auth → Rate Limiter → Semantic Cache
                                                    │
                                              (cache hit?) → Return cached
                                                    │ no
                                              LiteLLM Router → AWS Bedrock
                                                    │         → Azure OpenAI
                                                    │         → Ollama (local)
                                                    ↓
                                              Cache Store → Cost Log → Response
```

| Provider | LLM | Embeddings | Cost |
|---|---|---|---|
| **AWS** | Bedrock (Claude 3.5 Sonnet) | Titan Embed V2 (1024-dim) | ~$0.003/1K tokens |
| **Azure** | Azure OpenAI (GPT-4o) | text-embedding-3-small (1536-dim) | ~$0.0025/1K tokens |
| **Local** | Ollama (llama3.2) | nomic-embed-text (768-dim) | **$0** |

---

## Advanced Features

| Feature | What it does | Pattern |
|---|---|---|
| **Multi-provider routing** | Single, fallback, cost-optimised, round-robin | `RoutingStrategy` enum |
| **Semantic caching** | Cosine similarity on embeddings — similar prompts hit cache | Redis + `BaseCache` ABC |
| **Per-key rate limiting** | Fixed-window counter per API key (Redis or in-memory) | `BaseRateLimiter` ABC |
| **Cost tracking** | Per-request token/cost logging to PostgreSQL | `BaseCostTracker` ABC |
| **API key auth** | Optional Bearer token middleware | Toggle via `API_KEYS_ENABLED` |
| **LangFuse tracing** | Optional OpenTelemetry + LangFuse integration | Toggle via `LANGFUSE_ENABLED` |
| **Fallback routing** | Auto-failover to secondary provider on error | `FALLBACK_PROVIDER` config |

All features are **toggleable** via environment variables (`CACHE_ENABLED`, `RATE_LIMIT_ENABLED`, `COST_TRACKING_ENABLED`, `API_KEYS_ENABLED`).

---

## Project Structure

```
ai-gateway/
├── .github/workflows/          # CI/CD pipelines
├── docs/                       # Documentation (organised by topic)
│   ├── ai-engineering/         #   LiteLLM, caching, rate limiting, cost, observability, testing
│   ├── architecture-and-design/#   Architecture overview, API contract
│   ├── hands-on-labs/          #   2 phases of guided labs
│   ├── reference/              #   Pydantic models reference
│   └── setup-and-tooling/      #   Getting started, Docker, Terraform, debugging
├── infra/                      # Terraform (AWS + Azure)
│   ├── aws/                    #   ECS Fargate + ElastiCache + RDS
│   └── azure/                  #   Container Apps + Azure Cache + PostgreSQL
├── src/                        # Application source code
│   ├── config.py               #   Pydantic Settings (all env vars, routing strategy)
│   ├── main.py                 #   FastAPI factory + lifespan manager
│   ├── models.py               #   OpenAI-compatible request/response models
│   ├── gateway/                #   Core gateway components
│   │   ├── router.py           #   LLM routing via LiteLLM (strategy pattern)
│   │   ├── cache.py            #   Semantic cache (Redis / in-memory / no-op)
│   │   ├── rate_limiter.py     #   Rate limiting (Redis / in-memory / no-op)
│   │   └── cost_tracker.py     #   Usage logging (PostgreSQL / in-memory / no-op)
│   ├── middleware/              #   Request pipeline
│   │   ├── auth.py             #   API key authentication middleware
│   │   └── logging.py          #   Request/response logging middleware
│   └── routes/                 #   API endpoints
│       ├── health.py           #   GET /health — service status + connectivity
│       ├── completions.py      #   POST /v1/chat/completions — main gateway endpoint
│       ├── embeddings.py       #   POST /v1/embeddings — embedding proxy
│       ├── models.py           #   GET /v1/models — list available models
│       └── usage.py            #   GET /v1/usage — cost dashboard
├── tests/                      # Unit + integration tests
│   ├── test_health.py          #   Health, models, usage endpoints (8 tests)
│   ├── test_completions.py     #   Chat completions pipeline (12 tests)
│   ├── test_cache.py           #   InMemoryCache + NoCache (7 tests)
│   ├── test_rate_limiter.py    #   InMemoryRateLimiter + NoRateLimiter (7 tests)
│   └── test_cost_tracker.py    #   InMemoryCostTracker + NoCostTracker (6 tests)
├── pyproject.toml              # Poetry dependencies
├── Dockerfile                  # Container image
├── docker-compose.yml          # Full stack: app + Redis + PostgreSQL
└── .env.example                # Environment variable template
```

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/chat/completions` | Chat completion — OpenAI-compatible (main endpoint) |
| `POST` | `/v1/embeddings` | Text embeddings — OpenAI-compatible |
| `GET` | `/v1/models` | List available models across providers |
| `GET` | `/v1/usage` | Cost and usage dashboard (today / week / month) |
| `GET` | `/health` | Health check with Redis, PostgreSQL, LLM status |

---

## Quick Start

### Option 1: Local (no cloud, no cost)

```bash
# 1. Install Ollama and pull models
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2

# 2. Install dependencies
cd repos/ai-gateway && poetry install

# 3. Configure
cp .env.example .env
# Set CLOUD_PROVIDER=local in .env

# 4. Run
poetry run start
# → http://localhost:8100/docs
```

### Option 2: Docker Compose (with Redis + PostgreSQL)

```bash
docker compose up -d
# → Gateway: http://localhost:8100
# → Redis:   localhost:6379
# → PostgreSQL: localhost:5432
```

### Option 3: AWS or Azure

```bash
cp .env.example .env
# Set CLOUD_PROVIDER=aws (or azure) and add API keys

# Deploy + run all labs + destroy (automated)
./scripts/run_cloud_labs.sh --provider aws --email you@example.com

# Custom budget limit (default €5)
./scripts/run_cloud_labs.sh --provider aws --email you@example.com --cost-limit 15
```

Results saved to `scripts/lab_results/<aws|azure>/`.

See [Getting Started](docs/setup-and-tooling/getting-started.md) for the full step-by-step guide.

---

## Tech Stack

| Layer | AWS | Azure | Local |
|---|---|---|---|
| **Language** | Python 3.12 | Python 3.12 | Python 3.12 |
| **Framework** | FastAPI + LiteLLM | FastAPI + LiteLLM | FastAPI + LiteLLM |
| **LLM** | Bedrock (Claude 3.5 Sonnet) | Azure OpenAI (GPT-4o) | Ollama (llama3.2) |
| **Cache** | ElastiCache Redis | Azure Cache for Redis | Docker Redis / in-memory |
| **Cost DB** | RDS PostgreSQL | PostgreSQL Flexible | Docker PostgreSQL / in-memory |
| **Container** | ECS Fargate | Container Apps | Docker Compose |
| **Monitoring** | CloudWatch | App Insights | Console / LangFuse |

---

## Design Patterns

| Pattern | Where | Why |
|---|---|---|
| **Strategy (ABC + Factory)** | `BaseCache`, `BaseRateLimiter`, `BaseCostTracker`, `BaseLLMRouter` | Swap implementations without code changes |
| **Factory Method** | `create_cache()`, `create_rate_limiter()`, `create_cost_tracker()`, `create_router()` | Single entry point creates correct implementation |
| **Dependency Injection** | `request.app.state.*` | Components injected via FastAPI lifespan |
| **Pipeline** | Completions route | Auth → Rate Limit → Cache → LLM → Cache Store → Cost Log |
| **Graceful Degradation** | Cache/rate limiter factories | Redis unavailable → fall back to in-memory |

---

## Documentation Structure

```
docs/
├── ai-engineering/                     ← Deep-dives + testing
│   ├── litellm-deep-dive.md           ← LiteLLM unified interface
│   ├── caching-deep-dive.md           ← Semantic cache with cosine similarity
│   ├── rate-limiting-deep-dive.md     ← Fixed-window token bucket
│   ├── cost-tracking-deep-dive.md     ← PostgreSQL usage logging
│   ├── observability-deep-dive.md     ← Request tracing, LangFuse
│   ├── testing.md                     ← Test strategy & inventory
│   └── cost-analysis.md              ← AWS vs Azure costs, alternatives
├── architecture-and-design/           ← System design
│   ├── architecture.md                ← Architecture overview
│   └── api-contract.md               ← OpenAI-compatible API spec
├── hands-on-labs/                     ← Guided experiments
│   ├── hands-on-labs-phase-1.md       ← Foundation: setup, requests, providers
│   └── hands-on-labs-phase-2.md       ← Production: caching, rate limiting, cost
├── reference/                         ← Models reference
│   └── pydantic-models.md            ← Every model explained
└── setup-and-tooling/                 ← Getting started
    ├── getting-started.md             ← Full setup guide
    ├── docker-compose-guide.md        ← Docker Compose stack
    ├── terraform-guide.md             ← IaC deployment
    └── debugging-guide.md             ← Debugger setup
```

**Recommended reading order:**

1. [Architecture](docs/architecture-and-design/architecture.md) — how the gateway pipeline works
2. [Getting Started](docs/setup-and-tooling/getting-started.md) — run it locally
3. [LiteLLM Deep Dive](docs/ai-engineering/litellm-deep-dive.md) — the LLM routing engine
4. [Testing](docs/ai-engineering/testing.md) — how the codebase is tested

---

## Certification Relevance

| Gateway Concept | AWS Service | Exam Relevance |
|---|---|---|
| Semantic caching | ElastiCache Redis | SAA-C03: caching strategies |
| API rate limiting | API Gateway throttling | SAA-C03: API management |
| Cost tracking | Cost Explorer, CloudWatch | SAA-C03: cost optimisation |
| Fallback routing | Route 53, ALB | SAA-C03: high availability |
| IaC | Terraform → ECS, RDS, ElastiCache | SAA-C03: infrastructure automation |
| Container orchestration | ECS Fargate | SAA-C03: compute services |

---

**Phase:** Phase 2 (out of 5) · **Portfolio:** [Portfolio Overview](../../README.md)
