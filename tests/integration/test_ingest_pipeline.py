"""Integration tests for the ingest pipeline (mocked external calls)."""

from __future__ import annotations

import os
os.environ["DOC_INTEL_SKIP_VALIDATION"] = "1"

import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from doc_intel_rag.config import reset_settings
from doc_intel_rag.parsing.entity_types import EntityLabel
from doc_intel_rag.parsing.pipeline import ParsedElement, ParseResult


@pytest.fixture(autouse=True)
def reset():
    """Reset settings cache between tests."""
    reset_settings()
    yield
    reset_settings()


def _make_parse_result() -> ParseResult:
    """Build a minimal ParseResult with known doc_id for assertion."""
    return ParseResult(
        doc_id="abc123",
        source_file="test.pdf",
        page_count=2,
        elements=[
            ParsedElement(label=EntityLabel.SECTION_TITLE, text="Introduction", page=1, confidence=0.9),
            ParsedElement(label=EntityLabel.PARAGRAPH, text="This is test content.", page=1, confidence=0.85),
            ParsedElement(label=EntityLabel.TABLE, text="| Col1 | Col2 |", page=2, confidence=0.88),
        ],
    )


@pytest.mark.asyncio
async def test_ingest_pipeline_produces_chunks_and_upserts():
    """Full ingest path calls upsert_chunks with the parsed chunks."""
    from doc_intel_rag.api.routes.ingest import _run_ingest
    from doc_intel_rag.ingestion.embedder import DocumentEmbedder
    from doc_intel_rag.ingestion.graph_store import GraphStore
    from doc_intel_rag.ingestion.vector_store import QdrantDocumentStore

    mock_vs = AsyncMock(spec=QdrantDocumentStore)
    mock_vs.doc_exists.return_value = False
    mock_vs.upsert_chunks.return_value = 3
    mock_vs._get_client = AsyncMock(return_value=MagicMock())
    mock_vs.ensure_collection = AsyncMock()
    mock_vs._settings = MagicMock()
    mock_vs._settings.qdrant_collection = "test_col"
    mock_vs._settings.ingest_batch_size = 64

    mock_emb = AsyncMock(spec=DocumentEmbedder)
    mock_emb.embed_texts.return_value = [[0.1] * 10, [0.2] * 10, [0.3] * 10]
    mock_emb.sparse_encode.return_value = {1: 0.5, 2: 0.3}

    mock_gs = GraphStore()

    # Patch at the source module where these are defined
    with patch("doc_intel_rag.parsing.pipeline.DocumentParser") as MockParser, \
         patch("doc_intel_rag.enrichment.captioner.enrich_chunks", new_callable=AsyncMock) as mock_enrich, \
         patch("doc_intel_rag.enrichment.concept_extractor.enrich_chunks_concepts", new_callable=AsyncMock) as mock_concepts, \
         patch("doc_intel_rag.ingestion.graph_embedder.embed_graph", new_callable=AsyncMock) as mock_ge:

        mock_parser_instance = AsyncMock()
        mock_parser_instance.parse.return_value = _make_parse_result()
        MockParser.return_value = mock_parser_instance
        mock_enrich.side_effect = lambda chunks, settings=None: chunks
        mock_concepts.side_effect = lambda chunks: chunks
        mock_ge.return_value = None

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4")
            tmp_path = f.name

        try:
            result = await _run_ingest(
                source=tmp_path,
                collection="test_col",
                enrich=False,
                force=False,
                vector_store=mock_vs,
                embedder=mock_emb,
                graph_store=mock_gs,
                query_cache=None,
            )
            assert result.doc_id == "abc123"
            assert result.chunk_count > 0
            mock_vs.upsert_chunks.assert_called_once()
        finally:
            os.unlink(tmp_path)


@pytest.mark.asyncio
async def test_ingest_idempotent_returns_cached():
    """Re-ingesting the same doc_id returns cached=True without calling upsert."""
    from doc_intel_rag.api.routes.ingest import _run_ingest
    from doc_intel_rag.ingestion.embedder import DocumentEmbedder
    from doc_intel_rag.ingestion.graph_store import GraphStore
    from doc_intel_rag.ingestion.vector_store import QdrantDocumentStore

    mock_vs = AsyncMock(spec=QdrantDocumentStore)
    mock_vs.doc_exists.return_value = True  # Already ingested
    mock_vs.upsert_chunks = AsyncMock()

    mock_emb = AsyncMock(spec=DocumentEmbedder)

    with patch("doc_intel_rag.parsing.pipeline.DocumentParser") as MockParser:
        mock_parser_instance = AsyncMock()
        mock_parser_instance.parse.return_value = _make_parse_result()
        MockParser.return_value = mock_parser_instance

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4")
            tmp_path = f.name

        try:
            result = await _run_ingest(
                source=tmp_path,
                collection="test_col",
                enrich=False,
                force=False,
                vector_store=mock_vs,
                embedder=mock_emb,
                graph_store=GraphStore(),
                query_cache=None,
            )
            assert result.cached is True
            assert result.chunk_count == 0
            mock_vs.upsert_chunks.assert_not_called()
        finally:
            os.unlink(tmp_path)
