# doc-intel-rag — System Architecture

## Overview

doc-intel-rag is a production-grade multimodal Retrieval-Augmented Generation (RAG)
system. It ingests complex documents (PDF, DOCX, PPTX, HTML, Markdown), extracts and
indexes 35 distinct entity types per page, and answers natural language queries with
cited, grounded responses — including content from tables, formulas, charts, diagrams,
algorithms, and knowledge graphs.

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CLIENT LAYER                                    │
│                                                                              │
│   Browser / API Client / Streamlit Visualiser                                │
│              │ HTTP/SSE                                                      │
└──────────────┼───────────────────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         API GATEWAY / LOAD BALANCER                          │
│                                                                              │
│   AWS Application Load Balancer (port 80/443)                                │
│   • Routes to ECS Fargate tasks                                              │
│   • Health checks on /health                                                 │
└──────────────┬───────────────────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         APPLICATION LAYER (ECS Fargate)                      │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                      FastAPI Application                             │    │
│  │                                                                      │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │    │
│  │  │ Input Guard  │  │ Semantic     │  │ Output Guard             │  │    │
│  │  │ PII + Inject │  │ Router       │  │ NLI Faithfulness         │  │    │
│  │  │ Detection    │  │ 7 intents    │  │ Detoxify toxicity        │  │    │
│  │  └──────┬───────┘  └──────┬───────┘  └──────────────────────────┘  │    │
│  │         │                 │                                          │    │
│  │         ▼                 ▼                                          │    │
│  │  ┌─────────────────────────────────────────────────────────────┐   │    │
│  │  │                  RETRIEVAL PIPELINE                          │   │    │
│  │  │                                                              │   │    │
│  │  │  Dense Embed ──────────────────────────────────────────┐   │   │    │
│  │  │  (nomic-embed-text 768-dim)                             │   │   │    │
│  │  │                                                         ▼   │   │    │
│  │  │  BM25 Sparse ──────────────► Qdrant Hybrid Search ────►│   │   │    │
│  │  │  (feature-hashing 2^17)       RRF Fusion               │   │   │    │
│  │  │                                                         │   │   │    │
│  │  │  Graph Dense ──────────────────────────────────────────┘   │   │    │
│  │  │  (node2vec 128-dim)              │                          │   │    │
│  │  │                                  ▼                          │   │    │
│  │  │                    Cohere Rerank 3.5                        │   │    │
│  │  │                                  │                          │   │    │
│  │  │                    Groundedness Score                       │   │    │
│  │  │                                  │                          │   │    │
│  │  │                    < 0.45? ──► Tavily Web Search            │   │    │
│  │  └──────────────────────────────────┼──────────────────────────┘   │    │
│  │                                     ▼                               │    │
│  │  ┌──────────────────────────────────────────────────────────────┐  │    │
│  │  │              GENERATION PIPELINE                              │  │    │
│  │  │                                                               │  │    │
│  │  │  Context Builder → Jinja2 Prompt → LLM (llama3.2:1b)        │  │    │
│  │  │  Citation Formatter → SSE Stream → Output Guard              │  │    │
│  │  └──────────────────────────────────────────────────────────────┘  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            DATA LAYER                                        │
│                                                                              │
│  ┌─────────────────┐  ┌──────────────────┐  ┌────────────────────────────┐  │
│  │  Qdrant Cloud   │  │  Redis           │  │  NetworkX (in-memory)      │  │
│  │  (AWS us-west-2)│  │  (Docker/ECS)    │  │  Knowledge Graph Store     │  │
│  │                 │  │                  │  │  + Neo4j export (optional) │  │
│  │  3 named vectors│  │  Embedding cache │  │                            │  │
│  │  • text_dense   │  │  Query cache     │  │  2-hop graph traversal     │  │
│  │  • bm25_sparse  │  │  24hr/1hr TTL    │  │  at query time             │  │
│  │  • graph_dense  │  │                  │  │                            │  │
│  └─────────────────┘  └──────────────────┘  └────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        EXTERNAL SERVICES                                     │
│                                                                              │
│  ┌─────────────────┐  ┌──────────────────┐  ┌────────────────────────────┐  │
│  │  Ollama (local) │  │  Cohere API      │  │  Tavily Search API         │  │
│  │                 │  │                  │  │                            │  │
│  │  LLM Generation │  │  Rerank 3.5      │  │  Web fallback              │  │
│  │  llama3.2:1b    │  │  (reranking)     │  │  when groundedness < 0.45  │  │
│  │                 │  │                  │  │                            │  │
│  │  Embeddings     │  │                  │  │                            │  │
│  │  nomic-embed-   │  │                  │  │                            │  │
│  │  text 768-dim   │  │                  │  │                            │  │
│  └─────────────────┘  └──────────────────┘  └────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       OBSERVABILITY LAYER                                    │
│                                                                              │
│  Loguru JSON logs → CloudWatch Logs                                          │
│  Prometheus metrics → /metrics endpoint                                      │
│  OpenTelemetry traces → Jaeger (optional)                                    │
│  AWS CloudWatch → ECS service health + alarms                                │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Document Ingestion Pipeline

```
Document (PDF/DOCX/PPTX/HTML/MD)
         │
         ▼
  ┌─────────────┐
  │  GLM-OCR    │  PP-DocLayout-V3 detects 35 entity types per page
  │  Parser     │  (stub mode when API key not available)
  └──────┬──────┘
         │ ParseResult: list of ParsedElement
         ▼
  ┌─────────────┐
  │  Chunker    │  • Atomic elements → 1 chunk each (never split)
  │             │  • Text → accumulate to max_chunk_tokens (512)
  │             │  • Overlap → 64 tokens carried forward
  │             │  • section_path breadcrumbs maintained
  └──────┬──────┘
         │
         ▼
  ┌─────────────┐
  │  Graph      │  • Diagrams/flowcharts → Mesh API vision → NetworkX DiGraph
  │  Extractor  │  • Text → spaCy NER → entity co-occurrence edges
  └──────┬──────┘
         │
         ▼
  ┌─────────────┐
  │  Cross-Ref  │  Resolves "see Figure 3" → actual chunk_id (bidirectional)
  │  Linker     │
  └──────┬──────┘
         │
         ▼
  ┌─────────────┐
  │  Enrichment │  Per modality (Mesh API vision):
  │             │  image→caption, table→markdown+summary,
  │             │  formula→verbal+LaTeX, algorithm→steps,
  │             │  graph→edge list+summary, code→purpose
  └──────┬──────┘
         │
         ▼
  ┌─────────────┐
  │  Embedder   │  Dense: nomic-embed-text 768-dim (Redis cached)
  │             │  Sparse: BM25 feature-hash 2^17 buckets
  │             │  Graph: node2vec 128-dim averaged
  └──────┬──────┘
         │
         ▼
  ┌─────────────┐
  │  Qdrant     │  Upsert with 3 named vectors + full payload
  │  Cloud      │  Idempotent: doc_id SHA-256 hash check
  └─────────────┘
```

---

## Query Pipeline

```
User Query
    │
    ▼
Input Guard ──────────────────────────────────────────────────────┐
• presidio PII detection + redaction                              │
• 13-pattern + LLM injection detection                            │
• Content classification (benign/harmful)                         │
    │                                                             │
    ▼                                                             │
Semantic Router                                                    │
• LLM classifies into 7 intents:                                  │ BLOCKED
  factual / analytical / visual /                                 │ (GuardrailViolation)
  mathematical / code / relational / general                      │
    │                                                             │
    ▼                                                             │
Hybrid Search (Qdrant)                                             │
• Prefetch: text_dense (top 30) + bm25_sparse (top 30)           │
• RRF fusion → top 10                                             │
• Graph traversal (2-hop) for relational/analytical queries       │
    │                                                             │
    ▼                                                             │
Cohere Rerank 3.5 → top 5                                         │
    │                                                             │
    ▼                                                             │
Groundedness Score                                                 │
• Weighted cosine similarity of reranked results                  │
• Score < 0.45 → Tavily web search appended                       │
    │                                                             │
    ▼                                                             │
Context Builder                                                    │
• Assembles text / table / formula / image / graph blocks         │
• Web results clearly labelled [Web Source N]                     │
    │                                                             │
    ▼                                                             │
LLM Generation (llama3.2:1b via Ollama)                           │
• Jinja2 system prompt enforces citation rules                    │
• Streams token-by-token via SSE                                  │
• Final event: sources + groundedness + fallback_used             │
    │                                                             │
    ▼                                                             │
Output Guard                                                       │
• DeBERTa-v3 NLI faithfulness score < 0.5 → disclaimer           │
• Detoxify toxicity > 0.7 → blocked                               │
    │                                                             │
    ▼                                                             │
Response → Client ◄───────────────────────────────────────────────┘
```

---

## Data Models

### Chunk
| Field | Type | Description |
|---|---|---|
| chunk_id | UUID4 | Qdrant point ID |
| doc_id | SHA-256 | Source file hash (idempotency key) |
| modality | enum | text / image / table / formula / algorithm / graph / code |
| text | str | Markdown / verbal description |
| latex | str? | For formula chunks |
| html | str? | For table chunks |
| raw_image_b64 | str? | Base64 PNG crop for visual elements |
| is_atomic | bool | Never split (tables, formulas, figures) |
| section_path | list[str] | Breadcrumb from document root |
| cross_refs | list[str] | Linked chunk IDs |
| graph_json | dict? | Serialised NetworkX DiGraph |
| concept_tags | list[str] | spaCy NER entities |
| caption_json | dict? | Enrichment output from Mesh API |
| enriched_text | str | text + caption concatenation for embedding |

### Qdrant Named Vectors
| Vector | Dim | Distance | Purpose |
|---|---|---|---|
| text_dense | 768 | Cosine | Semantic similarity (nomic-embed-text) |
| bm25_sparse | 2^17 | — | Keyword overlap (feature-hash BM25) |
| graph_dense | 128 | Cosine | Graph structure similarity (node2vec) |

---

## AWS Infrastructure (ECS Fargate)

```
┌─────────────────────────────────────────────────────────────┐
│                         AWS Account                          │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                  VPC (default or custom)              │   │
│  │                                                       │   │
│  │  ┌────────────────┐      ┌────────────────────────┐  │   │
│  │  │  Public Subnet │      │  Public Subnet         │  │   │
│  │  │  (us-east-1a)  │      │  (us-east-1b)          │  │   │
│  │  │                │      │                        │  │   │
│  │  │  ┌──────────┐  │      │  ┌──────────┐         │  │   │
│  │  │  │  Fargate │  │      │  │  Fargate │         │  │   │
│  │  │  │  Task    │  │      │  │  Task    │         │  │   │
│  │  │  │  (2GB)   │  │      │  │  (2GB)   │         │  │   │
│  │  │  └────┬─────┘  │      │  └────┬─────┘         │  │   │
│  │  └───────┼────────┘      └───────┼────────────────┘  │   │
│  │          │                       │                    │   │
│  │          └──────────┬────────────┘                    │   │
│  │                     │                                 │   │
│  │            ┌────────▼────────┐                        │   │
│  │            │  App Load       │                        │   │
│  │            │  Balancer       │                        │   │
│  │            │  port 80/443    │                        │   │
│  │            └────────┬────────┘                        │   │
│  └─────────────────────┼───────────────────────────────  │   │
│                         │                                 │   │
└─────────────────────────┼─────────────────────────────────┘   │
                          │ Public URL
                          ▼
                     Internet

┌──────────────────────────────────────────────────────────────┐
│                   Supporting AWS Services                     │
│                                                              │
│  ECR          — Docker image registry                        │
│  Secrets Mgr  — API keys (Mesh, Qdrant, Cohere, Tavily)     │
│  CloudWatch   — Container logs (/ecs/doc-intel-rag)          │
│  IAM          — ecsTaskExecutionRole + ecsTaskRole           │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│                   External Services                           │
│                                                              │
│  Qdrant Cloud  — Vector DB (AWS us-west-2)                   │
│  Cohere API    — Reranking                                   │
│  Tavily API    — Web fallback search                         │
│  Ollama        — LLM + Embeddings (runs in Fargate task)     │
└──────────────────────────────────────────────────────────────┘
```

---

## Security Design

| Layer | Control |
|---|---|
| Network | ALB security group: only 80/443 inbound. ECS SG: only 8000 from ALB |
| Auth | X-API-Key header per request |
| Secrets | AWS Secrets Manager — never in environment or logs |
| Input | PII redaction + prompt injection detection on every query |
| Output | NLI faithfulness + Detoxify toxicity on every response |
| Logs | Secrets masked in all log records |
| IAM | Least-privilege task roles; OIDC for GitHub Actions (no static keys) |

---

## Technology Stack Summary

| Layer | Technology |
|---|---|
| Language | Python 3.12, strict type hints |
| API | FastAPI 0.115+ async, SSE streaming |
| LLM + Embeddings | Ollama (llama3.2:1b + nomic-embed-text) |
| Reranker | Cohere Rerank 3.5 |
| Vector DB | Qdrant Cloud (3 named vectors, RRF fusion) |
| Graph DB | NetworkX (in-memory) + Neo4j export |
| Cache | Redis (embeddings 24hr, queries 1hr) |
| Web Fallback | Tavily Search API |
| Safety | Presidio + DeBERTa-v3 NLI + Detoxify |
| Container | Docker multi-stage (CPU + CUDA GPU) |
| Orchestration | ECS Fargate + ALB |
| CI/CD | GitHub Actions → ECR → ECS |
| Secrets | AWS Secrets Manager |
| Logs | CloudWatch via awslogs driver |
| Package mgr | uv + pyproject.toml |
