"""
AI Gateway — API Key Authentication Middleware

Validates Bearer tokens in the Authorization header.
In production, keys are stored in a database with per-key rate limits and model access.
For development, a master key is accepted.

Header format:
    Authorization: Bearer gw-dev-key-12345
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.config import get_settings

# Paths that don't require authentication
PUBLIC_PATHS = {"/health", "/docs", "/redoc", "/openapi.json"}


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Validate API key from Authorization header.

    Skips authentication for health checks and docs.
    In development mode, accepts the master API key.
    In production, would look up keys in a database.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Skip auth for public paths
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        settings = get_settings()

        # Extract API key
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={
                    "error": "authentication_required",
                    "message": "Missing Authorization header. Use: Bearer <api-key>",
                },
            )

        api_key = auth_header.replace("Bearer ", "").strip()
        if not api_key:
            return JSONResponse(
                status_code=401,
                content={
                    "error": "invalid_api_key",
                    "message": "API key is empty",
                },
            )

        # Validate key (development: accept master key)
        valid_keys = {settings.master_api_key}
        if api_key not in valid_keys:
            return JSONResponse(
                status_code=403,
                content={
                    "error": "forbidden",
                    "message": "Invalid API key",
                },
            )

        return await call_next(request)
