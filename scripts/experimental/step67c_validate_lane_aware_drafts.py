#!/usr/bin/env python3
import argparse
import datetime as dt
import json
from collections import Counter
from pathlib import Path
from typing import Any


def utc_run_id() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d_%H%M%S")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def lane_items(packet: dict[str, Any], lane_name: str) -> list[dict[str, Any]]:
    value = packet.get(lane_name)
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    return []


def item_id(item: dict[str, Any], fallback: str) -> str:
    for key in ("evidence_id", "id", "overlay_candidate_id"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return fallback


def collect_ids(packet: dict[str, Any]) -> dict[str, set[str]]:
    lane_names = [
        "definition_lane",
        "scope_lane",
        "context_lane",
        "quarantine_lane",
        "sibling_lane",
        "sibling_contrast_lane",
    ]

    ids: dict[str, set[str]] = {name: set() for name in lane_names}

    for lane_name in lane_names:
        for i, item in enumerate(lane_items(packet, lane_name), start=1):
            eid = item_id(item, f"{lane_name}:{i}")
            ids[lane_name].add(eid)

    all_items = packet.get("all_items")
    if isinstance(all_items, list):
        for i, item in enumerate(all_items, start=1):
            if not isinstance(item, dict):
                continue
            lane = str(item.get("lane") or "")
            eid = item_id(item, f"all:{i}")
            if lane == "definition_candidate":
                ids["definition_lane"].add(eid)
            elif lane == "scope_candidate":
                ids["scope_lane"].add(eid)
            elif lane == "context_candidate":
                ids["context_lane"].add(eid)
            elif lane == "sibling_contrast":
                ids["sibling_contrast_lane"].add(eid)
            elif lane == "quarantine_or_irrelevant":
                ids["quarantine_lane"].add(eid)

    return ids


def field_obj(parsed: dict[str, Any], name: str) -> dict[str, Any]:
    value = parsed.get(name)
    return value if isinstance(value, dict) else {}


def support_ids(field: dict[str, Any]) -> list[str]:
    ids = field.get("supporting_evidence_ids")
    if not isinstance(ids, list):
        return []
    return [str(x) for x in ids]


def validate_field(
    *,
    field_name: str,
    field: dict[str, Any],
    lane_id_sets: dict[str, set[str]],
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    status = str(field.get("status") or "")
    text = str(field.get("text") or "")
    ids = support_ids(field)

    definition_ids = lane_id_sets.get("definition_lane", set())
    scope_ids = lane_id_sets.get("scope_lane", set())
    context_ids = lane_id_sets.get("context_lane", set())
    quarantine_ids = lane_id_sets.get("quarantine_lane", set())
    sibling_ids = lane_id_sets.get("sibling_lane", set()) | lane_id_sets.get("sibling_contrast_lane", set())

    allowed_non_quarantine = definition_ids | scope_ids | context_ids

    if status not in {"grounded", "abstained"}:
        errors.append(f"{field_name}: invalid status {status!r}")
        return errors, warnings

    if status == "abstained":
        if text.strip():
            errors.append(f"{field_name}: abstained but text is non-empty")
        if ids:
            errors.append(f"{field_name}: abstained but support ids are non-empty {ids}")
        return errors, warnings

    if status == "grounded":
        if not text.strip():
            errors.append(f"{field_name}: grounded but text is empty")
        if not ids:
            errors.append(f"{field_name}: grounded but support ids are empty")

        invalid = [x for x in ids if x not in allowed_non_quarantine]
        if invalid:
            errors.append(f"{field_name}: support ids not in non-quarantine lanes {invalid}")

        quarantined = [x for x in ids if x in quarantine_ids]
        if quarantined:
            errors.append(f"{field_name}: support ids cite quarantine lane {quarantined}")

        sibling = [x for x in ids if x in sibling_ids]
        if sibling:
            errors.append(f"{field_name}: support ids cite sibling or negative contrast lane {sibling}")

        if field_name == "definition":
            if not any(x in definition_ids for x in ids):
                errors.append("definition: grounded definition lacks definition_lane support")
            non_definition_support = [x for x in ids if x in scope_ids or x in context_ids]
            if non_definition_support:
                warnings.append(f"definition: also cites non-definition lane support {non_definition_support}")

        if field_name == "scope":
            if not any(x in scope_ids for x in ids):
                warnings.append("scope: grounded scope has no scope_lane support")
            context_only = ids and all(x in context_ids for x in ids)
            if context_only:
                warnings.append("scope: grounded only from context_lane")

    return errors, warnings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lanes", required=True)
    ap.add_argument("--drafts", required=True)
    ap.add_argument("--out-root", default="data/processed/step67_sidecar_lane_validated")
    args = ap.parse_args()

    lanes_path = Path(args.lanes)
    drafts_path = Path(args.drafts)

    packets = load_jsonl(lanes_path)
    drafts = load_jsonl(drafts_path)

    packet_by_kc = {str(p.get("kc_id") or ""): p for p in packets}

    run_id = utc_run_id()
    out_dir = Path(args.out_root) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    issue_counter = Counter()
    status_counter = Counter()

    for draft in drafts:
        kc_id = str(draft.get("kc_id") or "")
        packet = packet_by_kc.get(kc_id)
        parsed = draft.get("parsed") if isinstance(draft.get("parsed"), dict) else {}

        errors: list[str] = []
        warnings: list[str] = []

        if packet is None:
            errors.append("missing lane packet for kc_id")
            lane_id_sets = {}
        else:
            lane_id_sets = collect_ids(packet)

        if not draft.get("ok"):
            errors.append(f"model call not ok: {draft.get('error') or ''}")

        parsed_kc_id = str(parsed.get("kc_id") or "")
        if parsed_kc_id != kc_id:
            errors.append(f"parsed kc_id mismatch parsed={parsed_kc_id!r} expected={kc_id!r}")

        definition = field_obj(parsed, "definition")
        scope = field_obj(parsed, "scope")

        d_errors, d_warnings = validate_field(
            field_name="definition",
            field=definition,
            lane_id_sets=lane_id_sets,
        )
        s_errors, s_warnings = validate_field(
            field_name="scope",
            field=scope,
            lane_id_sets=lane_id_sets,
        )

        errors.extend(d_errors)
        warnings.extend(d_warnings)
        errors.extend(s_errors)
        warnings.extend(s_warnings)

        status_counter[f"definition::{definition.get('status')}"] += 1
        status_counter[f"scope::{scope.get('status')}"] += 1

        for e in errors:
            issue_counter[f"ERROR::{e}"] += 1
        for w in warnings:
            issue_counter[f"WARNING::{w}"] += 1

        rows.append({
            "kc_id": kc_id,
            "canonical_name": draft.get("canonical_name"),
            "model_call_ok": bool(draft.get("ok")),
            "definition_status": definition.get("status"),
            "definition_text": definition.get("text"),
            "definition_supporting_evidence_ids": support_ids(definition),
            "scope_status": scope.get("status"),
            "scope_text": scope.get("text"),
            "scope_supporting_evidence_ids": support_ids(scope),
            "lane_id_sets": {k: sorted(v) for k, v in lane_id_sets.items()},
            "errors": errors,
            "warnings": warnings,
        })

    valid_row_count = sum(1 for r in rows if not r["errors"])
    error_row_count = sum(1 for r in rows if r["errors"])
    warning_row_count = sum(1 for r in rows if r["warnings"])

    summary = {
        "stage": "step67c_validate_lane_aware_drafts",
        "run_id": run_id,
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "lanes_path": lanes_path.as_posix(),
        "drafts_path": drafts_path.as_posix(),
        "out_dir": out_dir.as_posix(),
        "packet_count": len(packets),
        "draft_row_count": len(drafts),
        "valid_row_count": valid_row_count,
        "error_row_count": error_row_count,
        "warning_row_count": warning_row_count,
        "status_counter": dict(status_counter),
        "issue_counter": dict(issue_counter),
        "validation_policy": {
            "definition": "grounded definition must cite at least one definition_lane id and no quarantine/sibling id",
            "scope": "grounded scope may cite scope, definition, or context lane ids; missing scope_lane support is warning",
            "abstained": "text and support ids must be empty",
        },
        "active_pointer_policy": "do_not_update_current_alias_or_active_pointer",
    }

    summary_path = out_dir / "summary.json"
    rows_path = out_dir / "validation_rows.jsonl"
    md_path = out_dir / "review_snapshot.md"

    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    write_jsonl(rows_path, rows)

    md = []
    md.append("# Step 6.7C lane-aware validation snapshot")
    md.append("")
    md.append(f"- Lanes: `{lanes_path.as_posix()}`")
    md.append(f"- Drafts: `{drafts_path.as_posix()}`")
    md.append(f"- Draft rows: `{len(drafts)}`")
    md.append(f"- Valid rows: `{valid_row_count}`")
    md.append(f"- Error rows: `{error_row_count}`")
    md.append(f"- Warning rows: `{warning_row_count}`")
    md.append("")
    md.append("## Summary")
    md.append("")
    md.append("```json")
    md.append(json.dumps(summary, indent=2, ensure_ascii=False))
    md.append("```")
    md.append("")
    md.append("## Rows")
    md.append("")

    for row in rows:
        md.append(f"### {row['kc_id']} | {row['canonical_name']}")
        md.append("")
        md.append(f"- model_call_ok: `{row['model_call_ok']}`")
        md.append(f"- definition_status: `{row['definition_status']}`")
        md.append(f"- definition_text: {row['definition_text'] or ''}")
        md.append(f"- definition_supporting_evidence_ids: `{row['definition_supporting_evidence_ids']}`")
        md.append(f"- scope_status: `{row['scope_status']}`")
        md.append(f"- scope_text: {row['scope_text'] or ''}")
        md.append(f"- scope_supporting_evidence_ids: `{row['scope_supporting_evidence_ids']}`")
        md.append(f"- errors: `{row['errors']}`")
        md.append(f"- warnings: `{row['warnings']}`")
        md.append("")

    md_path.write_text("\n".join(md), encoding="utf-8")

    print("STEP67C_LANE_VALIDATION_RUN_ID =", run_id)
    print("STEP67C_LANE_VALIDATION_DIR =", out_dir.as_posix())
    print("STEP67C_LANE_SUMMARY_JSON =", summary_path.as_posix())
    print("STEP67C_LANE_VALIDATION_ROWS =", rows_path.as_posix())
    print("STEP67C_LANE_REVIEW_SNAPSHOT_MD =", md_path.as_posix())
    print("draft_row_count =", len(drafts))
    print("valid_row_count =", valid_row_count)
    print("error_row_count =", error_row_count)
    print("warning_row_count =", warning_row_count)
    print("status_counter =", json.dumps(dict(status_counter), ensure_ascii=False))
    print("issue_counter =", json.dumps(dict(issue_counter), ensure_ascii=False))
    print("STEP67C_LANE_AWARE_VALIDATION_DONE")

    return 0 if error_row_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
