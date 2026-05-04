"""Dense (Mesh API) + sparse (BM25 feature-hashing) embedder with Redis cache."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

import numpy as np
from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from doc_intel_rag.config import Settings, get_settings

_SPARSE_BUCKETS = 2**17  # 131072 — same as reference project


class DocumentEmbedder:
    def __init__(self, settings: Settings | None = None, cache: "object | None" = None) -> None:
        self._settings = settings or get_settings()
        self._cache = cache  # EmbeddingCache | None
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                api_key=self._settings.mesh_api_key,
                base_url=self._settings.mesh_api_base_url,
            )
        return self._client

    # ── Public interface ──────────────────────────────────────────────────────

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return dense embeddings for a list of texts, using Redis cache."""
        if not texts:
            return []

        results: list[list[float] | None] = [None] * len(texts)
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []

        for i, text in enumerate(texts):
            cached = await self._cache_get(text)
            if cached is not None:
                results[i] = cached
            else:
                uncached_indices.append(i)
                uncached_texts.append(text)

        if uncached_texts:
            batch_size = 256
            fresh: list[list[float]] = []
            for start in range(0, len(uncached_texts), batch_size):
                batch = uncached_texts[start : start + batch_size]
                batch_embs = await self._embed_batch(batch)
                fresh.extend(batch_embs)
                for text, emb in zip(batch, batch_embs):
                    await self._cache_set(text, emb)

            for local_i, global_i in enumerate(uncached_indices):
                results[global_i] = fresh[local_i]

        return [r for r in results if r is not None]

    async def embed_query(self, query: str) -> list[float]:
        embs = await self.embed_texts([query])
        return embs[0] if embs else []

    def sparse_encode(self, text: str) -> dict[int, float]:
        """BM25 TF feature-hashing sparse vector (2^17 buckets)."""
        from sklearn.utils.murmurhash import murmurhash3_32  # type: ignore[import-untyped]

        tokens = text.lower().split()
        tf: dict[int, float] = {}
        for token in tokens:
            bucket = int(murmurhash3_32(token, positive=True)) % _SPARSE_BUCKETS
            tf[bucket] = tf.get(bucket, 0.0) + 1.0

        # TF normalisation
        max_tf = max(tf.values()) if tf else 1.0
        return {k: v / max_tf for k, v in tf.items()}

    # ── Internal ──────────────────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        client = self._get_client()
        response = await client.embeddings.create(
            model=self._settings.mesh_embedding_model,
            input=texts,
        )
        return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]

    async def _cache_get(self, text: str) -> list[float] | None:
        if self._cache is None:
            return None
        key = _cache_key(text, self._settings.mesh_embedding_model)
        try:
            raw = await self._cache.get(key)  # type: ignore[attr-defined]
            if raw:
                return json.loads(raw)
        except Exception:
            pass
        return None

    async def _cache_set(self, text: str, embedding: list[float]) -> None:
        if self._cache is None:
            return
        key = _cache_key(text, self._settings.mesh_embedding_model)
        try:
            await self._cache.set(  # type: ignore[attr-defined]
                key,
                json.dumps(embedding),
                ex=self._settings.redis_embedding_ttl,
            )
        except Exception:
            pass


def _cache_key(text: str, model: str) -> str:
    return "emb:" + hashlib.sha256(f"{model}:{text}".encode()).hexdigest()


def get_embedder(settings: Settings | None = None, cache: "object | None" = None) -> DocumentEmbedder:
    return DocumentEmbedder(settings=settings, cache=cache)
