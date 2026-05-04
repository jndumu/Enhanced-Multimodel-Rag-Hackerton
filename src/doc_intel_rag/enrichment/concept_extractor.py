"""NER-based concept tagging using spaCy (en_core_web_trf or sm fallback)."""

from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Any

from loguru import logger

from doc_intel_rag.chunking.schemas import Chunk


@lru_cache(maxsize=1)
def _load_nlp() -> Any:
    try:
        import spacy
        return spacy.load("en_core_web_trf")
    except (ImportError, OSError):
        pass
    try:
        import spacy
        return spacy.load("en_core_web_sm")
    except (ImportError, OSError):
        logger.warning("No spaCy model available — concept extraction disabled")
        return None


async def extract_concepts(chunk: Chunk) -> Chunk:
    """Run NER on chunk text and populate concept_tags."""
    nlp = _load_nlp()
    if nlp is None or not chunk.text:
        return chunk

    loop = asyncio.get_event_loop()
    doc = await loop.run_in_executor(None, nlp, chunk.text[:5000])

    tags: list[str] = []

    for ent in doc.ents:
        tag = f"{ent.text.strip()}:{ent.label_}"
        if tag not in tags:
            tags.append(tag)

    # Key noun chunks (top 10 by length to avoid noise)
    noun_chunks = sorted(
        {nc.text.strip().lower() for nc in doc.noun_chunks if len(nc.text.strip()) > 3},
        key=len,
        reverse=True,
    )[:10]
    for nc in noun_chunks:
        if nc not in tags:
            tags.append(nc)

    chunk.concept_tags = tags
    return chunk


async def enrich_chunks_concepts(chunks: list[Chunk]) -> list[Chunk]:
    tasks = [extract_concepts(c) for c in chunks]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.warning("Concept extraction failed", chunk_id=chunks[i].chunk_id, error=str(r))
    return chunks
