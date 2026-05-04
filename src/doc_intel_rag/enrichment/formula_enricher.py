"""LaTeX formula validation and verbal description enrichment."""

from __future__ import annotations

from loguru import logger

from doc_intel_rag.chunking.schemas import Chunk, ChunkModality
from doc_intel_rag.config import Settings, get_settings


async def enrich_formula(chunk: Chunk, settings: Settings | None = None) -> Chunk:
    """Validate LaTeX and enrich formula chunk with verbal description."""
    cfg = settings or get_settings()

    if chunk.modality != ChunkModality.FORMULA or not chunk.latex:
        return chunk

    validated_latex = _validate_latex(chunk.latex)
    if validated_latex is None:
        logger.warning("LaTeX validation failed", chunk_id=chunk.chunk_id, latex=chunk.latex[:80])
    else:
        chunk.latex = validated_latex

    description = await _describe_formula(chunk.latex or chunk.text, cfg)
    if description:
        existing = chunk.enriched_text or chunk.text
        chunk.enriched_text = f"{existing}\n\nVerbal description: {description}"

    return chunk


def _validate_latex(latex: str) -> str | None:
    try:
        from pylatexenc.latexwalker import LatexWalker

        walker = LatexWalker(latex)
        walker.get_latex_nodes()
        return latex
    except ImportError:
        return latex
    except Exception as exc:
        logger.debug("LaTeX parse error", error=str(exc))
        return None


async def _describe_formula(latex_or_text: str, settings: Settings) -> str:
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=settings.mesh_api_key,
            base_url=settings.mesh_api_base_url,
        )
        response = await client.chat.completions.create(
            model=settings.mesh_llm_model,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Describe this mathematical formula in plain English in 1-2 sentences. "
                        f"Include variable meanings if discernible.\n\nFormula: {latex_or_text}"
                    ),
                }
            ],
            max_tokens=256,
            temperature=0,
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as exc:
        logger.warning("Formula description failed", error=str(exc))
        return ""
