"""Qdrant vector store: hybrid dense + sparse + graph search with RRF fusion."""

from __future__ import annotations

from typing import Any

from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from doc_intel_rag.chunking.schemas import Chunk
from doc_intel_rag.config import Settings, get_settings
from doc_intel_rag.ingestion.graph_embedder import GRAPH_EMBED_DIM


class QdrantDocumentStore:
    """Async Qdrant client wrapper for hybrid document retrieval.

    Manages a Qdrant collection with three named vectors:

    * ``text_dense`` — cosine-similarity dense embeddings from the Mesh API.
    * ``bm25_sparse`` — sparse BM25 TF feature-hashing vectors.
    * ``graph_dense`` — 128-dim node2vec embeddings for graph-type chunks.

    Hybrid search uses Qdrant ``Prefetch`` on all three vectors combined with
    RRF (``Query(fusion="rrf")``) fusion.

    Ingestion is idempotent: :meth:`doc_exists` checks for an existing
    ``doc_id`` before processing, and ``force=True`` bypasses the check.

    Args:
        settings: Runtime configuration. Defaults to the global singleton.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client: Any = None

    async def _get_client(self) -> Any:
        if self._client is None:
            from qdrant_client import AsyncQdrantClient
            self._client = AsyncQdrantClient(
                url=self._settings.qdrant_url,
                api_key=self._settings.qdrant_api_key or None,
                timeout=30,
            )
        return self._client

    async def ensure_collection(self, collection: str | None = None) -> None:
        from qdrant_client.models import (
            Distance, SparseIndexParams, SparseVectorParams, VectorParams, VectorsConfig,
        )
        client = await self._get_client()
        col = collection or self._settings.qdrant_collection

        existing = {c.name for c in (await client.get_collections()).collections}
        if col in existing:
            return

        await client.create_collection(
            collection_name=col,
            vectors_config={
                "text_dense": VectorParams(
                    size=self._settings.mesh_embedding_dim,
                    distance=Distance.COSINE,
                ),
                "graph_dense": VectorParams(
                    size=GRAPH_EMBED_DIM,
                    distance=Distance.COSINE,
                ),
            },
            sparse_vectors_config={
                "bm25_sparse": SparseVectorParams(index=SparseIndexParams()),
            },
        )
        logger.info("Qdrant collection created", collection=col)

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def upsert_chunks(
        self,
        chunks: list[Chunk],
        dense_vectors: list[list[float]],
        sparse_vectors: list[dict[int, float]],
        graph_vectors: list[list[float] | None],
        collection: str | None = None,
    ) -> int:
        from qdrant_client.models import PointStruct, SparseVector

        client = await self._get_client()
        col = collection or self._settings.qdrant_collection
        await self.ensure_collection(col)

        points: list[PointStruct] = []
        for i, chunk in enumerate(chunks):
            named_vectors: dict[str, Any] = {
                "text_dense": dense_vectors[i],
                "bm25_sparse": SparseVector(
                    indices=list(sparse_vectors[i].keys()),
                    values=list(sparse_vectors[i].values()),
                ),
            }
            if graph_vectors[i] is not None:
                named_vectors["graph_dense"] = graph_vectors[i]

            payload = chunk.to_dict()
            payload.pop("raw_image_b64", None)  # don't store large base64 in Qdrant payload

            points.append(PointStruct(
                id=chunk.chunk_id,
                vector=named_vectors,
                payload=payload,
            ))

        batch_size = self._settings.ingest_batch_size
        for start in range(0, len(points), batch_size):
            await client.upsert(
                collection_name=col,
                points=points[start : start + batch_size],
            )

        logger.info("Upserted chunks", collection=col, count=len(chunks))
        return len(chunks)

    async def doc_exists(self, doc_id: str, collection: str | None = None) -> bool:
        from qdrant_client.models import FieldCondition, Filter, MatchValue
        client = await self._get_client()
        col = collection or self._settings.qdrant_collection
        try:
            result = await client.scroll(
                collection_name=col,
                scroll_filter=Filter(
                    must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
                ),
                limit=1,
            )
            return len(result[0]) > 0
        except Exception:
            return False

    async def delete_doc(self, doc_id: str, collection: str | None = None) -> None:
        from qdrant_client.models import FieldCondition, Filter, MatchValue
        client = await self._get_client()
        col = collection or self._settings.qdrant_collection
        await client.delete(
            collection_name=col,
            points_selector=Filter(
                must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
            ),
        )

    async def delete_collection(self, collection: str) -> None:
        client = await self._get_client()
        await client.delete_collection(collection)

    async def hybrid_search(
        self,
        dense_vector: list[float],
        sparse_vector: dict[int, float],
        top_k: int,
        collection: str | None = None,
        query_filter: Any = None,
    ) -> list[dict[str, Any]]:
        from qdrant_client.models import Prefetch, Query, SparseVector

        client = await self._get_client()
        col = collection or self._settings.qdrant_collection

        prefetch = [
            Prefetch(
                query=dense_vector,
                using="text_dense",
                limit=top_k * 3,
                filter=query_filter,
            ),
            Prefetch(
                query=SparseVector(
                    indices=list(sparse_vector.keys()),
                    values=list(sparse_vector.values()),
                ),
                using="bm25_sparse",
                limit=top_k * 3,
                filter=query_filter,
            ),
        ]

        results = await client.query_points(
            collection_name=col,
            prefetch=prefetch,
            query=Query(fusion="rrf"),
            limit=top_k,
            with_payload=True,
        )

        return [
            {"score": p.score, "payload": p.payload, "id": str(p.id)}
            for p in results.points
        ]

    async def graph_search(
        self,
        graph_vector: list[float],
        top_k: int,
        collection: str | None = None,
    ) -> list[dict[str, Any]]:
        client = await self._get_client()
        col = collection or self._settings.qdrant_collection

        results = await client.query_points(
            collection_name=col,
            query=graph_vector,
            using="graph_dense",
            limit=top_k,
            with_payload=True,
        )
        return [
            {"score": p.score, "payload": p.payload, "id": str(p.id)}
            for p in results.points
        ]

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def get_stats(self, collection: str | None = None) -> dict[str, Any]:
        client = await self._get_client()
        col = collection or self._settings.qdrant_collection
        try:
            info = await client.get_collection(col)
            return {
                "vectors_count": info.vectors_count,
                "points_count": info.points_count,
                "status": str(info.status),
            }
        except Exception:
            return {}
