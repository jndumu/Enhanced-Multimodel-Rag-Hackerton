"""Health check and metrics-summary endpoints."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends

from doc_intel_rag.api.dependencies import get_redis_client, get_settings_dep, get_vector_store
from doc_intel_rag.api.schemas import HealthComponent, HealthResponse
from doc_intel_rag.config import Settings

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(
    settings: Settings = Depends(get_settings_dep),
    vector_store: object = Depends(get_vector_store),
    redis_client: object = Depends(get_redis_client),
) -> HealthResponse:
    components: dict[str, HealthComponent] = {}

    # Qdrant
    try:
        t0 = time.monotonic()
        from doc_intel_rag.ingestion.vector_store import QdrantDocumentStore
        assert isinstance(vector_store, QdrantDocumentStore)
        client = await vector_store._get_client()
        await client.get_collections()
        components["qdrant"] = HealthComponent(
            status="ok", latency_ms=round((time.monotonic() - t0) * 1000, 1)
        )
    except Exception as exc:
        components["qdrant"] = HealthComponent(status="error", detail=str(exc))

    # Redis
    try:
        if redis_client is not None:
            t0 = time.monotonic()
            await redis_client.ping()  # type: ignore[attr-defined]
            components["redis"] = HealthComponent(
                status="ok", latency_ms=round((time.monotonic() - t0) * 1000, 1)
            )
        else:
            components["redis"] = HealthComponent(status="not_configured")
    except Exception as exc:
        components["redis"] = HealthComponent(status="error", detail=str(exc))

    # Mesh API (simple connectivity check)
    try:
        import httpx
        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(settings.mesh_api_base_url.rstrip("/v1") or "https://api.mesh.ai")
        components["mesh_api"] = HealthComponent(
            status="ok" if r.status_code < 500 else "degraded",
            latency_ms=round((time.monotonic() - t0) * 1000, 1),
        )
    except Exception as exc:
        components["mesh_api"] = HealthComponent(status="error", detail=str(exc)[:80])

    overall = "ok" if all(c.status in ("ok", "not_configured") for c in components.values()) else "degraded"
    return HealthResponse(status=overall, components=components)
