"""Chunk data model — shared contract between chunking, enrichment, ingestion, and retrieval."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from doc_intel_rag.parsing.entity_types import EntityLabel
from doc_intel_rag.parsing.pipeline import BBox


class ChunkModality(str, Enum):
    """Content modality of a :class:`Chunk`.

    Used by the embedder to select the correct Qdrant named vector and by the
    enrichment pipeline to route each chunk to the appropriate captioner.
    """

    TEXT      = "text"
    IMAGE     = "image"
    TABLE     = "table"
    FORMULA   = "formula"
    ALGORITHM = "algorithm"
    GRAPH     = "graph"
    CODE      = "code"
    MIXED     = "mixed"


_MODALITY_STR_TO_ENUM: dict[str, ChunkModality] = {m.value: m for m in ChunkModality}


def modality_from_str(s: str) -> ChunkModality:
    """Convert a raw modality string to its :class:`ChunkModality` enum member.

    Args:
        s: Lowercase modality string (e.g. ``"image"``).

    Returns:
        The matching ``ChunkModality``, or ``ChunkModality.TEXT`` for unknown values.
    """
    return _MODALITY_STR_TO_ENUM.get(s, ChunkModality.TEXT)


@dataclass
class Chunk:
    """A discrete unit of indexed content produced by the chunking pipeline.

    Atomic visual elements (tables, formulas, figures, graphs, algorithms, code)
    are always one ``Chunk`` with ``is_atomic=True``.  Text is accumulated up to
    ``max_chunk_tokens`` with ``chunk_overlap_tokens`` carried into the next chunk.

    Attributes:
        chunk_id: UUID4 assigned at creation; used as the Qdrant point ID.
        doc_id: SHA-256 hex digest of the source file bytes.
        source_file: Absolute path or URL of the ingested document.
        page: 1-based page number where this chunk originates.
        element_types: One or more :class:`~doc_intel_rag.parsing.entity_types.EntityLabel`
            values present in this chunk.
        modality: Dominant content type determining which embedding vector to use.
        text: Markdown/verbal representation of the content.
        latex: Raw LaTeX string for formula chunks.
        html: HTML table markup for table chunks.
        raw_image_b64: Base64-encoded PNG crop for visual elements.
        bbox: Bounding box of the element on its source page.
        is_atomic: ``True`` when the chunk must never be split or merged.
        token_count: Approximate token count of :attr:`text` (tiktoken cl100k_base).
        section_path: Breadcrumb from document root to the nearest section title.
        cross_refs: Chunk IDs of elements referenced by ``"see Figure 3"``-style text.
        graph_json: Serialised NetworkX DiGraph for relationship-graph chunks.
        concept_tags: Named entities and noun phrases extracted by spaCy NER.
        confidence: GLM-OCR layout detection confidence score (0–1).
        caption_json: Structured enrichment payload from the Mesh API captioner.
        enriched_text: Concatenation of ``text`` and ``caption_json`` summary used
            for dense embedding.
    """

    doc_id: str
    source_file: str
    page: int
    element_types: list[EntityLabel]
    modality: ChunkModality
    text: str
    chunk_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    latex: str | None = None
    html: str | None = None
    raw_image_b64: str | None = None
    bbox: BBox | None = None
    is_atomic: bool = False
    token_count: int = 0
    section_path: list[str] = field(default_factory=list)
    cross_refs: list[str] = field(default_factory=list)
    graph_json: dict[str, Any] | None = None
    concept_tags: list[str] = field(default_factory=list)
    confidence: float = 1.0
    # Enrichment output stored alongside text for Qdrant payload
    caption_json: dict[str, Any] | None = None
    enriched_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialise the chunk to a plain dict suitable for Qdrant payload storage.

        The ``raw_image_b64`` field is intentionally excluded — the caller in
        :mod:`doc_intel_rag.ingestion.vector_store` strips it before upserting
        to avoid inflating payload sizes.

        Returns:
            A JSON-serialisable dictionary of all chunk fields.
        """
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "source_file": self.source_file,
            "page": self.page,
            "element_types": [e.value for e in self.element_types],
            "modality": self.modality.value,
            "text": self.text,
            "latex": self.latex,
            "html": self.html,
            "is_atomic": self.is_atomic,
            "token_count": self.token_count,
            "section_path": self.section_path,
            "cross_refs": self.cross_refs,
            "graph_json": self.graph_json,
            "concept_tags": self.concept_tags,
            "confidence": self.confidence,
            "caption_json": self.caption_json,
            "enriched_text": self.enriched_text,
        }
