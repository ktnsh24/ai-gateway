"""
Tests for the AI Gateway health endpoint and app factory.

Tests:
    - Health endpoint returns correct status
    - App factory creates FastAPI instance
    - Settings are loaded and injected into app state
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


@pytest.fixture
def mock_settings():
    """Create mock settings for testing."""
    from src.config import AppEnvironment, CloudProvider, RoutingStrategy, Settings

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
def client(mock_settings):
    """Create a test client with mocked dependencies."""
    with patch("src.config.get_settings", return_value=mock_settings):
        with patch("src.gateway.router.create_router") as mock_router_factory:
            with patch("src.gateway.cache.create_cache") as mock_cache_factory:
                with patch("src.gateway.rate_limiter.create_rate_limiter") as mock_rl_factory:
                    with patch("src.gateway.cost_tracker.create_cost_tracker") as mock_ct_factory:
                        # Create mock instances
                        mock_router = MagicMock()
                        mock_router.list_models.return_value = [
                            {"id": "llama3.2", "provider": "local", "owned_by": "ollama", "capabilities": ["chat"]},
                        ]
                        mock_router_factory.return_value = mock_router

                        mock_cache = AsyncMock()
                        mock_cache.stats.return_value = {"hits": 0, "misses": 0, "total": 0, "hit_rate": 0.0}
                        mock_cache_factory.return_value = mock_cache

                        mock_rl = AsyncMock()
                        mock_rl.check.return_value = (True, {"limit": 60, "remaining": 59, "current": 1})
                        mock_rl_factory.return_value = mock_rl

                        mock_ct = AsyncMock()
                        mock_ct.get_usage_summary.return_value = {
                            "period": "today",
                            "total_requests": 0,
                            "total_tokens": 0,
                            "total_cost_usd": 0.0,
                            "avg_latency_ms": 0.0,
                            "cache_hit_rate": 0.0,
                            "requests_by_model": {},
                            "cost_by_provider": {},
                        }
                        mock_ct_factory.return_value = mock_ct

                        from src.main import create_app

                        app = create_app()
                        with TestClient(app) as c:
                            yield c


class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_returns_status_healthy(self, client):
        response = client.get("/health")
        data = response.json()
        assert data["status"] == "healthy"

    def test_health_returns_version(self, client):
        response = client.get("/health")
        data = response.json()
        assert data["version"] == "0.1.0"

    def test_health_returns_provider(self, client):
        response = client.get("/health")
        data = response.json()
        assert data["provider"] == "local"

    def test_health_returns_models(self, client):
        response = client.get("/health")
        data = response.json()
        assert "models_available" in data
        assert isinstance(data["models_available"], list)


class TestModelsEndpoint:
    """Tests for GET /v1/models."""

    def test_models_returns_200(self, client):
        response = client.get("/v1/models")
        assert response.status_code == 200

    def test_models_returns_list(self, client):
        response = client.get("/v1/models")
        data = response.json()
        assert data["object"] == "list"
        assert isinstance(data["data"], list)
        assert len(data["data"]) >= 1

    def test_models_have_required_fields(self, client):
        response = client.get("/v1/models")
        data = response.json()
        for model in data["data"]:
            assert "id" in model
            assert "provider" in model
            assert "owned_by" in model


class TestUsageEndpoint:
    """Tests for GET /v1/usage."""

    def test_usage_returns_200(self, client):
        response = client.get("/v1/usage")
        assert response.status_code == 200

    def test_usage_returns_summary(self, client):
        response = client.get("/v1/usage")
        data = response.json()
        assert "summary" in data
        assert data["summary"]["period"] == "today"
        assert "total_requests" in data["summary"]
        assert "total_cost_usd" in data["summary"]

    def test_usage_accepts_period_param(self, client):
        response = client.get("/v1/usage?period=week")
        assert response.status_code == 200
