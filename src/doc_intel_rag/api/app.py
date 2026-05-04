"""FastAPI application factory with lifespan."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from doc_intel_rag.api.middleware import RequestIDMiddleware, setup_rate_limiter
from doc_intel_rag.config import get_settings
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


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="doc-intel-rag",
        description="Production-grade multimodal RAG with graph intelligence",
        version="0.1.0",
        lifespan=_lifespan,
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

    # Request ID + logging
    app.add_middleware(RequestIDMiddleware)

    # Rate limiting
    setup_rate_limiter(app)

    # Routes
    from doc_intel_rag.api.routes.admin import router as admin_router
    from doc_intel_rag.api.routes.generate import router as generate_router
    from doc_intel_rag.api.routes.graph import router as graph_router
    from doc_intel_rag.api.routes.health import router as health_router
    from doc_intel_rag.api.routes.ingest import router as ingest_router
    from doc_intel_rag.api.routes.search import router as search_router

    app.include_router(health_router)
    app.include_router(ingest_router)
    app.include_router(search_router)
    app.include_router(generate_router)
    app.include_router(graph_router)
    app.include_router(admin_router)

    return app


app = create_app()
