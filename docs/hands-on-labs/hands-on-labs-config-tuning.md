# Hands-on Labs — Config Tuning (Tier 1–5)

> **Why these labs exist:** This is the AI-engineering interview answer. When asked "how would you tune this gateway?" the answer is a guided tour of these sweeps + their trade-offs.
>
> **How to run:** Each lab changes ONE config in `.env`, runs the same 3 questions, records the metrics, and explains the trade-off.
>
> **🫏 Donkey lens:** Each lab ends with a donkey takeaway summarising the trade-off in plain language.

## Table of Contents
- [Setup — Common to all labs](#setup--common-to-all-labs)
- [Lab 1: Temperature Sweep](#lab-1-temperature-sweep)
- [Lab 2: System Prompt Sweep](#lab-2-system-prompt-sweep)
- [Lab 3: Model Swap](#lab-3-model-swap)
- [Lab 4: Max Tokens Sweep](#lab-4-max-tokens-sweep)
- [Lab 5: Semantic Cache TTL Sweep](#lab-5-semantic-cache-ttl-sweep)
- [Lab 6: Semantic Cache Similarity Threshold Sweep](#lab-6-semantic-cache-similarity-threshold-sweep)
- [Lab 7: Rate-Limit RPM Sweep](#lab-7-rate-limit-rpm-sweep)

---

## Setup — Common to all labs

1. Make sure the gateway is running: `poetry run uvicorn src.main:app --port 8100 --reload`
2. Make sure Redis + Postgres are up: `docker compose up -d redis postgres`
3. Have the 3 fixed test questions ready (POST `/v1/chat/completions`):
   - **Q1:** "Explain RAG in 2 sentences."
   - **Q2:** "Translate 'good morning' to Dutch."
   - **Q3:** "What is 17 × 23?"
4. Each lab takes ~5–10 min: change config → restart gateway → run questions → record table

---

## Lab 1: Temperature Sweep — "How creative should the donkey be?"

**Config:** `LLM_TEMPERATURE` (default: `0.3`; pass-through to provider)
**What it controls:** Sampling randomness on every routed LLM call.
**Hypothesis:** 0.0 = deterministic + cache-friendly (identical inputs → identical outputs); higher = more diverse answers, more hallucination.

### Setup
1. Set `LLM_TEMPERATURE=0.0` in `.env`
2. Run the same 3 questions (Q1–Q3)
3. Repeat for each value below

### Results table (fill in as you run)
| Value | Cache hit rate | Faithfulness | Latency (ms) | Cost (€) | Notes |
|---|---|---|---|---|---|
| 0.0 | ___ | ___ | ___ | ___ | ___ |
| 0.3 | ___ | ___ | ___ | ___ | ___ |
| 0.7 | ___ | ___ | ___ | ___ | ___ |

### What we learned
At a gateway, temperature also affects cacheability — non-deterministic outputs make exact-match caching useless. Pin temp=0 for high-volume identical queries.

### 🫏 Donkey takeaway
Cold donkey delivers the same parcel every time, easy to remember; warm donkey delivers variations and the warehouse can't reuse yesterday's delivery.

---

## Lab 2: System Prompt Sweep — "Strict vs lax delivery note"

**Config:** `SYSTEM_PROMPT` (default: minimal pass-through)
**What it controls:** Default system prompt the gateway prepends if the client doesn't supply one.
**Hypothesis:** A strict default ("be concise; refuse off-topic; cite sources") raises baseline quality across all clients.

### Setup
1. Set `SYSTEM_PROMPT` to the strict variant in `.env`
2. Run the same 3 questions (Q1–Q3) without supplying a client-side system prompt
3. Repeat for balanced and lax defaults

### Results table (fill in as you run)
| Value | Cache hit rate | Faithfulness | Latency (ms) | Cost (€) | Notes |
|---|---|---|---|---|---|
| strict | ___ | ___ | ___ | ___ | ___ |
| balanced | ___ | ___ | ___ | ___ | ___ |
| lax | ___ | ___ | ___ | ___ | ___ |

### What we learned
The gateway's default prompt sets the floor for every downstream app — invest here once and every client benefits.

### 🫏 Donkey takeaway
The stable manager hands every donkey a default delivery note; a strict default keeps the whole stable polite even when individual clients forget to add their own.

---

## Lab 3: Model Swap — "Which donkey is on duty?"

**Config:** `AWS_BEDROCK_MODEL_ID` / `AZURE_OPENAI_DEPLOYMENT` / `OLLAMA_MODEL` and `ROUTING_STRATEGY`
**What it controls:** Which provider/model the gateway routes to.
**Hypothesis:** Bigger model = better quality + higher cost; the gateway's routing strategy lets you mix.

### Setup
1. Set `ROUTING_STRATEGY=single`, `OLLAMA_MODEL=llama3.2:1b`
2. Run the same 3 questions (Q1–Q3)
3. Repeat for each model below; also try `ROUTING_STRATEGY=cost` to auto-pick cheapest provider

### Results table (fill in as you run)
| Value | Cache hit rate | Faithfulness | Latency (ms) | Cost (€) | Notes |
|---|---|---|---|---|---|
| llama3.2:1b (local) | ___ | ___ | ___ | ___ | ___ |
| llama3.2 (3B, local) | ___ | ___ | ___ | ___ | ___ |
| Bedrock Claude 3.5 Sonnet | ___ | ___ | ___ | ___ | ___ |
| Azure GPT-4o | ___ | ___ | ___ | ___ | ___ |
| ROUTING_STRATEGY=cost | ___ | ___ | ___ | ___ | ___ |

### What we learned
Use the gateway to A/B providers without touching client code — that is the gateway's whole reason to exist. Always include a local fallback to keep dev free.

### 🫏 Donkey takeaway
The stable manager chooses which donkey to send out; clients never know whether it was the pony, the workhorse, or the racehorse.

---

## Lab 4: Max Tokens Sweep — "Cargo capacity of the reply"

**Config:** `LLM_MAX_TOKENS` (default: `1024`; pass-through unless capped at gateway)
**What it controls:** Cap on response tokens per request.
**Hypothesis:** Too low = clients see truncated answers and complain; too high = a runaway client can burn the entire monthly budget on one request.

### Setup
1. Set `LLM_MAX_TOKENS=256` in `.env`
2. Run the same 3 questions (Q1–Q3) and note any truncations
3. Repeat for each value below

### Results table (fill in as you run)
| Value | Cache hit rate | Faithfulness | Latency (ms) | Cost (€) | Notes |
|---|---|---|---|---|---|
| 256 | ___ | ___ | ___ | ___ | ___ |
| 1024 | ___ | ___ | ___ | ___ | ___ |
| 4096 | ___ | ___ | ___ | ___ | ___ |

### What we learned
At the gateway, max_tokens is a budget guardrail more than a quality lever. Set a hard ceiling per API key tier — clients can request less but never more.

### 🫏 Donkey takeaway
The stable manager sets the maximum crate size the donkey is allowed to carry, no matter what the client asks for.

---

## Lab 5: Semantic Cache TTL Sweep — "How long is yesterday's delivery still valid?"

**Config:** `CACHE_TTL_SECONDS` (default: `3600`)
**What it controls:** Time-to-live for cached LLM responses in Redis.
**Hypothesis:** Short TTL = fresh answers, low hit rate; long TTL = stale answers risk for time-sensitive queries, big cost savings.

### Setup
1. Set `CACHE_TTL_SECONDS=60` in `.env` and `CACHE_ENABLED=true`
2. Run the same 3 questions (Q1–Q3) twice (second run should hit cache)
3. Repeat for each value below; also test a time-sensitive query like "what's today's date?"

### Results table (fill in as you run)
| Value | Cache hit rate | Faithfulness | Latency (ms) | Cost (€) | Notes |
|---|---|---|---|---|---|
| 60s (1 min) | ___ | ___ | ___ | ___ | ___ |
| 3600s (1 hr) | ___ | ___ | ___ | ___ | ___ |
| 86400s (1 day) | ___ | ___ | ___ | ___ | ___ |

### What we learned
TTL is a freshness/cost dial. For static knowledge (translations, definitions) push TTL high; for time-sensitive queries (prices, news) keep it short or bypass cache entirely.

### 🫏 Donkey takeaway
A delivery note that says "this answer is good for 1 hour" lets the warehouse skip the trip; saying "good for a day" saves more trips but risks delivering yesterday's news.

---

## Lab 6: Semantic Cache Similarity Threshold Sweep — "How close is close enough?"

**Config:** `CACHE_SIMILARITY_THRESHOLD` (default: `0.92`)
**What it controls:** Cosine similarity threshold for the semantic cache to consider two queries "the same".
**Hypothesis:** Low threshold = high hit rate + frequent wrong-cache hits; high threshold = safe but rare hits.

### Setup
1. Set `CACHE_SIMILARITY_THRESHOLD=0.80` in `.env`
2. Run Q1–Q3, then run paraphrases ("Describe RAG briefly", "Say good morning in Dutch", "Multiply 17 by 23")
3. Repeat for each value below

### Results table (fill in as you run)
| Value | Cache hit rate | Faithfulness | Latency (ms) | Cost (€) | Notes |
|---|---|---|---|---|---|
| 0.80 | ___ | ___ | ___ | ___ | ___ |
| 0.92 | ___ | ___ | ___ | ___ | ___ |
| 0.98 | ___ | ___ | ___ | ___ | ___ |

### What we learned
Below ~0.90, semantic cache starts returning answers to *similar but different* questions — a silent quality bug. Above ~0.95, the cache barely fires. Calibrate against a paraphrase eval set.

### 🫏 Donkey takeaway
A loose match means the warehouse hands over yesterday's parcel because the address looked similar; a tight match keeps the parcels sorted but the warehouse rarely reuses any.

---

## Lab 7: Rate-Limit RPM Sweep — "How fast can a client knock at the stable door?"

**Config:** `RATE_LIMIT_REQUESTS_PER_MINUTE` (default: `60`)
**What it controls:** Per-API-key requests-per-minute ceiling.
**Hypothesis:** Low RPM = fair sharing + slow clients; high RPM = one client can starve others.

### Setup
1. Set `RATE_LIMIT_ENABLED=true` and `RATE_LIMIT_REQUESTS_PER_MINUTE=10` in `.env`
2. Run the 3 questions in a tight loop (e.g., `for i in {1..30}; do curl ... ; done`) and count 429s
3. Repeat for each value below

### Results table (fill in as you run)
| Value | 429 rate | Faithfulness | Latency p95 (ms) | Cost (€) | Notes |
|---|---|---|---|---|---|
| 10 RPM | ___ | ___ | ___ | ___ | ___ |
| 60 RPM | ___ | ___ | ___ | ___ | ___ |
| 600 RPM | ___ | ___ | ___ | ___ | ___ |

### What we learned
Rate limits protect the budget more than the latency. Tier them per API key (free / paid / internal) and always return useful headers (`X-RateLimit-Remaining`, `Retry-After`).

### 🫏 Donkey takeaway
The stable's front door only lets each client knock so many times per minute; otherwise one shouty client ties up every donkey and the rest of the village waits.
