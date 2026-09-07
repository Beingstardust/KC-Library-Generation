#!/usr/bin/env python3
"""Build R9 DOS full-vs-matched diagnostic reports.

This report is descriptive only. It joins the frozen DOS full outputs, the strict
Proposed-budget-matched DOS outputs, and the matching manifest so known cases can be
inspected without changing any R8 retrieval or drafting behavior.
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
from typing import Any, Iterable, Mapping


DEFAULT_KNOWN_CASES = [
    "Spearman Rank Correlation",
    "Sequential Forward Generation",
    "Cost Matrix",
    "F-Measure",
    "Classification Threshold",
    "Confidence Interval for Accuracy",
    "Threshold Effect on Precision, Recall, F1",
    "ID3 Algorithm",
    "Ranker",
    "External Index: Entropy",
    "Role of Test Sample Size",
]

FLAG_FIELDS = [
    "whether_defining_formula_was_lost",
    "whether_procedure_block_was_lost",
    "whether_definition_passage_was_lost",
]


def load_jsonl(path: pathlib.Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def load_csv(path: pathlib.Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def unit_id(row: Mapping[str, Any]) -> str:
    return str(row.get("knowledge_unit_id") or row.get("kc_id") or row.get("topic_id") or "")


def clean_name(value: Any) -> str:
    return " ".join(str(value or "").split())


def norm_name(value: Any) -> str:
    return clean_name(value).casefold()


def as_int(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_draft_object(row: Mapping[str, Any] | None) -> tuple[dict | None, str | None]:
    if row is None:
        return None, "missing_row"
    if row.get("runtime_error"):
        return None, f"runtime_error:{str(row.get('runtime_error'))[:160]}"
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
            except Exception as exc:
                return None, f"unparseable_{field}:{exc.__class__.__name__}"
            if isinstance(parsed, dict):
                return parsed, None
            return None, f"{field}_not_object"
    return None, "no_draft_and_no_raw_response"


def draft_payload(obj: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if obj is None:
        return {}
    payload = obj.get("contextual_kc_draft") or obj.get("contextual_topic_draft") or {}
    return payload if isinstance(payload, Mapping) else {}


def draft_summary(row: Mapping[str, Any] | None) -> dict[str, str]:
    obj, err = extract_draft_object(row)
    if obj is None:
        return {"status": "hard_failure" if err != "missing_row" else "missing_row", "text": "", "hard_failure": err or ""}
    payload = draft_payload(obj)
    return {
        "status": str(payload.get("status") or "unspecified").lower(),
        "text": str(payload.get("text") or "").strip(),
        "hard_failure": "",
    }


def snippet(text: str, limit: int = 360) -> str:
    one_line = " ".join(str(text or "").split())
    if len(one_line) <= limit:
        return one_line
    return one_line[: limit - 3].rstrip() + "..."


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"true", "1", "yes"}


def lost_chunks(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    chunks = row.get("evidence_chunks_lost_due_to_matching") or []
    return [dict(c) for c in chunks if isinstance(c, Mapping)]


def build_report_row(
    kc_id: str,
    fvm_row: Mapping[str, Any],
    budget_row: Mapping[str, Any],
    full_draft: Mapping[str, Any] | None,
    matched_draft: Mapping[str, Any] | None,
    case_group: str,
) -> dict[str, Any]:
    full = draft_summary(full_draft)
    matched = draft_summary(matched_draft)
    chunks = lost_chunks(fvm_row)
    out: dict[str, Any] = {
        "case_group": case_group,
        "kc_id": kc_id,
        "canonical_name": clean_name(fvm_row.get("canonical_name") or budget_row.get("canonical_name")),
        "proposed_budget_tokens": as_int(fvm_row.get("proposed_budget_tokens") or budget_row.get("proposed_evidence_tokens")),
        "dos_full_evidence_tokens": as_int(fvm_row.get("dos_full_evidence_tokens") or budget_row.get("dos_full_tokens")),
        "dos_matched_evidence_tokens": as_int(fvm_row.get("dos_matched_evidence_tokens") or budget_row.get("dos_matched_tokens")),
        "token_difference_vs_proposed": as_int(budget_row.get("token_difference_vs_proposed")),
        "pct_difference_vs_proposed": as_float(budget_row.get("pct_difference_vs_proposed")),
        "dos_matched_to_proposed_token_ratio": as_float(budget_row.get("dos_matched_to_proposed_token_ratio")),
        "dos_full_status": full["status"],
        "dos_matched_status": matched["status"],
        "dos_full_hard_failure": full["hard_failure"],
        "dos_matched_hard_failure": matched["hard_failure"],
        "dos_full_draft": full["text"],
        "dos_matched_draft": matched["text"],
        "lost_chunk_count": len(chunks),
        "lost_chunk_indices": json.dumps([c.get("dos_rag_chunk_index") for c in chunks], ensure_ascii=False),
        "lost_chunk_ranks": json.dumps([c.get("dos_rag_pre_reorder_rank") for c in chunks], ensure_ascii=False),
        "lost_chunk_snippets_json": json.dumps(
            [
                {
                    "dos_rag_pre_reorder_rank": c.get("dos_rag_pre_reorder_rank"),
                    "dos_rag_chunk_index": c.get("dos_rag_chunk_index"),
                    "snippet": snippet(str(c.get("text") or "")),
                }
                for c in chunks[:10]
            ],
            ensure_ascii=False,
        ),
    }
    for field in FLAG_FIELDS:
        out[field] = boolish(fvm_row.get(field))
    return out


def find_known_ids(rows_by_id: Mapping[str, Mapping[str, Any]], known_names: Iterable[str]) -> tuple[list[str], list[str]]:
    by_exact_name = {norm_name(row.get("canonical_name")): kc_id for kc_id, row in rows_by_id.items()}
    found: list[str] = []
    missing: list[str] = []
    for name in known_names:
        key = norm_name(name)
        kc_id = by_exact_name.get(key)
        if kc_id is None:
            matches = [
                candidate_id
                for candidate_id, row in rows_by_id.items()
                if key in norm_name(row.get("canonical_name")) or norm_name(row.get("canonical_name")) in key
            ]
            kc_id = sorted(matches)[0] if matches else None
        if kc_id is None:
            missing.append(name)
        elif kc_id not in found:
            found.append(kc_id)
    return found, missing


def select_controls(report_rows: list[dict[str, Any]], known_ids: set[str], count: int) -> list[str]:
    strict_candidates = []
    relaxed_candidates = []
    for row in report_rows:
        if row["kc_id"] in known_ids:
            continue
        if row["dos_full_status"] != "grounded" or row["dos_matched_status"] != "grounded":
            continue
        if any(bool(row[field]) for field in FLAG_FIELDS):
            relaxed_candidates.append(row)
        else:
            strict_candidates.append(row)

    strict_candidates.sort(
        key=lambda r: (abs(float(r.get("pct_difference_vs_proposed") or 0.0)), r["canonical_name"])
    )
    relaxed_candidates.sort(
        key=lambda r: (
            int(r.get("lost_chunk_count") or 0),
            abs(float(r.get("pct_difference_vs_proposed") or 0.0)),
            r["canonical_name"],
        )
    )
    picked = strict_candidates[:count]
    if len(picked) < count:
        picked.extend(relaxed_candidates[: count - len(picked)])
    return [row["kc_id"] for row in picked[:count]]


def format_num(value: Any, digits: int = 3) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def markdown_case(row: Mapping[str, Any], max_lost_chunks: int) -> list[str]:
    chunks = json.loads(str(row.get("lost_chunk_snippets_json") or "[]"))
    flags = ", ".join(f"{field}={row.get(field)}" for field in FLAG_FIELDS)
    lines = [
        f"### {row['canonical_name']} ({row['kc_id']})",
        f"- case group: {row['case_group']}",
        (
            "- budgets: "
            f"Proposed={row['proposed_budget_tokens']}, "
            f"DOS full={row['dos_full_evidence_tokens']}, "
            f"DOS matched={row['dos_matched_evidence_tokens']}, "
            f"matched/proposed={format_num(row.get('dos_matched_to_proposed_token_ratio'))}, "
            f"pct diff={format_num(row.get('pct_difference_vs_proposed'))}"
        ),
        (
            "- statuses: "
            f"DOS full={row['dos_full_status']}, "
            f"DOS matched={row['dos_matched_status']}"
        ),
        f"- lost chunks: {row['lost_chunk_count']}; {flags}",
    ]
    if row.get("dos_full_hard_failure") or row.get("dos_matched_hard_failure"):
        lines.append(
            "- hard failures: "
            f"full={row.get('dos_full_hard_failure') or 'none'}; "
            f"matched={row.get('dos_matched_hard_failure') or 'none'}"
        )
    for chunk in chunks[:max_lost_chunks]:
        lines.append(
            "- lost chunk "
            f"rank={chunk.get('dos_rag_pre_reorder_rank')} "
            f"idx={chunk.get('dos_rag_chunk_index')}: {chunk.get('snippet')}"
        )
    lines.append("")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--full-vs-matched-jsonl", required=True, type=pathlib.Path)
    ap.add_argument("--budget-csv", required=True, type=pathlib.Path)
    ap.add_argument("--dos-full-drafts-jsonl", required=True, type=pathlib.Path)
    ap.add_argument("--dos-matched-drafts-jsonl", required=True, type=pathlib.Path)
    ap.add_argument("--out-dir", required=True, type=pathlib.Path)
    ap.add_argument("--known-case", action="append", default=[])
    ap.add_argument("--control-count", type=int, default=5)
    ap.add_argument("--max-lost-chunks-md", type=int, default=3)
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    known_names = args.known_case or DEFAULT_KNOWN_CASES

    fvm_rows = load_jsonl(args.full_vs_matched_jsonl)
    budget_rows = load_csv(args.budget_csv)
    full_drafts = load_jsonl(args.dos_full_drafts_jsonl)
    matched_drafts = load_jsonl(args.dos_matched_drafts_jsonl)

    fvm_by_id = {unit_id(row): row for row in fvm_rows}
    budget_by_id = {str(row.get("kc_id") or ""): row for row in budget_rows}
    full_drafts_by_id = {unit_id(row): row for row in full_drafts}
    matched_drafts_by_id = {unit_id(row): row for row in matched_drafts}

    all_rows: list[dict[str, Any]] = []
    for kc_id, fvm_row in fvm_by_id.items():
        budget_row = budget_by_id.get(kc_id, {})
        all_rows.append(
            build_report_row(
                kc_id=kc_id,
                fvm_row=fvm_row,
                budget_row=budget_row,
                full_draft=full_drafts_by_id.get(kc_id),
                matched_draft=matched_drafts_by_id.get(kc_id),
                case_group="all",
            )
        )

    known_ids, missing_known = find_known_ids(fvm_by_id, known_names)
    rows_by_id = {row["kc_id"]: row for row in all_rows}
    control_ids = select_controls(all_rows, set(known_ids), args.control_count)

    selected_rows: list[dict[str, Any]] = []
    for kc_id in known_ids:
        row = dict(rows_by_id[kc_id])
        row["case_group"] = "known_advantage_case"
        selected_rows.append(row)
    for kc_id in control_ids:
        row = dict(rows_by_id[kc_id])
        row["case_group"] = "auto_healthy_control"
        selected_rows.append(row)

    csv_path = args.out_dir / "dos_full_vs_matched_manifest.csv"
    fieldnames = [
        "case_group",
        "kc_id",
        "canonical_name",
        "proposed_budget_tokens",
        "dos_full_evidence_tokens",
        "dos_matched_evidence_tokens",
        "token_difference_vs_proposed",
        "pct_difference_vs_proposed",
        "dos_matched_to_proposed_token_ratio",
        "dos_full_status",
        "dos_matched_status",
        "dos_full_hard_failure",
        "dos_matched_hard_failure",
        "dos_full_draft",
        "dos_matched_draft",
        "lost_chunk_count",
        "whether_defining_formula_was_lost",
        "whether_procedure_block_was_lost",
        "whether_definition_passage_was_lost",
        "lost_chunk_indices",
        "lost_chunk_ranks",
        "lost_chunk_snippets_json",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(selected_rows)

    cases_json = args.out_dir / "known_advantage_cases.json"
    cases_json.write_text(
        json.dumps(
            {
                "known_case_names_requested": known_names,
                "known_case_ids_found": known_ids,
                "known_case_names_missing": missing_known,
                "auto_healthy_control_ids": control_ids,
                "selected_rows": selected_rows,
            },
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    md_lines = [
        "# R9 DOS Full-vs-Matched Diagnostics",
        "",
        "This is a descriptive report for inspection. It does not judge quality and does not change any pipeline output.",
        "",
        f"- full-vs-matched manifest: `{args.full_vs_matched_jsonl}`",
        f"- budget manifest: `{args.budget_csv}`",
        f"- DOS full drafts: `{args.dos_full_drafts_jsonl}`",
        f"- DOS matched drafts: `{args.dos_matched_drafts_jsonl}`",
        f"- known cases found: {len(known_ids)} / {len(known_names)}",
        f"- healthy controls selected: {len(control_ids)}",
        "",
    ]
    if missing_known:
        md_lines.append("## Missing Known Case Names")
        md_lines.append("")
        for name in missing_known:
            md_lines.append(f"- {name}")
        md_lines.append("")

    md_lines.append("## Known Advantage Cases")
    md_lines.append("")
    for row in selected_rows:
        if row["case_group"] == "known_advantage_case":
            md_lines.extend(markdown_case(row, args.max_lost_chunks_md))

    md_lines.append("## Auto Healthy Controls")
    md_lines.append("")
    for row in selected_rows:
        if row["case_group"] == "auto_healthy_control":
            md_lines.extend(markdown_case(row, args.max_lost_chunks_md))

    md_path = args.out_dir / "known_advantage_case_analysis.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"diagnostic csv -> {csv_path}")
    print(f"diagnostic md -> {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
