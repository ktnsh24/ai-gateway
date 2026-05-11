# API Reference — AI Gateway

> OpenAI-compatible endpoints exposed by ai-gateway.

---

## Table of Contents

1. [Base URL and Auth](#1-base-url-and-auth)
2. [POST /v1/chat/completions](#2-post-v1chatcompletions)
3. [POST /v1/embeddings](#3-post-v1embeddings)
4. [GET /v1/models](#4-get-v1models)
5. [GET /v1/usage](#5-get-v1usage)
6. [GET /health](#6-get-health)
7. [Common Status Codes](#7-common-status-codes)

---

## 1. Base URL and Auth

- Local base URL: `http://localhost:8100`
- Auth header format: `Authorization: Bearer <API_KEY>`
- If auth is disabled (`API_KEYS_ENABLED=false`), requests can omit the header.

---

## 2. POST /v1/chat/completions

OpenAI-compatible chat completion proxy with gateway extensions.

### 2.1 Request Body

```json
{
  "model": "default",
  "messages": [
    {"role": "user", "content": "What is machine learning?"}
  ],
  "temperature": 0.7,
  "max_tokens": 300,
  "stream": false,
  "top_p": 1.0,
  "bypass_cache": false,
  "preferred_provider": "aws"
}
```

### 2.2 Response Body

```json
{
  "id": "chatcmpl-abc123def456",
  "object": "chat.completion",
  "created": 1714630000,
  "model": "anthropic.claude-3-5-sonnet-20241022-v2:0",
  "choices": [
    {
      "index": 0,
      "message": {"role": "assistant", "content": "Machine learning is..."},
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 12,
    "completion_tokens": 44,
    "total_tokens": 56
  },
  "cost": {
    "estimated_cost_usd": 0.00042,
    "provider": "aws",
    "model": "anthropic.claude-3-5-sonnet-20241022-v2:0",
    "cached": false
  },
  "cache_hit": false,
  "gateway_latency_ms": 842.19
}
```

### 2.3 Notes

- Pipeline: rate-limit check -> cache check -> provider route -> cache store -> cost log.
- `bypass_cache=true` forces provider call.
- `preferred_provider` can force `aws`, `azure`, or `local` if available.

---

## 3. POST /v1/embeddings

OpenAI-compatible embeddings proxy.

### 3.1 Request Body

```json
{
  "model": "default",
  "input": ["Machine learning", "Cloud computing"],
  "encoding_format": "float"
}
```

### 3.2 Response Body

```json
{
  "object": "list",
  "data": [
    {"object": "embedding", "embedding": [0.01, -0.02], "index": 0},
    {"object": "embedding", "embedding": [0.11, -0.07], "index": 1}
  ],
  "model": "text-embedding-3-small",
  "usage": {
    "prompt_tokens": 8,
    "completion_tokens": 0,
    "total_tokens": 8
  },
  "cost": {
    "estimated_cost_usd": 0.00001,
    "provider": "azure",
    "model": "text-embedding-3-small",
    "cached": false
  },
  "gateway_latency_ms": 203.11
}
```

### 3.3 Notes

- No cache write/read for embeddings endpoint.
- Embeddings endpoint is still rate-limited and cost-logged.

---

## 4. GET /v1/models

List available models across configured providers.

### 4.1 Response Body

```json
{
  "object": "list",
  "data": [
    {
      "id": "anthropic.claude-3-5-sonnet-20241022-v2:0",
      "object": "model",
      "created": 1714630000,
      "owned_by": "aws-bedrock",
      "provider": "aws",
      "capabilities": ["chat"]
    }
  ]
}
```

---

## 5. GET /v1/usage

Return usage dashboard metrics for an API key and period.

### 5.1 Query Parameters

- `period`: `today` (default), `week`, `month`

### 5.2 Example

`GET /v1/usage?period=today`

### 5.3 Response Body

```json
{
  "summary": {
    "period": "today",
    "total_requests": 31,
    "total_tokens": 18420,
    "total_cost_usd": 0.1324,
    "cache_hit_rate": 0.29,
    "avg_latency_ms": 412.7,
    "requests_by_model": {
      "anthropic.claude-3-5-sonnet-20241022-v2:0": 22,
      "llama3.2": 9
    },
    "cost_by_provider": {
      "aws": 0.1280,
      "local": 0.0044
    }
  },
  "api_key": "gw-dev-k..."
}
```

---

## 6. GET /health

Service liveness and dependency snapshot.

### 6.1 Response Body

```json
{
  "status": "healthy",
  "version": "0.1.0",
  "provider": "local",
  "redis_connected": true,
  "database_connected": true,
  "langfuse_connected": false,
  "models_available": [
    "llama3.2",
    "nomic-embed-text"
  ]
}
```

---

## 7. Common Status Codes

| Status | Meaning | Common causes |
|---|---|---|
| 200 | Success | Normal operation |
| 400 | Bad request | Invalid payload shape or values |
| 401 | Unauthorized | API key missing/invalid when auth is enabled |
| 429 | Rate limit exceeded | Too many requests per minute for API key |
| 502 | Upstream provider failure | LLM provider timeout/failure, all fallbacks exhausted |
| 500 | Internal gateway error | Unexpected failure in route/middleware |
