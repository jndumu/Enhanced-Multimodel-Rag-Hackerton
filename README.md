# doc-intel-rag

Production-grade, enhanced multimodal RAG system with graph intelligence.

```
╔══════════════════════════════════════════════════════════════════════╗
║                     doc-intel-rag  Architecture                     ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  Documents (PDF/DOCX/PPTX/HTML/MD)                                   ║
║        │                                                             ║
║        ▼                                                             ║
║  ┌─────────────┐  PP-DocLayout-V3   ┌──────────────────────────┐    ║
║  │  GLM-OCR    │──────────────────► │  35 Entity Labels         │    ║
║  │  Pipeline   │                    │  text/table/formula/      │    ║
║  └─────────────┘                    │  image/graph/algorithm    │    ║
║        │                            └──────────────────────────┘    ║
║        ▼                                                             ║
║  Document-Aware Chunker                                              ║
║  • Atomic elements (never split)                                     ║
║  • Section-path breadcrumbs                                          ║
║  • Overlap + semantic merger                                         ║
║  • Cross-reference linker                                            ║
║        │                                                             ║
║        ▼                                                             ║
║  Enrichment (Mesh API Vision)                                        ║
║  image/chart/table/formula/algorithm/code/graph captions             ║
║  + spaCy NER concept tags + formula LaTeX validation                 ║
║        │                                                             ║
║        ▼                                                             ║
║  Qdrant (3 named vectors)                                            ║
║  text_dense + bm25_sparse + graph_dense (node2vec)                  ║
║                                                                      ║
║  ─────────────────── Query Path ─────────────────────────────────── ║
║                                                                      ║
║  User Query                                                           ║
║    → Input Guard (PII + Injection + Content)                         ║
║    → Semantic Router (7 intents)                                     ║
║    → Hybrid Search (dense + sparse + graph RRF)                      ║
║    → Reranker (Cohere / Jina / OpenAI)                               ║
║    → Groundedness Score → [Tavily fallback if < threshold]           ║
║    → Mesh API Streaming Generation + Citation Formatter              ║
║    → Output Guard (Faithfulness NLI + Detoxify)                      ║
║    → SSE Stream to Client                                             ║
╚══════════════════════════════════════════════════════════════════════╝
```

## Quickstart

### 1. Prerequisites

- Python 3.12+, `uv` package manager
- Docker + Docker Compose (for full stack)

### 2. Install

```bash
git clone https://github.com/jndumu/Enhanced-Multimodel-Rag-Hackerton.git
cd Enhanced-Multimodel-Rag-Hackerton/doc-intel-rag
uv sync
```

### 3. Configure

```bash
cp .env.example .env
# Fill in at minimum: MESH_API_KEY
# Plus one of: COHERE_API_KEY / JINA_API_KEY / OPENAI_API_KEY (for reranking)
```

### 4. Run (Docker Compose — recommended)

```bash
docker compose -f docker/docker-compose.yml up -d
# API:        http://localhost:8000
# Qdrant UI:  http://localhost:6333/dashboard
# Graph viz:  http://localhost:8501
# Jaeger:     http://localhost:16686
```

### 5. Run (local)

```bash
# Start Qdrant and Redis, then:
uv run python scripts/serve.py --port 8000 --reload
```

### 6. Ingest a document

```bash
# CLI
uv run python scripts/ingest.py path/to/document.pdf

# REST API
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{"source": "/path/to/doc.pdf", "enrich": true}'
```

### 7. Generate an answer

```bash
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the main conclusion?", "streaming": false}'
```

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `MESH_API_KEY` | ✅ | — | Mesh AI API key |
| `MESH_API_BASE_URL` | | `https://api.mesh.ai/v1` | Mesh API base URL |
| `MESH_LLM_MODEL` | | `mesh-gpt-4o` | Generation model |
| `MESH_EMBEDDING_MODEL` | | `mesh-text-embedding-3-large` | Embedding model |
| `GLMOCR_API_KEY` | | — | GLM-OCR API key |
| `GLMOCR_BACKEND` | | `cloud` | `cloud` or `local` |
| `QDRANT_URL` | | `http://localhost:6333` | Qdrant URL |
| `REDIS_URL` | | `redis://localhost:6379` | Redis URL |
| `RERANKER_BACKEND` | | `cohere` | `cohere`, `jina`, or `openai` |
| `COHERE_API_KEY` | | — | Required if reranker=cohere |
| `JINA_API_KEY` | | — | Required if reranker=jina |
| `OPENAI_API_KEY` | | — | Required if reranker=openai |
| `TAVILY_API_KEY` | | — | Tavily Search (web fallback) |
| `GROUNDEDNESS_THRESHOLD` | | `0.45` | Below this → web fallback |
| `API_KEYS` | | `[]` | JSON array of valid API keys |

See `.env.example` for the complete list with documentation.

## API Reference

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/health` | — | Component health check |
| `GET` | `/metrics` | — | Prometheus metrics |
| `POST` | `/ingest` | key | Ingest URL or file path |
| `POST` | `/ingest/file` | key | Upload file (multipart) |
| `DELETE` | `/collections/{name}` | key | Delete collection |
| `POST` | `/search` | key | Retrieve + rerank only |
| `POST` | `/generate` | key | Full RAG pipeline, SSE stream |
| `GET` | `/graph/{doc_id}` | key | Export knowledge graph JSON |
| `GET` | `/admin/stats` | key | Stats and uptime |
| `POST` | `/admin/purge-cache` | key | Flush Redis query cache |

Auth: pass `X-API-Key: <your-key>` header. Omit if `API_KEYS=[]`.

## Safety Architecture

### Input Guard
1. **PII detection + redaction** — `presidio-analyzer` detects PERSON, EMAIL, PHONE, IP, CREDIT_CARD, IBAN, NRP, LOCATION, DATE_TIME, URL. Redacts or blocks (configurable).
2. **Prompt injection detection** — 13 regex patterns + Mesh API LLM classifier.
3. **Content classification** — benign / sensitive / off-topic / harmful.

### Output Guard
1. **Faithfulness scoring** — NLI cross-encoder (`deberta-v3-base`) scores entailment(context, answer). Score < 0.5 adds disclaimer.
2. **Toxicity filter** — Detoxify checks all dimensions. Score > 0.7 blocks the response.

## Web Fallback

When `groundedness_score < GROUNDEDNESS_THRESHOLD`:
1. Tavily Search API is called with the original query
2. Results are formatted as `ScoredChunk` with `retrieval_source="web"`
3. Web citations appear as `[Web Source N]` in the answer
4. API response includes `fallback_used: true` and `web_sources: [...]`

## Reranker Options

| Backend | Model | Notes |
|---|---|---|
| `cohere` *(default)* | `rerank-v3.5` | Best quality, multimodal |
| `jina` | `jina-reranker-v2-base-multilingual` | Multilingual, fast |
| `openai` | `gpt-4o-mini` | Parallel cross-encoder prompts |

> **Forbidden**: Qwen, BGE, Ollama, Mesh API must not be used for reranking.

## Running Tests

```bash
# Unit tests only (no external services needed)
uv run pytest tests/unit/ -q

# All tests
uv run pytest tests/ -q --tb=short
```

## GPU Deployment

```bash
docker build -f docker/Dockerfile.gpu -t doc-intel-rag:gpu .
docker run --gpus all -p 8000:8000 --env-file .env doc-intel-rag:gpu
```
