# doc-intel-rag — Claude Code Guide

> **Author:** Josephine Ndumu  
> **Stack:** Python 3.12 · FastAPI · Qdrant · Redis · Cohere · Tavily · AWS ECS Fargate

This file tells Claude Code everything it needs to know about this codebase.

---

## Quick Commands

```bash
# Install dependencies
uv sync

# Start infrastructure (Qdrant + Redis)
docker compose -f docker/docker-compose.yml up qdrant redis -d

# Run the API server
uv run python scripts/serve.py --port 8000 --reload

# Run all tests
uv run pytest tests/ -x -q --tb=short

# Unit tests only (no external services)
uv run pytest tests/unit/ -q

# Type checking
uv run mypy src/ --strict

# Linting
uv run ruff check src/
```

---

## Project Layout

```
src/doc_intel_rag/
├── config.py              # pydantic-settings v2 Settings singleton
├── logging_config.py      # Loguru + stdlib interception + OTel
├── exceptions.py          # Full domain exception hierarchy
│
├── parsing/               # Document ingestion — GLM-OCR + PP-DocLayout-V3
│   ├── pipeline.py        # DocumentParser: file + URL support, async
│   ├── entity_types.py    # 35 EntityLabel enum + modality mapping
│   ├── post_processor.py  # ParseResult → Markdown
│   ├── graph_extractor.py # LLM vision → NetworkX DiGraph + spaCy NER
│   └── cross_ref_linker.py# "see Figure 3" → chunk_id resolution
│
├── chunking/
│   ├── schemas.py         # Chunk dataclass + ChunkModality enum
│   ├── document_chunker.py# Atomic + text accumulation strategy
│   └── semantic_merger.py # Merge tiny adjacent chunks (cosine > 0.85)
│
├── enrichment/
│   ├── captioner.py       # Per-modality LLM vision captions (client cached)
│   ├── formula_enricher.py# pylatexenc + verbal LLM description
│   ├── concept_extractor.py# spaCy NER → concept_tags
│   └── graph_enricher.py  # Graph edge list + centrality + LLM summary
│
├── ingestion/
│   ├── embedder.py        # Dense (768-dim) + Sparse BM25 (2^17) + Redis cache
│   ├── vector_store.py    # QdrantDocumentStore: 3 named vectors, RRF fusion
│   ├── graph_embedder.py  # node2vec → 128-dim graph_dense vector
│   ├── graph_store.py     # In-memory NetworkX GraphStore
│   └── cache.py           # EmbeddingCache + QueryCache (Redis async)
│
├── retrieval/
│   ├── semantic_router.py # LLM → 7 QueryIntent classes (client cached)
│   ├── hybrid_searcher.py # Prefetch + RRF + 2-hop graph traversal
│   ├── reranker.py        # Cohere / Jina / OpenAI cross-encoder (immutable chunks)
│   ├── groundedness.py    # Weighted chunk-score groundedness metric
│   └── web_fallback.py    # Tavily search → ScoredChunk list
│
├── generation/
│   ├── generator.py       # Streaming SSE generation (LLM client cached)
│   ├── context_builder.py # Multimodal message assembly
│   ├── prompt_templates.py# Jinja2 system + user templates
│   └── citation_formatter.py# [Source N] inline + bibliography
│
├── safety/
│   ├── schemas.py         # SafetyResult, OutputGuardResult, GuardrailViolation
│   ├── input_guard.py     # PII → injection → content classification
│   ├── output_guard.py    # NLI faithfulness + Detoxify toxicity
│   ├── phi_detector.py    # Presidio PII detect-and-redact
│   └── rate_limiter.py    # slowapi per-IP rate limiting
│
├── api/
│   ├── app.py             # FastAPI factory + lifespan + exception handlers
│   ├── middleware.py      # RequestIDMiddleware + security headers
│   ├── dependencies.py    # Singleton DI (embedder, vector_store, reranker, …)
│   ├── schemas.py         # All Pydantic v2 request/response models
│   └── routes/
│       ├── health.py      # GET /health
│       ├── ingest.py      # POST /v1/ingest, /v1/ingest/file
│       ├── search.py      # POST /v1/search
│       ├── generate.py    # POST /v1/generate (SSE or JSON)
│       ├── graph.py       # GET /v1/graph/{doc_id}
│       └── admin.py       # GET /v1/admin/stats, POST /v1/admin/purge-cache
│
└── utils/
    ├── token_utils.py     # tiktoken cl100k_base helpers
    ├── image_utils.py     # Base64 image handling
    ├── pdf_utils.py       # PyMuPDF page crop helpers
    └── async_utils.py     # Async helpers
```

---

## Critical Rules

### Never break these invariants

1. **Rerankers must not mutate input chunks** — use `dataclasses.replace(chunk, score=new_score)` to return new objects. `CohereReranker`, `JinaReranker`, `OpenAICrossEncoder` all follow this pattern.

2. **LLM clients must be cached at the instance level** — never create `AsyncOpenAI(...)` inside a per-request function. Every class that calls the LLM holds a `self._client` and a `_get_client()` method:
   - `_Captioner._get_client()`
   - `SemanticRouter._get_client()`
   - `CohereReranker._get_client()`
   - `OpenAICrossEncoder._get_client()`
   - `InputGuard._get_llm_client()`
   - `generator._get_llm_client(settings)`

3. **No `assert isinstance()` in production paths** — use `if not isinstance(): raise TypeError(...)`. Assert statements are silently disabled with Python's `-O` flag.

4. **Forbidden reranker backends: Qwen, BGE, Ollama, Mesh API**. Only `cohere`, `jina`, `openai` are valid values for `RERANKER_BACKEND`. This is enforced in `retrieval/reranker.py:get_reranker()`.

5. **`asyncio.get_running_loop()` not `get_event_loop()`** — `get_event_loop()` is deprecated in Python 3.12 and raises a `DeprecationWarning`. All async code uses `asyncio.get_running_loop()`.

6. **URL support in the parser** — `DocumentParser.parse()` accepts both file paths and `http://`/`https://` URLs via `_load_source()`. Do not add path existence checks before calling `parse()`.

7. **Qdrant RRF fusion** — always use `FusionQuery(fusion=Fusion.RRF)`, not `Query(fusion="rrf")`. `Query` is a Union type alias and cannot be instantiated directly.

8. **API versioning** — all routes except `/health`, `/metrics`, `/docs`, `/openapi.json` are mounted under `/v1`. Do not remove this prefix.

### Exception hierarchy

All application errors extend `DocIntelError` from `doc_intel_rag.exceptions`. FastAPI exception handlers in `api/app.py` map these to HTTP responses. When adding new error conditions, subclass the appropriate domain exception rather than raising bare `Exception` or `HTTPException`.

### Config validation bypass

Tests set `DOC_INTEL_SKIP_VALIDATION=1` via `tests/conftest.py` before any import. Never set this in production. The `Settings` validator checks for `MESH_API_KEY` unless this env var is set.

---

## Architecture Decisions

### Why three Qdrant vectors?

- `text_dense` (768-dim COSINE): semantic similarity, captures meaning
- `bm25_sparse` (2^17 buckets): exact keyword overlap, captures terminology
- `graph_dense` (128-dim COSINE): graph structure similarity via node2vec

Dense-only retrieval misses keyword-specific queries. Sparse-only misses semantic equivalents ("car" vs "automobile"). Graph adds structural relationship context unavailable in either text vector.

### Why Cohere/Jina/OpenAI for reranking?

These are **cross-encoders** — they process `(query, document)` together in a single forward pass, capturing fine-grained token interactions. Bi-encoders (BGE) re-sort by the same signal already used in retrieval. Generative LLMs (Qwen, Ollama) are 50–200× slower and produce uncalibrated scores.

### Why `dataclasses.replace()` in rerankers?

Rerankers may be called from concurrent requests sharing the same `ScoredChunk` objects retrieved from cache. Mutating `.score` in-place would corrupt cache state and produce non-deterministic results across concurrent calls.

### Why security headers skip `/docs`?

The Swagger UI loads external CDN resources (CSS, JS). CSP `default-src 'self'` would block those. The `/docs`, `/openapi.json`, `/redoc` paths are exempted in `RequestIDMiddleware`.

---

## Environment Variables

Minimum for local development:

```env
DOC_INTEL_SKIP_VALIDATION=0
MESH_API_KEY=your-key                  # or Ollama key
MESH_API_BASE_URL=http://localhost:11434/v1  # for Ollama
MESH_LLM_MODEL=llama3.2:1b
MESH_EMBEDDING_MODEL=nomic-embed-text
MESH_EMBEDDING_DIM=768
QDRANT_URL=http://localhost:6333
REDIS_URL=redis://localhost:6379
RERANKER_BACKEND=cohere
COHERE_API_KEY=your-cohere-key
TAVILY_API_KEY=your-tavily-key
API_KEYS=[]
CORS_ORIGINS=["*"]
LOG_JSON=false
```

Full reference: `.env.example`

---

## Testing

```
tests/
├── conftest.py          # Sets DOC_INTEL_SKIP_VALIDATION=1, MESH_API_KEY=test-key
├── unit/
│   ├── test_chunker.py          # 7 tests — chunking logic
│   ├── test_groundedness.py     # 4 tests — score formula
│   ├── test_graph_extractor.py  # 5 tests — graph extraction + NER
│   └── test_safety_input.py     # 9 tests — PII, injection, content class
└── integration/
    ├── test_ingest_pipeline.py  # Mocked document parse + chunk + embed
    ├── test_search_endpoint.py  # FastAPI TestClient, mocked dependencies
    └── test_generate_endpoint.py# FastAPI TestClient, SSE + non-streaming
```

All integration tests mock external APIs (Qdrant, LLM, Cohere) — no real API calls in CI.

---

## Deployment

Live URL: `http://doc-intel-rag-alb-1457953429.us-east-1.elb.amazonaws.com`

```bash
# Deploy to ECS Fargate
cd doc-intel-rag
export AWS_REGION=us-east-1
bash deploy/aws/deploy.sh

# View logs
aws logs tail /ecs/doc-intel-rag --follow --region us-east-1

# Check service health
aws ecs describe-services \
  --cluster doc-intel-rag-cluster \
  --services doc-intel-rag-service \
  --query 'services[0].{status:status,running:runningCount}' \
  --region us-east-1
```

Full deployment guide: `deploy/DEPLOYMENT.md`  
Architecture diagrams: `deploy/ARCHITECTURE.md`
