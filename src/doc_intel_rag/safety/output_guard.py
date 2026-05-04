"""Output safety: faithfulness (NLI) + toxicity (Detoxify) checking."""

from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Any

from loguru import logger

from doc_intel_rag.config import Settings, get_settings
from doc_intel_rag.safety.schemas import OutputGuardResult

_DISCLAIMER = (
    "\n\n⚠️ *Note: parts of this answer may not be fully supported "
    "by the retrieved documents.*"
)
_BLOCKED_RESPONSE = (
    "I'm unable to provide this response as it may contain harmful content."
)
_FAITHFULNESS_THRESHOLD = 0.5
_TOXICITY_THRESHOLD = 0.7


@lru_cache(maxsize=1)
def _get_nli_model() -> Any:
    try:
        from sentence_transformers import CrossEncoder
        return CrossEncoder("cross-encoder/nli-deberta-v3-base")
    except (ImportError, Exception) as exc:
        logger.warning("NLI model not available — faithfulness check disabled", error=str(exc))
        return None


@lru_cache(maxsize=1)
def _get_detoxify() -> Any:
    try:
        from detoxify import Detoxify
        return Detoxify("original")
    except (ImportError, Exception) as exc:
        logger.warning("Detoxify not available — toxicity check disabled", error=str(exc))
        return None


class OutputGuard:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def check(self, answer: str, context: str) -> OutputGuardResult:
        faithfulness_score = 1.0
        toxicity_scores: dict[str, float] = {}
        disclaimer_added = False
        blocked = False

        if self._settings.safety_toxicity_enabled:
            toxicity_scores = await self._check_toxicity(answer)
            if any(v > _TOXICITY_THRESHOLD for v in toxicity_scores.values()):
                logger.warning("Toxicity threshold exceeded", scores=toxicity_scores)
                return OutputGuardResult(
                    answer=_BLOCKED_RESPONSE,
                    faithfulness_score=0.0,
                    toxicity_scores=toxicity_scores,
                    blocked=True,
                )

        if self._settings.safety_output_faithfulness:
            faithfulness_score = await self._score_faithfulness(context, answer)
            if faithfulness_score < _FAITHFULNESS_THRESHOLD:
                logger.info("Low faithfulness score", score=faithfulness_score)
                answer = answer + _DISCLAIMER
                disclaimer_added = True

        return OutputGuardResult(
            answer=answer,
            faithfulness_score=faithfulness_score,
            toxicity_scores=toxicity_scores,
            disclaimer_added=disclaimer_added,
            blocked=blocked,
        )

    async def _score_faithfulness(self, context: str, answer: str) -> float:
        model = _get_nli_model()
        if model is None:
            return 1.0
        loop = asyncio.get_event_loop()
        try:
            scores = await loop.run_in_executor(
                None,
                lambda: model.predict([(context[:2000], answer[:1000])]),
            )
            # CrossEncoder NLI returns [contradiction, neutral, entailment]
            entailment_score = float(scores[0][2]) if len(scores[0]) >= 3 else float(scores[0][-1])
            return entailment_score
        except Exception as exc:
            logger.warning("Faithfulness scoring failed", error=str(exc))
            return 1.0

    async def _check_toxicity(self, text: str) -> dict[str, float]:
        model = _get_detoxify()
        if model is None:
            return {}
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(None, lambda: model.predict(text[:1000]))
            return {k: float(v) for k, v in result.items()}
        except Exception as exc:
            logger.warning("Toxicity check failed", error=str(exc))
            return {}


def get_output_guard(settings: Settings | None = None) -> OutputGuard:
    return OutputGuard(settings)
