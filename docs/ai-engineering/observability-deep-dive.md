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
 │ │ │
 ├─ Log: method, path ├─ Log: auth result ├─ Log: LLM call
 ├─ Add: X-Request-ID │ ├─ Log: cache hit/miss
 ├─ Start: timer │ ├─ Log: cost
 │ │ │
 └──────────────────────┴────────────────────┘
 │
 [Response Headers]
 X-Request-ID: req_abc123
 X-Gateway-Latency-Ms: 1523.45
```

### Components

| Component | What | Where | 🚚 Courier |
|-----------|------|-------|-----------|
| Request Logging | Method, path, status, timing | `middleware/logging.py` | 🚚 The gateway's observability stack records every delivery's method, path, and status code so nothing gets lost in the haystack. |
| Request IDs | Unique trace ID per request | `middleware/logging.py` | 🚚 Each delivery gets a unique tachograph stamp so you can trace one courier's journey end to end across all log lines. |
| Auth Logging | Authentication success/failure | `middleware/auth.py` | 🚚 The gatekeeper logs every accepted or rejected API key, creating a full audit trail at the gateway's entry point. |
| Cost Logging | Per-request cost to PostgreSQL | `gateway/cost_tracker.py` | 🚚 Every courier delivery's request cost gets written into the PostgreSQL expense ledger for later billing review. |
| LangFuse | LLM-specific tracing (optional) | `main.py` | 🚚 Optional observability upgrade that records which courier carried what shipping manifests and exactly how many tokens it consumed. |
| Health Check | Component status monitoring | `routes/health.py` | 🚚 The "is the courier awake?" check polls every depot component and reports whether the dispatch desk is ready to route. |

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
INFO: Request started | request_id=req_abc123 method=POST path=/v1/chat/completions client_ip=127.0.0.1
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

| Level | When | Example | 🚚 Courier |
|-------|------|---------|-----------|
| `DEBUG` | Detailed internal state | Cache key computation, embedding values | 🚚 Scribbles the most granular depot notes — cache key hashes and embedding coordinates only seen when debugging a confused courier. |
| `INFO` | Normal operations | Request start/complete, cache hit, LLM call | 🚚 Standard tachograph entry for each delivery — courier left, courier returned, pickup locker checked, tokens counted and logged. |
| `WARNING` | Degraded but working | Redis unavailable → fallback to in-memory | 🚚 The fast pickup locker shelf went offline, so the dispatch desk switched to sticky-note fallback but kept accepting shipping manifests. |
| `ERROR` | Request failure | LLM provider error, database connection failure | 🚚 A courier returned empty — either the far depot refused the delivery or the expense ledger database connection snapped. |
| `CRITICAL` | System failure | All providers down, app startup failure | 🚚 Every courier in the gateway is sick or the gateway crashed on startup — nothing is moving through the dispatch desk at all. |

### Key Log Points

| Location | Level | Message | 🚚 Courier |
|----------|-------|---------|-----------|
| `middleware/logging.py` | INFO | Request started/completed | 🚚 The tachograph stamps every delivery in and out, recording the courier's departure time and the final status code returned. |
| `middleware/auth.py` | WARNING | Authentication failure | 🚚 The gatekeeper logged a rejected API key — an unknown courier tried to manifest through the gateway's entry point uninvited. |
| `gateway/router.py` | INFO | LLM call to provider | 🚚 The dispatch desk logs which courier got the next delivery and which far depot — AWS depot, Azure hub, or local environment — it was routed to. |
| `gateway/router.py` | WARNING | Provider failed, trying fallback | 🚚 Primary courier is sick, so the dispatch desk is handing the shipping manifests to the backup courier in the fallback depot instead. |
| `gateway/cache.py` | INFO | Cache hit/miss | 🚚 The dispatch desk checked the pickup locker — either a pre-written reply was found instantly or the courier had to make a fresh delivery. |
| `gateway/cache.py` | WARNING | Redis unavailable | 🚚 The fast pickup locker shelf is offline; the dispatch desk fell back to scribbled sticky notes on the in-memory board instead. |
| `gateway/rate_limiter.py` | WARNING | Rate limit exceeded | 🚚 This courier has burned through their daily dispatch quota for the current window — no more deliveries until the clock resets in the next minute. |
| `gateway/cost_tracker.py` | INFO | Usage logged | 🚚 One parcel-unit tally was successfully written into the expense ledger for this provider's billing record. |
| `gateway/cost_tracker.py` | ERROR | PostgreSQL insert failed | 🚚 The expense ledger is locked or unreachable — this courier delivery's parcel costs will not appear in the provider billing report. |

---

## 5. Latency Measurement

### Gateway Latency Breakdown

```
Total Gateway Latency (X-Gateway-Latency-Ms)
├── Auth check: ~0.1ms
├── Rate limit check: ~1ms (Redis) / ~0.01ms (in-memory)
├── Cache lookup: ~1ms (exact) / ~5ms (semantic)
├── LLM call: 500-5000ms ← dominates
├── Cache store: ~1ms
├── Cost log: ~2ms
└── Serialisation: ~0.1ms
```

### Where Time Is Spent

```
With cache miss: ███████████████████████████████████████ 2000ms
 ^rate ^cache ^^^^^ LLM call ^^^^^^ ^log

With cache hit: ███ 5ms
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

| Metric | Source | Value | 🚚 Courier |
|--------|--------|-------|-----------|
| Traces | Each API request | Full request lifecycle | 🚚 One row in the monitoring feed timeline per API request, showing the full journey from depot door arrival to delivery receipt and back. |
| Generations | LLM calls | Model, tokens, latency | 🚚 Each individual courier call is recorded with the model name, parcel-unit count, and how many milliseconds the courier actually took. |
| Scores | Response quality | Optional feedback loop | 🚚 Optional quality ratings scribbled on the returned shipping manifests to evaluate whether the courier answered the question correctly. |
| Costs | Token pricing | Per-generation cost | 🚚 parcel-unit pricing is tallied per courier call so the expense ledger shows a real-time cost-per-generation breakdown by provider. |
| Prompts | System/user messages | Prompt versioning | 🚚 Every shipping manifests template is versioned in LangFuse so you can compare which instructions produced better courier responses over time. |

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

| State | Meaning | HTTP Status | 🚚 Courier |
|-------|---------|-------------|-----------|
| `healthy` | All components working | 200 | 🚚 All couriers are available, the fast pickup locker shelf is connected, and the expense ledger is accepting new entries. |
| `degraded` | Some components down (Redis/PG) | 200 | 🚚 The dispatch desk is still routing requests but the pickup locker shelf or expense ledger is temporarily disconnected or unreachable. |
| `unhealthy` | LLM router unavailable | 503 | 🚚 No couriers are available — the LLM router is offline and the gateway returns 503 to every caller at the front door. |

---

## 8. Production Observability

### AWS CloudWatch

From `infra/aws/main.tf`:

```hcl
resource "aws_cloudwatch_log_group" "gateway" {
 name = "/ecs/ai-gateway-${var.environment}"
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

| Metric | Threshold | Action | 🚚 Courier |
|--------|-----------|--------|-----------|
| Error rate | > 5% | Page on-call | 🚚 More than five in every hundred deliveries are coming back failed — page the on-call depot master to investigate immediately. |
| P99 latency | > 10s | Investigate provider | 🚚 The slowest one-percent of couriers are taking over ten seconds per delivery — investigate which far depot is causing the delays. |
| Cache hit rate | < 10% | Review cache config | 🚚 Fewer than one in ten questions matched a pre-written reply in the pickup locker — review the TTL setting and cosine-similarity threshold. |
| Cost/hour | > $50 | Alert + review routing | 🚚 The courier expense ledger is charging over fifty dollars per hour — alert the team and review which provider depot is overspending. |
| Redis memory | > 80% | Scale or evict | 🚚 The fast pickup locker shelf is more than eighty percent full — scale it up or configure eviction before cache misses start spiking. |

---

## 9. Certification Relevance

| Cert Topic | Connection | 🚚 Courier |
|------------|------------|-----------|
| **AWS SAA-C03: CloudWatch** | Logging, metrics, alarms | 🚚 CloudWatch is the AWS gateway's observability stack — it collects courier-delivery logs, raises cost alarms, and stores tachograph metrics for the exam. |
| **AWS SAA-C03: X-Ray** | Request tracing (X-Request-ID pattern) | 🚚 X-Ray is the AWS tachograph that traces each courier delivery across services, mirroring the X-Request-ID pattern used throughout the gateway. |
| **AZ-305: Azure Monitor** | Logging, metrics, diagnostics | 🚚 Azure Monitor is the Azure gateway's observability stack — it ingests container logs, Redis metrics, and diagnostic traces for the AZ-305 exam. |
| **AZ-305: Application Insights** | Request tracing, performance | 🚚 Application Insights is Azure's tachograph for tracing courier deliveries end-to-end across microservices and measuring delivery performance. |

---

## 10. Cross-References

| Topic | Document | 🚚 Courier |
|-------|----------|-----------|
| Architecture overview | [Architecture](../architecture-and-design/architecture.md) | 🚚 See how the full depot switchboard connects every courier, pickup locker shelf, and expense ledger in one system-context diagram. |
| Cost tracking dashboard | [Cost Tracking Deep Dive](cost-tracking-deep-dive.md) | 🚚 The expense ledger deep dive shows how every courier delivery's request cost is recorded, queried, and surfaced to callers. |
| Auth middleware | [API Contract](../architecture-and-design/api-contract.md) | 🚚 The permission-manifest rulebook explains exactly how the gateway's entry point validates API keys for incoming couriers at the gate. |
| AWS infrastructure | [Terraform Guide](../setup-and-tooling/terraform-guide.md) | 🚚 depot blueprints in Terraform provision the ECS Fargate box, ElastiCache pickup locker shelf, and RDS expense ledger on AWS. |
| Docker setup (LangFuse) | [Docker Compose Guide](../setup-and-tooling/docker-compose-guide.md) | 🚚 The local Docker Compose setup guide shows how to spin up the optional LangFuse observability upgrade with a single Docker Compose profile flag. |
