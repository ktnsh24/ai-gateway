# Rate Limiting Deep Dive — AI Gateway

> **What:** Per-key rate limiting using fixed-window counters
>
> **Why:** Protects LLM providers from abuse, ensures fair usage, controls costs
>
> **File:** `src/gateway/rate_limiter.py`

---

## Table of Contents

1. [Why Rate Limit an LLM Gateway?](#1-why-rate-limit-an-llm-gateway)
2. [Rate Limiter Strategy Pattern](#2-rate-limiter-strategy-pattern)
3. [Fixed-Window Algorithm](#3-fixed-window-algorithm)
4. [Redis Implementation](#4-redis-implementation)
5. [In-Memory Fallback](#5-in-memory-fallback)
6. [Per-Key Tracking](#6-per-key-tracking)
7. [429 Response Handling](#7-429-response-handling)
8. [Algorithm Comparison](#8-algorithm-comparison)
9. [Certification Relevance](#9-certification-relevance)
10. [Cross-References](#10-cross-references)

---

## 1. Why Rate Limit an LLM Gateway?

| Without Rate Limiting | With Rate Limiting | 🚚 Courier |
|----------------------|-------------------|-----------| 
| Single user can exhaust provider quota | Fair allocation across consumers | 🚚 Without a daily dispatch quota, one greedy courier books every courier and leaves all other callers waiting at the gateway door. |
| No cost control | Predictable cost ceiling | 🚚 A per-courier daily dispatch quota means the courier expense ledger never exceeds a known maximum no matter how many requests arrive. |
| DDoS → cascading failures | Graceful degradation with 429 | 🚚 A sudden flood of shipping manifests hits the gateway, but the daily dispatch quota absorbs the storm and returns 429 instead of crashing every courier. |
| No per-client visibility | Per-key usage tracking | 🚚 Each API key gets its own counter so the dispatch desk can see exactly how many deliveries each courier has made this window. |

### Cost Protection Example

```
Rate: 60 requests/min per key
LLM cost: ~$0.003/request (Claude 3.5 Sonnet, 1K tokens)
Max cost/hour/key: 60 × 60 × $0.003 = $10.80
Without limit: Unlimited → unbounded cost
```

---

## 2. Rate Limiter Strategy Pattern

```python
class BaseRateLimiter(ABC):
 """Abstract interface for rate limiting."""

 @abstractmethod
 async def check_rate_limit(self, key: str) -> bool:
 """Check if request is allowed. Returns True if allowed."""
 ...

 @abstractmethod
 async def get_remaining(self, key: str) -> int:
 """Get remaining requests in current window."""
 ...

 @abstractmethod
 async def reset(self, key: str) -> None:
 """Reset rate limit counter for key."""
 ...
```

### Implementations

| Class | Backend | Use Case | 🚚 Courier |
|-------|---------|----------|-----------|
| `RedisRateLimiter` | Redis | Production — shared across instances | 🚚 The dispatch quota counter lives on the fast pickup locker shelf so every depot instance shares the same running total accurately. |
| `InMemoryRateLimiter` | Python dict | Development — single instance | 🚚 delivery counts are stored as sticky notes in a single process — fine for the local environment but inaccurate across multiple depot instances. |
| `NoRateLimiter` | None | Testing — no limiting | 🚚 No daily dispatch quota enforced at all — every shipping manifests is accepted without checking any counter, used only during the automated test suite. |

### Factory

```python
def create_rate_limiter(settings: Settings) -> BaseRateLimiter:
 if not settings.rate_limit_enabled:
 return NoRateLimiter()
 if settings.redis_url:
 try:
 return RedisRateLimiter(settings)
 except Exception:
 return InMemoryRateLimiter(settings)
 return InMemoryRateLimiter(settings)
```

---

## 3. Fixed-Window Algorithm

The gateway uses a **fixed-window counter** — the simplest and most common rate limiting algorithm:

```
Window: |←── 60 seconds ──→|←── 60 seconds ──→|
Requests: [1][2][3]...[60] [1][2][3]...
 ↑ ↑
 Window start New window start
 (counter = 0) (counter resets)
```

### Algorithm Steps

```
1. Receive request with API key "abc123"
2. Compute window key: "gateway:rate:abc123:1714000020"
 (prefix : key_hash : minute_timestamp)
3. GET count from Redis
4. If count >= limit (60) → REJECT (429)
5. Else → INCR count
6. If new key → EXPIRE 60 seconds (auto-cleanup)
7. ALLOW request
```

### Redis Commands (Atomic)

```
INCR gateway:rate:{key}:{window} → returns new count
EXPIRE gateway:rate:{key}:{window} 60 → auto-delete after window
```

Both commands are atomic in Redis, so no race conditions even with concurrent requests.

---

## 4. Redis Implementation

```python
class RedisRateLimiter(BaseRateLimiter):
 def __init__(self, settings: Settings) -> None:
 self.redis = redis.asyncio.from_url(settings.redis_url)
 self.limit = settings.rate_limit_requests_per_minute
 self.window_seconds = 60

 async def check_rate_limit(self, key: str) -> bool:
 window = int(time.time()) // self.window_seconds
 rate_key = f"gateway:rate:{hashlib.sha256(key.encode()).hexdigest()[:16]}:{window}"

 count = await self.redis.incr(rate_key)
 if count == 1:
 await self.redis.expire(rate_key, self.window_seconds)

 return count <= self.limit

 async def get_remaining(self, key: str) -> int:
 window = int(time.time()) // self.window_seconds
 rate_key = f"gateway:rate:{hashlib.sha256(key.encode()).hexdigest()[:16]}:{window}"
 count = await self.redis.get(rate_key)
 current = int(count) if count else 0
 return max(0, self.limit - current)
```

### Key Hashing

API keys are hashed (`SHA-256[:16]`) in the Redis key to avoid storing sensitive keys:

```
Real key: sk-abc123xyz789
Redis key: gateway:rate:a1b2c3d4e5f6g7h8:28566667
```

---

## 5. In-Memory Fallback

```python
class InMemoryRateLimiter(BaseRateLimiter):
 def __init__(self, settings: Settings) -> None:
 self._counters: dict[str, dict] = {}
 self.limit = settings.rate_limit_requests_per_minute

 async def check_rate_limit(self, key: str) -> bool:
 window = int(time.time()) // 60
 counter_key = f"{key}:{window}"

 if counter_key not in self._counters:
 self._counters[counter_key] = {"count": 0, "window": window}
 # Clean old windows
 self._cleanup_old_windows()

 self._counters[counter_key]["count"] += 1
 return self._counters[counter_key]["count"] <= self.limit
```

### Limitations

| Feature | Redis | In-Memory | 🚚 Courier |
|---------|-------|-----------|-----------|
| Shared across instances | ✅ | ❌ (per-process) | 🚚 The Redis pickup locker shelf is visible to every running depot instance, so the daily dispatch quota is exact even with horizontal scaling. |
| Survives restart | ✅ | ❌ | 🚚 If the gateway restarts, the fast pickup locker shelf still holds the delivery count, but sticky-note counters vanish with the process. |
| Cleanup | TTL (automatic) | Manual (on access) | 🚚 Redis sets a TTL so old window keys auto-expire; sticky-note counters are only swept up when the next request triggers a cleanup pass. |
| Accuracy with N instances | Perfect | Rate = limit × N | 🚚 Ten depot instances sharing one Redis shelf all see the same count, but ten sticky-note boards each count independently, multiplying the effective limit. |

---

## 6. Per-Key Tracking

Rate limits are tracked per API key, so different consumers get independent limits:

```
API Key A: [45/60] requests this window → ALLOWED
API Key B: [60/60] requests this window → REJECTED (429)
API Key C: [12/60] requests this window → ALLOWED
```

When `API_KEYS_ENABLED=false`, all requests share one global key (`"anonymous"`):

```
Anonymous: [55/60] → All users share one limit
```

---

## 7. 429 Response Handling

When rate limit is exceeded:

```python
if not await rate_limiter.check_rate_limit(api_key):
 remaining = await rate_limiter.get_remaining(api_key)
 raise HTTPException(
 status_code=429,
 detail={
 "error": {
 "message": f"Rate limit exceeded. {remaining} requests remaining.",
 "type": "rate_limit_error",
 "code": 429,
 }
 },
 headers={"Retry-After": str(window_seconds_remaining)},
 )
```

**Response:**

```json
{
 "error": {
 "message": "Rate limit exceeded. 0 requests remaining.",
 "type": "rate_limit_error",
 "code": 429
 }
}
```

**Headers:**

```
HTTP/1.1 429 Too Many Requests
Retry-After: 45
```

---

## 8. Algorithm Comparison

| Algorithm | Complexity | Accuracy | Redis Commands | Gateway Uses | 🚚 Courier |
|-----------|-----------|----------|----------------|-------------|-----------|
| **Fixed Window** | Simple | Window boundary burst | 2 (INCR + EXPIRE) | ✅ | 🚚 The gateway uses this: two Redis commands count deliveries per clock-aligned minute window — simple, fast, and good enough for expensive courier calls. |
| Sliding Window Log | Medium | Perfect | N (store each timestamp) | ❌ | 🚚 Every shipping manifests's timestamp is stored separately so the quota window slides perfectly, but it burns more Redis shelf memory per courier. |
| Sliding Window Counter | Medium | Good approximation | 3 (two windows + interpolate) | ❌ | 🚚 Two overlapping fixed windows are blended to approximate a smooth daily dispatch quota without storing every timestamp, saving pickup locker shelf space. |
| Token Bucket | Complex | Smooth | 3+ (bucket + refill) | ❌ | 🚚 tokens drip back into the bucket at a steady rate, allowing short bursts while smoothing sustained courier load — but needs more Redis commands. |
| Leaky Bucket | Complex | Smooth | Queue-based | ❌ | 🚚 shipping manifests queue up and leak out at a fixed rate, giving the smoothest output but requiring a Redis-backed queue for each courier key. |

### Why Fixed Window?

1. **Simplest to implement** — 2 Redis commands
2. **Lowest latency** — O(1) check
3. **Good enough** — the boundary burst issue (2× limit at window edges) is acceptable for LLM gateways where requests are expensive and infrequent
4. **Production standard** — used by AWS API Gateway, Cloudflare, Stripe

### Boundary Burst Issue

```
Window 1: ....[58][59][60] ← 60 requests at end of window
Window 2: [1][2]...[60]... ← 60 requests at start of window
 ^^^^^^^^^^^
 120 requests in 2 seconds
 (but still 60 per window)
```

For an LLM gateway doing ~1 req/sec, this is not a practical concern.

---

## 9. Certification Relevance

| Cert Topic | Connection | 🚚 Courier |
|------------|------------|-----------|
| **AWS SAA-C03: API Gateway throttling** | Fixed window = API Gateway's default throttling | 🚚 AWS API Gateway uses the same fixed-window approach — the daily dispatch quota resets every clock minute, just like this depot's rate limiter. |
| **AWS SAA-C03: ElastiCache patterns** | Redis as rate limit store | 🚚 ElastiCache Redis is the production pickup locker shelf for dispatch quota counters — a classic AWS caching-and-rate-limit pattern for the exam. |
| **AZ-305: API Management** | Rate limiting policies | 🚚 Azure API Management enforces delivery quotas via rate-limiting policies, mirroring the fixed-window counter the gateway implements in Python. |
| **AZ-305: Azure Cache for Redis** | Distributed rate limiting | 🚚 Azure Cache for Redis is the Azure pickup locker shelf that stores distributed dispatch quota counters across multiple depot container instances. |

---

## 10. Cross-References

| Topic | Document | 🚚 Courier |
|-------|----------|-----------|
| Architecture overview | [Architecture](../architecture-and-design/architecture.md) | 🚚 The full depot blueprint shows where the dispatch quota check sits in the request pipeline relative to the cache and courier router. |
| Caching (same Redis) | [Caching Deep Dive](caching-deep-dive.md) | 🚚 The same fast pickup locker shelf holds both dispatch quota counters and the semantic-reply cache on separate key prefixes. |
| Cost tracking | [Cost Tracking Deep Dive](cost-tracking-deep-dive.md) | 🚚 delivery quotas protect the courier expense ledger from runaway costs; see the cost deep dive for how spending is recorded per request. |
| API contract (429 response) | [API Contract](../architecture-and-design/api-contract.md) | 🚚 When a courier exceeds their quota, the gateway's entry point returns a 429 with a Retry-After header as documented in the contract. |
| Lab: Rate limit testing | [Labs Phase 1](../hands-on-labs/hands-on-labs-phase-1.md) | 🚚 The hands-on lab shows how to fire enough requests to trigger the 429 and observe the dispatch quota counter in Redis directly. |
