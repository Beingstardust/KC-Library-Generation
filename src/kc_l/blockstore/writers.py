from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional

from kc_l.blockstore.schema import BlockRecord, PageRecord
from kc_l.utils.fs import ensure_dir


def write_jsonl(path: Path, records: Iterable[dict]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def page_to_dict(p: PageRecord) -> dict:
    return {
        "doc_id": p.doc_id,
        "page_index": p.page_index,
        "width_pt": p.width_pt,
        "height_pt": p.height_pt,
        "rotation": p.rotation,
        "image_relpath": p.image_relpath,
        "image_sha256": p.image_sha256,
    }


def block_to_dict(b: BlockRecord) -> dict:
    return {
        "doc_id": b.doc_id,
        "block_id": b.block_id,
        "layer": b.layer,
        "page_index": b.page_index,
        "content_type": b.content_type,
        "text_raw": b.text_raw,
        "bbox_pt": list(b.bbox_pt) if b.bbox_pt else None,
        "bbox_coord_system": b.bbox_coord_system,
        "raw_ref": b.raw_ref,
    }