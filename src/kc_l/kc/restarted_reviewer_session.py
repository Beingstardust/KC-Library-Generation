from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from kc_l.utils.json_io import read_json, read_jsonl, write_json


RESTARTED_SESSION_MODE = "restarted_reviewer_surface_validation"
VALIDATION_STATEMENT = (
    "This reviewer session validates the reviewer surface of the restarted architecture only. "
    "Success means a reviewer can make reliable decisions from the packet surface without reopening raw internals."
)
SUCCESS_CRITERION = (
    "Reviewer-surface usability is the gate here: the packet should support approve, edit, or reject decisions "
    "without pretending the machine is already autonomous."
)
NON_GOAL = "This session is not proof of machine autonomy and not final approval correctness."
OUT_OF_SCOPE_NOTE = (
    "This session covers review-ready packets only. Quarantined packets and unrecoverable held bundles remain outside "
    "the queue, while the parallel curriculum-coverage manifest preserves their existence without treating them as "
    "review-ready."
)
RESTARTED_ONLY_NOTE = (
    "The working reviewer surface for this session comes only from the restarted Step 6.8 packet outputs. "
    "Old provisional or reduced-supervision packet artifacts are out of scope."
)
SCOPE_GAP_FLAG = "scope_gap_reviewer_editable"
SCOPE_ABSTAINED_FLAG = "scope_candidate_abstained"
HELD_SALVAGE_FLAG = "held_bundle_review_salvage"


REPO_ROOT = Path(__file__).resolve().parents[3]


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


def _load_packets(review_packet_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    packet_path = review_packet_dir / "review_packets.jsonl"
    summary_path = review_packet_dir / "review_packet_summary.json"
    if not packet_path.exists() or not summary_path.exists():
        raise FileNotFoundError(f"Restarted review packet artifacts missing under {review_packet_dir}")
    packets = read_jsonl(packet_path)
    summary = read_json(summary_path)
    if not packets:
        raise ValueError("Restarted review packet set is empty")
    return packets, summary


def _scope_gap(packet: Mapping[str, Any]) -> bool:
    if _as_text(packet.get("scope_status")) == "abstained":
        return True
    return SCOPE_GAP_FLAG in _normalize_string_list(packet.get("risk_flags"))


def _has_caution(packet: Mapping[str, Any]) -> bool:
    flags = _normalize_string_list(packet.get("risk_flags"))
    return any(flag not in {SCOPE_GAP_FLAG, SCOPE_ABSTAINED_FLAG, "draft_ready_with_holds"} for flag in flags)


def _held_salvage(packet: Mapping[str, Any]) -> bool:
    return HELD_SALVAGE_FLAG in _normalize_string_list(packet.get("risk_flags"))


def _system_recommendation(packet: Mapping[str, Any]) -> str:
    return _as_text((packet.get("system_recommendation") or {}).get("label"))


def _priority_bucket(packet: Mapping[str, Any]) -> str:
    return _as_text((packet.get("review_priority") or {}).get("bucket"))


def _session_bucket(packet: Mapping[str, Any]) -> str:
    recommendation = _system_recommendation(packet)
    if recommendation == "approve_ready":
        return "approve_ready"
    if recommendation == "review_needed":
        if _has_caution(packet):
            return "caution_review"
        if _scope_gap(packet):
            return "repairable_scope_gap"
        return "clean_review"
    if _held_salvage(packet):
        return "salvage_backlog"
    if _has_caution(packet):
        return "caution_review"
    if _scope_gap(packet):
        return "repairable_scope_gap"
    return "low_support_backlog"


def _session_bucket_rank(packet: Mapping[str, Any]) -> tuple[int, int, int, int, str]:
    bucket = _session_bucket(packet)
    bucket_rank = {
        "approve_ready": 0,
        "clean_review": 1,
        "repairable_scope_gap": 2,
        "caution_review": 3,
        "salvage_backlog": 4,
        "low_support_backlog": 5,
    }[bucket]
    priority_rank = {"high_support": 0, "moderate_support": 1, "needs_review": 2, "low_support": 3}.get(
        _priority_bucket(packet),
        9,
    )
    scope_rank = 1 if _scope_gap(packet) else 0
    risk_rank = len(_normalize_string_list(packet.get("risk_flags")))
    return bucket_rank, priority_rank, scope_rank, risk_rank, _as_text(packet.get("kc_candidate_id"))


def _aggregate_source_run_ids(packets: Sequence[Mapping[str, Any]]) -> list[str]:
    out: list[str] = []
    for packet in packets:
        provenance = dict(packet.get("source_provenance") or {})
        generation_run_id = _as_text(provenance.get("generation_run_id"))
        if generation_run_id and generation_run_id not in out:
            out.append(generation_run_id)
        field_map = dict(packet.get("field_provenance_map") or {})
        for entry in field_map.values():
            if not isinstance(entry, Mapping):
                continue
            for run_id in _normalize_string_list(entry.get("source_run_ids")):
                if run_id not in out:
                    out.append(run_id)
    return out


def _aggregate_source_set_ids(packets: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    aggregated: dict[str, list[str]] = {}
    for packet in packets:
        provenance = dict(packet.get("source_provenance") or {})
        source_set_ids = dict(provenance.get("source_set_ids") or {})
        for key, value in source_set_ids.items():
            text = _as_text(value)
            if not text:
                continue
            bucket = aggregated.setdefault(key, [])
            if text not in bucket:
                bucket.append(text)
        field_map = dict(packet.get("field_provenance_map") or {})
        for entry in field_map.values():
            if not isinstance(entry, Mapping):
                continue
            for set_id in _normalize_string_list(entry.get("source_set_ids")):
                bucket = aggregated.setdefault("field_provenance_source_set_ids", [])
                if set_id not in bucket:
                    bucket.append(set_id)
    return aggregated


def _build_manifest(review_packet_dir: Path, packets: Sequence[Mapping[str, Any]], summary: Mapping[str, Any]) -> dict[str, Any]:
    ordered_packets = sorted(packets, key=_session_bucket_rank)
    included_packet_ids = [_as_text(packet.get("review_packet_id")) for packet in ordered_packets]
    included_kc_ids = [_as_text(packet.get("kc_candidate_id")) for packet in ordered_packets]
    scope_gap_packet_ids = [
        _as_text(packet.get("review_packet_id"))
        for packet in ordered_packets
        if _scope_gap(packet)
    ]
    scope_gap_kc_ids = [
        _as_text(packet.get("kc_candidate_id"))
        for packet in ordered_packets
        if _scope_gap(packet)
    ]
    caution_packet_ids = [
        _as_text(packet.get("review_packet_id"))
        for packet in ordered_packets
        if _has_caution(packet)
    ]
    caution_kc_ids = [
        _as_text(packet.get("kc_candidate_id"))
        for packet in ordered_packets
        if _has_caution(packet)
    ]
    artifact_inputs = {
        "review_packet_jsonl": _relative_repo_path(review_packet_dir / "review_packets.jsonl"),
        "review_packet_summary_json": _relative_repo_path(review_packet_dir / "review_packet_summary.json"),
        "review_packet_preview_md": _relative_repo_path(review_packet_dir / "review_packet_preview.md"),
    }
    coverage_manifest_path = review_packet_dir / "curriculum_kc_coverage_manifest.jsonl"
    coverage_summary_path = review_packet_dir / "curriculum_kc_coverage_summary.json"
    if coverage_manifest_path.exists():
        artifact_inputs["curriculum_kc_coverage_manifest_jsonl"] = _relative_repo_path(coverage_manifest_path)
    if coverage_summary_path.exists():
        artifact_inputs["curriculum_kc_coverage_summary_json"] = _relative_repo_path(coverage_summary_path)

    session_packet_order = []
    for index, packet in enumerate(ordered_packets, start=1):
        session_packet_order.append(
            {
                "session_order": index,
                "review_packet_id": _as_text(packet.get("review_packet_id")),
                "kc_candidate_id": _as_text(packet.get("kc_candidate_id")),
                "title_draft": _as_text(packet.get("title_draft")),
                "session_bucket": _session_bucket(packet),
                "review_priority_bucket": _as_text((packet.get("review_priority") or {}).get("bucket")),
                "system_recommendation": _as_text((packet.get("system_recommendation") or {}).get("label")),
                "scope_status": _as_text(packet.get("scope_status")),
                "risk_flags": _normalize_string_list(packet.get("risk_flags")),
            }
        )

    quarantined_kcs = []
    for item in summary.get("quarantined_kcs") or []:
        if not isinstance(item, Mapping):
            continue
        quarantined_kcs.append(
            {
                "kc_candidate_id": _as_text(item.get("kc_candidate_id")),
                "draft_status": _as_text(item.get("draft_status")),
                "reasons": _normalize_string_list(item.get("reasons")),
                "risk_flags": _normalize_string_list(item.get("risk_flags")),
            }
        )

    excluded_kcs = []
    for item in summary.get("excluded_kcs") or []:
        if not isinstance(item, Mapping):
            continue
        excluded_kcs.append(
            {
                "kc_candidate_id": _as_text(item.get("kc_candidate_id")),
                "draft_status": _as_text(item.get("draft_status")),
                "reasons": _normalize_string_list(item.get("reasons")),
            }
        )

    return {
        "session_mode": RESTARTED_SESSION_MODE,
        "review_packet_dir": str(review_packet_dir.resolve()),
        "artifact_inputs": artifact_inputs,
        "validation_statement": VALIDATION_STATEMENT,
        "success_criterion": SUCCESS_CRITERION,
        "non_goal": NON_GOAL,
        "out_of_scope_note": OUT_OF_SCOPE_NOTE,
        "restarted_only_note": RESTARTED_ONLY_NOTE,
        "packet_count": len(ordered_packets),
        "included_review_packet_ids": included_packet_ids,
        "included_kc_candidate_ids": included_kc_ids,
        "excluded_packet_ids": [],
        "quarantined_kcs": quarantined_kcs,
        "quarantined_kc_candidate_ids": [_as_text(item.get("kc_candidate_id")) for item in quarantined_kcs],
        "excluded_kcs": excluded_kcs,
        "scope_gap_packet_ids": scope_gap_packet_ids,
        "scope_gap_kc_candidate_ids": scope_gap_kc_ids,
        "caution_flag_packet_ids": caution_packet_ids,
        "caution_flag_kc_candidate_ids": caution_kc_ids,
        "recommendation_counts": dict(summary.get("recommendation_counts") or {}),
        "priority_counts": dict(summary.get("priority_counts") or {}),
        "source_run_ids": _aggregate_source_run_ids(ordered_packets),
        "source_set_ids": _aggregate_source_set_ids(ordered_packets),
        "session_packet_order": session_packet_order,
        "reviewer_surface_validation_only": True,
        "final_approval_correctness_validated": False,
    }


def _packet_section(packet: Mapping[str, Any]) -> list[str]:
    evidence_spans = list(packet.get("evidence_spans") or [])
    field_map = dict(packet.get("field_provenance_map") or {})
    lines = [
        f"## {_as_text(packet.get('kc_candidate_id'))} - {_as_text(packet.get('title_draft'))}",
        "",
        f"- Review packet id: `{_as_text(packet.get('review_packet_id'))}`",
        f"- Draft status: `{_as_text(packet.get('draft_status'))}`",
        f"- Review priority: `{_as_text((packet.get('review_priority') or {}).get('bucket'))}` / `{_as_text((packet.get('review_priority') or {}).get('display_label'))}`",
        f"- System recommendation: `{_as_text((packet.get('system_recommendation') or {}).get('label'))}`",
        f"- Scope status: `{_as_text(packet.get('scope_status'))}`",
        f"- Risk flags: `{_normalize_string_list(packet.get('risk_flags'))}`",
        f"- Notes for reviewer: `{_as_text(packet.get('notes_for_reviewer'))}`",
        "",
        "### Draft Surface",
        "",
        f"- Definition draft: `{_as_text(packet.get('definition_draft'))}`",
        f"- Scope draft: `{_as_text(packet.get('scope_draft'))}`",
        f"- Coverage summary: `{dict(packet.get('evidence_coverage_summary') or {})}`",
        "",
        "### Provenance Summary",
        "",
        f"- Definition provenance: `{dict(field_map.get('definition_full_candidate') or {})}`",
        f"- Short-definition provenance: `{dict(field_map.get('definition_short_candidate') or {})}`",
        f"- Scope provenance: `{dict(field_map.get('scope_candidate') or {})}`",
        f"- Evidence-bundle provenance: `{dict(field_map.get('evidence_bundle') or {})}`",
        "",
        "### Evidence Spans",
        "",
    ]
    for index, span in enumerate(evidence_spans, start=1):
        lines.extend(
            [
                f"#### Span {index}",
                "",
                f"- Evidence id: `{_as_text(span.get('evidence_id'))}`",
                f"- Role: `{_as_text(span.get('role'))}`",
                f"- Provenance: doc `{_as_text(span.get('doc_id'))}`, block `{_as_text(span.get('block_id'))}`, page `{span.get('page_index')}`, layer `{_as_text(span.get('layer'))}`",
                f"- Quote verified: `{span.get('quote_verified')}`",
                f"- Quote: `{_as_text(span.get('quote'))}`",
                "",
            ]
        )
    lines.extend(
        [
            "### Reviewer Prompt",
            "",
            "- Can the reviewer approve, edit, or reject from this packet without reopening raw internals?",
            "- Are any remaining gaps honest and editable, rather than hidden drafting failures?",
            "- Do the evidence spans genuinely support the surfaced definition and scope?",
            "",
        ]
    )
    return lines


def _build_manual_inspection_bundle(review_packet_dir: Path, packets: Sequence[Mapping[str, Any]], summary: Mapping[str, Any]) -> str:
    ordered_packets = sorted(packets, key=_session_bucket_rank)
    lines = [
        "# Restarted Manual Inspection Bundle",
        "",
        f"- Review packet directory: `{_relative_repo_path(review_packet_dir)}`",
        f"- Source reviewer surface: `{_relative_repo_path(review_packet_dir / 'review_packets.jsonl')}`",
        f"- Packet count: `{len(ordered_packets)}`",
        f"- Included KCs: `{[_as_text(packet.get('kc_candidate_id')) for packet in ordered_packets]}`",
        f"- Excluded KCs: `{summary.get('excluded_kcs', [])}`",
        f"- Scope-gap packets: `{summary.get('packets_with_scope_gaps', [])}`",
        f"- Caution-flag packets: `{summary.get('packets_with_caution_flags', [])}`",
        f"- Validation statement: {VALIDATION_STATEMENT}",
        f"- Non-goal: {NON_GOAL}",
        "",
        "## Reviewer Surface Rules",
        "",
        f"- {RESTARTED_ONLY_NOTE}",
        "- Review packet decisions should be made from the packet surface; reopening raw internals counts as a reviewer-surface miss.",
        "- Scope gaps must stay visible and reviewer-editable. Do not silently complete them.",
        "- Quarantined packets and unrecoverable held bundles are outside the ready session and should not be treated as missing curriculum KCs.",
        "",
        "## Packet Order",
        "",
    ]
    for index, packet in enumerate(ordered_packets, start=1):
        lines.append(
            f"- `{index:02d}` `{_as_text(packet.get('kc_candidate_id'))}` -> `{_session_bucket(packet)}` / `{_as_text((packet.get('system_recommendation') or {}).get('label'))}`"
        )
    for packet in ordered_packets:
        lines.extend([""] + _packet_section(packet))
    return "\n".join(lines).rstrip() + "\n"


def _build_real_reviewer_session_md(review_packet_dir: Path, manifest: Mapping[str, Any]) -> str:
    order = list(manifest.get("session_packet_order") or [])
    lines = [
        "# Restarted Real Reviewer Session",
        "",
        f"- Review packet directory: `{_relative_repo_path(review_packet_dir)}`",
        f"- Session mode: `{_as_text(manifest.get('session_mode'))}`",
        f"- Validation statement: {VALIDATION_STATEMENT}",
        f"- Success criterion: {SUCCESS_CRITERION}",
        f"- Non-goal: {NON_GOAL}",
        f"- Out-of-scope note: {OUT_OF_SCOPE_NOTE}",
        "",
        "## Session Inputs",
        "",
        f"- Reviewer packets: `{_as_text((manifest.get('artifact_inputs') or {}).get('review_packet_jsonl'))}`",
        f"- Packet summary: `{_as_text((manifest.get('artifact_inputs') or {}).get('review_packet_summary_json'))}`",
        f"- Packet preview: `{_as_text((manifest.get('artifact_inputs') or {}).get('review_packet_preview_md'))}`",
        f"- Curriculum coverage manifest: `{_as_text((manifest.get('artifact_inputs') or {}).get('curriculum_kc_coverage_manifest_jsonl'))}`",
        f"- Curriculum coverage summary: `{_as_text((manifest.get('artifact_inputs') or {}).get('curriculum_kc_coverage_summary_json'))}`",
        f"- Manual inspection bundle: `{_relative_repo_path(review_packet_dir / 'manual_inspection_bundle.md')}`",
        "",
        "## Session Rules",
        "",
        "- Make reviewer decisions from the restarted packet surface only.",
        "- Do not treat machine recommendations as approval decisions.",
        "- If a packet forces reopening raw internals, record that as a reviewer-surface failure.",
        "- Keep scope-gap packets editable; do not silently fill in missing scope.",
        "- Quarantined packets and unrecoverable held bundles stay outside this session, while the curriculum coverage manifest preserves them as lower-trust representations.",
        "",
        "## Included Packets",
        "",
    ]
    for packet_id, kc_id in zip(manifest.get("included_review_packet_ids") or [], manifest.get("included_kc_candidate_ids") or [], strict=False):
        lines.append(f"- `{packet_id}` / `{kc_id}`")
    lines.extend(["", "## Quarantined KCs", ""])
    for item in manifest.get("quarantined_kcs") or []:
        lines.append(
            f"- `{_as_text(item.get('kc_candidate_id'))}` (`{_as_text(item.get('draft_status'))}`): "
            f"{', '.join(_normalize_string_list(item.get('reasons')))}"
        )
    lines.extend(["", "## Excluded Held KCs", ""])
    for item in manifest.get("excluded_kcs") or []:
        lines.append(
            f"- `{_as_text(item.get('kc_candidate_id'))}` (`{_as_text(item.get('draft_status'))}`): {', '.join(_normalize_string_list(item.get('reasons')))}"
        )
    lines.extend(["", "## Session Order", ""])
    current_bucket = None
    bucket_titles = {
        "approve_ready": "Approve-Ready Cases",
        "clean_review": "Clean Review Cases",
        "repairable_scope_gap": "Repairable Scope-Gap Cases",
        "caution_review": "Caution-Flag Cases",
        "salvage_backlog": "Held-Salvage Backlog",
        "low_support_backlog": "Low-Support Backlog",
    }
    for item in order:
        bucket = _as_text(item.get("session_bucket"))
        if bucket != current_bucket:
            current_bucket = bucket
            lines.extend([f"### {bucket_titles.get(bucket, bucket)}", ""])
        lines.extend(
            [
                f"- `{int(item.get('session_order', 0)):02d}` `{_as_text(item.get('kc_candidate_id'))}` `{_as_text(item.get('title_draft'))}`",
                f"  Packet: `{_as_text(item.get('review_packet_id'))}`; priority `{_as_text(item.get('review_priority_bucket'))}`; recommendation `{_as_text(item.get('system_recommendation'))}`; scope `{_as_text(item.get('scope_status'))}`",
                f"  Risk flags: `{_normalize_string_list(item.get('risk_flags'))}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Bottom Line",
            "",
            "- This session validates reviewer-surface usability on the restarted path only.",
            "- This session does not approve KCs, write audit events, or build a frozen library.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def build_restarted_reviewer_session_artifacts(review_packet_dir: Path) -> tuple[Path, Path, Path]:
    review_packet_dir = review_packet_dir.resolve()
    packets, summary = _load_packets(review_packet_dir)
    manifest = _build_manifest(review_packet_dir, packets, summary)

    manual_path = review_packet_dir / "manual_inspection_bundle.md"
    session_md_path = review_packet_dir / "real_reviewer_session.md"
    manifest_path = review_packet_dir / "real_reviewer_session_manifest.json"

    manual_path.write_text(_build_manual_inspection_bundle(review_packet_dir, packets, summary), encoding="utf-8")
    session_md_path.write_text(_build_real_reviewer_session_md(review_packet_dir, manifest), encoding="utf-8")
    write_json(manifest_path, manifest)
    return manual_path, session_md_path, manifest_path
