from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Tuple


LayerName = Literal["pymupdf", "docling", "mineru", "mineru_salvage", "math_ocr"]

ContentType = Literal[
    "text",
    "title",
    "header",
    "footer",
    "page_number",
    "list",
    "table",
    "table_caption",
    "table_footnote",
    "figure",
    "figure_caption",
    "figure_footnote",
    "equation",
    "code",
    "unknown",
]

BBox = Tuple[float, float, float, float]  # [x0, y0, x1, y1] in a documented coordinate system


@dataclass(frozen=True)
class PageRecord:
    doc_id: str
    page_index: int
    width_pt: float
    height_pt: float
    rotation: int
    image_relpath: Optional[str]
    image_sha256: Optional[str]


@dataclass(frozen=True)
class BlockRecord:
    doc_id: str
    block_id: str
    layer: LayerName
    page_index: int

    content_type: ContentType
    text_raw: str

    # Geometry
    bbox_pt: Optional[BBox]
    bbox_coord_system: Optional[str]  # "pdf_points_top_left" or "mineru_0_1000_norm" etc

    # Raw provenance pointer (critical for auditability without brittle alignment)
    raw_ref: Dict[str, Any]  # e.g., {"raw_relpath": "...", "json_pointer": "..."} or {"source": "..."}