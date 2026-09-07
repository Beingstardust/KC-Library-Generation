#!/usr/bin/env python3
"""Build descriptive, non-judgmental summaries for R9 packet/draft experiment arms.

This is intentionally not a quality judge. It records the mechanically checkable surface:
packet counts, evidence volume, support-state distribution, draft statuses, validation failures,
and optional DOS budget-matching token diagnostics.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib
import statistics
from collections import Counter
from typing import Any, Iterable, Mapping


def load_jsonl(path: pathlib.Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def unit_id(row: Mapping[str, Any]) -> str:
    return str(row.get("knowledge_unit_id") or row.get("kc_id") or row.get("topic_id") or "")


def canonical_name(row: Mapping[str, Any]) -> str:
    return " ".join(str(row.get("canonical_name") or "").split())


def stats(values: Iterable[float]) -> dict:
    xs = list(values)
    if not xs:
        return {"n": 0, "min": None, "mean": None, "median": None, "max": None}
    return {
        "n": len(xs),
        "min": min(xs),
        "mean": statistics.fmean(xs),
        "median": statistics.median(xs),
        "max": max(xs),
    }


def evidence_text(ev: Mapping[str, Any]) -> str:
    return str(ev.get("text") or ev.get("source_block_text") or "")


def extract_draft_object(row: Mapping[str, Any]) -> tuple[dict | None, str | None]:
    obj = row.get("draft")
    if isinstance(obj, dict) and obj:
        return obj, None
    for field in ("raw_response", "repair_raw_response", "parse_repair_raw_response"):
        raw = row.get(field)
        if isinstance(raw, dict) and raw:
            return raw, None
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
            except Exception as exc:  # pragma: no cover - diagnostic path
                return None, f"unparseable_{field}:{exc.__class__.__name__}"
            if isinstance(parsed, dict):
                return parsed, None
            return None, f"{field}_not_object"
    return None, "no_draft_and_no_raw_response"


def draft_payload(obj: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = obj.get("contextual_kc_draft") or obj.get("contextual_topic_draft") or {}
    return payload if isinstance(payload, Mapping) else {}


def evidence_map_count(payload: Mapping[str, Any], obj: Mapping[str, Any]) -> int:
    evmap = payload.get("evidence_map")
    if evmap is None:
        evmap = obj.get("evidence_map")
    if isinstance(evmap, list):
        return len(evmap)
    if isinstance(evmap, Mapping):
        return len(evmap)
    return 0


def summarize_budget_csv(path: pathlib.Path | None) -> dict | None:
    if path is None:
        return None
    rows: list[dict] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    numeric_fields = [
        "proposed_evidence_tokens",
        "dos_full_tokens",
        "dos_matched_tokens",
        "token_difference_vs_proposed",
        "pct_difference_vs_proposed",
        "dos_matched_to_proposed_token_ratio",
    ]
    out: dict[str, Any] = {"path": str(path), "sha256": sha256_file(path), "rows": len(rows), "fields": {}}
    for field in numeric_fields:
        vals: list[float] = []
        for row in rows:
            raw = row.get(field)
            if raw in (None, ""):
                continue
            try:
                vals.append(float(raw))
            except ValueError:
                continue
        out["fields"][field] = stats(vals)
    return out


def summarize_arm(label: str, packets_path: pathlib.Path, drafts_path: pathlib.Path) -> tuple[dict, list[dict]]:
    packets = load_jsonl(packets_path)
    drafts = load_jsonl(drafts_path)
    packets_by_id = {unit_id(p): p for p in packets}
    drafts_by_id = {unit_id(d): d for d in drafts}

    support_states = Counter()
    evidence_lanes = Counter()
    shape_tags = Counter()
    evidence_counts: list[int] = []
    evidence_chars: list[int] = []
    distinct_doc_counts: list[int] = []

    for packet in packets:
        support_states[str(packet.get("packet_support_state") or packet.get("support_state") or "unspecified")] += 1
        evidence = [e for e in (packet.get("evidence_for_synthesis") or []) if isinstance(e, Mapping)]
        evidence_counts.append(len(evidence))
        evidence_chars.append(sum(len(evidence_text(e)) for e in evidence))
        docs = {str(e.get("doc_id")) for e in evidence if e.get("doc_id") not in (None, "")}
        distinct_doc_counts.append(len(docs))
        for ev in evidence:
            evidence_lanes[str(ev.get("evidence_lane") or "unspecified")] += 1
            for tag in ev.get("shape_tags") or ev.get("shapes") or []:
                shape_tags[str(tag)] += 1

    status_counts = Counter()
    hard_failures: list[dict] = []
    text_chars: list[int] = []
    evidence_map_counts: list[int] = []
    per_unit: list[dict] = []

    for uid, packet in packets_by_id.items():
        draft_row = drafts_by_id.get(uid)
        status = "missing_row"
        text = ""
        evmap_n = 0
        error = None
        if draft_row is None:
            error = "row_missing"
            hard_failures.append({"unit_id": uid, "reason": error})
        elif draft_row.get("runtime_error"):
            error = f"runtime_error:{str(draft_row.get('runtime_error'))[:120]}"
            hard_failures.append({"unit_id": uid, "reason": error})
        else:
            obj, err = extract_draft_object(draft_row)
            if obj is None:
                error = err or "draft_parse_failed"
                hard_failures.append({"unit_id": uid, "reason": error})
            else:
                payload = draft_payload(obj)
                status = str(payload.get("status") or "unspecified").lower()
                text = str(payload.get("text") or "").strip()
                evmap_n = evidence_map_count(payload, obj)
                text_chars.append(len(text))
                evidence_map_counts.append(evmap_n)
        status_counts[status] += 1
        evidence = [e for e in (packet.get("evidence_for_synthesis") or []) if isinstance(e, Mapping)]
        per_unit.append({
            "arm": label,
            "unit_id": uid,
            "canonical_name": canonical_name(packet),
            "packet_support_state": packet.get("packet_support_state") or packet.get("support_state") or "",
            "evidence_items": len(evidence),
            "evidence_chars": sum(len(evidence_text(e)) for e in evidence),
            "distinct_docs": len({str(e.get("doc_id")) for e in evidence if e.get("doc_id") not in (None, "")}),
            "draft_status": status,
            "draft_text_chars": len(text),
            "evidence_map_entries": evmap_n,
            "hard_failure": error or "",
        })

    summary = {
        "label": label,
        "packets_jsonl": str(packets_path),
        "packets_sha256": sha256_file(packets_path),
        "drafts_jsonl": str(drafts_path),
        "drafts_sha256": sha256_file(drafts_path),
        "packet_rows": len(packets),
        "draft_rows": len(drafts),
        "missing_draft_rows": max(len(packets) - len(set(packets_by_id) & set(drafts_by_id)), 0),
        "support_states": dict(sorted(support_states.items())),
        "draft_statuses": dict(sorted(status_counts.items())),
        "hard_failures": hard_failures,
        "evidence_items": stats(evidence_counts),
        "evidence_chars": stats(evidence_chars),
        "distinct_docs": stats(distinct_doc_counts),
        "draft_text_chars": stats(text_chars),
        "evidence_map_entries": stats(evidence_map_counts),
        "evidence_lanes": dict(evidence_lanes.most_common()),
        "shape_tags": dict(shape_tags.most_common()),
    }
    return summary, per_unit


def parse_arm_arg(value: str) -> tuple[str, pathlib.Path, pathlib.Path]:
    parts = value.split("|")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("--arm must be label|packets_jsonl|drafts_jsonl")
    return parts[0], pathlib.Path(parts[1]), pathlib.Path(parts[2])


def parse_budget_arg(value: str) -> tuple[str, pathlib.Path]:
    parts = value.split("|")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("--budget-manifest must be label|csv_path")
    return parts[0], pathlib.Path(parts[1])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--arm", action="append", required=True, type=parse_arm_arg,
                    help="label|packets_jsonl|drafts_jsonl; repeat for every arm")
    ap.add_argument("--budget-manifest", action="append", default=[], type=parse_budget_arg,
                    help="label|dos_budget_matching_manifest.csv; optional, repeatable")
    ap.add_argument("--out-dir", required=True, type=pathlib.Path)
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    budget_by_label = {label: path for label, path in args.budget_manifest}

    summaries: list[dict] = []
    all_per_unit: list[dict] = []
    for label, packets_path, drafts_path in args.arm:
        summary, per_unit = summarize_arm(label, packets_path, drafts_path)
        summary["budget_manifest"] = summarize_budget_csv(budget_by_label.get(label))
        summaries.append(summary)
        all_per_unit.extend(per_unit)

    summary_obj = {"arms": summaries}
    (args.out_dir / "summary.json").write_text(
        json.dumps(summary_obj, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )

    fields = list(all_per_unit[0].keys()) if all_per_unit else []
    with (args.out_dir / "per_unit_metrics.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(all_per_unit)

    lines = ["# R9 Experiment Descriptive Summary", ""]
    for arm in summaries:
        lines.append(f"## {arm['label']}")
        lines.append(f"- packets: {arm['packet_rows']} rows")
        lines.append(f"- drafts: {arm['draft_rows']} rows")
        lines.append(f"- draft statuses: {arm['draft_statuses']}")
        lines.append(f"- support states: {arm['support_states']}")
        lines.append(f"- hard failures: {len(arm['hard_failures'])}")
        lines.append(f"- evidence chars mean: {arm['evidence_chars']['mean']}")
        if arm.get("budget_manifest"):
            ratio = arm["budget_manifest"]["fields"]["dos_matched_to_proposed_token_ratio"]
            lines.append(f"- DOS matched/proposed token ratio mean: {ratio['mean']}")
        lines.append("")
    (args.out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"summary -> {args.out_dir / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
