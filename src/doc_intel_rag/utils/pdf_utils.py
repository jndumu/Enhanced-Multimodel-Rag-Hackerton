"""PyMuPDF helper utilities."""

from __future__ import annotations

from pathlib import Path


def page_count(path: str | Path) -> int:
    import fitz
    with fitz.open(str(path)) as doc:
        return len(doc)


def extract_text(path: str | Path, page: int = 0) -> str:
    import fitz
    with fitz.open(str(path)) as doc:
        if page >= len(doc):
            return ""
        return doc[page].get_text()


def pdf_to_images_b64(path: str | Path, dpi: int = 150) -> list[str]:
    """Render each page as a base64 PNG."""
    import base64
    import fitz

    images: list[str] = []
    with fitz.open(str(path)) as doc:
        for pg in doc:
            pix = pg.get_pixmap(dpi=dpi)
            images.append(base64.b64encode(pix.tobytes("png")).decode())
    return images
