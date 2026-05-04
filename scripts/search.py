#!/usr/bin/env python
"""CLI: query → retrieve → rerank → print."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import click


@click.command()
@click.argument("query")
@click.option("--collection", default="doc_intel", show_default=True)
@click.option("--top-k", default=10, show_default=True)
@click.option("--top-n", default=5, show_default=True)
def main(query: str, collection: str, top_k: int, top_n: int) -> None:
    """Search for QUERY and print ranked results."""
    asyncio.run(_search(query, collection, top_k, top_n))


async def _search(query: str, collection: str, top_k: int, top_n: int) -> None:
    from doc_intel_rag.config import get_settings
    from doc_intel_rag.ingestion.embedder import DocumentEmbedder
    from doc_intel_rag.ingestion.vector_store import QdrantDocumentStore
    from doc_intel_rag.logging_config import setup_logging
    from doc_intel_rag.retrieval.hybrid_searcher import HybridSearcher
    from doc_intel_rag.retrieval.reranker import get_reranker
    from doc_intel_rag.retrieval.semantic_router import SemanticRouter

    settings = get_settings()
    setup_logging(settings)

    vs = QdrantDocumentStore(settings)
    emb = DocumentEmbedder(settings)
    reranker = get_reranker(settings)
    router = SemanticRouter(settings)

    intent = await router.classify(query)
    click.echo(f"Intent: {intent.value}")

    searcher = HybridSearcher(vector_store=vs, embedder=emb)
    chunks = await searcher.search(query=query, top_k=top_k, intent=intent, collection=collection)
    reranked = await reranker.rerank(query=query, chunks=chunks, top_n=top_n)

    for i, chunk in enumerate(reranked, 1):
        click.echo(f"\n[{i}] score={chunk.score:.4f} modality={chunk.modality} page={chunk.page}")
        click.echo(f"    {chunk.text[:200]}...")


if __name__ == "__main__":
    main()
