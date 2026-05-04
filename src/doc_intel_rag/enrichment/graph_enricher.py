"""Enrich graph/diagram chunks with edge list, centrality, and Mesh API summary."""

from __future__ import annotations

import json
from typing import Any

import networkx as nx
from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from doc_intel_rag.chunking.schemas import Chunk, ChunkModality
from doc_intel_rag.config import Settings, get_settings


async def enrich_graph(chunk: Chunk, settings: Settings | None = None) -> Chunk:
    """Add edge list, centrality metrics, and natural-language summary to a graph chunk."""
    cfg = settings or get_settings()

    if chunk.modality != ChunkModality.GRAPH or not chunk.graph_json:
        return chunk

    graph = _deserialize(chunk.graph_json)
    if graph.number_of_nodes() == 0:
        return chunk

    edge_list = _build_edge_list(graph)
    top_node, centrality = _top_by_centrality(graph)
    summary = await _summarise(graph, top_node, cfg)

    enrichment_text = (
        f"Graph: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges.\n"
        f"Most connected entity: {top_node} (centrality={centrality:.3f}).\n"
        f"Summary: {summary}\n\n"
        f"Edges:\n{edge_list}"
    )

    chunk.enriched_text = f"{chunk.text}\n\n[Graph Enrichment]\n{enrichment_text}"
    return chunk


def _deserialize(graph_json: dict[str, Any]) -> nx.DiGraph:
    g: nx.DiGraph = nx.DiGraph()
    for node in graph_json.get("nodes", []):
        g.add_node(node["id"], **{k: v for k, v in node.items() if k != "id"})
    for edge in graph_json.get("edges", []):
        g.add_edge(edge["source"], edge["target"], **{k: v for k, v in edge.items() if k not in ("source", "target")})
    return g


def _build_edge_list(graph: nx.DiGraph) -> str:
    lines: list[str] = []
    for u, v, data in graph.edges(data=True):
        relation = data.get("relation", "→")
        u_label = graph.nodes[u].get("label", u)
        v_label = graph.nodes[v].get("label", v)
        lines.append(f"  {u_label} --[{relation}]--> {v_label}")
    return "\n".join(lines[:50])  # cap at 50 edges in text


def _top_by_centrality(graph: nx.DiGraph) -> tuple[str, float]:
    try:
        centrality = nx.degree_centrality(graph)
        top = max(centrality, key=lambda n: centrality[n])
        return graph.nodes[top].get("label", top), centrality[top]
    except Exception:
        nodes = list(graph.nodes)
        return (nodes[0] if nodes else "unknown", 0.0)


@retry(
    retry=retry_if_exception_type(Exception),
    wait=wait_exponential(multiplier=1, min=2, max=20),
    stop=stop_after_attempt(3),
    reraise=False,
)
async def _summarise(graph: nx.DiGraph, top_node: str, settings: Settings) -> str:
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=settings.mesh_api_key,
            base_url=settings.mesh_api_base_url,
        )

        nodes_sample = list(graph.nodes(data=True))[:15]
        edges_sample = list(graph.edges(data=True))[:15]
        payload = json.dumps({"nodes": nodes_sample, "edges": edges_sample}, default=str)

        response = await client.chat.completions.create(
            model=settings.mesh_llm_model,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Summarise this knowledge graph in 2 sentences. "
                        f"The most central entity is '{top_node}'.\n\nGraph data: {payload}"
                    ),
                }
            ],
            max_tokens=200,
            temperature=0,
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as exc:
        logger.warning("Graph summary failed", error=str(exc))
        return f"Graph with {graph.number_of_nodes()} nodes centred on '{top_node}'."
