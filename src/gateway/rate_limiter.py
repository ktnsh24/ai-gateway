"""
AI Gateway — Rate Limiter (Redis)

Enforces per-API-key request limits using a sliding window algorithm.
Prevents any single consumer from overwhelming the LLM providers.

Algorithm: Fixed Window Counter
- Each API key gets a counter in Redis with a 1-minute TTL
- If counter > limit → reject with HTTP 429 (Too Many Requests)
- Counter auto-resets every minute (Redis TTL handles cleanup)

Why not sliding window? Simpler to implement and understand. The fixed window
can allow up to 2× burst at the window boundary, but for LLM rate limiting
this is acceptable — LLM providers have their own rate limits as a backstop.

See docs/ai-engineering/rate-limiting-deep-dive.md for detailed explanation.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod

from loguru import logger

from src.config import Settings


class BaseRateLimiter(ABC):
    """Abstract base class for rate limiting."""

    @abstractmethod
    async def check(self, api_key: str) -> tuple[bool, dict]:
        """Check if a request is allowed.

        Returns:
            (allowed: bool, info: dict with remaining, limit, reset_at)
        """

    @abstractmethod
    async def get_usage(self, api_key: str) -> dict:
        """Get current usage for an API key."""


class RedisRateLimiter(BaseRateLimiter):
    """Redis-backed fixed-window rate limiter.

    Uses Redis INCR + EXPIRE for atomic increment-and-expire.
    This is the standard pattern used by API gateways (Kong, AWS API Gateway).
    """

    def __init__(self, settings: Settings) -> None:
        self._limit = settings.rate_limit_requests_per_minute
        self._window_seconds = 60
        self._prefix = "gw:rate:"
        self._client = None
        self._settings = settings

    async def _get_client(self):
        """Lazy-init Redis client."""
        if self._client is None:
            import redis.asyncio as aioredis

            self._client = aioredis.from_url(
                self._settings.redis_url,
                decode_responses=True,
            )
        return self._client

    async def check(self, api_key: str) -> tuple[bool, dict]:
        """Check rate limit for an API key.

        Uses Redis INCR (atomic increment) + EXPIRE (auto-cleanup).
        """
        client = await self._get_client()
        key = f"{self._prefix}{api_key}"

        # Atomic increment
        current = await client.incr(key)

        # Set TTL on first request in window
        if current == 1:
            await client.expire(key, self._window_seconds)

        ttl = await client.ttl(key)
        remaining = max(0, self._limit - current)

        info = {
            "limit": self._limit,
            "remaining": remaining,
            "reset_in_seconds": max(0, ttl),
            "current": current,
        }

        if current > self._limit:
            logger.warning(f"Rate limit exceeded: key={api_key[:8]}..., count={current}/{self._limit}")
            return False, info

        return True, info

    async def get_usage(self, api_key: str) -> dict:
        """Get current usage for an API key."""
        client = await self._get_client()
        key = f"{self._prefix}{api_key}"
        current = await client.get(key)
        ttl = await client.ttl(key)
        return {
            "api_key": api_key[:8] + "...",
            "current": int(current) if current else 0,
            "limit": self._limit,
            "reset_in_seconds": max(0, ttl),
        }


class InMemoryRateLimiter(BaseRateLimiter):
    """Simple in-memory rate limiter for local development (no Redis needed).

    Uses a dict of {api_key: (count, window_start)}.
    Not suitable for production (single process only).
    """

    def __init__(self, settings: Settings) -> None:
        self._limit = settings.rate_limit_requests_per_minute
        self._window_seconds = 60
        self._counters: dict[str, tuple[int, float]] = {}

    async def check(self, api_key: str) -> tuple[bool, dict]:
        now = time.time()

        if api_key in self._counters:
            count, window_start = self._counters[api_key]
            if now - window_start >= self._window_seconds:
                # Window expired, reset
                self._counters[api_key] = (1, now)
                count = 1
            else:
                count += 1
                self._counters[api_key] = (count, window_start)
        else:
            count = 1
            self._counters[api_key] = (1, now)

        remaining = max(0, self._limit - count)
        window_start = self._counters[api_key][1]
        reset_in = max(0, self._window_seconds - (now - window_start))

        info = {
            "limit": self._limit,
            "remaining": remaining,
            "reset_in_seconds": int(reset_in),
            "current": count,
        }

        if count > self._limit:
            return False, info
        return True, info

    async def get_usage(self, api_key: str) -> dict:
        if api_key in self._counters:
            count, _ = self._counters[api_key]
        else:
            count = 0
        return {
            "api_key": api_key[:8] + "...",
            "current": count,
            "limit": self._limit,
        }


class NoRateLimiter(BaseRateLimiter):
    """No-op rate limiter — used when rate limiting is disabled."""

    async def check(self, api_key: str) -> tuple[bool, dict]:
        return True, {"limit": -1, "remaining": -1, "current": 0}

    async def get_usage(self, api_key: str) -> dict:
        return {"enabled": False}


def create_rate_limiter(settings: Settings) -> BaseRateLimiter:
    """Factory method — creates the appropriate rate limiter implementation."""
    if not settings.rate_limit_enabled:
        logger.info("Rate limiting disabled")
        return NoRateLimiter()

    try:
        import redis

        r = redis.from_url(settings.redis_url, socket_connect_timeout=1)
        r.ping()
        logger.info("Rate limiter: Redis")
        return RedisRateLimiter(settings)
    except Exception:
        logger.warning("Redis not available, falling back to in-memory rate limiter")
        return InMemoryRateLimiter(settings)
