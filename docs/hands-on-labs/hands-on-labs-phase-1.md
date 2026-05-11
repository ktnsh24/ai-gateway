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
| --- | --- | --- | --- | --- |
| **Local (Ollama + Redis + PostgreSQL)** | $0 | $0 | Learning, experimenting | 🚚 Running the whole service locally costs nothing, letting you practise every dispatch workflow without logging a single cent in the expense ledger. |
| **AWS (cheapest)** | ~$0.03 | ~$35/mo (ElastiCache + RDS) | Proving cloud skills | 🚚 The AWS depot charges about three cents per lab session, proving you can run a real cloud depot with a leather-bound PostgreSQL expense ledger. |
| **Azure (cheapest)** | ~$0.01 | ~$15/mo (Redis Cache Basic) | Good free tiers | 🚚 The Azure hub costs around one cent per session with generous free tiers that make it friendly for smaller courier fleets learning cloud dispatch. |

### Detailed AWS breakdown

| Component | AWS Service | Cost | 🚚 Courier |
| --- | --- | --- | --- |
| LLM | Bedrock (Claude 3 Haiku) | ~$0.02/session | 🚚 The AWS depot's Haiku courier costs about two cents per lab session, making it the cheapest cloud barn for straightforward delivery errands. |
| Semantic cache | ElastiCache Redis (t3.micro) | ~$13/mo | 🚚 ElastiCache is the fast pickup locker shelf in the AWS depot, storing pre-written replies at about thirteen dollars a month on a micro-sized rack. |
| Cost tracking DB | RDS PostgreSQL (t3.micro) | ~$15/mo | 🚚 RDS is the cloud leather-bound expense ledger that logs every delivery's tokens and cost at around fifteen dollars a month. |
| API server | ECS Fargate (0.5 vCPU) | ~$15/mo | 🚚 The Fargate gateway hosts the switchboard dispatch desk in the cloud for about fifteen dollars a month with no server to maintain yourself. |
| Logs | CloudWatch | $0 (free tier) | 🚚 CloudWatch is the free observability dashboard that records every delivery log and lets you replay any courier's delivery journey without paying a monitoring bill. |

### Detailed Azure breakdown

| Component | Azure Service | Cost | 🚚 Courier |
| --- | --- | --- | --- |
| LLM | Azure OpenAI (GPT-4o mini) | ~$0.01/session | 🚚 The Azure hub's GPT-4o mini courier costs just one cent per session, offering a quick and affordable cloud barn for standard delivery tasks. |
| Semantic cache | Azure Cache for Redis (Basic C0) | ~$15/mo | 🚚 Azure's fast pickup locker shelf keeps pre-written replies ready for about fifteen dollars a month on the Basic C0 rack at the Azure hub. |
| Cost tracking DB | Azure Database for PostgreSQL (Burstable B1ms) | ~$13/mo | 🚚 Azure's leather-bound expense ledger runs on a burstable instance for thirteen dollars a month, logging every parcel unit delivered by hub couriers. |
| API server | Container Apps (free tier) | $0 | 🚚 The Azure gateway runs the dispatch desk for free on Container Apps, hosting the switchboard without adding a cent to the monthly bill. |
| Logs | Azure Monitor | $0 | 🚚 Azure Monitor acts as free observability dashboard, recording every delivery detail so you can trace any courier's route without incurring extra observability costs. |

---

## 🚚 The Courier Analogy — Understanding Phase 1 Gateway Metrics

| Metric | 🚚 Courier Analogy | What It Means for the Gateway | How It's Calculated |
| --- | --- | --- | --- |
| **Provider Routing** | Chooses which model road to use | Selects the right LLM backend (OpenAI, Azure, local) based on config | Config lookup → provider factory → route request to correct endpoint |
| **Semantic Cache** | Remembers recent deliveries for speed | Skips the LLM call if a similar question was already answered | Embed query → cosine similarity vs cache → hit if similarity > threshold |
| **Rate Limiting** | Limits queue overload at the gate | Prevents exhausting shared LLM quotas under burst traffic | Token-bucket or fixed-window counter → reject/queue if limit exceeded |
| **Embeddings** | Prepares location vectors for smart lookup | Converts text to vectors for cache matching or downstream retrieval | Call embedding model → return float[] of dimension 384–1536 |
| **Latency** | How quickly the courier completes a round trip | End-to-end response time including provider + cache overhead | `time_end − time_start` on the full request lifecycle (ms) |
| **Health** | Checks the courier is alive and ready for work | Confirms all gateway dependencies (LLM provider, cache, DB) are reachable | `GET /health` → poll each dependency → return aggregate status |

---

## Lab 1: First Request Through the Gateway

> 🏢 **Business Context:** A platform team needs a unified API endpoint for multiple LLM providers. Instead of each team integrating directly with AWS Bedrock, Azure OpenAI, and Ollama, they want a single endpoint that handles provider abstraction, so teams can switch providers without code changes.

### Lab 1 Objective

Start from an intentional failure, detect it quickly, apply one minimal fix, and confirm recovery through measurable signals.

### Fail-First Setup (Intentional Break)

Before starting the gateway, intentionally misconfigure the model so startup or request flow fails.

```bash
# 1. Install dependencies
cd repos/ai-gateway
poetry install

# 2. Configure
cp .env.example .env

# 3. INTENTIONAL BREAK (example)
# Set a model name that does not exist locally
# MODEL_NAME=llama3.2-does-not-exist

# 4. Start the gateway
poetry run start
```

If startup succeeds despite the bad model, keep the bad config and trigger failure via the first request in Swagger UI.

### Failure Signals (What interviewers care about)

Noisy signals:

- Request fails with provider/model error
- Elevated response latency due to retries/fallback attempts
- Health check shows degraded dependency state

Silent signals:

- Gateway responds but answer quality degrades
- Incorrect fallback provider is used without explicit visibility
- Latency trend worsens before hard failures appear

### Lab 1 Setup Steps

```bash
# Ensure Ollama base models are available
ollama pull llama3.2
ollama pull nomic-embed-text
```

### Run in Swagger UI (Failure Run)

Open Swagger UI → `POST /v1/chat/completions` → Try it out → Execute with:

```json
{
  "messages": [
    {
      "role": "system",
      "content": "You are a helpful assistant. Be concise."
    },
    {
      "role": "user",
      "content": "What is the capital of the Netherlands?"
    }
  ],
  "temperature": 0.3
}
```

Record the failing behavior (error body or degraded response quality/latency).

### Minimal Fix Path

Apply one small fix only:

1. Restore valid model configuration in `.env`
2. Restart gateway: `poetry run start`
3. Re-run the exact same Swagger request

### Lab 1 Expected Result

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

### Before/After Recovery Metrics

| Metric | Before fix | After fix | Target |
| --- | --- | --- | --- |
| Request success rate | < 100% | 100% | 100% in local lab run |
| Gateway latency (`gateway_latency_ms`) | unstable / elevated | stable | p95 within your local baseline |
| Correctness (sample question) | inconsistent / failed | correct answer | Correct factual answer |
| Health endpoint status | degraded/partial | healthy | Healthy dependencies |

### Lab 1 Verification Checklist

- [ ] Swagger UI at `http://localhost:8100/docs` loads
- [ ] Failure was reproducible before the fix
- [ ] Response is in OpenAI format (`choices`, `usage`, `model`)
- [ ] `model` starts with `ollama/`
- [ ] `cache_hit` is `false` on first successful request
- [ ] `gateway_latency_ms` is present and improved vs failure run

### Interview Debrief (2-minute answer practice)

Use this exact structure when asked in interviews:

1. **Blast radius:** Which user paths failed or degraded?
2. **Detection:** Which signal caught it first (error, latency, health, quality)?
3. **Mitigation:** What single change restored service?
4. **Prevention:** What guardrail prevents recurrence (config validation, startup checks, health gates)?
5. **Tradeoff:** What did you optimize for (speed to recover vs deeper refactor)?

### 🧠 Lab 1 Certification Question

**Q: What AWS service provides a similar API gateway pattern for routing requests to multiple backend services?**
A: Amazon API Gateway — supports routing, throttling, and authentication for multiple backend integrations, similar to our LLM gateway pattern.

### Lab 1 What You Learned

In interview terms, you demonstrated system judgment: you triggered a realistic failure, separated noisy vs silent signals, applied a minimal fix, and proved recovery with measurable before/after behavior.

**✅ Skill unlocked:** You can explain not only how the gateway works, but how it fails, how you detect degradation early, and how you recover safely.

---

## Lab 2: Semantic Cache in Action

> 🏢 **Business Context:** The engineering team noticed that support chatbot users often ask the same questions. The LLM gateway should cache responses so that repeated or similar questions return instantly, reducing latency from 2 seconds to <10ms and cutting LLM costs by 20-30%.

### Lab 2 Objective

Start from a silent cache failure, detect the staleness, apply one fix, and confirm recovery with latency numbers.

### Lab 2 Fail-First Setup (Intentional Break)

Set the semantic similarity threshold too high so semantic matches silently fall back to full LLM calls — cache looks active but never fires for paraphrased questions.

```bash
# In .env, set threshold to near-exact match (breaks semantic hits)
# CACHE_SIMILARITY_THRESHOLD=0.99
# Restart: poetry run start
```

### Lab 2 Failure Signals

Noisy signals:

- Cache miss rate stays at 100% regardless of repeated similar questions
- `gateway_latency_ms` stays at ~1500ms even for paraphrased questions

Silent signals:

- `cache_hit: false` in every response but gateway looks healthy
- LLM cost per session is 3-5× higher than expected with no error visible
- `GET /api/metrics` shows cache hit rate at 0% — business team notices cost spike before you do

### Lab 2 Run in Swagger UI (Failure Run)

Open Swagger UI → `POST /v1/chat/completions` → Try it out → Execute:

**Request 1 — first question (cache miss expected):**

```json
{
  "messages": [{"role": "user", "content": "What is machine learning?"}]
}
```

Record: `cache_hit` and `gateway_latency_ms`.

**Request 2 — identical question (should be exact cache hit):**

Same body. Record: `cache_hit` and `gateway_latency_ms`.

**Request 3 — paraphrased question (semantic hit — broken with threshold 0.99):**

```json
{
  "messages": [{"role": "user", "content": "Explain machine learning to me"}]
}
```

Record: `cache_hit`. With threshold 0.99, this returns `false` (failure).

**Request 4 — bypass cache explicitly:**

```json
{
  "messages": [{"role": "user", "content": "What is machine learning?"}],
  "bypass_cache": true
}
```

### Lab 2 Minimal Fix Path

Apply one small fix only:

1. Lower threshold to a workable value: `CACHE_SIMILARITY_THRESHOLD=0.92`
2. Restart: `poetry run start`
3. Repeat requests 1–3 above and confirm request 3 now returns `cache_hit: true`

### Lab 2 Before/After Recovery Metrics

| Metric | Before fix (threshold 0.99) | After fix (threshold 0.92) | Target |
| --- | --- | --- | --- |
| Exact match cache hit | ✅ (unchanged) | ✅ (unchanged) | `cache_hit: true`, <10ms |
| Semantic match cache hit | ❌ `cache_hit: false` | ✅ `cache_hit: true` | <15ms |
| Latency on paraphrase | ~1500ms | ~10ms | 100× improvement |
| Cache hit rate (metrics endpoint) | 0% | 30–60% typical | Visible in `/api/metrics` |

### Lab 2 Interview Debrief (2-minute answer practice)

1. **Blast radius:** Users paying for LLM calls on every repeated question; cost is 3–5× expected.
2. **Detection:** Cache hit rate at 0% in `/api/metrics` — cost anomaly caught it before errors appeared.
3. **Mitigation:** Lowered similarity threshold from 0.99 to 0.92 — one config change.
4. **Prevention:** Set threshold alert: if cache hit rate < 10% after 100 requests, flag for review.
5. **Tradeoff:** Lower threshold catches more paraphrases but risks serving stale answers for semantically close but distinct questions. 0.92 is the practical sweet spot for FAQ-style workloads.

### 🧠 Lab 2 Certification Question

**Q: What is the difference between ElastiCache Redis and ElastiCache Memcached, and which would you choose for a semantic cache?**
A: Redis — supports complex data types (strings, hashes, lists), persistence (AOF), and TTL. Memcached is simpler (key-value only, no persistence). For semantic cache, Redis is the clear choice because we need to store structured data (embeddings + responses) with TTL expiry.

### Lab 2 What You Learned

In interview terms: a misconfigured similarity threshold is a silent failure — the system looks healthy but leaks money. You caught it through the metrics endpoint, not through errors, and fixed it with a single config change.

**✅ Skill unlocked:** You can explain not only how semantic cache works, but how it fails silently and how you detect and fix threshold misconfiguration.

---

## Lab 3: Rate Limiting

> 🏢 **Business Context:** The API gateway is exposed to internal teams via API keys. Without rate limiting, a misconfigured client could exhaust the AWS Bedrock quota and block other teams. The platform team needs per-key rate limiting with clear 429 responses.

### Lab 3 Objective

Start with rate limiting disabled, observe quota exhaustion, then enable it and confirm the 429 boundary with observable before/after metrics.

### Lab 3 Fail-First Setup (Intentional Break)

Disable rate limiting entirely so no 429 is returned even under rapid fire:

```bash
# In .env, disable rate limiting
# RATE_LIMIT_ENABLED=false
# RATE_LIMIT_REQUESTS_PER_MINUTE=10000
# Restart: poetry run start
```

Now send 10 rapid requests in Swagger UI — all return 200. This is the broken production state that would exhaust Bedrock quotas.

### Lab 3 Failure Signals

Noisy signals:

- External provider quota error appears (e.g. Bedrock ThrottlingException) after burst — too late
- Other teams start seeing 503/429 from the *provider*, not the gateway

Silent signals:

- Gateway metrics show 0 rate-limit events but Bedrock cost spikes
- A single misconfigured client consumes the shared quota before anyone detects it
- No 429 in gateway logs — problem only visible in cloud billing or provider console

### Lab 3 Run in Swagger UI (Failure Run — No Limit)

Open Swagger UI → `POST /v1/chat/completions` → Try it out.

Send 6 rapid requests with this body:

```json
{
  "messages": [{"role": "user", "content": "Count to 3"}]
}
```

Record: all 6 return 200 — no protection in place.

### Lab 3 Minimal Fix Path

Apply one fix only:

1. Set: `RATE_LIMIT_ENABLED=true` and `RATE_LIMIT_REQUESTS_PER_MINUTE=5`
2. Restart: `poetry run start`
3. Send 7 requests in Swagger UI, one at a time

### Lab 3 Run in Swagger UI (Recovery Run)

Send the same body 7 times. Record HTTP status for each:

```json
{
  "messages": [{"role": "user", "content": "Count to 3"}]
}
```

Expected pattern:

| Request | Expected status |
| --- | --- |
| 1–5 | 200 OK |
| 6+ | 429 Too Many Requests |

On the 429 response, note the `error.type` field in the response body.

### Lab 3 Before/After Recovery Metrics

| Metric | Before fix (no limit) | After fix (limit = 5/min) | Target |
| --- | --- | --- | --- |
| Requests allowed per minute | Unlimited ❌ | 5 ✓ | Hard cap enforced |
| 429 rate-limit events in logs | 0 | Visible at request 6+ | Gateway owns the error |
| Provider quota exhaustion risk | High | Mitigated | Gateway absorbs burst |
| Error type in response | None | `rate_limit_error` ✓ | Client-readable |

### Lab 3 Interview Debrief (2-minute answer practice)

1. **Blast radius:** One misconfigured client exhausts provider quota for all teams before gateway returns any error.
2. **Detection:** Silent — only visible in provider billing or a ThrottlingException from Bedrock, not in gateway logs.
3. **Mitigation:** Enable rate limit flag and set per-minute cap — one config change, immediate effect.
4. **Prevention:** Default-on rate limiting; require explicit override to disable; alert on 0 rate-limit events during load tests.
5. **Tradeoff:** Fixed-window counter is simple and predictable but can allow 2× burst at window boundaries. Token bucket is smoother but more complex. For learning workloads, fixed-window is fine.

### 🧠 Lab 3 Certification Question

**Q: How does AWS API Gateway handle throttling, and how does it compare to our implementation?**
A: AWS API Gateway uses a token bucket algorithm with configurable steady-state rate and burst capacity. Our gateway uses a simpler fixed-window counter. AWS API Gateway returns `429 Too Many Requests` with the same pattern. For production, AWS API Gateway can be placed in front of our gateway for additional throttling.

### Lab 3 What You Learned

In interview terms: rate-limit absence is a silent failure until an external quota breaks. You caught it by simulating the burst, applied a single config fix, and proved the boundary with observable 429 responses.

**✅ Skill unlocked:** You can explain how rate limiting protects shared quotas, what breaks silently without it, and how a token-bucket vs fixed-window tradeoff affects burst behavior.

---

## Lab 4: Embeddings Endpoint

> 🏢 **Business Context:** The RAG chatbot (Phase 1) needs text embeddings for document search. Instead of each service calling Ollama/Bedrock directly, the gateway provides a unified embedding endpoint with the same caching and rate limiting.

### Lab 4 Objective

Start from an embedding model misconfiguration that returns wrong dimensions, detect it through response shape, apply a single fix, and confirm recovery with a dimensions check.

### Lab 4 Fail-First Setup (Intentional Break)

Change the embedding model to a non-existent or wrong model name so the gateway either errors or returns unexpected dimensions:

```bash
# In .env, set a wrong embedding model
# EMBEDDING_MODEL=nomic-embed-text-wrong
# Restart: poetry run start
```

### Lab 4 Failure Signals

Noisy signals:

- Embedding request returns 500 or provider error
- Downstream RAG retrieval returns no results (vectors from wrong model are incompatible with stored index)

Silent signals:

- Embedding returns a response but dimensions are wrong (e.g. 384 instead of 768)
- RAG search still runs but retrieval quality drops silently — no errors, just wrong answers
- `GET /v1/models` shows the wrong model name registered — catch it before queries run

### Lab 4 Run in Swagger UI (Failure Run)

Open Swagger UI → `POST /v1/embeddings` → Try it out → Execute:

```json
{
  "input": "Machine learning is a subset of artificial intelligence."
}
```

Record: error response OR note the `dimensions` value in the response. If dimensions ≠ 768, you have a silent mismatch.

Also check: Swagger UI → `GET /v1/models` → Execute. Record which embedding model is listed.

### Lab 4 Minimal Fix Path

Apply one fix only:

1. Restore correct model: `EMBEDDING_MODEL=nomic-embed-text`
2. Restart: `poetry run start`
3. Re-run the Swagger embedding request

### Lab 4 Run in Swagger UI (Recovery Run)

`POST /v1/embeddings` with same body. Then `GET /v1/models`.

Expected recovery response:

```json
{
  "model": "ollama/nomic-embed-text",
  "data": [
    {
      "embedding": [0.0234, -0.0891, 0.0156, "...(768 total)"],
      "index": 0
    }
  ]
}
```

### Lab 4 Before/After Recovery Metrics

| Metric | Before fix (wrong model) | After fix (correct model) | Target |
| --- | --- | --- | --- |
| Embedding dimensions | Wrong (e.g. 384) or error | 768 ✓ | Matches index schema |
| RAG retrieval quality | Silent degradation or 0 results | Correct results ✓ | Recall measurable |
| Model in `/v1/models` response | Wrong name ❌ | `nomic-embed-text` ✓ | Config matches registry |
| Gateway error rate | 500 or silent wrong dims | 0 errors ✓ | Clean response |

### Lab 4 Interview Debrief (2-minute answer practice)

1. **Blast radius:** All downstream RAG retrieval silently returns wrong or empty results — no 500, just bad answers.
2. **Detection:** Check `dimensions` in embedding response; check `/v1/models` to verify model registry matches expected config.
3. **Mitigation:** Fix model name in config — one change, immediate fix on restart.
4. **Prevention:** Startup assertion: if embedding dimensions ≠ expected, refuse to start. Alert on retrieval recall drop < threshold.
5. **Tradeoff:** 768-dim (nomic) vs 1024-dim (Titan v2). Larger dims = better recall, higher storage cost. At 1M docs: 768-dim ≈ 3GB, 1024-dim ≈ 4GB. Choose smallest that hits your recall target.

### 🧠 Lab 4 Certification Question

**Q: What AWS service provides text embeddings, and how do embedding dimensions affect storage costs?**
A: Amazon Bedrock with Titan Embed V2 provides 1024-dim embeddings. Dimensions directly impact storage: 768 floats × 4 bytes = 3KB per vector. At 1M documents, that's ~3GB for 768-dim vs ~4GB for 1024-dim. Choose the smallest dimension that maintains retrieval quality.

### Lab 4 What You Learned

In interview terms: wrong embedding dimensions are a silent failure — the system runs but downstream retrieval degrades invisibly. You detected it through response shape inspection, fixed it with one config change, and proved recovery through dimensions match and model registry check.

**✅ Skill unlocked:** You can explain embedding dimensions, detect model mismatches silently degrading retrieval quality, and articulate the storage cost tradeoff between dimension sizes.

---

## Summary

| Lab | Component | Key Learning | 🚚 Courier |
| --- | --- | --- | --- |
| 1 | LLM Router | OpenAI-compatible API, provider abstraction | 🚚 The dispatch desk accepts any shipping manifest in OpenAI format and routes it to whichever provider depot the config points at, hiding the swap from clients. |
| 2 | Semantic Cache | Exact + semantic matching, latency reduction | 🚚 The pickup locker shelf saves repeated deliveries by returning pre-written replies for exact or GPS-coordinate-close queries, cutting latency from 1500ms to 5ms. |
| 3 | Rate Limiter | Fixed-window counters, 429 handling | 🚚 The depot gate counts each courier's knocks per minute and slams shut with a 429 quota-used-up error when the fixed-window daily dispatch quota is exceeded. |
| 4 | Embeddings | Embedding endpoint, vector dimensions | 🚚 The GPS-coordinate writer converts text into 768-dimensional float vectors so the pickup locker and downstream retrieval can compare delivery addresses. |

## Phase 1 Labs — Skills Checklist

| # | Skill | Lab | Can you explain it? | 🚚 Courier |
| --- | --- | --- | --- | --- |
| 1 | OpenAI-compatible gateway request flow | Lab 1 | [ ] Yes | 🚚 The gateway's front door accepts OpenAI-format shipping manifests and routes them to any courier regardless of which provider depot the courier actually works for. |
| 2 | Exact and semantic cache behavior | Lab 2 | [ ] Yes | 🚚 The pickup locker returns pre-written replies for identical or GPS-coordinate-close queries, saving the delivery and shrinking the expense ledger. |
| 3 | Rate-limit enforcement and error handling | Lab 3 | [ ] Yes | 🚚 The depot gate enforces a daily dispatch quota per API key, returning a 429 quota-used-up error when a courier exceeds their per-minute allowance. |
| 4 | Embeddings API shape and dimensions | Lab 4 | [ ] Yes | 🚚 The GPS-coordinate writer endpoint outputs a float array of 768 or 1024 values used by the pickup locker to judge address similarity between shipping manifests. |

**Next:** [Phase 2 Labs](hands-on-labs-phase-2.md) — Cost tracking, health checks, observability, multi-provider testing.
