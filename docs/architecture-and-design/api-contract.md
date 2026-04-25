# API Contract — AI Gateway

> **Base URL:** `http://localhost:8100`
>
> **Format:** OpenAI-compatible with gateway extensions
>
> **Auth:** Optional Bearer token

---

## Table of Contents

1. [Authentication](#1-authentication)
2. [Chat Completions](#2-chat-completions)
3. [Embeddings](#3-embeddings)
4. [Models](#4-models)
5. [Usage Dashboard](#5-usage-dashboard)
6. [Health Check](#6-health-check)
7. [Error Responses](#7-error-responses)
8. [Gateway Extensions](#8-gateway-extensions)
9. [Cross-References](#9-cross-references)

---

## 1. Authentication

When `API_KEYS_ENABLED=true`, all `/v1/*` endpoints require a Bearer token:

```
Authorization: Bearer <api-key>
```

Keys are configured via `GATEWAY_API_KEYS` (comma-separated).

**Public paths** (never require auth):
- `GET /health`
- `GET /docs` (Swagger UI)
- `GET /openapi.json`

---

## 2. Chat Completions

### `POST /v1/chat/completions`

**Request:**

```json
{
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "What is the capital of France?"}
  ],
  "model": "default",
  "temperature": 0.7,
  "max_tokens": 1024,
  "bypass_cache": false,
  "preferred_provider": null
}
```

| Field | Type | Required | Default | Description | 🚚 Courier |
|-------|------|----------|---------|-------------|-----------|
| `messages` | `list[Message]` | ✅ | — | Chat messages (system, user, assistant) | 🚚 The shipping manifest itself — a list of system and user parcel that the dispatch desk hands to the chosen courier for this delivery. |
| `model` | `string` | ❌ | `"default"` | Model to use (or `"default"` for provider default) | 🚚 Specifies which model type to request; use "default" to let the dispatch desk pick from the current available roster. |
| `temperature` | `float` | ❌ | `0.7` | Sampling temperature (0.0–2.0) | 🚚 How creative the courier is allowed to be — zero means safest known route, two means wildly exploratory and unpredictable delivery paths. |
| `max_tokens` | `int` | ❌ | `1024` | Maximum tokens in response | 🚚 Sets the maximum tokens the courier can pack into its reply before being told to stop and return immediately to the depot. |
| `bypass_cache` | `bool` | ❌ | `false` | 🔌 Gateway extension: skip cache | 🚚 Gateway extension telling the dispatch desk to skip the pickup locker entirely and send a fresh shipping manifest directly to the courier. |
| `preferred_provider` | `string` | ❌ | `null` | 🔌 Gateway extension: force provider | 🚚 Gateway extension that forces the dispatch desk to route this delivery to a specific depot — AWS depot, Azure hub, or local depot. |

**Response (200):**

```json
{
  "id": "chatcmpl-abc123def456",
  "object": "chat.completion",
  "created": 1714000000,
  "model": "ollama/llama3.2",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "The capital of France is Paris."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 25,
    "completion_tokens": 8,
    "total_tokens": 33
  },
  "cost": {
    "estimated_cost_usd": 0.000033,
    "provider": "local",
    "model": "ollama/llama3.2",
    "cached": false
  },
  "cache_hit": false,
  "gateway_latency_ms": 1523.45
}
```

| Field | Type | Description | 🚚 Courier |
|-------|------|-------------|-----------|
| `id` | `string` | Unique completion ID | 🚚 The tachograph stamp burned onto this completed delivery — use it to cross-reference gateway logs and expense ledger entries by request. |
| `object` | `string` | Always `"chat.completion"` | 🚚 Always "chat.completion" — confirms to the courier client that the gateway's front door returned a filled delivery receipt, not an error slip. |
| `created` | `int` | Unix timestamp | 🚚 Unix timestamp marking the exact moment the courier handed the filled shipping manifest back through the gateway's main delivery window. |
| `model` | `string` | Model used (LiteLLM format: `provider/model`) | 🚚 The universal harness format — tells you exactly which courier and which remote depot handled this particular parcel run for billing purposes. |
| `choices` | `list[Choice]` | Completion choices | 🚚 The list of filled shipping manifests returned by the courier; currently one reply per delivery unless the N field is set higher in the request. |
| `usage` | `Usage` | Token counts | 🚚 The token tally — prompt units in plus completion units out — used to calculate the line item on the cost ledger. |
| `cost` | `CostInfo` | 🔌 Gateway extension: cost breakdown | 🚚 Gateway extension showing estimated USD cost, which provider depot, which model, and whether the pickup locker was used instead. |
| `cache_hit` | `bool` | 🔌 Gateway extension: was this a cache hit? | 🚚 Gateway extension flag — true means the dispatch desk found a pre-written reply in the pickup locker and never woke the courier at all. |
| `gateway_latency_ms` | `float` | 🔌 Gateway extension: end-to-end latency | 🚚 Gateway extension measuring every millisecond from depot door entry to response header, including pickup locker lookup and courier round trip. |

---

## 3. Embeddings

### `POST /v1/embeddings`

**Request:**

```json
{
  "input": "Hello world",
  "model": "default"
}
```

| Field | Type | Required | Default | Description | 🚚 Courier |
|-------|------|----------|---------|-------------|-----------|
| `input` | `string \| list[string]` | ✅ | — | Text(s) to embed | 🚚 The text handed to the GPS-coordinate writer; one string or a list to encode multiple passages in a single call. |
| `model` | `string` | ❌ | `"default"` | Embedding model | 🚚 Which GPS-coordinate writer courier to use; "default" lets the dispatch desk assign the registered embedding model for the current depot. |

**Response (200):**

```json
{
  "object": "list",
  "data": [
    {
      "object": "embedding",
      "index": 0,
      "embedding": [0.0023, -0.0091, 0.0156, ...]
    }
  ],
  "model": "ollama/nomic-embed-text",
  "usage": {
    "prompt_tokens": 2,
    "total_tokens": 2
  }
}
```

---

## 4. Models

### `GET /v1/models`

**Response (200):**

```json
{
  "object": "list",
  "data": [
    {
      "id": "llama3.2",
      "object": "model",
      "provider": "local",
      "model_type": "chat"
    },
    {
      "id": "nomic-embed-text",
      "object": "model",
      "provider": "local",
      "model_type": "embedding"
    }
  ]
}
```

---

## 5. Usage Dashboard

### `GET /v1/usage?period=today`

| Param | Type | Default | Options | 🚚 Courier |
|-------|------|---------|---------|-----------|
| `period` | `string` | `"today"` | `today`, `week`, `month`, `all` | 🚚 Slide the expense ledger window open to today, the past week, the full month, or the entire lifetime of the gateway's billing records. |

**Response (200):**

```json
{
  "period": "today",
  "total_requests": 142,
  "total_tokens": 45230,
  "total_cost_usd": 0.0453,
  "cache_hit_rate": 0.23,
  "by_model": {
    "ollama/llama3.2": {
      "requests": 120,
      "tokens": 38000,
      "cost_usd": 0.0
    },
    "bedrock/anthropic.claude-3-5-sonnet-v2": {
      "requests": 22,
      "tokens": 7230,
      "cost_usd": 0.0453
    }
  },
  "by_provider": {
    "local": {"requests": 120, "cost_usd": 0.0},
    "aws": {"requests": 22, "cost_usd": 0.0453}
  }
}
```

---

## 6. Health Check

### `GET /health`

**Response (200):**

```json
{
  "status": "healthy",
  "version": "0.1.0",
  "provider": "local",
  "components": {
    "redis": "connected",
    "postgresql": "connected",
    "llm_router": "ready",
    "models_available": ["llama3.2", "nomic-embed-text"]
  }
}
```

---

## 7. Error Responses

All errors follow a consistent format:

```json
{
  "error": {
    "message": "Rate limit exceeded. Retry after 45 seconds.",
    "type": "rate_limit_error",
    "code": 429
  }
}
```

| Status | Type | When | 🚚 Courier |
|--------|------|------|-----------|
| `400` | `bad_request` | Malformed JSON, missing fields | 🚚 The shipping manifest arrived crumpled or missing required fields — the gateway's front door rejected it before any courier was dispatched. |
| `401` | `authentication_error` | Invalid or missing API key | 🚚 The courier showed up without a valid permission slip — the gateway's front door refused entry before the dispatch desk even saw the note. |
| `422` | `validation_error` | Pydantic validation failure | 🚚 The shipping manifest was readable but the gateway's Pydantic validator found illegal parcel — wrong type or value out of accepted range. |
| `429` | `rate_limit_error` | Rate limit exceeded | 🚚 The courier's daily dispatch quota for the current window is used up — wait for the clock to reset before sending any more shipping manifests. |
| `500` | `internal_error` | Unexpected server error | 🚚 The gateway tripped over something unexpected inside — not the courier's fault, not the courier's; check the gateway's internal logs. |
| `502` | `provider_error` | LLM provider returned error | 🚚 The remote depot picked up but returned an error receipt — the courier made the delivery but came back with a broken response from the provider. |
| `503` | `service_unavailable` | All providers failed (fallback exhausted) | 🚚 Every courier in every registered depot is sick or unreachable — the fallback chain is exhausted and no one can carry the shipping manifest. |

---

## 8. Gateway Extensions

These fields are **not part of the OpenAI spec** but are added by the gateway for observability:

### Request Extensions

| Field | Type | Description | 🚚 Courier |
|-------|------|-------------|-----------|
| `bypass_cache` | `bool` | Skip cache lookup (force fresh LLM call) | 🚚 Forces the dispatch desk to skip the pickup locker entirely and send a fresh shipping manifest to the courier even if a cached reply exists. |
| `preferred_provider` | `string` | Override routing strategy for this request | 🚚 Overrides the routing strategy for one delivery, directing the dispatch desk to a specific depot — AWS depot, Azure hub, or local depot. |

### Response Extensions

| Field | Type | Description | 🚚 Courier |
|-------|------|-------------|-----------|
| `cost` | `CostInfo` | Estimated cost, provider, model, cached flag | 🚚 The per-trip line item on the expense ledger — estimated USD cost, provider depot name, model, and whether the pickup locker was used. |
| `cache_hit` | `bool` | Whether the response came from cache | 🚚 Tells the courier whether the reply was a fresh courier run or a pre-written note pulled from the pickup locker without waking anyone. |
| `gateway_latency_ms` | `float` | Total gateway processing time | 🚚 Total wall-clock time from depot door arrival to response despatch, covering auth check, pickup locker lookup, and courier round trip. |

### Response Headers

| Header | Description | 🚚 Courier |
|--------|-------------|-----------|
| `X-Request-ID` | Unique request identifier for tracing | 🚚 The unique tachograph stamp assigned to every delivery through the gateway, used to correlate gateway logs with provider-side records. |
| `X-Gateway-Latency-Ms` | Processing time in milliseconds | 🚚 Total milliseconds the gateway took to process this delivery, from front-door arrival to the courier receiving their filled receipt. |

---

## 9. Cross-References

| Topic | Document | 🚚 Courier |
|-------|----------|-----------|
| Architecture overview | [Architecture](architecture.md) | 🚚 The infrastructure blueprint shows how the dispatch desk, pickup locker, daily-dispatch-quota counter, and expense ledger all connect behind the front door. |
| Pydantic model definitions | [Pydantic Models Reference](../reference/pydantic-models.md) | 🚚 The gateway's full Pydantic model inventory lists every request and response parcel schema the front door validates on arrival. |
| Caching behavior | [Caching Deep Dive](../ai-engineering/caching-deep-dive.md) | 🚚 The pickup locker deep dive explains exact-match SHA-256 keys, cosine-similarity semantic matching, and TTL eviction rules in detail. |
| Rate limiting algorithm | [Rate Limiting Deep Dive](../ai-engineering/rate-limiting-deep-dive.md) | 🚚 The daily-dispatch-quota deep dive walks through the fixed-window counter, Redis INCR commands, and the boundary-burst edge case at window edges. |
| Cost tracking schema | [Cost Tracking Deep Dive](../ai-engineering/cost-tracking-deep-dive.md) | 🚚 The expense ledger deep dive covers the PostgreSQL schema, per-provider cost calculation, and how cached deliverys are flagged differently. |
| Setup instructions | [Getting Started](../setup-and-tooling/getting-started.md) | 🚚 The getting-started guide explains how to boot the portable stack and verify the front door is accepting shipping manifests. |
