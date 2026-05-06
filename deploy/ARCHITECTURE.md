# doc-intel-rag — Enterprise Architecture Reference

> **Author:** Josephine Ndumu  
> **Stack:** Python 3.12 · FastAPI · Qdrant · Redis · Cohere · Tavily · AWS ECS Fargate  
> **Version:** 0.1.0

---

## Table of Contents

1. [System Context (C4 Level 1)](#1-system-context-c4-level-1)
2. [High-Level System Architecture (C4 Level 2)](#2-high-level-system-architecture-c4-level-2)
3. [Document Ingestion Pipeline](#3-document-ingestion-pipeline)
4. [Retrieval & Generation Pipeline](#4-retrieval--generation-pipeline)
5. [Three-Vector Hybrid Search Architecture](#5-three-vector-hybrid-search-architecture)
6. [Knowledge Graph Architecture](#6-knowledge-graph-architecture)
7. [Safety Architecture](#7-safety-architecture)
8. [AWS Deployment Topology](#8-aws-deployment-topology)
9. [CI/CD Pipeline](#9-cicd-pipeline)
10. [Observability Stack](#10-observability-stack)
11. [Data Models & Schemas](#11-data-models--schemas)
12. [Technology Stack Summary](#12-technology-stack-summary)

---

## 1. System Context (C4 Level 1)

> Who interacts with the system and what external services does it depend on.

```
                    ┌─────────────────────────────────────┐
                    │                                     │
        ┌───────────┤         doc-intel-rag               ├───────────┐
        │           │                                     │           │
        │           │  Production-grade multimodal RAG    │           │
        │           │  system. Ingests documents, builds  │           │
        │           │  knowledge graphs, answers queries  │           │
        │           │  with grounded, cited responses.    │           │
        │           │                                     │           │
        │           └──────────────────┬──────────────────┘           │
        │                              │                               │
        │                              │                               │
   ┌────▼────┐                ┌────────▼────────┐              ┌──────▼──────┐
   │  Human  │                │   API Consumer  │              │  CI/CD Bot  │
   │  User   │                │                 │              │             │
   │         │                │  Internal apps, │              │  GitHub     │
   │ Uploads │                │  dashboards,    │              │  Actions    │
   │ docs,   │                │  automation     │              │  deploys on │
   │ asks    │                │  pipelines      │              │  push to    │
   │ queries │                │  (REST/SSE)     │              │  main       │
   └────┬────┘                └────────┬────────┘              └──────┬──────┘
        │                              │                               │
        │         HTTP / SSE           │                      OIDC + ECR push
        └──────────────────────────────┘                               │
                        │                                              │
             ┌──────────▼──────────────────────────────────────────────▼───┐
             │                    AWS Cloud (us-east-1)                     │
             │                                                              │
             │   ALB → ECS Fargate → Secrets Manager → CloudWatch          │
             └──────────────────────────────────────────────────────────────┘
                        │                    │                    │
               ┌────────▼──────┐   ┌─────────▼──────┐  ┌────────▼────────┐
               │  Qdrant Cloud │   │   Cohere API   │  │  Tavily Search  │
               │  (us-west-2)  │   │                │  │  API            │
               │               │   │  Rerank 3.5    │  │                 │
               │  Vector DB    │   │  Cross-encoder │  │  Web fallback   │
               │  3 vectors    │   │  reranking     │  │  search         │
               └───────────────┘   └────────────────┘  └─────────────────┘
```

---

## 2. High-Level System Architecture (C4 Level 2)

> The major functional layers and how they connect.

```
═══════════════════════════════════════════════════════════════════════════════
                              PRESENTATION LAYER
═══════════════════════════════════════════════════════════════════════════════

  ┌──────────────────┐  ┌──────────────────┐  ┌───────────────────────────┐
  │   Browser /      │  │  API Consumer    │  │  Streamlit Visualiser     │
  │   Swagger UI     │  │  (curl / SDK)    │  │  (Knowledge Graph UI)     │
  └────────┬─────────┘  └────────┬─────────┘  └─────────────┬─────────────┘
           │                     │                            │
           └─────────────────────┴────────────────────────────┘
                                 │  HTTP / SSE
                                 ▼
═══════════════════════════════════════════════════════════════════════════════
                              GATEWAY LAYER
═══════════════════════════════════════════════════════════════════════════════

  ┌─────────────────────────────────────────────────────────────────────────┐
  │              AWS Application Load Balancer (port 80)                    │
  │                                                                         │
  │   Health check: GET /health every 30s                                  │
  │   Target group: ECS tasks on port 8000                                 │
  │   Security group: 80/443 inbound from 0.0.0.0/0                       │
  └─────────────────────────────────┬───────────────────────────────────────┘
                                    │
                                    ▼
═══════════════════════════════════════════════════════════════════════════════
                           APPLICATION LAYER  (ECS Fargate)
═══════════════════════════════════════════════════════════════════════════════

  ┌─────────────────────────────────────────────────────────────────────────┐
  │                         FastAPI (Uvicorn)                               │
  │                                                                         │
  │   Middleware stack (innermost → outermost):                             │
  │   CORS → Rate-Limit (slowapi) → Request-ID → OTel trace propagation    │
  │                                                                         │
  │  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────────────┐  │
  │  │ POST       │ │ POST       │ │ POST       │ │ GET /health        │  │
  │  │ /v1/ingest │ │ /v1/search │ │/v1/generate│ │ GET /metrics       │  │
  │  │ /v1/ingest │ │            │ │ (SSE or    │ │ GET /v1/graph/{id} │  │
  │  │ /file      │ │            │ │  JSON)     │ │ GET /v1/admin/stat │  │
  │  └─────┬──────┘ └─────┬──────┘ └─────┬──────┘ └────────────────────┘  │
  │        │              │              │                                  │
  │        ▼              ▼              ▼                                  │
  │  ┌─────────────────────────────────────────────────────────────────┐   │
  │  │                   SAFETY LAYER (pre-request)                    │   │
  │  │   InputGuard: PII redact → Injection detect → Content classify  │   │
  │  └─────────────────────────────┬───────────────────────────────────┘   │
  │                                │                                        │
  │        ┌───────────────────────┼───────────────────────┐               │
  │        │                       │                       │               │
  │        ▼                       ▼                       ▼               │
  │  ┌───────────┐         ┌───────────────┐        ┌────────────┐         │
  │  │ INGESTION │         │  RETRIEVAL    │        │ GENERATION │         │
  │  │ PIPELINE  │         │  PIPELINE     │        │ PIPELINE   │         │
  │  │           │         │               │        │            │         │
  │  │ Parse     │         │ Semantic      │        │ Context    │         │
  │  │ Chunk     │         │ Router        │        │ Builder    │         │
  │  │ Enrich    │         │ Hybrid Search │        │ Prompt     │         │
  │  │ Embed     │         │ Rerank        │        │ Template   │         │
  │  │ Upsert    │         │ Groundedness  │        │ LLM Call   │         │
  │  └───────────┘         │ Web Fallback  │        │ SSE Stream │         │
  │                        └───────────────┘        └────────────┘         │
  │                                                        │               │
  │                                                        ▼               │
  │                                          ┌─────────────────────────┐   │
  │                                          │  SAFETY LAYER (post)    │   │
  │                                          │  OutputGuard:           │   │
  │                                          │  NLI faithfulness       │   │
  │                                          │  Detoxify toxicity      │   │
  │                                          └─────────────────────────┘   │
  └─────────────────────────────────────────────────────────────────────────┘
                    │                   │                    │
                    ▼                   ▼                    ▼
═══════════════════════════════════════════════════════════════════════════════
                               DATA LAYER
═══════════════════════════════════════════════════════════════════════════════

  ┌─────────────────┐   ┌──────────────────┐   ┌────────────────────────────┐
  │  Qdrant Cloud   │   │  Redis           │   │  NetworkX Graph Store      │
  │                 │   │                  │   │  (in-memory per document)  │
  │  text_dense     │   │  EmbeddingCache  │   │                            │
  │  bm25_sparse    │   │  TTL: 24 hr      │   │  DiGraph per doc_id        │
  │  graph_dense    │   │                  │   │  2-hop query traversal     │
  │                 │   │  QueryCache      │   │                            │
  │  RRF fusion     │   │  TTL: 1 hr       │   │  Optional: Neo4j export    │
  └─────────────────┘   └──────────────────┘   └────────────────────────────┘

═══════════════════════════════════════════════════════════════════════════════
                           EXTERNAL SERVICES LAYER
═══════════════════════════════════════════════════════════════════════════════

  ┌─────────────────┐   ┌──────────────────┐   ┌────────────────────────────┐
  │  LLM Provider   │   │  Cohere API      │   │  Tavily Search API         │
  │  (OpenAI-compat)│   │                  │   │                            │
  │                 │   │  Rerank 3.5      │   │  Triggered when            │
  │  Generation     │   │  Cross-encoder   │   │  groundedness < 0.45       │
  │  Embeddings     │   │  reranking       │   │  Returns up to 5 results   │
  └─────────────────┘   └──────────────────┘   └────────────────────────────┘
```

---

## 3. Document Ingestion Pipeline

> End-to-end flow from raw document to indexed vectors.

```
  INPUT
  ─────
  POST /v1/ingest        { source: "path/or/url", enrich: true }
  POST /v1/ingest/file   multipart upload (PDF, DOCX, PPTX, HTML, MD)

                                    │
                                    ▼
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  STEP 1 — IDEMPOTENCY CHECK                                             │
  │                                                                         │
  │  doc_id = SHA-256(file bytes)                                           │
  │  Qdrant scroll filter: doc_id exists?                                   │
  │    ├── YES (force=false) → return cached:true, skip pipeline            │
  │    └── NO  (or force=true) → continue                                   │
  └─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  STEP 2 — DOCUMENT PARSING  (parsing/pipeline.py)                       │
  │                                                                         │
  │  GLM-OCR + PP-DocLayout-V3 layout detection                             │
  │                                                                         │
  │  Input:  file path or URL                                               │
  │  Output: ParseResult                                                    │
  │            ├── doc_id: str (SHA-256)                                    │
  │            ├── source_file: str                                         │
  │            ├── page_count: int                                          │
  │            └── elements: list[ParsedElement]                            │
  │                  ├── label: EntityLabel  (1 of 35 types)                │
  │                  ├── text: str                                           │
  │                  ├── bbox: BBox  (x0,y0,x1,y1,page)                    │
  │                  ├── confidence: float                                   │
  │                  ├── raw_image_b64: str?  (visual elements)             │
  │                  ├── latex: str?          (formula elements)             │
  │                  └── html: str?           (table elements)               │
  │                                                                         │
  │  35 Entity Labels:                                                       │
  │  ┌─────────────┬──────────────────────┬──────────────┬───────────────┐ │
  │  │ Structural  │ Mathematical         │ Visual       │ Code          │ │
  │  │ ──────────  │ ────────────────     │ ──────       │ ────          │ │
  │  │ paragraph   │ formula              │ figure       │ algorithm     │ │
  │  │ section_ttl │ formula_block        │ image        │ pseudo_code   │ │
  │  │ abstract    │ inline_formula       │ chart        │ code_block    │ │
  │  │ list_item   │ chemical_formula     │ flowchart    ├───────────────┤ │
  │  │ blockquote  │ equation_number      │ diagram      │ References    │ │
  │  │ footnote    ├──────────────────────┤ rel_graph    │ ──────────    │ │
  │  │ header      │ Tabular              ├──────────────┤ citation      │ │
  │  │ footer      │ ────────             │ Medical      │ reference_lst │ │
  │  │ page_number │ table                │ ──────       │ seal          │ │
  │  │ doc_title   │ table_caption        │ medical_scan │               │ │
  │  │ subsec_ttl  │ table_footnote       │ histology    │               │ │
  │  │             │                      │ clinical_pho │               │ │
  │  └─────────────┴──────────────────────┴──────────────┴───────────────┘ │
  └─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  STEP 3 — CHUNKING  (chunking/document_chunker.py)                      │
  │                                                                         │
  │  Two strategies based on entity type:                                   │
  │                                                                         │
  │  ATOMIC elements (never split):                                         │
  │    table, formula, formula_block, chemical_formula                      │
  │    figure, image, chart, medical_scan, histology, clinical_photo        │
  │    flowchart, diagram, relationship_graph                                │
  │    algorithm, pseudo_code, code_block                                   │
  │    → 1 Chunk per element, is_atomic=True                                │
  │                                                                         │
  │  TEXT elements (accumulated):                                           │
  │    paragraph, abstract, list_item, blockquote, footnote                 │
  │    → Accumulate up to max_chunk_tokens (512, tiktoken cl100k_base)      │
  │    → Overlap: 64 tokens carried into next chunk                         │
  │    → Title-forward: section_title prepended to next content chunk       │
  │    → section_path[] breadcrumb maintained throughout                    │
  │                                                                         │
  │  Semantic merge (semantic_merger.py):                                   │
  │    Adjacent text chunks with cosine similarity > 0.85 merged            │
  │                                                                         │
  │  Output: list[Chunk]                                                    │
  └─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  STEP 4 — GRAPH EXTRACTION  (parsing/graph_extractor.py)                │
  │                                                                         │
  │  Two extraction paths run in parallel per chunk:                        │
  │                                                                         │
  │  VISUAL (graph, flowchart, diagram, relationship_graph chunks):          │
  │    raw_image_b64 → LLM Vision API                                       │
  │    Prompt: extract nodes, edges, labels, relations as JSON               │
  │    → NetworkX DiGraph stored in chunk.graph_json                         │
  │    → GraphStore.add_graph(doc_id, graph_json)                           │
  │                                                                         │
  │  TEXT (all text chunks):                                                │
  │    text → spaCy en_core_web_trf NER                                     │
  │    Entity pairs with co-occurrence distance < 50 tokens → edges          │
  │    → NetworkX DiGraph merged into doc-level graph                       │
  │                                                                         │
  │  Graph schema:                                                           │
  │    node: { id, label, type, page, chunk_id, degree_centrality }         │
  │    edge: { source, target, relation, chunk_id, page, weight }           │
  └─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  STEP 5 — CROSS-REFERENCE LINKING  (parsing/cross_ref_linker.py)        │
  │                                                                         │
  │  Scans all text chunks for reference patterns:                          │
  │    "see Figure 3"  "as shown in Table 2"  "Equation 4 demonstrates"    │
  │    "Algorithm 1"   "refer to Section 3.2"                               │
  │                                                                         │
  │  Resolves reference → target chunk by label + occurrence index           │
  │  Stores bidirectional links:                                             │
  │    source_chunk.cross_refs.append(target_chunk_id)                      │
  │    target_chunk.cross_refs.append(source_chunk_id)                      │
  │                                                                         │
  │  Visible via: GET /v1/graph/{doc_id} → edges with type="cross_ref"      │
  └─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  STEP 6 — MULTIMODAL ENRICHMENT  (enrichment/)  [optional, enrich=true] │
  │                                                                         │
  │  Routed by chunk.modality:                                              │
  │                                                                         │
  │  ┌─────────────┬───────────────────────────────────────────────────┐   │
  │  │ Modality    │ Enrichment Action                                  │   │
  │  ├─────────────┼───────────────────────────────────────────────────┤   │
  │  │ image       │ LLM Vision: detailed caption + embedded context    │   │
  │  │ table       │ LLM Vision: Markdown table + column summary        │   │
  │  │ formula     │ pylatexenc validate + LLM verbal description       │   │
  │  │             │ + variable extraction                               │   │
  │  │ algorithm   │ LLM: step-by-step natural language explanation     │   │
  │  │ graph       │ Edge list + centrality + LLM graph summary         │   │
  │  │ code        │ LLM: purpose, inputs, outputs, complexity          │   │
  │  │ text        │ spaCy NER → concept_tags (no LLM call)            │   │
  │  └─────────────┴───────────────────────────────────────────────────┘   │
  │                                                                         │
  │  Output stored in: chunk.caption_json, chunk.concept_tags               │
  │  Embedding input:  chunk.enriched_text = chunk.text + caption_summary   │
  └─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  STEP 7 — EMBEDDING  (ingestion/embedder.py + ingestion/graph_embedder) │
  │                                                                         │
  │  Three embedding types computed per chunk:                              │
  │                                                                         │
  │  ① Dense (text_dense — 768-dim):                                        │
  │      Input:  chunk.enriched_text (text + caption, max 512 tokens)       │
  │      Model:  nomic-embed-text (Ollama / OpenAI-compatible)              │
  │      Cache:  Redis key = "emb:" + SHA-256(model:text), TTL 24hr         │
  │      Batch:  256 texts per API call                                     │
  │                                                                         │
  │  ② Sparse (bm25_sparse — 2^17 buckets):                                 │
  │      Input:  chunk.text (raw, no enrichment)                            │
  │      Method: MurmurHash3 feature-hashing, TF normalised to (0,1]        │
  │      Output: dict[bucket_index → tf_weight]                             │
  │                                                                         │
  │  ③ Graph (graph_dense — 128-dim):                                        │
  │      Input:  chunk.graph_json (only for graph-modality chunks)          │
  │      Method: node2vec walks → Word2Vec → average node embeddings        │
  │      Fallback: None vector (skipped in Qdrant upsert)                   │
  └─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  STEP 8 — QDRANT UPSERT  (ingestion/vector_store.py)                    │
  │                                                                         │
  │  Collection created on first ingest with:                               │
  │    text_dense:  VectorParams(size=768, distance=COSINE)                 │
  │    bm25_sparse: SparseVectorParams(index=SparseIndexParams())           │
  │    graph_dense: VectorParams(size=128, distance=COSINE)                 │
  │                                                                         │
  │  PointStruct per chunk:                                                 │
  │    id:      chunk.chunk_id  (UUID4)                                     │
  │    vector:  { text_dense, bm25_sparse, graph_dense? }                   │
  │    payload: chunk.to_dict() — all fields except raw_image_b64            │
  │                                                                         │
  │  Batched upsert: INGEST_BATCH_SIZE=64 points per call                   │
  │  Retried up to 3× with exponential backoff (tenacity)                   │
  └─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
  OUTPUT
  ──────
  { doc_id, chunk_count, graph_node_count, collection, cached: false }
```

---

## 4. Retrieval & Generation Pipeline

> End-to-end query flow from user input to streamed response.

```
  INPUT
  ─────
  POST /v1/search   { query, top_k, top_n, collection, modality_filter }
  POST /v1/generate { query, top_k, top_n, streaming, max_tokens, ... }

                                    │
                                    ▼
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  STAGE 1 — INPUT GUARD  (safety/input_guard.py)                         │
  │                                                                         │
  │  Step A — PII Detection (presidio-analyzer)                             │
  │    Detects: PERSON, EMAIL, PHONE, IP, CREDIT_CARD, IBAN, LOCATION      │
  │    SAFETY_BLOCK_ON_PII=false → redact entities → sanitised_query        │
  │    SAFETY_BLOCK_ON_PII=true  → HTTP 400                                 │
  │                                                                         │
  │  Step B — Prompt Injection Detection                                    │
  │    13 regex patterns: "ignore previous instructions", "you are now",   │
  │    "act as", "jailbreak", "do not follow", etc.                         │
  │    + LLM binary classifier: override attempt? yes/no                   │
  │    Detected → HTTP 400 { error: "injection_detected" }                 │
  │                                                                         │
  │  Step C — Content Classification                                        │
  │    LLM: classify query → benign | sensitive | off_topic | harmful       │
  │    harmful → HTTP 400                                                   │
  │    off_topic → flag in response, continue                               │
  │                                                                         │
  │  Output: SafetyResult { sanitised_query, pii_redacted, content_class }  │
  └─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  STAGE 2 — SEMANTIC ROUTER  (retrieval/semantic_router.py)              │
  │                                                                         │
  │  LLM classifies sanitised_query into one of 7 intents:                 │
  │                                                                         │
  │  ┌──────────────┬────────────────────────────────────────────────────┐  │
  │  │ Intent       │ Retrieval Modification                              │  │
  │  ├──────────────┼────────────────────────────────────────────────────┤  │
  │  │ factual      │ Default weights, boost BM25 sparse                 │  │
  │  │ analytical   │ top_k × 2, enable 2-hop graph traversal            │  │
  │  │ visual       │ Filter modality: image, chart, diagram              │  │
  │  │ mathematical │ Filter modality: formula, formula_block             │  │
  │  │ code         │ Filter modality: algorithm, code_block              │  │
  │  │ relational   │ Enable graph traversal, top_k × 1.5                │  │
  │  │ general      │ Default hybrid search, no modality filter           │  │
  │  └──────────────┴────────────────────────────────────────────────────┘  │
  └─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  STAGE 3 — HYBRID SEARCH  (retrieval/hybrid_searcher.py)                │
  │                                                                         │
  │  ① Embed query                                                          │
  │       Dense:  LLM embeddings → 768-dim float vector                    │
  │       Sparse: MurmurHash3 BM25 → dict[int, float]                      │
  │                                                                         │
  │  ② Qdrant Prefetch (parallel sub-queries):                              │
  │       Prefetch A: text_dense  cosine → limit=top_k×3                   │
  │       Prefetch B: bm25_sparse dot    → limit=top_k×3                   │
  │                                                                         │
  │  ③ RRF Fusion:  FusionQuery(fusion=Fusion.RRF)                          │
  │       Combines A + B results via Reciprocal Rank Fusion                 │
  │       → top_k ScoredChunk list                                          │
  │                                                                         │
  │  ④ Graph traversal (relational / analytical intents only):              │
  │       Seed nodes from top-3 RRF results                                 │
  │       2-hop BFS through NetworkX DiGraph                               │
  │       Graph-dense Qdrant query for discovered node IDs                  │
  │       → additional ScoredChunks appended with source="graph"            │
  └─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  STAGE 4 — RERANKING  (retrieval/reranker.py)                           │
  │                                                                         │
  │  Cross-encoder reranker (configurable backend):                         │
  │    Default: Cohere Rerank 3.5  (RERANKER_BACKEND=cohere)                │
  │    Alt:     Jina Reranker M0   (RERANKER_BACKEND=jina)                  │
  │    Alt:     OpenAI GPT-4o-mini (RERANKER_BACKEND=openai)                │
  │                                                                         │
  │  Input:  query + top_k ScoredChunks                                     │
  │  Output: top_n ScoredChunks reordered by cross-encoder relevance score  │
  │                                                                         │
  │  Forbidden: Qwen, BGE, Ollama, LLM APIs                                │
  │  (bi-encoders and generative LLMs cannot produce calibrated pair scores) │
  └─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  STAGE 5 — GROUNDEDNESS SCORING  (retrieval/groundedness.py)            │
  │                                                                         │
  │  Weighted cosine similarity between:                                    │
  │    query_embedding  ←→  each reranked chunk's dense embedding           │
  │  Weighted by rerank score (higher-ranked chunks contribute more)         │
  │                                                                         │
  │  score = Σ (rerank_weight_i × cosine(query_emb, chunk_emb_i))          │
  │          ──────────────────────────────────────────────────────         │
  │                     Σ rerank_weight_i                                   │
  │                                                                         │
  │  score ≥ 0.45 → proceed to generation with document context             │
  │  score < 0.45 → trigger Tavily web fallback                             │
  └─────────────────────────────────────────────────────────────────────────┘
                          │                   │
            score ≥ 0.45  │    score < 0.45   │
                          │                   ▼
                          │  ┌────────────────────────────────────────────┐
                          │  │  TAVILY WEB FALLBACK  (retrieval/web_...)  │
                          │  │                                            │
                          │  │  Tavily Search API (async)                 │
                          │  │  → up to TAVILY_MAX_RESULTS=5 results      │
                          │  │  → converted to ScoredChunk objects        │
                          │  │  → retrieval_source = "web"                │
                          │  │  → merged with document chunks             │
                          │  └────────────────────────────────────────────┘
                          │                   │
                          └───────────────────┘
                                    │
             ┌──────────────────────┴──────────────────────┐
             │ /v1/search returns here                      │ /v1/generate continues
             ▼                                              ▼
  SearchResponse                               ┌───────────────────────────────────┐
  { chunks, groundedness_score,                │  STAGE 6 — CONTEXT BUILDER        │
    fallback_used, web_sources,                │  (generation/context_builder.py)  │
    safety, latency_ms }                       │                                   │
                                               │  Assembles multimodal message     │
                                               │  list for LLM:                    │
                                               │    text    → inline Markdown      │
                                               │    table   → HTML table           │
                                               │    formula → LaTeX + verbal       │
                                               │    image   → base64 image part    │
                                               │    graph   → edge list summary    │
                                               │    code    → fenced code block    │
                                               │    web     → cited snippet        │
                                               └──────────────────┬────────────────┘
                                                                  │
                                                                  ▼
                                               ┌───────────────────────────────────┐
                                               │  STAGE 7 — GENERATION             │
                                               │  (generation/generator.py)        │
                                               │                                   │
                                               │  Jinja2 system prompt:            │
                                               │    • Role + citation rules        │
                                               │    • [Source N] format enforced   │
                                               │    • [Web Source N] for web       │
                                               │    • Grounding instruction        │
                                               │                                   │
                                               │  LLM API call (streaming):        │
                                               │    model: configurable            │
                                               │    max_tokens: 64–8192            │
                                               │    temperature: 0.0–2.0           │
                                               │                                   │
                                               │  SSE events per token delta:      │
                                               │    data: {"delta":"..","done":f}  │
                                               │  Final SSE event:                 │
                                               │    data: {"done":true,            │
                                               │      "sources":[...],             │
                                               │      "groundedness_score":0.82,   │
                                               │      "faithfulness_score":0.91}   │
                                               └──────────────────┬────────────────┘
                                                                  │
                                                                  ▼
                                               ┌───────────────────────────────────┐
                                               │  STAGE 8 — OUTPUT GUARD           │
                                               │  (safety/output_guard.py)         │
                                               │                                   │
                                               │  NLI Faithfulness:                │
                                               │    cross-encoder/nli-deberta-v3   │
                                               │    score(context, answer)         │
                                               │    < 0.5 → append disclaimer      │
                                               │                                   │
                                               │  Toxicity (Detoxify):             │
                                               │    6 dimensions scored            │
                                               │    any > 0.7 → replace with       │
                                               │    safe refusal message           │
                                               └──────────────────┬────────────────┘
                                                                  │
                                                                  ▼
                                                           GenerateResponse
                                                           or SSE stream
```

---

## 5. Three-Vector Hybrid Search Architecture

> How dense, sparse, and graph vectors combine for precision retrieval.

```
  QUERY: "How does the attention mechanism improve performance?"
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
                    ▼                               ▼
         ┌─────────────────────┐       ┌────────────────────────┐
         │  DENSE ENCODING     │       │  SPARSE ENCODING       │
         │                     │       │                        │
         │  nomic-embed-text   │       │  MurmurHash3 BM25      │
         │  → 768-dim float    │       │  feature hashing       │
         │    vector           │       │  → 2^17 = 131,072      │
         │                     │       │  buckets               │
         │  Cached in Redis    │       │  TF-normalised         │
         │  SHA-256(model:q)   │       │  weights (0,1]         │
         └──────────┬──────────┘       └────────────┬───────────┘
                    │                               │
                    ▼                               ▼
  ┌─────────────────────────────────────────────────────────────────────────┐
  │                    QDRANT PREFETCH  (parallel)                           │
  │                                                                         │
  │  Prefetch A                          Prefetch B                         │
  │  ───────────                         ───────────                        │
  │  query=dense_vector                  query=SparseVector(               │
  │  using="text_dense"                    indices=[...],                  │
  │  limit=top_k×3                         values=[...]  )                 │
  │  filter=modality_filter?             using="bm25_sparse"               │
  │                                      limit=top_k×3                     │
  │                                      filter=modality_filter?           │
  └─────────────────────────────────────────────────────────────────────────┘
                    │                               │
                    └───────────────┬───────────────┘
                                    │
                                    ▼
  ┌─────────────────────────────────────────────────────────────────────────┐
  │                    RRF FUSION  (Reciprocal Rank Fusion)                  │
  │                                                                         │
  │  FusionQuery(fusion=Fusion.RRF)  — Qdrant built-in                      │
  │                                                                         │
  │  score(d) = Σ  ──────────1──────────                                    │
  │               lists  (k=60) + rank(d, list)                             │
  │                                                                         │
  │  k=60 smoothing constant prevents high-rank dominance                   │
  │  Documents appearing in both lists score significantly higher           │
  └─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │  relational / analytical?     │  other intents
                    ▼                               ▼
  ┌─────────────────────────┐            Skip graph traversal
  │  GRAPH TRAVERSAL        │            → top_k ScoredChunks
  │                         │
  │  Seed: top-3 RRF chunks │
  │  NetworkX BFS (2 hops)  │
  │  → discovered node IDs  │
  │                         │
  │  Qdrant query:          │
  │  using="graph_dense"    │
  │  → ScoredChunks with    │
  │    source="graph"       │
  └────────────┬────────────┘
               │
               └───────────────┐
                               ▼
               ┌───────────────────────────────────┐
               │  MERGED RESULT SET                 │
               │                                   │
               │  RRF results + graph results       │
               │  tagged by retrieval_source:       │
               │    "qdrant" | "graph" | "web"      │
               └───────────────────────────────────┘
                               │
                               ▼
               ┌───────────────────────────────────┐
               │  COHERE RERANK 3.5                 │
               │                                   │
               │  Cross-encoder: scores every      │
               │  (query, chunk) pair together      │
               │  Output: top_n ranked chunks       │
               │  with calibrated relevance scores  │
               └───────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────┐
  │  VECTOR SPACE OVERVIEW                                                  │
  │                                                                         │
  │  text_dense (768-dim)          bm25_sparse (2^17 buckets)              │
  │  ────────────────────          ──────────────────────────              │
  │  Semantic similarity           Exact keyword overlap                    │
  │  Captures meaning              Captures terminology                     │
  │  e.g. "car" ≈ "automobile"    e.g. "BM25" ≠ "sparse retrieval"        │
  │                                                                         │
  │  graph_dense (128-dim)                                                  │
  │  ─────────────────────                                                  │
  │  Graph structure similarity                                             │
  │  node2vec random walks encode neighbourhood                             │
  │  e.g. nodes with similar connectivity score similar                    │
  └─────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Knowledge Graph Architecture

> How entity relationships are extracted, stored, and queried.

```
  EXTRACTION (during ingestion)
  ──────────────────────────────

  ┌───────────────────────────────────────────────────────────────────────┐
  │  SOURCE 1: Visual elements (graph_extractor.py)                       │
  │                                                                       │
  │  Chunk.modality ∈ {graph, flowchart, diagram, relationship_graph}     │
  │                │                                                      │
  │                ▼                                                      │
  │  raw_image_b64 ──► LLM Vision API                                     │
  │                    Prompt:                                            │
  │                    "Extract nodes, edges, and their labels from this  │
  │                     diagram. Return as JSON:                          │
  │                     { nodes: [{id, label, type}],                    │
  │                       edges: [{source, target, relation}] }"          │
  │                │                                                      │
  │                ▼                                                      │
  │  JSON response ──► NetworkX DiGraph                                   │
  │    G.add_node(id, label=..., type=..., chunk_id=..., page=...)        │
  │    G.add_edge(src, tgt, relation=..., weight=1.0)                     │
  └───────────────────────────────────────────────────────────────────────┘

  ┌───────────────────────────────────────────────────────────────────────┐
  │  SOURCE 2: Text elements (graph_extractor.py via spaCy)               │
  │                                                                       │
  │  Chunk.modality = text                                                │
  │                │                                                      │
  │                ▼                                                      │
  │  spaCy en_core_web_trf NER pipeline                                   │
  │    Entities: PERSON, ORG, GPE, PRODUCT, EVENT, WORK_OF_ART, LAW      │
  │                │                                                      │
  │                ▼                                                      │
  │  Co-occurrence within 50-token window → edges                         │
  │    G.add_node(entity.text, type=entity.label_)                       │
  │    G.add_edge(ent_a, ent_b, relation="co-occurs", weight=count)       │
  └───────────────────────────────────────────────────────────────────────┘

  ┌───────────────────────────────────────────────────────────────────────┐
  │  SOURCE 3: Cross-references (cross_ref_linker.py)                     │
  │                                                                       │
  │  Regex scan across all chunks:                                        │
  │    r"(?:see|refer to|shown in|as in)\s+(Figure|Table|Eq|Algo)\.?\s+\d+"│
  │                │                                                      │
  │                ▼                                                      │
  │  Resolve reference → target chunk_id by type + index                  │
  │  Bidirectional edges added to both chunks:                             │
  │    chunk_a.cross_refs.append(chunk_b_id)                              │
  │    chunk_b.cross_refs.append(chunk_a_id)                              │
  └───────────────────────────────────────────────────────────────────────┘

  STORAGE
  ────────

  ┌───────────────────────────────────────────────────────────────────────┐
  │  GraphStore (ingestion/graph_store.py)                                │
  │                                                                       │
  │  In-memory dict:  { doc_id → NetworkX DiGraph }                       │
  │                                                                       │
  │  add_graph(doc_id, graph_json):                                        │
  │    Merges new nodes/edges into existing graph for doc_id              │
  │    nx.compose() with edge deduplication                               │
  │                                                                       │
  │  serialize(doc_id) → { nodes: [...], edges: [...] }                   │
  │    Exposed via: GET /v1/graph/{doc_id}                                 │
  │                                                                       │
  │  Optional Neo4j export:  NEO4J_URI set → bolt driver sync             │
  └───────────────────────────────────────────────────────────────────────┘

  GRAPH EMBEDDING
  ────────────────

  ┌───────────────────────────────────────────────────────────────────────┐
  │  node2vec (ingestion/graph_embedder.py)                               │
  │                                                                       │
  │  Per graph-modality chunk:                                             │
  │    1. Deserialize graph_json → NetworkX DiGraph                       │
  │    2. node2vec(G, dimensions=128, walk_length=30, num_walks=200)      │
  │    3. Train Word2Vec on random walks                                   │
  │    4. Average all node embeddings → 128-dim graph_dense vector        │
  │    5. Store in Qdrant "graph_dense" named vector                      │
  └───────────────────────────────────────────────────────────────────────┘

  QUERY-TIME TRAVERSAL
  ─────────────────────

  ┌───────────────────────────────────────────────────────────────────────┐
  │  2-hop BFS (HybridSearcher, intent: relational / analytical)          │
  │                                                                       │
  │  seed_chunks = top-3 RRF results                                      │
  │                                                                       │
  │  for chunk in seed_chunks:                                            │
  │      for node in chunk.graph_json["nodes"]:                           │
  │          neighbors_1hop = G.neighbors(node["id"])                     │
  │          for n1 in neighbors_1hop:                                    │
  │              neighbors_2hop = G.neighbors(n1)                         │
  │              discovered_chunk_ids.update(...)                         │
  │                                                                       │
  │  Qdrant point lookup by chunk_id → ScoredChunk(source="graph")        │
  │  Merged into main result set before reranking                          │
  └───────────────────────────────────────────────────────────────────────┘
```

---

## 7. Safety Architecture

> Defense-in-depth: every request filtered before retrieval and after generation.

```
  ┌─────────────────────────────────────────────────────────────────────────┐
  │                          INPUT GUARD                                    │
  │                    (safety/input_guard.py)                              │
  │                                                                         │
  │  ┌──────────────────────────────────────────────────────────────────┐  │
  │  │  STAGE A — PII Detection                                         │  │
  │  │                                                                  │  │
  │  │  Engine: Microsoft Presidio (presidio-analyzer)                  │  │
  │  │                                                                  │  │
  │  │  Entity types scanned:                                           │  │
  │  │    PERSON · EMAIL_ADDRESS · PHONE_NUMBER · IP_ADDRESS            │  │
  │  │    CREDIT_CARD · IBAN_CODE · LOCATION · DATE_TIME · URL · NRP   │  │
  │  │                                                                  │  │
  │  │  SAFETY_BLOCK_ON_PII=false (default):                            │  │
  │  │    Replace detected spans with <ENTITY_TYPE> placeholders        │  │
  │  │    SafetyResult.pii_redacted = True                              │  │
  │  │    SafetyResult.redacted_entities = ["EMAIL_ADDRESS", ...]       │  │
  │  │    Continue with sanitised_query                                 │  │
  │  │                                                                  │  │
  │  │  SAFETY_BLOCK_ON_PII=true:                                       │  │
  │  │    HTTP 400 { "error": "pii_detected" }                          │  │
  │  └──────────────────────────────────────────────────────────────────┘  │
  │                                │                                        │
  │                                ▼                                        │
  │  ┌──────────────────────────────────────────────────────────────────┐  │
  │  │  STAGE B — Prompt Injection Detection                            │  │
  │  │                                                                  │  │
  │  │  Layer 1 — Rule-based (13 patterns):                             │  │
  │  │    "ignore (all) previous instructions"                          │  │
  │  │    "disregard prior instructions"                                │  │
  │  │    "you are now [persona]"                                       │  │
  │  │    "act as [if you are] an?"                                     │  │
  │  │    "do not / don't follow"                                       │  │
  │  │    "jailbreak"                                                   │  │
  │  │    + 7 more variants                                             │  │
  │  │                                                                  │  │
  │  │  Layer 2 — LLM classifier:                                       │  │
  │  │    "Does this query attempt to override system instructions?"    │  │
  │  │    Answer: yes → injection_detected=True                         │  │
  │  │                                                                  │  │
  │  │  Either layer triggered → HTTP 400                               │  │
  │  └──────────────────────────────────────────────────────────────────┘  │
  │                                │                                        │
  │                                ▼                                        │
  │  ┌──────────────────────────────────────────────────────────────────┐  │
  │  │  STAGE C — Content Classification                                │  │
  │  │                                                                  │  │
  │  │  LLM classifies sanitised_query:                                 │  │
  │  │    benign    → proceed normally                                  │  │
  │  │    sensitive → proceed, flag in response                         │  │
  │  │    off_topic → proceed, flag in response                         │  │
  │  │    harmful   → HTTP 400 { "error": "harmful_content" }          │  │
  │  └──────────────────────────────────────────────────────────────────┘  │
  │                                │                                        │
  │                                ▼                                        │
  │                     SafetyResult (passed to retrieval)                  │
  └─────────────────────────────────────────────────────────────────────────┘

                [ Retrieval + Generation Pipeline ]

  ┌─────────────────────────────────────────────────────────────────────────┐
  │                         OUTPUT GUARD                                    │
  │                    (safety/output_guard.py)                             │
  │                                                                         │
  │  ┌──────────────────────────────────────────────────────────────────┐  │
  │  │  FAITHFULNESS — NLI Cross-Encoder                                │  │
  │  │                                                                  │  │
  │  │  Model: cross-encoder/nli-deberta-v3-base                        │  │
  │  │                                                                  │  │
  │  │  Input:                                                          │  │
  │  │    premise:    context_text (first 5 reranked chunks joined)     │  │
  │  │    hypothesis: generated_answer                                  │  │
  │  │                                                                  │  │
  │  │  Scores:  entailment | neutral | contradiction                   │  │
  │  │  faithfulness_score = softmax(entailment_logit)                  │  │
  │  │                                                                  │  │
  │  │  score ≥ 0.5 → pass                                              │  │
  │  │  score < 0.5 → append disclaimer to answer:                      │  │
  │  │    "⚠️ Note: parts of this answer may not be fully supported     │  │
  │  │     by the retrieved documents."                                 │  │
  │  └──────────────────────────────────────────────────────────────────┘  │
  │                                │                                        │
  │                                ▼                                        │
  │  ┌──────────────────────────────────────────────────────────────────┐  │
  │  │  TOXICITY — Detoxify                                             │  │
  │  │                                                                  │  │
  │  │  6 dimensions scored independently (0.0 – 1.0):                 │  │
  │  │    toxic · severe_toxic · obscene                                │  │
  │  │    threat · insult · identity_hate                               │  │
  │  │                                                                  │  │
  │  │  Any dimension > 0.7:                                            │  │
  │  │    answer replaced with safe refusal:                            │  │
  │  │    "I'm unable to provide this response as it may contain        │  │
  │  │     harmful content."                                            │  │
  │  │    OutputGuardResult.blocked = True                              │  │
  │  └──────────────────────────────────────────────────────────────────┘  │
  │                                │                                        │
  │                                ▼                                        │
  │                     OutputGuardResult → client                          │
  └─────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────┐
  │  RATE LIMITING  (safety/rate_limiter.py + api/middleware.py)            │
  │                                                                         │
  │  slowapi (Redis-backed) per remote IP:                                  │
  │    RATE_LIMIT_PER_MINUTE = 60 (default)                                 │
  │    Exceeded → HTTP 429 Too Many Requests                                │
  │    Header: X-RateLimit-Limit, X-RateLimit-Remaining                     │
  └─────────────────────────────────────────────────────────────────────────┘
```

---

## 8. AWS Deployment Topology

> Full infrastructure layout in AWS us-east-1.

```
  ┌──────────────────────────────────────────────────────────────────────────────┐
  │  AWS Account: 431445718054   │   Region: us-east-1                           │
  │                                                                              │
  │  ┌──────────────────────────────────────────────────────────────────────┐   │
  │  │  VPC: vpc-0345ce5c8d813f0a3  (default)                               │   │
  │  │                                                                      │   │
  │  │  ┌─────────────────────────────────────────────────────────────┐    │   │
  │  │  │  Public Subnets (6 AZs):                                     │    │   │
  │  │  │  subnet-04def... · subnet-002... · subnet-01a...            │    │   │
  │  │  │  subnet-031... · subnet-00e... · subnet-0ec...               │    │   │
  │  │  │                                                             │    │   │
  │  │  │  ┌──────────────────────────────────────────────────────┐   │    │   │
  │  │  │  │  Application Load Balancer                           │   │    │   │
  │  │  │  │  doc-intel-rag-alb-1457953429.us-east-1.elb.amazonaws│   │    │   │
  │  │  │  │                                                      │   │    │   │
  │  │  │  │  Security Group (doc-intel-rag-alb-sg):              │   │    │   │
  │  │  │  │    Inbound:  TCP 80  from 0.0.0.0/0                  │   │    │   │
  │  │  │  │    Inbound:  TCP 443 from 0.0.0.0/0                  │   │    │   │
  │  │  │  │    Outbound: all traffic                              │   │    │   │
  │  │  │  │                                                      │   │    │   │
  │  │  │  │  Listener: HTTP:80                                   │   │    │   │
  │  │  │  │    → Forward to Target Group doc-intel-rag-tg        │   │    │   │
  │  │  │  └──────────────────────┬───────────────────────────────┘   │    │   │
  │  │  │                         │                                   │    │   │
  │  │  │                         │  port 8000                        │    │   │
  │  │  │                         ▼                                   │    │   │
  │  │  │  ┌──────────────────────────────────────────────────────┐   │    │   │
  │  │  │  │  ECS Cluster: doc-intel-rag-cluster                  │   │    │   │
  │  │  │  │  Service:     doc-intel-rag-service                  │   │    │   │
  │  │  │  │  Launch type: FARGATE                                │   │    │   │
  │  │  │  │  Desired:     1 task  │  Running: 1 task             │   │    │   │
  │  │  │  │                                                      │   │    │   │
  │  │  │  │  ┌────────────────────────────────────────────────┐  │   │    │   │
  │  │  │  │  │  Fargate Task  (doc-intel-rag:3)               │  │   │    │   │
  │  │  │  │  │  CPU: 1024 vCPU  │  Memory: 2048 MB            │  │   │    │   │
  │  │  │  │  │                                                │  │   │    │   │
  │  │  │  │  │  Container: doc-intel-rag                      │  │   │    │   │
  │  │  │  │  │  Image: ECR/doc-intel-rag:cc8fff0              │  │   │    │   │
  │  │  │  │  │  Port: 8000                                    │  │   │    │   │
  │  │  │  │  │                                                │  │   │    │   │
  │  │  │  │  │  Env from Secrets Manager:                     │  │   │    │   │
  │  │  │  │  │    MESH_API_KEY    QDRANT_URL                   │  │   │    │   │
  │  │  │  │  │    QDRANT_API_KEY  COHERE_API_KEY               │  │   │    │   │
  │  │  │  │  │    TAVILY_API_KEY  REDIS_URL                    │  │   │    │   │
  │  │  │  │  │                                                │  │   │    │   │
  │  │  │  │  │  Log driver: awslogs                           │  │   │    │   │
  │  │  │  │  │    group: /ecs/doc-intel-rag                    │  │   │    │   │
  │  │  │  │  │    region: us-east-1                            │  │   │    │   │
  │  │  │  │  │                                                │  │   │    │   │
  │  │  │  │  │  Health check:                                 │  │   │    │   │
  │  │  │  │  │    CMD curl -f localhost:8000/health            │  │   │    │   │
  │  │  │  │  │    Interval: 30s  Timeout: 10s  Retries: 3     │  │   │    │   │
  │  │  │  │  └────────────────────────────────────────────────┘  │   │    │   │
  │  │  │  │                                                      │   │    │   │
  │  │  │  │  Task Execution Role: ecsTaskExecutionRole            │   │    │   │
  │  │  │  │    AmazonECSTaskExecutionRolePolicy                  │   │    │   │
  │  │  │  │    secretsmanager:GetSecretValue (doc-intel-rag/*)   │   │    │   │
  │  │  │  │                                                      │   │    │   │
  │  │  │  │  Task Role: ecsTaskRole                              │   │    │   │
  │  │  │  │    logs:CreateLogGroup/Stream/PutLogEvents           │   │    │   │
  │  │  │  └──────────────────────────────────────────────────────┘   │    │   │
  │  │  │                                                             │    │   │
  │  │  │  Security Group (doc-intel-rag-ecs-sg):                     │    │   │
  │  │  │    Inbound: TCP 8000 from ALB SG only                        │    │   │
  │  │  └─────────────────────────────────────────────────────────────┘    │   │
  │  │                                                                      │   │
  │  └──────────────────────────────────────────────────────────────────────┘   │
  │                                                                              │
  │  ┌────────────────────────────────────────────────────────────────────┐     │
  │  │  Supporting Services                                                │     │
  │  │                                                                    │     │
  │  │  ECR Repository: doc-intel-rag                                     │     │
  │  │    Images tagged by git commit SHA (cc8fff0, f78b3ee, ...)         │     │
  │  │    Also tagged: latest                                              │     │
  │  │                                                                    │     │
  │  │  Secrets Manager  (doc-intel-rag/*)                                 │     │
  │  │    doc-intel-rag/MESH_API_KEY    doc-intel-rag/QDRANT_URL           │     │
  │  │    doc-intel-rag/QDRANT_API_KEY  doc-intel-rag/REDIS_URL            │     │
  │  │    doc-intel-rag/COHERE_API_KEY  doc-intel-rag/TAVILY_API_KEY       │     │
  │  │                                                                    │     │
  │  │  CloudWatch Log Group: /ecs/doc-intel-rag                           │     │
  │  │    Retention: default (never expire)                                │     │
  │  │    Tail: aws logs tail /ecs/doc-intel-rag --follow                 │     │
  │  │                                                                    │     │
  │  │  IAM Roles:                                                         │     │
  │  │    ecsTaskExecutionRole   — ECR pull + Secrets Manager read         │     │
  │  │    ecsTaskRole            — CloudWatch Logs write                   │     │
  │  │    GitHubActionsDeployRole — OIDC federated, ECR + ECS deploy       │     │
  │  └────────────────────────────────────────────────────────────────────┘     │
  │                                                                              │
  └──────────────────────────────────────────────────────────────────────────────┘

  EXTERNAL SERVICES (outside AWS account)
  ─────────────────────────────────────────

  ┌──────────────────────┐   ┌──────────────────────┐   ┌──────────────────────┐
  │  Qdrant Cloud        │   │  Cohere API          │   │  Tavily Search API   │
  │  AWS us-west-2       │   │  api.cohere.com       │   │  api.tavily.com      │
  │                      │   │                      │   │                      │
  │  Cluster:            │   │  Rerank 3.5          │   │  /search endpoint    │
  │  a1972350-ccfd-...   │   │  POST /rerank        │   │  max_results=5       │
  │  .qdrant.io:6333     │   │                      │   │                      │
  │                      │   │  Auth: API key       │   │  Auth: API key       │
  │  Collection:         │   │  header              │   │  in body             │
  │  doc_intel           │   └──────────────────────┘   └──────────────────────┘
  │                      │
  │  Auth: API key       │
  └──────────────────────┘
```

---

## 9. CI/CD Pipeline

> Automated test → build → deploy on push to main.

```
  Developer                GitHub                  AWS
  ─────────                ──────                  ───
      │                       │                     │
      │  git push main        │                     │
      ├──────────────────────►│                     │
      │                       │                     │
      │            ┌──────────▼──────────┐          │
      │            │  Trigger: push/main  │          │
      │            │  .github/workflows/  │          │
      │            │  deploy-ecs.yml      │          │
      │            └──────────┬──────────┘          │
      │                       │                     │
      │            ┌──────────▼──────────┐          │
      │            │  JOB 1: test         │          │
      │            │                     │          │
      │            │  uv sync            │          │
      │            │  pytest tests/unit/ │          │
      │            │    -x -q            │          │
      │            │                     │          │
      │            │  (32 unit tests)    │          │
      │            └──────────┬──────────┘          │
      │                       │ pass                │
      │            ┌──────────▼──────────┐          │
      │            │  JOB 2: deploy       │          │
      │            │  needs: [test]       │          │
      │            │                     │          │
      │            │  OIDC assume role:  ├─────────►│
      │            │  GitHubActions      │  STS     │
      │            │  DeployRole         │◄─────────┤
      │            │                     │  creds   │
      │            │  ECR login          ├─────────►│
      │            │                     │          │
      │            │  docker build       │          │
      │            │  docker push        ├─────────►│ ECR
      │            │  (git SHA tag)      │          │
      │            │                     │          │
      │            │  render new task    │          │
      │            │  definition JSON    │          │
      │            │                     │          │
      │            │  ecs register-task  ├─────────►│ ECS
      │            │                     │          │
      │            │  ecs update-service ├─────────►│ ECS (rolling deploy)
      │            │                     │          │
      │            │  ecs wait services- │          │
      │            │  stable             │◄─────────┤ health checks pass
      │            └──────────┬──────────┘          │
      │                       │                     │
      │            deploy complete                  │
      │◄──────────────────────┤                     │

  Security:
    No static AWS credentials in GitHub.
    OIDC trust policy scoped to: repo:jndumu/Enhanced-Multimodel-Rag-Hackerton:*
    GitHubActionsDeployRole permissions: ECR power user + ECS:* + iam:PassRole
```

---

## 10. Observability Stack

> Logging, metrics, and tracing across all layers.

```
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  LOGGING  (logging_config.py + loguru)                                  │
  │                                                                         │
  │  Loguru JSON sink (LOG_JSON=true in production):                        │
  │  {                                                                      │
  │    "time": "2026-05-06T13:45:20.874+00:00",                            │
  │    "level": "INFO",                                                     │
  │    "name": "doc_intel_rag.api.middleware",                              │
  │    "message": "Request handled"                                         │
  │  }                                                                      │
  │                                                                         │
  │  Stdlib interception: uvicorn · httpx · fastapi → Loguru                │
  │                                                                         │
  │  Secret masking filter: api_key · password · token → "***"              │
  │                                                                         │
  │  Sink: stderr → Docker → awslogs driver → CloudWatch Logs               │
  │    Log group: /ecs/doc-intel-rag                                         │
  │    Query: aws logs tail /ecs/doc-intel-rag --follow --region us-east-1  │
  └─────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────┐
  │  METRICS  (prometheus-fastapi-instrumentator)                            │
  │                                                                         │
  │  Auto-instrumented HTTP metrics:                                        │
  │    http_requests_total{method, handler, status}                         │
  │    http_request_duration_seconds{handler}                               │
  │    http_request_size_bytes{handler}                                     │
  │    http_response_size_bytes{handler}                                    │
  │                                                                         │
  │  Endpoint: GET /metrics  (Prometheus scrape target)                     │
  │                                                                         │
  │  Custom business metrics (to be scraped by Prometheus):                 │
  │    doc_intel_chunks_ingested_total{doc_id, modality}                    │
  │    doc_intel_groundedness_score  (histogram)                            │
  │    doc_intel_fallback_triggered_total                                   │
  │    doc_intel_safety_violation_total{violation_type}                     │
  │    doc_intel_rerank_latency_seconds{backend}                            │
  └─────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────┐
  │  DISTRIBUTED TRACING  (OpenTelemetry)                                   │
  │                                                                         │
  │  When OTEL_ENDPOINT configured → OTLP gRPC export to Jaeger:            │
  │                                                                         │
  │  Trace span tree per request:                                           │
  │                                                                         │
  │  ● POST /v1/generate  [total latency]                                   │
  │    ├── input_guard.check                [PII + injection + classify]    │
  │    ├── semantic_router.classify         [LLM intent call]               │
  │    ├── hybrid_searcher.search                                           │
  │    │   ├── embedder.embed_query         [dense + sparse]                │
  │    │   ├── qdrant.query_points          [prefetch + RRF]                │
  │    │   └── graph_store.traverse         [2-hop BFS, if applicable]      │
  │    ├── reranker.rerank                  [Cohere API call]               │
  │    ├── groundedness.score                                               │
  │    ├── tavily.search                    [if fallback triggered]         │
  │    ├── context_builder.build                                            │
  │    ├── generator.stream_generate        [LLM API + SSE]                 │
  │    └── output_guard.check              [NLI + Detoxify]                 │
  │                                                                         │
  │  View at: http://localhost:16686  (Jaeger UI, local Docker)             │
  └─────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────┐
  │  REQUEST TRACKING  (api/middleware.py)                                  │
  │                                                                         │
  │  Every request:                                                         │
  │    X-Request-ID header injected (UUID4) if not provided                 │
  │    Logged with method, path, status, latency_ms                         │
  │    Propagated through SSE events to client                              │
  │                                                                         │
  │  Every response body includes:                                          │
  │    "request_id": "uuid4-..."                                            │
  │    "latency_ms": 734.2                                                  │
  └─────────────────────────────────────────────────────────────────────────┘
```

---

## 11. Data Models & Schemas

### Chunk (core domain model)

| Field | Type | Description |
|---|---|---|
| `chunk_id` | `UUID4` | Qdrant point ID |
| `doc_id` | `SHA-256 hex` | Source file hash — idempotency key |
| `source_file` | `str` | Absolute path or URL |
| `page` | `int` | 1-based page number |
| `element_types` | `list[EntityLabel]` | One or more of 35 entity labels |
| `modality` | `ChunkModality` | text / image / table / formula / algorithm / graph / code |
| `text` | `str` | Markdown or verbal representation |
| `latex` | `str?` | Raw LaTeX (formula chunks) |
| `html` | `str?` | HTML table markup (table chunks) |
| `raw_image_b64` | `str?` | Base64 PNG crop — not stored in Qdrant |
| `bbox` | `BBox?` | x0, y0, x1, y1, page |
| `is_atomic` | `bool` | True = never split or merged |
| `token_count` | `int` | tiktoken cl100k_base count |
| `section_path` | `list[str]` | Breadcrumb from document root |
| `cross_refs` | `list[str]` | Linked chunk IDs (bidirectional) |
| `graph_json` | `dict?` | Serialised NetworkX DiGraph |
| `concept_tags` | `list[str]` | spaCy NER entities |
| `caption_json` | `dict?` | Enrichment payload from LLM captioner |
| `enriched_text` | `str` | text + caption summary — used for dense embedding |
| `confidence` | `float` | Layout detection confidence (0–1) |

### Qdrant Collection Schema

| Named Vector | Dimensions | Distance | Index | Purpose |
|---|---|---|---|---|
| `text_dense` | 768 | Cosine | HNSW | Semantic similarity |
| `bm25_sparse` | 2^17 buckets | — | Sparse | Keyword overlap |
| `graph_dense` | 128 | Cosine | HNSW | Graph structure similarity |

### API Request / Response Schemas

| Schema | Key Fields |
|---|---|
| `IngestRequest` | source, collection, enrich, force |
| `IngestResponse` | doc_id, chunk_count, graph_node_count, collection, cached |
| `SearchRequest` | query, collection, top_k, top_n, modality_filter, filters |
| `SearchResponse` | chunks, groundedness_score, fallback_used, web_sources, safety, latency_ms |
| `GenerateRequest` | query, top_k, top_n, streaming, max_tokens, temperature, fallback_enabled |
| `GenerateResponse` | answer, sources, groundedness_score, faithfulness_score, fallback_used, safety |
| `SafetyResult` | pii_redacted, redacted_entities, injection_detected, content_class |
| `ChunkResult` | chunk_id, doc_id, source_file, page, modality, text, score, section_path |
| `HealthResponse` | status, components{qdrant, redis, mesh_api}, version |

---

## 12. Technology Stack Summary

| Layer | Technology | Version | Role |
|---|---|---|---|
| Language | Python | 3.12 | Strict type hints throughout |
| API framework | FastAPI + Uvicorn | 0.115+ | Async HTTP + SSE streaming |
| Data validation | Pydantic v2 | 2.x | Request/response schemas |
| Settings | pydantic-settings | 2.x | Env-based config with validation |
| LLM + Embeddings | OpenAI-compatible API | — | Generation, embeddings, vision, routing |
| Document parsing | GLM-OCR + PP-DocLayout-V3 | — | 35-class layout detection |
| Chunking tokens | tiktoken (cl100k_base) | — | Token counting and truncation |
| NER | spaCy en_core_web_trf | 3.x | Named entity recognition |
| Reranker | Cohere Rerank 3.5 | rerank-v3.5 | Cross-encoder reranking |
| Vector DB | Qdrant Cloud | 1.17 | 3-vector hybrid search, RRF |
| Knowledge graph | NetworkX DiGraph | 3.x | In-memory per-document graph |
| Graph embedding | node2vec | — | 128-dim graph vector |
| Graph DB export | Neo4j | 5.x | Optional persistent graph store |
| Cache | Redis 7 | asyncio client | Embeddings (24hr) + queries (1hr) |
| Web fallback | Tavily Search API | — | Live web retrieval |
| PII detection | Microsoft Presidio | 2.x | 10 entity types |
| NLI faithfulness | DeBERTa-v3-base | cross-encoder | Entailment scoring |
| Toxicity | Detoxify | — | 6-dimension toxicity scoring |
| Observability | Loguru + OTel + Prometheus | — | Logs + traces + metrics |
| Container | Docker multi-stage | — | CPU + CUDA GPU variants |
| Orchestration | AWS ECS Fargate | — | Serverless containers |
| Load balancer | AWS ALB | — | Stable DNS, health checks |
| Image registry | AWS ECR | — | Docker image storage |
| Secrets | AWS Secrets Manager | — | API keys, never in env vars |
| Logs sink | AWS CloudWatch | — | /ecs/doc-intel-rag log group |
| CI/CD | GitHub Actions | — | OIDC → ECR → ECS on push |
| IAM | AWS IAM | — | Least-privilege task roles |
| Package manager | uv | 0.11+ | Fast Python dependency resolution |
| Test framework | pytest + respx | — | 32 unit + integration tests |
