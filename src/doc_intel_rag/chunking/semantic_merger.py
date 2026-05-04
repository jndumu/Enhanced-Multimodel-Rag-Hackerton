"""Merge tiny adjacent text chunks whose embeddings are semantically similar."""

from __future__ import annotations

import numpy as np
from loguru import logger

from doc_intel_rag.chunking.schemas import Chunk, ChunkModality
from doc_intel_rag.utils.token_utils import count_tokens

_MERGE_MAX_TOKENS = 64
_SIMILARITY_THRESHOLD = 0.85


async def semantic_merge(
    chunks: list[Chunk],
    embedder: object,
    threshold: float = _SIMILARITY_THRESHOLD,
) -> list[Chunk]:
    """Embed all text chunks under _MERGE_MAX_TOKENS tokens and merge consecutive similar ones."""
    from doc_intel_rag.ingestion.embedder import DocumentEmbedder

    assert isinstance(embedder, DocumentEmbedder)

    tiny_indices = [
        i for i, c in enumerate(chunks)
        if c.modality == ChunkModality.TEXT and c.token_count < _MERGE_MAX_TOKENS
    ]

    if len(tiny_indices) < 2:
        return chunks

    texts = [chunks[i].text for i in tiny_indices]
    try:
        embeddings = await embedder.embed_texts(texts)
    except Exception as exc:
        logger.warning("Semantic merge skipped — embedding failed", error=str(exc))
        return chunks

    emb_map = dict(zip(tiny_indices, embeddings))

    merged: list[Chunk] = []
    i = 0
    while i < len(chunks):
        chunk = chunks[i]

        if i not in emb_map or i + 1 >= len(chunks) or i + 1 not in emb_map:
            merged.append(chunk)
            i += 1
            continue

        emb_a = np.array(emb_map[i])
        emb_b = np.array(emb_map[i + 1])
        sim = float(np.dot(emb_a, emb_b) / (np.linalg.norm(emb_a) * np.linalg.norm(emb_b) + 1e-9))

        if sim >= threshold:
            next_chunk = chunks[i + 1]
            merged_text = chunk.text + "\n\n" + next_chunk.text
            merged_chunk = Chunk(
                doc_id=chunk.doc_id,
                source_file=chunk.source_file,
                page=chunk.page,
                element_types=list(dict.fromkeys(chunk.element_types + next_chunk.element_types)),
                modality=ChunkModality.TEXT,
                text=merged_text,
                is_atomic=False,
                token_count=count_tokens(merged_text),
                section_path=chunk.section_path,
                confidence=min(chunk.confidence, next_chunk.confidence),
            )
            merged.append(merged_chunk)
            i += 2
        else:
            merged.append(chunk)
            i += 1

    logger.debug(
        "Semantic merge done",
        before=len(chunks),
        after=len(merged),
        merged=len(chunks) - len(merged),
    )
    return merged
