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

| Component | What | Where | 🫏 Donkey |
|-----------|------|-------|-----------|
| Request Logging | Method, path, status, timing | `middleware/logging.py` | 🫏 The stable's CCTV records every trip's method, path, and status code so nothing gets lost in the haystack. |
| Request IDs | Unique trace ID per request | `middleware/logging.py` | 🫏 Each trip gets a unique tachograph stamp so you can trace one donkey's journey end to end across all log lines. |
| Auth Logging | Authentication success/failure | `middleware/auth.py` | 🫏 The gatekeeper logs every accepted or rejected permission slip, creating a full audit trail at the stable's front door. |
| Cost Logging | Per-request cost to PostgreSQL | `gateway/cost_tracker.py` | 🫏 Every donkey trip's cargo cost gets written into the leather-bound PostgreSQL expense ledger for later billing review. |
| LangFuse | LLM-specific tracing (optional) | `main.py` | 🫏 Optional CCTV upgrade that records which donkey carried what delivery note and exactly how many cargo units it consumed. |
| Health Check | Component status monitoring | `routes/health.py` | 🫏 The "is the donkey awake?" check polls every stable component and reports whether the dispatch desk is ready to route. |

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

| Level | When | Example | 🫏 Donkey |
|-------|------|---------|-----------|
| `DEBUG` | Detailed internal state | Cache key computation, embedding values | 🫏 Scribbles the most granular stable notes — cache key hashes and embedding coordinates only seen when debugging a confused donkey. |
| `INFO` | Normal operations | Request start/complete, cache hit, LLM call | 🫏 Standard tachograph entry for each trip — donkey left, donkey returned, pigeon-hole checked, cargo units counted and logged. |
| `WARNING` | Degraded but working | Redis unavailable → fallback to in-memory | 🫏 The fast pigeon-hole shelf went offline, so the dispatch desk switched to sticky-note fallback but kept accepting delivery notes. |
| `ERROR` | Request failure | LLM provider error, database connection failure | 🫏 A donkey returned empty — either the far stable refused the trip or the leather-bound expense ledger database connection snapped. |
| `CRITICAL` | System failure | All providers down, app startup failure | 🫏 Every donkey in the stable is sick or the stable manager crashed on startup — nothing is moving through the dispatch desk at all. |

### Key Log Points

| Location | Level | Message | 🫏 Donkey |
|----------|-------|---------|-----------|
| `middleware/logging.py` | INFO | Request started/completed | 🫏 The tachograph stamps every trip in and out, recording the donkey's departure time and the final status code returned. |
| `middleware/auth.py` | WARNING | Authentication failure | 🫏 The gatekeeper logged a rejected permission slip — an unknown courier tried to slip through the stable's front door uninvited. |
| `gateway/router.py` | INFO | LLM call to provider | 🫏 The dispatch desk logs which donkey got the next trip and which far stable — AWS depot, Azure hub, or local barn — it was routed to. |
| `gateway/router.py` | WARNING | Provider failed, trying fallback | 🫏 Primary donkey is sick, so the dispatch desk is handing the delivery note to the backup donkey in the fallback stable instead. |
| `gateway/cache.py` | INFO | Cache hit/miss | 🫏 The dispatch desk checked the pigeon-hole — either a pre-written reply was found instantly or the donkey had to make a fresh trip. |
| `gateway/cache.py` | WARNING | Redis unavailable | 🫏 The fast pigeon-hole shelf is offline; the dispatch desk fell back to scribbled sticky notes on the in-memory board instead. |
| `gateway/rate_limiter.py` | WARNING | Rate limit exceeded | 🫏 This courier has burned through their trip quota for the current window — no more deliveries until the clock resets in the next minute. |
| `gateway/cost_tracker.py` | INFO | Usage logged | 🫏 One cargo-unit tally was successfully written into the leather-bound expense ledger for this provider's billing record. |
| `gateway/cost_tracker.py` | ERROR | PostgreSQL insert failed | 🫏 The expense ledger is locked or unreachable — this donkey trip's cargo costs will not appear in the provider billing report. |

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

| Metric | Source | Value | 🫏 Donkey |
|--------|--------|-------|-----------|
| Traces | Each API request | Full request lifecycle | 🫏 One row in the CCTV timeline per API request, showing the full journey from stable door arrival to delivery receipt and back. |
| Generations | LLM calls | Model, tokens, latency | 🫏 Each individual donkey call is recorded with the model name, cargo-unit count, and how many milliseconds the donkey actually took. |
| Scores | Response quality | Optional feedback loop | 🫏 Optional quality ratings scribbled on the returned delivery note to evaluate whether the donkey answered the question correctly. |
| Costs | Token pricing | Per-generation cost | 🫏 Cargo-unit pricing is tallied per donkey call so the expense ledger shows a real-time cost-per-generation breakdown by provider. |
| Prompts | System/user messages | Prompt versioning | 🫏 Every delivery note template is versioned in LangFuse so you can compare which instructions produced better donkey responses over time. |

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

| State | Meaning | HTTP Status | 🫏 Donkey |
|-------|---------|-------------|-----------|
| `healthy` | All components working | 200 | 🫏 All donkeys are awake, the fast pigeon-hole shelf is connected, and the leather-bound expense ledger is accepting new entries. |
| `degraded` | Some components down (Redis/PG) | 200 | 🫏 The dispatch desk is still routing trips but the pigeon-hole shelf or expense ledger is temporarily disconnected or unreachable. |
| `unhealthy` | LLM router unavailable | 503 | 🫏 No donkeys are available at all — the LLM router is offline and the stable returns 503 to every caller at the front door. |

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

| Metric | Threshold | Action | 🫏 Donkey |
|--------|-----------|--------|-----------|
| Error rate | > 5% | Page on-call | 🫏 More than five in every hundred deliveries are coming back failed — page the on-call stable master to investigate immediately. |
| P99 latency | > 10s | Investigate provider | 🫏 The slowest one-percent of donkeys are taking over ten seconds per trip — investigate which far stable is causing the delays. |
| Cache hit rate | < 10% | Review cache config | 🫏 Fewer than one in ten questions matched a pre-written reply in the pigeon-hole — review the TTL setting and cosine-similarity threshold. |
| Cost/hour | > $50 | Alert + review routing | 🫏 The donkey expense ledger is charging over fifty dollars per hour — alert the team and review which provider stable is overspending. |
| Redis memory | > 80% | Scale or evict | 🫏 The fast pigeon-hole shelf is more than eighty percent full — scale it up or configure eviction before cache misses start spiking. |

---

## 9. Certification Relevance

| Cert Topic | Connection | 🫏 Donkey |
|------------|------------|-----------|
| **AWS SAA-C03: CloudWatch** | Logging, metrics, alarms | 🫏 CloudWatch is the AWS stable CCTV — it collects donkey-trip logs, raises cost alarms, and stores tachograph metrics for the exam. |
| **AWS SAA-C03: X-Ray** | Request tracing (X-Request-ID pattern) | 🫏 X-Ray is the AWS tachograph that traces each donkey trip across services, mirroring the X-Request-ID pattern used throughout the gateway. |
| **AZ-305: Azure Monitor** | Logging, metrics, diagnostics | 🫏 Azure Monitor is the Azure stable CCTV — it ingests container logs, Redis metrics, and diagnostic traces for the AZ-305 exam. |
| **AZ-305: Application Insights** | Request tracing, performance | 🫏 Application Insights is Azure's tachograph for tracing donkey trips end-to-end across microservices and measuring delivery performance. |

---

## 10. Cross-References

| Topic | Document | 🫏 Donkey |
|-------|----------|-----------|
| Architecture overview | [Architecture](../architecture-and-design/architecture.md) | 🫏 See how the full stable switchboard connects every donkey, pigeon-hole shelf, and expense ledger in one system-context diagram. |
| Cost tracking dashboard | [Cost Tracking Deep Dive](cost-tracking-deep-dive.md) | 🫏 The leather-bound expense ledger deep dive shows how every donkey trip's cargo cost is recorded, queried, and surfaced to callers. |
| Auth middleware | [API Contract](../architecture-and-design/api-contract.md) | 🫏 The permission-slip rulebook explains exactly how the stable's front door validates API keys for incoming couriers at the gate. |
| AWS infrastructure | [Terraform Guide](../setup-and-tooling/terraform-guide.md) | 🫏 Stable blueprints in Terraform provision the ECS Fargate box, ElastiCache pigeon-hole shelf, and RDS expense ledger on AWS. |
| Docker setup (LangFuse) | [Docker Compose Guide](../setup-and-tooling/docker-compose-guide.md) | 🫏 The portable mini-stable kit guide shows how to spin up the optional LangFuse CCTV upgrade with a single Docker Compose profile flag. |
