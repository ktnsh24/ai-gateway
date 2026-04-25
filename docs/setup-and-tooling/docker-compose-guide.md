# Docker Compose Guide — AI Gateway

> **Services:** app (FastAPI), Redis 7, PostgreSQL 16, LangFuse (optional)
>
> **File:** `docker-compose.yml`

---

## Table of Contents

1. [Quick Start](#1-quick-start)
2. [Services Overview](#2-services-overview)
3. [Service Details](#3-service-details)
4. [Common Commands](#4-common-commands)
5. [Development Workflows](#5-development-workflows)
6. [Troubleshooting](#6-troubleshooting)
7. [Cross-References](#7-cross-references)

---

## 1. Quick Start

```bash
# Start everything
docker compose up -d

# Check status
docker compose ps

# Watch logs
docker compose logs -f app

# Stop everything
docker compose down

# Stop and remove volumes (clean slate)
docker compose down -v
```

---

## 2. Services Overview

| Service | Image | Port | Purpose | 🚚 Courier |
|---------|-------|------|---------|-----------|
| `app` | Build from Dockerfile | 8100 | AI Gateway API | 🚚 The gateway listening on door 8100 — every cart pulls up here before any courier is dispatched on a delivery. |
| `redis` | `redis:7-alpine` | 6379 | Semantic cache + rate limiting | 🚚 The fast pickup locker shelf on door 6379 storing pre-written replies and enforcing each courier's per-key daily dispatch quota. |
| `pg` | `postgres:16-alpine` | 5432 | Cost tracking (usage_logs table) | 🚚 The expense ledger on door 5432 where every parcel-unit cost is permanently recorded per request. |
| `langfuse` | `langfuse/langfuse:2` | 3000 | LLM observability (optional) | 🚚 The optional gateway's observability stack dashboard on door 3000 that records every courier journey for replay and cost analysis. |

### Network

All services share a `gateway-net` bridge network and communicate via service names:
- App → Redis: `redis://redis:6379`
- App → PostgreSQL: `postgresql://gateway:gateway@pg:5432/gateway`
- App → LangFuse: `http://langfuse:3000`

---

## 3. Service Details

### App (AI Gateway)

```yaml
app:
 build: .
 ports:
 - "8100:8100"
 environment:
 - CLOUD_PROVIDER=local
 - REDIS_URL=redis://redis:6379
 - POSTGRESQL_URL=postgresql+asyncpg://gateway:gateway@pg:5432/gateway
 - OLLAMA_BASE_URL=http://host.docker.internal:11434
 depends_on:
 redis:
 condition: service_healthy
 pg:
 condition: service_healthy
```

**Note:** `host.docker.internal` lets the container reach Ollama running on the host machine.

### Redis

```yaml
redis:
 image: redis:7-alpine
 ports:
 - "6379:6379"
 volumes:
 - redis_data:/data
 healthcheck:
 test: ["CMD", "redis-cli", "ping"]
 interval: 5s
 timeout: 3s
 retries: 5
 command: redis-server --appendonly yes
```

**`--appendonly yes`** enables AOF persistence — data survives container restarts.

### PostgreSQL

```yaml
pg:
 image: postgres:16-alpine
 ports:
 - "5432:5432"
 environment:
 POSTGRES_USER: gateway
 POSTGRES_PASSWORD: gateway
 POSTGRES_DB: gateway
 volumes:
 - pg_data:/var/lib/postgresql/data
 healthcheck:
 test: ["CMD-SHELL", "pg_isready -U gateway"]
 interval: 5s
 timeout: 3s
 retries: 5
```

### LangFuse (Optional)

```yaml
# Start with: docker compose --profile langfuse up -d
langfuse:
 image: langfuse/langfuse:2
 profiles: ["langfuse"]
 ports:
 - "3000:3000"
 environment:
 DATABASE_URL: postgresql://gateway:gateway@pg:5432/gateway
 NEXTAUTH_SECRET: secret
 NEXTAUTH_URL: http://localhost:3000
 depends_on:
 pg:
 condition: service_healthy
```

---

## 4. Common Commands

### Start/Stop

```bash
# Start all services
docker compose up -d

# Start with LangFuse
docker compose --profile langfuse up -d

# Start only infrastructure (for local app development)
docker compose up -d redis pg

# Stop
docker compose down

# Stop and clean volumes
docker compose down -v
```

### Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f app

# Last 100 lines
docker compose logs --tail=100 app
```

### Debugging

```bash
# Check service status
docker compose ps

# Shell into a container
docker compose exec app bash
docker compose exec redis redis-cli
docker compose exec pg psql -U gateway

# Check Redis keys
docker compose exec redis redis-cli KEYS "gateway:*"

# Check PostgreSQL tables
docker compose exec pg psql -U gateway -c "SELECT count(*) FROM usage_logs;"
```

### Rebuild

```bash
# Rebuild after code changes
docker compose up -d --build app

# Force rebuild (no cache)
docker compose build --no-cache app
```

---

## 5. Development Workflows

### Workflow 1: Full Docker (simplest)

```bash
docker compose up -d
# Everything runs in containers
# Edit code → rebuild → test
docker compose up -d --build app
```

### Workflow 2: Local App + Docker Infra (fastest iteration)

```bash
# Start only infrastructure
docker compose up -d redis pg

# Run app locally
poetry run start

# Edit code → auto-reload (uvicorn --reload)
```

### Workflow 3: Minimal (no Docker)

```bash
# No Docker needed — in-memory fallbacks
poetry run start

# Cache: InMemoryCache
# Rate limiter: InMemoryRateLimiter
# Cost tracker: InMemoryCostTracker
```

---

## 6. Troubleshooting

### Redis Connection Refused

```
Error: Cannot connect to Redis at redis:6379
```

Fix:
```bash
docker compose ps redis # Check if running
docker compose logs redis # Check for errors
docker compose restart redis
```

### PostgreSQL Not Ready

```
Error: Connection refused to pg:5432
```

Fix:
```bash
docker compose ps pg
docker compose logs pg
# Wait for healthcheck to pass:
docker compose exec pg pg_isready -U gateway
```

### Ollama Not Accessible from Container

```
Error: Cannot connect to Ollama
```

Fix:
```bash
# On Linux, use host.docker.internal or the host's IP
# Or add to docker-compose.yml:
extra_hosts:
 - "host.docker.internal:host-gateway"
```

### Port Already in Use

```
Error: port 8100 already in use
```

Fix:
```bash
# Find what's using the port
lsof -i :8100
# Kill it or change the port in docker-compose.yml
```

---

## 7. Cross-References

| Topic | Document | 🚚 Courier |
|-------|----------|-----------|
| Getting started | [Getting Started](getting-started.md) | 🚚 The orientation pack that walks a new on-call engineer through setting up the whole dispatch desk from scratch. |
| Architecture | [Architecture](../architecture-and-design/architecture.md) | 🚚 The full depot blueprint explaining how the dispatch desk, pickup locker shelf, and expense ledger all connect. |
| Observability + LangFuse | [Observability Deep Dive](../ai-engineering/observability-deep-dive.md) | 🚚 The deep-dive into gateway's observability stack and tachograph showing how to trace each courier delivery through LangFuse dashboards. |
| Terraform (production) | [Terraform Guide](terraform-guide.md) | 🚚 the gateway-blueprints guide for stamping out a full cloud container on AWS or Azure with a single terraform apply. |
| Debugging | [Debugging Guide](debugging-guide.md) | 🚚 the gateway troubleshooting manual for diagnosing failed couriers, quota exhaustion, and broken pickup locker shelves. |
