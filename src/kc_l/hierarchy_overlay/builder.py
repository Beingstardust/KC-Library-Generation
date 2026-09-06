from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from kc_l.hierarchy_overlay.model import OverlayNode
from kc_l.utils.hashing import sha256_text


RAW_NODE_ID_KEYS: tuple[str, ...] = (
    "source_node_id",
    "raw_source_node_id",
    "raw_node_id",
    "node_id",
    "id",
)

RAW_EXPLICIT_TYPE_KEYS: tuple[str, ...] = (
    "node_type",
    "hierarchy_type",
    "granularity",
    "kind",
    "type",
)

EXPLICIT_INTERMEDIATE_VALUES = {"intermediate", "subtopic"}

# Real, checkable contract (kept consistent with kc_l/hierarchy/loader.py's own KC_ID_KEYS/
# CANONICAL_NAME_KEYS by convention, not by cross-import - separate packages, matching this
# repo's established small-helper-duplication convention): a KC leaf is identified structurally
# (no children), not by a manually-set "kc": true marker. kc_id/canonical_name aliasing mirrors
# the loader's own list exactly.
KC_ID_KEYS: tuple[str, ...] = ("kc_id", "id")
CANONICAL_NAME_KEYS: tuple[str, ...] = ("canonical_name", "name", "label")


def _first_present(node: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = _clean_optional_str(node.get(key))
        if value:
            return value
    return None


@dataclass
class OverlayBuildResult:
    nodes: list[OverlayNode]
    source_set_id: str
    raw_total_nodes: int
    raw_leaf_nodes: int
    raw_nonleaf_nodes: int


def _clean_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def extract_raw_source_node_id(node: Mapping[str, Any]) -> str | None:
    for key in RAW_NODE_ID_KEYS:
        value = _clean_optional_str(node.get(key))
        if value:
            return value
    return None


def extract_raw_explicit_node_type(node: Mapping[str, Any]) -> str | None:
    for key in RAW_EXPLICIT_TYPE_KEYS:
        value = _clean_optional_str(node.get(key))
        if value:
            return value.lower()
    return None


def _dedupe_preserve_order(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _make_fallback_hier_node_id(source_set_id: str, source_hierarchy_path: Sequence[str]) -> str:
    material = source_set_id + "\x1f" + "\x1f".join(source_hierarchy_path)
    return f"hier::path::{sha256_text(material)}"


def make_nonleaf_hier_node_id(
    *,
    source_set_id: str,
    source_hierarchy_path: Sequence[str],
    raw_source_node_id: str | None,
) -> str:
    if raw_source_node_id:
        return f"hier::raw::{raw_source_node_id}"
    return _make_fallback_hier_node_id(source_set_id, source_hierarchy_path)


def infer_node_type(
    *,
    raw_has_children: bool,
    raw_explicit_node_type: str | None,
) -> tuple[str, str]:
    # Structural contract (see ORCHESTRATOR_BUILD_STATE.md's hierarchy-ingestion-robustness
    # entry): a node with no children IS a KC leaf, unconditionally - "kc": true is no longer a
    # gating signal here (still captured as raw_kc_flag on OverlayNode for audit/provenance
    # only). Empirically confirmed against the known-good hierarchy file: every "kc": true node
    # in it is already exactly a no-children node, so this is behavior-preserving there.
    if not raw_has_children:
        return "leaf", "terminal_without_children"

    if raw_explicit_node_type in EXPLICIT_INTERMEDIATE_VALUES:
        return "intermediate", f"explicit_raw_node_type:{raw_explicit_node_type}"

    return "topic", "conservative_nonleaf_default"


def build_overlay(
    *,
    raw_tree: Mapping[str, Any],
    normalized_rows: list[dict[str, Any]],
    source_set_id: str,
) -> OverlayBuildResult:
    normalized_by_kc_id = {
        str(row.get("kc_id", "")).strip(): row
        for row in normalized_rows
        if str(row.get("kc_id", "")).strip()
    }
    nodes: list[OverlayNode] = []
    seen_hier_node_ids: set[str] = set()
    counters = {
        "raw_total_nodes": 0,
        "raw_leaf_nodes": 0,
        "raw_nonleaf_nodes": 0,
    }

    def recurse(node: Mapping[str, Any], source_hierarchy_path: list[str], parent_hier_node_id: str | None) -> OverlayNode:
        counters["raw_total_nodes"] += 1

        children = node.get("children")
        raw_has_children = isinstance(children, dict) and len(children) > 0
        # raw_kc_flag is captured for audit/provenance only (OverlayNode.raw_kc_flag) - it no
        # longer gates node_type or kc_id extraction, both of which are now structural/aliased.
        raw_kc_flag = node.get("kc") is True
        raw_source_node_id = extract_raw_source_node_id(node)
        raw_explicit_node_type = extract_raw_explicit_node_type(node)
        node_type, typing_basis = infer_node_type(
            raw_has_children=raw_has_children,
            raw_explicit_node_type=raw_explicit_node_type,
        )

        kc_id = _first_present(node, KC_ID_KEYS) if node_type == "leaf" else None
        label = _first_present(node, CANONICAL_NAME_KEYS) or source_hierarchy_path[-1]
        hier_node_id = (
            f"kc::{kc_id}"
            if kc_id
            else make_nonleaf_hier_node_id(
                source_set_id=source_set_id,
                source_hierarchy_path=source_hierarchy_path,
                raw_source_node_id=raw_source_node_id,
            )
        )

        if hier_node_id in seen_hier_node_ids:
            raise ValueError(f"Duplicate hier_node_id detected: {hier_node_id}")
        seen_hier_node_ids.add(hier_node_id)

        if node_type == "leaf":
            counters["raw_leaf_nodes"] += 1
        else:
            counters["raw_nonleaf_nodes"] += 1

        overlay_node = OverlayNode(
            hier_node_id=hier_node_id,
            kc_id=kc_id,
            label=label,
            node_type=node_type,
            parent_hier_node_id=parent_hier_node_id,
            depth_raw=len(source_hierarchy_path),
            depth_overlay=len(source_hierarchy_path),
            raw_source_present=True,
            normalized_leaf_present=bool(kc_id and kc_id in normalized_by_kc_id),
            source_hierarchy_path=list(source_hierarchy_path),
            hierarchy_description_raw=_clean_optional_str(node.get("description")) or "",
            pdf_grounded_semantic_status="unassessed",
            definition_full="",
            definition_short="",
            evidence_refs=[],
            raw_kc_flag=raw_kc_flag,
            raw_has_children=raw_has_children,
            raw_source_node_id=raw_source_node_id,
            raw_explicit_node_type=raw_explicit_node_type,
            typing_basis=typing_basis,
            source_set_id=source_set_id,
            raw_child_count=len(children) if raw_has_children else 0,
            is_root=parent_hier_node_id is None,
        )
        nodes.append(overlay_node)

        descendant_kc_ids: list[str] = []
        if raw_has_children:
            assert isinstance(children, dict)
            for child_label, child_node in children.items():
                child_overlay_node = recurse(
                    child_node,
                    source_hierarchy_path + [str(child_label)],
                    overlay_node.hier_node_id,
                )
                overlay_node.child_hier_node_ids.append(child_overlay_node.hier_node_id)
                descendant_kc_ids.extend(child_overlay_node.descendant_kc_ids)

        if kc_id:
            descendant_kc_ids.append(kc_id)

        overlay_node.descendant_kc_ids = _dedupe_preserve_order(descendant_kc_ids)
        overlay_node.descendant_leaf_count = len(overlay_node.descendant_kc_ids)
        return overlay_node

    for root_label, root_node in raw_tree.items():
        recurse(root_node, [str(root_label)], None)

    return OverlayBuildResult(
        nodes=nodes,
        source_set_id=source_set_id,
        raw_total_nodes=counters["raw_total_nodes"],
        raw_leaf_nodes=counters["raw_leaf_nodes"],
        raw_nonleaf_nodes=counters["raw_nonleaf_nodes"],
    )


def build_leaf_to_overlay_ancestry(nodes: Sequence[OverlayNode]) -> dict[str, dict[str, Any]]:
    node_by_id = {node.hier_node_id: node for node in nodes}
    ancestry: dict[str, dict[str, Any]] = {}

    for node in nodes:
        if not node.kc_id:
            continue

        ancestor_hier_node_ids: list[str] = []
        ancestor_labels: list[str] = []
        current_parent_id = node.parent_hier_node_id
        while current_parent_id:
            parent = node_by_id[current_parent_id]
            ancestor_hier_node_ids.append(parent.hier_node_id)
            ancestor_labels.append(parent.label)
            current_parent_id = parent.parent_hier_node_id

        ancestor_hier_node_ids.reverse()
        ancestor_labels.reverse()

        ancestry[node.kc_id] = {
            "leaf_hier_node_id": node.hier_node_id,
            "parent_hier_node_id": node.parent_hier_node_id,
            "source_hierarchy_path": node.source_hierarchy_path,
            "ancestor_hier_node_ids": ancestor_hier_node_ids,
            "ancestor_labels": ancestor_labels,
        }

    return ancestry


def build_overlay_node_index(nodes: Sequence[OverlayNode]) -> dict[str, dict[str, Any]]:
    return {
        node.hier_node_id: {
            "hier_node_id": node.hier_node_id,
            "kc_id": node.kc_id,
            "label": node.label,
            "node_type": node.node_type,
            "parent_hier_node_id": node.parent_hier_node_id,
            "source_hierarchy_path": node.source_hierarchy_path,
            "child_hier_node_ids": node.child_hier_node_ids,
            "descendant_kc_ids": node.descendant_kc_ids,
            "raw_source_node_id": node.raw_source_node_id,
            "raw_kc_flag": node.raw_kc_flag,
            "raw_has_children": node.raw_has_children,
        }
        for node in nodes
    }
