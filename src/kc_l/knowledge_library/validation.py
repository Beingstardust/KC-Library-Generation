from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from kc_l.knowledge_library.contracts import (
    ALLOWED_PILOT_EDGE_STATUSES,
    ALLOWED_PILOT_EDGE_TYPES,
    ALLOWED_PILOT_NODE_STATUSES,
    ALLOWED_PILOT_NODE_TYPES,
    GraphEdgeRecord,
    KCNodeRecord,
    KC_PAYLOAD_REQUIRED_FIELDS,
    KNOWLEDGE_LIBRARY_VALIDATION_VERSION,
    RAW_KC_PAYLOAD_FIELD,
    RAW_TOPIC_PAYLOAD_FIELD,
    TOPIC_PAYLOAD_REQUIRED_FIELDS,
    TopicNodeRecord,
    ValidationIssue,
)


TOPIC_COUNT_PATTERN = re.compile(r"- Topic node count: (\d+)")
KC_COUNT_PATTERN = re.compile(r"- KC node count: (\d+)")
TOPIC_EDGE_COUNT_PATTERN = re.compile(r"- topic_contains_topic edge count: (\d+)")
TOPIC_KC_EDGE_COUNT_PATTERN = re.compile(r"- topic_contains_kc edge count: (\d+)")
EXCLUDED_TOPIC_LEAK_PATTERN = re.compile(r"- Excluded topic nodes leaked into graph: (PASS|FAIL) \((\d+)\)")
NONAPPROVED_KC_LEAK_PATTERN = re.compile(r"- Non-approved KC nodes leaked into graph: (PASS|FAIL) \((\d+)\)")
NODE_COLLISION_PATTERN = re.compile(r"- Node id collisions across types: (PASS|FAIL) \((\d+)\)")
MISSING_ENDPOINT_PATTERN = re.compile(r"- Edges pointing to missing nodes: (PASS|FAIL) \((\d+)\)")


@dataclass(frozen=True)
class KnowledgeLibraryValidationBundle:
    normalized_nodes: tuple[TopicNodeRecord | KCNodeRecord, ...]
    normalized_edges: tuple[GraphEdgeRecord, ...]
    issues: tuple[ValidationIssue, ...]
    summary: dict[str, Any]

    @property
    def has_errors(self) -> bool:
        return any(issue.level == "ERROR" for issue in self.issues)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _is_mapping(value: Any) -> bool:
    return isinstance(value, Mapping)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _normalize_payload(
    row: Mapping[str, Any],
    *,
    node_type: str,
    artifact: str,
    record_id: str | None,
) -> tuple[dict[str, Any] | None, list[ValidationIssue], str | None]:
    issues: list[ValidationIssue] = []
    payload_field = "payload"
    alias_field = RAW_TOPIC_PAYLOAD_FIELD if node_type == "topic" else RAW_KC_PAYLOAD_FIELD
    wrong_alias_field = RAW_KC_PAYLOAD_FIELD if node_type == "topic" else RAW_TOPIC_PAYLOAD_FIELD

    payload_value = row.get(payload_field)
    alias_value = row.get(alias_field)
    wrong_alias_value = row.get(wrong_alias_field)

    if payload_value is not None and alias_value is not None:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="AMBIGUOUS_NODE_PAYLOAD",
                message=f"Node supplies both canonical payload and alias field `{alias_field}`.",
                artifact=artifact,
                record_id=record_id,
            )
        )
        return None, issues, None

    if wrong_alias_value is not None:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="WRONG_TYPED_PAYLOAD_ALIAS",
                message=f"Node of type `{node_type}` carries the wrong typed payload alias `{wrong_alias_field}`.",
                artifact=artifact,
                record_id=record_id,
            )
        )
        return None, issues, None

    selected_field = payload_field if payload_value is not None else alias_field
    selected_value = payload_value if payload_value is not None else alias_value
    if selected_value is None:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="MISSING_NODE_PAYLOAD",
                message=f"Node is missing payload data; expected `{payload_field}` or `{alias_field}`.",
                artifact=artifact,
                record_id=record_id,
            )
        )
        return None, issues, None

    if not _is_mapping(selected_value):
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="INVALID_NODE_PAYLOAD",
                message=f"Node payload field `{selected_field}` must be an object.",
                artifact=artifact,
                record_id=record_id,
            )
        )
        return None, issues, None

    return dict(selected_value), issues, selected_field


def _validate_required_payload_family(
    payload: Mapping[str, Any],
    *,
    required_fields: tuple[str, ...],
    forbidden_signature_fields: tuple[str, ...],
    artifact: str,
    record_id: str | None,
    payload_family: str,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    missing = [field for field in required_fields if field not in payload]
    if missing:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="MISSING_PAYLOAD_FIELDS",
                message=f"{payload_family} payload is missing required fields: {missing}.",
                artifact=artifact,
                record_id=record_id,
            )
        )
    if all(field in payload for field in forbidden_signature_fields):
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="COLLAPSED_TYPED_PAYLOAD",
                message=f"{payload_family} payload looks like the other typed payload family.",
                artifact=artifact,
                record_id=record_id,
            )
        )
    return issues


def normalize_node_row(
    row: Mapping[str, Any],
    *,
    artifact: str,
) -> tuple[TopicNodeRecord | KCNodeRecord | None, list[ValidationIssue], str | None]:
    issues: list[ValidationIssue] = []
    node_id = _as_text(row.get("node_id"))
    node_type = _as_text(row.get("node_type"))
    source_id = _as_text(row.get("source_id"))
    title = _as_text(row.get("title"))
    status = _as_text(row.get("status"))
    parent_id_raw = row.get("parent_id")
    provenance_ref = row.get("provenance_ref")

    if node_type not in ALLOWED_PILOT_NODE_TYPES:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="INVALID_NODE_TYPE",
                message=f"Invalid node_type `{node_type or '<missing>'}`.",
                artifact=artifact,
                record_id=node_id or None,
            )
        )
        return None, issues, None

    payload, payload_issues, payload_field = _normalize_payload(
        row,
        node_type=node_type,
        artifact=artifact,
        record_id=node_id or None,
    )
    issues.extend(payload_issues)

    if not node_id:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="MISSING_NODE_ID",
                message="Node is missing node_id.",
                artifact=artifact,
            )
        )
    if not source_id:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="MISSING_SOURCE_ID",
                message="Node is missing source_id.",
                artifact=artifact,
                record_id=node_id or None,
            )
        )
    if not title:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="MISSING_NODE_TITLE",
                message="Node is missing title.",
                artifact=artifact,
                record_id=node_id or None,
            )
        )
    if status not in ALLOWED_PILOT_NODE_STATUSES:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="INVALID_NODE_STATUS",
                message=f"Node status `{status or '<missing>'}` is not in the allowed pilot set.",
                artifact=artifact,
                record_id=node_id or None,
            )
        )
    if parent_id_raw is not None and not isinstance(parent_id_raw, str):
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="INVALID_PARENT_ID",
                message="Node parent_id must be a string or null.",
                artifact=artifact,
                record_id=node_id or None,
            )
        )
    if not _is_mapping(provenance_ref):
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="INVALID_PROVENANCE_REF",
                message="Node provenance_ref must be an object.",
                artifact=artifact,
                record_id=node_id or None,
            )
        )
    if payload is None or any(issue.level == "ERROR" for issue in issues):
        return None, issues, payload_field

    if node_type == "topic":
        issues.extend(
            _validate_required_payload_family(
                payload,
                required_fields=TOPIC_PAYLOAD_REQUIRED_FIELDS,
                forbidden_signature_fields=KC_PAYLOAD_REQUIRED_FIELDS,
                artifact=artifact,
                record_id=node_id or None,
                payload_family="Topic",
            )
        )
        if any(issue.level == "ERROR" for issue in issues):
            return None, issues, payload_field
        return (
            TopicNodeRecord(
                node_id=node_id,
                node_type="topic",
                source_id=source_id,
                title=title,
                parent_id=parent_id_raw,
                status=status,
                provenance_ref=dict(provenance_ref),
                payload=dict(payload),
            ),
            issues,
            payload_field,
        )

    issues.extend(
        _validate_required_payload_family(
            payload,
            required_fields=KC_PAYLOAD_REQUIRED_FIELDS,
            forbidden_signature_fields=TOPIC_PAYLOAD_REQUIRED_FIELDS,
            artifact=artifact,
            record_id=node_id or None,
            payload_family="KC",
        )
    )
    if any(issue.level == "ERROR" for issue in issues):
        return None, issues, payload_field
    return (
        KCNodeRecord(
            node_id=node_id,
            node_type="kc",
            source_id=source_id,
            title=title,
            parent_id=parent_id_raw,
            status=status,
            provenance_ref=dict(provenance_ref),
            payload=dict(payload),
        ),
        issues,
        payload_field,
    )


def normalize_edge_row(row: Mapping[str, Any], *, artifact: str) -> tuple[GraphEdgeRecord | None, list[ValidationIssue]]:
    issues: list[ValidationIssue] = []
    edge_id = _as_text(row.get("edge_id"))
    edge_type = _as_text(row.get("edge_type"))
    source_node_id = _as_text(row.get("source_node_id"))
    target_node_id = _as_text(row.get("target_node_id"))
    status = _as_text(row.get("status"))
    provenance_ref = row.get("provenance_ref")
    justification = _as_text(row.get("justification"))
    notes = _as_text(row.get("notes"))

    if edge_type not in ALLOWED_PILOT_EDGE_TYPES:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="INVALID_EDGE_TYPE",
                message=f"Invalid edge_type `{edge_type or '<missing>'}`.",
                artifact=artifact,
                record_id=edge_id or None,
            )
        )
    if not edge_id:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="MISSING_EDGE_ID",
                message="Edge is missing edge_id.",
                artifact=artifact,
            )
        )
    if not source_node_id or not target_node_id:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="MISSING_EDGE_ENDPOINT",
                message="Edge is missing source_node_id or target_node_id.",
                artifact=artifact,
                record_id=edge_id or None,
            )
        )
    if status not in ALLOWED_PILOT_EDGE_STATUSES:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="INVALID_EDGE_STATUS",
                message=f"Edge status `{status or '<missing>'}` is not in the allowed pilot set.",
                artifact=artifact,
                record_id=edge_id or None,
            )
        )
    if not _is_mapping(provenance_ref):
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="INVALID_EDGE_PROVENANCE_REF",
                message="Edge provenance_ref must be an object.",
                artifact=artifact,
                record_id=edge_id or None,
            )
        )
    if any(issue.level == "ERROR" for issue in issues):
        return None, issues
    return (
        GraphEdgeRecord(
            edge_id=edge_id,
            edge_type=edge_type,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            status=status,
            provenance_ref=dict(provenance_ref),
            justification=justification,
            notes=notes,
        ),
        issues,
    )


def _extract_single_int(pattern: re.Pattern[str], text: str) -> int | None:
    match = pattern.search(text)
    if not match:
        return None
    return int(match.group(1))


def _extract_pass_fail_int(pattern: re.Pattern[str], text: str) -> tuple[str, int] | None:
    match = pattern.search(text)
    if not match:
        return None
    return match.group(1), int(match.group(2))


def _validate_graph_validation_report(
    report_text: str,
    *,
    actual_counts: Mapping[str, int],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    report_counts = {
        "topic_nodes": _extract_single_int(TOPIC_COUNT_PATTERN, report_text),
        "kc_nodes": _extract_single_int(KC_COUNT_PATTERN, report_text),
        "topic_contains_topic_edges": _extract_single_int(TOPIC_EDGE_COUNT_PATTERN, report_text),
        "topic_contains_kc_edges": _extract_single_int(TOPIC_KC_EDGE_COUNT_PATTERN, report_text),
    }
    for key, value in report_counts.items():
        if value is None:
            issues.append(
                ValidationIssue(
                    level="ERROR",
                    code="MISSING_VALIDATION_REPORT_COUNT",
                    message=f"Graph validation report is missing `{key}`.",
                    artifact="graph_validation_report.md",
                )
            )
            continue
        if value != actual_counts[key]:
            issues.append(
                ValidationIssue(
                    level="ERROR",
                    code="GRAPH_VALIDATION_REPORT_COUNT_MISMATCH",
                    message=f"Graph validation report `{key}`={value} but actual count is {actual_counts[key]}.",
                    artifact="graph_validation_report.md",
                )
            )

    for label, pattern, expected in (
        ("excluded_topic_leaks", EXCLUDED_TOPIC_LEAK_PATTERN, 0),
        ("nonapproved_kc_leaks", NONAPPROVED_KC_LEAK_PATTERN, 0),
        ("node_collisions", NODE_COLLISION_PATTERN, 0),
        ("missing_edge_endpoints", MISSING_ENDPOINT_PATTERN, 0),
    ):
        extracted = _extract_pass_fail_int(pattern, report_text)
        if extracted is None:
            issues.append(
                ValidationIssue(
                    level="ERROR",
                    code="MISSING_VALIDATION_REPORT_CHECK",
                    message=f"Graph validation report is missing `{label}`.",
                    artifact="graph_validation_report.md",
                )
            )
            continue
        report_status, count = extracted
        if report_status != "PASS" or count != expected:
            issues.append(
                ValidationIssue(
                    level="ERROR",
                    code="GRAPH_VALIDATION_REPORT_STATUS_MISMATCH",
                    message=f"Graph validation report check `{label}` is {report_status} ({count}); expected PASS ({expected}).",
                    artifact="graph_validation_report.md",
                )
            )
    return issues


def validate_current_pilot_artifacts(
    *,
    topic_library_path: Path,
    topic_boundary_path: Path,
    kc_library_path: Path,
    kc_manifest_path: Path,
    graph_nodes_path: Path,
    graph_edges_path: Path,
    graph_manifest_path: Path,
    graph_validation_report_path: Path,
) -> KnowledgeLibraryValidationBundle:
    issues: list[ValidationIssue] = []

    topic_rows = _read_jsonl(topic_library_path)
    topic_boundary = _read_json(topic_boundary_path)
    kc_rows = _read_jsonl(kc_library_path)
    kc_manifest = _read_json(kc_manifest_path)
    graph_node_rows = _read_jsonl(graph_nodes_path)
    graph_edge_rows = _read_jsonl(graph_edges_path)
    graph_manifest = _read_json(graph_manifest_path)
    graph_validation_report = graph_validation_report_path.read_text(encoding="utf-8")

    resolved_topic_ids = {_as_text(row.get("topic_id")) for row in topic_rows}
    approved_kc_ids = {_as_text(row.get("kc_id")) for row in kc_rows}
    excluded_topic_ids = {
        _as_text(row.get("topic_id"))
        for row in topic_boundary.get("rescue_heavy_or_excluded_topics") or []
        if isinstance(row, Mapping)
    }
    included_kc_ids_from_manifest = set(kc_manifest.get("included_kc_ids") or [])

    expected_topic_count = int(topic_boundary.get("counts", {}).get("fully_resolved_reviewed_count") or 0)
    expected_kc_count = int(kc_manifest.get("counts", {}).get("approved_reviewed_entries_frozen") or 0)

    if len(topic_rows) != expected_topic_count:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="TOPIC_BOUNDARY_COUNT_MISMATCH",
                message=f"Resolved reviewed topic JSONL has {len(topic_rows)} rows; boundary expects {expected_topic_count}.",
                artifact=str(topic_library_path),
            )
        )
    if len(kc_rows) != expected_kc_count:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="KC_BOUNDARY_COUNT_MISMATCH",
                message=f"Approved KC JSONL has {len(kc_rows)} rows; manifest expects {expected_kc_count}.",
                artifact=str(kc_library_path),
            )
        )
    if approved_kc_ids != included_kc_ids_from_manifest:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="KC_MANIFEST_ID_SET_MISMATCH",
                message="Approved KC JSONL ids do not match included_kc_ids in the KC manifest.",
                artifact=str(kc_manifest_path),
            )
        )
    if resolved_topic_ids & excluded_topic_ids:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="EXCLUDED_TOPIC_IN_RESOLVED_BOUNDARY",
                message="An excluded topic appears in the resolved reviewed topic boundary.",
                artifact=str(topic_boundary_path),
            )
        )

    normalized_nodes: list[TopicNodeRecord | KCNodeRecord] = []
    payload_field_counts: Counter[str] = Counter()
    for row in graph_node_rows:
        normalized, node_issues, payload_field = normalize_node_row(row, artifact=str(graph_nodes_path))
        issues.extend(node_issues)
        if payload_field:
            payload_field_counts[payload_field] += 1
        if normalized is not None:
            normalized_nodes.append(normalized)

    normalized_edges: list[GraphEdgeRecord] = []
    for row in graph_edge_rows:
        normalized, edge_issues = normalize_edge_row(row, artifact=str(graph_edges_path))
        issues.extend(edge_issues)
        if normalized is not None:
            normalized_edges.append(normalized)

    node_lookup = {node.node_id: node for node in normalized_nodes}
    node_id_counts = Counter(node.node_id for node in normalized_nodes)
    duplicate_node_ids = sorted(node_id for node_id, count in node_id_counts.items() if count > 1)
    if duplicate_node_ids:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="DUPLICATE_NODE_ID",
                message=f"Duplicate node ids detected: {duplicate_node_ids}.",
                artifact=str(graph_nodes_path),
            )
        )

    edge_id_counts = Counter(edge.edge_id for edge in normalized_edges)
    duplicate_edge_ids = sorted(edge_id for edge_id, count in edge_id_counts.items() if count > 1)
    if duplicate_edge_ids:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="DUPLICATE_EDGE_ID",
                message=f"Duplicate edge ids detected: {duplicate_edge_ids}.",
                artifact=str(graph_edges_path),
            )
        )

    excluded_topic_node_leaks = 0
    nonapproved_kc_node_leaks = 0
    for node in normalized_nodes:
        if node.node_type == "topic":
            if node.source_id not in resolved_topic_ids:
                issues.append(
                    ValidationIssue(
                        level="ERROR",
                        code="TOPIC_NODE_OUTSIDE_RESOLVED_BOUNDARY",
                        message=f"Topic node source_id `{node.source_id}` is outside the resolved reviewed topic boundary.",
                        artifact=str(graph_nodes_path),
                        record_id=node.node_id,
                    )
                )
            if node.source_id in excluded_topic_ids:
                excluded_topic_node_leaks += 1
                issues.append(
                    ValidationIssue(
                        level="ERROR",
                        code="EXCLUDED_TOPIC_NODE_LEAK",
                        message=f"Excluded topic `{node.source_id}` leaked into graph nodes.",
                        artifact=str(graph_nodes_path),
                        record_id=node.node_id,
                    )
                )
            if node.parent_id is not None and node.parent_id not in node_lookup:
                issues.append(
                    ValidationIssue(
                        level="ERROR",
                        code="MISSING_TOPIC_PARENT_NODE",
                        message=f"Topic parent_id `{node.parent_id}` does not resolve to a graph node.",
                        artifact=str(graph_nodes_path),
                        record_id=node.node_id,
                    )
                )
        else:
            if node.source_id not in approved_kc_ids:
                nonapproved_kc_node_leaks += 1
                issues.append(
                    ValidationIssue(
                        level="ERROR",
                        code="KC_NODE_OUTSIDE_APPROVED_BOUNDARY",
                        message=f"KC node source_id `{node.source_id}` is outside the approved KC boundary.",
                        artifact=str(graph_nodes_path),
                        record_id=node.node_id,
                    )
                )

    for edge in normalized_edges:
        source_node = node_lookup.get(edge.source_node_id)
        target_node = node_lookup.get(edge.target_node_id)
        if source_node is None or target_node is None:
            issues.append(
                ValidationIssue(
                    level="ERROR",
                    code="EDGE_ENDPOINT_MISSING",
                    message=f"Edge `{edge.edge_id}` points to a missing node endpoint.",
                    artifact=str(graph_edges_path),
                    record_id=edge.edge_id,
                )
            )
            continue
        if edge.edge_type == "topic_contains_topic":
            if source_node.node_type != "topic" or target_node.node_type != "topic":
                issues.append(
                    ValidationIssue(
                        level="ERROR",
                        code="INVALID_TOPIC_CONTAINS_TOPIC_ENDPOINT_TYPES",
                        message="topic_contains_topic must connect topic -> topic.",
                        artifact=str(graph_edges_path),
                        record_id=edge.edge_id,
                    )
                )
            if target_node.parent_id and target_node.parent_id != edge.source_node_id:
                issues.append(
                    ValidationIssue(
                        level="ERROR",
                        code="TOPIC_HIERARCHY_EDGE_PARENT_MISMATCH",
                        message=(
                            f"topic_contains_topic edge source `{edge.source_node_id}` does not match "
                            f"target parent_id `{target_node.parent_id}`."
                        ),
                        artifact=str(graph_edges_path),
                        record_id=edge.edge_id,
                    )
                )
        elif edge.edge_type == "topic_contains_kc":
            if source_node.node_type != "topic" or target_node.node_type != "kc":
                issues.append(
                    ValidationIssue(
                        level="ERROR",
                        code="INVALID_TOPIC_CONTAINS_KC_ENDPOINT_TYPES",
                        message="topic_contains_kc must connect topic -> kc.",
                        artifact=str(graph_edges_path),
                        record_id=edge.edge_id,
                    )
                )

    actual_counts = {
        "topic_nodes": sum(1 for node in normalized_nodes if node.node_type == "topic"),
        "kc_nodes": sum(1 for node in normalized_nodes if node.node_type == "kc"),
        "topic_contains_topic_edges": sum(1 for edge in normalized_edges if edge.edge_type == "topic_contains_topic"),
        "topic_contains_kc_edges": sum(1 for edge in normalized_edges if edge.edge_type == "topic_contains_kc"),
    }

    manifest_counts = dict(graph_manifest.get("counts") or {})
    manifest_count_errors = 0
    for manifest_key, actual_key in (
        ("topic_nodes", "topic_nodes"),
        ("kc_nodes", "kc_nodes"),
        ("topic_contains_topic_edges", "topic_contains_topic_edges"),
        ("topic_contains_kc_edges", "topic_contains_kc_edges"),
    ):
        manifest_value = manifest_counts.get(manifest_key)
        if manifest_value != actual_counts[actual_key]:
            manifest_count_errors += 1
            issues.append(
                ValidationIssue(
                    level="ERROR",
                    code="GRAPH_MANIFEST_COUNT_MISMATCH",
                    message=(
                        f"Graph manifest count `{manifest_key}`={manifest_value} does not match "
                        f"actual value {actual_counts[actual_key]}."
                    ),
                    artifact=str(graph_manifest_path),
                )
            )

    emitted_edge_types = set(graph_manifest.get("construction_scope", {}).get("edge_types_emitted") or [])
    if emitted_edge_types != ALLOWED_PILOT_EDGE_TYPES:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="GRAPH_MANIFEST_EDGE_TYPE_SCOPE_MISMATCH",
                message=(
                    f"Graph manifest edge_types_emitted={sorted(emitted_edge_types)} does not match "
                    f"the allowed pilot edge types {sorted(ALLOWED_PILOT_EDGE_TYPES)}."
                ),
                artifact=str(graph_manifest_path),
            )
        )

    report_issues = _validate_graph_validation_report(graph_validation_report, actual_counts=actual_counts)
    issues.extend(report_issues)

    error_count = sum(1 for issue in issues if issue.level == "ERROR")
    warning_count = sum(1 for issue in issues if issue.level == "WARN")
    summary = {
        "schema_version": KNOWLEDGE_LIBRARY_VALIDATION_VERSION,
        "overall_status": "pass" if error_count == 0 else "fail",
        "issue_counts": {
            "error_count": error_count,
            "warning_count": warning_count,
            "total_issue_count": len(issues),
        },
        "source_boundary_counts": {
            "resolved_reviewed_topics": len(topic_rows),
            "approved_kcs": len(kc_rows),
            "excluded_topics": len(excluded_topic_ids),
        },
        "graph_counts": {
            **actual_counts,
            "total_nodes": len(normalized_nodes),
            "total_edges": len(normalized_edges),
        },
        "normalization": {
            "payload_field_counts": dict(payload_field_counts),
            "canonical_payload_field_count": payload_field_counts.get("payload", 0),
            "typed_payload_alias_count": payload_field_counts.get(RAW_TOPIC_PAYLOAD_FIELD, 0)
            + payload_field_counts.get(RAW_KC_PAYLOAD_FIELD, 0),
        },
        "boundary_checks": {
            "excluded_topics_in_graph_nodes": excluded_topic_node_leaks,
            "nonapproved_kcs_in_graph_nodes": nonapproved_kc_node_leaks,
        },
        "graph_manifest_consistency": {
            "graph_manifest_path": str(graph_manifest_path).replace("\\", "/"),
            "graph_validation_report_path": str(graph_validation_report_path).replace("\\", "/"),
            "manifest_count_error_count": manifest_count_errors,
            "report_error_count": len(report_issues),
            "counts_match_actual_rows": manifest_count_errors == 0 and not report_issues,
        },
    }
    return KnowledgeLibraryValidationBundle(
        normalized_nodes=tuple(normalized_nodes),
        normalized_edges=tuple(normalized_edges),
        issues=tuple(issues),
        summary=summary,
    )
