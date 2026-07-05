from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


OverlayNodeType = Literal["topic", "intermediate", "leaf"]
PdfGroundedSemanticStatus = Literal["unassessed", "grounded", "unsupported", "not_applicable"]


@dataclass
class OverlayNode:
    hier_node_id: str
    kc_id: str | None
    label: str
    node_type: OverlayNodeType
    parent_hier_node_id: str | None
    depth_raw: int
    depth_overlay: int
    raw_source_present: bool
    normalized_leaf_present: bool
    source_hierarchy_path: list[str]
    descendant_kc_ids: list[str] = field(default_factory=list)
    child_hier_node_ids: list[str] = field(default_factory=list)
    hierarchy_description_raw: str = ""
    pdf_grounded_semantic_status: PdfGroundedSemanticStatus = "unassessed"
    definition_full: str = ""
    definition_short: str = ""
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)
    raw_kc_flag: bool = False
    raw_has_children: bool = False
    raw_source_node_id: str | None = None
    raw_explicit_node_type: str | None = None
    typing_basis: str = ""
    source_set_id: str = ""
    raw_child_count: int = 0
    descendant_leaf_count: int = 0
    is_root: bool = False

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OverlayValidationIssue:
    level: str
    code: str
    message: str
    hier_node_id: str | None = None
    kc_id: str | None = None
    source_hierarchy_path: list[str] | None = None

    def to_row(self) -> dict[str, Any]:
        return asdict(self)
