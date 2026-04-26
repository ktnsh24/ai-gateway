"""
AI Gateway — Shared Test Fixtures

Centralised conftest.py providing reusable fixtures for all test files.
Components are mocked at the factory level so no Redis/PostgreSQL is needed.

Usage:
    def test_something(client, mock_router, mock_cache):
        mock_cache.get.return_value = {"content": "cached"}
        response = client.get("/health")
        assert response.status_code == 200
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from src.config import AppEnvironment, CloudProvider, RoutingStrategy, Settings


@pytest.fixture
def mock_settings() -> Settings:
    """Minimal settings with all external services disabled."""
    return Settings(
        app_name="ai-gateway-test",
        environment=AppEnvironment.DEV,
        cloud_provider=CloudProvider.LOCAL,
        routing_strategy=RoutingStrategy.SINGLE,
        redis_url="redis://localhost:6379/0",
        database_url="postgresql+asyncpg://test:test@localhost:5432/test",
        cache_enabled=False,
        rate_limit_enabled=False,
        cost_tracking_enabled=False,
        api_keys_enabled=False,
        langfuse_enabled=False,
    )


@pytest.fixture
def mock_llm_response() -> MagicMock:
    """Mock LiteLLM chat completion response."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = "The capital of France is Paris."
    response.usage.prompt_tokens = 15
    response.usage.completion_tokens = 8
    response.usage.total_tokens = 23
    return response


@pytest.fixture
def mock_router(mock_llm_response: MagicMock) -> AsyncMock:
    """Mock LLM router with default chat completion + model list."""
    router = AsyncMock()
    router.chat_completion.return_value = {
        "response": mock_llm_response,
        "provider": "local",
        "model": "ollama/llama3.2",
        "latency_ms": 1234.5,
    }
    router.list_models.return_value = [
        {"id": "llama3.2", "provider": "local", "owned_by": "ollama", "capabilities": ["chat"]},
    ]
    return router


@pytest.fixture
def mock_cache() -> AsyncMock:
    """Mock semantic cache — default: miss on get, no-op on put."""
    cache = AsyncMock()
    cache.get.return_value = None
    cache.stats.return_value = {"hits": 0, "misses": 0, "total": 0, "hit_rate": 0.0}
    return cache


@pytest.fixture
def mock_rate_limiter() -> AsyncMock:
    """Mock rate limiter — default: always allow."""
    rl = AsyncMock()
    rl.check.return_value = (True, {"limit": 60, "remaining": 59, "current": 1})
    return rl


@pytest.fixture
def mock_cost_tracker() -> AsyncMock:
    """Mock cost tracker with default empty summary."""
    ct = AsyncMock()
    ct.get_usage_summary.return_value = {
        "period": "today",
        "total_requests": 0,
        "total_tokens": 0,
        "total_cost_usd": 0.0,
        "avg_latency_ms": 0.0,
        "cache_hit_rate": 0.0,
        "requests_by_model": {},
        "cost_by_provider": {},
    }
    return ct


@pytest.fixture
def client(
    mock_settings: Settings,
    mock_router: AsyncMock,
    mock_cache: AsyncMock,
    mock_rate_limiter: AsyncMock,
    mock_cost_tracker: AsyncMock,
) -> TestClient:
    """Test client with all gateway components mocked at the factory level."""
    with patch("src.config.get_settings", return_value=mock_settings):
        with patch("src.gateway.router.create_router", return_value=mock_router):
            with patch("src.gateway.cache.create_cache", return_value=mock_cache):
                with patch("src.gateway.rate_limiter.create_rate_limiter", return_value=mock_rate_limiter):
                    with patch("src.gateway.cost_tracker.create_cost_tracker", return_value=mock_cost_tracker):
                        from src.main import create_app

                        app = create_app()
                        with TestClient(app) as c:
                            yield c
