# Debugging Guide — AI Gateway

> Common issues, debugging techniques, and troubleshooting steps

---

## Table of Contents

1. [Quick Checks](#1-quick-checks)
2. [Common Issues](#2-common-issues)
3. [Debugging Techniques](#3-debugging-techniques)
4. [Component-Specific Debugging](#4-component-specific-debugging)
5. [Performance Debugging](#5-performance-debugging)
6. [Cross-References](#6-cross-references)

---

## 1. Quick Checks

```bash
# 1. Is the gateway running?
curl http://localhost:8100/health | jq

# 2. Is Ollama running?
curl http://localhost:11434/api/tags | jq

# 3. Is Redis running?
redis-cli ping  # → PONG

# 4. Is PostgreSQL running?
pg_isready -h localhost -p 5432 -U gateway

# 5. Check Docker services
docker compose ps
```

---

## 2. Common Issues

### "Connection refused" on port 8100

**Cause:** Gateway not running.

```bash
# Check if process is running
lsof -i :8100

# Start it
poetry run start

# Or check Docker
docker compose logs app
```

### "Model not found" error

**Cause:** Ollama doesn't have the model pulled.

```bash
# List available models
ollama list

# Pull required models
ollama pull llama3.2
ollama pull nomic-embed-text
```

### "Redis connection failed" (warning, not error)

**Cause:** Redis not running. Gateway falls back to in-memory.

```bash
# This is expected in minimal setup
# If you want Redis:
docker compose up -d redis
```

### 429 Too Many Requests

**Cause:** Rate limit hit (default: 60/min).

```bash
# Check remaining
curl -v http://localhost:8100/v1/chat/completions -d '{"messages":[{"role":"user","content":"hi"}]}'
# Look for Retry-After header

# Temporarily disable
# Set RATE_LIMIT_ENABLED=false in .env
```

### 422 Validation Error

**Cause:** Request doesn't match Pydantic model.

```bash
# Check the error detail
curl -X POST http://localhost:8100/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": "wrong type"}' | jq

# messages must be a list of {role, content} objects
```

### 502 Provider Error

**Cause:** LLM provider returned an error.

```bash
# Check gateway logs
docker compose logs app | grep ERROR

# Test Ollama directly
curl http://localhost:11434/api/generate \
  -d '{"model": "llama3.2", "prompt": "Hi", "stream": false}'

# For AWS Bedrock — check credentials
aws bedrock list-foundation-models --region eu-west-1
```

---

## 3. Debugging Techniques

### Enable Debug Logging

```bash
# Set in .env
LOG_LEVEL=DEBUG

# Or as environment variable
LOG_LEVEL=DEBUG poetry run start
```

Debug logging shows:
- Cache key computation
- Exact/semantic match details
- Rate limit counter values
- LLM request/response details
- Cost calculations

### Use Request IDs

Every response includes `X-Request-ID`:

```bash
curl -v http://localhost:8100/v1/chat/completions \
  -d '{"messages":[{"role":"user","content":"test"}]}'
# Response header: X-Request-ID: req_abc123

# Find this in logs:
grep "req_abc123" gateway.log
```

### Pass Your Own Request ID

```bash
curl http://localhost:8100/v1/chat/completions \
  -H "X-Request-ID: my-debug-trace-001" \
  -d '{"messages":[{"role":"user","content":"test"}]}'
```

### Check Swagger UI

Open http://localhost:8100/docs and use the interactive "Try it out" button.

### Inspect Redis

```bash
# Connect to Redis CLI
redis-cli  # or: docker compose exec redis redis-cli

# List all gateway keys
KEYS "gateway:*"

# Check cache entries
KEYS "gateway:cache:*"

# Check rate limit counters
KEYS "gateway:rate:*"

# Get a cache entry
GET "gateway:cache:abc123..."

# Check TTL
TTL "gateway:cache:abc123..."

# Clear all gateway data
DEL $(redis-cli KEYS "gateway:*" | tr '\n' ' ')
```

### Inspect PostgreSQL

```bash
# Connect to PostgreSQL
psql -h localhost -U gateway -d gateway
# or: docker compose exec pg psql -U gateway

# Check usage logs
SELECT * FROM usage_logs ORDER BY timestamp DESC LIMIT 10;

# Cost summary
SELECT model, COUNT(*), SUM(estimated_cost_usd) as cost
FROM usage_logs
WHERE timestamp >= CURRENT_DATE
GROUP BY model;

# Cache hit rate
SELECT
  AVG(CASE WHEN cached THEN 1.0 ELSE 0.0 END) as hit_rate
FROM usage_logs
WHERE timestamp >= CURRENT_DATE;
```

---

## 4. Component-Specific Debugging

### Cache Debugging

```bash
# Test cache: send same request twice
# First request:
curl http://localhost:8100/v1/chat/completions \
  -d '{"messages":[{"role":"user","content":"What is 2+2?"}]}' | jq '.cache_hit'
# → false

# Second request (identical):
curl http://localhost:8100/v1/chat/completions \
  -d '{"messages":[{"role":"user","content":"What is 2+2?"}]}' | jq '.cache_hit'
# → true (should be cache hit)

# Bypass cache:
curl http://localhost:8100/v1/chat/completions \
  -d '{"messages":[{"role":"user","content":"What is 2+2?"}],"bypass_cache":true}' | jq '.cache_hit'
# → false (cache bypassed)
```

### Rate Limiter Debugging

```bash
# Send requests until rate limit
for i in $(seq 1 65); do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    http://localhost:8100/v1/chat/completions \
    -d '{"messages":[{"role":"user","content":"test"}]}')
  echo "Request $i: $STATUS"
done
# → Requests 1-60: 200
# → Requests 61-65: 429
```

### Cost Tracker Debugging

```bash
# Send a request then check usage
curl http://localhost:8100/v1/chat/completions \
  -d '{"messages":[{"role":"user","content":"test"}]}' > /dev/null

curl http://localhost:8100/v1/usage?period=today | jq
```

---

## 5. Performance Debugging

### Latency Breakdown

```bash
# Check gateway latency
curl -w "\n  DNS: %{time_namelookup}s\n  Connect: %{time_connect}s\n  TTFB: %{time_starttransfer}s\n  Total: %{time_total}s\n" \
  http://localhost:8100/v1/chat/completions \
  -d '{"messages":[{"role":"user","content":"Hi"}]}'
```

### Expected Latencies

| Component | Expected | If Slow | 🫏 Donkey |
|-----------|----------|---------|-----------|
| Health check | <10ms | Database connectivity | 🫏 The "is the donkey awake?" check clears the stable gate in under 10 ms when all barn doors are open. |
| Cache hit | <10ms | Redis connection slow | 🫏 The fast pigeon-hole shelf returns a pre-written reply in under 10 ms when Redis is humming along smoothly. |
| Cache miss (LLM) | 500ms-5s | Provider latency (normal) | 🫏 When no pre-written reply exists, the delivery note goes to the donkey, taking 500 ms–5 s for a fresh run. |
| Rate limit check | <1ms | Redis connection slow | 🫏 Checking whether the courier still has trips left in their per-key quota takes under 1 ms against the fast pigeon-hole shelf. |
| Cost log | <5ms | PostgreSQL slow | 🫏 Scribbling the cargo-unit tally into the leather-bound expense ledger takes under 5 ms when PostgreSQL is healthy. |

---

## 6. Cross-References

| Topic | Document | 🫏 Donkey |
|-------|----------|-----------|
| Getting started | [Getting Started](getting-started.md) | 🫏 The orientation pack that gets a new stable hand from zero to dispatching their first donkey in under five minutes. |
| Docker setup | [Docker Compose Guide](docker-compose-guide.md) | 🫏 The portable mini-stable kit guide showing how app, Redis shelf, and PostgreSQL ledger containers start together. |
| Architecture | [Architecture](../architecture-and-design/architecture.md) | 🫏 The full stable blueprint mapping every donkey path from the front door through the GPS warehouse and back. |
| API specification | [API Contract](../architecture-and-design/api-contract.md) | 🫏 The official delivery contract listing every route, payload shape, and error code the dispatch desk will accept. |
