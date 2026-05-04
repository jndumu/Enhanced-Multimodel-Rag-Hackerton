"""In-memory NetworkX graph store with optional Neo4j export."""

from __future__ import annotations

from typing import Any

import networkx as nx
from loguru import logger


class GraphStore:
    """In-memory per-document knowledge graph store.

    Maintains one ``networkx.DiGraph`` per ingested document.  When a new
    graph is added for an existing ``doc_id`` the new edges are merged via
    ``nx.compose`` rather than replacing the existing graph.

    For large deployments the graphs can be exported to Neo4j via
    :meth:`export_to_neo4j` when ``NEO4J_URI`` is configured.
    """

    def __init__(self) -> None:
        self._graphs: dict[str, nx.DiGraph] = {}

    def add_graph(self, doc_id: str, graph_json: dict[str, Any]) -> None:
        """Deserialise a graph JSON payload and merge it into the store.

        Args:
            doc_id: SHA-256 hex digest identifying the source document.
            graph_json: Dict with ``"nodes"`` and ``"edges"`` lists as produced
                by :meth:`~doc_intel_rag.parsing.graph_extractor.GraphExtractor.serialize`.
        """
        g: nx.DiGraph = nx.DiGraph()
        for node in graph_json.get("nodes", []):
            nid = node["id"]
            g.add_node(nid, **{k: v for k, v in node.items() if k != "id"})
        for edge in graph_json.get("edges", []):
            g.add_edge(
                edge["source"], edge["target"],
                **{k: v for k, v in edge.items() if k not in ("source", "target")},
            )

        if doc_id in self._graphs:
            self._graphs[doc_id] = nx.compose(self._graphs[doc_id], g)
        else:
            self._graphs[doc_id] = g

        logger.debug(
            "Graph updated",
            doc_id=doc_id[:12],
            nodes=g.number_of_nodes(),
            edges=g.number_of_edges(),
        )

    def get_graph(self, doc_id: str) -> nx.DiGraph | None:
        return self._graphs.get(doc_id)

    def get_neighbors(self, doc_id: str, node_id: str, depth: int = 2) -> list[str]:
        """Return all node IDs reachable within *depth* hops from *node_id*."""
        g = self._graphs.get(doc_id)
        if g is None or node_id not in g:
            return []
        reachable: set[str] = set()
        frontier = {node_id}
        for _ in range(depth):
            next_frontier: set[str] = set()
            for n in frontier:
                next_frontier.update(g.successors(n))
                next_frontier.update(g.predecessors(n))
            next_frontier -= reachable | {node_id}
            reachable.update(next_frontier)
            frontier = next_frontier
        return list(reachable)

    def serialize(self, doc_id: str) -> dict[str, Any] | None:
        g = self._graphs.get(doc_id)
        if g is None:
            return None
        return {
            "nodes": [{"id": n, **g.nodes[n]} for n in g.nodes],
            "edges": [
                {"source": u, "target": v, **g.edges[u, v]}
                for u, v in g.edges
            ],
        }

    def remove_doc(self, doc_id: str) -> None:
        self._graphs.pop(doc_id, None)

    async def export_to_neo4j(self, doc_id: str, uri: str, user: str, password: str) -> None:
        """Export this doc's graph to Neo4j via Bolt."""
        g = self._graphs.get(doc_id)
        if g is None:
            return
        try:
            from neo4j import AsyncGraphDatabase

            async with AsyncGraphDatabase.driver(uri, auth=(user, password)) as driver:
                async with driver.session() as session:
                    for node_id, attrs in g.nodes(data=True):
                        label = attrs.get("type", "Entity")
                        name = attrs.get("label", node_id)
                        await session.run(
                            f"MERGE (n:{label} {{id: $id}}) SET n.name = $name, n.doc_id = $doc_id",
                            id=node_id, name=name, doc_id=doc_id,
                        )
                    for u, v, attrs in g.edges(data=True):
                        rel = attrs.get("relation", "RELATED_TO").upper().replace(" ", "_").replace("-", "_")
                        await session.run(
                            f"MATCH (a {{id: $src}}), (b {{id: $tgt}}) MERGE (a)-[:{rel}]->(b)",
                            src=u, tgt=v,
                        )
            logger.info("Graph exported to Neo4j", doc_id=doc_id[:12])
        except ImportError:
            logger.warning("neo4j driver not installed — skipping export")
        except Exception as exc:
            logger.warning("Neo4j export failed", error=str(exc))
