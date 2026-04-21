"""
AI Gateway — Request Logging Middleware

Logs every request with timing, status code, and path.
Same pattern as V1's logging middleware.
"""

from __future__ import annotations

import time
import uuid

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every HTTP request with timing information."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = uuid.uuid4().hex[:12]
        start = time.perf_counter()

        # Add request_id to request state
        request.state.request_id = request_id

        response = await call_next(request)

        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            f"[{request_id}] {request.method} {request.url.path} "
            f"→ {response.status_code} ({elapsed_ms:.0f}ms)"
        )

        # Add gateway headers
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Gateway-Latency-Ms"] = f"{elapsed_ms:.0f}"

        return response
