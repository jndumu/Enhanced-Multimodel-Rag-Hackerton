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
    x0: float
    y0: float
    x1: float
    y1: float
    page: int


@dataclass
class ParsedElement:
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
        return ENTITY_TO_MODALITY[self.label]


@dataclass
class ParseResult:
    doc_id: str
    source_file: str
    page_count: int
    elements: list[ParsedElement] = field(default_factory=list)
    raw_metadata: dict[str, Any] = field(default_factory=dict)


class DocumentParser:
    """Wraps GLM-OCR SDK for cloud and local backends.

    Falls back to a stub parser when glmocr is not installed or API key is empty,
    so imports and unit tests work without the SDK.
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
