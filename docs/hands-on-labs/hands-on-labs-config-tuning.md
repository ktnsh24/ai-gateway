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
- [Lab 8: LLM-as-Judge Evaluation](#lab-8-llm-as-judge-evaluation--can-a-smarter-llm-grade-the-gateways-routing-choices)

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
| Value | Cache hit rate | Faithfulness | Latency (ms) | Cost (€) | Notes | 🫏 Donkey |
|---|---|---|---|---|---|---|
| 0.0 | ___ | ___ | ___ | ___ | ___ | 🫏 A zero-temperature donkey delivers identical parcels every time, making the pigeon-hole cache extremely effective at reusing yesterday's reply. |
| 0.3 | ___ | ___ | ___ | ___ | ___ | 🫏 At 0.3, the donkey adds mild variation to each delivery, balancing cache reuse against reasonable answer diversity for most queries. |
| 0.7 | ___ | ___ | ___ | ___ | ___ | 🫏 A 0.7-temperature donkey improvises freely, producing varied replies that defeat the pigeon-hole cache and inflate the expense ledger. |

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
| Value | Cache hit rate | Faithfulness | Latency (ms) | Cost (€) | Notes | 🫏 Donkey |
|---|---|---|---|---|---|---|
| strict | ___ | ___ | ___ | ___ | ___ | 🫏 A strict delivery note handed to every donkey raises the whole stable's quality floor without each client writing their own instructions. |
| balanced | ___ | ___ | ___ | ___ | ___ | 🫏 A balanced delivery note gives the donkey room to adapt tone, trading some consistency for flexibility across varied client requests. |
| lax | ___ | ___ | ___ | ___ | ___ | 🫏 A lax delivery note lets each donkey freelance, risking inconsistent replies and making the pigeon-hole cache nearly impossible to calibrate. |

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
| Value | Cache hit rate | Faithfulness | Latency (ms) | Cost (€) | Notes | 🫏 Donkey |
|---|---|---|---|---|---|---|
| llama3.2:1b (local) | ___ | ___ | ___ | ___ | ___ | 🫏 The 1B local barn donkey completes simple errands cheaply with no cloud fees, though it struggles with complex multi-step reasoning tasks. |
| llama3.2 (3B, local) | ___ | ___ | ___ | ___ | ___ | 🫏 The 3B local barn donkey handles moderately complex deliveries still at zero cloud cost, offering a useful middle ground for most queries. |
| Bedrock Claude 3.5 Sonnet | ___ | ___ | ___ | ___ | ___ | 🫏 The AWS depot's thoroughbred donkey delivers high-quality answers but logs a noticeably larger entry in the expense ledger per cargo unit. |
| Azure GPT-4o | ___ | ___ | ___ | ___ | ___ | 🫏 The Azure hub's racehorse donkey excels at nuanced multi-step trips and is priced competitively for high-quality workloads via the Azure stable door. |
| ROUTING_STRATEGY=cost | ___ | ___ | ___ | ___ | ___ | 🫏 The dispatch desk automatically picks the cheapest donkey available for each delivery, keeping the expense ledger lean without client involvement. |

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
| Value | Cache hit rate | Faithfulness | Latency (ms) | Cost (€) | Notes | 🫏 Donkey |
|---|---|---|---|---|---|---|
| 256 | ___ | ___ | ___ | ___ | ___ | 🫏 A 256-unit cargo cap forces the donkey to cut replies short, saving cost but risking truncated answers that frustrate downstream clients. |
| 1024 | ___ | ___ | ___ | ___ | ___ | 🫏 A 1024-unit cargo cap comfortably covers most queries, balancing reply completeness against per-request cost in the expense ledger. |
| 4096 | ___ | ___ | ___ | ___ | ___ | 🫏 A 4096-unit cap lets the donkey carry a full crate, ideal for long documents but exposing the ledger to runaway bills on a single careless request. |

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
| Value | Cache hit rate | Faithfulness | Latency (ms) | Cost (€) | Notes | 🫏 Donkey |
|---|---|---|---|---|---|---|
| 60s (1 min) | ___ | ___ | ___ | ___ | ___ | 🫏 A 60-second pigeon-hole shelf clears stale notes quickly, keeping answers fresh but forcing a donkey trip for nearly every minute-old query. |
| 3600s (1 hr) | ___ | ___ | ___ | ___ | ___ | 🫏 A one-hour shelf means the dispatch desk reuses the same reply for an entire hour, cutting donkey trips dramatically for stable-knowledge questions. |
| 86400s (1 day) | ___ | ___ | ___ | ___ | ___ | 🫏 A full-day shelf maximises cache savings but risks the pigeon-hole handing back yesterday's news for time-sensitive questions like today's date. |

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
| Value | Cache hit rate | Faithfulness | Latency (ms) | Cost (€) | Notes | 🫏 Donkey |
|---|---|---|---|---|---|---|
| 0.80 | ___ | ___ | ___ | ___ | ___ | 🫏 A 0.80 threshold means the pigeon-hole treats loosely similar questions as identical, yielding high hit rates but occasionally handing back the wrong parcel. |
| 0.92 | ___ | ___ | ___ | ___ | ___ | 🫏 The 0.92 default threshold balances cache reuse against accuracy, only matching deliveries whose GPS coordinates are very nearly the same address. |
| 0.98 | ___ | ___ | ___ | ___ | ___ | 🫏 A 0.98 threshold means only near-identical queries reuse the cached note, making the pigeon-hole almost as quiet as if caching were disabled entirely. |

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
| Value | 429 rate | Faithfulness | Latency p95 (ms) | Cost (€) | Notes | 🫏 Donkey |
|---|---|---|---|---|---|---|
| 10 RPM | ___ | ___ | ___ | ___ | ___ | 🫏 Ten trips per minute per courier means even a slow client will exhaust quota quickly, returning a 429 quota-used-up error after the eleventh knock. |
| 60 RPM | ___ | ___ | ___ | ___ | ___ | 🫏 Sixty trips per minute is a comfortable quota for typical clients, keeping the stable door busy but preventing any single courier from monopolising every donkey. |
| 600 RPM | ___ | ___ | ___ | ___ | ___ | 🫏 Six hundred trips per minute practically removes the trip quota for high-volume internal clients, shifting the cost guard to the provider tier instead. |

### What we learned
Rate limits protect the budget more than the latency. Tier them per API key (free / paid / internal) and always return useful headers (`X-RateLimit-Remaining`, `Retry-After`).

### 🫏 Donkey takeaway
The stable's front door only lets each client knock so many times per minute; otherwise one shouty client ties up every donkey and the rest of the village waits.

---

## Lab 8: LLM-as-Judge Evaluation — "Can a smarter LLM grade the gateway's routing choices?"

**Config:** `EVAL_MODE` (default: `rule_based`)
**What it controls:** Whether evaluation uses Python rules (cheap, deterministic) or a second LLM call (expensive, semantic) — and for the gateway, whether the judge also scores ROUTING CORRECTNESS ("did this query deserve a Sonnet, or could a Haiku have handled it?").
**Hypothesis:** Rule-based eval misses semantic hallucinations AND has no opinion on whether the gateway over-spent (sent a trivial query to Sonnet) or under-spent (sent a hard query to Haiku and got a bad answer). LLM-as-judge catches both at ~$0.001/eval.

### Why this matters
Rule-based evaluation (`EVAL_MODE=rule_based`) checks faithfulness keyword overlap on whatever the routed model returned. It's free and instant — but it cannot tell whether the gateway's router made a SMART or DUMB routing choice. A correct answer from the wrong (too-expensive) model is a silent budget leak.

LLM-as-judge (`EVAL_MODE=llm_judge`) sends the question, the routing decision (which model + why), the routed model's answer, and the cost/latency to a second cheap LLM with a rubric that scores BOTH answer quality AND routing fit. It catches the failure mode where Sonnet was used for "What is 17×23?" or Haiku was used for a multi-step reasoning task.

### Setup
1. Add `EVAL_MODE=rule_based` to `.env`
2. Pick a "judge" LLM in `.env`:
   - Local: `JUDGE_LLM_PROVIDER=ollama` + `JUDGE_LLM_MODEL=llama3.2`
   - AWS: `JUDGE_LLM_PROVIDER=bedrock` + `JUDGE_LLM_MODEL=anthropic.claude-haiku-...`
   - Azure: `JUDGE_LLM_PROVIDER=azure_openai` + `JUDGE_LLM_MODEL=gpt-4o-mini`
3. Implement the judge prompt (see template below) — it must take the routing decision, not just the answer
4. Run Q1–Q3 with both modes
5. Compare faithfulness scores AND the new routing-fit score

### The judge prompt template
```text
You are a strict evaluator of an LLM gateway's routing decision AND its routed answer. Given:
- QUESTION: {question}
- AVAILABLE_MODELS: {model_catalog}    # e.g. {"haiku": "cheap, fast, simple Qs", "sonnet": "expensive, multi-step reasoning", "opus": "premium, only for hardest tasks"}
- ROUTED_MODEL: {model}                # which model the gateway picked
- ROUTING_REASON: {reason}             # gateway's stated reason (if any)
- ANSWER: {answer}
- COST_USD: {cost}
- LATENCY_MS: {latency}

Score on:
1. answer_quality (0.0–1.0): Was the ANSWER correct and complete for the QUESTION?
2. routing_fit (0.0–1.0): Was ROUTED_MODEL the cheapest model in AVAILABLE_MODELS that could have produced this answer quality? (1.0 = perfect fit; 0.5 = over- or under-spent by one tier; 0.0 = badly mis-routed.)
3. cost_efficiency (0.0–1.0): Given the answer quality, was COST_USD reasonable?

Return strict JSON: {"answer_quality": 0.x, "routing_fit": 0.x, "cost_efficiency": 0.x, "should_have_routed_to": "haiku|sonnet|opus", "reason": "..."}
```

### Results table (fill in as you run)
| Question | Routed model | Rule-based faithfulness | LLM-judge answer_quality | LLM-judge routing_fit | Should have routed to | Why? | 🫏 Donkey |
|---|---|---|---|---|---|---|---|
| Q1 (Explain RAG in 2 sentences) | ___ | ___ | ___ | ___ | haiku (simple) | Sonnet would be over-spend | 🫏 Explaining RAG in two sentences is a straightforward delivery any small barn donkey handles; routing it to a racehorse wastes the expense ledger. |
| Q2 (Translate "good morning" → Dutch) | ___ | ___ | ___ | ___ | haiku (trivial) | Anything bigger is wasted | 🫏 A simple phrase translation is the lightest possible cargo; the dispatch desk should always pick the cheapest donkey rather than burn a thoroughbred on it. |
| Q3 (17 × 23) | ___ | ___ | ___ | ___ | haiku (or tool) | LLM-judge flags Sonnet as over-spend | 🫏 Basic arithmetic is a one-step errand; routing it to the expensive Sonnet donkey is like hiring a racehorse to deliver a sticky note around the corner. |

### Cost comparison
| Mode | Cost per eval | Latency added | Determinism | 🫏 Donkey |
|---|---|---|---|---|
| `rule_based` | €0 | ~1ms | ✅ Same input → same score | 🫏 The rule-based clipboard costs nothing and checks each parcel instantly against a fixed tick-list, giving the same verdict for every identical delivery. |
| `llm_judge` (Haiku) | ~$0.001 | ~500–1500ms | ❌ May vary slightly across runs | 🫏 The Haiku judge donkey reads the whole dispatch record and scores routing-fit for half a penny per trip, but occasionally grades the same delivery differently. |
| `llm_judge` (GPT-4o) | ~$0.01 | ~1–3s | ❌ May vary | 🫏 The GPT-4o judge is a premium senior dispatcher costing a cent per review, spending one to three seconds weighing routing quality before rendering a verdict. |

### What we learned
Rule-based eval is the right default — it's free, fast, and catches obvious failures. For a gateway, LLM-as-judge is uniquely valuable because it can score ROUTING-FIT, which rules cannot. Production pattern: run rule-based on every request, run LLM-judge on samples flagged as marginal OR where COST_USD is in the top 5% (the expensive routes are the ones worth auditing), and run a daily nightly batch over the golden dataset. Never run LLM-judge on 100% of traffic — at gateway-scale traffic, the judge cost would dwarf the routed-model cost.

### 🫏 Donkey takeaway
Rule-based eval is a clipboard-with-checkboxes the stable master uses on every parcel. LLM-as-judge is the senior dispatcher who reviews a sample of trips and notices when a racehorse was sent to deliver a postcard next door — the parcel arrived, but the stable spent ten times what it should have. The clipboard tracks delivery; the dispatcher tracks the bill.
