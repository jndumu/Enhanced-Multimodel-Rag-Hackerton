"""Loguru + stdlib interception + optional OpenTelemetry log bridge."""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from doc_intel_rag.config import Settings


class _InterceptHandler(logging.Handler):
    """Redirect stdlib logging records into Loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = sys._getframe(6), 6
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back  # type: ignore[assignment]
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def _mask_secrets(record: dict) -> bool:  # type: ignore[type-arg]
    """Strip secret fields from any log record before writing."""
    secret_keys = {
        "mesh_api_key", "api_key", "cohere_api_key", "jina_api_key",
        "openai_api_key", "tavily_api_key", "password", "token",
    }
    extra = record.get("extra", {})
    for key in secret_keys:
        if key in extra:
            extra[key] = "***"
    return True


def setup_logging(settings: "Settings | None" = None) -> None:
    """Configure Loguru sinks and intercept stdlib logging.

    Safe to call multiple times — removes previous sinks first.
    """
    from doc_intel_rag.config import get_settings

    if settings is None:
        try:
            settings = get_settings()
        except Exception:
            settings = None

    log_level = getattr(settings, "log_level", "INFO") if settings else "INFO"
    log_json = getattr(settings, "log_json", False) if settings else False
    otel_endpoint = getattr(settings, "otel_endpoint", "") if settings else ""
    service_name = getattr(settings, "otel_service_name", "doc-intel-rag") if settings else "doc-intel-rag"

    logger.remove()

    if log_json:
        fmt = (
            "{{"
            '"time":"{time:YYYY-MM-DDTHH:mm:ss.SSSZ}",'
            '"level":"{level}",'
            '"name":"{name}",'
            '"message":"{message}"'
            "}}"
        )
    else:
        fmt = (
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> — "
            "<level>{message}</level>"
        )

    logger.add(
        sys.stderr,
        level=log_level,
        format=fmt,
        colorize=not log_json,
        filter=_mask_secrets,
        enqueue=True,
        backtrace=True,
        diagnose=not log_json,
    )

    # Intercept all stdlib loggers
    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)
    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi", "httpx"):
        logging.getLogger(noisy).handlers = [_InterceptHandler()]
        logging.getLogger(noisy).propagate = False

    if otel_endpoint:
        _setup_otel(otel_endpoint, service_name, log_level)

    logger.info("Logging initialised", level=log_level, json=log_json, service=service_name)


def _setup_otel(endpoint: str, service_name: str, log_level: str) -> None:
    """Wire up OpenTelemetry tracer provider with OTLP gRPC export."""
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource(attributes={SERVICE_NAME: service_name})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
        )
        trace.set_tracer_provider(provider)
        logger.info("OpenTelemetry tracer configured", endpoint=endpoint)
    except ImportError:
        logger.warning("opentelemetry packages not installed — tracing disabled")
    except Exception as exc:
        logger.warning("Failed to configure OpenTelemetry", error=str(exc))


def get_tracer(name: str = "doc-intel-rag") -> "object":
    """Return an OTel tracer — no-op if OTel is not configured."""
    try:
        from opentelemetry import trace
        return trace.get_tracer(name)
    except ImportError:
        return _NoopTracer()


class _NoopTracer:
    """Minimal tracer stub used when OpenTelemetry is unavailable."""

    def start_as_current_span(self, name: str, **_: object) -> "_NoopSpan":  # type: ignore[return]
        return _NoopSpan()


class _NoopSpan:
    def __enter__(self) -> "_NoopSpan":
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def set_attribute(self, *_: object) -> None:
        pass

    def record_exception(self, *_: object) -> None:
        pass
