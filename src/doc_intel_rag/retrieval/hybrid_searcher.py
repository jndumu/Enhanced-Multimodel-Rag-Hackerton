"""Hybrid dense + sparse + graph search with RRF fusion."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from doc_intel_rag.retrieval.semantic_router import QueryIntent

_MODALITY_FILTER_MAP: dict[QueryIntent, list[str]] = {
    QueryIntent.VISUAL:       ["image", "graph"],
    QueryIntent.MATHEMATICAL: ["formula"],
    QueryIntent.CODE:         ["algorithm", "code"],
}


@dataclass
class ScoredChunk:
    """A retrieved chunk annotated with its retrieval score and source.

    Attributes:
        score: Relevance score assigned by the retriever or reranker (higher is better).
        payload: Full Qdrant point payload or web-result dict.
        chunk_id: Matches the ``chunk_id`` field stored in the Qdrant payload.
        retrieval_source: ``"vector"`` for Qdrant results, ``"graph"`` for graph
            traversal results, or ``"web"`` for Tavily fallback results.
    """

    score: float
    payload: dict[str, Any]
    chunk_id: str
    retrieval_source: str = "vector"

    @property
    def modality(self) -> str:
        return self.payload.get("modality", "text")

    @property
    def text(self) -> str:
        return self.payload.get("enriched_text") or self.payload.get("text", "")

    @property
    def doc_id(self) -> str:
        return self.payload.get("doc_id", "")

    @property
    def source_file(self) -> str:
        return self.payload.get("source_file", "")

    @property
    def page(self) -> int:
        return int(self.payload.get("page", 1))

    @property
    def section_path(self) -> list[str]:
        return self.payload.get("section_path", [])


class HybridSearcher:
    """Executes hybrid dense + sparse + graph search with Reciprocal Rank Fusion.

    Combines three retrieval signals via Qdrant ``Prefetch`` + RRF:

    * ``text_dense`` — cosine similarity against Mesh API embeddings.
    * ``bm25_sparse`` — BM25 feature-hashing TF overlap.
    * ``graph_dense`` — node2vec averaged embeddings (graph chunks only).

    For ``relational`` and ``analytical`` intents, 2-hop graph traversal is
    performed from the top-5 seed chunks and merged via a second RRF pass.

    Args:
        vector_store: A :class:`~doc_intel_rag.ingestion.vector_store.QdrantDocumentStore`.
        embedder: A :class:`~doc_intel_rag.ingestion.embedder.DocumentEmbedder`.
        graph_store: Optional :class:`~doc_intel_rag.ingestion.graph_store.GraphStore`
            for graph traversal; traversal is skipped when ``None``.
    """

    def __init__(
        self,
        vector_store: "object",
        embedder: "object",
        graph_store: "object | None" = None,
    ) -> None:
        self._vs = vector_store
        self._emb = embedder
        self._gs = graph_store

    async def search(
        self,
        query: str,
        top_k: int = 10,
        intent: QueryIntent = QueryIntent.GENERAL,
        collection: str | None = None,
        extra_filter: Any = None,
    ) -> list[ScoredChunk]:
        """Execute hybrid search and return ranked :class:`ScoredChunk` results.

        Args:
            query: Natural-language query string.
            top_k: Maximum number of chunks to return (doubled for ``ANALYTICAL``).
            intent: Query intent from :class:`~doc_intel_rag.retrieval.semantic_router.SemanticRouter`.
            collection: Qdrant collection name; defaults to ``settings.qdrant_collection``.
            extra_filter: Additional Qdrant ``Filter`` condition merged with intent filters.

        Returns:
            Ranked list of :class:`ScoredChunk` objects, highest score first.
        """
        from doc_intel_rag.ingestion.embedder import DocumentEmbedder
        from doc_intel_rag.ingestion.vector_store import QdrantDocumentStore

        assert isinstance(self._vs, QdrantDocumentStore)
        assert isinstance(self._emb, DocumentEmbedder)

        # Expand top_k for analytical queries
        effective_k = top_k * 2 if intent == QueryIntent.ANALYTICAL else top_k

        query_dense = await self._emb.embed_query(query)
        query_sparse = self._emb.sparse_encode(query)

        qdrant_filter = self._build_filter(intent, extra_filter)

        raw_results = await self._vs.hybrid_search(
            dense_vector=query_dense,
            sparse_vector=query_sparse,
            top_k=effective_k * 3,
            collection=collection,
            query_filter=qdrant_filter,
        )

        scored = [
            ScoredChunk(score=r["score"], payload=r["payload"], chunk_id=r["id"])
            for r in raw_results
        ]

        # Graph traversal for relational/analytical intents
        if intent in {QueryIntent.RELATIONAL, QueryIntent.ANALYTICAL} and self._gs is not None:
            graph_chunks = await self._graph_traverse(scored[:5], collection)
            scored = _rrf_merge(scored, graph_chunks)

        # Apply modality filter post-hoc when using intent-specific filtering
        if intent in _MODALITY_FILTER_MAP:
            allowed = _MODALITY_FILTER_MAP[intent]
            scored = [c for c in scored if c.modality in allowed] or scored

        return scored[:effective_k]

    def _build_filter(self, intent: QueryIntent, extra: Any) -> Any:
        from qdrant_client.models import FieldCondition, Filter, MatchAny

        conditions = []
        if extra is not None:
            conditions.append(extra)

        if intent in _MODALITY_FILTER_MAP:
            allowed = _MODALITY_FILTER_MAP[intent]
            conditions.append(
                FieldCondition(key="modality", match=MatchAny(any=allowed))
            )

        if not conditions:
            return None
        return Filter(must=conditions) if len(conditions) > 1 else conditions[0]

    async def _graph_traverse(
        self, seed_chunks: list[ScoredChunk], collection: str | None
    ) -> list[ScoredChunk]:
        from doc_intel_rag.ingestion.graph_store import GraphStore
        from doc_intel_rag.ingestion.vector_store import QdrantDocumentStore

        assert isinstance(self._gs, GraphStore)
        assert isinstance(self._vs, QdrantDocumentStore)

        neighbour_ids: set[str] = set()
        for chunk in seed_chunks:
            if chunk.payload.get("graph_json") and chunk.doc_id:
                nodes = list((chunk.payload.get("graph_json") or {}).get("nodes", []))
                if nodes:
                    top_node = nodes[0].get("id", "")
                    neighbours = self._gs.get_neighbors(chunk.doc_id, top_node, depth=2)
                    neighbour_ids.update(neighbours)

        if not neighbour_ids:
            return []

        # Fetch these chunks from Qdrant by ID
        try:
            client_raw = await self._vs._get_client()
            col = collection or self._vs._settings.qdrant_collection
            points = await client_raw.retrieve(
                collection_name=col,
                ids=list(neighbour_ids)[:20],
                with_payload=True,
            )
            return [
                ScoredChunk(score=0.5, payload=p.payload or {}, chunk_id=str(p.id), retrieval_source="graph")
                for p in points
            ]
        except Exception as exc:
            logger.debug("Graph traversal retrieval failed", error=str(exc))
            return []


def _rrf_merge(
    primary: list[ScoredChunk],
    secondary: list[ScoredChunk],
    rank_constant: int = 60,
) -> list[ScoredChunk]:
    scores: dict[str, float] = {}
    all_chunks: dict[str, ScoredChunk] = {}

    for rank, chunk in enumerate(primary):
        scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0) + 1.0 / (rank_constant + rank + 1)
        all_chunks[chunk.chunk_id] = chunk

    for rank, chunk in enumerate(secondary):
        scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0) + 1.0 / (rank_constant + rank + 1)
        if chunk.chunk_id not in all_chunks:
            all_chunks[chunk.chunk_id] = chunk

    return sorted(all_chunks.values(), key=lambda c: scores[c.chunk_id], reverse=True)
