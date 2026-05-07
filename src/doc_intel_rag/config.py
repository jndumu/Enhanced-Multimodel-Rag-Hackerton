"""Central configuration — single source of truth for all settings."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ImproperlyConfigured(RuntimeError):
    """Raised at startup when required configuration is missing or invalid."""


class Settings(BaseSettings):
    """All runtime settings loaded from environment variables or a .env file.

    Validated at startup; the application refuses to bind if required values
    are missing. Sensitive fields are masked in :meth:`masked_dict`.

    Attributes:
        mesh_api_key: Primary LLM + embedding API key (required in production).
        mesh_api_base_url: OpenAI-compatible base URL for the Mesh API.
        mesh_llm_model: Model name used for generation and routing calls.
        mesh_embedding_model: Model name used for dense text embeddings.
        mesh_embedding_dim: Output dimension of the embedding model.
        reranker_backend: Which reranker to use — ``cohere``, ``jina``, or ``openai``.
        groundedness_threshold: Retrieval score below which web fallback fires.
        fallback_enabled: Master toggle for the Tavily web search fallback.
        max_chunk_tokens: Hard token cap per text chunk.
        chunk_overlap_tokens: Tokens carried over between consecutive text chunks.
        api_keys: List of valid ``X-API-Key`` header values; empty = open access.
    """

    # === Mesh API (primary LLM + embeddings) ===
    mesh_api_key: str = Field(default="", description="Mesh API key (required for production)")
    mesh_api_base_url: str = "https://api.mesh.ai/v1"
    mesh_llm_model: str = "mesh-gpt-4o"
    mesh_embedding_model: str = "mesh-text-embedding-3-large"
    mesh_embedding_dim: int = 3072

    # === Vision model (OCR + image enrichment) ===
    vision_model: str = "llava"  # Ollama vision model for OCR and image captioning
    vision_enabled: bool = True  # Set false to skip vision enrichment

    # === GLM-OCR / Layout Detection ===
    glmocr_api_key: str = ""
    glmocr_backend: Literal["cloud", "local"] = "cloud"
    glmocr_local_model: str = "glm-ocr:latest"
    glmocr_timeout: int = 120

    # === Qdrant ===
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "doc_intel"

    # === Redis ===
    redis_url: str = "redis://localhost:6379"
    redis_embedding_ttl: int = 86400
    redis_query_ttl: int = 3600

    # === Reranker (NOT Qwen/BGE/Ollama/Mesh) ===
    reranker_backend: Literal["cohere", "jina", "openai"] = "cohere"
    cohere_api_key: str = ""
    cohere_rerank_model: str = "rerank-v3.5"
    jina_api_key: str = ""
    jina_rerank_model: str = "jina-reranker-v2-base-multilingual"
    openai_api_key: str = ""
    openai_rerank_model: str = "gpt-4o-mini"

    # === Tavily web fallback ===
    tavily_api_key: str = ""
    groundedness_threshold: float = 0.45
    tavily_max_results: int = 5
    fallback_enabled: bool = True

    # === Safety ===
    safety_pii_enabled: bool = True
    safety_injection_enabled: bool = True
    safety_output_faithfulness: bool = True
    safety_toxicity_enabled: bool = True
    safety_block_on_pii: bool = False

    # === Ingestion ===
    enrichment_enabled: bool = True
    max_chunk_tokens: int = 512
    chunk_overlap_tokens: int = 64
    ingest_batch_size: int = 64

    # === API ===
    # Use JSON array format in .env: API_KEYS=["key1","key2"]
    api_keys: list[str] = Field(default_factory=list)
    rate_limit_per_minute: int = 60
    streaming_enabled: bool = True
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])

    # === Neo4j (optional) ===
    neo4j_uri: str = ""
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # === Observability ===
    log_level: str = "INFO"
    log_json: bool = True
    otel_endpoint: str = ""
    otel_service_name: str = "doc-intel-rag"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    @field_validator("api_keys", mode="before")
    @classmethod
    def _parse_api_keys(cls, v: object) -> list[str]:
        if isinstance(v, str):
            return [k.strip() for k in v.split(",") if k.strip()]
        return list(v) if v else []  # type: ignore[arg-type]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, v: object) -> list[str]:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return list(v) if v else ["*"]  # type: ignore[arg-type]

    @model_validator(mode="after")
    def _validate_required_keys(self) -> "Settings":
        if not self.mesh_api_key:
            import os
            if os.getenv("DOC_INTEL_SKIP_VALIDATION") != "1":
                raise ImproperlyConfigured(
                    "MESH_API_KEY is required. Set it in .env or as an environment variable. "
                    "Set DOC_INTEL_SKIP_VALIDATION=1 to bypass (tests only)."
                )
        return self

    def masked_dict(self) -> dict[str, object]:
        """Return a settings snapshot with all secret fields replaced by ``***``.

        Returns:
            A plain ``dict`` safe for structured logging and debug output.
        """
        d = self.model_dump()
        secret_fields = {
            "mesh_api_key", "glmocr_api_key", "qdrant_api_key",
            "cohere_api_key", "jina_api_key", "openai_api_key",
            "tavily_api_key", "neo4j_password",
        }
        for field in secret_fields:
            if d.get(field):
                d[field] = "***"
        if d.get("api_keys"):
            d["api_keys"] = ["***"] * len(d["api_keys"])
        return d


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the process-wide :class:`Settings` singleton.

    Instantiates and caches on first call; subsequent calls return the cached
    instance. Call :func:`reset_settings` between tests to clear the cache.

    Returns:
        The validated ``Settings`` instance.

    Raises:
        ImproperlyConfigured: If ``MESH_API_KEY`` is missing and
            ``DOC_INTEL_SKIP_VALIDATION`` is not set.
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Clear the cached :class:`Settings` singleton.

    Use this in test fixtures to ensure each test starts with a fresh
    configuration derived from the current environment.
    """
    global _settings
    _settings = None
