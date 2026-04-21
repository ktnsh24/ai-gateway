# Testing Strategy & Inventory — AI Gateway

> How the AI Gateway is tested — unit tests for gateway components, integration tests for the full request pipeline, and the patterns that make it all work without Redis or PostgreSQL.

**Related:** [Architecture](../architecture-and-design/architecture.md) · [Getting Started](../setup-and-tooling/getting-started.md)

---

## Test Pyramid

```
        ╱ ╲           E2E (manual via curl / Swagger UI)
       ╱   ╲          Verify full stack with real Ollama
      ╱─────╲
     ╱       ╲        Integration (22 tests)
    ╱         ╲       Full pipeline: route → RL → cache → LLM → cost tracker
   ╱───────────╲
  ╱             ╲     Unit (40 tests)
 ╱               ╲    Individual components: cache, rate limiter, cost tracker, completions
╱─────────────────╲
```

---

## Running Tests

```bash
# All tests
poetry run pytest tests/ -v

# Specific file
poetry run pytest tests/test_integration.py -v

# With coverage
poetry run pytest tests/ --cov=src --cov-report=term-missing

# Only integration tests
poetry run pytest tests/test_integration.py -v -k "Pipeline"
```

---

## Test Inventory

### Unit Tests (5 files, ~40 tests)

| File | Tests | What it covers |
|---|---|---|
| `test_health.py` | 11 | Health endpoint, models list, usage endpoint |
| `test_completions.py` | 11 | Chat completions: pipeline, cache hit/miss, rate limit, validation |
| `test_cache.py` | 9 | InMemoryCache: hit/miss, TTL, stats, invalidation; NoCache |
| `test_rate_limiter.py` | 8 | InMemoryRateLimiter: allow/reject, window reset, separate keys; NoRateLimiter |
| `test_cost_tracker.py` | 7 | InMemoryCostTracker: log/retrieve, aggregation, breakdown; NoCostTracker |

### Integration Tests (1 file, 22 tests)

| File | Tests | What it covers |
|---|---|---|
| `test_integration.py` | 22 | Full pipeline for completions + embeddings; cache flow; error handling |

**Total: 6 files, ~62 tests**

---

## Test Patterns

### 1. Factory-Level Mocking

All gateway components are mocked at the factory level (`create_router`, `create_cache`, etc.), so tests never need Redis or PostgreSQL:

```python
with patch("src.gateway.router.create_router", return_value=mock_router):
    with patch("src.gateway.cache.create_cache", return_value=mock_cache):
        app = create_app()
        with TestClient(app) as client:
            ...
```

### 2. Shared Fixtures (conftest.py)

`tests/conftest.py` provides reusable fixtures:
- `mock_settings` — Settings with all external services disabled
- `mock_router` — AsyncMock LLM router with default response
- `mock_cache` — AsyncMock cache (default: miss)
- `mock_rate_limiter` — AsyncMock rate limiter (default: allow)
- `mock_cost_tracker` — AsyncMock cost tracker
- `client` — TestClient with all mocks wired

### 3. Component Tests Use Real Implementations

Unit tests for `InMemoryCache`, `InMemoryRateLimiter`, and `InMemoryCostTracker` use the real in-memory implementations — no mocking needed because these don't require external services.

---

## Known Limitations

| Limitation | Why | Mitigation |
|---|---|---|
| No Redis integration tests | Requires running Redis | Docker Compose for CI |
| No PostgreSQL integration tests | Requires running PostgreSQL | Docker Compose for CI |
| LiteLLM is always mocked | Can't call real LLMs in CI | E2E tests with Ollama for local validation |
| No load/stress tests | Not a priority for portfolio | Rate limiter unit tests cover the logic |

---

## DE Parallel — What This Looks Like at Scale

In a production data engineering team, this test suite would expand to:

| Layer | What | Tools |
|---|---|---|
| **Contract tests** | Verify OpenAI-compatible API contract | Pact, Schemathesis |
| **Integration tests** | Real Redis + PostgreSQL via Docker | Testcontainers, docker-compose |
| **Load tests** | Rate limiter + cache under concurrent load | Locust, k6 |
| **Chaos tests** | Provider failures, Redis downtime | Chaos Monkey patterns |
| **Observability tests** | LangFuse traces, cost accuracy | Custom assertions on trace data |
