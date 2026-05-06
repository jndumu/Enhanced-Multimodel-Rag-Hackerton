"""Query intent classifier — routes to appropriate retrieval strategy."""

from __future__ import annotations

from enum import Enum

from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from doc_intel_rag.config import Settings, get_settings


class QueryIntent(str, Enum):
    FACTUAL    = "factual"
    ANALYTICAL = "analytical"
    VISUAL     = "visual"
    MATHEMATICAL = "mathematical"
    CODE       = "code"
    RELATIONAL = "relational"
    GENERAL    = "general"


_SYSTEM_PROMPT = (
    "Classify the following user query into exactly one intent category. "
    "Return ONLY a JSON object: {\"intent\": \"<category>\", \"confidence\": <0-1>}.\n"
    "Categories: factual, analytical, visual, mathematical, code, relational, general\n\n"
    "factual=direct fact lookup, analytical=multi-hop reasoning, visual=chart/figure/diagram, "
    "mathematical=formula/equation, code=code/algorithm, relational=how X relates to Y, "
    "general=none of the above."
)


class SemanticRouter:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client: "object | None" = None

    def _get_client(self) -> "object":
        if self._client is None:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                api_key=self._settings.mesh_api_key,
                base_url=self._settings.mesh_api_base_url,
            )
        return self._client

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(3),
        reraise=False,
    )
    async def classify(self, query: str) -> QueryIntent:
        import json

        try:
            client = self._get_client()
            response = await client.chat.completions.create(  # type: ignore[attr-defined]
                model=self._settings.mesh_llm_model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": query[:500]},
                ],
                max_tokens=64,
                temperature=0,
            )
            raw = response.choices[0].message.content or "{}"
            data = json.loads(raw)
            intent_str = str(data.get("intent", "general")).lower()
            intent = QueryIntent(intent_str) if intent_str in QueryIntent._value2member_map_ else QueryIntent.GENERAL
            logger.debug("Query intent classified", intent=intent.value, query=query[:60])
            return intent
        except Exception as exc:
            logger.debug("Intent classification failed — defaulting to general", error=str(exc))
            return QueryIntent.GENERAL
