"""Tavily web search fallback — triggered when groundedness < threshold."""

from __future__ import annotations

from dataclasses import dataclass, field

from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from doc_intel_rag.config import Settings, get_settings
from doc_intel_rag.retrieval.hybrid_searcher import ScoredChunk


@dataclass
class WebResult:
    url: str
    title: str
    snippet: str
    score: float = 0.0
    raw: dict = field(default_factory=dict)


class WebFallback:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        stop=stop_after_attempt(3),
        reraise=False,
    )
    async def search(self, query: str) -> list[WebResult]:
        if not self._settings.tavily_api_key:
            logger.warning("Tavily API key not set — web fallback disabled")
            return []

        try:
            from tavily import AsyncTavilyClient

            client = AsyncTavilyClient(api_key=self._settings.tavily_api_key)
            response = await client.search(
                query=query,
                max_results=self._settings.tavily_max_results,
                include_answer=False,
            )
            results: list[WebResult] = []
            for item in response.get("results", []):
                results.append(WebResult(
                    url=item.get("url", ""),
                    title=item.get("title", ""),
                    snippet=item.get("content", ""),
                    score=float(item.get("score", 0.0)),
                    raw=item,
                ))
            logger.info("Web fallback retrieved", count=len(results), query=query[:60])
            return results
        except Exception as exc:
            logger.warning("Web fallback failed", error=str(exc))
            return []

    def to_chunks(self, results: list[WebResult]) -> list[ScoredChunk]:
        chunks: list[ScoredChunk] = []
        for result in results:
            payload = {
                "chunk_id": f"web:{result.url}",
                "doc_id": "web",
                "source_file": result.url,
                "page": 1,
                "modality": "text",
                "text": f"{result.title}\n\n{result.snippet}",
                "enriched_text": f"{result.title}\n\n{result.snippet}",
                "section_path": [],
                "url": result.url,
            }
            chunks.append(ScoredChunk(
                score=result.score,
                payload=payload,
                chunk_id=f"web:{result.url}",
                retrieval_source="web",
            ))
        return chunks
