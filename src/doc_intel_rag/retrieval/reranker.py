"""Pluggable reranker: Cohere | Jina | OpenAI cross-encoder. NOT Qwen/BGE/Ollama/Mesh."""

from __future__ import annotations

import asyncio
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
            Up to ``top_n`` :class:`ScoredChunk` objects sorted by descending
            relevance score.
        """
        ...


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

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def rerank(
        self, query: str, chunks: list[ScoredChunk], top_n: int
    ) -> list[ScoredChunk]:
        import cohere

        client = cohere.AsyncClientV2(api_key=self._settings.cohere_api_key)

        documents = [
            {"text": c.text[:2000] or c.payload.get("text", "")[:2000]}
            for c in chunks
        ]

        response = await client.rerank(
            model=self._settings.cohere_rerank_model,
            query=query,
            documents=documents,
            top_n=min(top_n, len(chunks)),
        )

        reranked: list[ScoredChunk] = []
        for result in response.results:
            chunk = chunks[result.index]
            chunk.score = float(result.relevance_score)
            reranked.append(chunk)

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
        import httpx

        documents = [c.text[:2000] or c.payload.get("text", "")[:2000] for c in chunks]

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

        reranked: list[ScoredChunk] = []
        for result in data.get("results", []):
            idx = result["index"]
            chunks[idx].score = float(result["relevance_score"])
            reranked.append(chunks[idx])

        logger.debug("Jina rerank done", top_n=len(reranked))
        return reranked


class OpenAICrossEncoder:
    """gpt-4o-mini as cross-encoder: parallel async (query, chunk) scoring."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def rerank(
        self, query: str, chunks: list[ScoredChunk], top_n: int
    ) -> list[ScoredChunk]:
        scores = await asyncio.gather(
            *[self._score_pair(query, c) for c in chunks],
            return_exceptions=True,
        )

        scored: list[tuple[float, ScoredChunk]] = []
        for i, score in enumerate(scores):
            if isinstance(score, Exception):
                scored.append((chunks[i].score, chunks[i]))
            else:
                chunks[i].score = float(score)
                scored.append((float(score), chunks[i]))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:top_n]]

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(3),
        reraise=False,
    )
    async def _score_pair(self, query: str, chunk: ScoredChunk) -> float:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=self._settings.openai_api_key,
            base_url="https://api.openai.com/v1",
        )
        response = await client.chat.completions.create(
            model=self._settings.openai_rerank_model,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Score how relevant this passage is to the query on a scale of 0.0 to 1.0. "
                        f"Return ONLY the decimal number.\n\nQuery: {query}\n\nPassage: {chunk.text[:800]}"
                    ),
                }
            ],
            max_tokens=8,
            temperature=0,
        )
        raw = (response.choices[0].message.content or "0.5").strip()
        return min(1.0, max(0.0, float(raw)))


def get_reranker(settings: Settings | None = None) -> BaseReranker:
    cfg = settings or get_settings()
    match cfg.reranker_backend:
        case "cohere":
            return CohereReranker(cfg)
        case "jina":
            return JinaReranker(cfg)
        case "openai":
            return OpenAICrossEncoder(cfg)
        case _:
            raise ValueError(f"Unknown reranker backend: {cfg.reranker_backend}")
