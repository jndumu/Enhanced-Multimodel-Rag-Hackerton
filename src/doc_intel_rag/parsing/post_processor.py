"""Convert ParseResult elements into structured Markdown."""

from __future__ import annotations

from doc_intel_rag.parsing.entity_types import EntityLabel, SKIP_ENTITIES, TITLE_ENTITIES
from doc_intel_rag.parsing.pipeline import ParseResult, ParsedElement


def to_markdown(result: ParseResult) -> str:
    """Render all elements of a ParseResult as a structured Markdown document."""
    lines: list[str] = []
    pending_caption: str | None = None

    for elem in result.elements:
        if elem.label in SKIP_ENTITIES:
            continue

        md = _element_to_markdown(elem, pending_caption)
        if md:
            lines.append(md)

        # A caption immediately follows its parent — reset after use
        if elem.label in {EntityLabel.FIGURE_CAPTION, EntityLabel.TABLE_CAPTION}:
            pending_caption = elem.text
        else:
            pending_caption = None

    return "\n\n".join(filter(None, lines))


def _element_to_markdown(elem: ParsedElement, caption: str | None) -> str:
    match elem.label:
        case EntityLabel.DOCUMENT_TITLE:
            return f"# {elem.text}"

        case EntityLabel.SECTION_TITLE:
            return f"## {elem.text}"

        case EntityLabel.SUBSECTION_TITLE:
            return f"### {elem.text}"

        case EntityLabel.PARAGRAPH | EntityLabel.ABSTRACT:
            return elem.text

        case EntityLabel.LIST_ITEM:
            return f"- {elem.text}"

        case EntityLabel.BLOCKQUOTE:
            return f"> {elem.text}"

        case EntityLabel.FOOTNOTE:
            return f"[^note]: {elem.text}"

        case EntityLabel.CITATION:
            return f"[{elem.text}]"

        case EntityLabel.REFERENCE_LIST:
            return f"**References**\n\n{elem.text}"

        case EntityLabel.TABLE:
            if elem.html:
                return f"<!-- table -->\n{elem.html}"
            return f"<!-- table -->\n{elem.text}"

        case EntityLabel.TABLE_CAPTION | EntityLabel.FIGURE_CAPTION:
            return f"*{elem.text}*"

        case EntityLabel.TABLE_FOOTNOTE:
            return f"_{elem.text}_"

        case EntityLabel.FORMULA | EntityLabel.FORMULA_BLOCK:
            if elem.latex:
                return f"$$\n{elem.latex}\n$$"
            return f"$$\n{elem.text}\n$$"

        case EntityLabel.INLINE_FORMULA:
            if elem.latex:
                return f"${elem.latex}$"
            return f"${elem.text}$"

        case EntityLabel.CHEMICAL_FORMULA:
            return f"**Chemical formula:** `{elem.text}`"

        case EntityLabel.EQUATION_NUMBER:
            return f"({elem.text})"

        case EntityLabel.FIGURE | EntityLabel.IMAGE | EntityLabel.CHART:
            cap = f"\n*{caption}*" if caption else ""
            return f"<!-- image: {elem.label.value} -->{cap}"

        case EntityLabel.FLOWCHART | EntityLabel.DIAGRAM | EntityLabel.RELATIONSHIP_GRAPH:
            cap = f"\n*{caption}*" if caption else ""
            return f"<!-- graph: {elem.label.value} -->{cap}"

        case EntityLabel.MEDICAL_SCAN | EntityLabel.HISTOLOGY | EntityLabel.CLINICAL_PHOTO:
            return f"<!-- medical-image: {elem.label.value} -->"

        case EntityLabel.ALGORITHM | EntityLabel.PSEUDO_CODE:
            return f"```\n{elem.text}\n```"

        case EntityLabel.CODE_BLOCK:
            return f"```\n{elem.text}\n```"

        case EntityLabel.SEAL:
            return ""

        case _:
            return elem.text
