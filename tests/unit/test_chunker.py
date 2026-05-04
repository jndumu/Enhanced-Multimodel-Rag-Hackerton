"""Unit tests for the document chunker."""

from __future__ import annotations

import os
os.environ["DOC_INTEL_SKIP_VALIDATION"] = "1"

import pytest

from doc_intel_rag.chunking.document_chunker import document_aware_chunking
from doc_intel_rag.chunking.schemas import ChunkModality
from doc_intel_rag.config import reset_settings
from doc_intel_rag.parsing.entity_types import EntityLabel
from doc_intel_rag.parsing.pipeline import BBox, ParsedElement, ParseResult


def _make_result(elements: list[ParsedElement]) -> ParseResult:
    return ParseResult(
        doc_id="test-doc-id",
        source_file="test.pdf",
        page_count=1,
        elements=elements,
    )


def _text_elem(text: str, label: EntityLabel = EntityLabel.PARAGRAPH, page: int = 1) -> ParsedElement:
    return ParsedElement(label=label, text=text, page=page, confidence=0.9)


def _atomic_elem(label: EntityLabel, text: str = "content", page: int = 1) -> ParsedElement:
    return ParsedElement(label=label, text=text, page=page, confidence=0.95)


@pytest.fixture(autouse=True)
def reset():
    reset_settings()
    yield
    reset_settings()


def test_atomic_elements_are_never_split():
    atomic_labels = [EntityLabel.TABLE, EntityLabel.FORMULA, EntityLabel.CODE_BLOCK]
    for label in atomic_labels:
        elements = [_atomic_elem(label, "x" * 100)]
        result = _make_result(elements)
        chunks = document_aware_chunking(result)
        assert len(chunks) == 1
        assert chunks[0].is_atomic
        assert label in chunks[0].element_types


def test_title_prepended_to_next_chunk():
    elements = [
        _text_elem("Introduction", label=EntityLabel.SECTION_TITLE),
        _text_elem("This is the introduction paragraph."),
    ]
    result = _make_result(elements)
    chunks = document_aware_chunking(result)
    # Section title updates section_path; the paragraph chunk carries it
    text_chunks = [c for c in chunks if not c.is_atomic]
    assert len(text_chunks) >= 1
    assert any("Introduction" in c.section_path for c in text_chunks)


def test_section_path_breadcrumb():
    elements = [
        _text_elem("My Document", label=EntityLabel.DOCUMENT_TITLE),
        _text_elem("Chapter 1", label=EntityLabel.SECTION_TITLE),
        _text_elem("Section 1.1", label=EntityLabel.SUBSECTION_TITLE),
        _text_elem("Body text here."),
    ]
    result = _make_result(elements)
    chunks = document_aware_chunking(result)
    body_chunks = [c for c in chunks if not c.is_atomic and "Body text" in c.text]
    assert body_chunks, "Expected a body chunk"
    section_path = body_chunks[0].section_path
    assert any("Chapter 1" in s for s in section_path)
    assert any("Section 1.1" in s for s in section_path)


def test_skip_entities_not_in_output():
    elements = [
        ParsedElement(label=EntityLabel.PAGE_NUMBER, text="1", page=1, confidence=1.0),
        ParsedElement(label=EntityLabel.HEADER, text="My Header", page=1, confidence=1.0),
        _text_elem("Real content"),
    ]
    result = _make_result(elements)
    chunks = document_aware_chunking(result)
    for chunk in chunks:
        assert "My Header" not in chunk.text
        assert chunk.text != "1"


def test_text_accumulation_creates_single_chunk_for_short_texts():
    elements = [_text_elem(f"Short paragraph {i}.") for i in range(5)]
    result = _make_result(elements)
    chunks = document_aware_chunking(result)
    text_chunks = [c for c in chunks if not c.is_atomic]
    # All short paragraphs should be in a single chunk (well under max_tokens)
    assert len(text_chunks) == 1


def test_image_chunk_has_correct_modality():
    elements = [_atomic_elem(EntityLabel.FIGURE, "figure content")]
    result = _make_result(elements)
    chunks = document_aware_chunking(result)
    assert chunks[0].modality == ChunkModality.IMAGE


def test_graph_chunk_has_graph_modality():
    elements = [_atomic_elem(EntityLabel.FLOWCHART, "flowchart content")]
    result = _make_result(elements)
    chunks = document_aware_chunking(result)
    assert chunks[0].modality == ChunkModality.GRAPH
