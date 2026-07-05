from __future__ import annotations

from collections import Counter
from typing import Any, Sequence

from kc_l.hierarchy_overlay.model import OverlayNode, OverlayValidationIssue


def _issue(
    issues: list[OverlayValidationIssue],
    *,
    level: str,
    code: str,
    message: str,
    node: OverlayNode | None = None,
    kc_id: str | None = None,
    source_hierarchy_path: list[str] | None = None,
) -> None:
    issues.append(
        OverlayValidationIssue(
            level=level,
            code=code,
            message=message,
            hier_node_id=node.hier_node_id if node else None,
            kc_id=kc_id or (node.kc_id if node else None),
            source_hierarchy_path=source_hierarchy_path or (node.source_hierarchy_path if node else None),
        )
    )


def _find_node_by_path(nodes: Sequence[OverlayNode], path: Sequence[str]) -> OverlayNode | None:
    path_list = list(path)
    for node in nodes:
        if node.source_hierarchy_path == path_list:
            return node
    return None


def _family_summary(nodes: Sequence[OverlayNode], path: Sequence[str]) -> dict[str, Any]:
    node = _find_node_by_path(nodes, path)
    if node is None:
        return {
            "present": False,
            "source_hierarchy_path": list(path),
        }

    return {
        "present": True,
        "hier_node_id": node.hier_node_id,
        "kc_id": node.kc_id,
        "label": node.label,
        "node_type": node.node_type,
        "child_count": len(node.child_hier_node_ids),
        "child_hier_node_ids": node.child_hier_node_ids,
        "descendant_kc_ids": node.descendant_kc_ids,
        "raw_kc_flag": node.raw_kc_flag,
        "raw_has_children": node.raw_has_children,
        "pdf_grounded_semantic_status": node.pdf_grounded_semantic_status,
    }


def validate_overlay(
    *,
    nodes: Sequence[OverlayNode],
    normalized_rows: list[dict[str, Any]],
    raw_total_nodes: int,
    raw_leaf_nodes: int,
    raw_nonleaf_nodes: int,
) -> dict[str, Any]:
    issues: list[OverlayValidationIssue] = []

    normalized_kc_ids = [
        str(row.get("kc_id", "")).strip()
        for row in normalized_rows
        if str(row.get("kc_id", "")).strip()
    ]
    normalized_kc_id_set = set(normalized_kc_ids)
    normalized_by_kc_id = {
        str(row.get("kc_id", "")).strip(): row
        for row in normalized_rows
        if str(row.get("kc_id", "")).strip()
    }

    hier_node_id_counts = Counter(node.hier_node_id for node in nodes)
    duplicate_hier_node_ids = sorted(node_id for node_id, count in hier_node_id_counts.items() if count > 1)
    for node_id in duplicate_hier_node_ids:
        _issue(
            issues,
            level="ERROR",
            code="DUPLICATE_HIER_NODE_ID",
            message=f"Duplicate hier_node_id detected: {node_id}",
        )

    overlay_leaf_kc_ids: list[str] = []
    for node in nodes:
        if node.node_type == "leaf":
            if not node.kc_id:
                _issue(
                    issues,
                    level="ERROR",
                    code="LEAF_MISSING_KC_ID",
                    message="Leaf overlay node missing kc_id.",
                    node=node,
                )
            else:
                overlay_leaf_kc_ids.append(node.kc_id)
        elif node.kc_id is not None:
            _issue(
                issues,
                level="ERROR",
                code="NONLEAF_HAS_KC_ID",
                message="Non-leaf overlay node must not carry kc_id.",
                node=node,
            )

        if node.raw_kc_flag and not node.kc_id:
            _issue(
                issues,
                level="ERROR",
                code="RAW_KC_FLAG_WITHOUT_KC_ID",
                message="Raw kc node is missing kc_id in overlay.",
                node=node,
            )

        if node.raw_has_children != bool(node.child_hier_node_ids):
            _issue(
                issues,
                level="ERROR",
                code="RAW_CHILD_FLAG_MISMATCH",
                message="raw_has_children does not match child_hier_node_ids.",
                node=node,
            )

        if node.definition_full:
            _issue(
                issues,
                level="ERROR",
                code="SEMANTIC_FIELD_POPULATED_DEFINITION_FULL",
                message="definition_full must remain empty in the structural overlay step.",
                node=node,
            )
        if node.definition_short:
            _issue(
                issues,
                level="ERROR",
                code="SEMANTIC_FIELD_POPULATED_DEFINITION_SHORT",
                message="definition_short must remain empty in the structural overlay step.",
                node=node,
            )
        if node.evidence_refs:
            _issue(
                issues,
                level="ERROR",
                code="SEMANTIC_FIELD_POPULATED_EVIDENCE_REFS",
                message="evidence_refs must remain empty in the structural overlay step.",
                node=node,
            )
        if node.pdf_grounded_semantic_status != "unassessed":
            _issue(
                issues,
                level="ERROR",
                code="UNEXPECTED_PDF_GROUNDED_STATUS",
                message="pdf_grounded_semantic_status must remain 'unassessed' in the structural overlay step.",
                node=node,
            )

        if node.kc_id and node.kc_id in normalized_by_kc_id:
            normalized_path = list(normalized_by_kc_id[node.kc_id].get("kc_path", []))
            if normalized_path != node.source_hierarchy_path:
                _issue(
                    issues,
                    level="ERROR",
                    code="LEAF_PATH_MISMATCH",
                    message="Overlay leaf path does not match the normalized registry path for the same kc_id.",
                    node=node,
                )
            if node.normalized_leaf_present is not True:
                _issue(
                    issues,
                    level="ERROR",
                    code="NORMALIZED_LEAF_PRESENT_FLAG_MISMATCH",
                    message="normalized_leaf_present is false for a leaf that exists in the normalized registry.",
                    node=node,
                )

    overlay_leaf_kc_id_counts = Counter(overlay_leaf_kc_ids)
    duplicate_leaf_kc_ids = sorted(kc_id for kc_id, count in overlay_leaf_kc_id_counts.items() if count > 1)
    for kc_id in duplicate_leaf_kc_ids:
        _issue(
            issues,
            level="ERROR",
            code="DUPLICATE_LEAF_KC_ID",
            message=f"Duplicate leaf kc_id detected: {kc_id}",
            kc_id=kc_id,
        )

    overlay_leaf_kc_id_set = set(overlay_leaf_kc_ids)
    normalized_missing_in_overlay = sorted(normalized_kc_id_set - overlay_leaf_kc_id_set)
    overlay_leaf_missing_in_normalized = sorted(overlay_leaf_kc_id_set - normalized_kc_id_set)
    for kc_id in normalized_missing_in_overlay:
        _issue(
            issues,
            level="ERROR",
            code="NORMALIZED_LEAF_MISSING_IN_OVERLAY",
            message=f"Normalized leaf kc_id missing in overlay: {kc_id}",
            kc_id=kc_id,
        )
    for kc_id in overlay_leaf_missing_in_normalized:
        _issue(
            issues,
            level="ERROR",
            code="OVERLAY_LEAF_MISSING_IN_NORMALIZED",
            message=f"Overlay leaf kc_id missing from normalized registry: {kc_id}",
            kc_id=kc_id,
        )

    dbscan = _family_summary(nodes, ["Data Mining", "Clustering", "Density-Based Clustering (DBSCAN)"])
    naive_bayes = _family_summary(nodes, ["Data Mining", "Classification", "Naive Bayes"])
    kmeans = _family_summary(nodes, ["Data Mining", "Clustering", "K-Means Family"])
    hierarchical = _family_summary(nodes, ["Data Mining", "Clustering", "Hierarchical Clustering"])

    if not dbscan["present"]:
        _issue(
            issues,
            level="ERROR",
            code="DBSCAN_PARENT_MISSING",
            message="DBSCAN parent/topic node is missing from overlay.",
            source_hierarchy_path=["Data Mining", "Clustering", "Density-Based Clustering (DBSCAN)"],
        )
    else:
        if dbscan["kc_id"] is not None:
            _issue(
                issues,
                level="ERROR",
                code="DBSCAN_PARENT_HAS_KC_ID",
                message="DBSCAN parent/topic node must not have an invented kc_id.",
                kc_id=dbscan["kc_id"],
                source_hierarchy_path=["Data Mining", "Clustering", "Density-Based Clustering (DBSCAN)"],
            )
        if dbscan["child_count"] != 9:
            _issue(
                issues,
                level="ERROR",
                code="DBSCAN_CHILD_COUNT_MISMATCH",
                message=f"DBSCAN child count mismatch: expected 9, found {dbscan['child_count']}.",
                source_hierarchy_path=["Data Mining", "Clustering", "Density-Based Clustering (DBSCAN)"],
            )

    additional_family_checks = {
        "Naive Bayes": naive_bayes,
        "K-Means Family": kmeans,
        "Hierarchical Clustering": hierarchical,
    }
    for family_name, family_summary in additional_family_checks.items():
        if not family_summary["present"]:
            _issue(
                issues,
                level="ERROR",
                code="FAMILY_PARENT_MISSING",
                message=f"{family_name} parent/topic node is missing from overlay.",
                source_hierarchy_path=family_summary["source_hierarchy_path"],
            )

    nonleaf_nodes = [node for node in nodes if node.node_type != "leaf"]
    nonleaf_identity_audit = {
        "nonleaf_total": len(nonleaf_nodes),
        "with_raw_source_node_id": sum(1 for node in nonleaf_nodes if node.raw_source_node_id),
        "with_hash_fallback_identity": sum(
            1 for node in nonleaf_nodes if node.hier_node_id.startswith("hier::path::")
        ),
        "nonleaf_nodes_with_kc_id": sum(1 for node in nonleaf_nodes if node.kc_id is not None),
    }

    hierarchy_description_count = sum(1 for node in nodes if node.hierarchy_description_raw)
    semantic_field_protection_audit = {
        "nodes_with_hierarchy_description_raw": hierarchy_description_count,
        "definition_full_nonempty_count": sum(1 for node in nodes if bool(node.definition_full)),
        "definition_short_nonempty_count": sum(1 for node in nodes if bool(node.definition_short)),
        "evidence_refs_nonempty_count": sum(1 for node in nodes if bool(node.evidence_refs)),
        "pdf_grounded_semantic_status_counts": dict(Counter(node.pdf_grounded_semantic_status for node in nodes)),
        "explanation": "Hierarchy descriptions are preserved only in hierarchy_description_raw; semantic fields remain empty and unassessed in this step.",
    }

    node_type_counts = dict(Counter(node.node_type for node in nodes))
    checks = {
        "overlay_total_matches_raw": len(nodes) == raw_total_nodes,
        "leaf_kc_id_preservation_ok": not normalized_missing_in_overlay and not overlay_leaf_missing_in_normalized,
        "nonleaf_kc_id_ok": nonleaf_identity_audit["nonleaf_nodes_with_kc_id"] == 0,
        "semantic_fields_protected_ok": (
            semantic_field_protection_audit["definition_full_nonempty_count"] == 0
            and semantic_field_protection_audit["definition_short_nonempty_count"] == 0
            and semantic_field_protection_audit["evidence_refs_nonempty_count"] == 0
        ),
        "dbscan_parent_present": dbscan["present"],
        "dbscan_child_count_ok": dbscan.get("child_count") == 9 if dbscan["present"] else False,
        "additional_families_present": all(summary["present"] for summary in additional_family_checks.values()),
    }

    return {
        "counts": {
            "raw_total_nodes": raw_total_nodes,
            "raw_leaf_nodes": raw_leaf_nodes,
            "raw_nonleaf_nodes": raw_nonleaf_nodes,
            "normalized_leaf_nodes": len(normalized_kc_ids),
            "overlay_total_nodes": len(nodes),
            "overlay_node_type_counts": node_type_counts,
        },
        "checks": checks,
        "dbscan": dbscan,
        "additional_families": additional_family_checks,
        "leaf_kc_id_preservation_audit": {
            "normalized_leaf_count": len(normalized_kc_ids),
            "overlay_leaf_count": len(overlay_leaf_kc_ids),
            "normalized_missing_in_overlay": normalized_missing_in_overlay,
            "overlay_leaf_missing_in_normalized": overlay_leaf_missing_in_normalized,
            "path_mismatch_count": sum(1 for issue in issues if issue.code == "LEAF_PATH_MISMATCH"),
        },
        "nonleaf_identity_audit": nonleaf_identity_audit,
        "semantic_field_protection_audit": semantic_field_protection_audit,
        "issues": [issue.to_row() for issue in issues],
        "issue_counts": dict(Counter(issue.code for issue in issues)),
        "has_errors": any(issue.level == "ERROR" for issue in issues),
    }
