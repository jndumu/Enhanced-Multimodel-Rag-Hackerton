"""Canonical entity label set and modality mapping for PP-DocLayout-V3 output.

Every module that branches on entity type or modality MUST import from here —
never use raw string literals for label comparisons.
"""

from __future__ import annotations

from enum import Enum


class EntityLabel(str, Enum):
    """PP-DocLayout-V3 entity labels — authoritative contract for all layers."""

    # ── Structural / textual ─────────────────────────────────────────────────
    DOCUMENT_TITLE   = "document_title"
    SECTION_TITLE    = "section_title"
    SUBSECTION_TITLE = "subsection_title"
    PARAGRAPH        = "paragraph"
    ABSTRACT         = "abstract"
    LIST_ITEM        = "list_item"
    BLOCKQUOTE       = "blockquote"
    FOOTNOTE         = "footnote"
    HEADER           = "header"
    FOOTER           = "footer"
    PAGE_NUMBER      = "page_number"

    # ── Mathematical ─────────────────────────────────────────────────────────
    FORMULA          = "formula"
    FORMULA_BLOCK    = "formula_block"
    INLINE_FORMULA   = "inline_formula"
    CHEMICAL_FORMULA = "chemical_formula"
    EQUATION_NUMBER  = "equation_number"

    # ── Tabular ──────────────────────────────────────────────────────────────
    TABLE            = "table"
    TABLE_CAPTION    = "table_caption"
    TABLE_FOOTNOTE   = "table_footnote"

    # ── Visual / figures ─────────────────────────────────────────────────────
    FIGURE           = "figure"
    IMAGE            = "image"
    FIGURE_CAPTION   = "figure_caption"
    CHART            = "chart"
    FLOWCHART        = "flowchart"
    DIAGRAM          = "diagram"
    RELATIONSHIP_GRAPH = "relationship_graph"

    # ── Medical imaging ──────────────────────────────────────────────────────
    MEDICAL_SCAN     = "medical_scan"
    HISTOLOGY        = "histology"
    CLINICAL_PHOTO   = "clinical_photo"

    # ── Code / algorithms ────────────────────────────────────────────────────
    ALGORITHM        = "algorithm"
    PSEUDO_CODE      = "pseudo_code"
    CODE_BLOCK       = "code_block"

    # ── References / citations ───────────────────────────────────────────────
    CITATION         = "citation"
    REFERENCE_LIST   = "reference_list"

    # ── Seals / stamps ───────────────────────────────────────────────────────
    SEAL             = "seal"


# ── Canonical modality mapping ────────────────────────────────────────────────
ENTITY_TO_MODALITY: dict[EntityLabel, str] = {
    # text
    EntityLabel.DOCUMENT_TITLE:      "text",
    EntityLabel.SECTION_TITLE:       "text",
    EntityLabel.SUBSECTION_TITLE:    "text",
    EntityLabel.PARAGRAPH:           "text",
    EntityLabel.ABSTRACT:            "text",
    EntityLabel.LIST_ITEM:           "text",
    EntityLabel.BLOCKQUOTE:          "text",
    EntityLabel.FOOTNOTE:            "text",
    EntityLabel.HEADER:              "text",
    EntityLabel.FOOTER:              "text",
    EntityLabel.PAGE_NUMBER:         "text",
    EntityLabel.TABLE_CAPTION:       "text",
    EntityLabel.TABLE_FOOTNOTE:      "text",
    EntityLabel.FIGURE_CAPTION:      "text",
    EntityLabel.EQUATION_NUMBER:     "text",
    EntityLabel.CITATION:            "text",
    EntityLabel.REFERENCE_LIST:      "text",
    EntityLabel.INLINE_FORMULA:      "text",
    # formula
    EntityLabel.FORMULA:             "formula",
    EntityLabel.FORMULA_BLOCK:       "formula",
    EntityLabel.CHEMICAL_FORMULA:    "formula",
    # table
    EntityLabel.TABLE:               "table",
    # image
    EntityLabel.FIGURE:              "image",
    EntityLabel.IMAGE:               "image",
    EntityLabel.CHART:               "image",
    EntityLabel.MEDICAL_SCAN:        "image",
    EntityLabel.HISTOLOGY:           "image",
    EntityLabel.CLINICAL_PHOTO:      "image",
    EntityLabel.SEAL:                "image",
    # graph
    EntityLabel.FLOWCHART:           "graph",
    EntityLabel.DIAGRAM:             "graph",
    EntityLabel.RELATIONSHIP_GRAPH:  "graph",
    # algorithm
    EntityLabel.ALGORITHM:           "algorithm",
    EntityLabel.PSEUDO_CODE:         "algorithm",
    # code
    EntityLabel.CODE_BLOCK:          "code",
}

assert len(ENTITY_TO_MODALITY) == len(EntityLabel), (
    f"ENTITY_TO_MODALITY has {len(ENTITY_TO_MODALITY)} entries "
    f"but EntityLabel has {len(EntityLabel)} members — mapping is incomplete"
)

# Atomic elements: never split or merged across chunk boundaries
ATOMIC_ENTITIES: frozenset[EntityLabel] = frozenset({
    EntityLabel.TABLE,
    EntityLabel.FORMULA,
    EntityLabel.FORMULA_BLOCK,
    EntityLabel.CHEMICAL_FORMULA,
    EntityLabel.FIGURE,
    EntityLabel.IMAGE,
    EntityLabel.CHART,
    EntityLabel.MEDICAL_SCAN,
    EntityLabel.HISTOLOGY,
    EntityLabel.CLINICAL_PHOTO,
    EntityLabel.FLOWCHART,
    EntityLabel.DIAGRAM,
    EntityLabel.RELATIONSHIP_GRAPH,
    EntityLabel.ALGORITHM,
    EntityLabel.PSEUDO_CODE,
    EntityLabel.CODE_BLOCK,
})

# Title entities: prepended to the next content element for context
TITLE_ENTITIES: frozenset[EntityLabel] = frozenset({
    EntityLabel.DOCUMENT_TITLE,
    EntityLabel.SECTION_TITLE,
    EntityLabel.SUBSECTION_TITLE,
    EntityLabel.FIGURE_CAPTION,
    EntityLabel.TABLE_CAPTION,
})

# Entities skipped in Markdown assembly and embedding entirely
SKIP_ENTITIES: frozenset[EntityLabel] = frozenset({
    EntityLabel.PAGE_NUMBER,
    EntityLabel.SEAL,
    EntityLabel.HEADER,
    EntityLabel.FOOTER,
})

# Enrichment pipeline routing: modality → enricher function name
ENRICHMENT_ROUTING: dict[str, str] = {
    "image":     "enrich_image",
    "table":     "enrich_table",
    "formula":   "enrich_formula",
    "algorithm": "enrich_algorithm",
    "graph":     "enrich_graph",
    "code":      "enrich_code",
}
