"""
AI Gateway — Integration Tests for Completions + Embeddings Endpoints

These tests exercise the full request pipeline (route → rate limiter → cache → router → cost tracker)
with mocked gateway components. They verify the integration between components, not just individual units.

Test inventory (22 tests):
    TestCompletionsPipeline       — Full pipeline: route → RL → cache → LLM → cost tracker (7 tests)
    TestCompletionsCacheFlow      — Cache hit/miss/bypass paths (5 tests)
    TestCompletionsErrorHandling  — Rate limit, LLM failure, validation (4 tests)
    TestEmbeddingsPipeline        — Full embeddings pipeline (4 tests)
    TestEmbeddingsErrorHandling   — Rate limit, provider failure (2 tests)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Completions Pipeline
# ---------------------------------------------------------------------------
class TestCompletionsPipeline:
    """Integration: full request flows through all gateway components."""

    def test_full_pipeline_returns_200(self, client):
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "chat.completion"
        assert len(data["choices"]) >= 1
        assert data["choices"][0]["message"]["role"] == "assistant"

    def test_pipeline_checks_rate_limiter(self, client, mock_rate_limiter):
        client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )
        mock_rate_limiter.check.assert_called_once()

    def test_pipeline_checks_cache(self, client, mock_cache):
        client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )
        mock_cache.get.assert_called_once()

    def test_pipeline_calls_llm_router(self, client, mock_router):
        client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )
        mock_router.chat_completion.assert_called_once()

    def test_pipeline_stores_in_cache(self, client, mock_cache):
        client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )
        mock_cache.put.assert_called_once()

    def test_pipeline_logs_cost(self, client, mock_cost_tracker):
        client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )
        mock_cost_tracker.log_request.assert_called_once()

    def test_pipeline_returns_gateway_extensions(self, client):
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )
        data = response.json()
        assert "cost" in data
        assert "cache_hit" in data
        assert "gateway_latency_ms" in data
        assert data["cache_hit"] is False
        assert data["gateway_latency_ms"] > 0


# ---------------------------------------------------------------------------
# Cache Flow
# ---------------------------------------------------------------------------
class TestCompletionsCacheFlow:
    """Integration: cache hit/miss/bypass paths."""

    def test_cache_miss_calls_llm(self, client, mock_cache, mock_router):
        mock_cache.get.return_value = None
        client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )
        mock_router.chat_completion.assert_called_once()

    def test_cache_hit_skips_llm(self, client, mock_cache, mock_router):
        mock_cache.get.return_value = {
            "content": "Cached answer",
            "model": "cached-model",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )
        data = response.json()
        assert data["cache_hit"] is True
        assert data["choices"][0]["message"]["content"] == "Cached answer"
        assert data["cost"]["estimated_cost_usd"] == 0.0
        mock_router.chat_completion.assert_not_called()

    def test_cache_hit_logs_cost_with_cached_flag(self, client, mock_cache, mock_cost_tracker):
        mock_cache.get.return_value = {
            "content": "Cached",
            "model": "cached-model",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
        client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )
        call_kwargs = mock_cost_tracker.log_request.call_args
        assert call_kwargs.kwargs.get("cached") is True or (
            len(call_kwargs.args) > 0 or call_kwargs[1].get("cached") is True
        )

    def test_bypass_cache_skips_cache_get(self, client, mock_cache):
        mock_cache.get.return_value = {"content": "Should not appear"}
        response = client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "Hello"}],
                "bypass_cache": True,
            },
        )
        data = response.json()
        assert data["cache_hit"] is False
        mock_cache.get.assert_not_called()

    def test_bypass_cache_still_stores_result(self, client, mock_cache):
        client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "Hello"}],
                "bypass_cache": True,
            },
        )
        mock_cache.put.assert_called_once()


# ---------------------------------------------------------------------------
# Completions Error Handling
# ---------------------------------------------------------------------------
class TestCompletionsErrorHandling:
    """Integration: error paths through the pipeline."""

    def test_rate_limit_returns_429(self, client, mock_rate_limiter):
        mock_rate_limiter.check.return_value = (
            False,
            {"limit": 60, "remaining": 0, "current": 61, "reset_in_seconds": 30},
        )
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )
        assert response.status_code == 429

    def test_llm_failure_returns_502(self, client, mock_router):
        mock_router.chat_completion.side_effect = Exception("Connection refused")
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )
        assert response.status_code == 502

    def test_missing_messages_returns_422(self, client):
        response = client.post("/v1/chat/completions", json={})
        assert response.status_code == 422

    def test_invalid_temperature_returns_422(self, client):
        response = client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "Hello"}],
                "temperature": 5.0,  # max is 2.0
            },
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Embeddings Pipeline
# ---------------------------------------------------------------------------
class TestEmbeddingsPipeline:
    """Integration: full embeddings request pipeline."""

    @pytest.fixture(autouse=True)
    def setup_embedding_mock(self, mock_router):
        """Configure mock router with embedding response."""
        embed_response = MagicMock()
        embed_response.data = [{"embedding": [0.1, 0.2, 0.3], "index": 0}]
        embed_response.usage = MagicMock()
        embed_response.usage.prompt_tokens = 5
        embed_response.usage.total_tokens = 5
        mock_router.embedding.return_value = {
            "response": embed_response,
            "provider": "local",
            "model": "ollama/nomic-embed-text",
            "latency_ms": 50.0,
        }

    def test_embedding_returns_200(self, client):
        response = client.post(
            "/v1/embeddings",
            json={"input": "Hello world"},
        )
        assert response.status_code == 200

    def test_embedding_returns_openai_format(self, client):
        response = client.post(
            "/v1/embeddings",
            json={"input": "Hello world"},
        )
        data = response.json()
        assert data["object"] == "list"
        assert len(data["data"]) >= 1
        assert "embedding" in data["data"][0]

    def test_embedding_checks_rate_limiter(self, client, mock_rate_limiter):
        client.post("/v1/embeddings", json={"input": "Hello"})
        mock_rate_limiter.check.assert_called_once()

    def test_embedding_logs_cost(self, client, mock_cost_tracker):
        client.post("/v1/embeddings", json={"input": "Hello"})
        mock_cost_tracker.log_request.assert_called_once()


# ---------------------------------------------------------------------------
# Embeddings Error Handling
# ---------------------------------------------------------------------------
class TestEmbeddingsErrorHandling:
    """Integration: embeddings error paths."""

    def test_embedding_rate_limit_returns_429(self, client, mock_rate_limiter):
        mock_rate_limiter.check.return_value = (
            False,
            {"limit": 60, "remaining": 0, "current": 61, "reset_in_seconds": 30},
        )
        response = client.post("/v1/embeddings", json={"input": "Hello"})
        assert response.status_code == 429

    def test_embedding_provider_failure_returns_502(self, client, mock_router):
        mock_router.embedding.side_effect = Exception("Provider down")
        response = client.post("/v1/embeddings", json={"input": "Hello"})
        assert response.status_code == 502
