"""Full RAG pipeline endpoint with SSE streaming."""

from __future__ import annotations

import json
import time
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from doc_intel_rag.api.dependencies import (
    get_embedder, get_input_guard, get_output_guard, get_reranker,
    get_vector_store, get_web_fallback, verify_api_key,
)
from doc_intel_rag.api.schemas import (
    GenerateRequest, GenerateResponse, SafetyResultModel, SourceRef, WebResultModel,
)
from doc_intel_rag.config import Settings, get_settings
from doc_intel_rag.generation.citation_formatter import build_source_index
from doc_intel_rag.generation.generator import generate, stream_generate
from doc_intel_rag.retrieval.groundedness import score_groundedness
from doc_intel_rag.retrieval.hybrid_searcher import HybridSearcher
from doc_intel_rag.retrieval.semantic_router import SemanticRouter

router = APIRouter(tags=["generate"])


@router.post("/generate", response_model=None)
async def generate_endpoint(
    request: GenerateRequest,
    req: Request,
    api_key: str = Depends(verify_api_key),
    embedder: object = Depends(get_embedder),
    vector_store: object = Depends(get_vector_store),
    reranker: object = Depends(get_reranker),
    input_guard: object = Depends(get_input_guard),
    output_guard: object = Depends(get_output_guard),
    web_fallback: object = Depends(get_web_fallback),
) -> StreamingResponse | GenerateResponse:
    t0 = time.monotonic()
    request_id = req.state.request_id if hasattr(req.state, "request_id") else str(uuid.uuid4())
    settings = get_settings()

    from doc_intel_rag.safety.input_guard import InputGuard
    from doc_intel_rag.safety.output_guard import OutputGuard
    from doc_intel_rag.ingestion.embedder import DocumentEmbedder
    from doc_intel_rag.ingestion.vector_store import QdrantDocumentStore
    from doc_intel_rag.retrieval.reranker import BaseReranker
    from doc_intel_rag.retrieval.web_fallback import WebFallback

    assert isinstance(input_guard, InputGuard)
    assert isinstance(output_guard, OutputGuard)
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

    fallback_enabled = request.fallback_enabled if request.fallback_enabled is not None else settings.fallback_enabled
    fallback_used = False
    web_results = []

    if groundedness < settings.groundedness_threshold and fallback_enabled:
        if isinstance(web_fallback, WebFallback):
            raw_web = await web_fallback.search(safety_result.sanitised_query)
            web_results = raw_web
            web_chunks = web_fallback.to_chunks(raw_web)
            reranked = reranked + web_chunks
            fallback_used = True

    if request.streaming and settings.streaming_enabled:
        async def _event_stream():  # type: ignore[return]
            async for event in stream_generate(
                query=safety_result.sanitised_query,
                chunks=reranked,
                groundedness_score=groundedness,
                fallback_used=fallback_used,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                settings=settings,
            ):
                yield event

        return StreamingResponse(_event_stream(), media_type="text/event-stream")

    # Non-streaming path
    answer = await generate(
        query=safety_result.sanitised_query,
        chunks=reranked,
        groundedness_score=groundedness,
        fallback_used=fallback_used,
        max_tokens=request.max_tokens,
        temperature=request.temperature,
        settings=settings,
    )

    guard_result = await output_guard.check(answer=answer, context=" ".join(c.text for c in reranked[:5]))
    source_index = build_source_index(reranked)

    return GenerateResponse(
        query=request.query,
        answer=guard_result.answer,
        sources=[
            SourceRef(
                source_num=source_index[c.chunk_id],
                file=c.source_file,
                page=c.page,
                modality=c.modality,
                section_path=c.section_path,
                retrieval_source=c.retrieval_source,
            )
            for c in reranked
        ],
        groundedness_score=groundedness,
        faithfulness_score=guard_result.faithfulness_score,
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
