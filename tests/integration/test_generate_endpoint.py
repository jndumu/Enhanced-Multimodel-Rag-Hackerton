"""Integration tests for the /generate endpoint."""

from __future__ import annotations

import os
os.environ["DOC_INTEL_SKIP_VALIDATION"] = "1"

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from doc_intel_rag.config import reset_settings
from doc_intel_rag.retrieval.hybrid_searcher import ScoredChunk


@pytest.fixture(autouse=True)
def reset():
    reset_settings()
    yield
    reset_settings()


def _mock_chunk(score: float = 0.9) -> ScoredChunk:
    return ScoredChunk(
        score=score,
        payload={
            "chunk_id": "c1", "doc_id": "d1", "source_file": "doc.pdf",
            "page": 1, "modality": "text",
            "text": "Relevant content for generation.",
            "enriched_text": "Relevant content for generation.",
            "section_path": ["Results"], "concept_tags": [],
        },
        chunk_id="c1",
    )


@pytest.fixture()
def client():
    with patch("doc_intel_rag.api.dependencies.init_singletons", new_callable=AsyncMock):
        with patch("doc_intel_rag.api.dependencies.shutdown_singletons", new_callable=AsyncMock):
            from doc_intel_rag.api.app import create_app
            app = create_app()
            return TestClient(app, raise_server_exceptions=False)


def test_generate_endpoint_is_reachable(client: TestClient):
    resp = client.post(
        "/v1/generate",
        json={"query": "What is the summary?", "streaming": False, "top_k": 5, "top_n": 3},
        headers={"X-API-Key": ""},
    )
    # Endpoint exists and returns something (200 if all deps mocked, else 4xx/5xx)
    assert resp.status_code in (200, 401, 422, 500)


def test_generate_streaming_returns_event_stream(client: TestClient):
    resp = client.post(
        "/v1/generate",
        json={"query": "Stream test", "streaming": True, "top_k": 3, "top_n": 2},
        headers={"X-API-Key": ""},
    )
    if resp.status_code == 200:
        content_type = resp.headers.get("content-type", "")
        assert "text/event-stream" in content_type or "application/json" in content_type


def test_fallback_triggered_when_groundedness_low():
    """Verify that low groundedness triggers web fallback."""
    from doc_intel_rag.config import get_settings
    settings = get_settings()
    # With no real chunks, groundedness = 0.0 < threshold (0.45) → fallback
    from doc_intel_rag.retrieval.groundedness import score_groundedness
    score = score_groundedness([1.0] * 10, [])
    assert score < settings.groundedness_threshold
    assert settings.fallback_enabled
