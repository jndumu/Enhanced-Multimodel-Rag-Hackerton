"""Resolve cross-references between document chunks (e.g. 'see Figure 3')."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import TYPE_CHECKING

from doc_intel_rag.parsing.entity_types import EntityLabel

if TYPE_CHECKING:
    from doc_intel_rag.chunking.schemas import Chunk

# Patterns: "Figure 3", "Table 2", "Algorithm 1", "Equation (4)", etc.
_CROSS_REF_PATTERN = re.compile(
    r"\b(Figure|Fig\.|Table|Algorithm|Alg\.|Equation|Eq\.|Chart|Diagram|Listing|Code)\s+(\d+)\b",
    re.IGNORECASE,
)

_LABEL_KEYWORDS: dict[str, list[EntityLabel]] = {
    "figure": [EntityLabel.FIGURE, EntityLabel.IMAGE, EntityLabel.CHART],
    "fig.": [EntityLabel.FIGURE, EntityLabel.IMAGE, EntityLabel.CHART],
    "chart": [EntityLabel.CHART],
    "table": [EntityLabel.TABLE],
    "algorithm": [EntityLabel.ALGORITHM, EntityLabel.PSEUDO_CODE],
    "alg.": [EntityLabel.ALGORITHM, EntityLabel.PSEUDO_CODE],
    "equation": [EntityLabel.FORMULA, EntityLabel.FORMULA_BLOCK],
    "eq.": [EntityLabel.FORMULA, EntityLabel.FORMULA_BLOCK],
    "diagram": [EntityLabel.DIAGRAM, EntityLabel.FLOWCHART],
    "listing": [EntityLabel.CODE_BLOCK],
    "code": [EntityLabel.CODE_BLOCK],
}


def link_cross_references(chunks: list["Chunk"]) -> list["Chunk"]:
    """Scan text chunks for cross-reference patterns and inject chunk_ids on both sides."""
    # Build index: (label_group, sequence_number) → chunk_id
    # Sequence number = appearance order within that label group across the document
    label_counters: dict[str, int] = defaultdict(int)
    atomic_index: dict[tuple[str, int], str] = {}

    for chunk in chunks:
        for etype in chunk.element_types:
            group = _entity_to_group(etype)
            if group:
                label_counters[group] += 1
                seq = label_counters[group]
                atomic_index[(group, seq)] = chunk.chunk_id

    # Now scan text chunks for references and inject cross_refs
    for chunk in chunks:
        if chunk.modality not in ("text",):
            continue

        found_refs: list[str] = []
        for match in _CROSS_REF_PATTERN.finditer(chunk.text):
            keyword = match.group(1).lower()
            number = int(match.group(2))

            for group_key, labels in _LABEL_KEYWORDS.items():
                if keyword == group_key or keyword.rstrip(".") == group_key.rstrip("."):
                    target_id = atomic_index.get((group_key.rstrip("."), number))
                    if target_id and target_id not in found_refs:
                        found_refs.append(target_id)
                    break

        if found_refs:
            chunk.cross_refs = list(dict.fromkeys(chunk.cross_refs + found_refs))
            # Back-link from target to this chunk
            for ref_id in found_refs:
                for target_chunk in chunks:
                    if target_chunk.chunk_id == ref_id:
                        if chunk.chunk_id not in target_chunk.cross_refs:
                            target_chunk.cross_refs.append(chunk.chunk_id)

    return chunks


def _entity_to_group(label: EntityLabel) -> str | None:
    for group, labels in _LABEL_KEYWORDS.items():
        if label in labels:
            return group.rstrip(".")
    return None
