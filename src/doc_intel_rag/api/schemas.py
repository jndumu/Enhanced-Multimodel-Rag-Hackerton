"""All Pydantic v2 request/response models for the API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
    source: str
    collection: str = "doc_intel"
    enrich: bool = True
    force: bool = False


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    collection: str = "doc_intel"
    top_k: int = Field(default=10, ge=1, le=100)
    top_n: int = Field(default=5, ge=1, le=50)
    modality_filter: list[str] | None = None
    filters: dict[str, Any] | None = None


class GenerateRequest(SearchRequest):
    max_tokens: int = Field(default=1024, ge=64, le=8192)
    streaming: bool = True
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    include_sources: bool = True
    fallback_enabled: bool | None = None


class ChunkResult(BaseModel):
    chunk_id: str
    doc_id: str
    source_file: str
    page: int
    modality: str
    text: str
    score: float
    section_path: list[str]
    retrieval_source: str
    concept_tags: list[str] = []


class SourceRef(BaseModel):
    source_num: int
    file: str
    page: int
    modality: str
    section_path: list[str]
    retrieval_source: str


class WebResultModel(BaseModel):
    url: str
    title: str
    snippet: str
    score: float


class SafetyResultModel(BaseModel):
    pii_redacted: bool
    redacted_entities: list[str]
    injection_detected: bool
    content_class: str


class IngestResponse(BaseModel):
    doc_id: str
    chunk_count: int
    graph_node_count: int
    collection: str
    cached: bool = False


class SearchResponse(BaseModel):
    query: str
    chunks: list[ChunkResult]
    groundedness_score: float
    fallback_used: bool
    web_sources: list[WebResultModel]
    safety: SafetyResultModel
    request_id: str
    latency_ms: float


class GenerateResponse(BaseModel):
    query: str
    answer: str
    sources: list[SourceRef]
    groundedness_score: float
    faithfulness_score: float
    fallback_used: bool
    web_sources: list[WebResultModel]
    safety: SafetyResultModel
    request_id: str
    latency_ms: float


class HealthComponent(BaseModel):
    status: str
    latency_ms: float | None = None
    detail: str | None = None


class HealthResponse(BaseModel):
    status: str
    components: dict[str, HealthComponent]
    version: str = "0.1.0"


class AdminStatsResponse(BaseModel):
    qdrant: dict[str, Any]
    cache_flushable: bool
    uptime_seconds: float


class GraphResponse(BaseModel):
    doc_id: str
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    node_count: int
    edge_count: int
