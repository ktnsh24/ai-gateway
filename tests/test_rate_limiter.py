"""
Tests for the AI Gateway rate limiter implementations.

Tests:
    - InMemoryRateLimiter allows requests within limit
    - InMemoryRateLimiter rejects requests over limit
    - InMemoryRateLimiter resets after window expires
    - NoRateLimiter always allows
"""

import time

import pytest
from src.config import Settings
from src.gateway.rate_limiter import InMemoryRateLimiter, NoRateLimiter


@pytest.fixture
def settings():
    return Settings(
        rate_limit_enabled=True,
        rate_limit_requests_per_minute=5,
    )


@pytest.fixture
def limiter(settings):
    return InMemoryRateLimiter(settings)


class TestInMemoryRateLimiter:
    """Tests for InMemoryRateLimiter."""

    @pytest.mark.asyncio
    async def test_allows_first_request(self, limiter):
        allowed, info = await limiter.check("test-key")
        assert allowed is True
        assert info["remaining"] == 4
        assert info["current"] == 1

    @pytest.mark.asyncio
    async def test_allows_requests_within_limit(self, limiter):
        for i in range(5):
            allowed, info = await limiter.check("test-key")
            assert allowed is True
            assert info["current"] == i + 1

    @pytest.mark.asyncio
    async def test_rejects_over_limit(self, limiter):
        # Use all 5 allowed requests
        for _ in range(5):
            await limiter.check("test-key")

        # 6th should be rejected
        allowed, info = await limiter.check("test-key")
        assert allowed is False
        assert info["remaining"] == 0
        assert info["current"] == 6

    @pytest.mark.asyncio
    async def test_different_keys_have_separate_limits(self, limiter):
        # Use all 5 for key-a
        for _ in range(5):
            await limiter.check("key-a")

        # key-b should still be allowed
        allowed, _ = await limiter.check("key-b")
        assert allowed is True

    @pytest.mark.asyncio
    async def test_window_resets(self, limiter):
        """Rate limit resets after the window expires."""
        limiter._window_seconds = 1  # 1 second window

        # Use all 5
        for _ in range(5):
            await limiter.check("test-key")

        # Rejected
        allowed, _ = await limiter.check("test-key")
        assert allowed is False

        # Wait for window to expire
        time.sleep(1.1)

        # Should be allowed again
        allowed, info = await limiter.check("test-key")
        assert allowed is True
        assert info["current"] == 1

    @pytest.mark.asyncio
    async def test_get_usage(self, limiter):
        await limiter.check("test-key")
        await limiter.check("test-key")

        usage = await limiter.get_usage("test-key")
        assert usage["current"] == 2
        assert usage["limit"] == 5


class TestNoRateLimiter:
    """Tests for NoRateLimiter (disabled rate limiting)."""

    @pytest.mark.asyncio
    async def test_always_allows(self):
        limiter = NoRateLimiter()
        allowed, info = await limiter.check("any-key")
        assert allowed is True
        assert info["limit"] == -1

    @pytest.mark.asyncio
    async def test_usage_shows_disabled(self):
        limiter = NoRateLimiter()
        usage = await limiter.get_usage("any-key")
        assert usage["enabled"] is False
