#!/usr/bin/env python
"""CLI: parse a document → Markdown + JSON + chunks."""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import click


@click.command()
@click.argument("path")
@click.option("--output-dir", "-o", default=".", help="Directory to write output files")
@click.option("--no-enrich", is_flag=True, default=False, help="Skip enrichment")
def main(path: str, output_dir: str, no_enrich: bool) -> None:
    """Parse PATH and write <stem>.md, <stem>_chunks.json to OUTPUT_DIR."""
    asyncio.run(_parse(path, output_dir, not no_enrich))


async def _parse(path: str, output_dir: str, enrich: bool) -> None:
    os.environ.setdefault("DOC_INTEL_SKIP_VALIDATION", "0")
    from doc_intel_rag.chunking.document_chunker import document_aware_chunking
    from doc_intel_rag.config import get_settings
    from doc_intel_rag.logging_config import setup_logging
    from doc_intel_rag.parsing.pipeline import DocumentParser
    from doc_intel_rag.parsing.post_processor import to_markdown

    settings = get_settings()
    setup_logging(settings)

    parser = DocumentParser(settings)
    result = await parser.parse(path)
    md = to_markdown(result)
    chunks = document_aware_chunking(result, settings)

    stem = os.path.splitext(os.path.basename(path))[0]
    os.makedirs(output_dir, exist_ok=True)

    md_path = os.path.join(output_dir, f"{stem}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    click.echo(f"Markdown written to {md_path}")

    chunks_path = os.path.join(output_dir, f"{stem}_chunks.json")
    with open(chunks_path, "w", encoding="utf-8") as f:
        json.dump([c.to_dict() for c in chunks], f, indent=2, default=str)
    click.echo(f"Chunks written to {chunks_path} ({len(chunks)} chunks)")


if __name__ == "__main__":
    main()
