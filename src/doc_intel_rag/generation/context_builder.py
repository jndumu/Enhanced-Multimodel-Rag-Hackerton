"""Assemble multimodal context from retrieved chunks for Mesh API."""

from __future__ import annotations

from typing import Any

from doc_intel_rag.retrieval.hybrid_searcher import ScoredChunk


def build_context_text(chunks: list[ScoredChunk]) -> str:
    """Build a flat text context string with source labels."""
    parts: list[str] = []
    for i, chunk in enumerate(chunks, 1):
        label = "Web Source" if chunk.retrieval_source == "web" else "Source"
        breadcrumb = " › ".join(chunk.section_path) if chunk.section_path else ""
        header = f"[{label} {i}]" + (f" {breadcrumb}" if breadcrumb else "")

        modality = chunk.modality
        text = chunk.text

        match modality:
            case "table":
                html = chunk.payload.get("html", "")
                summary = (chunk.payload.get("caption_json") or {}).get("semantic_summary", "")
                body = f"Table:\n{html or text}"
                if summary:
                    body += f"\nSummary: {summary}"
            case "formula":
                latex = chunk.payload.get("latex", "")
                verbal = (chunk.payload.get("caption_json") or {}).get("verbal_description", "")
                body = f"Formula: {verbal or text}"
                if latex:
                    body += f"\nLaTeX: {latex}"
            case "algorithm" | "code":
                lang = (chunk.payload.get("caption_json") or {}).get("language", "")
                fence = f"```{lang}\n{text}\n```"
                body = fence
            case "graph":
                summary = (chunk.payload.get("caption_json") or {}).get("summary", "")
                edges = _extract_edges(chunk)
                body = f"Relationship Graph: {summary or text}"
                if edges:
                    body += f"\nEdges:\n{edges}"
            case _:
                body = text

        parts.append(f"{header}\n{body}")

    return "\n\n".join(parts)


def build_messages(
    query: str,
    chunks: list[ScoredChunk],
    system_prompt: str,
    user_prompt: str,
) -> list[dict[str, Any]]:
    """Build OpenAI-format message list with interleaved image blocks."""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
    ]

    user_content: list[dict[str, Any]] = [{"type": "text", "text": user_prompt}]

    for i, chunk in enumerate(chunks, 1):
        image_b64 = chunk.payload.get("raw_image_b64")
        if image_b64 and chunk.modality in ("image", "graph"):
            label = "Web Source" if chunk.retrieval_source == "web" else "Source"
            user_content.append({"type": "text", "text": f"[{label} {i} — image]"})
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{image_b64}"},
            })

    messages.append({"role": "user", "content": user_content})
    return messages


def _extract_edges(chunk: ScoredChunk) -> str:
    graph_json = chunk.payload.get("graph_json") or {}
    edges = graph_json.get("edges", [])
    lines = []
    for edge in edges[:20]:
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        rel = edge.get("relation", "→")
        lines.append(f"  {src} --[{rel}]--> {tgt}")
    return "\n".join(lines)
