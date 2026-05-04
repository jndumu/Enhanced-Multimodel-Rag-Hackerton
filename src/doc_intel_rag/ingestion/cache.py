"""Redis async cache for embeddings and query results."""

from __future__ import annotations

import json
from typing import Any

from loguru import logger


class EmbeddingCache:
    """Redis-backed async cache for dense embedding vectors.

    Keys are SHA-256 hashes of ``"{model}:{text}"`` so cache entries are
    invalidated automatically when the embedding model changes.

    Args:
        redis_client: An ``redis.asyncio`` client instance.
        ttl: Time-to-live in seconds (default 86 400 = 1 day).
    """

    def __init__(self, redis_client: Any, ttl: int = 86400) -> None:
        self._r = redis_client
        self._ttl = ttl

    async def get(self, key: str) -> str | None:
        try:
            value = await self._r.get(key)
            return value.decode() if isinstance(value, bytes) else value
        except Exception as exc:
            logger.debug("Cache get failed", key=key, error=str(exc))
            return None

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        try:
            await self._r.set(key, value, ex=ex or self._ttl)
        except Exception as exc:
            logger.debug("Cache set failed", key=key, error=str(exc))


class QueryCache:
    """Redis-backed async cache for full retrieval result lists.

    Caches ``(query, top_k, filters)`` → ``list[ScoredChunk]`` responses so
    repeat identical queries are served without hitting Qdrant or the reranker.

    All keys are prefixed with ``"qcache:"`` so :meth:`flush_all` only removes
    query cache entries, leaving embedding entries untouched.  Entries are
    invalidated per ``doc_id`` after re-ingestion via :meth:`invalidate_doc`.

    Args:
        redis_client: An ``redis.asyncio`` client instance.
        ttl: Time-to-live in seconds (default 3 600 = 1 hour).
    """

    _PREFIX = "qcache:"

    def __init__(self, redis_client: Any, ttl: int = 3600) -> None:
        self._r = redis_client
        self._ttl = ttl

    async def get(self, key: str) -> list[dict[str, Any]] | None:
        try:
            raw = await self._r.get(f"{self._PREFIX}{key}")
            if raw:
                data = raw.decode() if isinstance(raw, bytes) else raw
                return json.loads(data)
        except Exception as exc:
            logger.debug("QueryCache get failed", error=str(exc))
        return None

    async def set(self, key: str, results: list[dict[str, Any]]) -> None:
        try:
            await self._r.set(
                f"{self._PREFIX}{key}",
                json.dumps(results),
                ex=self._ttl,
            )
        except Exception as exc:
            logger.debug("QueryCache set failed", error=str(exc))

    async def invalidate_doc(self, doc_id: str) -> None:
        """Remove all cached queries associated with a re-ingested doc."""
        try:
            pattern = f"{self._PREFIX}*{doc_id}*"
            keys = await self._r.keys(pattern)
            if keys:
                await self._r.delete(*keys)
                logger.debug("QueryCache invalidated", doc_id=doc_id[:12], keys=len(keys))
        except Exception as exc:
            logger.debug("QueryCache invalidate failed", error=str(exc))

    async def flush_all(self) -> int:
        try:
            keys = await self._r.keys(f"{self._PREFIX}*")
            if keys:
                await self._r.delete(*keys)
            return len(keys)
        except Exception:
            return 0


async def create_redis_client(url: str) -> Any:
    """Create and return a connected ``redis.asyncio`` client.

    Args:
        url: Redis connection URL (e.g. ``"redis://localhost:6379"``).

    Returns:
        An ``redis.asyncio`` client configured with ``decode_responses=False``
        so raw bytes are preserved for JSON deserialisation.
    """
    import redis.asyncio as aioredis
    client = aioredis.from_url(url, decode_responses=False)
    return client
