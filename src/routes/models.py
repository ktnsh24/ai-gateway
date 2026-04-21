"""
AI Gateway — Models Endpoint

GET /v1/models — List available models across all configured providers.
OpenAI-compatible response format.
"""

from fastapi import APIRouter, Request

from src.models import ModelInfo, ModelListResponse

router = APIRouter(prefix="/v1", tags=["models"])


@router.get("/models", response_model=ModelListResponse)
async def list_models(request: Request) -> ModelListResponse:
    """List all available models from configured providers."""
    llm_router = request.app.state.router
    raw_models = llm_router.list_models()

    models = [
        ModelInfo(
            id=m["id"],
            owned_by=m["owned_by"],
            provider=m["provider"],
            capabilities=m.get("capabilities", ["chat"]),
        )
        for m in raw_models
    ]

    return ModelListResponse(data=models)
