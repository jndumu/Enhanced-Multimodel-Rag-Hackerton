"""Unit tests for the groundedness scorer."""

from __future__ import annotations

import os
os.environ["DOC_INTEL_SKIP_VALIDATION"] = "1"

import pytest

from doc_intel_rag.retrieval.groundedness import score_groundedness
from doc_intel_rag.retrieval.hybrid_searcher import ScoredChunk


def _make_chunk(score: float, text: str = "test") -> ScoredChunk:
    return ScoredChunk(
        score=score,
        payload={"text": text, "modality": "text", "doc_id": "d1",
                 "source_file": "f.pdf", "page": 1, "section_path": []},
        chunk_id="c1",
    )


def test_empty_chunks_returns_zero():
    emb = [0.1, 0.2, 0.3]
    assert score_groundedness(emb, []) == 0.0


def test_zero_query_embedding_uses_chunk_scores():
    # query_embedding is reserved for future cosine-sim use; score is chunk-score-based
    chunks = [_make_chunk(0.9)]
    score = score_groundedness([0.0, 0.0, 0.0], chunks)
    assert 0.0 < score <= 1.0, f"Expected positive score from high-scoring chunk, got {score}"


def test_high_score_chunks_above_threshold():
    emb = [1.0] * 10
    chunks = [_make_chunk(0.95), _make_chunk(0.90), _make_chunk(0.85)]
    score = score_groundedness(emb, chunks)
    assert score > 0.4, f"Expected groundedness > 0.4, got {score}"


def test_low_score_chunks_below_threshold():
    emb = [1.0] * 10
    chunks = [_make_chunk(0.05), _make_chunk(0.03), _make_chunk(0.01)]
    score = score_groundedness(emb, chunks)
    # Low retrieval scores → low groundedness
    assert score < 0.5, f"Expected groundedness < 0.5, got {score}"


def test_score_is_bounded():
    emb = [0.5] * 128
    for s in [0.01, 0.5, 0.99, 1.0]:
        chunks = [_make_chunk(s)]
        score = score_groundedness(emb, chunks)
        assert 0.0 <= score <= 1.0
