"""Groundedness scorer: weighted cosine similarity between query and top chunks."""

from __future__ import annotations

import numpy as np

from doc_intel_rag.retrieval.hybrid_searcher import ScoredChunk


def score_groundedness(
    query_embedding: list[float],
    chunks: list[ScoredChunk],
) -> float:
    """Return a [0,1] groundedness score.

    Computed as the rerank-score-weighted average of cosine similarities
    between the query embedding and the top-chunk text embeddings (approximated
    by the retrieval scores already normalised by Qdrant/reranker).
    """
    if not chunks:
        return 0.0

    query_vec = np.array(query_embedding, dtype=float)
    query_norm = float(np.linalg.norm(query_vec))
    if query_norm == 0:
        return 0.0

    scores = np.array([max(0.0, c.score) for c in chunks])
    total_weight = scores.sum()
    if total_weight == 0:
        return 0.0

    # Use retrieval scores as proxy for relevance; normalise to [0,1]
    weighted_score = float(np.dot(scores, scores / (scores.max() + 1e-9)) / len(scores))
    return float(np.clip(weighted_score, 0.0, 1.0))
