"""Domain exception hierarchy for doc-intel-rag.

All application-level errors inherit from :class:`DocIntelError` so callers
can catch the entire family with a single ``except DocIntelError`` clause.
"""

from __future__ import annotations


class DocIntelError(Exception):
    """Base class for all doc-intel-rag application errors."""


# ── Configuration ─────────────────────────────────────────────────────────────

class ConfigurationError(DocIntelError):
    """Raised when required configuration is missing or invalid at startup."""


# ── Ingestion ─────────────────────────────────────────────────────────────────

class IngestionError(DocIntelError):
    """Raised when the document ingestion pipeline fails."""


class DocumentParseError(IngestionError):
    """Raised when GLM-OCR / PP-DocLayout-V3 cannot parse a document."""


class UnsupportedDocumentType(IngestionError):
    """Raised when the supplied file type is not supported."""


class DocumentNotFoundError(IngestionError):
    """Raised when the source file or URL cannot be resolved."""


# ── Retrieval ─────────────────────────────────────────────────────────────────

class RetrievalError(DocIntelError):
    """Raised when the hybrid search or reranking step fails."""


class VectorStoreError(RetrievalError):
    """Raised when Qdrant operations fail after all retries."""


class EmbeddingError(RetrievalError):
    """Raised when the embedding API fails after all retries."""


class RerankerError(RetrievalError):
    """Raised when the reranker API (Cohere/Jina/OpenAI) fails."""


# ── Generation ────────────────────────────────────────────────────────────────

class GenerationError(DocIntelError):
    """Raised when the LLM generation call fails."""


# ── Safety ────────────────────────────────────────────────────────────────────

class SafetyError(DocIntelError):
    """Base class for safety guardrail violations."""


class PIIDetectedError(SafetyError):
    """Raised when PII is detected and ``SAFETY_BLOCK_ON_PII=true``."""

    def __init__(self, entity_types: list[str]) -> None:
        self.entity_types = entity_types
        super().__init__(f"PII detected: {', '.join(entity_types)}")


class InjectionDetectedError(SafetyError):
    """Raised when a prompt-injection attempt is detected."""


class HarmfulContentError(SafetyError):
    """Raised when query or response content is classified as harmful."""


class FaithfulnessError(SafetyError):
    """Raised when the generated answer has very low NLI faithfulness score."""


# ── External services ─────────────────────────────────────────────────────────

class ExternalServiceError(DocIntelError):
    """Raised when an external API call fails after all retries."""

    def __init__(self, service: str, detail: str) -> None:
        self.service = service
        self.detail = detail
        super().__init__(f"{service} error: {detail}")


class TavilyError(ExternalServiceError):
    """Raised when the Tavily web search API fails."""

    def __init__(self, detail: str) -> None:
        super().__init__("Tavily", detail)


class CohereError(ExternalServiceError):
    """Raised when the Cohere reranker API fails."""

    def __init__(self, detail: str) -> None:
        super().__init__("Cohere", detail)
