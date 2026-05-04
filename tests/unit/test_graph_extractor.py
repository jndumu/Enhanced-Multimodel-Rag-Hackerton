"""Unit tests for the graph extractor."""

from __future__ import annotations

import os
os.environ["DOC_INTEL_SKIP_VALIDATION"] = "1"

import pytest
import networkx as nx

from doc_intel_rag.config import reset_settings
from doc_intel_rag.parsing.graph_extractor import GraphExtractor


@pytest.fixture(autouse=True)
def reset():
    reset_settings()
    yield
    reset_settings()


def test_build_graph_from_valid_json():
    extractor = GraphExtractor()
    raw = '{"nodes": [{"id": "A", "label": "Node A", "type": "entity"}, {"id": "B", "label": "Node B", "type": "entity"}], "edges": [{"source": "A", "target": "B", "relation": "connects-to"}]}'
    graph = extractor._build_graph(raw, source="test")
    assert graph.number_of_nodes() == 2
    assert graph.number_of_edges() == 1
    assert graph.has_edge("A", "B")
    assert graph.edges["A", "B"]["relation"] == "connects-to"


def test_build_graph_from_malformed_json():
    extractor = GraphExtractor()
    graph = extractor._build_graph("{not valid json}", source="test")
    # Graceful fallback: empty graph
    assert isinstance(graph, nx.DiGraph)
    assert graph.number_of_nodes() == 0
    assert graph.number_of_edges() == 0


def test_build_graph_empty_nodes():
    extractor = GraphExtractor()
    graph = extractor._build_graph('{"nodes": [], "edges": []}', source="test")
    assert graph.number_of_nodes() == 0


def test_serialize_round_trip():
    extractor = GraphExtractor()
    raw = '{"nodes": [{"id": "X", "label": "X label", "type": "t"}], "edges": []}'
    graph = extractor._build_graph(raw)
    serialized = extractor.serialize(graph)
    assert len(serialized["nodes"]) == 1
    assert serialized["nodes"][0]["id"] == "X"
    assert serialized["edges"] == []


def test_build_graph_ignores_edges_with_missing_nodes():
    extractor = GraphExtractor()
    # Edge references node C which doesn't exist — should still add it (NetworkX auto-adds)
    raw = '{"nodes": [{"id": "A", "label": "A", "type": "e"}], "edges": [{"source": "A", "target": "C", "relation": "r"}]}'
    graph = extractor._build_graph(raw)
    assert graph.has_edge("A", "C")
    assert "C" in graph.nodes  # NetworkX adds missing nodes automatically
