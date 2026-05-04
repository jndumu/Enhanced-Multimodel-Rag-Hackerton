"""PII detection and redaction using presidio."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from loguru import logger

_PII_ENTITIES = [
    "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "IP_ADDRESS",
    "CREDIT_CARD", "IBAN_CODE", "NRP", "LOCATION", "DATE_TIME", "URL",
]


@lru_cache(maxsize=1)
def _get_analyzer() -> Any:
    try:
        from presidio_analyzer import AnalyzerEngine
        return AnalyzerEngine()
    except ImportError:
        logger.warning("presidio-analyzer not installed — PII detection disabled")
        return None


@lru_cache(maxsize=1)
def _get_anonymizer() -> Any:
    try:
        from presidio_anonymizer import AnonymizerEngine
        return AnonymizerEngine()
    except ImportError:
        return None


def detect_and_redact(text: str) -> tuple[str, list[str]]:
    """Return (redacted_text, list_of_detected_entity_types)."""
    analyzer = _get_analyzer()
    anonymizer = _get_anonymizer()

    if analyzer is None or anonymizer is None:
        return text, []

    try:
        results = analyzer.analyze(text=text, entities=_PII_ENTITIES, language="en")
        if not results:
            return text, []

        entity_types = list({r.entity_type for r in results})

        from presidio_anonymizer.entities import OperatorConfig

        operators = {
            entity: OperatorConfig("replace", {"new_value": f"<{entity}>"})
            for entity in entity_types
        }
        redacted = anonymizer.anonymize(text=text, analyzer_results=results, operators=operators)
        return redacted.text, entity_types

    except Exception as exc:
        logger.warning("PII detection error", error=str(exc))
        return text, []
