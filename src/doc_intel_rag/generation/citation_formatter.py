"""Inject [Source N] markers and build bibliography block."""

from __future__ import annotations

from doc_intel_rag.retrieval.hybrid_searcher import ScoredChunk


def build_source_index(chunks: list[ScoredChunk]) -> dict[str, int]:
    """Map chunk_id → 1-based source number."""
    return {c.chunk_id: i + 1 for i, c in enumerate(chunks)}


def format_bibliography(chunks: list[ScoredChunk]) -> str:
    lines: list[str] = ["\n\n---\n**Sources:**"]
    for i, chunk in enumerate(chunks, 1):
        source_label = "Web Source" if chunk.retrieval_source == "web" else "Source"
        file_ref = chunk.payload.get("url") or chunk.source_file
        page_ref = f" (p. {chunk.page})" if chunk.retrieval_source != "web" else ""
        section = " › ".join(chunk.section_path) if chunk.section_path else ""
        section_str = f" — {section}" if section else ""
        lines.append(f"[{source_label} {i}] {file_ref}{page_ref}{section_str}")
    return "\n".join(lines)
