from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path.cwd()

REVIEW_DIR = REPO_ROOT / "data/processed/kc_review_packets_restarted/2026-04-09_011924"
CONSOLIDATED_DIR = max(
    (REPO_ROOT / "data/work/staging").glob("2026-04-09_011924_reviewer_pass_consolidated_*"),
    key=lambda p: p.name,
)

STEP69_PROCESSED_ROOT = REPO_ROOT / "data/processed/kc_review_audits_restarted"
STEP69_SETS_ROOT = STEP69_PROCESSED_ROOT / "_sets"
STEP610_PROCESSED_ROOT = REPO_ROOT / "data/processed/kc_review_audits_restarted_resolved"
STEP610_SETS_ROOT = STEP610_PROCESSED_ROOT / "_sets"
RUNS_ROOT = REPO_ROOT / "data/runs"

RESTARTED_REVIEW_AUDIT_STAGE = "step6_9_restarted_review_audit_ingestion"
RESTARTED_REVIEW_AUDIT_RULE_VERSION = "step6.9.restarted_review_audit_ingestion.v2_real_reviewer_bridge"
RESTARTED_REVIEW_MODE = "real_reviewer_pass"
RESTARTED_REVIEWER_ID = "llm_expert_review_pass"

RESTARTED_REVIEW_AUDIT_RESOLUTION_STAGE = "step6_10_restarted_review_audit_resolution"
RESTARTED_REVIEW_AUDIT_RESOLUTION_RULE_VERSION = "step6.10.restarted_review_audit_resolution.v2_real_reviewer_bridge"
RESTARTED_FINAL_TEXT_CAPTURE_MODE = "real_reviewer_final_text_capture"

EDIT_PENDING_STATUS = "edit_pending"
APPROVED_STATUS = "approved"
EDITED_APPROVED_STATUS = "edited_approved"
REJECTED_STATUS = "rejected"
NOT_APPLICABLE_RESOLUTION = "not_applicable"
PENDING_FINAL_TEXT_CAPTURE = "pending_final_text_capture"
FINALIZED_RESOLUTION_STATUS = "finalized"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def rel_path(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()


def choose_run_paths(processed_root: Path, runs_root: Path, sets_root: Path, step_suffix: str, set_suffix: str) -> dict[str, Path]:
    base_stamp = utc_stamp()
    suffix = 0
    while True:
        run_id = base_stamp if suffix == 0 else f"{base_stamp}_{suffix:02d}"
        processed_dir = (processed_root / run_id).resolve()
        audit_dir = (runs_root / f"{run_id}_{step_suffix}").resolve()
        set_path = (sets_root / f"{run_id}_{set_suffix}.json").resolve()
        if not processed_dir.exists() and not audit_dir.exists() and not set_path.exists():
            return {
                "run_id": Path(run_id),
                "processed_dir": processed_dir,
                "audit_dir": audit_dir,
                "set_path": set_path,
            }
        suffix += 1


def build_manifest_for_paths(paths: list[Path]) -> dict[str, Any]:
    out = []
    for p in paths:
        rec = {"path": rel_path(p), "exists": p.exists()}
        if p.exists() and p.is_file():
            stat = p.stat()
            rec["size_bytes"] = stat.st_size
            rec["mtime_utc"] = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat().replace("+00:00", "Z")
        out.append(rec)
    return {"files": out}


def build_output_manifest(root: Path) -> dict[str, Any]:
    files = []
    for dirpath, _, filenames in os.walk(root):
        for name in sorted(filenames):
            p = Path(dirpath) / name
            stat = p.stat()
            files.append({
                "path": rel_path(p),
                "size_bytes": stat.st_size,
                "mtime_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat().replace("+00:00", "Z"),
            })
    return {"files": files}


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def packet_text_snapshot(packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": normalize_text(packet.get("title_draft")) or None,
        "level": normalize_text(packet.get("level_draft")) or None,
        "definition": normalize_text(packet.get("definition_draft")) or None,
        "scope": normalize_text(packet.get("scope_draft")) or None,
    }


def field_linked_evidence_ids(packet: dict[str, Any]) -> dict[str, list[str]]:
    provenance_map = dict(packet.get("field_provenance_map") or {})
    def pull_ids(key: str) -> list[str]:
        row = dict(provenance_map.get(key) or {})
        out = []
        for v in row.get("overlay_candidate_ids") or []:
            t = normalize_text(v)
            if t and t not in out:
                out.append(t)
        return out

    definition_ids = pull_ids("definition_full_candidate") or pull_ids("definition_short_candidate")
    scope_ids = pull_ids("scope_candidate")
    return {
        "definition": definition_ids,
        "scope": scope_ids,
    }


def linked_evidence_ids(packet: dict[str, Any], field_linked: dict[str, list[str]]) -> list[str]:
    out: list[str] = []
    for key in ("definition", "scope"):
        for item in field_linked.get(key, []):
            if item and item not in out:
                out.append(item)
    for span in packet.get("evidence_spans") or []:
        eid = normalize_text((span or {}).get("evidence_id"))
        if eid and eid not in out:
            out.append(eid)
    return out


def load_step68_set_path() -> Path:
    candidates = sorted((REPO_ROOT / "data/processed/kc_review_packets_restarted/_sets").glob("*2026-04-09_011924*_step6_8_kc_review_packets_restarted_set.json"))
    if not candidates:
        raise RuntimeError("Could not find Step 6.8 set manifest for review packets.")
    return candidates[-1]


def load_packets() -> dict[str, dict[str, Any]]:
    rows = read_jsonl(REVIEW_DIR / "review_packets.jsonl")
    out = {}
    for row in rows:
        kc = normalize_text(row.get("kc_candidate_id"))
        if kc:
            out[kc] = row
    return out


def load_real_actions() -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    verdict_payload = read_json(CONSOLIDATED_DIR / "all_batches_llm_expert_verdicts.json")
    normalized_rows = read_jsonl(CONSOLIDATED_DIR / "all_batches_review_actions_normalized.jsonl")

    row_map = {}
    for row in normalized_rows:
        kc = normalize_text(row.get("kc_candidate_id"))
        if kc:
            row_map[kc] = row

    verdicts = dict(verdict_payload.get("verdicts") or {})
    out = {}
    for kc, verdict in verdicts.items():
        row = deepcopy(row_map.get(kc, {}))
        row.update(verdict)
        row["kc_candidate_id"] = kc
        out[kc] = row
    return out, verdict_payload


def compute_edited_fields(packet: dict[str, Any], action_row: dict[str, Any]) -> list[str]:
    action = normalize_text(action_row.get("llm_expert_action"))
    if action != "edit":
        return []

    current = packet_text_snapshot(packet)
    edited_fields = []

    title = normalize_text(action_row.get("edited_title"))
    definition = normalize_text(action_row.get("edited_definition"))
    scope = normalize_text(action_row.get("edited_scope"))

    if title and title != normalize_text(current.get("title")):
        edited_fields.append("title")
    if definition and definition != normalize_text(current.get("definition")):
        edited_fields.append("definition")
    if scope and scope != normalize_text(current.get("scope")):
        edited_fields.append("scope")

    if not edited_fields:
        # fallback so edit actions never collapse to empty
        if definition:
            edited_fields.append("definition")
        elif scope:
            edited_fields.append("scope")
        elif title:
            edited_fields.append("title")

    return edited_fields


def merged_final_text(packet: dict[str, Any], action_row: dict[str, Any]) -> dict[str, Any]:
    current = packet_text_snapshot(packet)
    action = normalize_text(action_row.get("llm_expert_action"))

    if action == "reject":
        return {"title": None, "level": None, "definition": None, "scope": None}

    merged = dict(current)
    if action == "edit":
        title = normalize_text(action_row.get("edited_title"))
        definition = normalize_text(action_row.get("edited_definition"))
        scope = normalize_text(action_row.get("edited_scope"))
        if title:
            merged["title"] = title
        if definition:
            merged["definition"] = definition
        if scope:
            merged["scope"] = scope
    return merged


def kc_lists(events: list[dict[str, Any]], key: str, value: str) -> list[str]:
    return [e["kc_candidate_id"] for e in events if normalize_text(e.get(key)) == value]


def make_step69_preview(events: list[dict[str, Any]]) -> str:
    lines = [
        "# Step 6.9 Review Audit Preview",
        "",
        f"- Event count: {len(events)}",
        f"- Approved: {len(kc_lists(events, 'action_taken', 'approve'))}",
        f"- Edit pending: {len([e for e in events if e.get('final_status') == EDIT_PENDING_STATUS])}",
        f"- Rejected: {len(kc_lists(events, 'action_taken', 'reject'))}",
        "",
    ]
    for event in events[:20]:
        lines.extend([
            f"## {event['kc_candidate_id']}",
            f"- Action: `{event['action_taken']}`",
            f"- Final status: `{event['final_status']}`",
            f"- Edited fields: `{event['edited_fields']}`",
            f"- Review rationale: {event.get('review_notes') or ''}",
            "",
        ])
    return "\n".join(lines)


def make_step610_preview(events: list[dict[str, Any]]) -> str:
    lines = [
        "# Step 6.10 Review Audit Resolution Preview",
        "",
        f"- Event count: {len(events)}",
        f"- Approved: {len([e for e in events if e.get('final_status') == APPROVED_STATUS])}",
        f"- Edited approved: {len([e for e in events if e.get('final_status') == EDITED_APPROVED_STATUS])}",
        f"- Rejected: {len([e for e in events if e.get('final_status') == REJECTED_STATUS])}",
        "",
    ]
    for event in events[:20]:
        lines.extend([
            f"## {event['kc_candidate_id']}",
            f"- Final status: `{event['final_status']}`",
            f"- Edited fields: `{event.get('edited_fields', [])}`",
            f"- Final title: {normalize_text((event.get('final_text') or {}).get('title'))}",
            "",
        ])
    return "\n".join(lines)


def main() -> int:
    packets = load_packets()
    action_map, consolidated_payload = load_real_actions()

    missing = sorted(set(packets) - set(action_map))
    if missing:
        raise RuntimeError(f"Missing reviewer action rows for {len(missing)} KC(s), e.g. {missing[:10]}")

    step68_set_path = load_step68_set_path()
    step68_set_obj = read_json(step68_set_path)
    source_step68_set_id = normalize_text(step68_set_obj.get("set_id")) or step68_set_path.stem

    # Step 6.9
    step69_paths = choose_run_paths(
        STEP69_PROCESSED_ROOT, RUNS_ROOT, STEP69_SETS_ROOT,
        "step6_9", "step6_9_kc_review_audits_restarted_set"
    )
    run_id69 = str(step69_paths["run_id"])
    processed69 = step69_paths["processed_dir"]
    audit69 = step69_paths["audit_dir"]
    set69 = step69_paths["set_path"]
    processed69.mkdir(parents=True, exist_ok=False)
    audit69.mkdir(parents=True, exist_ok=False)
    STEP69_SETS_ROOT.mkdir(parents=True, exist_ok=True)

    step69_events: list[dict[str, Any]] = []

    for kc_id, packet in sorted(packets.items(), key=lambda kv: int(action_map[kv[0]].get("session_order", 10**9))):
        action_row = action_map[kc_id]
        action = normalize_text(action_row.get("llm_expert_action"))
        if action not in {"approve", "edit", "reject"}:
            raise RuntimeError(f"Unsupported reviewer action for {kc_id}: {action!r}")

        edited_fields = compute_edited_fields(packet, action_row)
        current = packet_text_snapshot(packet)
        proposed_final = merged_final_text(packet, action_row)
        field_linked = field_linked_evidence_ids(packet)
        linked_ids = linked_evidence_ids(packet, field_linked)

        if action == "approve":
            final_status = APPROVED_STATUS
            edit_resolution_status = NOT_APPLICABLE_RESOLUTION
            packet_sufficiency = "sufficient"
            rejection_reason = None
        elif action == "edit":
            final_status = EDIT_PENDING_STATUS
            edit_resolution_status = PENDING_FINAL_TEXT_CAPTURE
            packet_sufficiency = "sufficient"
            rejection_reason = None
        else:
            final_status = REJECTED_STATUS
            edit_resolution_status = NOT_APPLICABLE_RESOLUTION
            packet_sufficiency = "not_reviewable"
            rejection_reason = normalize_text(action_row.get("verdict_rationale")) or "reviewer_rejected_from_packet_surface"

        review_notes = normalize_text(action_row.get("verdict_rationale"))
        if action == "edit" and edited_fields:
            review_notes = f"{review_notes} Pending final text capture for edited fields: {', '.join(edited_fields)}.".strip()

        event = {
            "review_event_id": f"step6_9:{run_id69}:{kc_id}",
            "review_stage": RESTARTED_REVIEW_AUDIT_STAGE,
            "rule_version": RESTARTED_REVIEW_AUDIT_RULE_VERSION,
            "review_packet_id": normalize_text(packet.get("review_packet_id")),
            "reviewer_id": RESTARTED_REVIEWER_ID,
            "review_timestamp": now_utc_iso(),
            "kc_candidate_id": kc_id,
            "action_taken": action,
            "final_status": final_status,
            "edited_fields": edited_fields,
            "rejection_reason": rejection_reason,
            "final_text": current if action == "approve" else {"title": None, "level": current.get("level"), "definition": None, "scope": None},
            "current_packet_text": current,
            "reviewer_final_text": proposed_final,
            "linked_evidence_ids": linked_ids,
            "field_linked_evidence_ids": field_linked,
            "packet_review_priority_bucket": normalize_text((packet.get("review_priority") or {}).get("bucket")),
            "packet_system_recommendation_label": normalize_text((packet.get("system_recommendation") or {}).get("label")),
            "packet_sufficiency": packet_sufficiency,
            "packet_alone_sufficient": True,
            "raw_internals_reopened": False,
            "current_risk_flags": list(packet.get("risk_flags") or []),
            "scope_status_at_review": normalize_text(packet.get("scope_status")),
            "edit_resolution_status": edit_resolution_status,
            "review_mode": RESTARTED_REVIEW_MODE,
            "review_notes": review_notes,
            "criteria_authoring_ready": normalize_text(action_row.get("criteria_authoring_ready")),
            "batch_id": normalize_text(action_row.get("batch_id")),
            "source_review_packet_run_id": "2026-04-09_011924",
            "source_review_packet_set_id": source_step68_set_id,
            "source_reviewer_session_run_id": "2026-04-09_011924",
            "source_reviewer_session_set_id": None,
            "source_draft_set_id": normalize_text((((packet.get("source_provenance") or {}).get("source_set_ids") or {}).get("step6_7_set_id"))),
        }
        step69_events.append(event)

    review_audit_jsonl = processed69 / "review_audit.jsonl"
    review_audit_summary = processed69 / "review_audit_summary.json"
    review_audit_preview = processed69 / "review_audit_preview.md"

    write_jsonl(review_audit_jsonl, step69_events)
    summary69 = {
        "event_count": len(step69_events),
        "action_counts": {
            "approve": len([e for e in step69_events if e["action_taken"] == "approve"]),
            "edit": len([e for e in step69_events if e["action_taken"] == "edit"]),
            "reject": len([e for e in step69_events if e["action_taken"] == "reject"]),
        },
        "included_kcs": [e["kc_candidate_id"] for e in step69_events],
        "approved_kcs": [e["kc_candidate_id"] for e in step69_events if e["action_taken"] == "approve"],
        "pending_edit_kcs": [e["kc_candidate_id"] for e in step69_events if e["action_taken"] == "edit"],
        "rejected_kcs": [e["kc_candidate_id"] for e in step69_events if e["action_taken"] == "reject"],
        "excluded_case_assessments": [],
        "pending_scope_kcs": [e["kc_candidate_id"] for e in step69_events if "scope" in e["edited_fields"]],
        "pending_definition_kcs": [e["kc_candidate_id"] for e in step69_events if "definition" in e["edited_fields"]],
        "pending_title_kcs": [e["kc_candidate_id"] for e in step69_events if "title" in e["edited_fields"]],
    }
    write_json(review_audit_summary, summary69)
    review_audit_preview.write_text(make_step69_preview(step69_events), encoding="utf-8")

    input_manifest69 = build_manifest_for_paths([
        REVIEW_DIR / "review_packets.jsonl",
        REVIEW_DIR / "review_packet_summary.json",
        REVIEW_DIR / "human_review_capture_manifest.json",
        CONSOLIDATED_DIR / "all_batches_llm_expert_verdicts.json",
        CONSOLIDATED_DIR / "all_batches_review_actions_normalized.jsonl",
        step68_set_path,
    ])
    write_json(audit69 / "input_manifest.json", input_manifest69)

    summary69_audit = {
        "run_id": run_id69,
        "created_utc": now_utc_iso(),
        "bridge_mode": True,
        "source_step6_8_set_id": source_step68_set_id,
        "source_review_packet_dir": rel_path(REVIEW_DIR),
        "source_consolidated_review_dir": rel_path(CONSOLIDATED_DIR),
        "stats": summary69,
    }
    write_json(audit69 / "summary.json", summary69_audit)

    set_manifest69 = {
        "schema_version": "1.0",
        "kind": "step6_9_kc_review_audits_restarted_set",
        "set_id": f"{run_id69}_step6_9_kc_review_audits_restarted_set",
        "created_utc": now_utc_iso(),
        "run_id_step6_9": run_id69,
        "artifacts": {
            "review_audit_jsonl": rel_path(review_audit_jsonl),
            "review_audit_summary_json": rel_path(review_audit_summary),
            "review_audit_preview_md": rel_path(review_audit_preview),
        },
        "upstream": {
            "step6_8_set_manifest_json": rel_path(step68_set_path),
            "review_packet_jsonl": rel_path(REVIEW_DIR / "review_packets.jsonl"),
            "review_packet_summary_json": rel_path(REVIEW_DIR / "review_packet_summary.json"),
            "real_reviewer_verdicts_json": rel_path(CONSOLIDATED_DIR / "all_batches_llm_expert_verdicts.json"),
            "real_reviewer_actions_jsonl": rel_path(CONSOLIDATED_DIR / "all_batches_review_actions_normalized.jsonl"),
        },
        "slice": {
            "included_kcs": summary69["included_kcs"],
            "approved_kcs": summary69["approved_kcs"],
            "pending_edit_kcs": summary69["pending_edit_kcs"],
            "rejected_kcs": summary69["rejected_kcs"],
            "excluded_kcs": [],
        },
        "audit": {
            "run_dir": rel_path(audit69),
            "input_manifest": rel_path(audit69 / "input_manifest.json"),
            "summary": rel_path(audit69 / "summary.json"),
            "output_manifest": rel_path(audit69 / "output_manifest.json"),
        },
    }
    write_json(set69, set_manifest69)

    output_manifest69 = {
        "processed_outputs": build_output_manifest(processed69),
        "audit_outputs": build_output_manifest(audit69),
        "set_manifest": {"path": rel_path(set69)},
    }
    write_json(audit69 / "output_manifest.json", output_manifest69)

    # Step 6.10
    step610_paths = choose_run_paths(
        STEP610_PROCESSED_ROOT, RUNS_ROOT, STEP610_SETS_ROOT,
        "step6_10", "step6_10_kc_review_audits_restarted_resolved_set"
    )
    run_id610 = str(step610_paths["run_id"])
    processed610 = step610_paths["processed_dir"]
    audit610 = step610_paths["audit_dir"]
    set610 = step610_paths["set_path"]
    processed610.mkdir(parents=True, exist_ok=False)
    audit610.mkdir(parents=True, exist_ok=False)
    STEP610_SETS_ROOT.mkdir(parents=True, exist_ok=True)

    resolved_events: list[dict[str, Any]] = []
    intentionally_blank_final_fields: list[dict[str, Any]] = []

    for event in step69_events:
        row = action_map[event["kc_candidate_id"]]
        action = normalize_text(row.get("llm_expert_action"))
        resolved = deepcopy(event)
        resolved["resolution_stage"] = RESTARTED_REVIEW_AUDIT_RESOLUTION_STAGE
        resolved["resolution_rule_version"] = RESTARTED_REVIEW_AUDIT_RESOLUTION_RULE_VERSION
        resolved["resolution_timestamp"] = now_utc_iso()
        resolved["resolution_mode"] = RESTARTED_FINAL_TEXT_CAPTURE_MODE

        if action == "approve":
            resolved["final_status"] = APPROVED_STATUS
            resolved["edit_resolution_status"] = NOT_APPLICABLE_RESOLUTION
            resolved["final_text"] = packet_text_snapshot(packets[event["kc_candidate_id"]])
            resolved["resolution_note"] = normalize_text(row.get("verdict_rationale")) or "Approved as-is from reviewer pass."
        elif action == "edit":
            final_text = merged_final_text(packets[event["kc_candidate_id"]], row)
            resolved["final_status"] = EDITED_APPROVED_STATUS
            resolved["edit_resolution_status"] = FINALIZED_RESOLUTION_STATUS
            resolved["final_text"] = final_text
            resolved["resolution_note"] = "Final text captured directly from consolidated real reviewer edits."
            for field in ("title", "definition", "scope"):
                if not normalize_text((final_text or {}).get(field)):
                    intentionally_blank_final_fields.append({
                        "kc_candidate_id": event["kc_candidate_id"],
                        "field": field,
                    })
        else:
            resolved["final_status"] = REJECTED_STATUS
            resolved["edit_resolution_status"] = NOT_APPLICABLE_RESOLUTION
            resolved["final_text"] = {"title": None, "level": None, "definition": None, "scope": None}
            resolved["resolution_note"] = normalize_text(row.get("verdict_rationale")) or "Rejected by reviewer."

        resolved_events.append(resolved)

    resolved_jsonl = processed610 / "review_audit_resolved.jsonl"
    resolution_summary_json = processed610 / "review_audit_resolution_summary.json"
    resolution_preview_md = processed610 / "review_audit_resolution_preview.md"

    write_jsonl(resolved_jsonl, resolved_events)
    summary610 = {
        "event_count": len(resolved_events),
        "final_status_counts": {
            "approved": len([e for e in resolved_events if e["final_status"] == APPROVED_STATUS]),
            "edited_approved": len([e for e in resolved_events if e["final_status"] == EDITED_APPROVED_STATUS]),
            "rejected": len([e for e in resolved_events if e["final_status"] == REJECTED_STATUS]),
        },
        "approved_kcs": [e["kc_candidate_id"] for e in resolved_events if e["final_status"] == APPROVED_STATUS],
        "edited_approved_kcs": [e["kc_candidate_id"] for e in resolved_events if e["final_status"] == EDITED_APPROVED_STATUS],
        "rejected_kcs": [e["kc_candidate_id"] for e in resolved_events if e["final_status"] == REJECTED_STATUS],
        "unresolved_edit_kcs": [],
        "intentionally_blank_final_fields": intentionally_blank_final_fields,
    }
    write_json(resolution_summary_json, summary610)
    resolution_preview_md.write_text(make_step610_preview(resolved_events), encoding="utf-8")

    input_manifest610 = build_manifest_for_paths([
        review_audit_jsonl,
        review_audit_summary,
        REVIEW_DIR / "review_packets.jsonl",
        CONSOLIDATED_DIR / "all_batches_llm_expert_verdicts.json",
        CONSOLIDATED_DIR / "all_batches_review_actions_normalized.jsonl",
        set69,
        step68_set_path,
    ])
    write_json(audit610 / "input_manifest.json", input_manifest610)

    summary610_audit = {
        "run_id": run_id610,
        "created_utc": now_utc_iso(),
        "bridge_mode": True,
        "source_step6_9_set_id": set_manifest69["set_id"],
        "source_step6_8_set_id": source_step68_set_id,
        "source_review_audit_dir": rel_path(processed69),
        "source_review_packet_dir": rel_path(REVIEW_DIR),
        "source_consolidated_review_dir": rel_path(CONSOLIDATED_DIR),
        "stats": summary610,
    }
    write_json(audit610 / "summary.json", summary610_audit)

    set_manifest610 = {
        "schema_version": "1.0",
        "kind": "step6_10_kc_review_audits_restarted_resolved_set",
        "set_id": f"{run_id610}_step6_10_kc_review_audits_restarted_resolved_set",
        "created_utc": now_utc_iso(),
        "run_id_step6_10": run_id610,
        "artifacts": {
            "review_audit_resolved_jsonl": rel_path(resolved_jsonl),
            "review_audit_resolution_summary_json": rel_path(resolution_summary_json),
            "review_audit_resolution_preview_md": rel_path(resolution_preview_md),
        },
        "upstream": {
            "step6_9_set_manifest_json": rel_path(set69),
            "review_audit_jsonl": rel_path(review_audit_jsonl),
            "review_audit_summary_json": rel_path(review_audit_summary),
            "step6_8_set_manifest_json": rel_path(step68_set_path),
            "review_packet_jsonl": rel_path(REVIEW_DIR / "review_packets.jsonl"),
            "review_packet_summary_json": rel_path(REVIEW_DIR / "review_packet_summary.json"),
            "real_reviewer_verdicts_json": rel_path(CONSOLIDATED_DIR / "all_batches_llm_expert_verdicts.json"),
            "real_reviewer_actions_jsonl": rel_path(CONSOLIDATED_DIR / "all_batches_review_actions_normalized.jsonl"),
        },
        "slice": {
            "approved_kcs": summary610["approved_kcs"],
            "edited_approved_kcs": summary610["edited_approved_kcs"],
            "rejected_kcs": summary610["rejected_kcs"],
            "unresolved_edit_kcs": summary610["unresolved_edit_kcs"],
            "intentionally_blank_final_fields": summary610["intentionally_blank_final_fields"],
        },
        "audit": {
            "run_dir": rel_path(audit610),
            "input_manifest": rel_path(audit610 / "input_manifest.json"),
            "summary": rel_path(audit610 / "summary.json"),
            "output_manifest": rel_path(audit610 / "output_manifest.json"),
        },
    }
    write_json(set610, set_manifest610)

    output_manifest610 = {
        "processed_outputs": build_output_manifest(processed610),
        "audit_outputs": build_output_manifest(audit610),
        "set_manifest": {"path": rel_path(set610)},
    }
    write_json(audit610 / "output_manifest.json", output_manifest610)

    print(json.dumps({
        "review_dir": rel_path(REVIEW_DIR),
        "consolidated_dir": rel_path(CONSOLIDATED_DIR),
        "step6_9_run_id": run_id69,
        "step6_9_processed_dir": rel_path(processed69),
        "step6_9_set_manifest": rel_path(set69),
        "step6_10_run_id": run_id610,
        "step6_10_processed_dir": rel_path(processed610),
        "step6_10_set_manifest": rel_path(set610),
        "step6_9_action_counts": summary69["action_counts"],
        "step6_10_final_status_counts": summary610["final_status_counts"],
    }, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
