"""Streaming RAG generation with citations using Mesh API."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import TYPE_CHECKING, AsyncIterator

from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from doc_intel_rag.config import Settings, get_settings

if TYPE_CHECKING:
    pass


def _get_llm_client(settings: Settings) -> "object":
    """Return a cached AsyncOpenAI client for the configured LLM endpoint."""
    from openai import AsyncOpenAI
    return AsyncOpenAI(
        api_key=settings.mesh_api_key,
        base_url=settings.mesh_api_base_url,
    )
from doc_intel_rag.generation.citation_formatter import build_source_index, format_bibliography
from doc_intel_rag.generation.context_builder import build_context_text, build_messages
from doc_intel_rag.generation.prompt_templates import render_system, render_user
from doc_intel_rag.retrieval.hybrid_searcher import ScoredChunk


async def stream_generate(
    query: str,
    chunks: list[ScoredChunk],
    groundedness_score: float = 1.0,
    fallback_used: bool = False,
    max_tokens: int = 1024,
    temperature: float = 0.2,
    settings: Settings | None = None,
) -> AsyncIterator[str]:
    """Stream a cited RAG answer as Server-Sent Events.

    Assembles the multimodal context from ``chunks``, calls the Mesh API with
    ``stream=True``, and yields SSE frames.  The final frame carries a
    ``"done": true`` payload with full source metadata.

    Args:
        query: Sanitised user query (post-input-guard).
        chunks: Reranked chunks, including any web-fallback results.
        groundedness_score: Score from :func:`~doc_intel_rag.retrieval.groundedness.score_groundedness`.
        fallback_used: Whether Tavily results are included in ``chunks``.
        max_tokens: Maximum tokens the LLM may generate.
        temperature: Sampling temperature (0 = deterministic).
        settings: Optional settings override; uses the global singleton when ``None``.

    Yields:
        SSE-formatted strings of the form
        ``data: {"delta": "...", "done": false}\\n\\n``.
        The final yield is
        ``data: {"done": true, "sources": [...], "groundedness_score": ..., "fallback_used": ...}\\n\\n``.
    """
    cfg = settings or get_settings()

    context_text = build_context_text(chunks)
    system_prompt = render_system(fallback_used=fallback_used)
    user_prompt = render_user(query=query, context=context_text)
    messages = build_messages(query, chunks, system_prompt, user_prompt)

    bibliography = format_bibliography(chunks)
    source_index = build_source_index(chunks)

    web_sources = [
        {"url": c.payload.get("url", c.source_file), "title": c.payload.get("text", "")[:80]}
        for c in chunks if c.retrieval_source == "web"
    ]
    sources = [
        {
            "source_num": source_index[c.chunk_id],
            "file": c.source_file,
            "page": c.page,
            "modality": c.modality,
            "section_path": c.section_path,
            "retrieval_source": c.retrieval_source,
        }
        for c in chunks
    ]

    from openai import AsyncOpenAI

    client = _get_llm_client(cfg)

    try:
        stream = await client.chat.completions.create(
            model=cfg.mesh_llm_model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )

        async for chunk_event in stream:
            delta = chunk_event.choices[0].delta.content if chunk_event.choices else None
            if delta:
                yield f"data: {json.dumps({'delta': delta, 'done': False})}\n\n"

        # Append bibliography to the final streamed output
        yield f"data: {json.dumps({'delta': bibliography, 'done': False})}\n\n"

        # Final metadata event
        yield f"data: {json.dumps({'done': True, 'sources': sources, 'web_sources': web_sources, 'groundedness_score': groundedness_score, 'fallback_used': fallback_used})}\n\n"

    except Exception as exc:
        logger.error("Generation failed", error=str(exc))
        yield f"data: {json.dumps({'error': str(exc), 'done': True})}\n\n"


async def generate(
    query: str,
    chunks: list[ScoredChunk],
    groundedness_score: float = 1.0,
    fallback_used: bool = False,
    max_tokens: int = 1024,
    temperature: float = 0.2,
    settings: Settings | None = None,
) -> str:
    """Collect a complete answer by consuming :func:`stream_generate` internally.

    Convenience wrapper for the non-streaming ``/generate`` response path.

    Args:
        query: Sanitised user query.
        chunks: Reranked context chunks.
        groundedness_score: Pre-computed groundedness score.
        fallback_used: Whether Tavily web results were appended to ``chunks``.
        max_tokens: Maximum generation tokens.
        temperature: LLM sampling temperature.
        settings: Optional settings override.

    Returns:
        The full generated answer string including inline citations and
        the bibliography block, but excluding the SSE envelope.
    """
    parts: list[str] = []
    async for event in stream_generate(
        query=query,
        chunks=chunks,
        groundedness_score=groundedness_score,
        fallback_used=fallback_used,
        max_tokens=max_tokens,
        temperature=temperature,
        settings=settings,
    ):
        if event.startswith("data: "):
            try:
                data = json.loads(event[6:])
                if data.get("delta") and not data.get("done"):
                    parts.append(data["delta"])
            except json.JSONDecodeError:
                pass
    return "".join(parts)
