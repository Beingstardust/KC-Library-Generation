from __future__ import annotations

from pathlib import Path
from typing import Dict

import fitz  # PyMuPDF

from kc_l.utils.fs import ensure_dir
from kc_l.utils.hash import sha256_file


def render_pages(pdf_path: Path, out_dir: Path, dpi: int, fmt: str) -> Dict[int, Dict[str, str]]:
    """
    Renders each page to an image file. Needed for audit and later multimodal.
    """
    ensure_dir(out_dir)
    doc = fitz.open(str(pdf_path))

    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)

    result: Dict[int, Dict[str, str]] = {}

    for page_index in range(doc.page_count):
        page = doc.load_page(page_index)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        fn = f"page_{page_index:04d}.{fmt}"
        path = out_dir / fn
        pix.save(str(path))
        result[page_index] = {
            "relpath": f"page_images/{fn}",
            "sha256": sha256_file(path),
        }

    doc.close()
    return result