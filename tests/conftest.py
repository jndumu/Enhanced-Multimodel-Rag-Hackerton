"""Test configuration — set environment before any import of doc_intel_rag."""

from __future__ import annotations

import os

# Must be set before any Settings import.
# pydantic-settings v2 JSON-decodes list fields from env, so use JSON arrays.
os.environ["DOC_INTEL_SKIP_VALIDATION"] = "1"
os.environ["MESH_API_KEY"] = "test-key"
os.environ["API_KEYS"] = "[]"        # valid JSON empty list
os.environ["CORS_ORIGINS"] = '["*"]' # valid JSON list

import pytest


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Reset the singleton settings cache between tests to avoid state leakage."""
    from doc_intel_rag.config import reset_settings
    reset_settings()
    yield
    reset_settings()
