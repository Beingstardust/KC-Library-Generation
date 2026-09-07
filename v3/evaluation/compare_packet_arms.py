"""Compare complete KC packet artifacts from two controlled pipeline arms."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import pathlib
from typing import Any, Mapping


def load_jsonl(path: pathlib.Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def unit_id(row: Mapping[str, Any]) -> str:
    return str(row.get("kc_id") or row.get("knowledge_unit_id") or "")


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def evidence_identity(item: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(item.get("doc_id") or ""),
        str(item.get("page_index") if item.get("page_index") is not None else ""),
        str(item.get("sentence_id") or ""),
        " ".join(str(item.get("text") or "").split()),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm-a", required=True, type=pathlib.Path)
    parser.add_argument("--arm-b", required=True, type=pathlib.Path)
    parser.add_argument("--out-json", type=pathlib.Path)
    parser.add_argument("--require-same-evidence", action="store_true")
    args = parser.parse_args()

    arm_a_rows = load_jsonl(args.arm_a)
    arm_b_rows = load_jsonl(args.arm_b)
    arm_a = {unit_id(row): row for row in arm_a_rows}
    arm_b = {unit_id(row): row for row in arm_b_rows}
    duplicate_a = len(arm_a_rows) - len(arm_a)
    duplicate_b = len(arm_b_rows) - len(arm_b)
    only_a = sorted(set(arm_a) - set(arm_b))
    only_b = sorted(set(arm_b) - set(arm_a))

    changed_packets = []
    support_transitions: collections.Counter[str] = collections.Counter()
    changed_fields: collections.Counter[str] = collections.Counter()
    evidence_changed = []
    total_lost_evidence = 0
    total_added_evidence = 0
    for key in sorted(set(arm_a) & set(arm_b)):
        left, right = arm_a[key], arm_b[key]
        if canonical_hash(left) == canonical_hash(right):
            continue
        left_fields = set(left)
        right_fields = set(right)
        fields = []
        for field in sorted(left_fields | right_fields):
            if canonical_hash(left.get(field)) != canonical_hash(right.get(field)):
                fields.append(field)
                changed_fields[field] += 1
        left_state = str(left.get("packet_support_state") or "")
        right_state = str(right.get("packet_support_state") or "")
        if left_state != right_state:
            support_transitions["%s -> %s" % (left_state, right_state)] += 1

        left_evidence = collections.Counter(
            evidence_identity(item) for item in left.get("evidence_for_synthesis") or [])
        right_evidence = collections.Counter(
            evidence_identity(item) for item in right.get("evidence_for_synthesis") or [])
        lost = sorted((left_evidence - right_evidence).elements())
        added = sorted((right_evidence - left_evidence).elements())
        total_lost_evidence += len(lost)
        total_added_evidence += len(added)
        if lost or added:
            evidence_changed.append({
                "kc_id": key,
                "canonical_name": right.get("canonical_name") or left.get("canonical_name"),
                "lost_count": len(lost),
                "added_count": len(added),
                "lost_examples": [item[-1] for item in lost[:3]],
                "added_examples": [item[-1] for item in added[:3]],
            })
        changed_packets.append({
            "kc_id": key,
            "canonical_name": right.get("canonical_name") or left.get("canonical_name"),
            "changed_fields": fields,
            "support_state_a": left_state,
            "support_state_b": right_state,
            "support_reason_a": left.get("support_state_reason"),
            "support_reason_b": right.get("support_state_reason"),
            "evidence_lost": len(lost),
            "evidence_added": len(added),
        })

    result = {
        "arm_a": str(args.arm_a),
        "arm_b": str(args.arm_b),
        "arm_a_sha256": hashlib.sha256(args.arm_a.read_bytes()).hexdigest(),
        "arm_b_sha256": hashlib.sha256(args.arm_b.read_bytes()).hexdigest(),
        "counts": {
            "arm_a_rows": len(arm_a_rows),
            "arm_b_rows": len(arm_b_rows),
            "arm_a_duplicate_ids": duplicate_a,
            "arm_b_duplicate_ids": duplicate_b,
            "only_in_arm_a": len(only_a),
            "only_in_arm_b": len(only_b),
            "whole_packets_changed": len(changed_packets),
            "packets_with_evidence_changes": len(evidence_changed),
            "distinct_evidence_lost": total_lost_evidence,
            "distinct_evidence_added": total_added_evidence,
        },
        "support_state_transitions": dict(sorted(support_transitions.items())),
        "changed_top_level_fields": dict(sorted(changed_fields.items())),
        "only_in_arm_a": only_a,
        "only_in_arm_b": only_b,
        "changed_packets": changed_packets,
        "evidence_changes": evidence_changed,
    }
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    print(rendered)
    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(rendered + "\n", encoding="utf-8")

    structural_failure = bool(duplicate_a or duplicate_b or only_a or only_b)
    evidence_failure = bool(args.require_same_evidence and evidence_changed)
    return 1 if structural_failure or evidence_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
