#!/usr/bin/env python3
import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def words(text: Any) -> list[str]:
    return re.findall(r"[a-zA-Z0-9_]+", str(text or "").lower())


def exact_copy_flag(text: str, evidence_texts: list[str]) -> bool:
    nt = norm(text)
    if len(nt) < 80:
        return False
    token_count = len(words(nt))
    if token_count < 10:
        return False
    for ev in evidence_texts:
        nev = norm(ev)
        if nt and nt in nev:
            return True
    return False


def validate_field(
    field_name: str,
    field: Any,
    valid_evidence_ids: set[str],
    evidence_texts: list[str],
) -> tuple[list[str], list[str]]:
    errors = []
    warnings = []

    if not isinstance(field, dict):
        return [f"{field_name}: field is not an object"], warnings

    status = str(field.get("status") or "").strip().lower()
    text = str(field.get("text") or "").strip()
    support = field.get("supporting_evidence_ids") or []

    if status not in {"grounded", "abstained"}:
        errors.append(f"{field_name}: invalid status {status!r}")

    if status == "grounded":
        if not text:
            errors.append(f"{field_name}: grounded field has empty text")
        if not isinstance(support, list) or not support:
            errors.append(f"{field_name}: grounded field has no supporting_evidence_ids")
        else:
            invalid = [str(x) for x in support if str(x) not in valid_evidence_ids]
            if invalid:
                errors.append(f"{field_name}: invalid supporting evidence ids {invalid}")
        if exact_copy_flag(text, evidence_texts):
            errors.append(f"{field_name}: exact source-copy flag")
    elif status == "abstained":
        if text:
            errors.append(f"{field_name}: abstained field should have empty text")
        reason = str(field.get("abstention_reason") or "").strip()
        if not reason:
            warnings.append(f"{field_name}: abstained field has no abstention_reason")

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packets", required=True)
    parser.add_argument("--drafts", required=True)
    parser.add_argument("--out-root", default="data/processed/step67_sidecar_validated")
    args = parser.parse_args()

    packets_path = Path(args.packets)
    drafts_path = Path(args.drafts)
    packets = read_jsonl(packets_path)
    drafts = read_jsonl(drafts_path)

    packet_by_kc = {str(p.get("kc_id") or ""): p for p in packets}
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    out_dir = Path(args.out_root) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    validation_rows = []
    issue_counter = Counter()
    status_counter = Counter()

    for row in drafts:
        kc_id = str(row.get("kc_id") or "")
        packet = packet_by_kc.get(kc_id)
        parsed = row.get("parsed")
        errors = []
        warnings = []

        if not row.get("ok"):
            errors.append(f"model_call_failed: {row.get('error')}")
        if packet is None:
            errors.append("missing_source_packet")
            valid_ids = set()
            evidence_texts = []
        else:
            valid_ids = {str(ev.get("evidence_id")) for ev in (packet.get("evidence") or [])}
            evidence_texts = [str(ev.get("text") or "") for ev in (packet.get("evidence") or [])]

        if not isinstance(parsed, dict):
            errors.append("parsed_output_missing_or_not_object")
            parsed = {}

        if str(parsed.get("kc_id") or "") != kc_id:
            errors.append(f"kc_id_mismatch parsed={parsed.get('kc_id')!r} expected={kc_id!r}")

        if parsed.get("kc_specific_criteria") not in ([], None):
            errors.append("kc_specific_criteria_nonempty_before_expert_review")

        for field_name in ["definition", "scope"]:
            e, w = validate_field(field_name, parsed.get(field_name), valid_ids, evidence_texts)
            errors.extend(e)
            warnings.extend(w)

        definition_status = ""
        scope_status = ""
        if isinstance(parsed.get("definition"), dict):
            definition_status = str(parsed["definition"].get("status") or "")
        if isinstance(parsed.get("scope"), dict):
            scope_status = str(parsed["scope"].get("status") or "")

        status_counter[f"definition::{definition_status}"] += 1
        status_counter[f"scope::{scope_status}"] += 1

        for issue in errors:
            issue_counter[f"ERROR::{issue}"] += 1
        for issue in warnings:
            issue_counter[f"WARNING::{issue}"] += 1

        validation_rows.append({
            "kc_id": kc_id,
            "canonical_name": row.get("canonical_name"),
            "model_call_ok": bool(row.get("ok")),
            "thinking_present": bool(row.get("thinking_present")),
            "thinking_char_count": row.get("thinking_char_count"),
            "definition_status": definition_status,
            "definition_text": (parsed.get("definition") or {}).get("text") if isinstance(parsed.get("definition"), dict) else "",
            "scope_status": scope_status,
            "scope_text": (parsed.get("scope") or {}).get("text") if isinstance(parsed.get("scope"), dict) else "",
            "errors": errors,
            "warnings": warnings,
        })

    summary = {
        "stage": "step67c_validate_onepass_drafts",
        "run_id": run_id,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "packets_path": packets_path.as_posix(),
        "drafts_path": drafts_path.as_posix(),
        "out_dir": out_dir.as_posix(),
        "packet_count": len(packets),
        "draft_row_count": len(drafts),
        "valid_row_count": sum(1 for r in validation_rows if not r["errors"]),
        "error_row_count": sum(1 for r in validation_rows if r["errors"]),
        "warning_row_count": sum(1 for r in validation_rows if r["warnings"]),
        "status_counter": dict(status_counter),
        "issue_counter": dict(issue_counter),
        "active_pointer_policy": "do_not_update_current_alias_or_active_pointer",
    }

    validation_path = out_dir / "validation_rows.jsonl"
    for item in validation_rows:
        with validation_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    md = []
    md.append("# Step 6.7C one-pass validation snapshot")
    md.append("")
    md.append(f"- Packets: `{packets_path.as_posix()}`")
    md.append(f"- Drafts: `{drafts_path.as_posix()}`")
    md.append(f"- Draft rows: `{len(drafts)}`")
    md.append(f"- Valid rows: `{summary['valid_row_count']}`")
    md.append(f"- Error rows: `{summary['error_row_count']}`")
    md.append(f"- Warning rows: `{summary['warning_row_count']}`")
    md.append("")
    md.append("## Status counter")
    md.append("")
    md.append("```json")
    md.append(json.dumps(summary["status_counter"], indent=2, ensure_ascii=False))
    md.append("```")
    md.append("")
    md.append("## Issue counter")
    md.append("")
    md.append("```json")
    md.append(json.dumps(summary["issue_counter"], indent=2, ensure_ascii=False))
    md.append("```")
    md.append("")
    md.append("## Rows")
    md.append("")
    for item in validation_rows:
        md.append(f"### {item['kc_id']} | {item.get('canonical_name')}")
        md.append("")
        md.append(f"- model_call_ok: `{item['model_call_ok']}`")
        md.append(f"- thinking_present: `{item['thinking_present']}`")
        md.append(f"- thinking_char_count: `{item['thinking_char_count']}`")
        md.append(f"- definition_status: `{item['definition_status']}`")
        md.append(f"- definition_text: {item['definition_text']}")
        md.append(f"- scope_status: `{item['scope_status']}`")
        md.append(f"- scope_text: {item['scope_text']}")
        md.append(f"- errors: `{item['errors']}`")
        md.append(f"- warnings: `{item['warnings']}`")
        md.append("")
    md_path = out_dir / "review_snapshot.md"
    md_path.write_text("\n".join(md), encoding="utf-8")

    print("STEP67C_VALIDATION_RUN_ID =", run_id)
    print("STEP67C_VALIDATION_DIR =", out_dir.as_posix())
    print("STEP67C_SUMMARY_JSON =", summary_path.as_posix())
    print("STEP67C_VALIDATION_ROWS =", validation_path.as_posix())
    print("STEP67C_REVIEW_SNAPSHOT_MD =", md_path.as_posix())
    print("draft_row_count =", len(drafts))
    print("valid_row_count =", summary["valid_row_count"])
    print("error_row_count =", summary["error_row_count"])
    print("warning_row_count =", summary["warning_row_count"])
    print("status_counter =", json.dumps(summary["status_counter"], ensure_ascii=False))
    print("issue_counter =", json.dumps(summary["issue_counter"], ensure_ascii=False))
    print("STEP67C_ONEPASS_VALIDATION_DONE")
    return 0 if summary["error_row_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
