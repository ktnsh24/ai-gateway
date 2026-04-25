# Observability Deep Dive — AI Gateway

> **What:** Request logging, timing, tracing, and optional LangFuse integration
>
> **Why:** You can't improve what you can't measure — observability is critical for production LLM systems
>
> **Files:** `src/middleware/logging.py`, `src/middleware/auth.py`, `src/main.py`

---

## Table of Contents

1. [Observability Stack](#1-observability-stack)
2. [Request Logging Middleware](#2-request-logging-middleware)
3. [Request ID Tracing](#3-request-id-tracing)
4. [Structured Logging](#4-structured-logging)
5. [Latency Measurement](#5-latency-measurement)
6. [LangFuse Integration](#6-langfuse-integration)
7. [Health Check Monitoring](#7-health-check-monitoring)
8. [Production Observability](#8-production-observability)
9. [Certification Relevance](#9-certification-relevance)
10. [Cross-References](#10-cross-references)

---

## 1. Observability Stack

```
Request → [Logging Middleware] → [Auth Middleware] → [Route Handler]
              │                      │                    │
              ├─ Log: method, path   ├─ Log: auth result  ├─ Log: LLM call
              ├─ Add: X-Request-ID   │                    ├─ Log: cache hit/miss
              ├─ Start: timer        │                    ├─ Log: cost
              │                      │                    │
              └──────────────────────┴────────────────────┘
                                     │
                           [Response Headers]
                           X-Request-ID: req_abc123
                           X-Gateway-Latency-Ms: 1523.45
```

### Components

| Component | What | Where |
|-----------|------|-------|
| Request Logging | Method, path, status, timing | `middleware/logging.py` |
| Request IDs | Unique trace ID per request | `middleware/logging.py` |
| Auth Logging | Authentication success/failure | `middleware/auth.py` |
| Cost Logging | Per-request cost to PostgreSQL | `gateway/cost_tracker.py` |
| LangFuse | LLM-specific tracing (optional) | `main.py` |
| Health Check | Component status monitoring | `routes/health.py` |

---

## 2. Request Logging Middleware

```python
class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", f"req_{uuid4().hex[:12]}")
        start_time = time.perf_counter()

        # Attach request ID to request state
        request.state.request_id = request_id

        logger.info(
            "Request started",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "client_ip": request.client.host if request.client else "unknown",
            },
        )

        response = await call_next(request)

        duration_ms = (time.perf_counter() - start_time) * 1000

        # Add trace headers to response
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Gateway-Latency-Ms"] = f"{duration_ms:.2f}"

        logger.info(
            "Request completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
            },
        )

        return response
```

### What Gets Logged

Every request produces two log lines:

```
INFO: Request started  | request_id=req_abc123 method=POST path=/v1/chat/completions client_ip=127.0.0.1
INFO: Request completed | request_id=req_abc123 method=POST path=/v1/chat/completions status=200 duration_ms=1523.45
```

---

## 3. Request ID Tracing

### Flow

```
Client → sends X-Request-ID: "my-trace-123"
  → Gateway uses "my-trace-123" (client-provided)

Client → no X-Request-ID header
  → Gateway generates "req_a1b2c3d4e5f6" (auto-generated)
```

### Response Headers

```http
HTTP/1.1 200 OK
X-Request-ID: req_abc123
X-Gateway-Latency-Ms: 1523.45
Content-Type: application/json
```

### Why Request IDs Matter

1. **Correlation** — Match gateway logs with provider logs
2. **Debugging** — Find the exact request that failed
3. **Client tracing** — Clients pass their own IDs for end-to-end tracing
4. **Cost attribution** — Link `usage_logs.request_id` to request logs

---

## 4. Structured Logging

### Log Format

```python
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
```

### Log Levels

| Level | When | Example |
|-------|------|---------|
| `DEBUG` | Detailed internal state | Cache key computation, embedding values |
| `INFO` | Normal operations | Request start/complete, cache hit, LLM call |
| `WARNING` | Degraded but working | Redis unavailable → fallback to in-memory |
| `ERROR` | Request failure | LLM provider error, database connection failure |
| `CRITICAL` | System failure | All providers down, app startup failure |

### Key Log Points

| Location | Level | Message |
|----------|-------|---------|
| `middleware/logging.py` | INFO | Request started/completed |
| `middleware/auth.py` | WARNING | Authentication failure |
| `gateway/router.py` | INFO | LLM call to provider |
| `gateway/router.py` | WARNING | Provider failed, trying fallback |
| `gateway/cache.py` | INFO | Cache hit/miss |
| `gateway/cache.py` | WARNING | Redis unavailable |
| `gateway/rate_limiter.py` | WARNING | Rate limit exceeded |
| `gateway/cost_tracker.py` | INFO | Usage logged |
| `gateway/cost_tracker.py` | ERROR | PostgreSQL insert failed |

---

## 5. Latency Measurement

### Gateway Latency Breakdown

```
Total Gateway Latency (X-Gateway-Latency-Ms)
├── Auth check:        ~0.1ms
├── Rate limit check:  ~1ms (Redis) / ~0.01ms (in-memory)
├── Cache lookup:      ~1ms (exact) / ~5ms (semantic)
├── LLM call:          500-5000ms ← dominates
├── Cache store:       ~1ms
├── Cost log:          ~2ms
└── Serialisation:     ~0.1ms
```

### Where Time Is Spent

```
With cache miss:  ███████████████████████████████████████ 2000ms
                  ^rate ^cache   ^^^^^ LLM call ^^^^^^  ^log

With cache hit:   ███ 5ms
                  ^rate ^cache hit → return immediately
```

Cache hits are **400× faster** than cache misses.

---

## 6. LangFuse Integration

LangFuse provides LLM-specific observability: token usage, prompt analysis, evaluation.

### Setup

```bash
# docker-compose.yml includes optional LangFuse:
docker compose --profile langfuse up -d

# Environment variables:
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=http://localhost:3000
```

### What LangFuse Tracks

| Metric | Source | Value |
|--------|--------|-------|
| Traces | Each API request | Full request lifecycle |
| Generations | LLM calls | Model, tokens, latency |
| Scores | Response quality | Optional feedback loop |
| Costs | Token pricing | Per-generation cost |
| Prompts | System/user messages | Prompt versioning |

### LangFuse Dashboard

```
LangFuse UI (localhost:3000)
├── Traces — Request timeline with all steps
├── Generations — LLM calls with token counts
├── Scores — Quality metrics (if configured)
├── Costs — Token costs over time
└── Prompts — Prompt templates and versions
```

---

## 7. Health Check Monitoring

### `GET /health`

```python
@router.get("/health")
async def health_check(request: Request):
    components = {}

    # Check Redis
    try:
        cache = request.app.state.cache
        if hasattr(cache, "redis"):
            await cache.redis.ping()
            components["redis"] = "connected"
        else:
            components["redis"] = "not_configured"
    except Exception:
        components["redis"] = "disconnected"

    # Check PostgreSQL
    try:
        tracker = request.app.state.cost_tracker
        if hasattr(tracker, "engine"):
            async with tracker.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            components["postgresql"] = "connected"
        else:
            components["postgresql"] = "not_configured"
    except Exception:
        components["postgresql"] = "disconnected"

    # Check LLM router
    try:
        models = await request.app.state.router.list_models()
        components["llm_router"] = "ready"
        components["models_available"] = [m.id for m in models]
    except Exception:
        components["llm_router"] = "unavailable"

    status = "healthy" if components.get("llm_router") == "ready" else "degraded"
    return {"status": status, "version": "0.1.0", "components": components}
```

### Health States

| State | Meaning | HTTP Status |
|-------|---------|-------------|
| `healthy` | All components working | 200 |
| `degraded` | Some components down (Redis/PG) | 200 |
| `unhealthy` | LLM router unavailable | 503 |

---

## 8. Production Observability

### AWS CloudWatch

From `infra/aws/main.tf`:

```hcl
resource "aws_cloudwatch_log_group" "gateway" {
  name              = "/ecs/ai-gateway-${var.environment}"
  retention_in_days = 30
}
```

Key CloudWatch metrics:
- **ECS**: CPU/memory utilisation, task count
- **ElastiCache**: Cache hit rate, memory usage, connections
- **RDS**: CPU, connections, IOPS, storage

### Azure Monitor

From `infra/azure/main.tf`:
- Container App logs → Azure Monitor
- Redis metrics → Azure Monitor
- PostgreSQL metrics → Azure Monitor

### Alerts to Configure

| Metric | Threshold | Action |
|--------|-----------|--------|
| Error rate | > 5% | Page on-call |
| P99 latency | > 10s | Investigate provider |
| Cache hit rate | < 10% | Review cache config |
| Cost/hour | > $50 | Alert + review routing |
| Redis memory | > 80% | Scale or evict |

---

## 9. Certification Relevance

| Cert Topic | Connection |
|------------|------------|
| **AWS SAA-C03: CloudWatch** | Logging, metrics, alarms |
| **AWS SAA-C03: X-Ray** | Request tracing (X-Request-ID pattern) |
| **AZ-305: Azure Monitor** | Logging, metrics, diagnostics |
| **AZ-305: Application Insights** | Request tracing, performance |

---

## 10. Cross-References

| Topic | Document |
|-------|----------|
| Architecture overview | [Architecture](../architecture-and-design/architecture.md) |
| Cost tracking dashboard | [Cost Tracking Deep Dive](cost-tracking-deep-dive.md) |
| Auth middleware | [API Contract](../architecture-and-design/api-contract.md) |
| AWS infrastructure | [Terraform Guide](../setup-and-tooling/terraform-guide.md) |
| Docker setup (LangFuse) | [Docker Compose Guide](../setup-and-tooling/docker-compose-guide.md) |
