"""Search endpoint — retrieve + rerank without generation."""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, Request

from doc_intel_rag.api.dependencies import (
    get_embedder, get_input_guard, get_reranker,
    get_vector_store, get_web_fallback, verify_api_key,
)
from doc_intel_rag.api.schemas import (
    ChunkResult, SafetyResultModel, SearchRequest, SearchResponse, WebResultModel,
)
from doc_intel_rag.config import Settings, get_settings
from doc_intel_rag.retrieval.groundedness import score_groundedness
from doc_intel_rag.retrieval.hybrid_searcher import HybridSearcher
from doc_intel_rag.retrieval.semantic_router import SemanticRouter

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchResponse)
async def search(
    request: SearchRequest,
    req: Request,
    api_key: str = Depends(verify_api_key),
    embedder: object = Depends(get_embedder),
    vector_store: object = Depends(get_vector_store),
    reranker: object = Depends(get_reranker),
    input_guard: object = Depends(get_input_guard),
    web_fallback: object = Depends(get_web_fallback),
) -> SearchResponse:
    t0 = time.monotonic()
    request_id = req.state.request_id if hasattr(req.state, "request_id") else str(uuid.uuid4())
    settings = get_settings()

    from doc_intel_rag.safety.input_guard import InputGuard
    from doc_intel_rag.ingestion.embedder import DocumentEmbedder
    from doc_intel_rag.ingestion.vector_store import QdrantDocumentStore
    from doc_intel_rag.retrieval.reranker import BaseReranker
    from doc_intel_rag.retrieval.web_fallback import WebFallback

    assert isinstance(input_guard, InputGuard)
    assert isinstance(embedder, DocumentEmbedder)
    assert isinstance(vector_store, QdrantDocumentStore)
    assert isinstance(reranker, BaseReranker)

    safety_result = await input_guard.check(request.query)

    router_cls = SemanticRouter(settings)
    intent = await router_cls.classify(safety_result.sanitised_query)

    searcher = HybridSearcher(vector_store=vector_store, embedder=embedder)
    scored_chunks = await searcher.search(
        query=safety_result.sanitised_query,
        top_k=request.top_k,
        intent=intent,
        collection=request.collection,
    )

    reranked = await reranker.rerank(  # type: ignore[attr-defined]
        query=safety_result.sanitised_query,
        chunks=scored_chunks,
        top_n=request.top_n,
    )

    query_emb = await embedder.embed_query(safety_result.sanitised_query)
    groundedness = score_groundedness(query_emb, reranked)
    fallback_used = False
    web_results = []

    if groundedness < settings.groundedness_threshold and settings.fallback_enabled:
        if isinstance(web_fallback, WebFallback):
            raw_web = await web_fallback.search(safety_result.sanitised_query)
            web_results = raw_web
            web_chunks = web_fallback.to_chunks(raw_web)
            reranked = reranked + web_chunks
            fallback_used = True

    chunk_results = [
        ChunkResult(
            chunk_id=c.chunk_id,
            doc_id=c.doc_id,
            source_file=c.source_file,
            page=c.page,
            modality=c.modality,
            text=c.text[:500],
            score=c.score,
            section_path=c.section_path,
            retrieval_source=c.retrieval_source,
            concept_tags=c.payload.get("concept_tags", []),
        )
        for c in reranked
    ]

    return SearchResponse(
        query=request.query,
        chunks=chunk_results,
        groundedness_score=groundedness,
        fallback_used=fallback_used,
        web_sources=[WebResultModel(url=w.url, title=w.title, snippet=w.snippet, score=w.score) for w in web_results],
        safety=SafetyResultModel(
            pii_redacted=safety_result.pii_redacted,
            redacted_entities=safety_result.redacted_entities,
            injection_detected=safety_result.injection_detected,
            content_class=safety_result.content_class,
        ),
        request_id=request_id,
        latency_ms=round((time.monotonic() - t0) * 1000, 1),
    )
