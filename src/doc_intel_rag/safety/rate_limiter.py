"""Per-API-key rate-limit helpers for FastAPI endpoints.

Integrates with ``slowapi`` (Starlette middleware) to enforce per-key limits
defined by ``settings.rate_limit_per_minute``.

Usage inside a route::

    from doc_intel_rag.safety.rate_limiter import limiter

    @router.post("/generate")
    @limiter.limit("{rate_limit_per_minute}/minute")
    async def generate(request: Request, ...):
        ...

The key function defaults to the ``X-API-Key`` header value so each client
gets its own independent counter.  Falls back to the remote IP address when
no API key is present.
"""

from __future__ import annotations

from typing import Callable

from starlette.requests import Request


def _api_key_or_ip(request: Request) -> str:
    """Return the ``X-API-Key`` header or the client IP for rate-key bucketing.

    Args:
        request: The incoming Starlette request.

    Returns:
        The API key string if present, otherwise the client host IP.
    """
    return request.headers.get("X-API-Key") or request.client.host or "unknown"


def get_limiter() -> "object":
    """Construct and return a ``slowapi.Limiter`` keyed on ``X-API-Key``.

    The limiter is intentionally constructed lazily so the ``slowapi``
    dependency is only imported when rate limiting is actually configured,
    keeping startup cheap in environments where ``slowapi`` is absent.

    Returns:
        A configured ``slowapi.Limiter`` instance.

    Raises:
        ImportError: If ``slowapi`` is not installed.
    """
    from slowapi import Limiter

    return Limiter(key_func=_api_key_or_ip, default_limits=[])


def rate_limit_decorator(rate: str) -> Callable:  # type: ignore[type-arg]
    """Return a ``slowapi`` limit decorator for the given rate string.

    Args:
        rate: A rate-limit expression understood by ``limits`` (e.g. ``"60/minute"``).

    Returns:
        A route decorator that enforces the specified rate limit.

    Example::

        @router.post("/search")
        @rate_limit_decorator("60/minute")
        async def search(request: Request, ...):
            ...
    """
    from slowapi import Limiter

    limiter = Limiter(key_func=_api_key_or_ip)
    return limiter.limit(rate)
