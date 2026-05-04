"""Image cropping, resizing, and base64 encoding helpers."""

from __future__ import annotations

import base64
from io import BytesIO


def pil_to_b64(image: "object") -> str:
    """Convert a PIL Image to base64-encoded PNG string."""
    from PIL import Image
    assert isinstance(image, Image.Image)
    buf = BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def crop_bbox_from_bytes(
    pdf_bytes: bytes,
    page: int,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    dpi: int = 150,
) -> str | None:
    """Extract a bounding-box region from a PDF page as base64 PNG."""
    try:
        import fitz

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page_num = max(0, page - 1)
        if page_num >= len(doc):
            return None
        pg = doc[page_num]
        rect = fitz.Rect(x0, y0, x1, y1)
        pix = pg.get_pixmap(clip=rect, dpi=dpi)
        return base64.b64encode(pix.tobytes("png")).decode()
    except Exception:
        return None


def resize_b64(b64: str, max_dim: int = 1024) -> str:
    """Resize a base64 PNG so that neither dimension exceeds max_dim."""
    from PIL import Image

    data = base64.b64decode(b64)
    img = Image.open(BytesIO(data))
    img.thumbnail((max_dim, max_dim))
    return pil_to_b64(img)
