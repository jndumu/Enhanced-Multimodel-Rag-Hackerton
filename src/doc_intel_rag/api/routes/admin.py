"""Admin endpoints: cache purge and stats."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from doc_intel_rag.api.dependencies import (
    get_query_cache, get_vector_store, verify_api_key,
)
from doc_intel_rag.api.schemas import AdminStatsResponse

router = APIRouter(prefix="/admin", tags=["admin"])

_start_time = time.monotonic()


@router.get("/stats", response_model=AdminStatsResponse)
async def stats(
    api_key: str = Depends(verify_api_key),
    vector_store: object = Depends(get_vector_store),
    query_cache: object = Depends(get_query_cache),
) -> AdminStatsResponse:
    from doc_intel_rag.ingestion.vector_store import QdrantDocumentStore
    assert isinstance(vector_store, QdrantDocumentStore)

    qdrant_stats = await vector_store.get_stats()

    return AdminStatsResponse(
        qdrant=qdrant_stats,
        cache_flushable=query_cache is not None,
        uptime_seconds=round(time.monotonic() - _start_time, 1),
    )


@router.post("/purge-cache", status_code=status.HTTP_200_OK)
async def purge_cache(
    api_key: str = Depends(verify_api_key),
    query_cache: object = Depends(get_query_cache),
) -> JSONResponse:
    flushed = 0
    if query_cache is not None:
        from doc_intel_rag.ingestion.cache import QueryCache
        assert isinstance(query_cache, QueryCache)
        flushed = await query_cache.flush_all()
    return JSONResponse({"flushed_keys": flushed})
