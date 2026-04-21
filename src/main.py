"""
AI Gateway — FastAPI Application Entry Point

Central LLM proxy that routes, caches, rate-limits, and tracks costs
for all LLM calls across AWS Bedrock, Azure OpenAI, and Local (Ollama).

Run with:
    poetry run start
    # or
    uvicorn src.main:app --reload --port 8100
"""

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from src.config import get_settings
from src.gateway.cache import create_cache
from src.gateway.cost_tracker import create_cost_tracker
from src.gateway.rate_limiter import create_rate_limiter
from src.gateway.router import create_router
from src.middleware.auth import APIKeyMiddleware
from src.middleware.logging import RequestLoggingMiddleware
from src.routes import completions, embeddings, health, models, usage


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Startup:
        - Load settings
        - Initialise LLM router (LiteLLM)
        - Initialise semantic cache (Redis / in-memory)
        - Initialise rate limiter (Redis / in-memory)
        - Initialise cost tracker (PostgreSQL / in-memory)

    Shutdown:
        - Close Redis connections
        - Close database connections
    """
    settings = get_settings()

    # --- Startup ---
    logger.info("=" * 60)
    logger.info(f"Starting {settings.app_name}")
    logger.info(f"  Provider:  {settings.cloud_provider.value}")
    logger.info(f"  Routing:   {settings.routing_strategy.value}")
    logger.info(f"  Cache:     {'enabled' if settings.cache_enabled else 'disabled'}")
    logger.info(f"  Rate Limit: {'enabled' if settings.rate_limit_enabled else 'disabled'}")
    logger.info(f"  Cost Track: {'enabled' if settings.cost_tracking_enabled else 'disabled'}")
    logger.info(f"  LangFuse:  {'enabled' if settings.langfuse_enabled else 'disabled'}")
    logger.info("=" * 60)

    # Store settings on app state (dependency injection)
    app.state.settings = settings

    # Initialise gateway components
    app.state.router = create_router(settings)
    app.state.cache = create_cache(settings)
    app.state.rate_limiter = create_rate_limiter(settings)
    app.state.cost_tracker = create_cost_tracker(settings)

    logger.info("All gateway components initialised")

    yield

    # --- Shutdown ---
    logger.info("Shutting down gateway...")


def create_app() -> FastAPI:
    """Application factory — creates and configures the FastAPI app."""
    settings = get_settings()

    app = FastAPI(
        title="AI Gateway",
        description=(
            "Central LLM proxy — routes requests to AWS Bedrock, Azure OpenAI, "
            "or Local (Ollama). Provides semantic caching, rate limiting, "
            "cost tracking, and observability."
        ),
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # --- Middleware (order matters: first added = last executed) ---
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestLoggingMiddleware)

    if settings.api_keys_enabled:
        app.add_middleware(APIKeyMiddleware)

    # --- Routes ---
    app.include_router(health.router)
    app.include_router(completions.router)
    app.include_router(embeddings.router)
    app.include_router(models.router)
    app.include_router(usage.router)

    return app


# Module-level app instance (for uvicorn src.main:app)
app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=get_settings().port,
        reload=True,
    )
