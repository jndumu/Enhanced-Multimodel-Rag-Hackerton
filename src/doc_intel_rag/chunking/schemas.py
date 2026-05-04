"""Chunk data model — shared contract between chunking, enrichment, ingestion, and retrieval."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from doc_intel_rag.parsing.entity_types import EntityLabel
from doc_intel_rag.parsing.pipeline import BBox


class ChunkModality(str, Enum):
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
    return _MODALITY_STR_TO_ENUM.get(s, ChunkModality.TEXT)


@dataclass
class Chunk:
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
