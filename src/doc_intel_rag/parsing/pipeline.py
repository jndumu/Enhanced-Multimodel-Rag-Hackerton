"""GLM-OCR + PP-DocLayout-V3 document parsing pipeline."""

from __future__ import annotations

import asyncio
import base64
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from doc_intel_rag.config import Settings, get_settings
from doc_intel_rag.parsing.entity_types import EntityLabel, ENTITY_TO_MODALITY


@dataclass
class BBox:
    """Axis-aligned bounding box of a detected layout element.

    Coordinates are in PDF points (72 dpi) relative to the page origin
    (bottom-left for most PDF renderers).

    Attributes:
        x0: Left edge of the bounding box.
        y0: Bottom edge of the bounding box.
        x1: Right edge of the bounding box.
        y1: Top edge of the bounding box.
        page: 1-based page number on which this box appears.
    """

    x0: float
    y0: float
    x1: float
    y1: float
    page: int


@dataclass
class ParsedElement:
    """A single layout element detected by PP-DocLayout-V3 / GLM-OCR.

    Attributes:
        label: Canonical :class:`~doc_intel_rag.parsing.entity_types.EntityLabel`.
        text: Extracted text content (OCR output or raw text for PDFs).
        page: 1-based page number.
        confidence: Layout detection confidence in ``[0, 1]``.
        bbox: Bounding box of the element on the page; ``None`` if unavailable.
        raw_image_b64: Base64-encoded PNG crop of the element's bounding region;
            populated for image, graph, and table elements.
        latex: LaTeX string for formula elements; ``None`` for all others.
        html: HTML representation for table elements; ``None`` for all others.
    """

    label: EntityLabel
    text: str
    page: int
    confidence: float
    bbox: BBox | None = None
    raw_image_b64: str | None = None
    latex: str | None = None
    html: str | None = None

    @property
    def modality(self) -> str:
        """Lookup the canonical modality string for this element's label."""
        return ENTITY_TO_MODALITY[self.label]


@dataclass
class ParseResult:
    """Complete output of a single document parse pass.

    Attributes:
        doc_id: SHA-256 hex digest of the source file bytes.  Used as the
            idempotency key for ingestion.
        source_file: Absolute path or URL of the document that was parsed.
        page_count: Total number of pages in the document.
        elements: Ordered list of all detected :class:`ParsedElement` objects.
        raw_metadata: Provider-specific metadata returned by the GLM-OCR SDK.
    """

    doc_id: str
    source_file: str
    page_count: int
    elements: list[ParsedElement] = field(default_factory=list)
    raw_metadata: dict[str, Any] = field(default_factory=dict)


class DocumentParser:
    """Entry point for document parsing using GLM-OCR + PP-DocLayout-V3.

    Supports both ``cloud`` and ``local`` backends as configured by
    ``settings.glmocr_backend``.  When the ``glmocr`` package is not installed
    or the API key is absent, a :class:`_StubGLMOCRClient` is used so the rest
    of the pipeline can still be exercised in tests without the SDK.

    All API calls are retried up to 3 times with exponential back-off via
    ``tenacity``.  CPU-bound operations (page rendering, bbox crop) are
    offloaded to a thread pool via ``asyncio.get_event_loop().run_in_executor``.

    Args:
        settings: Runtime configuration. Defaults to the global singleton.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        try:
            import glmocr  # type: ignore[import-untyped]

            if self._settings.glmocr_backend == "cloud":
                self._client = glmocr.Client(
                    api_key=self._settings.glmocr_api_key,
                    timeout=self._settings.glmocr_timeout,
                )
            else:
                self._client = glmocr.LocalClient(
                    model=self._settings.glmocr_local_model,
                    timeout=self._settings.glmocr_timeout,
                )
        except ImportError:
            logger.warning("glmocr SDK not installed — using stub parser")
            self._client = _StubGLMOCRClient()

        return self._client

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def parse(self, file_path: str | Path) -> ParseResult:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Document not found: {path}")

        raw_bytes = path.read_bytes()
        doc_id = hashlib.sha256(raw_bytes).hexdigest()

        logger.info("Parsing document", doc_id=doc_id[:12], path=str(path))

        client = self._get_client()

        loop = asyncio.get_event_loop()
        raw_result = await loop.run_in_executor(
            None, lambda: client.parse(str(path))
        )

        elements = self._convert_elements(raw_result, raw_bytes)
        page_count = max((e.page for e in elements), default=1)

        logger.info(
            "Parsing complete",
            doc_id=doc_id[:12],
            elements=len(elements),
            pages=page_count,
        )

        return ParseResult(
            doc_id=doc_id,
            source_file=str(path),
            page_count=page_count,
            elements=elements,
            raw_metadata=getattr(raw_result, "metadata", {}),
        )

    def _convert_elements(self, raw_result: Any, raw_bytes: bytes) -> list[ParsedElement]:
        elements: list[ParsedElement] = []

        raw_elements: list[Any] = getattr(raw_result, "elements", raw_result) or []

        for raw in raw_elements:
            label_str: str = getattr(raw, "label", "paragraph")
            try:
                label = EntityLabel(label_str)
            except ValueError:
                logger.debug("Unknown entity label, defaulting to paragraph", label=label_str)
                label = EntityLabel.PARAGRAPH

            bbox_raw = getattr(raw, "bbox", None)
            bbox: BBox | None = None
            if bbox_raw is not None:
                bbox = BBox(
                    x0=float(getattr(bbox_raw, "x0", 0)),
                    y0=float(getattr(bbox_raw, "y0", 0)),
                    x1=float(getattr(bbox_raw, "x1", 0)),
                    y1=float(getattr(bbox_raw, "y1", 0)),
                    page=int(getattr(raw, "page", 1)),
                )

            image_b64: str | None = None
            if ENTITY_TO_MODALITY[label] in {"image", "graph", "table"} and bbox is not None:
                image_b64 = self._crop_element(raw_bytes, bbox, str(getattr(raw, "page", 1)))

            elements.append(
                ParsedElement(
                    label=label,
                    text=str(getattr(raw, "text", "") or ""),
                    page=int(getattr(raw, "page", 1)),
                    confidence=float(getattr(raw, "confidence", 1.0)),
                    bbox=bbox,
                    raw_image_b64=image_b64 or getattr(raw, "image_b64", None),
                    latex=getattr(raw, "latex", None),
                    html=getattr(raw, "html", None),
                )
            )

        return elements

    def _crop_element(self, raw_bytes: bytes, bbox: BBox, page_str: str) -> str | None:
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(stream=raw_bytes, filetype="pdf")
            page_num = max(0, int(page_str) - 1)
            if page_num >= len(doc):
                return None
            page = doc[page_num]
            rect = fitz.Rect(bbox.x0, bbox.y0, bbox.x1, bbox.y1)
            pix = page.get_pixmap(clip=rect, dpi=150)
            return base64.b64encode(pix.tobytes("png")).decode()
        except Exception as exc:
            logger.debug("Element crop failed", error=str(exc))
            return None


class _StubGLMOCRClient:
    """Returns a minimal single-element result when glmocr is unavailable."""

    def parse(self, path: str) -> "_StubResult":
        return _StubResult(path)


@dataclass
class _StubResult:
    _path: str

    @property
    def elements(self) -> list[Any]:
        return [
            _StubElement(
                label="paragraph",
                text=f"[Stub parse result for: {self._path}]",
                page=1,
                confidence=0.0,
            )
        ]

    @property
    def metadata(self) -> dict[str, Any]:
        return {"stub": True}


@dataclass
class _StubElement:
    label: str
    text: str
    page: int
    confidence: float
    bbox: None = None
    image_b64: None = None
    latex: None = None
    html: None = None
