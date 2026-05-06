"""Groundedness scorer: weighted average of reranker relevance scores."""

from __future__ import annotations

import numpy as np

from doc_intel_rag.retrieval.hybrid_searcher import ScoredChunk


def score_groundedness(
    query_embedding: list[float],
    chunks: list[ScoredChunk],
) -> float:
    """Estimate how well the retrieved chunks ground the query.

    Uses the calibrated reranker scores (Cohere/Jina return scores in [0,1])
    as the relevance signal.  A score below
    ``settings.groundedness_threshold`` (default 0.45) signals that the
    retrieved context is unlikely to support a faithful answer, triggering
    the Tavily web fallback.

    The score is the weighted average of the top-chunk scores, weighted by
    the scores themselves so that highly relevant chunks dominate:

        groundedness = Σ(score_i²) / Σ(score_i)

    Args:
        query_embedding: Dense embedding vector for the user query (reserved
            for future cosine-similarity extensions; not used in current impl
            because chunk embeddings are not stored in the Qdrant payload).
        chunks: Reranked candidate chunks from the retrieval pipeline.

    Returns:
        A float in ``[0, 1]``; higher values indicate that highly-scored
        chunks were retrieved and the answer is likely well-grounded.
    """
    if not chunks:
        return 0.0

    scores = np.array([max(0.0, c.score) for c in chunks], dtype=float)

    total = float(scores.sum())
    if total == 0.0:
        return 0.0

    # Self-weighted average: high-scoring chunks contribute quadratically
    weighted = float(np.dot(scores, scores) / total)
    return float(np.clip(weighted, 0.0, 1.0))
