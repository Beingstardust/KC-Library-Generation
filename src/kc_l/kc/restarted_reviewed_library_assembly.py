from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kc_l.kc_drafting.hierarchy_refs import typed_topic_hierarchy_fields
from kc_l.kc.downstream_library import validate_downstream_kc_entry
from kc_l.utils.json_io import read_jsonl, write_json, write_jsonl


RESTARTED_REVIEWED_LIBRARY_ASSEMBLY_STAGE = "step6_11_reviewed_library_assembly"
RESTARTED_REVIEWED_LIBRARY_ASSEMBLY_RULE_VERSION = "step6.11.reviewed_library_assembly_restarted.v1"
RESTARTED_REVIEWED_LIBRARY_CONTENT_SOURCE_MODE = "restarted_review_resolved_primary"
FROZEN_LIBRARY_TIER = "frozen_reviewed_library"
SANDBOX_LIBRARY_TIER = "kc_review_sandbox"
APPROVED_STATUS = "approved"
EDITED_APPROVED_STATUS = "edited_approved"
REJECTED_STATUS = "rejected"
SKIPPED_BEFORE_REVIEW_STATUS = "skipped_before_review"
REJECTED_AFTER_REVIEW_STATUS = "rejected_after_review"
EXCLUDED_FROM_READY_SET_STATUS = "excluded_from_bounded_review_ready_set"


@dataclass(frozen=True)
class RestartedReviewedLibraryAssemblyResult:
    frozen_output_dir: Path
    frozen_library_path: Path
    reviewed_summary_path: Path
    reviewed_preview_path: Path
    sandbox_output_dir: Path
    sandbox_path: Path
    sandbox_summary_path: Path
    frozen_count: int
    sandbox_count: int


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _ensure(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _normalize_string_list(values: Any) -> list[str]:
    out: list[str] = []
    for value in values or []:
        text = _as_text(value)
        if text and text not in out:
            out.append(text)
    return out


def _unique_doc_ids_from_packet(packet: Mapping[str, Any]) -> list[str]:
    source_provenance = dict(packet.get("source_provenance") or {})
    out = _normalize_string_list(source_provenance.get("source_document_ids"))
    if out:
        return out
    for span in packet.get("evidence_spans") or []:
        if not isinstance(span, Mapping):
            continue
        doc_id = _as_text(span.get("doc_id"))
        if doc_id and doc_id not in out:
            out.append(doc_id)
    return out


def _unique_doc_ids_from_draft(draft: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for item in draft.get("evidence_bundle") or []:
        if not isinstance(item, Mapping):
            continue
        doc_id = _as_text(item.get("doc_id"))
        if doc_id and doc_id not in out:
            out.append(doc_id)
    return out


def _mapping_or_empty(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _draft_hierarchy_fields(draft: Mapping[str, Any]) -> dict[str, Any]:
    hierarchy_fields = typed_topic_hierarchy_fields(draft)
    return {
        "topic_path_ids": list(hierarchy_fields.get("topic_path_ids") or []),
        "topic_path_labels": list(hierarchy_fields.get("topic_path_labels") or []),
        "parent_topic_id": hierarchy_fields.get("parent_topic_id"),
        "parent_topic_label": hierarchy_fields.get("parent_topic_label"),
        "ancestor_topic_ids": list(hierarchy_fields.get("ancestor_topic_ids") or []),
        "ancestor_topic_labels": list(hierarchy_fields.get("ancestor_topic_labels") or []),
        "hierarchy_ancestry": dict(hierarchy_fields.get("hierarchy_ancestry") or {}),
    }


def _stage_lineage(*, lineage: Mapping[str, Any], include_review_stages: bool) -> dict[str, Any]:
    base = {
        "step4": {
            "set_id": _as_text(lineage.get("step4_set_id")),
        },
        "step4_5": {
            "set_id": _as_text(lineage.get("step4_5_set_id")),
        },
        "step5_3": {
            "set_id": _as_text(lineage.get("step5_set_id")),
        },
        "step6_6": {
            "set_id": _as_text(lineage.get("step6_6_set_id")),
            "run_id": _as_text(lineage.get("step6_6_run_id")),
        },
        "step6_7": {
            "set_id": _as_text(lineage.get("step6_7_set_id")),
            "run_id": _as_text(lineage.get("step6_7_run_id")),
        },
        "step6_8": {
            "set_id": _as_text(lineage.get("step6_8_set_id")),
            "run_id": _as_text(lineage.get("step6_8_run_id")),
        },
    }
    if include_review_stages:
        base["step6_9"] = {
            "set_id": _as_text(lineage.get("step6_9_set_id")),
            "run_id": _as_text(lineage.get("step6_9_run_id")),
        }
        base["step6_10"] = {
            "set_id": _as_text(lineage.get("step6_10_set_id")),
            "run_id": _as_text(lineage.get("step6_10_run_id")),
        }
    else:
        base["step6_9"] = None
        base["step6_10"] = None
    return base


def _build_final_field_provenance(
    *,
    event: Mapping[str, Any],
    final_text: Mapping[str, Any],
    intentionally_blank_fields: set[str],
) -> dict[str, Any]:
    kc_id = _as_text(event.get("kc_candidate_id"))
    field_linked = _mapping_or_empty(event.get("field_linked_evidence_ids"))
    definition_ids = _normalize_string_list(field_linked.get("definition"))
    scope_ids = _normalize_string_list(field_linked.get("scope"))
    scope_blank_intentional = f"{kc_id}.scope" in intentionally_blank_fields
    scope_value = final_text.get("scope")
    scope_status = "grounded"
    if scope_value is None and scope_blank_intentional:
        scope_status = "intentionally_blank"
    elif scope_value is None:
        scope_status = "missing"
    return {
        "title": {
            "source": "resolved_review_audit.final_text.title",
            "linked_evidence_ids": [],
            "status": "resolved_text",
        },
        "level": {
            "source": "resolved_review_audit.final_text.level",
            "linked_evidence_ids": [],
            "status": "resolved_text",
        },
        "definition": {
            "source": "resolved_review_audit.final_text.definition",
            "linked_evidence_ids": definition_ids,
            "status": "grounded" if _as_text(final_text.get("definition")) else "missing",
        },
        "scope": {
            "source": "resolved_review_audit.final_text.scope",
            "linked_evidence_ids": scope_ids,
            "status": scope_status,
            "intentionally_blank": scope_blank_intentional,
        },
    }


def build_frozen_reviewed_entry(
    *,
    event: Mapping[str, Any],
    packet: Mapping[str, Any],
    draft: Mapping[str, Any],
    assembly_run_id: str,
    lineage: Mapping[str, Any],
    intentionally_blank_fields: set[str],
) -> dict[str, Any]:
    kc_id = _as_text(event.get("kc_candidate_id"))
    final_status = _as_text(event.get("final_status"))
    _ensure(final_status in {APPROVED_STATUS, EDITED_APPROVED_STATUS}, f"Unsupported frozen final status for {kc_id}: {final_status}")

    final_text = _mapping_or_empty(event.get("final_text"))
    title = _as_text(final_text.get("title")) or _as_text(packet.get("title_draft")) or _as_text(draft.get("canonical_name"))
    level = _as_text(final_text.get("level")) or _as_text(packet.get("level_draft")) or "atomic"
    definition = _as_text(final_text.get("definition"))
    scope_value = final_text.get("scope")
    scope_blank_intentional = f"{kc_id}.scope" in intentionally_blank_fields

    packet_source_provenance = _mapping_or_empty(packet.get("source_provenance"))
    hierarchy_fields = _draft_hierarchy_fields(draft)
    source_provenance = {
        "assembly_stage": RESTARTED_REVIEWED_LIBRARY_ASSEMBLY_STAGE,
        "assembly_run_id": assembly_run_id,
        "packet_source_provenance": packet_source_provenance,
        "source_stage_lineage": {
            **_stage_lineage(lineage=lineage, include_review_stages=True),
            "review_packet_id": _as_text(event.get("review_packet_id")),
            "review_event_id": _as_text(event.get("review_event_id")),
        },
        "source_document_ids": _unique_doc_ids_from_packet(packet),
    }

    entry = {
        "status": final_status,
        "final_decision_status": final_status,
        "library_tier": FROZEN_LIBRARY_TIER,
        "review_status": final_status,
        "source_run_id": _as_text(lineage.get("step6_10_run_id")),
        "assembly_run_id": assembly_run_id,
        "kc_id": kc_id,
        "canonical_name": _as_text(draft.get("canonical_name")) or title,
        "aliases": list(draft.get("aliases") or []),
        "authoritative_definition_status": _as_text(packet.get("authoritative_definition_status")) or _as_text(draft.get("authoritative_definition_status")),
        **hierarchy_fields,
        "title": title,
        "level": level,
        "reviewer_facing_definition": definition,
        "reviewer_facing_scope": scope_value,
        "scope_status": "intentionally_blank" if scope_blank_intentional else ("grounded" if _as_text(scope_value) else "missing"),
        "scope_blank_is_intentional": scope_blank_intentional,
        "final_text": dict(final_text),
        "edited_fields": list(event.get("edited_fields") or []),
        "review_packet_id": _as_text(event.get("review_packet_id")),
        "review_event_id": _as_text(event.get("review_event_id")),
        "review_mode": _as_text(event.get("review_mode")),
        "review_notes": _as_text(event.get("review_notes")),
        "evidence_spans": list(packet.get("evidence_spans") or []),
        "source_provenance": source_provenance,
        "risk_flags": list(packet.get("risk_flags") or []),
        "review_priority": _mapping_or_empty(packet.get("review_priority")),
        "system_recommendation": _mapping_or_empty(packet.get("system_recommendation")),
        "content_source_mode": RESTARTED_REVIEWED_LIBRARY_CONTENT_SOURCE_MODE,
        "field_provenance_map": _mapping_or_empty(packet.get("field_provenance_map")),
        "final_field_provenance": _build_final_field_provenance(
            event=event,
            final_text=final_text,
            intentionally_blank_fields=intentionally_blank_fields,
        ),
        "field_linked_evidence_ids": dict(event.get("field_linked_evidence_ids") or {}),
        "linked_evidence_ids": list(event.get("linked_evidence_ids") or []),
        "draft_status_at_review": _as_text(packet.get("draft_status")),
        "draft_hold_reasons_at_review": list(packet.get("draft_hold_reasons") or []),
        "notes_for_reviewer": _as_text(packet.get("notes_for_reviewer")),
    }
    validate_downstream_kc_entry(entry, expected_tier=FROZEN_LIBRARY_TIER, operational_use=False)
    return entry

def build_rejected_sandbox_entry(
    *,
    event: Mapping[str, Any],
    packet: Mapping[str, Any],
    draft: Mapping[str, Any],
    assembly_run_id: str,
    lineage: Mapping[str, Any],
) -> dict[str, Any]:
    kc_id = _as_text(event.get("kc_candidate_id"))
    current_packet_text = _mapping_or_empty(event.get("current_packet_text"))
    final_text = _mapping_or_empty(event.get("final_text"))
    title = _as_text(current_packet_text.get("title")) or _as_text(packet.get("title_draft")) or _as_text(draft.get("canonical_name")) or kc_id
    level = _as_text(current_packet_text.get("level")) or _as_text(packet.get("level_draft")) or "atomic"

    packet_source_provenance = _mapping_or_empty(packet.get("source_provenance"))
    hierarchy_fields = _draft_hierarchy_fields(draft)
    source_provenance = {
        "assembly_stage": RESTARTED_REVIEWED_LIBRARY_ASSEMBLY_STAGE,
        "assembly_run_id": assembly_run_id,
        "packet_source_provenance": packet_source_provenance,
        "source_stage_lineage": {
            **_stage_lineage(lineage=lineage, include_review_stages=True),
            "review_packet_id": _as_text(event.get("review_packet_id")),
            "review_event_id": _as_text(event.get("review_event_id")),
        },
        "source_document_ids": _unique_doc_ids_from_packet(packet),
    }

    entry = {
        "status": REJECTED_AFTER_REVIEW_STATUS,
        "final_decision_status": REJECTED_STATUS,
        "library_tier": SANDBOX_LIBRARY_TIER,
        "review_status": REJECTED_STATUS,
        "source_run_id": _as_text(lineage.get("step6_10_run_id")),
        "assembly_run_id": assembly_run_id,
        "kc_id": kc_id,
        "canonical_name": _as_text(draft.get("canonical_name")) or title,
        "aliases": list(draft.get("aliases") or []),
        "authoritative_definition_status": _as_text(packet.get("authoritative_definition_status")) or _as_text(draft.get("authoritative_definition_status")),
        **hierarchy_fields,
        "title": title,
        "level": level,
        "reviewer_facing_definition": _as_text(current_packet_text.get("definition")),
        "reviewer_facing_scope": current_packet_text.get("scope"),
        "scope_status": _as_text(event.get("scope_status_at_review")) or ("grounded" if _as_text(current_packet_text.get("scope")) else "missing"),
        "current_packet_text": current_packet_text,
        "final_text": final_text,
        "edited_fields": list(event.get("edited_fields") or []),
        "rejection_reason": _as_text(event.get("rejection_reason")),
        "review_packet_id": _as_text(event.get("review_packet_id")),
        "review_event_id": _as_text(event.get("review_event_id")),
        "review_mode": _as_text(event.get("review_mode")),
        "review_notes": _as_text(event.get("review_notes")),
        "evidence_spans": list(packet.get("evidence_spans") or []),
        "source_provenance": source_provenance,
        "risk_flags": list(packet.get("risk_flags") or []),
        "review_priority": _mapping_or_empty(packet.get("review_priority")),
        "system_recommendation": _mapping_or_empty(packet.get("system_recommendation")),
        "content_source_mode": RESTARTED_REVIEWED_LIBRARY_CONTENT_SOURCE_MODE,
        "field_provenance_map": _mapping_or_empty(packet.get("field_provenance_map")),
        "field_linked_evidence_ids": dict(event.get("field_linked_evidence_ids") or {}),
        "linked_evidence_ids": list(event.get("linked_evidence_ids") or []),
        "draft_status_at_review": _as_text(packet.get("draft_status")),
        "draft_hold_reasons_at_review": list(packet.get("draft_hold_reasons") or []),
        "reason": {
            "skip_category": "rejected_during_restarted_review",
            "rejection_reason": _as_text(event.get("rejection_reason")),
            "packet_sufficiency": _as_text(event.get("packet_sufficiency")),
            "packet_alone_sufficient": bool(event.get("packet_alone_sufficient")),
            "raw_internals_reopened": bool(event.get("raw_internals_reopened")),
            "current_risk_flags": list(event.get("current_risk_flags") or []),
            "excluded_from_frozen_reviewed_library": True,
            "source_exclusion_stage": RESTARTED_REVIEWED_LIBRARY_ASSEMBLY_STAGE,
        },
    }
    validate_downstream_kc_entry(entry, expected_tier=SANDBOX_LIBRARY_TIER, operational_use=False)
    return entry


def build_excluded_sandbox_entry(
    *,
    excluded_case: Mapping[str, Any],
    draft: Mapping[str, Any],
    assembly_run_id: str,
    lineage: Mapping[str, Any],
) -> dict[str, Any]:
    kc_id = _as_text(excluded_case.get("kc_candidate_id"))
    title = _as_text(draft.get("canonical_name")) or kc_id
    reason_codes = _normalize_string_list(excluded_case.get("reasons"))
    hierarchy_fields = _draft_hierarchy_fields(draft)

    source_provenance = {
        "assembly_stage": RESTARTED_REVIEWED_LIBRARY_ASSEMBLY_STAGE,
        "assembly_run_id": assembly_run_id,
        "source_stage_lineage": {
            **_stage_lineage(lineage=lineage, include_review_stages=False),
            "excluded_before_review_audit": True,
            "source_packet_exclusion_stage": "step6_8_restarted_review_packet_emission",
        },
        "draft_input_overlay_set_id": _as_text(draft.get("draft_input_overlay_set_id")),
        "step5_source_set_id": _as_text(draft.get("source_set_id")),
        "step5_source_run_id": _as_text(draft.get("source_run_id")),
        "source_document_ids": _unique_doc_ids_from_draft(draft),
    }

    entry = {
        "status": EXCLUDED_FROM_READY_SET_STATUS,
        "final_decision_status": "excluded_before_review",
        "library_tier": SANDBOX_LIBRARY_TIER,
        "review_status": SKIPPED_BEFORE_REVIEW_STATUS,
        "source_run_id": _as_text(lineage.get("step6_8_run_id")),
        "assembly_run_id": assembly_run_id,
        "kc_id": kc_id,
        "canonical_name": title,
        "aliases": list(draft.get("aliases") or []),
        "authoritative_definition_status": _as_text(draft.get("authoritative_definition_status")),
        **hierarchy_fields,
        "title": title,
        "level": "atomic",
        "draft_status": _as_text(excluded_case.get("draft_status")) or _as_text(draft.get("draft_status")),
        "hold_reasons": list(draft.get("hold_reasons") or []),
        "contamination_flags": list(draft.get("contamination_flags") or []),
        "evidence_bundle": list(draft.get("evidence_bundle") or []),
        "reason": {
            "summary_skip_reasons": reason_codes,
            "skip_category": "held_excluded_from_restarted_ready_packet_set",
            "draft_status": _as_text(excluded_case.get("draft_status")) or _as_text(draft.get("draft_status")),
            "excluded_from_review_ready_packetization": True,
            "source_exclusion_stage": "step6_8_restarted_review_packet_emission",
        },
        "source_provenance": source_provenance,
    }
    validate_downstream_kc_entry(entry, expected_tier=SANDBOX_LIBRARY_TIER, operational_use=False)
    return entry


def build_reviewed_library_summary(
    *,
    frozen_entries: Sequence[Mapping[str, Any]],
    rejected_entries: Sequence[Mapping[str, Any]],
    intentionally_blank_fields: Sequence[str],
    excluded_cases: Sequence[Mapping[str, Any]],
    contract_validation_failures: Sequence[str],
) -> dict[str, Any]:
    final_status_counts = Counter(_as_text(item.get("review_status")) for item in frozen_entries)
    missing_lineage = [
        entry.get("kc_id")
        for entry in frozen_entries
        if not _as_text((((entry.get("source_provenance") or {}).get("source_stage_lineage") or {}).get("step6_7") or {}).get("set_id"))
        or not _as_text((((entry.get("source_provenance") or {}).get("source_stage_lineage") or {}).get("step6_8") or {}).get("set_id"))
        or not _as_text((((entry.get("source_provenance") or {}).get("source_stage_lineage") or {}).get("step6_9") or {}).get("set_id"))
        or not _as_text((((entry.get("source_provenance") or {}).get("source_stage_lineage") or {}).get("step6_10") or {}).get("set_id"))
    ]
    return {
        "schema_version": "1.0",
        "stage": RESTARTED_REVIEWED_LIBRARY_ASSEMBLY_STAGE,
        "rule_version": RESTARTED_REVIEWED_LIBRARY_ASSEMBLY_RULE_VERSION,
        "frozen_reviewed_entry_count": len(frozen_entries),
        "approved_count": final_status_counts.get(APPROVED_STATUS, 0),
        "edited_approved_count": final_status_counts.get(EDITED_APPROVED_STATUS, 0),
        "approved_vs_edited_approved_counts": dict(final_status_counts),
        "rejected_count": len(rejected_entries),
        "excluded_held_count": len(excluded_cases),
        "included_kcs": [entry["kc_id"] for entry in frozen_entries],
        "rejected_kcs": [entry["kc_id"] for entry in rejected_entries],
        "excluded_held_kcs": [
            {
                "kc_candidate_id": _as_text(item.get("kc_candidate_id")),
                "reasons": list(item.get("reasons") or []),
            }
            for item in excluded_cases
        ],
        "intentionally_blank_fields_preserved": list(intentionally_blank_fields),
        "provenance_completeness_check": {
            "entries_with_complete_lineage": len(frozen_entries) - len(missing_lineage),
            "entries_missing_lineage": missing_lineage,
        },
        "contract_validation_failures": list(contract_validation_failures),
    }


def _sandbox_missing_lineage(entry: Mapping[str, Any]) -> bool:
    lineage = _mapping_or_empty((_mapping_or_empty(entry.get("source_provenance"))).get("source_stage_lineage"))
    review_status = _as_text(entry.get("review_status"))
    required_steps = ["step6_7", "step6_8"]
    if review_status == REJECTED_STATUS:
        required_steps.extend(["step6_9", "step6_10"])
    for step in required_steps:
        step_info = lineage.get(step)
        if not isinstance(step_info, Mapping) or not _as_text(step_info.get("set_id")):
            return True
    return False


def build_sandbox_summary(
    *,
    sandbox_entries: Sequence[Mapping[str, Any]],
    contract_validation_failures: Sequence[str],
) -> dict[str, Any]:
    rejected_entries = [entry for entry in sandbox_entries if _as_text(entry.get("review_status")) == REJECTED_STATUS]
    excluded_held_entries = [entry for entry in sandbox_entries if _as_text(entry.get("review_status")) == SKIPPED_BEFORE_REVIEW_STATUS]
    missing_lineage = [entry.get("kc_id") for entry in sandbox_entries if _sandbox_missing_lineage(entry)]
    return {
        "schema_version": "1.0",
        "stage": RESTARTED_REVIEWED_LIBRARY_ASSEMBLY_STAGE,
        "rule_version": RESTARTED_REVIEWED_LIBRARY_ASSEMBLY_RULE_VERSION,
        "sandbox_entry_count": len(sandbox_entries),
        "sandbox_kcs": [entry["kc_id"] for entry in sandbox_entries],
        "rejected_entry_count": len(rejected_entries),
        "excluded_held_entry_count": len(excluded_held_entries),
        "rejected_kcs": [entry["kc_id"] for entry in rejected_entries],
        "excluded_held_kcs": [entry["kc_id"] for entry in excluded_held_entries],
        "excluded_kcs": [entry["kc_id"] for entry in excluded_held_entries],
        "statuses": dict(Counter(_as_text(entry.get("review_status")) for entry in sandbox_entries)),
        "provenance_completeness_check": {
            "entries_with_complete_lineage": len(sandbox_entries) - len(missing_lineage),
            "entries_missing_lineage": missing_lineage,
        },
        "contract_validation_failures": list(contract_validation_failures),
    }


def build_reviewed_library_preview(
    *,
    reviewed_summary: Mapping[str, Any],
    frozen_entries: Sequence[Mapping[str, Any]],
    sandbox_summary: Mapping[str, Any],
    sandbox_entries: Sequence[Mapping[str, Any]],
) -> str:
    lines = [
        "# Restarted Reviewed Library Preview",
        "",
        f"- Frozen reviewed entries: `{reviewed_summary['frozen_reviewed_entry_count']}`",
        f"- Sandbox entries: `{sandbox_summary['sandbox_entry_count']}`",
        f"- Approved vs edited-approved counts: `{reviewed_summary['approved_vs_edited_approved_counts']}`",
        f"- Rejected count: `{reviewed_summary['rejected_count']}`",
        f"- Excluded-held count: `{reviewed_summary['excluded_held_count']}`",
        f"- Sandbox breakdown: `{{'rejected': {sandbox_summary['rejected_entry_count']}, 'excluded_held': {sandbox_summary['excluded_held_entry_count']}}}`",
        f"- Intentionally blank fields preserved: `{reviewed_summary['intentionally_blank_fields_preserved']}`",
        "",
        "## Frozen Reviewed Slice",
        "",
    ]
    for entry in frozen_entries:
        lines.extend(
            [
                f"### {entry['kc_id']} - {entry['review_status']}",
                "",
                f"- Title: `{entry['title']}`",
                f"- Definition: `{entry['reviewer_facing_definition']}`",
                f"- Scope: `{entry.get('reviewer_facing_scope')}`",
                f"- Scope status: `{entry.get('scope_status')}`",
                f"- Review packet id: `{entry.get('review_packet_id')}`",
                f"- Review event id: `{entry.get('review_event_id')}`",
                f"- Risk flags: `{entry.get('risk_flags')}`",
                f"- Linked evidence ids: `{entry.get('linked_evidence_ids')}`",
                "",
            ]
        )
    lines.extend(["## Sandbox Slice", ""])
    for entry in sandbox_entries:
        reason = dict(entry.get("reason") or {})
        lines.extend(
            [
                f"### {entry['kc_id']} - {entry['review_status']}",
                "",
                f"- Title: `{entry.get('title')}`",
                f"- Status: `{entry.get('status')}`",
                f"- Draft status: `{entry.get('draft_status') or entry.get('draft_status_at_review')}`",
                f"- Skip category: `{reason.get('skip_category')}`",
                f"- Rejection reason: `{reason.get('rejection_reason')}`",
                f"- Exclusion reasons: `{reason.get('summary_skip_reasons')}`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"

def assemble_restarted_reviewed_library(
    *,
    source_resolved_audit_dir: Path,
    source_review_packet_dir: Path,
    source_draft_dir: Path,
    frozen_output_dir: Path,
    sandbox_output_dir: Path,
    assembly_run_id: str,
    lineage: Mapping[str, Any],
    excluded_cases: Sequence[Mapping[str, Any]],
    intentionally_blank_final_fields: Sequence[str],
) -> RestartedReviewedLibraryAssemblyResult:
    source_resolved_audit_dir = source_resolved_audit_dir.resolve()
    source_review_packet_dir = source_review_packet_dir.resolve()
    source_draft_dir = source_draft_dir.resolve()
    frozen_output_dir = frozen_output_dir.resolve()
    sandbox_output_dir = sandbox_output_dir.resolve()

    resolved_events = read_jsonl(source_resolved_audit_dir / "review_audit_resolved.jsonl")
    review_packet_jsonl_path = source_review_packet_dir / "review_packet.jsonl"
    if not review_packet_jsonl_path.exists():
        review_packet_jsonl_path = source_review_packet_dir / "review_packets.jsonl"
    packets = read_jsonl(review_packet_jsonl_path)
    drafts = read_jsonl(source_draft_dir / "kc_draft_bundles.jsonl")

    packet_lookup = {_as_text(packet.get("kc_candidate_id")): dict(packet) for packet in packets}
    draft_lookup = {_as_text(draft.get("kc_id")): dict(draft) for draft in drafts}
    intentionally_blank_fields = set(_normalize_string_list(intentionally_blank_final_fields))

    contract_validation_failures: list[str] = []
    frozen_entries: list[dict[str, Any]] = []
    rejected_sandbox_entries: list[dict[str, Any]] = []
    for event in resolved_events:
        final_status = _as_text(event.get("final_status"))
        kc_id = _as_text(event.get("kc_candidate_id"))
        packet = packet_lookup.get(kc_id)
        draft = draft_lookup.get(kc_id)
        _ensure(packet is not None, f"Missing review packet for kc_id={kc_id}")
        _ensure(draft is not None, f"Missing draft bundle for kc_id={kc_id}")
        try:
            if final_status in {APPROVED_STATUS, EDITED_APPROVED_STATUS}:
                frozen_entries.append(
                    build_frozen_reviewed_entry(
                        event=event,
                        packet=packet,
                        draft=draft,
                        assembly_run_id=assembly_run_id,
                        lineage=lineage,
                        intentionally_blank_fields=intentionally_blank_fields,
                    )
                )
            elif final_status == REJECTED_STATUS:
                rejected_sandbox_entries.append(
                    build_rejected_sandbox_entry(
                        event=event,
                        packet=packet,
                        draft=draft,
                        assembly_run_id=assembly_run_id,
                        lineage=lineage,
                    )
                )
            else:
                raise ValueError(f"Unsupported resolved final status for {kc_id}: {final_status}")
        except Exception as exc:
            contract_validation_failures.append(f"{kc_id}: {exc}")
            raise

    excluded_sandbox_entries: list[dict[str, Any]] = []
    for excluded_case in excluded_cases:
        kc_id = _as_text(excluded_case.get("kc_candidate_id"))
        draft = draft_lookup.get(kc_id)
        _ensure(draft is not None, f"Missing draft bundle for sandbox kc_id={kc_id}")
        try:
            excluded_sandbox_entries.append(
                build_excluded_sandbox_entry(
                    excluded_case=excluded_case,
                    draft=draft,
                    assembly_run_id=assembly_run_id,
                    lineage=lineage,
                )
            )
        except Exception as exc:
            contract_validation_failures.append(f"{kc_id}: {exc}")
            raise

    sandbox_entries = [*rejected_sandbox_entries, *excluded_sandbox_entries]

    reviewed_summary = build_reviewed_library_summary(
        frozen_entries=frozen_entries,
        rejected_entries=rejected_sandbox_entries,
        intentionally_blank_fields=intentionally_blank_final_fields,
        excluded_cases=excluded_cases,
        contract_validation_failures=contract_validation_failures,
    )
    sandbox_summary = build_sandbox_summary(
        sandbox_entries=sandbox_entries,
        contract_validation_failures=contract_validation_failures,
    )
    preview_text = build_reviewed_library_preview(
        reviewed_summary=reviewed_summary,
        frozen_entries=frozen_entries,
        sandbox_summary=sandbox_summary,
        sandbox_entries=sandbox_entries,
    )

    frozen_output_dir.mkdir(parents=True, exist_ok=True)
    sandbox_output_dir.mkdir(parents=True, exist_ok=True)

    frozen_library_path = frozen_output_dir / "frozen_reviewed_library.jsonl"
    reviewed_summary_path = frozen_output_dir / "reviewed_library_summary.json"
    reviewed_preview_path = frozen_output_dir / "reviewed_library_preview.md"
    sandbox_path = sandbox_output_dir / "kc_review_sandbox.jsonl"
    sandbox_summary_path = sandbox_output_dir / "sandbox_summary.json"

    write_jsonl(frozen_library_path, frozen_entries)
    write_json(reviewed_summary_path, reviewed_summary)
    reviewed_preview_path.write_text(preview_text, encoding="utf-8")
    write_jsonl(sandbox_path, sandbox_entries)
    write_json(sandbox_summary_path, sandbox_summary)

    return RestartedReviewedLibraryAssemblyResult(
        frozen_output_dir=frozen_output_dir,
        frozen_library_path=frozen_library_path,
        reviewed_summary_path=reviewed_summary_path,
        reviewed_preview_path=reviewed_preview_path,
        sandbox_output_dir=sandbox_output_dir,
        sandbox_path=sandbox_path,
        sandbox_summary_path=sandbox_summary_path,
        frozen_count=len(frozen_entries),
        sandbox_count=len(sandbox_entries),
    )
