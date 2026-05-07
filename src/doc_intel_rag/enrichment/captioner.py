"""Mesh API vision-based enrichment for all non-text chunk modalities."""

from __future__ import annotations

import json
from typing import Any

from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from doc_intel_rag.chunking.schemas import Chunk, ChunkModality
from doc_intel_rag.config import Settings, get_settings
from doc_intel_rag.parsing.entity_types import ENRICHMENT_ROUTING

_MODALITY_PROMPTS: dict[str, str] = {
    "image": (
        'Analyse this image and return JSON with keys: '
        '"type", "caption", "detail", "objects" (list), "colors" (list), "layout".'
    ),
    "chart": (
        'Analyse this chart and return JSON with keys: '
        '"chart_type", "title", "axes", "series" (list), "trend_summary", "data_points" (list of {x,y,label}).'
    ),
    "graph": (
        'Describe this diagram/flowchart and return JSON with keys: '
        '"process_name", "steps" (list), "decision_points" (list), "connections" (list), "summary".'
    ),
    "table": (
        'Analyse this table and return JSON with keys: '
        '"title", "column_headers" (list), "row_count", "col_count", "markdown_repr", "semantic_summary".'
    ),
    "formula": (
        'Analyse this mathematical expression and return JSON with keys: '
        '"notation_type", "verbal_description", "latex", "variables" (list of {name, role}), "domain".'
    ),
    "chemical_formula": (
        'Analyse this chemical formula/structure and return JSON with keys: '
        '"name", "formula_string", "element_counts" (dict), "description".'
    ),
    "algorithm": (
        'Analyse this algorithm/pseudocode and return JSON with keys: '
        '"name", "purpose", "inputs" (list), "outputs" (list), "steps" (list), "complexity".'
    ),
    "code": (
        'Analyse this code listing and return JSON with keys: '
        '"language", "purpose", "inputs" (list), "outputs" (list), "key_operations" (list).'
    ),
}


async def enrich_chunks(
    chunks: list[Chunk],
    settings: Settings | None = None,
) -> list[Chunk]:
    """Enrich all non-text chunks with Mesh API vision captions."""
    cfg = settings or get_settings()
    if not cfg.enrichment_enabled:
        return chunks

    captioner = _Captioner(cfg)
    for chunk in chunks:
        routing_key = ENRICHMENT_ROUTING.get(chunk.modality.value)
        if routing_key is None:
            continue
        try:
            await captioner.enrich(chunk)
        except Exception as exc:
            logger.warning(
                "Enrichment failed for chunk",
                chunk_id=chunk.chunk_id,
                modality=chunk.modality.value,
                error=str(exc),
            )
    return chunks


class _Captioner:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: "object | None" = None

    def _get_client(self) -> "object":
        if self._client is None:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                api_key=self._settings.mesh_api_key,
                base_url=self._settings.mesh_api_base_url,
            )
        return self._client

    def _model_for(self, chunk: Chunk) -> str:
        """Return the right model: vision model for image chunks, text LLM for others."""
        needs_vision = chunk.raw_image_b64 is not None and self._settings.vision_enabled
        if needs_vision:
            return self._settings.vision_model
        return self._settings.mesh_llm_model

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        stop=stop_after_attempt(3),
        reraise=False,
    )
    async def enrich(self, chunk: Chunk) -> None:
        client = self._get_client()

        prompt = self._build_prompt(chunk)
        messages = self._build_messages(chunk, prompt)
        model = self._model_for(chunk)

        uses_vision = model == self._settings.vision_model
        create_kwargs: dict[str, object] = {
            "model": model,
            "messages": messages,
            "max_tokens": 1024,
            "temperature": 0,
        }
        if not uses_vision:
            create_kwargs["response_format"] = {"type": "json_object"}

        response = await client.chat.completions.create(**create_kwargs)  # type: ignore[attr-defined]

        raw = response.choices[0].message.content or "{}"
        try:
            caption_data: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            caption_data = {"raw": raw}

        chunk.caption_json = caption_data
        summary = _caption_to_text(chunk.modality, caption_data)
        chunk.enriched_text = f"{chunk.text}\n\n[Enrichment]\n{summary}"

        logger.debug(
            "Chunk enriched",
            chunk_id=chunk.chunk_id,
            modality=chunk.modality.value,
        )

    def _build_prompt(self, chunk: Chunk) -> str:
        mod = chunk.modality.value
        if mod == "graph":
            return _MODALITY_PROMPTS["graph"]
        return _MODALITY_PROMPTS.get(mod, _MODALITY_PROMPTS["image"])

    def _build_messages(self, chunk: Chunk, prompt: str) -> list[dict[str, Any]]:
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]

        if chunk.raw_image_b64:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{chunk.raw_image_b64}"},
            })
        elif chunk.html:
            content = [{"type": "text", "text": f"{prompt}\n\nTable HTML:\n{chunk.html}"}]
        elif chunk.latex:
            content = [{"type": "text", "text": f"{prompt}\n\nLaTeX: {chunk.latex}"}]
        elif chunk.text:
            content = [{"type": "text", "text": f"{prompt}\n\nContent:\n{chunk.text}"}]

        return [{"role": "user", "content": content}]


def _caption_to_text(modality: ChunkModality, data: dict[str, Any]) -> str:
    match modality:
        case ChunkModality.IMAGE:
            return data.get("caption", data.get("detail", str(data)))
        case ChunkModality.TABLE:
            return data.get("semantic_summary", data.get("markdown_repr", str(data)))
        case ChunkModality.FORMULA:
            return data.get("verbal_description", str(data))
        case ChunkModality.ALGORITHM:
            steps = data.get("steps", [])
            steps_str = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(steps))
            return f"{data.get('purpose', '')}\n{steps_str}"
        case ChunkModality.CODE:
            return data.get("purpose", str(data))
        case ChunkModality.GRAPH:
            return data.get("summary", str(data))
        case _:
            return str(data)
