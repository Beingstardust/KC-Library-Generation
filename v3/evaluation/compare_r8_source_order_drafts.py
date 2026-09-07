"""Compare matched generation outputs for the R8 source-order experiment."""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
from typing import Any, Mapping


RELATION_RE = re.compile(r"(?:<=|>=|!=|=|\u2264|\u2265|\u2260|\u2248)")


def load_jsonl(path: pathlib.Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def unit_id(row: Mapping[str, Any]) -> str:
    return str(row.get("kc_id") or row.get("knowledge_unit_id") or "")


def payload(row: Mapping[str, Any]) -> Mapping[str, Any]:
    value = row.get("draft") or {}
    return value if isinstance(value, Mapping) else {}


def contextual(row: Mapping[str, Any]) -> Mapping[str, Any]:
    value = payload(row).get("contextual_kc_draft") or {}
    return value if isinstance(value, Mapping) else {}


def body(row: Mapping[str, Any]) -> str:
    return str(contextual(row).get("text") or "")


def status(row: Mapping[str, Any]) -> str:
    return str(contextual(row).get("status") or "")


def technical_failure(row: Mapping[str, Any]) -> bool:
    return bool(row.get("runtime_error") or row.get("parse_error")
                or not isinstance(row.get("draft"), Mapping))


def hygiene_by_unit(path: pathlib.Path | None) -> dict[str, collections.Counter[str]]:
    if path is None:
        return {}
    result: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    for row in load_jsonl(path):
        result[unit_id(row)][str(row.get("check") or "UNKNOWN")] += 1
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm-a", required=True, type=pathlib.Path)
    parser.add_argument("--arm-b", required=True, type=pathlib.Path)
    parser.add_argument("--manifest", required=True, type=pathlib.Path)
    parser.add_argument("--hygiene-a", type=pathlib.Path)
    parser.add_argument("--hygiene-b", type=pathlib.Path)
    parser.add_argument("--out-json", type=pathlib.Path)
    args = parser.parse_args()

    rows_a = load_jsonl(args.arm_a)
    rows_b = load_jsonl(args.arm_b)
    arm_a = {unit_id(row): row for row in rows_a}
    arm_b = {unit_id(row): row for row in rows_b}
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    manifest_by_id = {str(row["kc_id"]): row for row in manifest.get("packets") or []}
    hygiene_a = hygiene_by_unit(args.hygiene_a)
    hygiene_b = hygiene_by_unit(args.hygiene_b)

    only_a = sorted(set(arm_a) - set(arm_b))
    only_b = sorted(set(arm_b) - set(arm_a))
    status_transitions: collections.Counter[str] = collections.Counter()
    hygiene_a_counts: collections.Counter[str] = collections.Counter()
    hygiene_b_counts: collections.Counter[str] = collections.Counter()
    comparisons = []
    for key in sorted(set(arm_a) & set(arm_b)):
        left, right = arm_a[key], arm_b[key]
        meta = manifest_by_id.get(key) or {}
        left_status, right_status = status(left), status(right)
        status_transitions["%s -> %s" % (left_status, right_status)] += 1
        hygiene_a_counts.update(hygiene_a.get(key) or {})
        hygiene_b_counts.update(hygiene_b.get(key) or {})
        left_ids = {str(value) for entry in payload(left).get("evidence_map") or []
                    if isinstance(entry, Mapping)
                    for value in entry.get("supporting_evidence_ids") or []}
        right_ids = {str(value) for entry in payload(right).get("evidence_map") or []
                     if isinstance(entry, Mapping)
                     for value in entry.get("supporting_evidence_ids") or []}
        comparisons.append({
            "kc_id": key,
            "canonical_name": right.get("canonical_name") or left.get("canonical_name"),
            "stratum": meta.get("stratum"),
            "packet_order_changed": bool(meta.get("order_changed")),
            "body_identical": body(left) == body(right),
            "status_a": left_status,
            "status_b": right_status,
            "body_chars_a": len(body(left)),
            "body_chars_b": len(body(right)),
            "relation_operators_a": len(RELATION_RE.findall(body(left))),
            "relation_operators_b": len(RELATION_RE.findall(body(right))),
            "evidence_map_entries_a": len(payload(left).get("evidence_map") or []),
            "evidence_map_entries_b": len(payload(right).get("evidence_map") or []),
            "distinct_cited_evidence_a": len(left_ids),
            "distinct_cited_evidence_b": len(right_ids),
            "technical_failure_a": technical_failure(left),
            "technical_failure_b": technical_failure(right),
            "validation_issues_a": list(left.get("validation_issues") or []),
            "validation_issues_b": list(right.get("validation_issues") or []),
            "hygiene_a": dict(sorted((hygiene_a.get(key) or {}).items())),
            "hygiene_b": dict(sorted((hygiene_b.get(key) or {}).items())),
            "body_a": body(left),
            "body_b": body(right),
        })

    no_op = [row for row in comparisons if not row["packet_order_changed"]]
    result = {
        "counts": {
            "arm_a_rows": len(rows_a),
            "arm_b_rows": len(rows_b),
            "only_in_arm_a": len(only_a),
            "only_in_arm_b": len(only_b),
            "technical_failures_a": sum(technical_failure(row) for row in rows_a),
            "technical_failures_b": sum(technical_failure(row) for row in rows_b),
            "bodies_changed": sum(not row["body_identical"] for row in comparisons),
            "no_op_packets": len(no_op),
            "no_op_packets_with_identical_bodies": sum(row["body_identical"] for row in no_op),
        },
        "status_transitions": dict(sorted(status_transitions.items())),
        "hygiene_counts_a": dict(sorted(hygiene_a_counts.items())),
        "hygiene_counts_b": dict(sorted(hygiene_b_counts.items())),
        "only_in_arm_a": only_a,
        "only_in_arm_b": only_b,
        "comparisons": comparisons,
    }
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    print(rendered)
    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(rendered + "\n", encoding="utf-8")
    structural_failure = bool(only_a or only_b or len(rows_a) != len(rows_b))
    deterministic_failure = any(not row["body_identical"] for row in no_op)
    return 1 if structural_failure or deterministic_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
