"""
AI Gateway — Pydantic Request/Response Models

OpenAI-compatible API contract. Any client that speaks the OpenAI API
can call this gateway without modification.

See: https://platform.openai.com/docs/api-reference/chat/create
"""

from __future__ import annotations

import time
import uuid
from enum import Enum

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Chat Completions
# ---------------------------------------------------------------------------
class ChatMessage(BaseModel):
    """A single message in a conversation."""

    role: str = Field(..., description="Role: system, user, or assistant")
    content: str = Field(..., description="Message content")


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible chat completion request."""

    model: str = Field(
        default="default",
        description="Model identifier. Use 'default' to let the gateway choose.",
    )
    messages: list[ChatMessage] = Field(..., description="Conversation messages")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Sampling temperature")
    max_tokens: int | None = Field(default=None, description="Max tokens in response")
    stream: bool = Field(default=False, description="Enable streaming response")
    top_p: float = Field(default=1.0, ge=0.0, le=1.0, description="Nucleus sampling")

    # --- Gateway-specific fields (not in OpenAI spec) ---
    bypass_cache: bool = Field(default=False, description="Skip semantic cache for this request")
    preferred_provider: str | None = Field(
        default=None,
        description="Force a specific provider: aws, azure, local",
    )


class ChatChoice(BaseModel):
    """A single completion choice."""

    index: int = 0
    message: ChatMessage
    finish_reason: str = "stop"


class UsageInfo(BaseModel):
    """Token usage information."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class CostInfo(BaseModel):
    """Cost estimation for this request (gateway extension)."""

    estimated_cost_usd: float = 0.0
    provider: str = ""
    model: str = ""
    cached: bool = False


class ChatCompletionResponse(BaseModel):
    """OpenAI-compatible chat completion response."""

    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid.uuid4().hex[:12]}")
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str = ""
    choices: list[ChatChoice] = []
    usage: UsageInfo = Field(default_factory=UsageInfo)

    # --- Gateway extensions ---
    cost: CostInfo = Field(default_factory=CostInfo)
    cache_hit: bool = False
    gateway_latency_ms: float = 0.0


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------
class EmbeddingRequest(BaseModel):
    """OpenAI-compatible embedding request."""

    model: str = Field(default="default", description="Embedding model identifier")
    input: str | list[str] = Field(..., description="Text(s) to embed")
    encoding_format: str = Field(default="float", description="Output format: float or base64")


class EmbeddingData(BaseModel):
    """A single embedding result."""

    object: str = "embedding"
    embedding: list[float] = []
    index: int = 0


class EmbeddingResponse(BaseModel):
    """OpenAI-compatible embedding response."""

    object: str = "list"
    data: list[EmbeddingData] = []
    model: str = ""
    usage: UsageInfo = Field(default_factory=UsageInfo)

    # --- Gateway extensions ---
    cost: CostInfo = Field(default_factory=CostInfo)
    gateway_latency_ms: float = 0.0


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class ModelPermission(BaseModel):
    """Model permission info."""

    id: str = "modelperm-default"
    allow_create_engine: bool = False


class ModelInfo(BaseModel):
    """Information about an available model."""

    id: str
    object: str = "model"
    created: int = Field(default_factory=lambda: int(time.time()))
    owned_by: str = ""
    provider: str = ""
    capabilities: list[str] = Field(default_factory=lambda: ["chat"])


class ModelListResponse(BaseModel):
    """List of available models."""

    object: str = "list"
    data: list[ModelInfo] = []


# ---------------------------------------------------------------------------
# Usage & Cost Dashboard
# ---------------------------------------------------------------------------
class UsagePeriod(str, Enum):
    """Time period for usage queries."""

    TODAY = "today"
    WEEK = "week"
    MONTH = "month"


class UsageSummary(BaseModel):
    """Usage summary for a time period."""

    period: str
    total_requests: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    cache_hit_rate: float = 0.0
    avg_latency_ms: float = 0.0
    requests_by_model: dict[str, int] = Field(default_factory=dict)
    cost_by_provider: dict[str, float] = Field(default_factory=dict)


class UsageResponse(BaseModel):
    """Usage dashboard response."""

    summary: UsageSummary
    api_key: str = ""  # Masked key identifier


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
class HealthStatus(BaseModel):
    """Health check response."""

    status: str = "healthy"
    version: str = "0.1.0"
    provider: str = ""
    redis_connected: bool = False
    database_connected: bool = False
    langfuse_connected: bool = False
    models_available: list[str] = []


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------
class GatewayError(BaseModel):
    """Standardised error response."""

    error: str
    message: str
    status_code: int = 500
    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
