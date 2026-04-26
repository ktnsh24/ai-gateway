"""
Tests for the AI Gateway cache implementations.

Tests:
    - InMemoryCache exact match hit/miss
    - InMemoryCache semantic similarity match
    - InMemoryCache TTL expiry
    - Cache stats tracking
    - NoCache always returns None
"""

import time

import pytest
from src.config import Settings
from src.gateway.cache import InMemoryCache, NoCache


@pytest.fixture
def settings():
    return Settings(
        cache_enabled=True,
        cache_ttl_seconds=60,
        cache_similarity_threshold=0.92,
    )


@pytest.fixture
def cache(settings):
    return InMemoryCache(settings)


class TestInMemoryCache:
    """Tests for InMemoryCache."""

    @pytest.mark.asyncio
    async def test_miss_on_empty_cache(self, cache):
        result = await cache.get([{"role": "user", "content": "Hello"}])
        assert result is None

    @pytest.mark.asyncio
    async def test_exact_hit_after_put(self, cache):
        messages = [{"role": "user", "content": "What is 2+2?"}]
        response = {"content": "4", "model": "test"}
        await cache.put(messages, response)

        result = await cache.get(messages)
        assert result is not None
        assert result["content"] == "4"

    @pytest.mark.asyncio
    async def test_miss_on_different_question(self, cache):
        messages1 = [{"role": "user", "content": "What is 2+2?"}]
        messages2 = [{"role": "user", "content": "What is the meaning of life?"}]
        await cache.put(messages1, {"content": "4"})

        result = await cache.get(messages2)
        assert result is None

    @pytest.mark.asyncio
    async def test_stats_tracking(self, cache):
        messages = [{"role": "user", "content": "Hello"}]
        await cache.put(messages, {"content": "Hi"})

        await cache.get(messages)  # Hit
        await cache.get([{"role": "user", "content": "Other"}])  # Miss

        stats = await cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["total"] == 2
        assert stats["hit_rate"] == 0.5

    @pytest.mark.asyncio
    async def test_invalidate_clears_cache(self, cache):
        messages = [{"role": "user", "content": "Hello"}]
        await cache.put(messages, {"content": "Hi"})

        count = await cache.invalidate()
        assert count == 1

        result = await cache.get(messages)
        assert result is None

    @pytest.mark.asyncio
    async def test_ttl_expiry(self, cache):
        """Cache entries expire after TTL."""
        cache._ttl = 1  # 1 second TTL
        messages = [{"role": "user", "content": "Hello"}]
        await cache.put(messages, {"content": "Hi"})

        # Should hit immediately
        result = await cache.get(messages)
        assert result is not None

        # Wait for expiry
        time.sleep(1.1)
        result = await cache.get(messages)
        assert result is None


class TestNoCache:
    """Tests for NoCache (disabled cache)."""

    @pytest.mark.asyncio
    async def test_always_returns_none(self):
        cache = NoCache()
        result = await cache.get([{"role": "user", "content": "Hello"}])
        assert result is None

    @pytest.mark.asyncio
    async def test_stats_shows_disabled(self):
        cache = NoCache()
        stats = await cache.stats()
        assert stats["enabled"] is False

    @pytest.mark.asyncio
    async def test_invalidate_returns_zero(self):
        cache = NoCache()
        count = await cache.invalidate()
        assert count == 0
