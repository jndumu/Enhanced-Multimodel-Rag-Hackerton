"""node2vec graph embeddings — 128-dim averaged per-chunk graph vector."""

from __future__ import annotations

from typing import Any

import numpy as np
from loguru import logger


_GRAPH_EMBED_DIM = 128


async def embed_graph(graph_json: dict[str, Any]) -> list[float] | None:
    """Run node2vec on the graph and return the averaged node embedding."""
    try:
        import networkx as nx
        from node2vec import Node2Vec  # type: ignore[import-untyped]
        import asyncio

        g: nx.DiGraph = nx.DiGraph()
        for node in graph_json.get("nodes", []):
            g.add_node(node["id"])
        for edge in graph_json.get("edges", []):
            g.add_edge(edge["source"], edge["target"])

        if g.number_of_nodes() < 2:
            return None

        loop = asyncio.get_event_loop()
        embedding = await loop.run_in_executor(None, _run_node2vec, g)
        return embedding

    except ImportError:
        logger.warning("node2vec not installed — graph embeddings disabled")
        return None
    except Exception as exc:
        logger.warning("Graph embedding failed", error=str(exc))
        return None


def _run_node2vec(g: "Any") -> list[float]:
    from node2vec import Node2Vec  # type: ignore[import-untyped]

    n2v = Node2Vec(
        g,
        dimensions=_GRAPH_EMBED_DIM,
        walk_length=10,
        num_walks=20,
        workers=1,
        quiet=True,
    )
    model = n2v.fit(window=5, min_count=1, batch_words=4)
    vectors = np.array([
        model.wv[str(node)]
        for node in g.nodes
        if str(node) in model.wv
    ])
    if len(vectors) == 0:
        return [0.0] * _GRAPH_EMBED_DIM
    avg = vectors.mean(axis=0)
    norm = float(np.linalg.norm(avg))
    if norm > 0:
        avg = avg / norm
    return avg.tolist()


GRAPH_EMBED_DIM = _GRAPH_EMBED_DIM
