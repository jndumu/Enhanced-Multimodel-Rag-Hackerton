"""Pluggable reranker: Cohere | Jina | OpenAI cross-encoder. NOT Qwen/BGE/Ollama/Mesh."""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Protocol, runtime_checkable

from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from doc_intel_rag.config import Settings, get_settings
from doc_intel_rag.retrieval.hybrid_searcher import ScoredChunk


@runtime_checkable
class BaseReranker(Protocol):
    """Structural protocol satisfied by all reranker backends.

    Any class that implements ``async def rerank(...)`` with the correct
    signature is a valid reranker and can be injected via FastAPI dependencies.

    **Forbidden backends**: Qwen, BGE, Ollama, and Mesh API must not be used
    for reranking — only Cohere, Jina, and OpenAI are permitted.
    """

    async def rerank(
        self, query: str, chunks: list[ScoredChunk], top_n: int
    ) -> list[ScoredChunk]:
        """Re-score and sort chunks by relevance to the query.

        Args:
            query: The user's search query.
            chunks: Candidate chunks from the hybrid retriever.
            top_n: Maximum number of chunks to return.

        Returns:
            Up to ``top_n`` new :class:`ScoredChunk` objects (input is never
            mutated) sorted by descending relevance score.
        """
        ...


def _replace_score(chunk: ScoredChunk, score: float) -> ScoredChunk:
    """Return a new ScoredChunk with an updated score; never mutates input."""
    return dataclasses.replace(chunk, score=score)


class CohereReranker:
    """Reranker backed by Cohere's ``rerank-v3.5`` model.

    Sends up to ``top_n`` document snippets (first 2000 chars each) to the
    Cohere Rerank v3 API and returns results sorted by ``relevance_score``.
    Retries up to 3 times with exponential back-off on any exception.

    Args:
        settings: Runtime configuration supplying the Cohere API key and model name.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: "object | None" = None

    def _get_client(self) -> "object":
        if self._client is None:
            import cohere
            self._client = cohere.AsyncClientV2(api_key=self._settings.cohere_api_key)
        return self._client

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def rerank(
        self, query: str, chunks: list[ScoredChunk], top_n: int
    ) -> list[ScoredChunk]:
        if not chunks:
            return []

        client = self._get_client()

        documents = [
            {"text": (c.text or c.payload.get("text", ""))[:2000]}
            for c in chunks
        ]

        response = await client.rerank(  # type: ignore[attr-defined]
            model=self._settings.cohere_rerank_model,
            query=query,
            documents=documents,
            top_n=min(top_n, len(chunks)),
        )

        reranked = [
            _replace_score(chunks[r.index], float(r.relevance_score))
            for r in response.results
        ]

        logger.debug("Cohere rerank done", top_n=len(reranked))
        return reranked


class JinaReranker:
    """Jina Reranker API — multimodal via HTTP."""

    _API_URL = "https://api.jina.ai/v1/rerank"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def rerank(
        self, query: str, chunks: list[ScoredChunk], top_n: int
    ) -> list[ScoredChunk]:
        if not chunks:
            return []

        import httpx

        documents = [(c.text or c.payload.get("text", ""))[:2000] for c in chunks]

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                self._API_URL,
                headers={"Authorization": f"Bearer {self._settings.jina_api_key}"},
                json={
                    "model": self._settings.jina_rerank_model,
                    "query": query,
                    "documents": documents,
                    "top_n": min(top_n, len(chunks)),
                },
            )
            response.raise_for_status()
            data = response.json()

        reranked = [
            _replace_score(chunks[r["index"]], float(r["relevance_score"]))
            for r in data.get("results", [])
        ]

        logger.debug("Jina rerank done", top_n=len(reranked))
        return reranked


class OpenAICrossEncoder:
    """GPT-4o-mini as cross-encoder: parallel async (query, chunk) scoring."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: "object | None" = None

    def _get_client(self) -> "object":
        if self._client is None:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                api_key=self._settings.openai_api_key,
                base_url="https://api.openai.com/v1",
            )
        return self._client

    async def rerank(
        self, query: str, chunks: list[ScoredChunk], top_n: int
    ) -> list[ScoredChunk]:
        if not chunks:
            return []

        raw_scores = await asyncio.gather(
            *[self._score_pair(query, c) for c in chunks],
            return_exceptions=True,
        )

        pairs: list[tuple[float, ScoredChunk]] = []
        for chunk, score in zip(chunks, raw_scores):
            s = chunk.score if isinstance(score, Exception) else float(score)
            pairs.append((s, _replace_score(chunk, s)))

        pairs.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in pairs[:top_n]]

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(3),
        reraise=False,
    )
    async def _score_pair(self, query: str, chunk: ScoredChunk) -> float:
        client = self._get_client()
        response = await client.chat.completions.create(  # type: ignore[attr-defined]
            model=self._settings.openai_rerank_model,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Score how relevant this passage is to the query on a scale "
                        "of 0.0 to 1.0. Return ONLY the decimal number.\n\n"
                        f"Query: {query}\n\nPassage: {chunk.text[:800]}"
                    ),
                }
            ],
            max_tokens=8,
            temperature=0,
        )
        raw = (response.choices[0].message.content or "0.5").strip()
        try:
            return min(1.0, max(0.0, float(raw)))
        except ValueError:
            return 0.5


def get_reranker(settings: Settings | None = None) -> BaseReranker:
    """Instantiate and return the configured reranker backend.

    Args:
        settings: Optional settings override; uses the global singleton when ``None``.

    Returns:
        A :class:`BaseReranker` instance for the configured backend.

    Raises:
        ValueError: When ``settings.reranker_backend`` is not one of
            ``cohere``, ``jina``, ``openai``.
    """
    cfg = settings or get_settings()
    match cfg.reranker_backend:
        case "cohere":
            return CohereReranker(cfg)
        case "jina":
            return JinaReranker(cfg)
        case "openai":
            return OpenAICrossEncoder(cfg)
        case _:
            raise ValueError(
                f"Unknown reranker backend: {cfg.reranker_backend!r}. "
                "Valid options: cohere, jina, openai"
            )
