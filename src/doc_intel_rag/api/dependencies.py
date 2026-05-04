"""FastAPI dependency-injection singletons."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from doc_intel_rag.config import Settings, get_settings

_header_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)

# Module-level singleton cache
_singletons: dict[str, Any] = {}


def _get(key: str, factory: "Any") -> Any:
    if key not in _singletons:
        _singletons[key] = factory()
    return _singletons[key]


def get_settings_dep() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


def verify_api_key(
    api_key: str | None = Security(_header_scheme),
    settings: Settings = Depends(get_settings_dep),
) -> str:
    if not settings.api_keys:
        return "anonymous"
    if api_key not in settings.api_keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key",
        )
    return api_key


def get_embedder(settings: Settings = Depends(get_settings_dep)) -> Any:
    from doc_intel_rag.ingestion.embedder import DocumentEmbedder

    def _factory() -> DocumentEmbedder:
        cache = _singletons.get("query_cache")
        return DocumentEmbedder(settings=settings, cache=cache)

    return _get("embedder", _factory)


def get_vector_store(settings: Settings = Depends(get_settings_dep)) -> Any:
    from doc_intel_rag.ingestion.vector_store import QdrantDocumentStore
    return _get("vector_store", lambda: QdrantDocumentStore(settings=settings))


def get_graph_store() -> Any:
    from doc_intel_rag.ingestion.graph_store import GraphStore
    return _get("graph_store", GraphStore)


def get_reranker(settings: Settings = Depends(get_settings_dep)) -> Any:
    from doc_intel_rag.retrieval.reranker import get_reranker as _get_reranker
    return _get("reranker", lambda: _get_reranker(settings=settings))


def get_input_guard(settings: Settings = Depends(get_settings_dep)) -> Any:
    from doc_intel_rag.safety.input_guard import InputGuard
    return _get("input_guard", lambda: InputGuard(settings=settings))


def get_output_guard(settings: Settings = Depends(get_settings_dep)) -> Any:
    from doc_intel_rag.safety.output_guard import OutputGuard
    return _get("output_guard", lambda: OutputGuard(settings=settings))


def get_redis_client() -> Any:
    return _singletons.get("redis_client")


def get_query_cache() -> Any:
    return _singletons.get("query_cache")


def get_web_fallback(settings: Settings = Depends(get_settings_dep)) -> Any:
    from doc_intel_rag.retrieval.web_fallback import WebFallback
    return _get("web_fallback", lambda: WebFallback(settings=settings))


async def init_singletons(settings: Settings) -> None:
    """Called during FastAPI lifespan startup."""
    try:
        from doc_intel_rag.ingestion.cache import QueryCache, create_redis_client
        redis_client = await create_redis_client(settings.redis_url)
        _singletons["redis_client"] = redis_client
        _singletons["query_cache"] = QueryCache(redis_client, ttl=settings.redis_query_ttl)
    except Exception:
        pass  # Redis optional — degrade gracefully


async def shutdown_singletons() -> None:
    """Called during FastAPI lifespan shutdown."""
    vs = _singletons.get("vector_store")
    if vs is not None:
        await vs.close()

    redis = _singletons.get("redis_client")
    if redis is not None:
        await redis.aclose()

    _singletons.clear()
