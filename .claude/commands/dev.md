# doc-intel-rag dev skill
> Full project reference: see [CLAUDE.md](../CLAUDE.md)

You are helping develop **doc-intel-rag** — a production-grade multimodal RAG system built with FastAPI, Qdrant, Redis, and the Mesh API. The project root is `doc-intel-rag/`. All commands below are run from that directory.

## Package manager
Always use `uv run` to execute Python scripts and tools (not `python` directly).

## Key commands

### Run tests
```bash
uv run pytest tests/ -x -q --tb=short          # all tests (32)
uv run pytest tests/unit/ -q                    # unit only (no external services)
uv run pytest tests/integration/ -q             # integration (mocked APIs)
```

### Lint + type check
```bash
uv run ruff check src/ && uv run ruff format src/
uv run mypy src/ --strict
```

### Start the full stack (Docker)
```bash
docker compose -f docker/docker-compose.yml up -d
# Services: app :8000, Qdrant :6333, Redis :6379, Neo4j :7474, Jaeger :16686, Streamlit :8501
```

### Start API server locally (no Docker)
```bash
uv run python scripts/serve.py --port 8000 --reload
```

### Ingest a document
```bash
uv run python scripts/ingest.py <file.pdf> --enrich
# Or via API:
curl -X POST http://localhost:8000/v1/ingest/file \
  -H "X-API-Key: $API_KEY" \
  -F "file=@document.pdf" -F "enrich=true"
```

### Search
```bash
uv run python scripts/search.py --query "your question"
# Or via API:
curl -X POST http://localhost:8000/v1/search \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "your question", "top_k": 20, "top_n": 5}'
```

### Generate (streaming SSE)
```bash
curl -N -X POST http://localhost:8000/v1/generate \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "summarise key findings", "streaming": true, "max_tokens": 1024}'
```

### Health check
```bash
curl http://localhost:8000/health
```

## Project structure (key files)
- `src/doc_intel_rag/config.py` — all settings via Pydantic-settings v2 (single source of truth)
- `src/doc_intel_rag/api/app.py` — FastAPI factory + lifespan
- `src/doc_intel_rag/api/dependencies.py` — singleton DI (embedder, vector_store, reranker)
- `src/doc_intel_rag/api/routes/` — ingest, search, generate, graph, health, admin
- `src/doc_intel_rag/safety/input_guard.py` — PII + injection + content classification
- `src/doc_intel_rag/retrieval/hybrid_searcher.py` — RRF fusion + 2-hop graph traversal
- `src/doc_intel_rag/generation/generator.py` — streaming SSE generation
- `tests/conftest.py` — sets `DOC_INTEL_SKIP_VALIDATION=1` for all tests

## Required environment variables (.env)
| Variable | Purpose |
|---|---|
| `MESH_API_KEY` | LLM + embeddings (required) |
| `COHERE_API_KEY` | Reranker default backend |
| `TAVILY_API_KEY` | Web fallback search |
| `GLMOCR_API_KEY` | Cloud document parsing |
| `QDRANT_URL` | Vector store (default: http://localhost:6333) |
| `REDIS_URL` | Cache (default: redis://localhost:6379) |
| `API_KEYS` | JSON array of valid API keys (empty = no auth) |

## Branch conventions
- `main` — production, deploys to AWS ECS Fargate via CI/CD on push
- `dev` — active development; PRs merge into main after tests pass
- CI runs `uv run pytest tests/unit/` → Docker build → ECR push → `terraform apply`

## Deployment (main branch only)
```bash
cd terraform && terraform plan   # preview
cd terraform && terraform apply  # apply
# Or push to main — CI/CD handles it automatically via .github/workflows/deploy-ecs.yml
```

## Live endpoints (production)
- API + Swagger: `http://doc-intel-rag-alb-1457953429.us-east-1.elb.amazonaws.com/docs`
- Health: `http://doc-intel-rag-alb-1457953429.us-east-1.elb.amazonaws.com/health`
- Metrics: `http://doc-intel-rag-alb-1457953429.us-east-1.elb.amazonaws.com/metrics`

## Common debugging
- **Tests fail with validation errors**: ensure `DOC_INTEL_SKIP_VALIDATION=1` is set (conftest.py handles this automatically)
- **Embedding dimension mismatch**: `MESH_EMBEDDING_DIM` is immutable after first ingest — purge the Qdrant collection to change it
- **Reranker errors**: only `cohere`, `jina`, or `openai` are valid `RERANKER_BACKEND` values
- **Groundedness always triggering fallback**: lower `GROUNDEDNESS_THRESHOLD` below `0.45` or set `FALLBACK_ENABLED=false`
