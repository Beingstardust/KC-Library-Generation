"""Build matched generation-only packet arms for the source-order experiment."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import pathlib
from typing import Any, Mapping

from investigate_r8_selection import source_contiguous_order


# These names are the externally reviewed completeness/DOS-advantage stratum from the supplied
# post-r7 assessment. They select evaluation cases only; the ordering mechanism never reads them.
REVIEWED_PROBLEM_NAMES = {
    "Spearman Rank Correlation",
    "Sequential Forward Generation (SFG)",
    "Cost Matrix",
    "F-Measure",
    "Classification Threshold (Cutoff)",
    "Confidence Interval for Accuracy",
    "External Index: Entropy",
    "External Index: Purity",
    "ID3 Algorithm",
    "Ranker (Filter Subcategory)",
    "Threshold Effect on Precision, Recall, F1",
}


def load_jsonl(path: pathlib.Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def unit_id(row: Mapping[str, Any]) -> str:
    return str(row.get("kc_id") or row.get("knowledge_unit_id") or "")


def draft_status(row: Mapping[str, Any]) -> str:
    draft = row.get("draft") or {}
    contextual = draft.get("contextual_kc_draft") or {} if isinstance(draft, Mapping) else {}
    return str(contextual.get("status") or "") if isinstance(contextual, Mapping) else ""


def write_jsonl(path: pathlib.Path, rows: list[Mapping[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                    encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packets", required=True, type=pathlib.Path)
    parser.add_argument("--drafts", required=True, type=pathlib.Path)
    parser.add_argument("--out-dir", required=True, type=pathlib.Path)
    parser.add_argument("--control-count", type=int, default=8)
    args = parser.parse_args()

    packets = load_jsonl(args.packets)
    drafts = load_jsonl(args.drafts)
    draft_by_id = {unit_id(row): row for row in drafts}
    packet_by_name = {str(row.get("canonical_name") or ""): row for row in packets}
    missing_reviewed = sorted(REVIEWED_PROBLEM_NAMES - set(packet_by_name))
    if missing_reviewed:
        raise SystemExit("reviewed packet names not found: %s" % missing_reviewed)

    reviewed = [packet_by_name[name] for name in sorted(REVIEWED_PROBLEM_NAMES)]
    control_pool = []
    for packet in packets:
        name = str(packet.get("canonical_name") or "")
        evidence = list(packet.get("evidence_for_synthesis") or [])
        if name in REVIEWED_PROBLEM_NAMES or len(evidence) < 2:
            continue
        if draft_status(draft_by_id.get(unit_id(packet)) or {}) != "grounded":
            continue
        source_ids = [item.get("evidence_id") for item in source_contiguous_order(evidence)]
        current_ids = [item.get("evidence_id") for item in evidence]
        if source_ids == current_ids:
            continue
        selection_hash = hashlib.sha256(
            ("r8-source-order-control:" + unit_id(packet)).encode("utf-8")).hexdigest()
        control_pool.append((selection_hash, packet))
    controls = [packet for _, packet in sorted(control_pool)[:args.control_count]]
    selected = reviewed + controls

    arm_a = []
    arm_b = []
    manifest_rows = []
    for stratum, rows in (("reviewed_problem", reviewed), ("deterministic_healthy_control", controls)):
        for packet in rows:
            left = copy.deepcopy(packet)
            right = copy.deepcopy(packet)
            right["evidence_for_synthesis"] = source_contiguous_order(
                list(right.get("evidence_for_synthesis") or []))
            before = [item.get("evidence_id") for item in left.get("evidence_for_synthesis") or []]
            after = [item.get("evidence_id") for item in right.get("evidence_for_synthesis") or []]
            arm_a.append(left)
            arm_b.append(right)
            manifest_rows.append({
                "kc_id": unit_id(packet),
                "canonical_name": packet.get("canonical_name"),
                "stratum": stratum,
                "evidence_count": len(before),
                "order_changed": before != after,
                "evidence_set_identical": sorted(before) == sorted(after),
                "r7_status": draft_status(draft_by_id.get(unit_id(packet)) or {}),
            })

    args.out_dir.mkdir(parents=True, exist_ok=False)
    write_jsonl(args.out_dir / "arm_a_current_order_packets.jsonl", arm_a)
    write_jsonl(args.out_dir / "arm_b_source_order_packets.jsonl", arm_b)
    manifest = {
        "selection": {
            "reviewed_problem_count": len(reviewed),
            "deterministic_healthy_control_count": len(controls),
            "total": len(selected),
            "control_rule": "lowest sha256(r8-source-order-control:<kc_id>) among grounded reordered non-problems",
        },
        "invariants": {
            "same_packet_count": len(arm_a) == len(arm_b),
            "all_evidence_sets_identical": all(row["evidence_set_identical"] for row in manifest_rows),
        },
        "packets": manifest_rows,
    }
    (args.out_dir / "selection_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
