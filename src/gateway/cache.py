"""
AI Gateway — Semantic Cache (Redis)

Caches LLM responses keyed by semantic similarity of the prompt.
If a new question is ≥92% similar to a cached question, returns the cached answer
without calling the LLM (saving both time and money).

How it works:
1. Incoming question → generate embedding
2. Compare embedding against cached embeddings using cosine similarity
3. If similarity ≥ threshold → cache HIT (return cached response)
4. If similarity < threshold → cache MISS (call LLM, then cache the result)

Cost impact: ~30% reduction in LLM calls for repetitive queries (e.g., support bots).

See docs/ai-engineering/caching-deep-dive.md for detailed explanation.
"""

from __future__ import annotations

import hashlib
import json
import time
from abc import ABC, abstractmethod

import numpy as np
from loguru import logger

from src.config import Settings


class BaseCache(ABC):
    """Abstract base class for semantic caching.

    Strategy Pattern — same interface whether using Redis, in-memory, or no cache.
    """

    @abstractmethod
    async def get(self, messages: list[dict], embedding: list[float] | None = None) -> dict | None:
        """Look up a cached response. Returns None on cache miss."""

    @abstractmethod
    async def put(
        self,
        messages: list[dict],
        response: dict,
        embedding: list[float] | None = None,
        ttl: int | None = None,
    ) -> None:
        """Store a response in the cache."""

    @abstractmethod
    async def invalidate(self, pattern: str = "*") -> int:
        """Remove cache entries matching a pattern. Returns count removed."""

    @abstractmethod
    async def stats(self) -> dict:
        """Return cache statistics (hits, misses, size)."""


class RedisSemanticCache(BaseCache):
    """Redis-backed semantic cache with cosine similarity matching.

    Each cache entry stores:
    - key: hash of the messages
    - embedding: vector representation of the prompt
    - response: the full LLM response
    - timestamp: when it was cached
    - ttl: automatic expiry

    Lookup:
    1. Hash the messages → check exact match first (fast path)
    2. If no exact match → compare embeddings of recent entries (semantic path)
    3. Return the entry with highest similarity above threshold
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._threshold = settings.cache_similarity_threshold
        self._ttl = settings.cache_ttl_seconds
        self._prefix = "gw:cache:"
        self._hits = 0
        self._misses = 0
        self._client = None

    async def _get_client(self):
        """Lazy-init Redis client."""
        if self._client is None:
            import redis.asyncio as aioredis

            self._client = aioredis.from_url(
                self._settings.redis_url,
                decode_responses=True,
            )
        return self._client

    @staticmethod
    def _hash_messages(messages: list[dict]) -> str:
        """Create a deterministic hash of the conversation messages."""
        content = json.dumps(messages, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        a_np = np.array(a)
        b_np = np.array(b)
        dot = np.dot(a_np, b_np)
        norm = np.linalg.norm(a_np) * np.linalg.norm(b_np)
        if norm == 0:
            return 0.0
        return float(dot / norm)

    async def get(self, messages: list[dict], embedding: list[float] | None = None) -> dict | None:
        """Look up a cached response.

        1. Try exact hash match (fast)
        2. If embedding provided, try semantic similarity match (slower but smarter)
        """
        client = await self._get_client()
        msg_hash = self._hash_messages(messages)

        # Fast path: exact match
        exact_key = f"{self._prefix}exact:{msg_hash}"
        cached = await client.get(exact_key)
        if cached:
            self._hits += 1
            logger.debug(f"Cache HIT (exact): {msg_hash[:8]}...")
            return json.loads(cached)

        # Semantic path: compare embeddings
        if embedding:
            semantic_keys = await client.keys(f"{self._prefix}semantic:*")
            best_match = None
            best_score = 0.0

            for key in semantic_keys[:100]:  # Limit scan for performance
                entry_data = await client.get(key)
                if not entry_data:
                    continue
                entry = json.loads(entry_data)
                if "embedding" not in entry:
                    continue

                score = self._cosine_similarity(embedding, entry["embedding"])
                if score > best_score:
                    best_score = score
                    best_match = entry

            if best_match and best_score >= self._threshold:
                self._hits += 1
                logger.info(f"Cache HIT (semantic): similarity={best_score:.4f}")
                return best_match.get("response")

        self._misses += 1
        logger.debug(f"Cache MISS: {msg_hash[:8]}...")
        return None

    async def put(
        self,
        messages: list[dict],
        response: dict,
        embedding: list[float] | None = None,
        ttl: int | None = None,
    ) -> None:
        """Store a response in the cache."""
        client = await self._get_client()
        msg_hash = self._hash_messages(messages)
        ttl = ttl or self._ttl

        # Store exact match
        exact_key = f"{self._prefix}exact:{msg_hash}"
        await client.set(exact_key, json.dumps(response), ex=ttl)

        # Store semantic entry (with embedding)
        if embedding:
            semantic_key = f"{self._prefix}semantic:{msg_hash}"
            entry = {
                "embedding": embedding,
                "response": response,
                "timestamp": time.time(),
            }
            await client.set(semantic_key, json.dumps(entry), ex=ttl)

        logger.debug(f"Cached response: {msg_hash[:8]}... (ttl={ttl}s)")

    async def invalidate(self, pattern: str = "*") -> int:
        """Remove cache entries matching a pattern."""
        client = await self._get_client()
        keys = await client.keys(f"{self._prefix}{pattern}")
        if keys:
            count = await client.delete(*keys)
            logger.info(f"Invalidated {count} cache entries")
            return count
        return 0

    async def stats(self) -> dict:
        """Return cache statistics."""
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0.0
        return {
            "hits": self._hits,
            "misses": self._misses,
            "total": total,
            "hit_rate": round(hit_rate, 4),
        }


class InMemoryCache(BaseCache):
    """Simple in-memory cache for local development (no Redis needed).

    Uses a Python dict with TTL tracking. Not suitable for production
    (no persistence, no distribution), but perfect for running labs locally.
    """

    def __init__(self, settings: Settings) -> None:
        self._ttl = settings.cache_ttl_seconds
        self._threshold = settings.cache_similarity_threshold
        self._store: dict[str, dict] = {}
        self._hits = 0
        self._misses = 0

    async def get(self, messages: list[dict], embedding: list[float] | None = None) -> dict | None:
        msg_hash = RedisSemanticCache._hash_messages(messages)

        # Check exact match
        if msg_hash in self._store:
            entry = self._store[msg_hash]
            if time.time() - entry.get("timestamp", 0) < self._ttl:
                self._hits += 1
                return entry["response"]
            else:
                del self._store[msg_hash]

        # Check semantic match
        if embedding:
            for key, entry in list(self._store.items()):
                if "embedding" not in entry:
                    continue
                if time.time() - entry.get("timestamp", 0) >= self._ttl:
                    del self._store[key]
                    continue
                score = RedisSemanticCache._cosine_similarity(embedding, entry["embedding"])
                if score >= self._threshold:
                    self._hits += 1
                    return entry["response"]

        self._misses += 1
        return None

    async def put(
        self,
        messages: list[dict],
        response: dict,
        embedding: list[float] | None = None,
        ttl: int | None = None,
    ) -> None:
        msg_hash = RedisSemanticCache._hash_messages(messages)
        self._store[msg_hash] = {
            "response": response,
            "embedding": embedding,
            "timestamp": time.time(),
        }

    async def invalidate(self, pattern: str = "*") -> int:
        count = len(self._store)
        self._store.clear()
        return count

    async def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "total": total,
            "hit_rate": round(self._hits / total, 4) if total > 0 else 0.0,
            "size": len(self._store),
        }


class NoCache(BaseCache):
    """No-op cache — used when caching is disabled."""

    async def get(self, messages: list[dict], embedding: list[float] | None = None) -> dict | None:
        return None

    async def put(self, messages: list[dict], response: dict, **kwargs) -> None:
        pass

    async def invalidate(self, pattern: str = "*") -> int:
        return 0

    async def stats(self) -> dict:
        return {"enabled": False}


def create_cache(settings: Settings) -> BaseCache:
    """Factory method — creates the appropriate cache implementation."""
    if not settings.cache_enabled:
        logger.info("Cache disabled")
        return NoCache()

    if settings.cloud_provider.value == "local" and "localhost" in settings.redis_url:
        # Check if Redis is available for local dev
        try:
            import redis

            r = redis.from_url(settings.redis_url, socket_connect_timeout=1)
            r.ping()
            logger.info("Cache: Redis (local)")
            return RedisSemanticCache(settings)
        except Exception:
            logger.warning("Redis not available, falling back to in-memory cache")
            return InMemoryCache(settings)

    logger.info("Cache: Redis")
    return RedisSemanticCache(settings)
