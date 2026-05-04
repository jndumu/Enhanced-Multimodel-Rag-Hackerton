#!/usr/bin/env python
"""Launch uvicorn server for doc-intel-rag."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import click
import uvicorn


@click.command()
@click.option("--host", default="0.0.0.0", show_default=True, help="Bind host")
@click.option("--port", default=8000, show_default=True, help="Bind port")
@click.option("--workers", default=1, show_default=True, help="Worker processes")
@click.option("--reload", is_flag=True, default=False, help="Enable hot reload (dev only)")
@click.option("--log-level", default="info", show_default=True, help="Uvicorn log level")
def main(host: str, port: int, workers: int, reload: bool, log_level: str) -> None:
    """Start the doc-intel-rag API server."""
    uvicorn.run(
        "doc_intel_rag.api.app:app",
        host=host,
        port=port,
        workers=workers if not reload else 1,
        reload=reload,
        log_level=log_level,
    )


if __name__ == "__main__":
    main()
