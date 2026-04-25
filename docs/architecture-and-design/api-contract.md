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

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `messages` | `list[Message]` | ✅ | — | Chat messages (system, user, assistant) |
| `model` | `string` | ❌ | `"default"` | Model to use (or `"default"` for provider default) |
| `temperature` | `float` | ❌ | `0.7` | Sampling temperature (0.0–2.0) |
| `max_tokens` | `int` | ❌ | `1024` | Maximum tokens in response |
| `bypass_cache` | `bool` | ❌ | `false` | 🔌 Gateway extension: skip cache |
| `preferred_provider` | `string` | ❌ | `null` | 🔌 Gateway extension: force provider |

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

| Field | Type | Description |
|-------|------|-------------|
| `id` | `string` | Unique completion ID |
| `object` | `string` | Always `"chat.completion"` |
| `created` | `int` | Unix timestamp |
| `model` | `string` | Model used (LiteLLM format: `provider/model`) |
| `choices` | `list[Choice]` | Completion choices |
| `usage` | `Usage` | Token counts |
| `cost` | `CostInfo` | 🔌 Gateway extension: cost breakdown |
| `cache_hit` | `bool` | 🔌 Gateway extension: was this a cache hit? |
| `gateway_latency_ms` | `float` | 🔌 Gateway extension: end-to-end latency |

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

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `input` | `string \| list[string]` | ✅ | — | Text(s) to embed |
| `model` | `string` | ❌ | `"default"` | Embedding model |

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

| Param | Type | Default | Options |
|-------|------|---------|---------|
| `period` | `string` | `"today"` | `today`, `week`, `month`, `all` |

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

| Status | Type | When |
|--------|------|------|
| `400` | `bad_request` | Malformed JSON, missing fields |
| `401` | `authentication_error` | Invalid or missing API key |
| `422` | `validation_error` | Pydantic validation failure |
| `429` | `rate_limit_error` | Rate limit exceeded |
| `500` | `internal_error` | Unexpected server error |
| `502` | `provider_error` | LLM provider returned error |
| `503` | `service_unavailable` | All providers failed (fallback exhausted) |

---

## 8. Gateway Extensions

These fields are **not part of the OpenAI spec** but are added by the gateway for observability:

### Request Extensions

| Field | Type | Description |
|-------|------|-------------|
| `bypass_cache` | `bool` | Skip cache lookup (force fresh LLM call) |
| `preferred_provider` | `string` | Override routing strategy for this request |

### Response Extensions

| Field | Type | Description |
|-------|------|-------------|
| `cost` | `CostInfo` | Estimated cost, provider, model, cached flag |
| `cache_hit` | `bool` | Whether the response came from cache |
| `gateway_latency_ms` | `float` | Total gateway processing time |

### Response Headers

| Header | Description |
|--------|-------------|
| `X-Request-ID` | Unique request identifier for tracing |
| `X-Gateway-Latency-Ms` | Processing time in milliseconds |

---

## 9. Cross-References

| Topic | Document |
|-------|----------|
| Architecture overview | [Architecture](architecture.md) |
| Pydantic model definitions | [Pydantic Models Reference](../reference/pydantic-models.md) |
| Caching behavior | [Caching Deep Dive](../ai-engineering/caching-deep-dive.md) |
| Rate limiting algorithm | [Rate Limiting Deep Dive](../ai-engineering/rate-limiting-deep-dive.md) |
| Cost tracking schema | [Cost Tracking Deep Dive](../ai-engineering/cost-tracking-deep-dive.md) |
| Setup instructions | [Getting Started](../setup-and-tooling/getting-started.md) |
