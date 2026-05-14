"""Extract structured relationship graphs from visual and textual elements."""

from __future__ import annotations

import json
from typing import Any

import networkx as nx
from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from doc_intel_rag.config import Settings, get_settings
from doc_intel_rag.parsing.entity_types import EntityLabel


_GRAPH_EXTRACTION_PROMPT = """You are a structured data extractor. Given an image of a diagram,
flowchart, or relationship graph, extract all nodes and edges.

Return ONLY a JSON object with this exact schema:
{
  "nodes": [{"id": "string", "label": "string", "type": "string"}],
  "edges": [{"source": "string", "target": "string", "relation": "string"}]
}

Use short, descriptive IDs. If you cannot extract a graph, return {"nodes": [], "edges": []}.
"""

_TEXT_NER_PROMPT = """Extract entity relationships from the following text.

Return ONLY a JSON object:
{
  "nodes": [{"id": "string", "label": "string", "type": "string"}],
  "edges": [{"source": "string", "target": "string", "relation": "string"}]
}

Text: {text}
"""

_GRAPH_LABELS: frozenset[EntityLabel] = frozenset({
    EntityLabel.FLOWCHART,
    EntityLabel.DIAGRAM,
    EntityLabel.RELATIONSHIP_GRAPH,
})


class GraphExtractor:
    """Extracts NetworkX DiGraphs from visual graph elements and text via Mesh API + spaCy."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._nlp: Any = None

    def _get_nlp(self) -> Any:
        if self._nlp is not None:
            return self._nlp
        import spacy
        for model in ("en_core_web_trf", "en_core_web_lg", "en_core_web_sm"):
            try:
                self._nlp = spacy.load(model)
                logger.debug("spaCy loaded model: {}", model)
                break
            except (ImportError, OSError):
                continue
        else:
            logger.warning("spaCy model not available — text NER disabled")
            self._nlp = None
        return self._nlp

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        stop=stop_after_attempt(3),
        reraise=False,
    )
    async def extract_from_image(self, image_b64: str, label: EntityLabel) -> nx.DiGraph:
        """Call vision model to extract graph structure from an image."""
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=self._settings.mesh_api_key,
            base_url=self._settings.mesh_api_base_url,
        )

        response = await client.chat.completions.create(
            model=self._settings.vision_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _GRAPH_EXTRACTION_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                        },
                    ],
                }
            ],
            max_tokens=1024,
            temperature=0,
        )

        raw = response.choices[0].message.content or "{}"
        return self._build_graph(raw, source=label.value)

    async def extract_from_text(self, text: str) -> nx.DiGraph:
        """Run spaCy NER + relation heuristics on text to build a lightweight graph."""
        nlp = self._get_nlp()
        graph = nx.DiGraph()

        if nlp is None:
            return graph

        import asyncio

        loop = asyncio.get_running_loop()
        doc = await loop.run_in_executor(None, nlp, text[:5000])

        entities = {ent.text: ent.label_ for ent in doc.ents}
        for ent_text, ent_type in entities.items():
            node_id = ent_text.lower().replace(" ", "_")[:64]
            graph.add_node(node_id, label=ent_text, type=ent_type)

        # Simple co-occurrence edges: entities in same sentence
        for sent in doc.sents:
            sent_ents = [e for e in sent.ents]
            for i, src in enumerate(sent_ents):
                for tgt in sent_ents[i + 1:]:
                    src_id = src.text.lower().replace(" ", "_")[:64]
                    tgt_id = tgt.text.lower().replace(" ", "_")[:64]
                    if src_id != tgt_id:
                        graph.add_edge(src_id, tgt_id, relation="co-occurs-with")

        return graph

    def _build_graph(self, raw_json: str, source: str = "unknown") -> nx.DiGraph:
        graph = nx.DiGraph()
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError:
            logger.warning("Graph extraction returned invalid JSON", source=source)
            return graph

        for node in data.get("nodes", []):
            node_id = str(node.get("id", ""))
            if node_id:
                graph.add_node(
                    node_id,
                    label=node.get("label", node_id),
                    type=node.get("type", "entity"),
                )

        for edge in data.get("edges", []):
            src = str(edge.get("source", ""))
            tgt = str(edge.get("target", ""))
            if src and tgt:
                graph.add_edge(src, tgt, relation=edge.get("relation", "related-to"))

        return graph

    def serialize(self, graph: nx.DiGraph) -> dict[str, Any]:
        return {
            "nodes": [
                {"id": n, **graph.nodes[n]} for n in graph.nodes
            ],
            "edges": [
                {"source": u, "target": v, **graph.edges[u, v]}
                for u, v in graph.edges
            ],
        }
