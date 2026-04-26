"""
AI Gateway — Chat Completions Endpoint

POST /v1/chat/completions — OpenAI-compatible chat completion proxy.

Request flow:
1. Validate request body (Pydantic)
2. Check API key authentication (if enabled)
3. Check rate limit (Redis)
4. Check semantic cache (Redis)
5. Route to LLM provider (LiteLLM)
6. Store in cache
7. Log usage (PostgreSQL)
8. Return OpenAI-compatible response + gateway extensions (cost, cache_hit, latency)

This is the heart of the gateway — every LLM call goes through here.
"""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from src.models import (
    ChatChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    CostInfo,
    UsageInfo,
)

router = APIRouter(prefix="/v1", tags=["completions"])


@router.post("/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(
    request: Request,
    body: ChatCompletionRequest,
) -> ChatCompletionResponse:
    """Process a chat completion request through the gateway pipeline.

    Pipeline: Auth → Rate Limit → Cache Check → LLM Route → Cache Store → Log Usage
    """
    request_id = uuid.uuid4().hex[:12]
    start = time.perf_counter()

    settings = request.app.state.settings
    llm_router = request.app.state.router
    cache = request.app.state.cache
    rate_limiter = request.app.state.rate_limiter
    cost_tracker = request.app.state.cost_tracker

    # Extract API key (from header or use default)
    api_key = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not api_key:
        api_key = settings.master_api_key

    # --- Step 1: Rate Limit Check ---
    allowed, rate_info = await rate_limiter.check(api_key)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "rate_limit_exceeded",
                "message": f"Rate limit exceeded. Retry in {rate_info['reset_in_seconds']}s",
                "limit": rate_info["limit"],
                "remaining": 0,
            },
        )

    # --- Step 2: Cache Check ---
    messages_dicts = [{"role": m.role, "content": m.content} for m in body.messages]

    if not body.bypass_cache:
        cached_response = await cache.get(messages_dicts)
        if cached_response:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.info(f"[{request_id}] Cache HIT — returning cached response ({elapsed_ms:.0f}ms)")

            # Log the cached request
            await cost_tracker.log_request(
                request_id=request_id,
                api_key=api_key,
                model=cached_response.get("model", "cached"),
                provider="cache",
                prompt_tokens=0,
                completion_tokens=0,
                estimated_cost_usd=0.0,
                latency_ms=elapsed_ms,
                cached=True,
            )

            return ChatCompletionResponse(
                id=f"chatcmpl-{request_id}",
                model=cached_response.get("model", "cached"),
                choices=[
                    ChatChoice(
                        message=ChatMessage(
                            role="assistant",
                            content=cached_response.get("content", ""),
                        )
                    )
                ],
                usage=UsageInfo(**cached_response.get("usage", {})),
                cost=CostInfo(
                    estimated_cost_usd=0.0,
                    provider="cache",
                    model=cached_response.get("model", "cached"),
                    cached=True,
                ),
                cache_hit=True,
                gateway_latency_ms=round(elapsed_ms, 2),
            )

    # --- Step 3: Route to LLM ---
    try:
        result = await llm_router.chat_completion(
            messages=messages_dicts,
            model=body.model,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            preferred_provider=body.preferred_provider,
        )
    except Exception as e:
        logger.error(f"[{request_id}] LLM routing failed: {e}")
        raise HTTPException(
            status_code=502,
            detail={
                "error": "llm_provider_error",
                "message": f"All LLM providers failed: {str(e)}",
                "request_id": request_id,
            },
        ) from e

    response_obj = result["response"]
    provider = result["provider"]
    model = result["model"]
    result["latency_ms"]

    # Extract response content
    content = response_obj.choices[0].message.content
    usage = response_obj.usage

    # Estimate cost using LiteLLM
    try:
        from litellm import completion_cost

        cost_usd = completion_cost(completion_response=response_obj)
    except Exception:
        cost_usd = 0.0

    # --- Step 4: Store in Cache ---
    cache_entry = {
        "content": content,
        "model": model,
        "usage": {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        },
    }
    await cache.put(messages_dicts, cache_entry)

    # --- Step 5: Log Usage ---
    elapsed_ms = (time.perf_counter() - start) * 1000
    await cost_tracker.log_request(
        request_id=request_id,
        api_key=api_key,
        model=model,
        provider=provider,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        estimated_cost_usd=cost_usd,
        latency_ms=elapsed_ms,
        cached=False,
    )

    logger.info(
        f"[{request_id}] Completed: provider={provider}, model={model}, "
        f"tokens={usage.total_tokens}, cost=${cost_usd:.6f}, latency={elapsed_ms:.0f}ms"
    )

    return ChatCompletionResponse(
        id=f"chatcmpl-{request_id}",
        model=model,
        choices=[
            ChatChoice(
                message=ChatMessage(role="assistant", content=content),
            )
        ],
        usage=UsageInfo(
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
        ),
        cost=CostInfo(
            estimated_cost_usd=round(cost_usd, 6),
            provider=provider,
            model=model,
            cached=False,
        ),
        cache_hit=False,
        gateway_latency_ms=round(elapsed_ms, 2),
    )
