# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All commands run from `doc-intel-rag/` using `uv run`.

```bash
# Tests
uv run pytest tests/unit/ -q --tb=short          # unit only (no external services)
uv run pytest tests/integration/ -q --tb=short   # integration (all deps mocked)
uv run pytest tests/ -x -q --tb=short            # full suite, stop on first failure
uv run pytest tests/unit/test_chunker.py -q      # single test file
uv run pytest tests/unit/test_chunker.py::test_atomic_element_not_split -q  # single test

# Lint + format
uv run ruff check src/
uv run ruff format src/

# Type checking
uv run mypy src/ --strict

# Run API server locally
uv run python scripts/serve.py --port 8000 --reload

# Full stack (Qdrant + Redis + Neo4j + Jaeger + app)
docker compose -f docker/docker-compose.yml up -d

# Ingest a document
uv run python scripts/ingest.py path/to/file.pdf --enrich

# Interactive search REPL
uv run python scripts/search.py --query "your question"
```

## Environment Setup

Copy `.env.example` to `.env`. Minimum required:
```
MESH_API_KEY=your-key        # required — blocks startup if missing
COHERE_API_KEY=your-key      # required when RERANKER_BACKEND=cohere (default)
```

`API_KEYS` and `CORS_ORIGINS` must be **JSON arrays** in `.env`:
```
API_KEYS=["key1","key2"]
CORS_ORIGINS=["https://yourdomain.com"]
```

For tests, `conftest.py` sets `DOC_INTEL_SKIP_VALIDATION=1` automatically — never set this in production as it bypasses the `MESH_API_KEY` presence check.

## Architecture

### Request Pipeline

Every query follows this linear path:

```
POST /v1/generate
  → InputGuard      (PII redaction → injection detection → content classification)
  → SemanticRouter  (classifies intent: factual / analytical / visual / mathematical / code / relational / general)
  → HybridSearcher  (dense + BM25 sparse + graph vectors via Qdrant RRF fusion; 2-hop graph traversal for relational/analytical)
  → Reranker        (Cohere / Jina / OpenAI cross-encoder — NOT Qwen/BGE/Ollama/Mesh)
  → Groundedness    (weighted cosine score; if < 0.45 triggers Tavily web fallback)
  → Generator       (streaming SSE via Mesh API; cites sources inline)
  → OutputGuard     (NLI faithfulness via deberta-v3 cross-encoder; Detoxify toxicity)
  → SSE response
```

### Settings Singleton

`config.py` exports `get_settings()` which caches a `Settings` instance process-wide. In tests, every fixture calls `reset_settings()` (from `config.py`) before and after to prevent state leakage between tests. Never instantiate `Settings()` directly in application code — always use `get_settings()`.

### Dependency Injection

`api/dependencies.py` maintains a module-level `_singletons` dict keyed by string name. All heavy objects (embedder, vector store, reranker, graph store, caches) are created once at startup via `init_singletons()` and retrieved via FastAPI `Depends()`. Redis failure at startup is silently swallowed — the app degrades gracefully without caching.

### Chunking Strategy

`chunking/document_chunker.py` processes `ParsedElement` lists in order:
- **Title elements** (`DOCUMENT_TITLE`, `SECTION_TITLE`, `SUBSECTION_TITLE`) flush the current accumulator and update `_section_path` — the breadcrumb list stored on every subsequent chunk (e.g. `["Methods", "Image Encoder"]`).
- **Atomic elements** (tables, formulas, images, code, graphs) are never split — each becomes exactly one chunk. A pending caption/title is prepended to the atomic chunk's text.
- **Text elements** accumulate into a buffer up to `MAX_CHUNK_TOKENS` (512). When the buffer fills, the last `CHUNK_OVERLAP_TOKENS` (64) tokens are carried into the next chunk via `_seed_overlap()`.

### Three-Vector Hybrid Search

Qdrant stores three vectors per chunk:
- `text_dense` (768-dim Mesh API embeddings) — semantic similarity
- `bm25_sparse` (2¹⁷ buckets, feature hashing) — keyword/BM25 exact match
- `graph_dense` (128-dim node2vec) — structural graph position

`MESH_EMBEDDING_DIM` is **immutable after first ingest** — changing it requires purging the entire Qdrant collection.

### Safety Layers

Two guard classes bookend every request:
- `InputGuard` — PII (Presidio), 13-pattern injection regex + LLM classifier, content classification. Violations raise typed exceptions (`PIIDetectedError`, `InjectionDetectedError`, `HarmfulContentError`) mapped to HTTP 400 in `app.py`.
- `OutputGuard` — NLI faithfulness (score < 0.5 appends a warning), Detoxify toxicity (score > 0.7 replaces answer with a refusal).

### Key Constraints

- **Reranker**: only `cohere`, `jina`, or `openai` are valid `RERANKER_BACKEND` values. Qwen, BGE, Ollama, and Mesh are architecturally excluded (see README for reasoning).
- **Vision enrichment**: `VISION_ENABLED=false` in ECS — requires Ollama locally.
- **Neo4j**: optional. Set `NEO4J_URI` to export graph data; omit for in-memory NetworkX only.
- **API auth**: `API_KEYS=[]` (empty list) disables auth entirely — development only.

## Branches and CI

- `dev` — active development branch
- `main` — production; every push triggers CI: unit tests → Docker build → ECR push → `terraform apply` to AWS ECS Fargate

CI runs only `tests/unit/` — integration tests require live Qdrant/Redis and are run locally.

## Live Infrastructure

- API: `http://doc-intel-rag-alb-1457953429.us-east-1.elb.amazonaws.com`
- Swagger: `/docs`, Health: `/health`, Metrics: `/metrics`
- Terraform state: S3 bucket `doc-intel-rag-tfstate-431445718054`, lock table `doc-intel-rag-tfstate-lock`
- CloudWatch alarms → SNS → `fetinue3@gmail.com`
