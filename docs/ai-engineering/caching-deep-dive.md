# Caching Deep Dive — AI Gateway

> **What:** Semantic caching stores LLM responses and returns them for identical or semantically similar requests
>
> **Why:** Reduces latency from seconds to milliseconds, eliminates redundant LLM costs
>
> **File:** `src/gateway/cache.py`

---

## Table of Contents

1. [Why Cache LLM Responses?](#1-why-cache-llm-responses)
2. [Cache Strategy Pattern](#2-cache-strategy-pattern)
3. [Cache Key Generation](#3-cache-key-generation)
4. [Exact Match vs Semantic Match](#4-exact-match-vs-semantic-match)
5. [Redis Implementation](#5-redis-implementation)
6. [In-Memory Fallback](#6-in-memory-fallback)
7. [Cache Invalidation](#7-cache-invalidation)
8. [Performance Characteristics](#8-performance-characteristics)
9. [Certification Relevance](#9-certification-relevance)
10. [Cross-References](#10-cross-references)

---

## 1. Why Cache LLM Responses?

| Without Cache | With Cache |
|--------------|------------|
| Every request → LLM provider | Repeated questions → instant response |
| 1-5 seconds per request | <10ms for cache hits |
| Full token cost every time | Zero cost for cache hits |
| Provider rate limits hit faster | Provider calls reduced 20-40% |

### Real-World Impact

If 25% of requests are cache hits:
- **Latency:** 25% of requests go from ~2s → ~5ms (400x faster)
- **Cost:** 25% token cost savings
- **Throughput:** Can handle 25% more traffic without scaling LLM

---

## 2. Cache Strategy Pattern

```python
class BaseCache(ABC):
    """Abstract interface for caching."""

    @abstractmethod
    async def get(self, messages: list[dict], model: str, temperature: float) -> dict | None:
        """Look up cached response. Returns None on miss."""
        ...

    @abstractmethod
    async def set(self, messages: list[dict], model: str, temperature: float, response: dict) -> None:
        """Store response in cache."""
        ...

    @abstractmethod
    async def invalidate(self, pattern: str | None = None) -> int:
        """Clear cached entries. Returns count cleared."""
        ...

    @abstractmethod
    async def stats(self) -> dict:
        """Return cache statistics."""
        ...
```

### Implementations

| Class | Backend | Use Case |
|-------|---------|----------|
| `RedisSemanticCache` | Redis 7 | Production — persistent, distributed |
| `InMemoryCache` | Python dict | Development — no Redis needed |
| `NoCache` | None | Testing — no caching at all |

### Factory Selection

```python
def create_cache(settings: Settings) -> BaseCache:
    if not settings.cache_enabled:
        return NoCache()
    if settings.redis_url:
        try:
            return RedisSemanticCache(settings)
        except Exception:
            logger.warning("Redis unavailable, falling back to in-memory cache")
            return InMemoryCache(settings)
    return InMemoryCache(settings)
```

---

## 3. Cache Key Generation

The cache key must uniquely identify a request. Two requests should hit the same cache entry **only if they would produce the same response**.

### Exact Match Key (SHA-256)

```python
def _make_cache_key(self, messages: list[dict], model: str, temperature: float) -> str:
    key_data = json.dumps(
        {"messages": messages, "model": model, "temperature": temperature},
        sort_keys=True,
        ensure_ascii=True,
    )
    hash_hex = hashlib.sha256(key_data.encode()).hexdigest()
    return f"gateway:cache:{hash_hex}"
```

### Why These Fields?

| Field | Included? | Why |
|-------|-----------|-----|
| `messages` | ✅ | Different questions → different answers |
| `model` | ✅ | Different models → different answers |
| `temperature` | ✅ | Higher temperature → different phrasing |
| `max_tokens` | ❌ | Same answer, just truncated |
| `timestamp` | ❌ | Would make every request unique |

### Key Design: `sort_keys=True`

```python
# These produce the SAME cache key:
{"messages": [{"role": "user", "content": "Hi"}], "model": "default", "temperature": 0.7}
{"temperature": 0.7, "model": "default", "messages": [{"role": "user", "content": "Hi"}]}
```

Without `sort_keys=True`, JSON key ordering would create different hashes for identical requests.

---

## 4. Exact Match vs Semantic Match

### Exact Match

```
User: "What is the capital of France?"
Cache: "What is the capital of France?" → EXACT MATCH → return cached
```

Fast (O(1) hash lookup), but misses slight rephrasing.

### Semantic Match

```
User: "What's the capital city of France?"
Cache: "What is the capital of France?" → cosine_sim = 0.96 > 0.92 → SEMANTIC MATCH
```

The gateway generates an embedding of the last user message and compares it against stored embeddings using cosine similarity:

```python
async def _semantic_lookup(self, messages: list[dict]) -> dict | None:
    last_user_msg = messages[-1]["content"]
    query_embedding = await self._embed(last_user_msg)

    for stored_key, stored_data in self._semantic_index.items():
        similarity = self._cosine_similarity(
            query_embedding, stored_data["embedding"]
        )
        if similarity >= self.settings.cache_similarity_threshold:
            return stored_data["response"]
    return None
```

### Similarity Threshold

| Threshold | Behaviour |
|-----------|-----------|
| `0.99` | Almost exact match only |
| `0.95` | Close paraphrases |
| `0.92` | **Default** — balances precision and recall |
| `0.85` | Loose matching — risks wrong cache hits |
| `0.80` | Too loose — semantically different questions match |

The threshold is configured via `CACHE_SIMILARITY_THRESHOLD`.

### Cosine Similarity Formula

$$\text{cosine\_similarity}(\mathbf{a}, \mathbf{b}) = \frac{\mathbf{a} \cdot \mathbf{b}}{|\mathbf{a}| \cdot |\mathbf{b}|}$$

```python
def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
    a_arr, b_arr = np.array(a), np.array(b)
    dot_product = np.dot(a_arr, b_arr)
    norm_a, norm_b = np.linalg.norm(a_arr), np.linalg.norm(b_arr)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot_product / (norm_a * norm_b))
```

---

## 5. Redis Implementation

### Data Structure

```
Redis Key                                      Value
─────────────────────────────────────          ──────
gateway:cache:{sha256_hash}                     JSON: {response, embedding, created_at}
```

Each cache entry stores:
- **response** — The full LLM response (serialised JSON)
- **embedding** — The embedding vector of the last user message (for semantic match)
- **created_at** — Timestamp for TTL management

### TTL

All cache entries have a TTL (default: 3600 seconds = 1 hour):

```python
await self.redis.setex(cache_key, self.settings.cache_ttl_seconds, json.dumps(entry))
```

After TTL expires, Redis automatically deletes the entry.

### Connection Management

```python
class RedisSemanticCache(BaseCache):
    def __init__(self, settings: Settings) -> None:
        self.redis = redis.asyncio.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
```

---

## 6. In-Memory Fallback

When Redis is unavailable, the `InMemoryCache` provides the same interface:

```python
class InMemoryCache(BaseCache):
    def __init__(self, settings: Settings) -> None:
        self._store: dict[str, dict] = {}
        self._hits = 0
        self._misses = 0
        self._max_size = 1000
```

### Differences from Redis

| Feature | Redis | In-Memory |
|---------|-------|-----------|
| Persistence | Across restarts | Lost on restart |
| Shared | Across processes | Per process |
| TTL | Native Redis TTL | Checked on access |
| Max size | Limited by Redis memory | 1000 entries (LRU) |
| Semantic match | ✅ | ✅ (same algorithm) |

---

## 7. Cache Invalidation

### Full Clear

```python
await cache.invalidate()  # Clear all entries
```

### Pattern Clear

```python
await cache.invalidate(pattern="gateway:cache:*")  # Clear matching keys
```

### TTL-Based

Entries expire automatically after `CACHE_TTL_SECONDS` (default 3600).

### Per-Request Bypass

Clients can bypass cache for a specific request:

```json
{
  "messages": [...],
  "bypass_cache": true
}
```

---

## 8. Performance Characteristics

| Operation | Redis | In-Memory |
|-----------|-------|-----------|
| Exact match lookup | ~1ms | ~0.1ms |
| Semantic match (100 entries) | ~5ms | ~3ms |
| Semantic match (1000 entries) | ~50ms | ~30ms |
| Cache store | ~1ms | ~0.1ms |

### When Cache Size Grows

The semantic matching is O(n) — it compares against every cached embedding. For large caches (>1000 entries), consider:
- FAISS index for approximate nearest neighbour search
- Pre-filtering by model/temperature before similarity search
- Limiting semantic index to recent entries

---

## 9. Certification Relevance

| Cert Topic | Connection |
|------------|------------|
| **AWS SAA-C03: ElastiCache** | Redis caching strategies, TTL management |
| **AWS SAA-C03: Caching patterns** | Cache-aside pattern with semantic matching |
| **AZ-305: Azure Cache for Redis** | Same concepts, Azure implementation |
| **AZ-305: Performance optimisation** | Reducing latency via intelligent caching |

---

## 10. Cross-References

| Topic | Document |
|-------|----------|
| Architecture overview | [Architecture](../architecture-and-design/architecture.md) |
| LLM routing | [LiteLLM Deep Dive](litellm-deep-dive.md) |
| Rate limiting | [Rate Limiting Deep Dive](rate-limiting-deep-dive.md) |
| Cost tracking | [Cost Tracking Deep Dive](cost-tracking-deep-dive.md) |
| Redis setup | [Docker Compose Guide](../setup-and-tooling/docker-compose-guide.md) |
| Lab: Cache testing | [Labs Phase 1](../hands-on-labs/hands-on-labs-phase-1.md) |
