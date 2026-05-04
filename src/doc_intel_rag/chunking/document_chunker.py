"""Document-aware hierarchical chunker with atomic element support and overlap."""

from __future__ import annotations

from typing import Any

from loguru import logger

from doc_intel_rag.chunking.schemas import Chunk, ChunkModality, modality_from_str
from doc_intel_rag.config import Settings, get_settings
from doc_intel_rag.parsing.entity_types import (
    ATOMIC_ENTITIES,
    ENTITY_TO_MODALITY,
    SKIP_ENTITIES,
    TITLE_ENTITIES,
    EntityLabel,
)
from doc_intel_rag.parsing.pipeline import ParseResult, ParsedElement
from doc_intel_rag.utils.token_utils import count_tokens, truncate_to_tokens


def document_aware_chunking(
    parse_result: ParseResult,
    settings: Settings | None = None,
) -> list[Chunk]:
    """Convert a ParseResult into a list of Chunks following the chunking strategy."""
    cfg = settings or get_settings()
    chunker = _Chunker(
        doc_id=parse_result.doc_id,
        source_file=parse_result.source_file,
        max_tokens=cfg.max_chunk_tokens,
        overlap_tokens=cfg.chunk_overlap_tokens,
    )
    return chunker.process(parse_result.elements)


class _Chunker:
    def __init__(
        self,
        doc_id: str,
        source_file: str,
        max_tokens: int,
        overlap_tokens: int,
    ) -> None:
        self._doc_id = doc_id
        self._source_file = source_file
        self._max_tokens = max_tokens
        self._overlap_tokens = overlap_tokens

        self._section_path: list[str] = []
        self._pending_title: str | None = None

        # Accumulator for the current text chunk being built
        self._acc_texts: list[str] = []
        self._acc_types: list[EntityLabel] = []
        self._acc_page: int = 1
        self._acc_tokens: int = 0
        self._acc_confidence: float = 1.0

        self._chunks: list[Chunk] = []

    def process(self, elements: list[ParsedElement]) -> list[Chunk]:
        for elem in elements:
            self._handle(elem)
        self._flush()
        logger.debug(
            "Chunking complete",
            doc_id=self._doc_id[:12],
            chunks=len(self._chunks),
        )
        return self._chunks

    def _handle(self, elem: ParsedElement) -> None:
        if elem.label in SKIP_ENTITIES:
            return

        # Update section path for title labels
        if elem.label in TITLE_ENTITIES and elem.label not in {
            EntityLabel.FIGURE_CAPTION, EntityLabel.TABLE_CAPTION
        }:
            self._flush()
            self._update_section_path(elem)
            self._pending_title = elem.text
            return

        # Atomic elements: one chunk each
        if elem.label in ATOMIC_ENTITIES:
            self._flush()
            chunk = self._make_atomic_chunk(elem)
            self._chunks.append(chunk)
            return

        # Caption labels: flush, emit as tiny text chunk, store for next atomic
        if elem.label in {EntityLabel.FIGURE_CAPTION, EntityLabel.TABLE_CAPTION}:
            self._flush()
            self._pending_title = elem.text
            return

        # Accumulative text elements
        self._accumulate(elem)

    def _update_section_path(self, elem: ParsedElement) -> None:
        match elem.label:
            case EntityLabel.DOCUMENT_TITLE:
                self._section_path = [elem.text]
            case EntityLabel.SECTION_TITLE:
                self._section_path = [self._section_path[0]] + [elem.text] if self._section_path else [elem.text]
            case EntityLabel.SUBSECTION_TITLE:
                base = self._section_path[:2] if len(self._section_path) >= 2 else self._section_path
                self._section_path = base + [elem.text]

    def _accumulate(self, elem: ParsedElement) -> None:
        text = elem.text.strip()
        if not text:
            return

        tok = count_tokens(text)

        if self._acc_tokens + tok > self._max_tokens and self._acc_texts:
            self._flush()
            # Carry overlap from previous chunk
            self._seed_overlap()

        prefix = ""
        if self._pending_title and not self._acc_texts:
            prefix = f"{self._pending_title}\n\n"
            self._pending_title = None

        self._acc_texts.append(prefix + text)
        self._acc_types.append(elem.label)
        self._acc_page = elem.page
        self._acc_tokens += tok + count_tokens(prefix)
        self._acc_confidence = min(self._acc_confidence, elem.confidence)

    def _seed_overlap(self) -> None:
        """Carry the last overlap_tokens worth of text into the new accumulator."""
        if not self._acc_texts:
            return
        tail = " ".join(self._acc_texts)
        overlap_text = truncate_to_tokens(tail, self._overlap_tokens, from_end=True)
        if overlap_text:
            self._acc_texts = [overlap_text]
            self._acc_tokens = count_tokens(overlap_text)
        else:
            self._acc_texts = []
            self._acc_tokens = 0
        self._acc_types = []

    def _flush(self) -> None:
        if not self._acc_texts:
            return

        text = "\n\n".join(self._acc_texts)
        chunk = Chunk(
            doc_id=self._doc_id,
            source_file=self._source_file,
            page=self._acc_page,
            element_types=list(dict.fromkeys(self._acc_types)),
            modality=ChunkModality.TEXT,
            text=text,
            is_atomic=False,
            token_count=count_tokens(text),
            section_path=list(self._section_path),
            confidence=self._acc_confidence,
        )
        self._chunks.append(chunk)

        self._acc_texts = []
        self._acc_types = []
        self._acc_tokens = 0
        self._acc_confidence = 1.0

    def _make_atomic_chunk(self, elem: ParsedElement) -> Chunk:
        modality = modality_from_str(ENTITY_TO_MODALITY[elem.label])
        text_parts = []
        if self._pending_title:
            text_parts.append(self._pending_title)
            self._pending_title = None
        if elem.text:
            text_parts.append(elem.text)

        text = "\n\n".join(text_parts) or f"[{elem.label.value}]"

        return Chunk(
            doc_id=self._doc_id,
            source_file=self._source_file,
            page=elem.page,
            element_types=[elem.label],
            modality=modality,
            text=text,
            latex=elem.latex,
            html=elem.html,
            raw_image_b64=elem.raw_image_b64,
            bbox=elem.bbox,
            is_atomic=True,
            token_count=count_tokens(text),
            section_path=list(self._section_path),
            confidence=elem.confidence,
        )
