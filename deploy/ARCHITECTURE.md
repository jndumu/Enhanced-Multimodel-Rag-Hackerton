# doc-intel-rag — System Architecture

## Overview

doc-intel-rag is a production-grade multimodal Retrieval-Augmented Generation (RAG)
system. It ingests complex documents (PDF, DOCX, PPTX, HTML, Markdown), extracts and
indexes 35 distinct entity types per page, and answers natural language queries with
cited, grounded responses — including content from tables, formulas, charts, diagrams,
algorithms, and knowledge graphs.

---

## 1. High-Level System Architecture

```mermaid
graph TB
    Client["Client (curl / SDK / Demo UI)"]

    subgraph AWS ["AWS — ECS Fargate (us-east-1)"]
        ALB["Application Load Balancer\n(port 80 → /health target group)"]
        App["FastAPI App :8000\n(doc-intel-rag container)"]
        Secrets["AWS Secrets Manager\n(API keys injected at task start)"]
        ECR["ECR\n(Docker image registry)"]
        CW["CloudWatch Logs\n(/ecs/doc-intel-rag)"]
    end

    subgraph Storage ["Data Layer"]
        Qdrant["Qdrant Cloud\n(text_dense · bm25_sparse · graph_dense)"]
        Redis["Redis Cache\n(embeddings 24h · queries 1h)"]
        GraphStore["Graph Store\n(NetworkX in-memory + optional Neo4j)"]
    end

    subgraph ExternalAPIs ["External APIs"]
        MeshAPI["Mesh API (Requesty)\nmeta-llama/llama-3.2-3b-instruct\nnomic-embed-text · vision"]
        CohereAPI["Cohere\nRerank 3.5"]
        TavilyAPI["Tavily\nWeb search fallback"]
    end

    subgraph Observability
        OTel["OpenTelemetry → Jaeger\nPrometheus /metrics"]
    end

    Client --> ALB --> App
    App --> Secrets
    App --> Qdrant
    App --> Redis
    App --> GraphStore
    App --> MeshAPI
    App --> CohereAPI
    App --> TavilyAPI
    App --> CW
    App --> OTel
    ECR --> App
```

---

## 2. Document Ingestion Pipeline

```mermaid
graph TB
    Input["Document Input\n(PDF · DOCX · PPTX · HTML · Markdown · URL)"]

    subgraph Parsing ["Parsing Layer"]
        Parser["GLM-OCR + PP-DocLayout-V3\n(35 entity classes · bounding boxes · page crops)"]
        GraphEx["Graph Extractor\n(Vision LLM → DiGraph for diagrams)\n(spaCy NER → co-occurrence edges for text)"]
        XRef["Cross-Reference Linker\n('see Figure 3' → chunk_id bidirectional)"]
        PostProc["Post Processor\n(ParseResult → structured Markdown)"]
    end

    subgraph Chunking ["Chunking Layer"]
        Chunker["Document-Aware Chunker\n(atomic elements = 1 chunk · text accumulates to 512 tokens)\n(64-token overlap · section_path breadcrumbs)"]
        Merger["Semantic Merger\n(merge tiny adjacent text chunks · cosine > 0.85)"]
    end

    subgraph Enrichment ["Enrichment Layer (optional)"]
        Captioner["Vision Captioner\n(image/chart/graph → structured JSON via Mesh API vision)"]
        FormulaEnricher["Formula Enricher\n(pylatexenc validation · verbal description · variable extraction)"]
        ConceptExtractor["Concept Extractor\n(spaCy NER → concept_tags per chunk)"]
        GraphEnricher["Graph Enricher\n(edge list + centrality + LLM summary)"]
    end

    subgraph Embedding ["Embedding Layer"]
        DenseEmb["Dense Embedder\n(Mesh API · nomic-embed-text · 768-dim · Redis cached)"]
        SparseEmb["Sparse BM25\n(MurmurHash3 feature-hashing · 2¹⁷ buckets · TF normalised)"]
        GraphEmb["Graph Embedder\n(node2vec · 10-step walks · 128-dim · averaged + L2-norm)"]
    end

    subgraph Storage ["Storage Layer"]
        Qdrant["Qdrant Cloud\n(text_dense · bm25_sparse · graph_dense)\n(idempotent upsert by doc_id SHA-256)"]
        GraphStore["Graph Store\n(NetworkX DiGraph per doc · optional Neo4j export)"]
    end

    Input --> Parser
    Parser --> GraphEx
    Parser --> PostProc
    GraphEx --> XRef
    XRef --> Chunker
    Chunker --> Merger
    Merger --> Captioner
    Merger --> FormulaEnricher
    Merger --> ConceptExtractor
    GraphEx --> GraphEnricher
    GraphEx --> GraphStore

    Captioner --> DenseEmb
    FormulaEnricher --> DenseEmb
    ConceptExtractor --> DenseEmb
    DenseEmb --> Qdrant
    DenseEmb --> SparseEmb --> Qdrant
    GraphEmb --> Qdrant
    GraphEx --> GraphEmb
```

---

## 3. Query & Generation Pipeline

```mermaid
graph TB
    Query["User Query"]

    subgraph Safety_In ["Input Safety (pre-retrieval)"]
        PII["Stage 1 — PII Detection\n(Presidio · 10 entity types · redact or block)"]
        Injection["Stage 2 — Injection Detection\n(13 regex patterns + LLM classifier)"]
        Content["Stage 3 — Content Classification\n(regex harmful patterns → HTTP 400)"]
    end

    subgraph Routing ["Intent Routing"]
        Router["Semantic Router\n(LLM → JSON intent · 7 classes)\nfactual · analytical · visual · mathematical\ncode · relational · general"]
    end

    subgraph Retrieval ["Retrieval Layer"]
        HybridSearch["Hybrid Searcher\n(Dense query embed + BM25 sparse encode)\n(Qdrant Prefetch × 3 → RRF Fusion rank=60)"]
        GraphTraversal["Graph Traversal\n(2-hop BFS through NetworkX DiGraph)\n(triggered for relational / analytical intents)"]
        Reranker["Reranker\n(Cohere rerank-v3.5 · Jina · OpenAI cross-encoder)\n(re-scores top-N by true relevance)"]
        Ground["Groundedness Scorer\n(weighted cosine of reranked scores)\n(threshold 0.45)"]
        WebFB["Web Fallback\n(Tavily Search · up to 5 results)\n(appended as retrieval_source='web' chunks)"]
    end

    subgraph Generation ["Generation Layer"]
        CtxBuilder["Context Builder\n(text · table HTML · LaTeX formula · base64 image · graph edges · web URL)"]
        Prompt["Jinja2 Prompt Templates\n(system: cite every claim · user: query + context)"]
        Generator["LLM Generator\n(Mesh API · meta-llama/llama-3.2-3b-instruct · streaming SSE)\n(yields delta tokens → final sources + groundedness event)"]
        Citations["Citation Formatter\n([Source N] markers + bibliography block)"]
    end

    subgraph Safety_Out ["Output Safety (post-generation)"]
        NLI["Faithfulness — NLI Cross-Encoder\n(cross-encoder/nli-deberta-v3-base)\n(entailment score < 0.5 → disclaimer appended)"]
        Toxicity["Toxicity — Detoxify\n(6 dimensions · score > 0.7 → blocked response)"]
    end

    Response["SSE Stream / JSON Response → Client"]

    Query --> PII --> Injection --> Content --> Router
    Router --> HybridSearch
    HybridSearch --> GraphTraversal --> Reranker
    HybridSearch --> Reranker
    Reranker --> Ground
    Ground -->|"score ≥ 0.45"| CtxBuilder
    Ground -->|"score < 0.45"| WebFB --> CtxBuilder
    CtxBuilder --> Prompt --> Generator --> Citations --> NLI --> Toxicity --> Response
```

---

## 4. AWS Infrastructure

```mermaid
graph TB
    Internet["Internet"]

    subgraph AWS_Infra ["AWS Account (us-east-1) — managed by Terraform"]
        ALB["Application Load Balancer\nHTTP :80 · health check GET /health"]

        subgraph ECS_Cluster ["ECS Fargate Cluster"]
            Task1["Fargate Task\n(doc-intel-rag container)\n1 vCPU · 2 GB RAM"]
            Task2["Fargate Task\n(auto-scaled replica)\n1 vCPU · 2 GB RAM"]
        end

        subgraph Scaling ["Auto Scaling"]
            CPU_Scale["CPU > 70% → scale out\n(60s cooldown)"]
            Mem_Scale["Memory > 80% → scale out\n(60s cooldown)"]
        end

        subgraph Supporting ["Supporting Services"]
            ECR["ECR\n(Docker image registry)\nlifecycle: keep 10 images"]
            SecretsMgr["Secrets Manager\n(MESH_API_KEY · QDRANT_URL\nQDRANT_API_KEY · COHERE_API_KEY\nTAVILY_API_KEY · JINA_API_KEY)"]
            CWLogs["CloudWatch Logs\n(/ecs/doc-intel-rag)\nalarms → SNS → email"]
            IAM["IAM Roles\necsTaskExecutionRole\necsTaskRole (least-privilege)"]
            S3["S3 + DynamoDB\n(Terraform remote state\n+ locking)"]
        end
    end

    subgraph CICD ["CI/CD (GitHub Actions)"]
        Test["1. uv run pytest"]
        Build["2. Docker build + ECR push\n(tagged with git SHA)"]
        TF["3. terraform apply\n(plan on PR · apply on main)"]
    end

    Internet --> ALB --> Task1
    ALB --> Task2
    CPU_Scale --> ECS_Cluster
    Mem_Scale --> ECS_Cluster
    SecretsMgr --> Task1 & Task2
    ECR --> Task1 & Task2
    Task1 & Task2 --> CWLogs
    IAM --> Task1 & Task2
    Test --> Build --> TF --> ECS_Cluster
```

---

## 5. Data Models

### Chunk

| Field | Type | Description |
|---|---|---|
| `chunk_id` | UUID4 | Qdrant point ID |
| `doc_id` | SHA-256 | Source file hash — idempotency key |
| `modality` | enum | `text · image · table · formula · algorithm · graph · code` |
| `text` | str | Markdown / verbal content |
| `latex` | str? | Raw LaTeX for formula chunks |
| `html` | str? | HTML markup for table chunks |
| `raw_image_b64` | str? | Base64 PNG crop — NOT stored in Qdrant |
| `is_atomic` | bool | Never split (tables, formulas, figures) |
| `section_path` | list[str] | Breadcrumb from document root |
| `cross_refs` | list[str] | Linked chunk IDs from cross-reference linker |
| `graph_json` | dict? | Serialised NetworkX DiGraph |
| `concept_tags` | list[str] | spaCy NER named entities |
| `caption_json` | dict? | Structured enrichment payload from Mesh API |
| `enriched_text` | str | `text + caption_json` — used for dense embedding |

### Qdrant Named Vectors

| Vector | Dim | Distance | Purpose |
|---|---|---|---|
| `text_dense` | 768 | Cosine | Semantic similarity (nomic-embed-text) |
| `bm25_sparse` | 2¹⁷ | — | Keyword overlap (MurmurHash3 BM25) |
| `graph_dense` | 128 | Cosine | Graph structure similarity (node2vec) |

---

## 6. Security Design

| Layer | Control |
|---|---|
| Network | ALB SG: only port 80 inbound from internet. ECS SG: only port 8000 from ALB SG |
| Auth | `X-API-Key` header — configurable list, empty = dev mode (no auth) |
| Secrets | AWS Secrets Manager — injected at task startup, never in image or logs |
| Input | PII redaction (Presidio) + prompt injection (13 patterns + LLM) on every query |
| Output | NLI faithfulness (deberta-v3-base) + Detoxify toxicity on every response |
| Logs | All API keys masked in Loguru records via `_mask_secrets` filter |
| IAM | Least-privilege task roles; OIDC (`GitHubActionsDeployRole`) for CI — no static keys |

---

## 7. Technology Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12, strict type hints throughout |
| API | FastAPI 0.115+ async, Server-Sent Events streaming |
| LLM + Embeddings | Mesh API / Requesty (`meta-llama/llama-3.2-3b-instruct` · `nomic-embed-text`) |
| Reranker | Cohere Rerank 3.5 (default) · Jina multimodal · OpenAI cross-encoder |
| Vector DB | Qdrant Cloud — 3 named vectors, Prefetch + RRF fusion |
| Graph DB | NetworkX (in-memory) + optional Neo4j Bolt export |
| Cache | Redis — embedding TTL 24h, query TTL 1h |
| Web Fallback | Tavily Search API |
| Safety | Microsoft Presidio (PII) · deberta-v3-base NLI · Detoxify |
| Container | Docker multi-stage CPU build + CUDA 12.4 GPU variant |
| Orchestration | AWS ECS Fargate + ALB — auto-scaling 1–5 tasks |
| IaC | Terraform 7 modules — S3 remote state + DynamoDB lock |
| CI/CD | GitHub Actions — test → build → ECR → terraform apply |
| Secrets | AWS Secrets Manager (6 secrets, `prevent_destroy = true`) |
| Logs | CloudWatch via `awslogs` driver + Loguru JSON structured logs |
| Traces | OpenTelemetry OTLP → Jaeger · Prometheus `/metrics` |
| Package manager | uv + `pyproject.toml` |
