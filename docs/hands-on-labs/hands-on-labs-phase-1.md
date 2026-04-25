# Hands-on Labs — Phase 1: Gateway Foundation

> **Labs 1-4:** Build and test the core gateway components step by step
>
> **Time:** ~2 hours total
>
> **Prerequisites:** Poetry, Ollama with llama3.2 + nomic-embed-text

---

## Table of Contents

- [Cost Estimation — Local vs Cloud](#cost-estimation--local-vs-cloud)
- [Lab 1: First Request Through the Gateway](#lab-1-first-request-through-the-gateway)
- [Lab 2: Semantic Cache in Action](#lab-2-semantic-cache-in-action)
- [Lab 3: Rate Limiting](#lab-3-rate-limiting)
- [Lab 4: Embeddings Endpoint](#lab-4-embeddings-endpoint)

---

## Cost Estimation — Local vs Cloud

All labs run **locally for free**. Cloud costs if you deploy:

| Stack | Per lab session (~50 queries) | Monthly (always on) | Best for | 🚚 Courier |
|-------|-------------------------------|---------------------|----------|-----------|
| **Local (Ollama + Redis + PostgreSQL)** | $0 | $0 | Learning, experimenting | 🚚 Running the whole service locally costs nothing, letting you practise every dispatch workflow without logging a single cent in the expense ledger. |
| **AWS (cheapest)** | ~$0.03 | ~$35/mo (ElastiCache + RDS) | Proving cloud skills | 🚚 The AWS depot charges about three cents per lab session, proving you can run a real cloud depot with a leather-bound PostgreSQL expense ledger. |
| **Azure (cheapest)** | ~$0.01 | ~$15/mo (Redis Cache Basic) | Good free tiers | 🚚 The Azure hub costs around one cent per session with generous free tiers that make it friendly for smaller courier fleets learning cloud dispatch. |

<details>
<summary>Detailed AWS breakdown</summary>

| Component | AWS Service | Cost | 🚚 Courier |
|-----------|-------------|------|-----------|
| LLM | Bedrock (Claude 3 Haiku) | ~$0.02/session | 🚚 The AWS depot's Haiku courier costs about two cents per lab session, making it the cheapest cloud barn for straightforward delivery errands. |
| Semantic cache | ElastiCache Redis (t3.micro) | ~$13/mo | 🚚 ElastiCache is the fast pickup locker shelf in the AWS depot, storing pre-written replies at about thirteen dollars a month on a micro-sized rack. |
| Cost tracking DB | RDS PostgreSQL (t3.micro) | ~$15/mo | 🚚 RDS is the cloud leather-bound expense ledger that logs every delivery's tokens and cost at around fifteen dollars a month. |
| API server | ECS Fargate (0.5 vCPU) | ~$15/mo | 🚚 The Fargate gateway hosts the switchboard dispatch desk in the cloud for about fifteen dollars a month with no server to maintain yourself. |
| Logs | CloudWatch | $0 (free tier) | 🚚 CloudWatch is the free observability dashboard that records every delivery log and lets you replay any courier's delivery journey without paying a monitoring bill. |

</details>

<details>
<summary>Detailed Azure breakdown</summary>

| Component | Azure Service | Cost | 🚚 Courier |
|-----------|---------------|------|-----------|
| LLM | Azure OpenAI (GPT-4o mini) | ~$0.01/session | 🚚 The Azure hub's GPT-4o mini courier costs just one cent per session, offering a quick and affordable cloud barn for standard delivery tasks. |
| Semantic cache | Azure Cache for Redis (Basic C0) | ~$15/mo | 🚚 Azure's fast pickup locker shelf keeps pre-written replies ready for about fifteen dollars a month on the Basic C0 rack at the Azure hub. |
| Cost tracking DB | Azure Database for PostgreSQL (Burstable B1ms) | ~$13/mo | 🚚 Azure's leather-bound expense ledger runs on a burstable instance for thirteen dollars a month, logging every parcel unit delivered by hub couriers. |
| API server | Container Apps (free tier) | $0 | 🚚 The Azure gateway runs the dispatch desk for free on Container Apps, hosting the switchboard without adding a cent to the monthly bill. |
| Logs | Azure Monitor | $0 | 🚚 Azure Monitor acts as free observability dashboard, recording every delivery detail so you can trace any courier's route without incurring extra observability costs. |

</details>

---

## 🚚 The Courier Analogy — Understanding Phase 1 Gateway Metrics

| Metric | 🚚 Courier Analogy | What It Means for the Gateway | How It's Calculated |
|--------|-------------------|-------------------------------|---------------------|
| **Provider Routing** | Chooses which model road to use | Selects the right LLM backend (OpenAI, Azure, local) based on config | Config lookup → provider factory → route request to correct endpoint |
| **Semantic Cache** | Remembers recent deliveries for speed | Skips the LLM call if a similar question was already answered | Embed query → cosine similarity vs cache → hit if similarity > threshold |
| **Rate Limiting** | Limits queue overload at the gate | Prevents exhausting shared LLM quotas under burst traffic | Token-bucket or fixed-window counter → reject/queue if limit exceeded |
| **Embeddings** | Prepares location vectors for smart lookup | Converts text to vectors for cache matching or downstream retrieval | Call embedding model → return float[] of dimension 384–1536 |
| **Latency** | How quickly the courier completes a round trip | End-to-end response time including provider + cache overhead | `time_end − time_start` on the full request lifecycle (ms) |
| **Health** | Checks the courier is alive and ready for work | Confirms all gateway dependencies (LLM provider, cache, DB) are reachable | `GET /health` → poll each dependency → return aggregate status |

---

## Lab 1: First Request Through the Gateway

> 🏢 **Business Context:** A platform team needs a unified API endpoint for multiple LLM providers. Instead of each team integrating directly with AWS Bedrock, Azure OpenAI, and Ollama, they want a single endpoint that handles provider abstraction, so teams can switch providers without code changes.

### Objective

Start the gateway with minimal configuration and send your first OpenAI-compatible request.

### Steps

```bash
# 1. Install dependencies
cd repos/ai-gateway
poetry install

# 2. Configure
cp .env.example .env
# Defaults work: CLOUD_PROVIDER=local

# 3. Ensure Ollama is running
ollama pull llama3.2
ollama pull nomic-embed-text

# 4. Start the gateway
poetry run start
```

### Test

```bash
# Send a chat completion request
curl -X POST http://localhost:8100/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "system", "content": "You are a helpful assistant. Be concise."},
      {"role": "user", "content": "What is the capital of the Netherlands?"}
    ],
    "temperature": 0.3
  }' | jq
```

### Expected Result

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "model": "ollama/llama3.2",
  "choices": [
    {
      "message": {
        "role": "assistant",
        "content": "The capital of the Netherlands is Amsterdam."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 25,
    "completion_tokens": 10,
    "total_tokens": 35
  },
  "cache_hit": false,
  "gateway_latency_ms": 1500
}
```

### Verify

- [ ] Response is in OpenAI format (has `choices`, `usage`, `model`)
- [ ] `model` starts with `ollama/`
- [ ] `cache_hit` is `false` (first request)
- [ ] `gateway_latency_ms` is present
- [ ] Swagger UI at http://localhost:8100/docs loads

### 🧠 Certification Question

**Q: What AWS service provides a similar API gateway pattern for routing requests to multiple backend services?**
A: Amazon API Gateway — supports routing, throttling, and authentication for multiple backend integrations, similar to our LLM gateway pattern.

### What you learned

The gateway exposes an OpenAI-compatible API regardless of the underlying provider. Responses include `cache_hit` and `gateway_latency_ms` — gateway-specific metadata that doesn't exist in raw LLM calls.

**✅ Skill unlocked:** You can send requests through the gateway and interpret gateway-specific response fields.

---

## Lab 2: Semantic Cache in Action

> 🏢 **Business Context:** The engineering team noticed that support chatbot users often ask the same questions. The LLM gateway should cache responses so that repeated or similar questions return instantly, reducing latency from 2 seconds to <10ms and cutting LLM costs by 20-30%.

### Objective

Demonstrate exact-match and semantic cache hits.

### Steps

```bash
# 1. Send a request (cache MISS)
curl -s http://localhost:8100/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "What is machine learning?"}]
  }' | jq '{cache_hit, gateway_latency_ms}'
# → cache_hit: false, gateway_latency_ms: ~1500

# 2. Send IDENTICAL request (cache HIT — exact match)
curl -s http://localhost:8100/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "What is machine learning?"}]
  }' | jq '{cache_hit, gateway_latency_ms}'
# → cache_hit: true, gateway_latency_ms: ~5

# 3. Send SIMILAR request (cache HIT — semantic match)
curl -s http://localhost:8100/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Explain machine learning to me"}]
  }' | jq '{cache_hit, gateway_latency_ms}'
# → cache_hit: true (if similarity > 0.92), gateway_latency_ms: ~10

# 4. Send DIFFERENT request (cache MISS)
curl -s http://localhost:8100/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "What is quantum computing?"}]
  }' | jq '{cache_hit, gateway_latency_ms}'
# → cache_hit: false, gateway_latency_ms: ~1500

# 5. Bypass cache
curl -s http://localhost:8100/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "What is machine learning?"}],
    "bypass_cache": true
  }' | jq '{cache_hit, gateway_latency_ms}'
# → cache_hit: false (cache bypassed)
```

### Expected Results

| Request | Cache Hit | Latency | 🚚 Courier |
|---------|-----------|---------|-----------|
| First "What is machine learning?" | ❌ | ~1500ms | 🚚 The first shipping manifest about machine learning has no match in the pickup locker, so a courier makes the full 1500ms round trip to the provider depot. |
| Identical repeat | ✅ (exact) | ~5ms | 🚚 The pickup locker finds an exact address match and hands back the cached reply in 5ms, skipping the delivery entirely for a 300× speed-up. |
| "Explain machine learning to me" | ✅ (semantic) | ~10ms | 🚚 A paraphrased shipping manifest matches the GPS-coordinate warehouse entry closely enough to trigger a semantic cache hit in about 10ms. |
| "What is quantum computing?" | ❌ | ~1500ms | 🚚 Quantum computing has never been delivered before, so the pickup locker is empty and a courier must make the full 1500ms round trip to fetch the answer. |
| With `bypass_cache: true` | ❌ (bypassed) | ~1500ms | 🚚 The bypass flag tells the dispatch desk to ignore the pickup locker entirely, forcing a fresh delivery even when a cached reply is already on the shelf. |

### Verify

- [ ] Exact match cache hit returns in <10ms
- [ ] Semantic match works for paraphrased questions
- [ ] `bypass_cache` forces a fresh LLM call
- [ ] Cache miss latency is 100-400× slower than cache hit

### 🧠 Certification Question

**Q: What is the difference between ElastiCache Redis and ElastiCache Memcached, and which would you choose for a semantic cache?**
A: Redis — supports complex data types (strings, hashes, lists), persistence (AOF), and TTL. Memcached is simpler (key-value only, no persistence). For semantic cache, Redis is the clear choice because we need to store structured data (embeddings + responses) with TTL expiry.

### What you learned

Semantic cache saves money and latency by matching paraphrased questions to cached answers. Exact match is instant (~5ms); semantic match embeds then compares (~10ms). Both are 100–400× faster than a fresh LLM call.

**✅ Skill unlocked:** You can demonstrate cache hits, explain the similarity threshold, and bypass cache when needed.

---

## Lab 3: Rate Limiting

> 🏢 **Business Context:** The API gateway is exposed to internal teams via API keys. Without rate limiting, a misconfigured client could exhaust the AWS Bedrock quota and block other teams. The platform team needs per-key rate limiting with clear 429 responses.

### Objective

Test the rate limiter by exceeding the configured limit.

### Steps

```bash
# 1. Set a low rate limit for testing
# Edit .env: RATE_LIMIT_REQUESTS_PER_MINUTE=5
# Restart: poetry run start

# 2. Send 7 rapid requests
for i in $(seq 1 7); do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST http://localhost:8100/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{"messages":[{"role":"user","content":"Count to 3"}]}')
  echo "Request $i: HTTP $STATUS"
  sleep 0.5
done
```

### Expected Results

```
Request 1: HTTP 200
Request 2: HTTP 200
Request 3: HTTP 200
Request 4: HTTP 200
Request 5: HTTP 200
Request 6: HTTP 429
Request 7: HTTP 429
```

### Check the 429 Response

```bash
curl -v http://localhost:8100/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"test"}]}' 2>&1 | grep -E "HTTP|Retry-After|rate_limit"
```

### Verify

- [ ] First 5 requests return 200
- [ ] Request 6+ returns 429
- [ ] 429 response includes `error.type: "rate_limit_error"`
- [ ] After 60 seconds, requests are allowed again

### 🧠 Certification Question

**Q: How does AWS API Gateway handle throttling, and how does it compare to our implementation?**
A: AWS API Gateway uses a token bucket algorithm with configurable steady-state rate and burst capacity. Our gateway uses a simpler fixed-window counter. AWS API Gateway returns `429 Too Many Requests` with the same pattern. For production, AWS API Gateway can be placed in front of our gateway for additional throttling.

### What you learned

Rate limiting protects shared LLM quotas. The 429 response with `rate_limit_error` follows the industry standard. After the window resets, requests flow again.

**✅ Skill unlocked:** You can configure, test, and verify rate-limit behaviour including recovery.

---

## Lab 4: Embeddings Endpoint

> 🏢 **Business Context:** The RAG chatbot (Phase 1) needs text embeddings for document search. Instead of each service calling Ollama/Bedrock directly, the gateway provides a unified embedding endpoint with the same caching and rate limiting.

### Objective

Generate embeddings through the gateway and verify the response format.

### Steps

```bash
# 1. Generate an embedding
curl -s http://localhost:8100/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{
    "input": "Machine learning is a subset of artificial intelligence."
  }' | jq '{model, "dimensions": (.data[0].embedding | length), "first_5": (.data[0].embedding[:5])}'

# 2. Generate multiple embeddings
curl -s http://localhost:8100/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{
    "input": ["Hello world", "Machine learning", "Cloud computing"]
  }' | jq '.data | length'
# → 3

# 3. Check the models endpoint
curl -s http://localhost:8100/v1/models | jq '.data[] | select(.model_type == "embedding")'
```

### Expected Results

```json
{
  "model": "ollama/nomic-embed-text",
  "dimensions": 768,
  "first_5": [0.0234, -0.0891, 0.0156, -0.0432, 0.0671]
}
```

### Verify

- [ ] Embedding dimensions are 768 (nomic-embed-text)
- [ ] Multiple inputs return multiple embedding objects
- [ ] Response matches OpenAI embedding format
- [ ] Models endpoint lists the embedding model

### 🧠 Certification Question

**Q: What AWS service provides text embeddings, and how do embedding dimensions affect storage costs?**
A: Amazon Bedrock with Titan Embed V2 provides 1024-dim embeddings. Dimensions directly impact storage: 768 floats × 4 bytes = 3KB per vector. At 1M documents, that's ~3GB for 768-dim vs ~4GB for 1024-dim. Choose the smallest dimension that maintains retrieval quality.

### What you learned

Embeddings are the bridge between text and vector search. The gateway unifies embedding access the same way it unifies chat — one endpoint, any provider.

**✅ Skill unlocked:** You can generate embeddings, check dimensions, and explain storage cost implications.

---

## Summary

| Lab | Component | Key Learning | 🚚 Courier |
|-----|-----------|-------------|-----------|
| 1 | LLM Router | OpenAI-compatible API, provider abstraction | 🚚 The dispatch desk accepts any shipping manifest in OpenAI format and routes it to whichever provider depot the config points at, hiding the swap from clients. |
| 2 | Semantic Cache | Exact + semantic matching, latency reduction | 🚚 The pickup locker shelf saves repeated deliveries by returning pre-written replies for exact or GPS-coordinate-close queries, cutting latency from 1500ms to 5ms. |
| 3 | Rate Limiter | Fixed-window counters, 429 handling | 🚚 The depot gate counts each courier's knocks per minute and slams shut with a 429 quota-used-up error when the fixed-window daily dispatch quota is exceeded. |
| 4 | Embeddings | Embedding endpoint, vector dimensions | 🚚 The GPS-coordinate writer converts text into 768-dimensional float vectors so the pickup locker and downstream retrieval can compare delivery addresses. |

## Phase 1 Labs — Skills Checklist

| # | Skill | Lab | Can you explain it? | 🚚 Courier |
|---|---|---|---|---|
| 1 | OpenAI-compatible gateway request flow | Lab 1 | [ ] Yes | 🚚 The gateway's front door accepts OpenAI-format shipping manifests and routes them to any courier regardless of which provider depot the courier actually works for. |
| 2 | Exact and semantic cache behavior | Lab 2 | [ ] Yes | 🚚 The pickup locker returns pre-written replies for identical or GPS-coordinate-close queries, saving the delivery and shrinking the expense ledger. |
| 3 | Rate-limit enforcement and error handling | Lab 3 | [ ] Yes | 🚚 The depot gate enforces a daily dispatch quota per API key, returning a 429 quota-used-up error when a courier exceeds their per-minute allowance. |
| 4 | Embeddings API shape and dimensions | Lab 4 | [ ] Yes | 🚚 The GPS-coordinate writer endpoint outputs a float array of 768 or 1024 values used by the pickup locker to judge address similarity between shipping manifests. |

**Next:** [Phase 2 Labs](hands-on-labs-phase-2.md) — Cost tracking, health checks, observability, multi-provider testing.
