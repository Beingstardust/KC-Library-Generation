from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Literal


NodeType = Literal["doc", "page", "leaf"]


@dataclass(frozen=True)
class DocNode:
    node_id: str
    doc_id: str
    node_type: NodeType

    label: str
    page_index: Optional[int]

    parent_id: Optional[str]
    child_ids: List[str]

    # Do not merge across layers. Keep explicit mappings.
    block_ids_by_layer: Dict[str, List[str]]

    # Evidence-backed title fields (optional)
    title: Optional[str]
    title_block_id: Optional[str]
    title_confidence: Optional[float]

    meta: Dict[str, Any]