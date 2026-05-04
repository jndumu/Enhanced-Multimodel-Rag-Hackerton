"""Request ID injection, structured logging, and rate-limit helpers."""

from __future__ import annotations

import time
import uuid

from fastapi import FastAPI, Request, Response
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: object) -> Response:
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        t0 = time.monotonic()
        response: Response = await call_next(request)  # type: ignore[operator]
        latency_ms = round((time.monotonic() - t0) * 1000, 1)

        response.headers["X-Request-ID"] = request_id
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
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from slowapi.util import get_remote_address

    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
