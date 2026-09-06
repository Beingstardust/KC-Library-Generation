from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kc_l.kc.supervision import load_review_audit_schema
from kc_l.utils.json_io import read_json, read_jsonl, write_json, write_jsonl


RESTARTED_REVIEW_AUDIT_STAGE = "step6_9_restarted_review_audit_ingestion"
RESTARTED_REVIEW_AUDIT_RULE_VERSION = "step6.9.restarted_review_audit_ingestion.v1"
RESTARTED_REVIEW_MODE = "restarted_bounded_human_reviewer_pass"
RESTARTED_REVIEWER_ID = "bounded_restarted_reviewer_pass"
EDIT_PENDING_STATUS = "edit_pending"
APPROVED_STATUS = "approved"
EDITED_APPROVED_STATUS = "edited_approved"
REJECTED_STATUS = "rejected"
NOT_APPLICABLE_RESOLUTION = "not_applicable"
PENDING_FINAL_TEXT_CAPTURE = "pending_final_text_capture"

EDIT_FIELD_PLAN: dict[str, tuple[str, ...]] = {
    "KC_CLF_DT_001": ("definition", "scope"),
    "KC_CLF_DT_003": ("scope",),
    "KC_CLF_DT_004": ("definition", "scope"),
    "KC_CLF_DT_006": ("definition",),
    "KC_CLF_DT_008": ("definition", "scope"),
    "KC_CLF_NB_001": (),
    "KC_CLF_NB_004": ("definition", "scope"),
    "KC_CLF_UND_001": ("definition",),
    "KC_CLF_UND_003": ("definition", "scope"),
    "KC_CLF_UND_004": ("definition",),
    "KC_CLF_UND_005": ("definition", "scope"),
    "KC_CLF_NB_006": ("definition", "scope"),
    "KC_EVAL_ENS_004": ("definition", "scope"),
    "KC_EVAL_SAMP_004": ("definition", "scope"),
    "KC_EVAL_SAMP_002": ("definition", "scope"),
    "KC_CLF_NB_008": ("definition", "scope"),
    "KC_CLF_NB_011": ("definition",),
    "KC_EVAL_BASIC_002": ("definition", "scope"),
    "KC_EVAL_BASIC_004": ("definition", "scope"),
    "KC_EVAL_BASIC_005": ("definition", "scope"),
    "KC_EVAL_ENS_001": ("definition",),
    "KC_EVAL_ENS_002": ("definition", "scope"),
    "KC_EVAL_ENS_003": ("definition", "scope"),
    "KC_EVAL_IMBAL_001": ("definition",),
    "KC_EVAL_SAMP_001": ("definition", "scope"),
    "KC_EVAL_SAMP_003": ("definition", "scope"),
    "KC_EVAL_BASIC_006": ("definition", "scope"),
    "KC_EVAL_SAMP_005": ("definition", "scope"),
}


@dataclass(frozen=True)
class RestartedReviewAuditIngestionResult:
    output_dir: Path
    audit_jsonl_path: Path
    summary_path: Path
    preview_path: Path
    event_count: int


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def _ensure(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _packet_text_snapshot(packet: Mapping[str, Any]) -> dict[str, Any]:
    scope_text = _as_text(packet.get("scope_draft"))
    return {
        "title": _as_text(packet.get("title_draft")) or None,
        "level": _as_text(packet.get("level_draft")) or None,
        "definition": _as_text(packet.get("definition_draft")) or None,
        "scope": scope_text or None,
    }


def _field_linked_evidence_ids(packet: Mapping[str, Any]) -> dict[str, list[str]]:
    provenance_map = dict(packet.get("field_provenance_map") or {})
    definition_ids = _normalize_string_list((provenance_map.get("definition_full_candidate") or {}).get("overlay_candidate_ids"))
    if not definition_ids:
        definition_ids = _normalize_string_list((provenance_map.get("definition_short_candidate") or {}).get("overlay_candidate_ids"))
    scope_ids = _normalize_string_list((provenance_map.get("scope_candidate") or {}).get("overlay_candidate_ids"))
    return {
        "definition": definition_ids,
        "scope": scope_ids,
    }


def _linked_evidence_ids(packet: Mapping[str, Any], field_linked: Mapping[str, Sequence[str]]) -> list[str]:
    out: list[str] = []
    for key in ("definition", "scope"):
        for value in field_linked.get(key) or []:
            text = _as_text(value)
            if text and text not in out:
                out.append(text)
    for span in packet.get("evidence_spans") or []:
        if not isinstance(span, Mapping):
            continue
        text = _as_text(span.get("evidence_id"))
        if text and text not in out:
            out.append(text)
    return out


def _run_id_from_set_id(set_id: str, suffix: str) -> str | None:
    text = _as_text(set_id)
    if not text or not text.endswith(suffix):
        return None
    return text[: -len(suffix)]


def _lineage_fields(
    *,
    packet: Mapping[str, Any],
    source_review_packet_set_id: str | None,
    source_reviewer_session_run_id: str | None,
    source_reviewer_session_set_id: str | None,
) -> dict[str, Any]:
    provenance = dict(packet.get("source_provenance") or {})
    source_set_ids = dict(provenance.get("source_set_ids") or {})
    step6_7_set_id = _as_text(source_set_ids.get("step6_7_set_id")) or None
    review_packet_run_id = _as_text(provenance.get("generation_run_id")) or None
    return {
        "source_review_packet_run_id": review_packet_run_id,
        "source_review_packet_set_id": _as_text(source_review_packet_set_id) or None,
        "source_reviewer_session_run_id": _as_text(source_reviewer_session_run_id) or review_packet_run_id or None,
        "source_reviewer_session_set_id": _as_text(source_reviewer_session_set_id) or None,
        "source_draft_run_id": _run_id_from_set_id(_as_text(step6_7_set_id), "_step6_7_kc_drafts_set"),
        "source_draft_set_id": step6_7_set_id,
    }


def _edited_fields(verdict: Mapping[str, Any]) -> list[str]:
    kc_id = _as_text(verdict.get("kc_candidate_id"))
    action = _as_text(verdict.get("dry_run_provisional_action"))
    if action != "edit":
        return []
    plan = EDIT_FIELD_PLAN.get(kc_id)
    if plan is None:
        # Generic fallback for newly editable packets on refreshed replay surfaces.
        return ["definition"]
    return list(plan)


def _final_text_snapshot(packet: Mapping[str, Any], edited_fields: Sequence[str], action: str) -> dict[str, Any]:
    current = _packet_text_snapshot(packet)
    if action == "approve":
        return dict(current)
    if action == "reject":
        return {
            "title": None,
            "level": None,
            "definition": None,
            "scope": None,
        }
    edited = set(edited_fields)
    return {
        "title": None if "title" in edited else current["title"],
        "level": None if "level" in edited else current["level"],
        "definition": None if "definition" in edited else current["definition"],
        "scope": None if "scope" in edited else current["scope"],
    }


def build_restarted_review_audit_event(
    *,
    packet: Mapping[str, Any],
    verdict: Mapping[str, Any],
    run_id_step6_9: str,
    source_review_packet_set_id: str | None,
    source_reviewer_session_run_id: str | None,
    source_reviewer_session_set_id: str | None,
) -> dict[str, Any]:
    kc_id = _as_text(packet.get("kc_candidate_id"))
    _ensure(kc_id == _as_text(verdict.get("kc_candidate_id")), f"Packet/verdict kc_id mismatch for {kc_id}")
    action = _as_text(verdict.get("dry_run_provisional_action"))
    _ensure(action in {"approve", "edit", "reject"}, f"Unsupported review action: {action}")

    edited_fields = _edited_fields(verdict)
    if action == "approve":
        final_status = APPROVED_STATUS
        edit_resolution_status = NOT_APPLICABLE_RESOLUTION
    elif action == "edit":
        final_status = EDIT_PENDING_STATUS
        edit_resolution_status = PENDING_FINAL_TEXT_CAPTURE
    else:
        final_status = REJECTED_STATUS
        edit_resolution_status = NOT_APPLICABLE_RESOLUTION

    field_linked = _field_linked_evidence_ids(packet)
    linked_evidence_ids = _linked_evidence_ids(packet, field_linked)
    current_packet_text = _packet_text_snapshot(packet)
    final_text = _final_text_snapshot(packet, edited_fields, action)
    packet_sufficiency = _as_text(verdict.get("packet_sufficiency")) or "borderline"
    raw_internals_reopened = bool(verdict.get("requires_raw_internals"))
    packet_alone_sufficient = not raw_internals_reopened
    current_risk_flags = _normalize_string_list(packet.get("risk_flags"))
    lineage = _lineage_fields(
        packet=packet,
        source_review_packet_set_id=source_review_packet_set_id,
        source_reviewer_session_run_id=source_reviewer_session_run_id,
        source_reviewer_session_set_id=source_reviewer_session_set_id,
    )

    rejection_reason = None
    if action == "reject":
        rejection_reason = _as_text(verdict.get("verdict_rationale")) or "reviewer_rejected_from_packet_surface"

    review_notes = _as_text(verdict.get("verdict_rationale"))
    if action == "edit":
        review_notes = (
            f"{review_notes} Pending final text capture for edited fields: {', '.join(edited_fields)}."
        ).strip()

    event = {
        "review_event_id": f"step6_9:{run_id_step6_9}:{kc_id}",
        "review_packet_id": _as_text(packet.get("review_packet_id")),
        "reviewer_id": RESTARTED_REVIEWER_ID,
        "review_timestamp": _now_utc_iso(),
        "kc_candidate_id": kc_id,
        "action_taken": action,
        "final_status": final_status,
        "edited_fields": edited_fields,
        "rejection_reason": rejection_reason,
        "final_text": final_text,
        "current_packet_text": current_packet_text,
        "linked_evidence_ids": linked_evidence_ids,
        "field_linked_evidence_ids": field_linked,
        "packet_review_priority_bucket": _as_text((packet.get("review_priority") or {}).get("bucket")),
        "packet_system_recommendation_label": _as_text((packet.get("system_recommendation") or {}).get("label")),
        "packet_sufficiency": packet_sufficiency,
        "packet_alone_sufficient": packet_alone_sufficient,
        "raw_internals_reopened": raw_internals_reopened,
        "current_risk_flags": current_risk_flags,
        "scope_status_at_review": _as_text(packet.get("scope_status")),
        "edit_resolution_status": edit_resolution_status,
        "review_mode": RESTARTED_REVIEW_MODE,
        "review_notes": review_notes,
        **lineage,
    }
    validate_scope_aware_review_audit_event(event)
    return event


def validate_scope_aware_review_audit_event(event: Mapping[str, Any]) -> None:
    schema = load_review_audit_schema()
    _ensure(_as_text(schema.get("schema_version")) == "step6.review_audit.v2", "Unexpected review-audit schema version")
    _ensure(_as_text(event.get("review_event_id")), "review_event_id is required")
    _ensure(_as_text(event.get("review_packet_id")), "review_packet_id is required")
    _ensure(_as_text(event.get("reviewer_id")), "reviewer_id is required")
    _ensure(_as_text(event.get("review_timestamp")), "review_timestamp is required")
    _ensure(_as_text(event.get("kc_candidate_id")), "kc_candidate_id is required")
    action = _as_text(event.get("action_taken"))
    _ensure(action in {"approve", "edit", "reject"}, "action_taken invalid")
    final_status = _as_text(event.get("final_status"))
    _ensure(final_status in {APPROVED_STATUS, EDITED_APPROVED_STATUS, REJECTED_STATUS, EDIT_PENDING_STATUS}, "final_status invalid")
    edited_fields = _normalize_string_list(event.get("edited_fields"))
    _ensure(all(item in {"title", "level", "definition", "scope"} for item in edited_fields), "edited_fields invalid")
    _ensure(isinstance(event.get("linked_evidence_ids"), list) and event.get("linked_evidence_ids"), "linked_evidence_ids invalid")
    field_linked = event.get("field_linked_evidence_ids")
    _ensure(isinstance(field_linked, Mapping), "field_linked_evidence_ids must be an object")
    for key in ("definition", "scope"):
        _ensure(isinstance(field_linked.get(key), list), f"field_linked_evidence_ids.{key} must be a list")
    for key in ("final_text", "current_packet_text"):
        snapshot = event.get(key)
        _ensure(isinstance(snapshot, Mapping), f"{key} must be an object")
        for field in ("title", "level", "definition", "scope"):
            _ensure(field in snapshot, f"{key}.{field} missing")
    scope_status = _as_text(event.get("scope_status_at_review"))
    _ensure(scope_status in {"grounded", "abstained"}, "scope_status_at_review invalid")
    edit_resolution_status = _as_text(event.get("edit_resolution_status"))
    _ensure(edit_resolution_status in {NOT_APPLICABLE_RESOLUTION, PENDING_FINAL_TEXT_CAPTURE, "finalized"}, "edit_resolution_status invalid")
    _ensure(_as_text(event.get("review_mode")), "review_mode is required")

    packet_sufficiency = event.get("packet_sufficiency")
    if packet_sufficiency is not None:
        _ensure(_as_text(packet_sufficiency) in {"sufficient", "borderline", "not_reviewable"}, "packet_sufficiency invalid")
    packet_alone_sufficient = event.get("packet_alone_sufficient")
    if packet_alone_sufficient is not None:
        _ensure(isinstance(packet_alone_sufficient, bool), "packet_alone_sufficient invalid")
    raw_internals_reopened = event.get("raw_internals_reopened")
    if raw_internals_reopened is not None:
        _ensure(isinstance(raw_internals_reopened, bool), "raw_internals_reopened invalid")
    current_risk_flags = event.get("current_risk_flags")
    if current_risk_flags is not None:
        _ensure(isinstance(current_risk_flags, list), "current_risk_flags invalid")
        _ensure(all(_as_text(flag) for flag in current_risk_flags), "current_risk_flags contains empty flag")
    for key in (
        "source_review_packet_run_id",
        "source_review_packet_set_id",
        "source_reviewer_session_run_id",
        "source_reviewer_session_set_id",
        "source_draft_run_id",
        "source_draft_set_id",
    ):
        if key in event:
            value = event.get(key)
            _ensure(value is None or isinstance(value, str), f"{key} invalid")

    if action == "approve":
        _ensure(final_status == APPROVED_STATUS, "approve action must produce approved final_status")
        _ensure(not edited_fields, "approve action must not carry edited_fields")
        _ensure(edit_resolution_status == NOT_APPLICABLE_RESOLUTION, "approve action must be finalized")
    if action == "edit":
        _ensure(bool(edited_fields), "edit action must carry edited_fields")
        _ensure(
            final_status in {EDIT_PENDING_STATUS, EDITED_APPROVED_STATUS},
            "edit action must produce edit_pending or edited_approved final_status",
        )
        if final_status == EDIT_PENDING_STATUS:
            _ensure(edit_resolution_status == PENDING_FINAL_TEXT_CAPTURE, "edit action pending state must be pending_final_text_capture")
        if final_status == EDITED_APPROVED_STATUS:
            _ensure(edit_resolution_status == "finalized", "edited_approved action must be finalized")
    if action == "reject":
        _ensure(final_status == REJECTED_STATUS, "reject action must produce rejected final_status")
        _ensure(edit_resolution_status == NOT_APPLICABLE_RESOLUTION, "reject action must be finalized")



def build_summary(
    *,
    source_review_packet_dir: Path,
    events: Sequence[Mapping[str, Any]],
    verdict_payload: Mapping[str, Any],
) -> dict[str, Any]:
    action_counts = Counter(_as_text(event.get("action_taken")) for event in events)
    final_status_counts = Counter(_as_text(event.get("final_status")) for event in events)
    resolution_counts = Counter(_as_text(event.get("edit_resolution_status")) for event in events)
    included_packet_ids = [_as_text(event.get("review_packet_id")) for event in events]
    included_kcs = [event["kc_candidate_id"] for event in events]
    scope_gap_kcs = [event["kc_candidate_id"] for event in events if _as_text(event.get("scope_status_at_review")) == "abstained"]
    pending_scope_kcs = [event["kc_candidate_id"] for event in events if "scope" in _normalize_string_list(event.get("edited_fields"))]
    pending_definition_kcs = [event["kc_candidate_id"] for event in events if "definition" in _normalize_string_list(event.get("edited_fields"))]
    approved_kcs = [event["kc_candidate_id"] for event in events if _as_text(event.get("final_status")) == APPROVED_STATUS]
    pending_edit_kcs = [event["kc_candidate_id"] for event in events if _as_text(event.get("final_status")) == EDIT_PENDING_STATUS]
    rejected_kcs = [event["kc_candidate_id"] for event in events if _as_text(event.get("final_status")) == REJECTED_STATUS]
    packet_alone_sufficiency_count = sum(1 for event in events if bool(event.get("packet_alone_sufficient")))
    raw_internals_reopen_count = sum(1 for event in events if bool(event.get("raw_internals_reopened")))
    excluded_case_assessments = list(verdict_payload.get("excluded_case_assessments") or [])
    return {
        "schema_version": "1.0",
        "stage": RESTARTED_REVIEW_AUDIT_STAGE,
        "rule_version": RESTARTED_REVIEW_AUDIT_RULE_VERSION,
        "review_mode": RESTARTED_REVIEW_MODE,
        "source_review_packet_dir": str(source_review_packet_dir),
        "event_count": len(events),
        "included_review_packet_ids": included_packet_ids,
        "included_kcs": included_kcs,
        "action_counts": dict(action_counts),
        "final_status_counts": dict(final_status_counts),
        "edit_resolution_status_counts": dict(resolution_counts),
        "approved_count": len(approved_kcs),
        "edit_pending_count": len(pending_edit_kcs),
        "reject_count": len(rejected_kcs),
        "excluded_held_count": len(excluded_case_assessments),
        "packet_alone_sufficiency_count": packet_alone_sufficiency_count,
        "raw_internals_reopen_count": raw_internals_reopen_count,
        "contract_validation_failures": [],
        "approved_kcs": approved_kcs,
        "pending_edit_kcs": pending_edit_kcs,
        "rejected_kcs": rejected_kcs,
        "scope_gap_kcs": scope_gap_kcs,
        "pending_scope_capture_kcs": pending_scope_kcs,
        "pending_definition_capture_kcs": pending_definition_kcs,
        "excluded_case_assessments": excluded_case_assessments,
        "headline_findings": list(verdict_payload.get("headline_findings") or []),
        "no_frozen_library_assembly": True,
    }



def build_preview_markdown(
    *,
    source_review_packet_dir: Path,
    events: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
) -> str:
    lines = [
        "# Restarted Review Audit Preview",
        "",
        f"- Source review packet dir: `{source_review_packet_dir}`",
        f"- Event count: `{summary['event_count']}`",
        f"- Action counts: `{summary['action_counts']}`",
        f"- Final status counts: `{summary['final_status_counts']}`",
        f"- Edit-resolution counts: `{summary['edit_resolution_status_counts']}`",
        f"- Approved count: `{summary['approved_count']}`",
        f"- Edit-pending count: `{summary['edit_pending_count']}`",
        f"- Reject count: `{summary['reject_count']}`",
        f"- Excluded held count: `{summary['excluded_held_count']}`",
        f"- Packet-alone sufficiency count: `{summary['packet_alone_sufficiency_count']}`",
        f"- Raw-internals reopen count: `{summary['raw_internals_reopen_count']}`",
        f"- Contract validation failures: `{summary['contract_validation_failures']}`",
        f"- Approved KCs: `{summary['approved_kcs']}`",
        f"- Rejected KCs: `{summary['rejected_kcs']}`",
        f"- Scope-gap KCs: `{summary['scope_gap_kcs']}`",
        f"- Pending definition capture KCs: `{summary['pending_definition_capture_kcs']}`",
        f"- Pending scope capture KCs: `{summary['pending_scope_capture_kcs']}`",
        "",
        "## Audit Events",
        "",
    ]
    for event in events:
        lines.extend(
            [
                f"### {event['kc_candidate_id']} - {event['action_taken']}",
                "",
                f"- Review packet id: `{event['review_packet_id']}`",
                f"- Final status: `{event['final_status']}`",
                f"- Packet alone sufficient: `{event.get('packet_alone_sufficient')}`",
                f"- Raw internals reopened: `{event.get('raw_internals_reopened')}`",
                f"- Packet sufficiency: `{event.get('packet_sufficiency')}`",
                f"- Current risk flags: `{event.get('current_risk_flags', [])}`",
                f"- Edited fields: `{event['edited_fields']}`",
                f"- Scope status at review: `{event['scope_status_at_review']}`",
                f"- Edit resolution status: `{event['edit_resolution_status']}`",
                f"- Linked evidence ids: `{event['linked_evidence_ids']}`",
                f"- Current packet text: `{event['current_packet_text']}`",
                f"- Final text snapshot: `{event['final_text']}`",
                f"- Source packet lineage: run `{event.get('source_review_packet_run_id')}`, set `{event.get('source_review_packet_set_id')}`",
                f"- Source reviewer-session lineage: run `{event.get('source_reviewer_session_run_id')}`, set `{event.get('source_reviewer_session_set_id')}`",
                f"- Source draft lineage: run `{event.get('source_draft_run_id')}`, set `{event.get('source_draft_set_id')}`",
                f"- Review note: {event.get('review_notes', '')}",
                "",
            ]
        )
    if summary.get("excluded_case_assessments"):
        lines.extend(["## Excluded Held Cases", ""])
        for item in summary["excluded_case_assessments"]:
            lines.append(
                f"- `{item['kc_candidate_id']}` (`{item.get('draft_status', '')}`): {', '.join(item.get('summary_exclusion_reasons') or [])}"
            )
    return "\n".join(lines).rstrip() + "\n"



def _resolve_review_packet_jsonl_path(source_review_packet_dir: Path) -> Path:
    """Resolve the real review-packets JSONL filename for this directory.

    "review_packet.jsonl" is the legacy Step 6.8 producer's filename (confirmed real at e.g.
    data/processed/kc_review_packets_restarted/2026-04-08_194540/review_packet.jsonl, no
    manifest sibling) - the current v2 producer
    (emit_review_packets_from_postprocessed_source()) writes "step68_v2_review_packets.jsonl"
    instead, recorded dynamically in that directory's own STEP68_V2_REVIEW_PACKET_MANIFEST.json
    (outputs.review_packets_jsonl). Read the filename from that manifest when present, so a
    future producer filename change doesn't silently reintroduce this bug; fall back to the
    legacy hardcoded name for legacy-schema callers, which have no such manifest.
    """
    manifest_path = source_review_packet_dir / "STEP68_V2_REVIEW_PACKET_MANIFEST.json"
    if manifest_path.exists():
        manifest = read_json(manifest_path)
        review_packets_jsonl = manifest.get("outputs", {}).get("review_packets_jsonl")
        if review_packets_jsonl:
            # Use only the filename, joined against the CALLER's own resolved directory - not
            # the manifest's recorded absolute path, which can be stale if this directory was
            # ever copied/moved from where the manifest was originally written (confirmed
            # locally: this repo's own committed fixtures carry HPC-absolute manifest paths).
            return source_review_packet_dir / Path(review_packets_jsonl).name
    return source_review_packet_dir / "review_packet.jsonl"


def emit_restarted_review_audits(
    *,
    source_review_packet_dir: Path,
    output_dir: Path,
    run_id_step6_9: str,
    source_review_packet_set_id: str | None = None,
    source_reviewer_session_run_id: str | None = None,
    source_reviewer_session_set_id: str | None = None,
) -> RestartedReviewAuditIngestionResult:
    source_review_packet_dir = source_review_packet_dir.resolve()
    output_dir = output_dir.resolve()
    packets = read_jsonl(_resolve_review_packet_jsonl_path(source_review_packet_dir))
    verdict_payload = read_json(source_review_packet_dir / "reviewer_dry_run_verdicts.json")

    packet_lookup = {_as_text(packet.get("kc_candidate_id")): dict(packet) for packet in packets}
    events: list[dict[str, Any]] = []
    for verdict in verdict_payload.get("verdicts") or []:
        if not isinstance(verdict, Mapping):
            continue
        kc_id = _as_text(verdict.get("kc_candidate_id"))
        packet = packet_lookup.get(kc_id)
        _ensure(packet is not None, f"Missing packet for verdict kc_id={kc_id}")
        events.append(
            build_restarted_review_audit_event(
                packet=packet,
                verdict=verdict,
                run_id_step6_9=run_id_step6_9,
                source_review_packet_set_id=source_review_packet_set_id,
                source_reviewer_session_run_id=source_reviewer_session_run_id,
                source_reviewer_session_set_id=source_reviewer_session_set_id,
            )
        )

    summary = build_summary(source_review_packet_dir=source_review_packet_dir, events=events, verdict_payload=verdict_payload)
    preview = build_preview_markdown(source_review_packet_dir=source_review_packet_dir, events=events, summary=summary)

    output_dir.mkdir(parents=True, exist_ok=True)
    audit_jsonl_path = output_dir / "review_audit.jsonl"
    summary_path = output_dir / "review_audit_summary.json"
    preview_path = output_dir / "review_audit_preview.md"
    write_jsonl(audit_jsonl_path, events)
    write_json(summary_path, summary)
    preview_path.write_text(preview, encoding="utf-8")

    return RestartedReviewAuditIngestionResult(
        output_dir=output_dir,
        audit_jsonl_path=audit_jsonl_path,
        summary_path=summary_path,
        preview_path=preview_path,
        event_count=len(events),
    )

