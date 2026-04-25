# Pydantic Models Reference — AI Gateway

> **File:** `src/models.py`
>
> **Pattern:** OpenAI-compatible request/response models with gateway extensions

---

## Table of Contents

1. [Request Models](#1-request-models)
2. [Response Models](#2-response-models)
3. [Gateway Extensions](#3-gateway-extensions)
4. [Config Enums](#4-config-enums)
5. [Internal Models](#5-internal-models)

---

## 1. Request Models

### ChatCompletionRequest

```python
class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible chat completion request with gateway extensions."""

    messages: list[Message]           # Required: list of chat messages
    model: str = "default"            # Model name (or "default" for provider default)
    temperature: float = 0.7          # Sampling temperature (0.0-2.0)
    max_tokens: int = 1024            # Maximum tokens in response

    # Gateway extensions (not part of OpenAI spec)
    bypass_cache: bool = False        # Skip cache lookup
    preferred_provider: str | None = None  # Override routing strategy
```

### Message

```python
class Message(BaseModel):
    """A single message in a chat conversation."""

    role: str                         # "system", "user", or "assistant"
    content: str                      # Message content
```

### EmbeddingRequest

```python
class EmbeddingRequest(BaseModel):
    """OpenAI-compatible embedding request."""

    input: str | list[str]            # Text(s) to embed
    model: str = "default"            # Embedding model
```

---

## 2. Response Models

### ChatCompletionResponse

```python
class ChatCompletionResponse(BaseModel):
    """OpenAI-compatible chat completion response with gateway extensions."""

    id: str                           # Unique completion ID (e.g., "chatcmpl-abc123")
    object: str = "chat.completion"   # Always "chat.completion"
    created: int                      # Unix timestamp
    model: str                        # Model used (LiteLLM format)
    choices: list[Choice]             # Completion choices
    usage: Usage                      # Token counts

    # Gateway extensions
    cost: CostInfo | None = None      # Cost breakdown
    cache_hit: bool = False           # Whether from cache
    gateway_latency_ms: float | None = None  # Gateway processing time
```

### Choice

```python
class Choice(BaseModel):
    """A single completion choice."""

    index: int = 0
    message: Message
    finish_reason: str = "stop"       # "stop", "length", "content_filter"
```

### Usage

```python
class Usage(BaseModel):
    """Token usage statistics."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
```

### EmbeddingResponse

```python
class EmbeddingResponse(BaseModel):
    """OpenAI-compatible embedding response."""

    object: str = "list"
    data: list[EmbeddingData]
    model: str
    usage: Usage
```

### EmbeddingData

```python
class EmbeddingData(BaseModel):
    """A single embedding result."""

    object: str = "embedding"
    index: int = 0
    embedding: list[float]            # Vector (768 or 1536 dimensions)
```

---

## 3. Gateway Extensions

These models extend the OpenAI spec with gateway-specific information.

### CostInfo

```python
class CostInfo(BaseModel):
    """Cost breakdown for a single request."""

    estimated_cost_usd: float = 0.0   # Estimated cost in USD
    provider: str = ""                # Provider name (aws, azure, local)
    model: str = ""                   # Model name
    cached: bool = False              # Whether response came from cache
```

### GatewayError

```python
class GatewayError(BaseModel):
    """Standard error response."""

    error: ErrorDetail

class ErrorDetail(BaseModel):
    message: str                      # Human-readable error message
    type: str                         # Error type (rate_limit_error, etc.)
    code: int                         # HTTP status code
```

---

## 4. Config Enums

### CloudProvider

```python
class CloudProvider(str, Enum):
    AWS = "aws"
    AZURE = "azure"
    LOCAL = "local"
```

### RoutingStrategy

```python
class RoutingStrategy(str, Enum):
    SINGLE = "single"                 # Route to one provider
    FALLBACK = "fallback"             # Try providers in order
    COST = "cost"                     # Route to cheapest
    ROUND = "round"                   # Round-robin distribution
```

### AppEnvironment

```python
class AppEnvironment(str, Enum):
    DEV = "dev"
    STG = "stg"
    PRD = "prd"
```

---

## 5. Internal Models

### HealthStatus

```python
class HealthStatus(BaseModel):
    """Health check response."""

    status: str                       # "healthy", "degraded", "unhealthy"
    version: str                      # App version
    provider: str                     # Current cloud provider
    components: dict[str, str]        # Component → status mapping
```

### ModelInfo / ModelListResponse

```python
class ModelInfo(BaseModel):
    """Information about an available model."""

    id: str                           # Model identifier
    object: str = "model"
    provider: str                     # Provider (aws, azure, local)
    model_type: str                   # "chat" or "embedding"

class ModelListResponse(BaseModel):
    """List of available models."""

    object: str = "list"
    data: list[ModelInfo]
```

### UsageSummary / UsageResponse

```python
class UsageSummary(BaseModel):
    """Aggregated usage statistics."""

    period: str                       # "today", "week", "month", "all"
    total_requests: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    cache_hit_rate: float = 0.0
    by_model: dict[str, dict] = {}    # Per-model breakdown
    by_provider: dict[str, dict] = {} # Per-provider breakdown

class UsageResponse(BaseModel):
    """Usage dashboard response."""

    data: UsageSummary
```

---

## Cross-References

| Topic | Document |
|-------|----------|
| API specification | [API Contract](../architecture-and-design/api-contract.md) |
| Architecture | [Architecture](../architecture-and-design/architecture.md) |
| Config settings | [Getting Started](../setup-and-tooling/getting-started.md) |
