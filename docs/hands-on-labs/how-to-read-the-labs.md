# How to Read the Hands-On Labs

> **Read this BEFORE opening Phase 1 or any config-tuning lab.** It's the missing intro that explains why every gateway lab seems to report the same five numbers — without this mental model the labs feel repetitive and confusing. With it, they click immediately.

---

## Table of Contents

- [Why labs feel repetitive (yardstick vs knob)](#why-labs-feel-repetitive-yardstick-vs-knob)
- [The yardstick — 5 metrics every gateway lab measures](#the-yardstick--5-metrics-every-gateway-lab-measures)
- [The 5-question method for any gateway lab](#the-5-question-method-for-any-gateway-lab)
- [Worked example — Lab 2 (semantic cache)](#worked-example--lab-2-semantic-cache)
- [Suggested study order](#suggested-study-order)
- [Which knob does each lab turn?](#which-knob-does-each-lab-turn)
- [What NOT to do](#what-not-to-do)

---

## Why labs feel repetitive (yardstick vs knob)

The gateway labs are **NOT one lab per metric**. They are **one lab per knob**, all measured against **the same five-metric yardstick**.

```
                    ┌─────────────────────────────────────┐
                    │   THE YARDSTICK (5 metrics)         │
                    │   • latency (gateway + provider)    │
                    │   • cache hit %                     │
                    │   • cost per 1k requests            │
                    │   • error rate (4xx, 5xx, 429)      │
                    │   • throughput (req/s)              │
                    └─────────────────────────────────────┘
                                    ▲
                                    │ (every lab measures against this)
                                    │
   ┌────────────┬─────────────┬────┴─────┬─────────────┬─────────────┐
   │  Lab 2     │  Lab 3      │  CT-1    │  CT-3       │  Phase 2    │
   │  cache     │ rate-limit  │ TTL      │ model swap  │ fallback    │
   │  knob      │ knob        │ sweep    │ knob        │ knob        │
   └────────────┴─────────────┴──────────┴─────────────┴─────────────┘
```

So when Lab 2 reports `cache_hit=true, latency=5ms` and Lab 3 reports `error_rate=37%, latency=2ms`, those numbers exist because that's how we tell whether **turning that knob** improved the system or made it worse than the Lab 1 baseline. **The ruler doesn't change between labs — only the knob you're turning does.**

> 🚚 **Courier way:** the report card always grades the same five subjects — speed, cache hits, cost, rejected requests, and throughput. Each lab is a different lesson plan for those same subjects.

---

## The yardstick — 5 metrics every gateway lab measures

Memorise these once and the labs feel half as long.

| Metric | Range | Higher / Lower better | What it answers | Where it's logged |
| --- | --- | --- | --- | --- |
| **latency_ms** | 1 ms – 30 s | lower = better | How long did the round-trip take through the gateway? | response body `gateway_latency_ms` + access log |
| **cache_hit %** | 0 – 100 % | higher = better (usually) | What fraction of requests were served from Redis without an LLM call? | response body `cache_hit` boolean, aggregated |
| **cost ($/1k req)** | varies | lower = better | What did 1 000 requests cost in provider tokens? | PostgreSQL `cost_log` table |
| **error_rate %** | 0 – 100 % | lower = better | Fraction of responses that were 4xx (incl. 429 quota) or 5xx | structured logs, aggregated |
| **throughput (req/s)** | varies | higher = better | How many requests/second did the gateway sustain? | Prometheus counter / load-test report |

There is no single "overall score" like in rag-chatbot — the gateway is judged on a *trade-off*, not a composite. A high cache-hit rate is great UNLESS the threshold is so loose you're returning wrong answers. A low cost is great UNLESS error rate jumped because you starved the provider with too tight a rate limit. **Always read at least two of the five together.**

> 🚚 **Courier way:** read the report card as a row, not a column — speed, parcel weight, cost, complaints, and deliveries-per-shift only make sense together.

---

## The 5-question method for any gateway lab

For every lab in every phase, ask these five questions in order:

1. **What knob are we turning?** — `cache_ttl`, `rate_limit_per_minute`, `routing_strategy`, `temperature`, `max_tokens`, `model`, etc. The knob is the whole point of the lab.
2. **What's the hypothesis?** — One sentence: "raising TTL from 60 s to 600 s should lift cache hit % but stale answers may creep in." If the lab doesn't say it, write it down before reading the result.
3. **What's the baseline?** — Almost always the previous lab's numbers OR Lab 1's defaults. The lab is meaningful only as a *delta* against the baseline.
4. **What did the same yardstick measure?** — Look at the 5 metrics above. *Same metrics every lab.* If the lab introduces a new column (e.g. Lab 3 adds `429_count`), that's a *replacement* signal for the rate-limit knob, not a new yardstick.
5. **What's the takeaway?** — When would I turn this knob in production? What would force me to turn it back? That's the answer the lab is really teaching.

If you can answer those five in two minutes, you understood the lab. If not, re-read questions 1 and 3 — confusion almost always lives there.

---

## Worked example — Lab 2 (semantic cache)

Applying the 5-question method to Phase 1 Lab 2 ("Semantic Cache in Action"):

| # | Question | Answer for Lab 2 |
| --- | --- | --- |
| 1 | What knob? | The cache itself — first request bypasses (forced miss), then identical, semantic-similar, different-topic, and explicit `bypass_cache: true` requests are sent to probe what counts as a hit. |
| 2 | Hypothesis? | "Identical prompts hit instantly (~5 ms), paraphrases hit if cosine similarity ≥ ~0.92, unrelated prompts miss, and `bypass_cache: true` always misses regardless of pickup locker contents." |
| 3 | Baseline? | Lab 1 — cold cache, every request a full ~1500 ms LLM round-trip. |
| 4 | Yardstick? | `latency_ms` and `cache_hit %` are the dominant signals here. `cost` drops to ~0 on a hit because no LLM tokens are spent. `error_rate` and `throughput` should be flat (cache failures shouldn't introduce errors; throughput obviously rises with hits). |
| 5 | Takeaway? | Turn the cache **ON** for any workload with repeat or paraphrased questions (chatbots, FAQ, support). Lower the similarity threshold for higher hit % at the cost of occasionally returning the wrong cached answer. Raise it (towards 0.99) for code or numeric prompts where wrong-but-close is unacceptable. |

Now when you read row `Identical repeat | ✅ exact | ~5ms`, those numbers tell you: ✅ the cache delivered the predicted 300× speed-up. And `"What is quantum computing?" | ❌ | ~1500ms` proves the cache isn't just returning a stale answer for everything — it correctly misses on unrelated questions, which is what makes the hits trustworthy.

---

## Suggested study order

Phase order (Config Tuning → Phase 1 → Phase 2) is fine for reference. For *learning* the yardstick fastest, do this:

| Step | Lab | Why this order |
| --- | --- | --- |
| 1 | **Phase 1 Lab 1** First request | Learn the empty-yardstick baseline — no cache, no quota deliveryped, full provider latency. |
| 2 | **Phase 1 Lab 2** Cache | First experiment that moves `latency_ms` and `cache_hit %` dramatically. |
| 3 | **Phase 1 Lab 3** Rate limit | Introduces `error_rate %` (specifically 429s) — the first knob that *hurts* on purpose. |
| 4 | **Phase 1 Lab 4** Embeddings | Same yardstick, different endpoint — proves the gateway is consistent, not chat-only. |
| 5 | **Config Tuning labs** | Now sweep the dials one at a time (TTL, temperature, max_tokens, model, rate limit, similarity threshold). The yardstick stays the same. |
| 6 | **Phase 2 labs** | Multi-provider, fallback, cost-optimised routing under load — same yardstick, more interesting trade-offs. |

After Lab 1 + Lab 2, **every other lab is "what happens to those five numbers when I change X?"** That's the whole game.

---

## Which knob does each lab turn?

The single-sentence summary of every gateway lab. Bookmark this table.

| Lab | Knob | Yardstick metrics primarily affected | 🚚 Courier |
| --- | --- | --- | --- |
| Phase 1 Lab 1 | none (baseline cold-start) | latency (cold), cache_hit=0 | First delivery ever — empty pickup locker, fresh courier, full route, no shortcuts. |
| Phase 1 Lab 2 | semantic cache (on, vs bypass) | cache_hit %, latency_ms | The pickup locker shelf — does a paraphrased slip get the same note in 5 ms? |
| Phase 1 Lab 3 | `RATE_LIMIT_PER_MINUTE` (e.g. 5) | error_rate (429), throughput | Trip quota per courier — how the gate slams when one badge runs over budget. |
| Phase 1 Lab 4 | endpoint = `/v1/embeddings` | latency, cost (per parcel unit) | The GPS-coordinate writer — same dispatch desk, different output type. |
| Config Tuning #1 | `CACHE_TTL_SECONDS` sweep | cache_hit %, freshness vs staleness | How long pre-written notes stay in the pickup locker before the dispatcher tosses them. |
| Config Tuning #2 | `CACHE_SIMILARITY_THRESHOLD` sweep | cache_hit %, wrong-answer rate | How loose a paraphrase the dispatcher accepts as "same question". |
| Config Tuning #3 | `ROUTING_STRATEGY` (single / fallback / cost / round-robin) | latency, cost, error_rate | Which courier gets the next slip — fixed courier, backup courier, cheapest courier, or take-turns. |
| Config Tuning #4 | `LLM_TEMPERATURE` (0.0 / 0.3 / 0.7) | (qualitative) answer variability + cost flat | How predictable the model's output is — 0.0 same words every delivery, 0.7 creative. |
| Config Tuning #5 | `LLM_MAX_TOKENS` (256 / 1024 / 4096) | cost per request, truncation rate | How heavy a parcel the courier is allowed to carry back — small caps cut answers mid-sentence, large caps inflate spend. |
| Config Tuning #6 | model swap (Sonnet ↔ Haiku ↔ GPT-4o ↔ llama3.2) | cost ($/1k req), latency, error_rate | Which courier today — strong-and-expensive, fast-and-cheap, or the local depot courier for free. |
| Config Tuning #7 | `RATE_LIMIT_PER_MINUTE` sweep | error_rate (429), throughput | Same gate, different opening hours — find the quota that protects budget without starving real users. |
| Config Tuning #8 | semantic-cache ON vs OFF | cache_hit %, cost | The big switch — pickup locker present or removed entirely. |
| Phase 2 (fallback) | `ROUTING_STRATEGY=fallback` + simulated outage | error_rate (should ~0), latency (slight bump on failover) | Knock primary courier out — does the backup pick up the slip without the customer noticing? |
| Phase 2 (cost) | `ROUTING_STRATEGY=cost` under load | cost ($/1k req), latency distribution | Cheapest courier first — does the bill drop without latency exploding? |
| Phase 2 (observability) | logging / metrics dashboards on | none directly — visibility of all 5 above | Turn on the observability dashboard — every move now shows up in the dashboard. |

---

## What NOT to do

1. **Don't read one metric in isolation.** A 95 % cache hit rate is meaningless if the wrong-answer rate also rose because you loosened the similarity threshold. Always pair it with at least one other column.
2. **Don't compare across knobs.** "Lab 3 had 37 % errors but Lab 2 had 0 % errors" is a meaningless comparison — they're turning different knobs. Compare each lab against its own baseline only.
3. **Don't skip the hypothesis step.** If you read the result before writing down the hypothesis, you'll rationalise whatever you see. Write the prediction first, then read the table.
4. **Don't run a lab without the previous lab's numbers handy.** A delta needs a reference. If you can't quote the baseline number, you can't read the lab.
5. **Don't assume the local depot (Ollama) numbers translate to AWS/Azure.** Latency and cost shift by an order of magnitude between providers. Re-run the lab on the provider you actually plan to deploy on before drawing conclusions.
6. **Don't add a sixth metric without removing one.** The yardstick is five columns on purpose. If you add `p99_latency` you'd better drop `throughput` from your default view, otherwise tables become unreadable.

> 🚚 **Final courier wisdom:** every gateway lab is one of these two questions, dressed differently:
>
> - "I changed knob X. Did the cache hit more, did the courier get faster, or did the bill go down?" (Cache, TTL, similarity, model swap, cost routing)
> - "I changed knob X. Did anyone get rate-limited, did fallback kick in, did a backup courier have to step in?" (Rate limit, fallback, max_tokens truncation)
>
> Once you see this, the labs stop feeling repetitive. They become a series of small, controlled experiments — exactly what production AI engineering actually is.
