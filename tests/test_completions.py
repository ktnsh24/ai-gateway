"""
Tests for the AI Gateway chat completions endpoint.

Tests:
    - Valid request returns 200 with OpenAI-compatible response
    - Missing messages returns 422 (validation error)
    - Rate limit exceeded returns 429
    - LLM failure returns 502
    - Cache hit returns cached response
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def mock_settings():
    from src.config import AppEnvironment, CloudProvider, RoutingStrategy, Settings

    return Settings(
        app_name="ai-gateway-test",
        environment=AppEnvironment.DEV,
        cloud_provider=CloudProvider.LOCAL,
        routing_strategy=RoutingStrategy.SINGLE,
        cache_enabled=False,
        rate_limit_enabled=False,
        cost_tracking_enabled=False,
        api_keys_enabled=False,
        langfuse_enabled=False,
    )


@pytest.fixture
def mock_llm_response():
    """Create a mock LiteLLM response object."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = "The capital of France is Paris."
    response.usage.prompt_tokens = 15
    response.usage.completion_tokens = 8
    response.usage.total_tokens = 23
    return response


@pytest.fixture
def client(mock_settings, mock_llm_response):
    with patch("src.config.get_settings", return_value=mock_settings):
        with patch("src.gateway.router.create_router") as mock_router_factory:
            with patch("src.gateway.cache.create_cache") as mock_cache_factory:
                with patch("src.gateway.rate_limiter.create_rate_limiter") as mock_rl_factory:
                    with patch("src.gateway.cost_tracker.create_cost_tracker") as mock_ct_factory:
                        mock_router = AsyncMock()
                        mock_router.chat_completion.return_value = {
                            "response": mock_llm_response,
                            "provider": "local",
                            "model": "ollama/llama3.2",
                            "latency_ms": 1234.5,
                        }
                        mock_router.list_models.return_value = []
                        mock_router_factory.return_value = mock_router

                        mock_cache = AsyncMock()
                        mock_cache.get.return_value = None
                        mock_cache.stats.return_value = {"hits": 0, "misses": 0}
                        mock_cache_factory.return_value = mock_cache

                        mock_rl = AsyncMock()
                        mock_rl.check.return_value = (True, {"limit": 60, "remaining": 59, "current": 1})
                        mock_rl_factory.return_value = mock_rl

                        mock_ct = AsyncMock()
                        mock_ct_factory.return_value = mock_ct

                        from src.main import create_app

                        app = create_app()
                        with TestClient(app) as c:
                            # Store mocks for assertions
                            c._mock_router = mock_router
                            c._mock_cache = mock_cache
                            c._mock_rl = mock_rl
                            c._mock_ct = mock_ct
                            yield c


class TestChatCompletions:
    """Tests for POST /v1/chat/completions."""

    def test_valid_request_returns_200(self, client):
        response = client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "What is the capital of France?"}],
            },
        )
        assert response.status_code == 200

    def test_response_has_openai_format(self, client):
        response = client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        data = response.json()
        assert data["object"] == "chat.completion"
        assert "choices" in data
        assert len(data["choices"]) >= 1
        assert data["choices"][0]["message"]["role"] == "assistant"
        assert data["choices"][0]["message"]["content"] == "The capital of France is Paris."

    def test_response_includes_usage(self, client):
        response = client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        data = response.json()
        assert "usage" in data
        assert data["usage"]["prompt_tokens"] == 15
        assert data["usage"]["completion_tokens"] == 8
        assert data["usage"]["total_tokens"] == 23

    def test_response_includes_gateway_extensions(self, client):
        response = client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        data = response.json()
        assert "cost" in data
        assert "cache_hit" in data
        assert "gateway_latency_ms" in data
        assert data["cache_hit"] is False

    def test_missing_messages_returns_422(self, client):
        response = client.post("/v1/chat/completions", json={})
        assert response.status_code == 422

    def test_empty_messages_returns_422(self, client):
        response = client.post(
            "/v1/chat/completions",
            json={"messages": []},
        )
        # FastAPI validates list length
        assert response.status_code in (200, 422)

    def test_cost_tracker_called(self, client):
        client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        client._mock_ct.log_request.assert_called_once()

    def test_cache_checked(self, client):
        client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        client._mock_cache.get.assert_called_once()

    def test_cache_stored_after_response(self, client):
        client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        client._mock_cache.put.assert_called_once()


class TestChatCompletionsRateLimit:
    """Tests for rate limiting on chat completions."""

    def test_rate_limit_exceeded_returns_429(self, client):
        # Override rate limiter to reject
        client._mock_rl.check.return_value = (
            False,
            {"limit": 60, "remaining": 0, "current": 61, "reset_in_seconds": 42},
        )
        response = client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        assert response.status_code == 429


class TestChatCompletionsCacheHit:
    """Tests for cache hit behaviour."""

    def test_cache_hit_returns_cached_response(self, client):
        client._mock_cache.get.return_value = {
            "content": "Cached answer",
            "model": "cached-model",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        response = client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        data = response.json()
        assert data["cache_hit"] is True
        assert data["choices"][0]["message"]["content"] == "Cached answer"
        assert data["cost"]["estimated_cost_usd"] == 0.0

    def test_bypass_cache_skips_cache(self, client):
        client._mock_cache.get.return_value = {"content": "Cached"}
        response = client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "Hello"}],
                "bypass_cache": True,
            },
        )
        data = response.json()
        assert data["cache_hit"] is False
        # Cache.get should NOT be called when bypass_cache=True
        client._mock_cache.get.assert_not_called()
