#!/usr/bin/env python
"""Pre-load models to eliminate cold-start latency on first request."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import click


@click.command()
@click.option("--skip-nli", is_flag=True, default=False, help="Skip NLI faithfulness model")
@click.option("--skip-spacy", is_flag=True, default=False, help="Skip spaCy model")
@click.option("--skip-detoxify", is_flag=True, default=False, help="Skip Detoxify model")
def main(skip_nli: bool, skip_spacy: bool, skip_detoxify: bool) -> None:
    """Warm up all ML models into memory."""
    click.echo("Warming up models...")

    if not skip_spacy:
        click.echo("  Loading spaCy model...")
        from doc_intel_rag.enrichment.concept_extractor import _load_nlp
        _load_nlp()
        click.echo("  spaCy: ok")

    if not skip_nli:
        click.echo("  Loading NLI faithfulness model...")
        from doc_intel_rag.safety.output_guard import _get_nli_model
        _get_nli_model()
        click.echo("  NLI: ok")

    if not skip_detoxify:
        click.echo("  Loading Detoxify toxicity model...")
        from doc_intel_rag.safety.output_guard import _get_detoxify
        _get_detoxify()
        click.echo("  Detoxify: ok")

    click.echo("Warmup complete.")


if __name__ == "__main__":
    main()
