"""
Tests for the AI Gateway cost tracker implementations.

Tests:
    - InMemoryCostTracker logs and retrieves requests
    - InMemoryCostTracker aggregates by period
    - InMemoryCostTracker breakdowns by model and provider
    - NoCostTracker returns disabled status
"""

import pytest
from src.gateway.cost_tracker import InMemoryCostTracker, NoCostTracker


@pytest.fixture
def tracker():
    return InMemoryCostTracker()


class TestInMemoryCostTracker:
    """Tests for InMemoryCostTracker."""

    @pytest.mark.asyncio
    async def test_log_and_retrieve(self, tracker):
        await tracker.log_request(
            request_id="req-001",
            api_key="test-key",
            model="ollama/llama3.2",
            provider="local",
            prompt_tokens=100,
            completion_tokens=50,
            estimated_cost_usd=0.0,
            latency_ms=500.0,
        )

        summary = await tracker.get_usage_summary(period="today")
        assert summary["total_requests"] == 1
        assert summary["total_tokens"] == 150
        assert summary["total_cost_usd"] == 0.0

    @pytest.mark.asyncio
    async def test_multiple_requests(self, tracker):
        for i in range(3):
            await tracker.log_request(
                request_id=f"req-{i}",
                api_key="test-key",
                model="ollama/llama3.2",
                provider="local",
                prompt_tokens=100,
                completion_tokens=50,
                estimated_cost_usd=0.001,
                latency_ms=500.0 + i * 100,
            )

        summary = await tracker.get_usage_summary(period="today")
        assert summary["total_requests"] == 3
        assert summary["total_tokens"] == 450
        assert summary["total_cost_usd"] == 0.003

    @pytest.mark.asyncio
    async def test_breakdown_by_model(self, tracker):
        await tracker.log_request(
            request_id="req-1", api_key="k", model="llama3.2", provider="local",
            prompt_tokens=10, completion_tokens=5, estimated_cost_usd=0, latency_ms=100,
        )
        await tracker.log_request(
            request_id="req-2", api_key="k", model="gpt-4o", provider="azure",
            prompt_tokens=10, completion_tokens=5, estimated_cost_usd=0.01, latency_ms=200,
        )

        summary = await tracker.get_usage_summary(period="today")
        assert "llama3.2" in summary["requests_by_model"]
        assert "gpt-4o" in summary["requests_by_model"]

    @pytest.mark.asyncio
    async def test_breakdown_by_provider(self, tracker):
        await tracker.log_request(
            request_id="req-1", api_key="k", model="llama3.2", provider="local",
            prompt_tokens=10, completion_tokens=5, estimated_cost_usd=0, latency_ms=100,
        )
        await tracker.log_request(
            request_id="req-2", api_key="k", model="claude", provider="aws",
            prompt_tokens=10, completion_tokens=5, estimated_cost_usd=0.005, latency_ms=200,
        )

        summary = await tracker.get_usage_summary(period="today")
        assert "local" in summary["cost_by_provider"]
        assert "aws" in summary["cost_by_provider"]
        assert summary["cost_by_provider"]["aws"] == 0.005

    @pytest.mark.asyncio
    async def test_cache_hit_rate(self, tracker):
        await tracker.log_request(
            request_id="req-1", api_key="k", model="m", provider="p",
            prompt_tokens=10, completion_tokens=5, estimated_cost_usd=0, latency_ms=100,
            cached=True,
        )
        await tracker.log_request(
            request_id="req-2", api_key="k", model="m", provider="p",
            prompt_tokens=10, completion_tokens=5, estimated_cost_usd=0.01, latency_ms=500,
            cached=False,
        )

        summary = await tracker.get_usage_summary(period="today")
        assert summary["cache_hit_rate"] == 0.5


class TestNoCostTracker:
    """Tests for NoCostTracker (disabled)."""

    @pytest.mark.asyncio
    async def test_returns_disabled(self):
        tracker = NoCostTracker()
        summary = await tracker.get_usage_summary()
        assert summary["enabled"] is False
