"""Request ID injection, security headers, structured logging, and rate-limit helpers."""

from __future__ import annotations

import time
import uuid

from fastapi import FastAPI, Request, Response
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware

_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'",
}


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Injects X-Request-ID, enforces security headers, and logs every request."""

    async def dispatch(self, request: Request, call_next: object) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        t0 = time.monotonic()
        response: Response = await call_next(request)  # type: ignore[operator]
        latency_ms = round((time.monotonic() - t0) * 1000, 1)

        response.headers["X-Request-ID"] = request_id

        # Apply security headers (skip for /docs, /openapi.json, /metrics)
        if not request.url.path.startswith(("/docs", "/openapi", "/redoc")):
            for header, value in _SECURITY_HEADERS.items():
                response.headers.setdefault(header, value)

        logger.info(
            "Request handled",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            latency_ms=latency_ms,
        )
        return response


def setup_rate_limiter(app: FastAPI) -> None:
    """Attach a slowapi rate limiter to the FastAPI application.

    The limiter uses the client's remote address as the key.  The limit is
    configured via ``settings.rate_limit_per_minute``.
    """
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from slowapi.util import get_remote_address

    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
