from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kc_l.utils.json_io import read_json, read_jsonl, write_json


REPO_ROOT = Path(__file__).resolve().parents[3]

REVIEW_CAPTURE_MODE = "restarted_broader_human_review_capture_template"
BOUNDARY_NOTE = (
    "This bundle prepares blank human review capture artifacts for the restarted Step 6.8 packet surface. "
    "Machine metadata remains advisory only until a human reviewer enters final decisions."
)
SESSION_SCOPE = (
    "Cover all review-ready packets from the current restarted Step 6.8 surface, while keeping unrecoverable held "
    "KCs outside the ready session as explicit exclusions."
)
NON_GOAL = (
    "This bundle does not execute Step 6.9, does not simulate reviewer judgments, and does not change any packet content."
)
NEXT_STEP_NOTE = (
    "Do not run Step 6.9 until every reviewable packet has a human-entered action, packet sufficiency judgment, "
    "raw-internals flag, rationale, and any needed edit notes."
)
ACTION_SPACE = ["approve", "edit", "reject"]
DEFAULT_BATCH_SIZE = 12


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


def _relative_repo_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path.resolve())


def _ensure(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _load_inputs(review_packet_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    packet_path = review_packet_dir / "review_packets.jsonl"
    summary_path = review_packet_dir / "review_packet_summary.json"
    session_manifest_path = review_packet_dir / "real_reviewer_session_manifest.json"
    if not packet_path.exists() or not summary_path.exists() or not session_manifest_path.exists():
        raise FileNotFoundError(f"Required restarted reviewer-session artifacts missing under {review_packet_dir}")
    packets = read_jsonl(packet_path)
    summary = read_json(summary_path)
    session_manifest = read_json(session_manifest_path)
    if not packets:
        raise ValueError("Restarted review packet set is empty")
    return packets, summary, session_manifest


def _ordered_entries(
    session_manifest: Mapping[str, Any],
    packets: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    packet_by_id = {_as_text(packet.get("review_packet_id")): dict(packet) for packet in packets}
    order_by_id = {
        _as_text(item.get("review_packet_id")): dict(item)
        for item in session_manifest.get("session_packet_order") or []
        if isinstance(item, Mapping)
    }

    ordered: list[dict[str, Any]] = []
    for packet_id in session_manifest.get("included_review_packet_ids") or []:
        key = _as_text(packet_id)
        packet = packet_by_id.get(key)
        _ensure(packet is not None, f"session manifest references missing packet: {packet_id}")
        order_item = order_by_id.get(key)
        _ensure(order_item is not None, f"session packet order missing packet: {packet_id}")
        ordered.append({"packet": packet, "order": order_item})
    return ordered


def _build_batch_plan(entries: Sequence[Mapping[str, Any]], batch_size: int) -> list[dict[str, Any]]:
    batches: list[dict[str, Any]] = []
    for start in range(0, len(entries), batch_size):
        chunk = entries[start : start + batch_size]
        first = dict(chunk[0]["order"])
        last = dict(chunk[-1]["order"])
        priority_counts = Counter(_as_text(item["order"].get("review_priority_bucket")) for item in chunk)
        bucket_counts = Counter(_as_text(item["order"].get("session_bucket")) for item in chunk)
        batches.append(
            {
                "batch_id": f"batch_{len(batches) + 1:02d}",
                "batch_index": len(batches) + 1,
                "batch_size": len(chunk),
                "start_session_order": int(first.get("session_order", 0)),
                "end_session_order": int(last.get("session_order", 0)),
                "session_bucket_counts": dict(bucket_counts),
                "review_priority_counts": dict(priority_counts),
                "review_packet_ids": [_as_text(item["packet"].get("review_packet_id")) for item in chunk],
                "kc_candidate_ids": [_as_text(item["packet"].get("kc_candidate_id")) for item in chunk],
            }
        )
    return batches


def _find_batch_item(batch_plan: Sequence[Mapping[str, Any]], review_packet_id: str) -> tuple[str, int]:
    for batch in batch_plan:
        review_packet_ids = [_as_text(item) for item in batch.get("review_packet_ids") or []]
        if review_packet_id in review_packet_ids:
            return _as_text(batch.get("batch_id")), review_packet_ids.index(review_packet_id) + 1
    raise ValueError(f"Missing batch assignment for packet {review_packet_id}")


def _source_set_ids(packet: Mapping[str, Any]) -> dict[str, str]:
    provenance = dict(packet.get("source_provenance") or {})
    raw = dict(provenance.get("source_set_ids") or {})
    return {key: _as_text(value) for key, value in raw.items() if _as_text(value)}


def _evidence_ids(packet: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for span in packet.get("evidence_spans") or []:
        if not isinstance(span, Mapping):
            continue
        evidence_id = _as_text(span.get("evidence_id"))
        if evidence_id and evidence_id not in out:
            out.append(evidence_id)
    return out


def _build_verdict_row(
    *,
    packet: Mapping[str, Any],
    order_item: Mapping[str, Any],
    batch_id: str,
    batch_position: int,
) -> dict[str, Any]:
    return {
        "kc_candidate_id": _as_text(packet.get("kc_candidate_id")),
        "review_packet_id": _as_text(packet.get("review_packet_id")),
        "title_draft": _as_text(packet.get("title_draft")),
        "definition_draft": _as_text(packet.get("definition_draft")),
        "scope_draft": _as_text(packet.get("scope_draft")),
        "notes_for_reviewer": _as_text(packet.get("notes_for_reviewer")),
        "current_review_priority_bucket": _as_text((packet.get("review_priority") or {}).get("bucket")),
        "current_system_recommendation": _as_text((packet.get("system_recommendation") or {}).get("label")),
        "content_source_mode": _as_text(packet.get("content_source_mode")),
        "content_repair_applied": bool(packet.get("content_repair_applied")),
        "scope_status": _as_text(packet.get("scope_status")),
        "draft_status": _as_text(packet.get("draft_status")),
        "risk_flags": _normalize_string_list(packet.get("risk_flags")),
        "evidence_ids": _evidence_ids(packet),
        "source_set_ids": _source_set_ids(packet),
        "session_order": int(order_item.get("session_order", 0)),
        "session_bucket": _as_text(order_item.get("session_bucket")),
        "batch_id": batch_id,
        "batch_position": batch_position,
        "available_actions": list(ACTION_SPACE),
        "review_capture_status": "pending_human_decision",
        "human_decision_required": True,
        "dry_run_provisional_action": None,
        "packet_sufficiency": None,
        "requires_raw_internals": None,
        "verdict_rationale": None,
        "key_findings": [],
    }


def _build_action_row(
    *,
    packet: Mapping[str, Any],
    order_item: Mapping[str, Any],
    batch_id: str,
    batch_position: int,
) -> dict[str, Any]:
    return {
        "kc_candidate_id": _as_text(packet.get("kc_candidate_id")),
        "review_packet_id": _as_text(packet.get("review_packet_id")),
        "title_draft": _as_text(packet.get("title_draft")),
        "definition_draft": _as_text(packet.get("definition_draft")),
        "scope_draft": _as_text(packet.get("scope_draft")),
        "machine_bucket": _as_text((packet.get("review_priority") or {}).get("bucket")),
        "machine_recommendation": _as_text((packet.get("system_recommendation") or {}).get("label")),
        "content_repair_applied": bool(packet.get("content_repair_applied")),
        "content_source_mode": _as_text(packet.get("content_source_mode")),
        "draft_status": _as_text(packet.get("draft_status")),
        "risk_flags": _normalize_string_list(packet.get("risk_flags")),
        "session_order": int(order_item.get("session_order", 0)),
        "session_bucket": _as_text(order_item.get("session_bucket")),
        "batch_id": batch_id,
        "batch_position": batch_position,
        "available_actions": list(ACTION_SPACE),
        "review_capture_status": "pending_human_decision",
        "draft_human_action": None,
        "packet_sufficiency": None,
        "requires_raw_internals": None,
        "workflow_decision_ready": None,
        "workflow_note": None,
    }


def _build_excluded_case(summary_item: Mapping[str, Any]) -> dict[str, Any]:
    reasons = _normalize_string_list(summary_item.get("reasons"))
    rationale = "Held before reviewer packet emission and therefore excluded from the ready human-review session."
    if reasons:
        rationale = f"{rationale} Hold reasons: {', '.join(reasons)}."
    return {
        "kc_candidate_id": _as_text(summary_item.get("kc_candidate_id")),
        "draft_status": _as_text(summary_item.get("draft_status")),
        "summary_exclusion_reasons": reasons,
        "pre_review_disposition": "excluded_from_ready_session",
        "packet_sufficiency": "not_reviewable",
        "requires_raw_internals": None,
        "skip_assessment": "held_exclusion",
        "verdict_rationale": rationale,
        "key_findings": [
            "This KC was held at Step 6.7 and never emitted as a ready review packet.",
            "It remains outside the human review session until a later stage decides whether it should be revisited.",
        ],
    }


def _build_headline_findings(
    *,
    packet_count: int,
    excluded_count: int,
    batch_count: int,
    batch_size: int,
) -> list[str]:
    return [
        f"Prepared blank human-review capture rows for all {packet_count} current review-ready packets without fabricating reviewer decisions.",
        f"Preserved {excluded_count} held KCs as explicit exclusions outside the ready review session.",
        f"Chunked the ready session into {batch_count} deterministic batch(es) of up to {batch_size} packets using the neutral reviewer-session order.",
        NEXT_STEP_NOTE,
    ]


def _build_workflow_markdown(
    *,
    review_packet_dir: Path,
    packet_count: int,
    excluded_count: int,
    batch_plan: Sequence[Mapping[str, Any]],
    headline_findings: Sequence[str],
) -> str:
    lines = [
        "# Human Review Capture Preparation",
        "",
        f"- Review packet directory: `{_relative_repo_path(review_packet_dir)}`",
        f"- Capture mode: `{REVIEW_CAPTURE_MODE}`",
        f"- Boundary note: {BOUNDARY_NOTE}",
        f"- Session scope: {SESSION_SCOPE}",
        f"- Non-goal: {NON_GOAL}",
        f"- Ready packet count awaiting human input: `{packet_count}`",
        f"- Held exclusions carried as advisory only: `{excluded_count}`",
        "",
        "## Reviewer Instructions",
        "",
        "- Read the session order in `real_reviewer_session.md` and the packet details in `manual_inspection_bundle.md`.",
        "- For each ready packet, fill the blank human decision fields in `reviewer_dry_run_verdicts.json`.",
        "- Mirror the selected reviewer action in `human_supervised_draft_actions.json`.",
        "- Keep the primary decision space to `approve`, `edit`, or `reject` only.",
        f"- {NEXT_STEP_NOTE}",
        "",
        "## Batch Plan",
        "",
    ]
    for batch in batch_plan:
        lines.append(
            f"- `{_as_text(batch.get('batch_id'))}`: session orders `{batch.get('start_session_order')}`-`{batch.get('end_session_order')}` "
            f"covering `{batch.get('batch_size')}` packets with bucket mix `{dict(batch.get('session_bucket_counts') or {})}` "
            f"and priority mix `{dict(batch.get('review_priority_counts') or {})}`"
        )
    lines.extend(["", "## Headline Findings", ""])
    for finding in headline_findings:
        lines.append(f"- {finding}")
    return "\n".join(lines).rstrip() + "\n"


def build_restarted_human_review_capture(
    review_packet_dir: Path,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> tuple[Path, Path, Path, Path]:
    review_packet_dir = review_packet_dir.resolve()
    packets, summary, session_manifest = _load_inputs(review_packet_dir)
    ordered_entries = _ordered_entries(session_manifest, packets)
    batch_plan = _build_batch_plan(ordered_entries, batch_size)

    verdicts: list[dict[str, Any]] = []
    draft_actions: list[dict[str, Any]] = []
    for entry in ordered_entries:
        packet = dict(entry["packet"])
        order_item = dict(entry["order"])
        batch_id, batch_position = _find_batch_item(batch_plan, _as_text(packet.get("review_packet_id")))
        verdicts.append(
            _build_verdict_row(
                packet=packet,
                order_item=order_item,
                batch_id=batch_id,
                batch_position=batch_position,
            )
        )
        draft_actions.append(
            _build_action_row(
                packet=packet,
                order_item=order_item,
                batch_id=batch_id,
                batch_position=batch_position,
            )
        )

    excluded_case_assessments = [
        _build_excluded_case(item)
        for item in summary.get("excluded_kcs") or []
        if isinstance(item, Mapping)
    ]

    headline_findings = _build_headline_findings(
        packet_count=len(verdicts),
        excluded_count=len(excluded_case_assessments),
        batch_count=len(batch_plan),
        batch_size=batch_size,
    )

    verdict_payload = {
        "review_packet_dir": str(review_packet_dir),
        "source_processed_dir": str(summary.get("source_processed_dir") or ""),
        "dry_run_mode": REVIEW_CAPTURE_MODE,
        "dry_run_scope": "current restarted Step 6.8 packet surface awaiting human review decisions",
        "selected_packet_count": len(verdicts),
        "selected_packet_ids": [_as_text(item.get("review_packet_id")) for item in verdicts],
        "selected_kc_ids": [_as_text(item.get("kc_candidate_id")) for item in verdicts],
        "draft_action_space": list(ACTION_SPACE),
        "pending_human_decision_count": len(verdicts),
        "reviewer_decisions_entered": False,
        "step6_9_ready": False,
        "batch_size": batch_size,
        "batch_count": len(batch_plan),
        "batch_plan": batch_plan,
        "headline_findings": headline_findings,
        "verdicts": verdicts,
        "excluded_case_assessments": excluded_case_assessments,
    }

    workflow_payload = {
        "review_packet_dir": str(review_packet_dir),
        "source_processed_dir": str(summary.get("source_processed_dir") or ""),
        "validation_mode": REVIEW_CAPTURE_MODE,
        "boundary_note": BOUNDARY_NOTE,
        "session_scope": SESSION_SCOPE,
        "non_goal": NON_GOAL,
        "draft_action_space": list(ACTION_SPACE),
        "selected_packet_count": len(draft_actions),
        "pending_human_decision_count": len(draft_actions),
        "reviewer_decisions_entered": False,
        "step6_9_ready": False,
        "batch_size": batch_size,
        "batch_count": len(batch_plan),
        "batch_plan": batch_plan,
        "draft_actions": draft_actions,
        "excluded_case_assessments": excluded_case_assessments,
        "workflow_findings": headline_findings,
    }

    set_manifest_path = review_packet_dir.parent / "_sets" / f"{review_packet_dir.name}_step6_8_kc_review_packets_restarted_set.json"
    source_review_packet_set_id = None
    if set_manifest_path.exists():
        set_manifest = read_json(set_manifest_path)
        source_review_packet_set_id = _as_text(set_manifest.get("set_id")) or None

    capture_manifest = {
        "schema_version": "1.0",
        "capture_mode": REVIEW_CAPTURE_MODE,
        "generated_utc": _now_utc_iso(),
        "review_packet_dir": _relative_repo_path(review_packet_dir),
        "source_review_packet_set_id": source_review_packet_set_id,
        "packet_count": len(verdicts),
        "excluded_held_count": len(excluded_case_assessments),
        "pending_human_decision_count": len(verdicts),
        "reviewer_decisions_entered": False,
        "step6_9_ready": False,
        "batch_size": batch_size,
        "batch_count": len(batch_plan),
        "batch_plan": batch_plan,
        "artifact_paths": {
            "manual_inspection_bundle_md": _relative_repo_path(review_packet_dir / "manual_inspection_bundle.md"),
            "real_reviewer_session_md": _relative_repo_path(review_packet_dir / "real_reviewer_session.md"),
            "real_reviewer_session_manifest_json": _relative_repo_path(review_packet_dir / "real_reviewer_session_manifest.json"),
            "reviewer_dry_run_verdicts_json": _relative_repo_path(review_packet_dir / "reviewer_dry_run_verdicts.json"),
            "human_supervised_draft_actions_json": _relative_repo_path(review_packet_dir / "human_supervised_draft_actions.json"),
            "human_supervised_workflow_validation_md": _relative_repo_path(review_packet_dir / "human_supervised_workflow_validation.md"),
        },
        "headline_findings": headline_findings,
    }

    verdict_path = review_packet_dir / "reviewer_dry_run_verdicts.json"
    actions_path = review_packet_dir / "human_supervised_draft_actions.json"
    workflow_md_path = review_packet_dir / "human_supervised_workflow_validation.md"
    capture_manifest_path = review_packet_dir / "human_review_capture_manifest.json"

    write_json(verdict_path, verdict_payload)
    write_json(actions_path, workflow_payload)
    workflow_md_path.write_text(
        _build_workflow_markdown(
            review_packet_dir=review_packet_dir,
            packet_count=len(verdicts),
            excluded_count=len(excluded_case_assessments),
            batch_plan=batch_plan,
            headline_findings=headline_findings,
        ),
        encoding="utf-8",
    )
    write_json(capture_manifest_path, capture_manifest)
    return verdict_path, actions_path, workflow_md_path, capture_manifest_path
