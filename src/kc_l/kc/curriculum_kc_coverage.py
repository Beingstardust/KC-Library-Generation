from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kc_l.utils.json_io import write_json, write_jsonl


REPO_ROOT = Path(__file__).resolve().parents[3]

CURRICULUM_KC_COVERAGE_STAGE = "step6_8_curriculum_kc_coverage_representation"
CURRICULUM_KC_COVERAGE_RULE_VERSION = "step6.coverage_representation.v1"
CURRICULUM_KC_COVERAGE_SCHEMA_VERSION = "1.0"

REPRESENTATION_TIER_APPROVED = "approved_frozen_usable_library"
REPRESENTATION_TIER_REVIEW_READY = "review_ready_packet"
REPRESENTATION_TIER_COVERAGE_ONLY = "coverage_complete_curriculum_only"

APPROVED_FROZEN_LIBRARY_TIER = "frozen_reviewed_library"
APPROVED_REVIEW_STATUSES = {"approved", "edited_approved"}


@dataclass(frozen=True)
class CurriculumKCCoverageResult:
    output_dir: Path
    manifest_path: Path
    summary_path: Path
    represented_count: int
    missing_count: int


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_string_list(values: Any) -> list[str]:
    out: list[str] = []
    for value in values or []:
        text = _as_text(value)
        if text and text not in out:
            out.append(text)
    return out


def _relative_repo_path(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path.resolve())


def _mapping_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _field_hold_reasons(payload: Any) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for key, raw_values in _mapping_dict(payload).items():
        values = _normalize_string_list(raw_values)
        if values:
            out[_as_text(key)] = values
    return out


def _drafting_state(draft_row: Mapping[str, Any] | None) -> dict[str, Any]:
    if draft_row is None:
        return {
            "status": "missing_from_step6_7_surface",
            "support_state": "unknown",
            "hold_reasons": [],
            "field_hold_reasons": {},
            "definition_short_status": "missing",
            "definition_short_available": False,
            "scope_status": "missing",
            "evidence_bundle_size": 0,
            "source_run_id": "",
            "source_set_id": "",
        }

    support_summary = _mapping_dict(draft_row.get("support_summary"))
    definition_short = _mapping_dict(draft_row.get("definition_short_candidate"))
    scope_candidate = _mapping_dict(draft_row.get("scope_candidate"))
    evidence_bundle = draft_row.get("evidence_bundle") or []
    return {
        "status": _as_text(draft_row.get("draft_status")) or "unknown",
        "support_state": _as_text(support_summary.get("support_state")) or "unknown",
        "hold_reasons": _normalize_string_list(draft_row.get("hold_reasons")),
        "field_hold_reasons": _field_hold_reasons(draft_row.get("field_hold_reasons")),
        "definition_short_status": _as_text(definition_short.get("status")) or "missing",
        "definition_short_available": _as_text(definition_short.get("status")) == "grounded"
        and bool(_as_text(definition_short.get("text"))),
        "scope_status": _as_text(scope_candidate.get("status")) or "missing",
        "evidence_bundle_size": len(evidence_bundle) if isinstance(evidence_bundle, Sequence) else 0,
        "source_run_id": _as_text(draft_row.get("source_run_id")),
        "source_set_id": _as_text(draft_row.get("source_set_id")),
    }


def _review_lane_state(
    *,
    kc_id: str,
    ready_packets: Mapping[str, Mapping[str, Any]],
    quarantined_packets: Mapping[str, Mapping[str, Any]],
    excluded_packets: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    if kc_id in ready_packets:
        packet = dict(ready_packets[kc_id])
        return {
            "status": "review_ready",
            "packet_state": _as_text(packet.get("packet_state")) or "review_ready",
            "review_packet_id": _as_text(packet.get("review_packet_id")),
            "review_priority_bucket": _as_text(_mapping_dict(packet.get("review_priority")).get("bucket")),
            "system_recommendation": _as_text(_mapping_dict(packet.get("system_recommendation")).get("label")),
            "scope_status": _as_text(packet.get("scope_status")),
            "reasons": [],
            "risk_flags": _normalize_string_list(packet.get("risk_flags")),
        }

    if kc_id in quarantined_packets:
        item = dict(quarantined_packets[kc_id])
        return {
            "status": "quarantined",
            "packet_state": "quarantined",
            "review_packet_id": "",
            "review_priority_bucket": "",
            "system_recommendation": "",
            "scope_status": _as_text(item.get("scope_status")),
            "reasons": _normalize_string_list(item.get("reasons")),
            "risk_flags": _normalize_string_list(item.get("risk_flags")),
        }

    if kc_id in excluded_packets:
        item = dict(excluded_packets[kc_id])
        return {
            "status": "excluded",
            "packet_state": "excluded",
            "review_packet_id": "",
            "review_priority_bucket": "",
            "system_recommendation": "",
            "scope_status": "",
            "reasons": _normalize_string_list(item.get("reasons")),
            "risk_flags": [],
        }

    return {
        "status": "not_emitted",
        "packet_state": "not_emitted",
        "review_packet_id": "",
        "review_priority_bucket": "",
        "system_recommendation": "",
        "scope_status": "",
        "reasons": [],
        "risk_flags": [],
    }


def _approved_frozen_state(
    *,
    kc_id: str,
    approved_rows: Mapping[str, Mapping[str, Any]],
    approved_source_path: Path | None,
) -> dict[str, Any]:
    row = dict(approved_rows.get(kc_id) or {})
    if not row:
        status = "not_available_in_repo" if approved_source_path is None else "not_in_frozen_library"
        return {
            "status": status,
            "approved_frozen_usable": False,
            "review_status": "",
            "source_library_tier": "",
            "source_artifact": _relative_repo_path(approved_source_path),
        }

    review_status = _as_text(row.get("review_status"))
    source_library_tier = _as_text(row.get("library_tier"))
    approved_usable = source_library_tier == APPROVED_FROZEN_LIBRARY_TIER and review_status in APPROVED_REVIEW_STATUSES
    return {
        "status": "approved_frozen" if approved_usable else "present_non_operational",
        "approved_frozen_usable": approved_usable,
        "review_status": review_status,
        "source_library_tier": source_library_tier,
        "source_artifact": _relative_repo_path(approved_source_path),
    }


def _representation_tier(
    *,
    review_lane_state: Mapping[str, Any],
    approved_frozen_state: Mapping[str, Any],
) -> str:
    if bool(approved_frozen_state.get("approved_frozen_usable")):
        return REPRESENTATION_TIER_APPROVED
    if _as_text(review_lane_state.get("status")) == "review_ready":
        return REPRESENTATION_TIER_REVIEW_READY
    return REPRESENTATION_TIER_COVERAGE_ONLY


def _coverage_row(
    *,
    registry_row: Mapping[str, Any],
    ancestry_row: Mapping[str, Any] | None,
    draft_row: Mapping[str, Any] | None,
    review_lane_state: Mapping[str, Any],
    approved_frozen_state: Mapping[str, Any],
    step1_registry_path: Path,
    step1_5_overlay_manifest_path: Path,
    step6_6_set_id: str,
    step6_7_set_id: str,
    step6_8_run_id: str,
) -> dict[str, Any]:
    kc_id = _as_text(registry_row.get("kc_id"))
    representation_tier = _representation_tier(
        review_lane_state=review_lane_state,
        approved_frozen_state=approved_frozen_state,
    )
    ancestry = _mapping_dict(ancestry_row)
    return {
        "schema_version": CURRICULUM_KC_COVERAGE_SCHEMA_VERSION,
        "stage": CURRICULUM_KC_COVERAGE_STAGE,
        "rule_version": CURRICULUM_KC_COVERAGE_RULE_VERSION,
        "kc_id": kc_id,
        "canonical_name": _as_text(registry_row.get("canonical_name")),
        "aliases": _normalize_string_list(registry_row.get("aliases")),
        "level": "atomic",
        "curriculum_source": {
            "step1_registry_jsonl": _relative_repo_path(step1_registry_path),
            "step1_5_overlay_manifest_json": _relative_repo_path(step1_5_overlay_manifest_path),
            "kc_path": _normalize_string_list(registry_row.get("kc_path")),
            "seed_definition": _as_text(registry_row.get("seed_definition")),
            "source_hierarchy_path": _normalize_string_list(ancestry.get("source_hierarchy_path")),
            "ancestor_labels": _normalize_string_list(ancestry.get("ancestor_labels")),
            "ancestor_hier_node_ids": _normalize_string_list(ancestry.get("ancestor_hier_node_ids")),
            "leaf_hier_node_id": _as_text(ancestry.get("leaf_hier_node_id")),
            "parent_hier_node_id": _as_text(ancestry.get("parent_hier_node_id")),
        },
        "source_sets": {
            "step6_6_set_id": step6_6_set_id,
            "step6_7_set_id": step6_7_set_id,
            "step6_8_run_id": step6_8_run_id,
        },
        "drafting_state": _drafting_state(draft_row),
        "review_lane_state": dict(review_lane_state),
        "approved_frozen_state": dict(approved_frozen_state),
        "representation_tier": representation_tier,
        "segmentation_eligible": True,
        "segmentation_eligibility_tier": representation_tier,
        "evaluation_eligible": True,
        "evaluation_eligibility_tier": representation_tier,
        "eligibility_note": (
            "This row preserves curriculum existence for lower-trust downstream fallback. "
            "It does not promote the KC into the approved frozen usable library."
        ),
        "kc_specific_criteria": "",
    }


def _summary(
    *,
    expected_kc_ids: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
    ready_packets: Sequence[Mapping[str, Any]],
    review_summary: Mapping[str, Any],
    step1_registry_path: Path,
    step1_5_overlay_manifest_path: Path,
    approved_source_path: Path | None,
) -> dict[str, Any]:
    represented_kc_ids = [_as_text(row.get("kc_id")) for row in rows if _as_text(row.get("kc_id"))]
    represented_kc_id_set = set(represented_kc_ids)
    missing_kc_ids = [kc_id for kc_id in expected_kc_ids if kc_id not in represented_kc_id_set]

    representation_tier_counts = Counter(_as_text(row.get("representation_tier")) for row in rows)
    drafting_state_counts = Counter(
        _as_text(_mapping_dict(row.get("drafting_state")).get("status")) for row in rows
    )
    review_lane_state_counts = Counter(
        _as_text(_mapping_dict(row.get("review_lane_state")).get("status")) for row in rows
    )
    approved_frozen_state_counts = Counter(
        _as_text(_mapping_dict(row.get("approved_frozen_state")).get("status")) for row in rows
    )
    review_priority_counts = Counter(
        _as_text(_mapping_dict(row.get("review_lane_state")).get("review_priority_bucket"))
        for row in rows
        if _as_text(_mapping_dict(row.get("review_lane_state")).get("review_priority_bucket"))
    )
    recommendation_counts = Counter(
        _as_text(_mapping_dict(row.get("review_lane_state")).get("system_recommendation"))
        for row in rows
        if _as_text(_mapping_dict(row.get("review_lane_state")).get("system_recommendation"))
    )
    criteria_ok = all("kc_specific_criteria" in row and not _as_text(row.get("kc_specific_criteria")) for row in rows)

    return {
        "schema_version": CURRICULUM_KC_COVERAGE_SCHEMA_VERSION,
        "stage": CURRICULUM_KC_COVERAGE_STAGE,
        "rule_version": CURRICULUM_KC_COVERAGE_RULE_VERSION,
        "representation_layer_note": (
            "This manifest preserves one row per Step 1 atomic curriculum KC regardless of review readiness. "
            "It is a parallel coverage layer, not a relaxed approved-library boundary."
        ),
        "fallback_preference_order": [
            REPRESENTATION_TIER_APPROVED,
            REPRESENTATION_TIER_REVIEW_READY,
            REPRESENTATION_TIER_COVERAGE_ONLY,
        ],
        "approved_frozen_boundary_mode": "parallel_not_modified",
        "approved_frozen_artifact_present_in_repo": approved_source_path is not None,
        "approved_frozen_source_artifact": _relative_repo_path(approved_source_path),
        "step1_registry_jsonl": _relative_repo_path(step1_registry_path),
        "step1_5_overlay_manifest_json": _relative_repo_path(step1_5_overlay_manifest_path),
        "total_curriculum_atomic_kc_count": len(expected_kc_ids),
        "represented_kc_count": len(represented_kc_ids),
        "missing_kc_count": len(missing_kc_ids),
        "missing_kc_ids": missing_kc_ids,
        "representation_tier_counts": dict(representation_tier_counts),
        "drafting_state_counts": dict(drafting_state_counts),
        "review_lane_state_counts": dict(review_lane_state_counts),
        "approved_frozen_state_counts": dict(approved_frozen_state_counts),
        "review_priority_counts": dict(review_priority_counts),
        "system_recommendation_counts": dict(recommendation_counts),
        "ready_packet_count": len(ready_packets),
        "quarantine_count": int(review_summary.get("quarantine_count") or 0),
        "excluded_count": len(review_summary.get("excluded_kcs") or []),
        "segmentation_eligible_count": sum(1 for row in rows if bool(row.get("segmentation_eligible"))),
        "evaluation_eligible_count": sum(1 for row in rows if bool(row.get("evaluation_eligible"))),
        "kc_specific_criteria_present_and_empty": criteria_ok,
    }


def emit_curriculum_kc_coverage_manifest(
    *,
    output_dir: Path,
    registry_rows: Sequence[Mapping[str, Any]],
    ancestry_by_kc_id: Mapping[str, Any],
    draft_rows: Sequence[Mapping[str, Any]],
    ready_packets: Sequence[Mapping[str, Any]],
    review_summary: Mapping[str, Any],
    step1_registry_path: Path,
    step1_5_overlay_manifest_path: Path,
    step6_6_set_id: str,
    step6_7_set_id: str,
    step6_8_run_id: str,
    approved_rows: Sequence[Mapping[str, Any]] | None = None,
    approved_source_path: Path | None = None,
) -> CurriculumKCCoverageResult:
    draft_by_kc = {
        _as_text(row.get("kc_id")): dict(row)
        for row in draft_rows
        if _as_text(row.get("kc_id"))
    }
    ready_by_kc = {
        _as_text(packet.get("kc_candidate_id")): dict(packet)
        for packet in ready_packets
        if _as_text(packet.get("kc_candidate_id"))
    }
    quarantined_by_kc = {
        _as_text(item.get("kc_candidate_id")): dict(item)
        for item in review_summary.get("quarantined_kcs") or []
        if isinstance(item, Mapping) and _as_text(item.get("kc_candidate_id"))
    }
    excluded_by_kc = {
        _as_text(item.get("kc_candidate_id")): dict(item)
        for item in review_summary.get("excluded_kcs") or []
        if isinstance(item, Mapping) and _as_text(item.get("kc_candidate_id"))
    }
    approved_by_kc = {
        _as_text(row.get("kc_id")): dict(row)
        for row in approved_rows or []
        if _as_text(row.get("kc_id"))
    }

    rows: list[dict[str, Any]] = []
    expected_kc_ids: list[str] = []
    for registry_row in registry_rows:
        kc_id = _as_text(registry_row.get("kc_id"))
        if not kc_id:
            continue
        expected_kc_ids.append(kc_id)
        review_lane_state = _review_lane_state(
            kc_id=kc_id,
            ready_packets=ready_by_kc,
            quarantined_packets=quarantined_by_kc,
            excluded_packets=excluded_by_kc,
        )
        approved_frozen_state = _approved_frozen_state(
            kc_id=kc_id,
            approved_rows=approved_by_kc,
            approved_source_path=approved_source_path,
        )
        rows.append(
            _coverage_row(
                registry_row=registry_row,
                ancestry_row=_mapping_dict(ancestry_by_kc_id.get(kc_id)),
                draft_row=draft_by_kc.get(kc_id),
                review_lane_state=review_lane_state,
                approved_frozen_state=approved_frozen_state,
                step1_registry_path=step1_registry_path,
                step1_5_overlay_manifest_path=step1_5_overlay_manifest_path,
                step6_6_set_id=step6_6_set_id,
                step6_7_set_id=step6_7_set_id,
                step6_8_run_id=step6_8_run_id,
            )
        )

    summary = _summary(
        expected_kc_ids=expected_kc_ids,
        rows=rows,
        ready_packets=ready_packets,
        review_summary=review_summary,
        step1_registry_path=step1_registry_path,
        step1_5_overlay_manifest_path=step1_5_overlay_manifest_path,
        approved_source_path=approved_source_path,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "curriculum_kc_coverage_manifest.jsonl"
    summary_path = output_dir / "curriculum_kc_coverage_summary.json"
    write_jsonl(manifest_path, rows)
    write_json(summary_path, summary)
    return CurriculumKCCoverageResult(
        output_dir=output_dir,
        manifest_path=manifest_path,
        summary_path=summary_path,
        represented_count=int(summary["represented_kc_count"]),
        missing_count=int(summary["missing_kc_count"]),
    )
