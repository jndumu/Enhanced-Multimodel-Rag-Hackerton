"""Document ingestion endpoints."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status

from doc_intel_rag.api.dependencies import (
    get_embedder, get_graph_store, get_query_cache, get_vector_store, verify_api_key,
)
from doc_intel_rag.api.schemas import IngestRequest, IngestResponse
from doc_intel_rag.config import Settings, get_settings

router = APIRouter(tags=["ingest"])


@router.post("/ingest", response_model=IngestResponse)
async def ingest_url_or_path(
    request: IngestRequest,
    api_key: str = Depends(verify_api_key),
    vector_store: object = Depends(get_vector_store),
    embedder: object = Depends(get_embedder),
    graph_store: object = Depends(get_graph_store),
    query_cache: object = Depends(get_query_cache),
) -> IngestResponse:
    return await _run_ingest(
        source=request.source,
        collection=request.collection,
        enrich=request.enrich,
        force=request.force,
        vector_store=vector_store,
        embedder=embedder,
        graph_store=graph_store,
        query_cache=query_cache,
    )


@router.post("/ingest/file", response_model=IngestResponse)
async def ingest_file(
    file: UploadFile,
    collection: str = "doc_intel",
    enrich: bool = True,
    force: bool = False,
    api_key: str = Depends(verify_api_key),
    vector_store: object = Depends(get_vector_store),
    embedder: object = Depends(get_embedder),
    graph_store: object = Depends(get_graph_store),
    query_cache: object = Depends(get_query_cache),
) -> IngestResponse:
    contents = await file.read()
    suffix = Path(file.filename or "doc").suffix or ".pdf"

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(contents)
        tmp_path = tmp.name

    return await _run_ingest(
        source=tmp_path,
        collection=collection,
        enrich=enrich,
        force=force,
        vector_store=vector_store,
        embedder=embedder,
        graph_store=graph_store,
        query_cache=query_cache,
    )


@router.delete("/collections/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(
    name: str,
    api_key: str = Depends(verify_api_key),
    vector_store: object = Depends(get_vector_store),
    query_cache: object = Depends(get_query_cache),
) -> None:
    from doc_intel_rag.ingestion.vector_store import QdrantDocumentStore
    assert isinstance(vector_store, QdrantDocumentStore)
    await vector_store.delete_collection(name)
    if query_cache is not None:
        from doc_intel_rag.ingestion.cache import QueryCache
        assert isinstance(query_cache, QueryCache)
        await query_cache.flush_all()


async def _run_ingest(
    source: str,
    collection: str,
    enrich: bool,
    force: bool,
    vector_store: object,
    embedder: object,
    graph_store: object,
    query_cache: object,
) -> IngestResponse:
    from doc_intel_rag.chunking.document_chunker import document_aware_chunking
    from doc_intel_rag.enrichment.captioner import enrich_chunks
    from doc_intel_rag.enrichment.concept_extractor import enrich_chunks_concepts
    from doc_intel_rag.enrichment.graph_enricher import enrich_graph
    from doc_intel_rag.ingestion.graph_embedder import embed_graph
    from doc_intel_rag.ingestion.graph_store import GraphStore
    from doc_intel_rag.ingestion.vector_store import QdrantDocumentStore
    from doc_intel_rag.parsing.cross_ref_linker import link_cross_references
    from doc_intel_rag.parsing.graph_extractor import GraphExtractor
    from doc_intel_rag.parsing.pipeline import DocumentParser
    from doc_intel_rag.ingestion.embedder import DocumentEmbedder
    from doc_intel_rag.ingestion.cache import QueryCache

    assert isinstance(vector_store, QdrantDocumentStore)
    assert isinstance(embedder, DocumentEmbedder)

    settings = get_settings()
    parser = DocumentParser(settings)
    parse_result = await parser.parse(source)

    if not force and await vector_store.doc_exists(parse_result.doc_id, collection):
        return IngestResponse(
            doc_id=parse_result.doc_id,
            chunk_count=0,
            graph_node_count=0,
            collection=collection,
            cached=True,
        )

    chunks = document_aware_chunking(parse_result, settings)

    extractor = GraphExtractor(settings)
    for chunk in chunks:
        if chunk.modality.value in ("graph",) and chunk.raw_image_b64:
            g = await extractor.extract_from_image(chunk.raw_image_b64, chunk.element_types[0])
            chunk.graph_json = extractor.serialize(g)
            if isinstance(graph_store, GraphStore) and chunk.doc_id:
                graph_store.add_graph(chunk.doc_id, chunk.graph_json)
        elif chunk.modality.value == "text":
            g = await extractor.extract_from_text(chunk.text)
            if g.number_of_nodes() > 0:
                if isinstance(graph_store, GraphStore):
                    graph_store.add_graph(chunk.doc_id, extractor.serialize(g))

    chunks = link_cross_references(chunks)

    if enrich:
        chunks = await enrich_chunks(chunks, settings)
        chunks = await enrich_chunks_concepts(chunks)
        for chunk in chunks:
            if chunk.graph_json:
                await enrich_graph(chunk, settings)

    texts_to_embed = [c.enriched_text or c.text for c in chunks]
    dense_vectors = await embedder.embed_texts(texts_to_embed)
    sparse_vectors = [embedder.sparse_encode(t) for t in texts_to_embed]

    graph_vectors: list[list[float] | None] = []
    for chunk in chunks:
        if chunk.graph_json:
            gv = await embed_graph(chunk.graph_json)
            graph_vectors.append(gv)
        else:
            graph_vectors.append(None)

    await vector_store.upsert_chunks(
        chunks=chunks,
        dense_vectors=dense_vectors,
        sparse_vectors=sparse_vectors,
        graph_vectors=graph_vectors,
        collection=collection,
    )

    if query_cache is not None and isinstance(query_cache, QueryCache):
        await query_cache.invalidate_doc(parse_result.doc_id)

    graph_node_count = sum(
        len((c.graph_json or {}).get("nodes", [])) for c in chunks if c.graph_json
    )

    return IngestResponse(
        doc_id=parse_result.doc_id,
        chunk_count=len(chunks),
        graph_node_count=graph_node_count,
        collection=collection,
        cached=False,
    )
