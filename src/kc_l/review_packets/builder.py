from __future__ import annotations

import csv
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Tuple


ALLOWED_REVIEWER_ACTIONS = [
    "approve",
    "edit_then_approve",
    "needs_expert_rewrite",
    "hold_for_evidence_repair",
    "hold_as_segmentable_gap",
]

REVIEW_PRIORITY_RANK = {
    "evidence_reference_warning_review": 10,
    "segmentable_gap_review": 20,
    "content_caution_review": 30,
    "provenance_caution_review": 40,
    "standard_review": 50,
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _as_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> List[Any]:
    return list(value) if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _unit_id(row: Mapping[str, Any]) -> str:
    return _text(row.get("knowledge_unit_id") or row.get("kc_id") or row.get("topic_id") or row.get("unit_id"))


def _unit_type(row: Mapping[str, Any]) -> str:
    return _text(row.get("knowledge_unit_type") or row.get("unit_type"))


def _canonical_name(row: Mapping[str, Any]) -> str:
    return _text(row.get("canonical_name") or row.get("name") or row.get("title"))


def _draft_status(row: Mapping[str, Any]) -> str:
    draft = _as_dict(row.get("draft"))
    utype = _unit_type(row)
    if utype == "topic":
        obj = _as_dict(draft.get("contextual_topic_draft"))
    else:
        obj = _as_dict(draft.get("contextual_kc_draft"))
    return _text(obj.get("status") or row.get("draft_status"))


def _review_preflight(row: Mapping[str, Any]) -> Dict[str, Any]:
    draft = _as_dict(row.get("draft"))
    value = draft.get("review_preflight")
    if isinstance(value, Mapping):
        return dict(value)
    value = row.get("review_preflight")
    return dict(value) if isinstance(value, Mapping) else {}


def _review_mode(row: Mapping[str, Any], preflight: Mapping[str, Any]) -> str:
    status = _draft_status(row)
    action = _text(preflight.get("review_action"))
    if status == "abstained" or action == "emit_segmentable_gap_packet":
        return "segmentable_gap_review"
    if action == "review_with_evidence_reference_warning":
        return "evidence_reference_warning_review"
    if action == "review_with_provenance_caution":
        return "provenance_caution_review"
    if action == "review_with_content_caution":
        return "content_caution_review"
    return "standard_review"


def _recommended_decision(mode: str) -> str:
    if mode == "segmentable_gap_review":
        return "hold_as_segmentable_gap_or_expert_author_draft"
    if mode == "evidence_reference_warning_review":
        return "inspect_evidence_refs_before_approve"
    if mode == "provenance_caution_review":
        return "verify_source_support_before_approve"
    if mode == "content_caution_review":
        return "review_content_before_approve"
    return "ready_for_expert_review"


def _copy_evidence_item(item: Any, source: str) -> Dict[str, Any] | None:
    if not isinstance(item, Mapping):
        return None
    copied = dict(item)
    copied["_step68_review_evidence_source"] = source
    return copied


def _dedupe_evidence(items: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    for item in items:
        if not isinstance(item, Mapping):
            continue
        key = (
            _text(item.get("evidence_id")),
            _text(item.get("doc_id")),
            _text(item.get("sentence_id")),
            _text(item.get("text") or item.get("source_block_text"))[:200],
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(item))
    return out


def _normalize_topic_evidence(source_packet: Dict[str, Any]) -> Tuple[bool, int, str]:
    existing = source_packet.get("evidence_for_synthesis")
    if isinstance(existing, list) and existing:
        return False, len(existing), "already_present"

    recovered: List[Dict[str, Any]] = []

    topic_evidence = source_packet.get("topic_evidence_for_synthesis")
    if isinstance(topic_evidence, list):
        for item in topic_evidence:
            copied = _copy_evidence_item(item, "source_packet.topic_evidence_for_synthesis")
            if copied is not None:
                recovered.append(copied)

    if not recovered:
        direct_child = _as_dict(source_packet.get("direct_child_kc_summary"))
        child_kcs = _as_list(direct_child.get("child_kcs"))
        for child in child_kcs:
            if not isinstance(child, Mapping):
                continue
            for item in _as_list(child.get("top_child_evidence")):
                copied = _copy_evidence_item(
                    item,
                    "source_packet.direct_child_kc_summary.child_kcs.top_child_evidence",
                )
                if copied is not None:
                    recovered.append(copied)

    recovered = _dedupe_evidence(recovered)
    if recovered:
        source_packet["evidence_for_synthesis"] = recovered
        source_packet["_step68_topic_evidence_normalization"] = {
            "status": "recovered_from_existing_topic_packet_evidence",
            "no_evidence_invented": True,
            "recovered_count": len(recovered),
        }
        return True, len(recovered), "recovered_from_existing_topic_packet_evidence"

    return False, 0, "no_recoverable_topic_evidence"


def _ensure_source_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    source_row = dict(row)
    source_packet = _as_dict(source_row.get("source_packet"))
    source_row["source_packet"] = source_packet
    return source_row


def build_review_packet(row: Mapping[str, Any]) -> Dict[str, Any]:
    uid = _unit_id(row)
    utype = _unit_type(row)
    name = _canonical_name(row)
    status = _draft_status(row)
    preflight = _review_preflight(row)
    mode = _review_mode(row, preflight)

    source_row = _ensure_source_row(row)
    source_packet = _as_dict(source_row.get("source_packet"))
    source_row["source_packet"] = source_packet

    topic_evidence_recovered = False
    topic_evidence_recovered_count = 0
    topic_evidence_recovery_source = ""

    if utype == "topic" and mode != "segmentable_gap_review":
        topic_evidence_recovered, topic_evidence_recovered_count, topic_evidence_recovery_source = _normalize_topic_evidence(source_packet)

    packet: Dict[str, Any] = {
        "schema_version": "step68_v2_review_packet_from_postprocessed_source_v1",
        "review_packet_id": f"step68_v2_postprocessed:{uid}",
        "knowledge_unit_id": uid,
        "knowledge_unit_type": utype,
        "canonical_name": name,
        "draft_status": status,
        "review_mode": mode,
        "recommended_reviewer_decision": _recommended_decision(mode),
        "review_priority_rank": REVIEW_PRIORITY_RANK.get(mode, 99),
        "review_preflight": preflight,
        "draft": _as_dict(row.get("draft")),
        "source_row": source_row,
        "allowed_reviewer_actions": list(ALLOWED_REVIEWER_ACTIONS),
        "reviewer_decision": {
            "status": "pending",
            "selected_action": "",
            "edited_draft": None,
            "reviewer_notes": "",
            "approved_kc_specific_criteria": [],
        },
        "invariants": {
            "machine_draft_is_not_expert_approved": True,
            "kc_survives_even_if_machine_draft_needs_rewrite": True,
            "kc_specific_criteria_expert_pending": True,
            "no_draft_regeneration_in_step68": True,
            "no_evidence_invention_in_step68": True,
        },
        "step68_packetization_metadata": {
            "source_contract": "step67_v2_postprocessed_review_source",
            "topic_evidence_recovered": topic_evidence_recovered,
            "topic_evidence_recovered_count": topic_evidence_recovered_count,
            "topic_evidence_recovery_source": topic_evidence_recovery_source,
        },
    }

    if mode == "segmentable_gap_review":
        packet["segmentable_gap_contract"] = {
            "segmentable": True,
            "instructional_draft_available": False,
            "non_grounding_segmentation_support_only": True,
            "kc_survives_review_lane": True,
            "expert_options": [
                "hold_as_segmentable_gap",
                "needs_expert_rewrite",
                "hold_for_evidence_repair",
            ],
        }

    return packet


def build_review_packets(rows: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    packets = [build_review_packet(row) for row in rows]
    return sorted(
        packets,
        key=lambda p: (
            int(p.get("review_priority_rank") or 999),
            _text(p.get("knowledge_unit_type")),
            _text(p.get("canonical_name")),
            _text(p.get("knowledge_unit_id")),
        ),
    )


def _evidence_has_text_and_locator(items: Any) -> Tuple[bool, bool]:
    has_text = False
    has_locator = False
    if not isinstance(items, list):
        return has_text, has_locator
    for item in items:
        if not isinstance(item, Mapping):
            continue
        if _text(item.get("text")) or _text(item.get("source_block_text")) or _text(item.get("quote")):
            has_text = True
        if item.get("doc_id") or item.get("sentence_id") or item.get("page_index") is not None:
            has_locator = True
    return has_text, has_locator


def validate_review_packets(packets: List[Mapping[str, Any]]) -> Dict[str, Any]:
    unit_type_counter = Counter(_text(p.get("knowledge_unit_type")) for p in packets)
    draft_status_counter = Counter(_text(p.get("draft_status")) for p in packets)
    review_mode_counter = Counter(_text(p.get("review_mode")) for p in packets)
    allowed_action_counter = Counter(a for p in packets for a in _as_list(p.get("allowed_reviewer_actions")))

    issues: List[str] = []
    missing_review_preflight_count = 0
    non_pending_reviewer_count = 0
    expert_approval_suspect_count = 0
    segmentable_gap_missing_contract_count = 0
    reviewable_missing_evidence_for_synthesis_count = 0
    reviewable_evidence_missing_text_count = 0
    reviewable_evidence_missing_locator_count = 0
    topic_evidence_recovered_count = 0

    for packet in packets:
        uid = _text(packet.get("knowledge_unit_id"))
        mode = _text(packet.get("review_mode"))
        utype = _text(packet.get("knowledge_unit_type"))

        if not uid or not utype or not _text(packet.get("canonical_name")):
            issues.append(f"{uid}:missing_identity")

        preflight = packet.get("review_preflight")
        if not isinstance(preflight, Mapping) or not preflight:
            missing_review_preflight_count += 1
            issues.append(f"{uid}:missing_review_preflight")

        reviewer_decision = packet.get("reviewer_decision")
        if not isinstance(reviewer_decision, Mapping) or reviewer_decision.get("status") != "pending":
            non_pending_reviewer_count += 1
            expert_approval_suspect_count += 1
            issues.append(f"{uid}:reviewer_decision_not_pending")

        actions = _as_list(packet.get("allowed_reviewer_actions"))
        if "reject" in actions:
            issues.append(f"{uid}:reject_action_present")
        for action in ALLOWED_REVIEWER_ACTIONS:
            if action not in actions:
                issues.append(f"{uid}:missing_allowed_action:{action}")

        metadata = _as_dict(packet.get("step68_packetization_metadata"))
        if metadata.get("topic_evidence_recovered") is True:
            topic_evidence_recovered_count += 1

        if mode == "segmentable_gap_review":
            if not isinstance(packet.get("segmentable_gap_contract"), Mapping):
                segmentable_gap_missing_contract_count += 1
                issues.append(f"{uid}:segmentable_gap_missing_contract")
            continue

        source_row = _as_dict(packet.get("source_row"))
        source_packet = _as_dict(source_row.get("source_packet"))
        efs = source_packet.get("evidence_for_synthesis")
        if not isinstance(efs, list) or not efs:
            reviewable_missing_evidence_for_synthesis_count += 1
            issues.append(f"{uid}:reviewable_draft_missing_evidence_for_synthesis")
        else:
            has_text, has_locator = _evidence_has_text_and_locator(efs)
            if not has_text:
                reviewable_evidence_missing_text_count += 1
                issues.append(f"{uid}:evidence_for_synthesis_missing_text")
            if not has_locator:
                reviewable_evidence_missing_locator_count += 1
                issues.append(f"{uid}:evidence_for_synthesis_missing_locator")

    # this used to hard-assert packet_count==165/kc==144/topic==21/
    # segmentable_gap_review==19 - the exact counts of ONE specific historical run
    # (20260520T151731Z_policy_repair_replay's "full165"), not a real correctness invariant
    # (packet_count == unit_type_counter["kc"] + unit_type_counter["topic"] holds by
    # construction for any corpus). A run with a genuinely different, correctly-resolved KC
    # count (this run: 159 KC + 22 topic = 181, after fixing the upstream stale-pointer bugs
    # that previously silently capped every run at the 2026-05 corpus's 144-KC snapshot) would
    # otherwise always hard-fail here regardless of correctness. The real counts remain fully
    # visible below (packet_count/unit_type_counter/review_mode_counter) for anyone auditing a
    # specific run - this just stops comparing them against a frozen historical snapshot.

    return {
        "packet_count": len(packets),
        "unit_type_counter": dict(unit_type_counter),
        "draft_status_counter": dict(draft_status_counter),
        "review_mode_counter": dict(review_mode_counter),
        "allowed_action_counter": dict(allowed_action_counter),
        "reject_action_present_count": allowed_action_counter.get("reject", 0),
        "needs_expert_rewrite_action_count": allowed_action_counter.get("needs_expert_rewrite", 0),
        "missing_review_preflight_count": missing_review_preflight_count,
        "non_pending_reviewer_count": non_pending_reviewer_count,
        "expert_approval_suspect_count": expert_approval_suspect_count,
        "segmentable_gap_missing_contract_count": segmentable_gap_missing_contract_count,
        "reviewable_missing_evidence_for_synthesis_count": reviewable_missing_evidence_for_synthesis_count,
        "reviewable_evidence_missing_text_count": reviewable_evidence_missing_text_count,
        "reviewable_evidence_missing_locator_count": reviewable_evidence_missing_locator_count,
        "topic_evidence_recovered_count": topic_evidence_recovered_count,
        "issues": issues,
        "decision": "PASS_STEP68_CURRENT_REVIEW_PACKET_VALIDATION" if not issues else "FAIL_STEP68_CURRENT_REVIEW_PACKET_VALIDATION",
    }


def write_review_queue_csv(path: Path, packets: List[Mapping[str, Any]]) -> None:
    fields = [
        "review_priority_rank",
        "knowledge_unit_id",
        "knowledge_unit_type",
        "canonical_name",
        "draft_status",
        "review_mode",
        "recommended_reviewer_decision",
        "semantic_grade_provisional",
        "provenance_quality",
        "evidence_reference_status",
        "packet_support_state",
        "issue_flags",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for packet in packets:
            preflight = _as_dict(packet.get("review_preflight"))
            flags = preflight.get("issue_flags")
            writer.writerow({
                "review_priority_rank": packet.get("review_priority_rank"),
                "knowledge_unit_id": packet.get("knowledge_unit_id"),
                "knowledge_unit_type": packet.get("knowledge_unit_type"),
                "canonical_name": packet.get("canonical_name"),
                "draft_status": packet.get("draft_status"),
                "review_mode": packet.get("review_mode"),
                "recommended_reviewer_decision": packet.get("recommended_reviewer_decision"),
                "semantic_grade_provisional": preflight.get("semantic_grade_provisional"),
                "provenance_quality": preflight.get("provenance_quality"),
                "evidence_reference_status": preflight.get("evidence_reference_status"),
                "packet_support_state": preflight.get("packet_support_state"),
                "issue_flags": "|".join(str(x) for x in flags) if isinstance(flags, list) else "",
            })


def emit_review_packets_from_postprocessed_source(
    *,
    postprocessed_jsonl: Path,
    output_dir: Path,
    run_id: str,
    update_best_pointer: bool = False,
    best_pointer: Path | None = None,
    pointer_backup_dir: Path | None = None,
) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = read_jsonl(postprocessed_jsonl)
    packets = build_review_packets(rows)
    validation = validate_review_packets(packets)

    packets_path = output_dir / "step68_v2_review_packets.jsonl"
    queue_path = output_dir / "step68_v2_review_queue_index.csv"
    stats_path = output_dir / "STEP68_V2_REVIEW_PACKET_STATS.json"
    manifest_path = output_dir / "STEP68_V2_REVIEW_PACKET_MANIFEST.json"
    closeout_path = output_dir / "CLOSEOUT_STEP68_V2_REVIEW_PACKETS_FROM_POSTPROCESSED_SOURCE.txt"

    write_jsonl(packets_path, packets)
    write_review_queue_csv(queue_path, packets)

    stats = {
        "schema_version": "step68_v2_current_postprocessed_review_packet_stats_v1",
        "decision": validation["decision"],
        "run_id": run_id,
        "source_postprocessed_jsonl": str(postprocessed_jsonl),
        "review_packets_jsonl": str(packets_path),
        "review_queue_csv": str(queue_path),
        **validation,
        "review_packets_sha256": sha256_file(packets_path),
        "review_queue_sha256": sha256_file(queue_path),
    }
    stats_path.write_text(json.dumps(stats, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    manifest = {
        "schema_version": "step68_v2_current_postprocessed_review_packet_manifest_v1",
        "run_id": run_id,
        "inputs": {
            "postprocessed_jsonl": str(postprocessed_jsonl),
        },
        "outputs": {
            "review_packets_jsonl": str(packets_path),
            "review_queue_csv": str(queue_path),
            "stats_json": str(stats_path),
            "manifest_json": str(manifest_path),
            "closeout_txt": str(closeout_path),
        },
        "invariants": {
            "no_model_rerun": True,
            "no_draft_regeneration": True,
            "no_evidence_invention": True,
            "no_expert_approval_inferred": True,
            "kc_survival_preserved": True,
            "kc_specific_criteria_expert_pending": True,
            "legacy_step68_runner_not_used": True,
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    closeout_lines = [
        "STEP68_CURRENT_POSTPROCESSED_REVIEW_PACKET_RUNNER_CLOSEOUT",
        f"DECISION={validation['decision']}",
        f"RUN_ID={run_id}",
        f"POSTPROCESSED_JSONL={postprocessed_jsonl}",
        f"REVIEW_PACKETS_JSONL={packets_path}",
        f"REVIEW_QUEUE_CSV={queue_path}",
        f"STATS_JSON={stats_path}",
        f"MANIFEST_JSON={manifest_path}",
        f"REVIEW_PACKETS_SHA256={stats['review_packets_sha256']}",
        f"PACKET_COUNT={stats['packet_count']}",
        f"UNIT_TYPE_COUNTER={stats['unit_type_counter']}",
        f"DRAFT_STATUS_COUNTER={stats['draft_status_counter']}",
        f"REVIEW_MODE_COUNTER={stats['review_mode_counter']}",
        f"ALLOWED_ACTION_COUNTER={stats['allowed_action_counter']}",
        f"REJECT_ACTION_PRESENT_COUNT={stats['reject_action_present_count']}",
        f"NEEDS_EXPERT_REWRITE_ACTION_COUNT={stats['needs_expert_rewrite_action_count']}",
        f"TOPIC_EVIDENCE_RECOVERED_COUNT={stats['topic_evidence_recovered_count']}",
        f"REVIEWABLE_MISSING_EVIDENCE_FOR_SYNTHESIS_COUNT={stats['reviewable_missing_evidence_for_synthesis_count']}",
        f"HARD_ISSUE_COUNT={len(stats['issues'])}",
        "NO_MODEL_RERUN=1",
        "NO_DRAFT_REGENERATION=1",
        "NO_EVIDENCE_INVENTION=1",
        "NO_EXPERT_APPROVAL_INFERRED=1",
        "KC_SURVIVAL_PRESERVED=1",
    ]
    closeout_path.write_text("\n".join(closeout_lines) + "\n", encoding="utf-8")

    best_pointer_updated = False
    if update_best_pointer and validation["decision"] == "PASS_STEP68_CURRENT_REVIEW_PACKET_VALIDATION":
        if best_pointer is None:
            raise ValueError("best_pointer is required when update_best_pointer=True")
        if pointer_backup_dir is not None:
            pointer_backup_dir.mkdir(parents=True, exist_ok=True)
            if best_pointer.exists():
                shutil.copy2(best_pointer, pointer_backup_dir / "BEST_STEP68_POINTER_BEFORE_CURRENT_RUNNER.txt")
        best_pointer.parent.mkdir(parents=True, exist_ok=True)
        best_pointer.write_text(
            "\n".join([
                f"RUN_ID={run_id}",
                f"OUT_DIR={output_dir}",
                f"REVIEW_PACKETS_JSONL={packets_path}",
                f"REVIEW_QUEUE_CSV={queue_path}",
                f"STATS_JSON={stats_path}",
                f"MANIFEST_JSON={manifest_path}",
                f"CLOSEOUT_TXT={closeout_path}",
                f"REVIEW_PACKETS_SHA256={stats['review_packets_sha256']}",
                "DECISION=PASS_STEP68_CURRENT_REVIEW_PACKET_VALIDATION",
                "POINTER_KIND=BEST_STEP68_V2_REVIEW_PACKETS_FROM_POSTPROCESSED_SOURCE",
                "ACTIVE_POINTER_MUTATED=0",
            ]) + "\n",
            encoding="utf-8",
        )
        best_pointer_updated = True

    return {
        **stats,
        "stats_json": str(stats_path),
        "manifest_json": str(manifest_path),
        "closeout_txt": str(closeout_path),
        "best_pointer_updated": best_pointer_updated,
    }
