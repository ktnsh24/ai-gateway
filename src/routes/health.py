"""
AI Gateway — Health Endpoint

GET /health — returns service status, connectivity checks, and available models.
Same pattern as V1's health route, but also checks Redis and PostgreSQL.
"""

from fastapi import APIRouter, Request

from src.models import HealthStatus

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthStatus)
async def health_check(request: Request) -> HealthStatus:
    """Check service health, Redis connectivity, database connectivity, and list available models."""
    settings = request.app.state.settings
    router_instance = request.app.state.router

    # Check Redis
    redis_ok = False
    try:
        cache = request.app.state.cache
        stats = await cache.stats()
        redis_ok = stats.get("enabled", True)  # NoCache returns enabled=False
    except Exception:
        pass

    # Check PostgreSQL
    db_ok = False
    try:
        cost_tracker = request.app.state.cost_tracker
        await cost_tracker.get_usage_summary(period="today")
        db_ok = True
    except Exception:
        pass

    # Available models
    models = [m["id"] for m in router_instance.list_models()]

    return HealthStatus(
        status="healthy",
        version="0.1.0",
        provider=settings.cloud_provider.value,
        redis_connected=redis_ok,
        database_connected=db_ok,
        langfuse_connected=settings.langfuse_enabled,
        models_available=models,
    )
