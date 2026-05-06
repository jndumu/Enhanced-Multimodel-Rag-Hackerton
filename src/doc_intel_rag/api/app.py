"""FastAPI application factory with lifespan, exception handlers, and middleware."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from doc_intel_rag.api.middleware import RequestIDMiddleware, setup_rate_limiter
from doc_intel_rag.config import get_settings
from doc_intel_rag.exceptions import (
    DocIntelError,
    HarmfulContentError,
    InjectionDetectedError,
    PIIDetectedError,
    SafetyError,
)
from doc_intel_rag.logging_config import setup_logging


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(settings)

    logger.info("Starting doc-intel-rag", version="0.1.0")

    from doc_intel_rag.api.dependencies import init_singletons
    await init_singletons(settings)

    if settings.otel_endpoint:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            FastAPIInstrumentor.instrument_app(app)
        except ImportError:
            logger.warning("FastAPI OTel instrumentation not available")

    yield

    logger.info("Shutting down doc-intel-rag")
    from doc_intel_rag.api.dependencies import shutdown_singletons
    await shutdown_singletons()


def _register_exception_handlers(app: FastAPI) -> None:
    """Map domain exceptions to consistent JSON HTTP error responses."""

    @app.exception_handler(PIIDetectedError)
    async def _pii_handler(request: Request, exc: PIIDetectedError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error": "pii_detected", "detail": str(exc), "entity_types": exc.entity_types},
        )

    @app.exception_handler(InjectionDetectedError)
    async def _injection_handler(request: Request, exc: InjectionDetectedError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error": "injection_detected", "detail": str(exc)},
        )

    @app.exception_handler(HarmfulContentError)
    async def _harmful_handler(request: Request, exc: HarmfulContentError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error": "harmful_content", "detail": str(exc)},
        )

    @app.exception_handler(SafetyError)
    async def _safety_handler(request: Request, exc: SafetyError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error": "safety_violation", "detail": str(exc)},
        )

    @app.exception_handler(DocIntelError)
    async def _domain_handler(request: Request, exc: DocIntelError) -> JSONResponse:
        logger.error("Domain error", error_type=type(exc).__name__, detail=str(exc))
        return JSONResponse(
            status_code=500,
            content={"error": type(exc).__name__, "detail": str(exc)},
        )

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception", error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"error": "internal_server_error", "detail": "An unexpected error occurred"},
        )


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application.

    Registers all middleware, exception handlers, and versioned routes.
    """
    settings = get_settings()

    app = FastAPI(
        title="doc-intel-rag",
        description="Production-grade multimodal RAG with graph intelligence",
        version="0.1.0",
        lifespan=_lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Prometheus metrics
    try:
        from prometheus_fastapi_instrumentator import Instrumentator
        Instrumentator().instrument(app).expose(app)
    except ImportError:
        pass

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request ID + security headers + structured logging
    app.add_middleware(RequestIDMiddleware)

    # Rate limiting
    setup_rate_limiter(app)

    # Domain exception → HTTP response mapping
    _register_exception_handlers(app)

    # Routes
    from doc_intel_rag.api.routes.admin import router as admin_router
    from doc_intel_rag.api.routes.generate import router as generate_router
    from doc_intel_rag.api.routes.graph import router as graph_router
    from doc_intel_rag.api.routes.health import router as health_router
    from doc_intel_rag.api.routes.ingest import router as ingest_router
    from doc_intel_rag.api.routes.search import router as search_router

    app.include_router(health_router)
    app.include_router(ingest_router, prefix="/v1")
    app.include_router(search_router, prefix="/v1")
    app.include_router(generate_router, prefix="/v1")
    app.include_router(graph_router, prefix="/v1")
    app.include_router(admin_router, prefix="/v1")

    return app


app = create_app()
