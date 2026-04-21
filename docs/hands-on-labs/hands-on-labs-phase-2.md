# Hands-on Labs — Phase 2: Production Features

> **Labs 5-8:** Cost tracking, health checks, observability, Docker Compose
> **Time:** ~2 hours total
> **Prerequisites:** Labs 1-4 completed, Docker + Docker Compose installed

---

## Table of Contents

- [Lab 5: Cost Tracking Dashboard](#lab-5-cost-tracking-dashboard)
- [Lab 6: Health Check and Monitoring](#lab-6-health-check-and-monitoring)
- [Lab 7: Request Tracing and Observability](#lab-7-request-tracing-and-observability)
- [Lab 8: Full Docker Compose Stack](#lab-8-full-docker-compose-stack)

---

## 🫏 The Donkey Analogy — Understanding Phase 2 Production Operations

| Metric | 🫏 Donkey Analogy | What It Means for the Gateway | How It's Calculated |
|--------|-------------------|-------------------------------|---------------------|
| **Cost Tracking** | Counting hay spent per trip | Attributing token usage and cost to each request/model | `Σ(prompt_tokens + completion_tokens) × price_per_token` per provider |
| **Health Checks** | Confirms each stable door is open | Validates all dependencies are live before serving traffic | `GET /health` → check provider, cache, DB status → return OK/degraded |
| **Request Tracing** | Follows one package end-to-end via request IDs | Correlates logs across services for debugging and observability | Propagate `x-request-id` header → log at each stage → aggregate in traces |
| **Docker Deployment** | The whole depot can be recreated identically | Reproducible multi-service stack (gateway + dependencies) | `docker compose up` → build image → mount config → expose ports |

---

## Lab 5: Cost Tracking Dashboard

> 🏢 **Business Context:** The finance team needs to understand LLM spending per team and per model. The platform team built a cost tracking dashboard that logs every request to PostgreSQL and exposes aggregated usage data via a REST endpoint that finance can consume.

### Objective

Generate usage data and query the cost dashboard.

### Steps

```bash
# 1. Start with Docker (includes PostgreSQL)
docker compose up -d redis pg
poetry run start

# 2. Send diverse requests to generate usage data
for i in $(seq 1 10); do
  curl -s http://localhost:8100/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d "{\"messages\":[{\"role\":\"user\",\"content\":\"Tell me fact number $i about AI\"}]}" > /dev/null
  echo "Sent request $i"
done

# 3. Send some embedding requests
for i in $(seq 1 5); do
  curl -s http://localhost:8100/v1/embeddings \
    -H "Content-Type: application/json" \
    -d "{\"input\":\"Embedding text number $i\"}" > /dev/null
done

# 4. Query the usage dashboard
curl -s http://localhost:8100/v1/usage?period=today | jq
```

### Expected Results

```json
{
  "period": "today",
  "total_requests": 15,
  "total_tokens": 4500,
  "total_cost_usd": 0.0,
  "cache_hit_rate": 0.0,
  "by_model": {
    "ollama/llama3.2": {
      "requests": 10,
      "tokens": 3500,
      "cost_usd": 0.0
    },
    "ollama/nomic-embed-text": {
      "requests": 5,
      "tokens": 1000,
      "cost_usd": 0.0
    }
  },
  "by_provider": {
    "local": {
      "requests": 15,
      "cost_usd": 0.0
    }
  }
}
```

### Test with Cached Requests

```bash
# Send duplicate requests (should hit cache)
for i in $(seq 1 5); do
  curl -s http://localhost:8100/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{"messages":[{"role":"user","content":"Tell me fact number 1 about AI"}]}' > /dev/null
done

# Check cache hit rate
curl -s http://localhost:8100/v1/usage?period=today | jq '.cache_hit_rate'
# → Should be > 0 now
```

### Query PostgreSQL Directly

```bash
docker compose exec pg psql -U gateway -c "
  SELECT model, COUNT(*) as requests, 
         SUM(total_tokens) as tokens,
         ROUND(SUM(estimated_cost_usd)::numeric, 4) as cost,
         ROUND(AVG(CASE WHEN cached THEN 1.0 ELSE 0.0 END)::numeric, 2) as cache_rate
  FROM usage_logs 
  WHERE timestamp >= CURRENT_DATE
  GROUP BY model
  ORDER BY requests DESC;
"
```

### Verify

- [ ] Usage endpoint returns aggregated data
- [ ] `by_model` breakdown shows separate models
- [ ] `cache_hit_rate` increases after duplicate requests
- [ ] PostgreSQL `usage_logs` table has rows
- [ ] Local Ollama models show $0.00 cost

### 🧠 Certification Question

**Q: How would you design a cost allocation system for multiple AWS accounts using Cost Explorer and tags?**
A: Use AWS Cost Explorer with resource tags (team, project, environment). Each team's API key maps to a cost allocation tag. Cross-account with AWS Organizations + consolidated billing. Our `usage_logs.api_key_hash` serves the same purpose at the application level.

### What you learned

Every request is logged to PostgreSQL with model, tokens, cost, and cache status. The `/v1/usage` endpoint aggregates this into a dashboard. This is how you prove LLM ROI to finance.

**✅ Skill unlocked:** You can query usage data, verify cache savings, and explain cost attribution.

---

## Lab 6: Health Check and Monitoring

> 🏢 **Business Context:** The SRE team needs to monitor the gateway's health. Load balancers need a health endpoint to route traffic only to healthy instances. The health check should verify all dependencies (Redis, PostgreSQL, LLM router) and report degraded status when non-critical components are down.

### Objective

Test health check behaviour with components up and down.

### Steps

```bash
# 1. All components healthy
docker compose up -d redis pg
poetry run start &
sleep 2

curl -s http://localhost:8100/health | jq
```

### Expected (All Healthy)

```json
{
  "status": "healthy",
  "version": "0.1.0",
  "provider": "local",
  "components": {
    "redis": "connected",
    "postgresql": "connected",
    "llm_router": "ready",
    "models_available": ["llama3.2", "nomic-embed-text"]
  }
}
```

### Test Degraded State

```bash
# Stop Redis
docker compose stop redis

# Check health again
curl -s http://localhost:8100/health | jq
# → status: "healthy" (Redis is optional — cache falls back to in-memory)
# → components.redis: "disconnected"

# Stop PostgreSQL
docker compose stop pg

# Check health again
curl -s http://localhost:8100/health | jq
# → status: "healthy" (PostgreSQL is optional — cost tracking falls back)
# → components.postgresql: "disconnected"

# Stop Ollama
# (kill the ollama process)

curl -s http://localhost:8100/health | jq
# → status: "degraded"
# → components.llm_router: "unavailable"
```

### Verify

- [ ] All components healthy → status: "healthy"
- [ ] Redis down → status: "healthy" (graceful degradation)
- [ ] PostgreSQL down → status: "healthy" (graceful degradation)
- [ ] LLM router down → status: "degraded"
- [ ] `models_available` lists pulled Ollama models

### 🧠 Certification Question

**Q: How do ALB health checks work in AWS, and what happens when a target fails?**
A: ALB sends periodic HTTP requests to the health check path. If a target returns non-200 for the unhealthy threshold count, it's marked unhealthy and removed from the target group. Our `/health` endpoint serves this purpose — ALB would check it every 30s.

### What you learned

Graceful degradation means optional components (Redis, PostgreSQL) can fail without crashing the gateway. Only the LLM router being down triggers "degraded" status. This maps to ALB health checks in production.

**✅ Skill unlocked:** You can interpret component health and explain graceful degradation.

---

## Lab 7: Request Tracing and Observability

> 🏢 **Business Context:** When a customer reports a slow response, the support team needs to trace the exact request through the system. Request IDs and latency headers enable end-to-end tracing from client to provider.

### Objective

Trace a request through the gateway using request IDs and latency headers.

### Steps

```bash
# 1. Send a request with a custom request ID
curl -v http://localhost:8100/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Request-ID: debug-trace-001" \
  -d '{"messages":[{"role":"user","content":"What is Docker?"}]}' 2>&1

# Look for response headers:
# < X-Request-ID: debug-trace-001
# < X-Gateway-Latency-Ms: 1523.45
```

### Auto-Generated Request IDs

```bash
# Send without X-Request-ID header
curl -v http://localhost:8100/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"What is Kubernetes?"}]}' 2>&1 | grep X-Request-ID
# → X-Request-ID: req_a1b2c3d4e5f6 (auto-generated)
```

### Trace in Logs

```bash
# Watch gateway logs while sending a request
# In terminal 1:
LOG_LEVEL=DEBUG poetry run start 2>&1 | tee gateway.log

# In terminal 2:
curl http://localhost:8100/v1/chat/completions \
  -H "X-Request-ID: trace-me" \
  -d '{"messages":[{"role":"user","content":"Hi"}]}' > /dev/null

# In terminal 1, you should see:
# INFO: Request started  | request_id=trace-me method=POST path=/v1/chat/completions
# INFO: Request completed | request_id=trace-me status=200 duration_ms=1523.45
```

### Verify

- [ ] Custom X-Request-ID is echoed back in response
- [ ] Auto-generated request IDs are in `req_` format
- [ ] X-Gateway-Latency-Ms header is present
- [ ] Request IDs appear in gateway logs
- [ ] Latency matches actual response time

### 🧠 Certification Question

**Q: What AWS service provides distributed tracing, and how does it compare to our request ID approach?**
A: AWS X-Ray provides distributed tracing with trace IDs (format: `1-{timestamp}-{24-digit hex}`). It automatically instruments AWS SDK calls. Our X-Request-ID is a simpler version of the same concept — correlating logs across request lifecycle. In production, X-Ray would wrap our gateway for full tracing.

### What you learned

Request IDs and latency headers enable end-to-end tracing. Custom or auto-generated IDs let you grep one request across all logs — the same pattern as AWS X-Ray.

**✅ Skill unlocked:** You can trace a request, correlate logs, and explain the value of distributed tracing.

---

## Lab 8: Full Docker Compose Stack

> 🏢 **Business Context:** The DevOps team needs a single command to spin up the entire gateway stack for testing. Docker Compose brings up the gateway, Redis, PostgreSQL, and optionally LangFuse for LLM-specific observability.

### Objective

Run the complete stack via Docker Compose and verify all integrations.

### Steps

```bash
# 1. Start the full stack
docker compose up -d
docker compose ps

# 2. Wait for health checks
sleep 10
curl -s http://localhost:8100/health | jq

# 3. Run through the full flow
# Chat completion
curl -s http://localhost:8100/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Explain Docker Compose"}]}' | jq '{model, cache_hit, gateway_latency_ms}'

# Same again (cache hit)
curl -s http://localhost:8100/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Explain Docker Compose"}]}' | jq '{model, cache_hit, gateway_latency_ms}'

# Embedding
curl -s http://localhost:8100/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{"input":"Docker Compose orchestrates containers"}' | jq '{model, "dim": (.data[0].embedding | length)}'

# Models
curl -s http://localhost:8100/v1/models | jq '.data[].id'

# Usage dashboard
curl -s http://localhost:8100/v1/usage?period=today | jq

# 4. Verify Redis has cache entries
docker compose exec redis redis-cli KEYS "gateway:*" | head -5

# 5. Verify PostgreSQL has usage logs
docker compose exec pg psql -U gateway -c "SELECT COUNT(*) FROM usage_logs;"
```

### Expected Flow

```
Step 2: health → {status: "healthy", components: {redis: "connected", postgresql: "connected"}}
Step 3a: chat → {cache_hit: false, gateway_latency_ms: ~1500}
Step 3b: same → {cache_hit: true, gateway_latency_ms: ~5}
Step 3c: embed → {dim: 768}
Step 3d: models → ["llama3.2", "nomic-embed-text"]
Step 3e: usage → {total_requests: 3, ...}
Step 4: Redis → gateway:cache:* keys present
Step 5: PostgreSQL → count > 0
```

### Cleanup

```bash
# Stop all services
docker compose down

# Remove volumes (fresh start)
docker compose down -v
```

### Verify

- [ ] All 4 services start and pass health checks
- [ ] Chat completion works end-to-end
- [ ] Cache hit works on repeated request
- [ ] Embeddings return 768 dimensions
- [ ] Usage dashboard shows request data
- [ ] Redis has `gateway:*` keys
- [ ] PostgreSQL has `usage_logs` rows

### 🧠 Certification Question

**Q: How would you convert this Docker Compose setup to ECS with Fargate for production?**
A: Each Docker Compose service maps to an ECS component: `app` → ECS Fargate task + ALB, `redis` → ElastiCache, `pg` → RDS PostgreSQL. The `docker-compose.yml` env vars become ECS task definition environment variables or Secrets Manager references. Health checks map to ALB target group health checks. This is exactly what our `infra/aws/main.tf` implements.

### What you learned

The full stack — gateway, Redis, PostgreSQL — starts with one command. Cache and cost tracking work end-to-end. This Compose file is the blueprint for the ECS task definitions in production.

**✅ Skill unlocked:** You can run the full gateway stack and verify all integrations.

---

## Summary

| Lab | Component | Key Learning |
|-----|-----------|-------------|
| 5 | Cost Tracker | Usage logging, aggregation, dashboard API |
| 6 | Health Check | Component monitoring, graceful degradation |
| 7 | Observability | Request IDs, tracing, latency headers |
| 8 | Docker Compose | Full stack deployment, integration testing |

## Phase 2 Labs — Skills Checklist

| # | Skill | Lab | Can you explain it? |
|---|---|---|---|
| 1 | Usage aggregation and cost attribution | Lab 5 | [ ] Yes |
| 2 | Dependency-aware health interpretation | Lab 6 | [ ] Yes |
| 3 | Request tracing with IDs and latency headers | Lab 7 | [ ] Yes |
| 4 | End-to-end compose integration validation | Lab 8 | [ ] Yes |

**All 8 labs cover the complete AI Gateway feature set.** Each maps to real production patterns and certification topics.
