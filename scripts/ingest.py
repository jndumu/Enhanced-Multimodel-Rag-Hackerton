#!/usr/bin/env python
"""CLI: ingest a document → embed → Qdrant."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import click


@click.command()
@click.argument("path")
@click.option("--collection", default="doc_intel", show_default=True)
@click.option("--no-enrich", is_flag=True, default=False)
@click.option("--force", is_flag=True, default=False, help="Re-ingest even if doc exists")
def main(path: str, collection: str, no_enrich: bool, force: bool) -> None:
    """Ingest PATH into Qdrant collection."""
    asyncio.run(_ingest(path, collection, not no_enrich, force))


async def _ingest(path: str, collection: str, enrich: bool, force: bool) -> None:
    from doc_intel_rag.api.routes.ingest import _run_ingest
    from doc_intel_rag.config import get_settings
    from doc_intel_rag.ingestion.graph_store import GraphStore
    from doc_intel_rag.ingestion.embedder import DocumentEmbedder
    from doc_intel_rag.ingestion.vector_store import QdrantDocumentStore
    from doc_intel_rag.logging_config import setup_logging

    settings = get_settings()
    setup_logging(settings)

    vs = QdrantDocumentStore(settings)
    emb = DocumentEmbedder(settings)
    gs = GraphStore()

    result = await _run_ingest(
        source=path,
        collection=collection,
        enrich=enrich,
        force=force,
        vector_store=vs,
        embedder=emb,
        graph_store=gs,
        query_cache=None,
    )
    click.echo(
        f"Ingested: doc_id={result.doc_id[:12]}... "
        f"chunks={result.chunk_count} "
        f"graph_nodes={result.graph_node_count} "
        f"cached={result.cached}"
    )


if __name__ == "__main__":
    main()
