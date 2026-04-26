"""
AI Gateway — Embeddings Endpoint

POST /v1/embeddings — OpenAI-compatible embedding proxy.

Similar pipeline to chat completions but simpler (no conversation context).
Embeddings are used by:
- Vector stores (document ingestion + search)
- Semantic cache (computing similarity between prompts)
- Classification tasks (input categorisation)
"""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from src.models import (
    CostInfo,
    EmbeddingData,
    EmbeddingRequest,
    EmbeddingResponse,
    UsageInfo,
)

router = APIRouter(prefix="/v1", tags=["embeddings"])


@router.post("/embeddings", response_model=EmbeddingResponse)
async def create_embeddings(
    request: Request,
    body: EmbeddingRequest,
) -> EmbeddingResponse:
    """Generate embeddings through the gateway.

    Pipeline: Auth → Rate Limit → Route to Provider → Log Usage
    (No caching for embeddings — they're used to BUILD the cache)
    """
    request_id = uuid.uuid4().hex[:12]
    start = time.perf_counter()

    llm_router = request.app.state.router
    rate_limiter = request.app.state.rate_limiter
    cost_tracker = request.app.state.cost_tracker
    settings = request.app.state.settings

    api_key = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not api_key:
        api_key = settings.master_api_key

    # Rate limit
    allowed, rate_info = await rate_limiter.check(api_key)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "rate_limit_exceeded",
                "message": f"Retry in {rate_info['reset_in_seconds']}s",
            },
        )

    # Route to provider
    try:
        result = await llm_router.embedding(
            input_text=body.input,
            model=body.model,
        )
    except Exception as e:
        logger.error(f"[{request_id}] Embedding failed: {e}")
        raise HTTPException(
            status_code=502,
            detail={"error": "embedding_provider_error", "message": str(e)},
        ) from e

    response_obj = result["response"]
    provider = result["provider"]
    model = result["model"]

    # Extract embeddings
    data = []
    for i, item in enumerate(response_obj.data):
        data.append(EmbeddingData(
            embedding=item["embedding"],
            index=i,
        ))

    usage = response_obj.usage

    # Cost estimation
    try:
        from litellm import completion_cost

        cost_usd = completion_cost(completion_response=response_obj)
    except Exception:
        cost_usd = 0.0

    elapsed_ms = (time.perf_counter() - start) * 1000

    # Log usage
    await cost_tracker.log_request(
        request_id=request_id,
        api_key=api_key,
        model=model,
        provider=provider,
        prompt_tokens=usage.prompt_tokens if hasattr(usage, "prompt_tokens") else 0,
        completion_tokens=0,
        estimated_cost_usd=cost_usd,
        latency_ms=elapsed_ms,
    )

    logger.info(f"[{request_id}] Embedding: provider={provider}, latency={elapsed_ms:.0f}ms")

    return EmbeddingResponse(
        data=data,
        model=model,
        usage=UsageInfo(
            prompt_tokens=getattr(usage, "prompt_tokens", 0),
            total_tokens=getattr(usage, "total_tokens", 0),
        ),
        cost=CostInfo(
            estimated_cost_usd=round(cost_usd, 6),
            provider=provider,
            model=model,
        ),
        gateway_latency_ms=round(elapsed_ms, 2),
    )
