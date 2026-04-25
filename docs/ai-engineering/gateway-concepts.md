# Gateway Concepts — What is an LLM Gateway, Explained Simply

> The mental model you need before reading any other ai-gateway doc. By the end you'll know what an LLM gateway is, why teams build one instead of calling providers directly, and the four pillars (routing, caching, rate limiting, cost tracking) that make it useful.

---

## Table of Contents

- [What is an LLM gateway?](#what-is-an-llm-gateway)
- [Direct provider calls vs gateway calls](#direct-provider-calls-vs-gateway-calls)
- [Why centralize?](#why-centralize)
- [The four pillars](#the-four-pillars)
  - [Pillar 1 — Routing](#pillar-1--routing)
  - [Pillar 2 — Caching](#pillar-2--caching)
  - [Pillar 3 — Rate Limiting](#pillar-3--rate-limiting)
  - [Pillar 4 — Cost Tracking](#pillar-4--cost-tracking)
- [The OpenAI-compatible interface](#the-openai-compatible-interface)
- [Architecture mini-diagram](#architecture-mini-diagram)
- [When NOT to use a gateway](#when-not-to-use-a-gateway)
- [Glossary](#glossary)

---

## What is an LLM gateway?

An **LLM gateway** is a single HTTP service that sits between your applications and one or more LLM providers (OpenAI, Anthropic via Bedrock, Azure OpenAI, Ollama, …). Every app calls the gateway with the same OpenAI-compatible request shape; the gateway picks a provider, talks to it, and returns the response.

Think of it as a **reverse proxy specialised for LLM calls**, with bookkeeping (cost), control (rate limits), and acceleration (cache) built in.

> 🫏 **Donkey analogy:** The gateway is one front door for many donkeys (LLMs) — your app asks once, it picks the right donkey and brings the answer back.

---

## Direct provider calls vs gateway calls

Without a gateway, your app code directly imports each provider's SDK:

```
┌──────────┐      boto3.invoke_model       ┌─────────────┐
│  App A   │───────────────────────────────▶│ AWS Bedrock │
└──────────┘                                 └─────────────┘
┌──────────┐      openai.ChatCompletion     ┌─────────────┐
│  App B   │───────────────────────────────▶│ Azure OAI   │
└──────────┘                                 └─────────────┘
┌──────────┐      httpx.post                 ┌─────────────┐
│  App C   │───────────────────────────────▶│ Ollama      │
└──────────┘                                 └─────────────┘
```

Each app reinvents auth, retries, cost logging, and provider switching. With a gateway:

```
┌──────────┐                                 ┌─────────────┐
│  App A   │──┐                            ┌▶│ AWS Bedrock │
└──────────┘  │   POST /v1/chat/completions │ └─────────────┘
┌──────────┐  │   (OpenAI format)            │ ┌─────────────┐
│  App B   │──┼──▶ ┌─────────┐  ──────────────┼▶│ Azure OAI   │
└──────────┘  │    │ Gateway │                │ └─────────────┘
┌──────────┐  │    └─────────┘  ──────────────┼▶┌─────────────┐
│  App C   │──┘                                 │ Ollama      │
└──────────┘                                    └─────────────┘
```

The gateway becomes the *one place* where you wire up auth, observability, retries, fallback, caching, rate limits, and cost.

---

## Why centralize?

Five concrete reasons:

1. **One API surface.** Apps speak OpenAI format only. Switching providers = change one env var on the gateway, not 14 codebases.
2. **Cost tracking in one ledger.** Every token is counted in one PostgreSQL table — finance gets a single dashboard, not seven CloudWatch invoices.
3. **Fallback when a provider is down.** Bedrock throttling? Gateway transparently retries against Azure. The calling app never sees the failure.
4. **Rate limit per API key, per app.** Stop one runaway batch job from burning your whole monthly budget on Sonnet.
5. **Caching across apps.** App A asks "summarise these terms" — App B asks the same thing two minutes later — App B gets a free hit from the cache. No second LLM call.

> 🫏 **Donkey analogy:** The gateway is the stable's reception desk — one ledger, one quota policy, and a spare donkey ready when another is sick.

---

## The four pillars

Every production LLM gateway — including this one — is built on the same four pillars. Each is a distinct concern with a clean interface.

### Pillar 1 — Routing

**Job:** Given a request, decide *which* provider and *which* model to call.

The gateway supports four routing strategies (selectable per deployment via `ROUTING_STRATEGY`):

| Strategy | Behaviour | When to use |
| --- | --- | --- |
| `single` | Always route to one configured provider | Dev, single-vendor production |
| `fallback` | Try provider list in order; on failure try next | High-availability — survive a provider outage |
| `cost` | Pick cheapest healthy provider per request | Bulk batch workloads where pennies add up |
| `round-robin` | Distribute requests evenly | Load-balance across providers / spread quota |

> 🫏 **Donkey analogy:** Routing picks which donkey takes the next delivery note — always one donkey, the cheapest, a backup if one is sick, or take turns.

### Pillar 2 — Caching

**Job:** If a near-identical request just came through, return the previous answer without re-calling the LLM.

This gateway uses **semantic caching** — incoming prompts are embedded into vectors, the cache (Redis) is searched by cosine similarity, and any hit above the configured threshold is returned immediately. That catches paraphrases, not just exact repeats.

Trade-off: setting the similarity threshold too low returns wrong answers; too high and the cache rarely hits. Typical: cosine ≥ 0.95 for chat, ≥ 0.99 for code.

> 🫏 **Donkey analogy:** Semantic cache = a shelf of pre-written notes the donkey can grab when the question is similar to one already answered.

### Pillar 3 — Rate Limiting

**Job:** Cap how many requests each API key (= each app, each user, each tenant) can make per time window.

This gateway uses a **fixed-window** limiter keyed by API key, backed by Redis (production) or in-memory (dev). On the (N+1)th request inside the window, the gateway returns HTTP 429 and the calling app must back off.

Why per API key? Because one runaway batch job should hit *its* ceiling, not take the whole gateway down for everyone.

> 🫏 **Donkey analogy:** Rate limit = a cap on how many trips per minute each customer (API key) can request — others are unaffected.

### Pillar 4 — Cost Tracking

**Job:** Log every request's provider, model, input tokens, output tokens, and computed cost — so finance and engineering can see who is spending what.

Stored per-request in PostgreSQL (production) or in-memory (dev). Aggregated views are exposed via `/v1/usage`. Token counts come back from LiteLLM's `usage` field; price-per-1K-tokens lives in a config table per provider/model.

> 🫏 **Donkey analogy:** Cost tracking is the donkey's expense tab — every trip's customer, donkey, cargo size, and price logged for the month-end report card.

---

## The OpenAI-compatible interface

Why OpenAI's request shape and not something the gateway invented?

- **Adoption.** Every LLM SDK, agent framework, and IDE plugin already speaks OpenAI's format. Speak OpenAI = work with everything out of the box.
- **Forward-compatibility.** When OpenAI add a field, the rest of the ecosystem adopts it within weeks. Riding their schema means getting tool-call support, streaming, and JSON-mode for free.
- **Testability.** You can swap the gateway URL into any OpenAI client (Python `openai.OpenAI(base_url=...)`, the `curl` examples in OpenAI's docs, …) and it Just Works.

The contract is simple:

```
POST /v1/chat/completions
Authorization: Bearer <api-key>
Content-Type: application/json

{
  "model": "claude-sonnet",
  "messages": [{"role": "user", "content": "Hello"}],
  "temperature": 0.0
}
```

What the gateway does with `model`: looks it up in its routing config and translates to the actual provider model string (e.g. `bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0`). The caller never has to know the AWS model ID.

> 🫏 **Donkey analogy:** OpenAI's request shape is the standard delivery note every customer fills out and every donkey already knows how to read.

---

## Architecture mini-diagram

```
                ┌────────────────────────────────────────────┐
                │              AI GATEWAY                    │
                │  (FastAPI on port 8100)                    │
                │                                            │
   client ──▶   │  1. Auth (API key)                         │
                │       │                                    │
                │       ▼                                    │
                │  2. Rate limiter ──── Redis (per-key)      │
                │       │                                    │
                │       ▼                                    │
                │  3. Cache check ──── Redis (cosine sim)    │
                │       │  (hit? → return immediately)       │
                │       ▼                                    │
                │  4. LiteLLM router ──── Routing strategy   │
                │       │                                    │
                │       ▼                                    │
                │  5. Provider call ──── AWS / Azure / Local │
                │       │                                    │
                │       ▼                                    │
                │  6. Cost tracker ──── PostgreSQL (insert)  │
                │       │                                    │
                │       ▼                                    │
                │  7. Cache write ──── Redis (set)           │
                │       │                                    │
   ◀───── response ◀────┘                                    │
                └────────────────────────────────────────────┘
```

Every request walks this pipeline once. Each step is a separately testable component with its own deep-dive doc under `docs/ai-engineering/`.

---

## When NOT to use a gateway

A gateway is overhead. It buys you the four pillars at the cost of:

- **One more service to run, monitor, and pay for.** Redis + PostgreSQL + the gateway itself = three more processes.
- **Extra latency.** A round-trip through the gateway adds ~5–20 ms even on a cache hit, more on a cache miss.
- **A single point of failure** if you don't run it HA. Direct provider calls don't have this dependency.

**Skip the gateway when:**

- You have **one app** calling **one provider** and don't need fallback. Just use the SDK.
- Your **latency budget** is sub-50 ms end-to-end (rare in LLM use cases — but it happens for streaming-first chat).
- You're **prototyping** and provider switching / cost tracking aren't problems yet. Add the gateway when you have ≥ 2 apps or ≥ 2 providers.

Rule of thumb: **two apps or two providers = gateway becomes worth it.**

> 🫏 **Donkey analogy:** Skip the gateway if you have one donkey and one customer — only worth it once you have at least two donkeys or two customers.

---

## Glossary

| Term | What it means | 🫏 Donkey |
| --- | --- | --- |
| **LLM** | Large Language Model — the thing that turns prompts into text | The donkey — does the actual carrying once the dispatcher hands it the slip. |
| **Gateway** | The proxy service in front of the LLMs (this repo) | The stable's switchboard / dispatch desk where every slip lands first. |
| **LiteLLM** | Library that translates OpenAI-format calls into 100+ provider formats | Universal harness that fits any donkey — same reins regardless of which donkey is in it. |
| **Provider** | A company or service that hosts an LLM (AWS Bedrock, Azure OpenAI, Ollama, …) | A stable a donkey works for — AWS depot, Azure hub, local barn. |
| **Routing strategy** | The rule the gateway uses to pick a provider per request | The dispatcher's "which donkey gets this slip?" policy. |
| **Fallback** | If primary provider fails, retry against the next one in a list | Backup donkey when the primary calls in sick — customer never notices. |
| **Semantic cache** | Redis-backed cache keyed by embedding cosine similarity, not exact match | Pigeon-hole of pre-written replies — match by *meaning* of the question, not exact wording. |
| **Cache TTL** | How long a cached entry stays valid before being evicted | How long the pre-written note is allowed to sit in the pigeon-hole before the dispatcher tosses it. |
| **Rate limit** | Cap on requests per time window per API key | Trip quota per courier — each key gets N trips per minute, no exceptions. |
| **API key** | The token a client sends in `Authorization: Bearer …` to identify itself | The courier's badge — the dispatcher looks at the badge to decide quota and bill the right account. |
| **Cost tracking** | Per-request log of provider, model, tokens, and price | The leather-bound expense ledger — every trip costed and saved for the month-end report. |
| **Token** | The unit LLMs count input + output by, billed at a $/1K rate | A cargo unit — the donkey is paid by the kilo, not by the trip. |
| **Observability** | Logs + metrics + traces that explain what the gateway did | Stable CCTV plus tachograph — every step of every trip is timestamped and replayable. |
| **OpenAI-compatible** | Speaks OpenAI's request/response shape so existing clients work unchanged | The industry-standard delivery slip — every customer fills it out the same way. |
| **Round-trip latency** | Time from client request → gateway → provider → response | How long the courier waits at the front desk from handing over the slip to getting the parcel back. |

---

**Next:** read the [Architecture Overview](../architecture-and-design/architecture.md) to see how these pillars are wired together in code.
