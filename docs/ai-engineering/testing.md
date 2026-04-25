# Testing Strategy & Inventory — AI Gateway

> How the AI Gateway is tested — unit tests for gateway components, integration tests for the full request pipeline, and the patterns that make it all work without Redis or PostgreSQL.

**Related:** [Architecture](../architecture-and-design/architecture.md) · [Getting Started](../setup-and-tooling/getting-started.md)

---

## Table of Contents

- [Test Pyramid](#test-pyramid)
- [Running Tests](#running-tests)
- [Test Inventory](#test-inventory)
- [Test Patterns](#test-patterns)
- [Known Limitations](#known-limitations)
- [DE Parallel — What This Looks Like at Scale](#de-parallel--what-this-looks-like-at-scale)

---

## Test Pyramid

```
 ╱ ╲ E2E (manual via curl / Swagger UI)
 ╱ ╲ Verify full stack with real Ollama
 ╱─────╲
 ╱ ╲ Integration (22 tests)
 ╱ ╲ Full pipeline: route → RL → cache → LLM → cost tracker
 ╱───────────╲
 ╱ ╲ Unit (40 tests)
 ╱ ╲ Individual components: cache, rate limiter, cost tracker, completions
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

| File | Tests | What it covers | 🚚 Courier |
|---|---|---|---|
| `test_health.py` | 11 | Health endpoint, models list, usage endpoint | 🚚 Checks that the "is the courier awake?" endpoint returns healthy, lists the roster, and opens the expense ledger window correctly. |
| `test_completions.py` | 11 | Chat completions: pipeline, cache hit/miss, rate limit, validation | 🚚 Exercises the main delivery window — full dispatch pipeline, pickup locker hit and miss, daily dispatch quota rejection, and malformed shipping manifests. |
| `test_cache.py` | 9 | InMemoryCache: hit/miss, TTL, stats, invalidation; NoCache | 🚚 Pokes the in-memory pickup locker directly — verifies replies land and return, TTL eviction fires on time, and NoCache never stores anything. |
| `test_rate_limiter.py` | 8 | InMemoryRateLimiter: allow/reject, window reset, separate keys; NoRateLimiter | 🚚 Fires requests at the rate-limit cap — confirms allow and reject behaviour, window reset, and that separate API keys stay independent. |
| `test_cost_tracker.py` | 7 | InMemoryCostTracker: log/retrieve, aggregation, breakdown; NoCostTracker | 🚚 Writes fake parcel-unit tallies to the in-memory expense ledger and checks that aggregation and per-provider breakdowns are accurate. |

### Integration Tests (1 file, 22 tests)

| File | Tests | What it covers | 🚚 Courier |
|---|---|---|---|
| `test_integration.py` | 22 | Full pipeline for completions + embeddings; cache flow; error handling | 🚚 Runs the full depot pipeline — shipping manifests in, courier mocked, pickup locker hit and miss checked, and all error paths exercised end-to-end. |

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

| Limitation | Why | Mitigation | 🚚 Courier |
|---|---|---|---|
| No Redis integration tests | Requires running Redis | Docker Compose for CI | 🚚 Real pickup locker shelf tests need a live Redis process — spin up the local Docker Compose setup in CI to enable them properly. |
| No PostgreSQL integration tests | Requires running PostgreSQL | Docker Compose for CI | 🚚 Real expense ledger tests need a live PostgreSQL server — the Docker Compose Docker Compose setup provides one for CI pipelines. |
| LiteLLM is always mocked | Can't call real LLMs in CI | E2E tests with Ollama for local validation | 🚚 The universal courier adapter is always replaced with an AsyncMock, so no real courier calls are made during the automated test suite. |
| No load/stress tests | Not a priority for portfolio | Rate limiter unit tests cover the logic | 🚚 Flooding the dispatch desk with concurrent shipping manifests is not yet automated — unit tests cover the dispatch quota counter logic instead. |

---

## DE Parallel — What This Looks Like at Scale

In a production data engineering team, this test suite would expand to:

| Layer | What | Tools | 🚚 Courier |
|---|---|---|---|
| **Contract tests** | Verify OpenAI-compatible API contract | Pact, Schemathesis | 🚚 Verify the gateway's entry point still speaks the exact OpenAI dialect — any undocumented change breaks downstream courier clients immediately. |
| **Integration tests** | Real Redis + PostgreSQL via Docker | Testcontainers, docker-compose | 🚚 Spin up a real Redis pickup locker shelf and PostgreSQL expense ledger via Testcontainers to validate the full pipeline without mocking. |
| **Load tests** | Rate limiter + cache under concurrent load | Locust, k6 | 🚚 Flood the dispatch desk with concurrent shipping manifests to confirm the dispatch quota counter holds firm and the pickup locker absorbs repeat questions. |
| **Chaos tests** | Provider failures, Redis downtime | Chaos Monkey patterns | 🚚 Pull the plug on the primary courier's far depot and verify the dispatch desk seamlessly switches to the backup courier without dropping requests. |
| **Observability tests** | LangFuse traces, cost accuracy | Custom assertions on trace data | 🚚 Assert that LangFuse tachograph entries contain accurate parcel-unit counts and that per-request costs match the expense ledger entries exactly. |
