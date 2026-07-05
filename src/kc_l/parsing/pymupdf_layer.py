from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fitz  # PyMuPDF

from kc_l.blockstore.schema import BlockRecord, PageRecord
from kc_l.utils.hash import sha256_file
from kc_l.utils.fs import ensure_dir


def extract_pymupdf(
    doc_id: str,
    pdf_path: Path,
    out_dir: Path,
    sort_text: bool,
    write_raw_dump: bool,
) -> Dict[str, Any]:
    """
    Extract:
      - page metadata (size, rotation)
      - text blocks via Page.get_text("blocks") which includes bbox info. :contentReference[oaicite:7]{index=7}
    """
    ensure_dir(out_dir)
    raw_dir = out_dir / "raw_output"
    ensure_dir(raw_dir)

    doc = fitz.open(str(pdf_path))
    pages: List[PageRecord] = []
    blocks: List[BlockRecord] = []

    raw_dump: Dict[str, Any] = {"pages": []}

    for page_index in range(doc.page_count):
        page = doc.load_page(page_index)
        rect = page.rect  # points
        rotation = int(page.rotation)

        # blocks: (x0, y0, x1, y1, "text", block_no, block_type)
        blk = page.get_text("blocks", sort=sort_text)
        # blk is list[tuple]
        raw_page = {
            "page_index": page_index,
            "width_pt": float(rect.width),
            "height_pt": float(rect.height),
            "rotation": rotation,
            "blocks": [],
        }

        for i, t in enumerate(blk):
            x0, y0, x1, y1, text, bno, btype = t
            text = text or ""
            block_id = f"{doc_id}:pymupdf:{page_index}:{i}"

            blocks.append(
                BlockRecord(
                    doc_id=doc_id,
                    block_id=block_id,
                    layer="pymupdf",
                    page_index=page_index,
                    content_type="text",
                    text_raw=text,
                    bbox_pt=(float(x0), float(y0), float(x1), float(y1)),
                    bbox_coord_system="pdf_points_top_left",
                    raw_ref={"layer": "pymupdf", "page_index": page_index, "block_index": i, "raw_dump": "pymupdf_raw.json"},
                )
            )

            raw_page["blocks"].append(
                {
                    "i": i,
                    "bbox_pt": [float(x0), float(y0), float(x1), float(y1)],
                    "text": text,
                    "block_no": int(bno),
                    "block_type": int(btype),
                }
            )

        pages.append(
            PageRecord(
                doc_id=doc_id,
                page_index=page_index,
                width_pt=float(rect.width),
                height_pt=float(rect.height),
                rotation=rotation,
                image_relpath=None,
                image_sha256=None,
            )
        )
        raw_dump["pages"].append(raw_page)

    if write_raw_dump:
        (raw_dir / "pymupdf_raw.json").write_text(json.dumps(raw_dump, ensure_ascii=False, indent=2), encoding="utf-8")

    doc.close()

    return {
        "pages": pages,
        "blocks": blocks,
        "layer_status": {"enabled": True, "ok": True, "n_pages": len(pages), "n_blocks": len(blocks)},
    }