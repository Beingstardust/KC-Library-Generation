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
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
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
            return value.strip()
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
            ids[lane_name].add(item_id(item, f"{lane_name}:{i}"))

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


def supporting_lanes(field: dict[str, Any]) -> list[str]:
    lanes = field.get("supporting_lanes")
    if not isinstance(lanes, list):
        return []
    return [str(x) for x in lanes]


def validate_field(
    *,
    field_name: str,
    field: dict[str, Any],
    lane_id_sets: dict[str, set[str]],
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    status = str(field.get("status") or "")
    mode = str(field.get("grounding_mode") or "")
    text = str(field.get("text") or "")
    ids = support_ids(field)
    lanes = supporting_lanes(field)

    definition_ids = lane_id_sets.get("definition_lane", set())
    scope_ids = lane_id_sets.get("scope_lane", set())
    context_ids = lane_id_sets.get("context_lane", set())
    quarantine_ids = lane_id_sets.get("quarantine_lane", set())
    sibling_ids = lane_id_sets.get("sibling_lane", set()) | lane_id_sets.get("sibling_contrast_lane", set())

    allowed_positive = definition_ids | scope_ids | context_ids

    if status not in {"grounded", "abstained"}:
        errors.append(f"{field_name}: invalid status {status!r}")
        return errors, warnings

    if status == "abstained":
        if mode not in {"", "abstained"}:
            errors.append(f"{field_name}: abstained but grounding_mode is {mode!r}")
        if text.strip():
            errors.append(f"{field_name}: abstained but text is non-empty")
        if ids:
            errors.append(f"{field_name}: abstained but support ids are non-empty {ids}")
        if lanes:
            errors.append(f"{field_name}: abstained but supporting_lanes are non-empty {lanes}")
        return errors, warnings

    if status == "grounded":
        if not text.strip():
            errors.append(f"{field_name}: grounded but text is empty")
        if not ids:
            errors.append(f"{field_name}: grounded but support ids are empty")

        invalid = [x for x in ids if x not in allowed_positive]
        if invalid:
            errors.append(f"{field_name}: support ids not in positive lanes {invalid}")

        quarantined = [x for x in ids if x in quarantine_ids]
        if quarantined:
            errors.append(f"{field_name}: support ids cite quarantine lane {quarantined}")

        sibling = [x for x in ids if x in sibling_ids]
        if sibling:
            errors.append(f"{field_name}: support ids cite sibling or negative contrast lane {sibling}")

        if field_name == "definition":
            if mode not in {"direct_definition", "contextual_synthesis", "single_strong_context"}:
                errors.append(f"definition: invalid grounding_mode {mode!r}")

            if mode == "direct_definition":
                if not any(x in definition_ids for x in ids):
                    errors.append("definition: direct_definition lacks definition_lane support")

            if mode == "contextual_synthesis":
                if len(ids) < 2:
                    errors.append("definition: contextual_synthesis requires at least two supporting evidence ids")
                if not any(x in scope_ids or x in context_ids for x in ids):
                    errors.append("definition: contextual_synthesis requires scope or context lane support")
                if any(x in definition_ids for x in ids):
                    warnings.append("definition: contextual_synthesis also cites definition_lane support")

            if mode == "single_strong_context":
                if len(ids) != 1:
                    errors.append("definition: single_strong_context requires exactly one supporting evidence id")
                if not any(x in scope_ids or x in context_ids for x in ids):
                    errors.append("definition: single_strong_context requires one scope or context lane id")
                warnings.append("definition: single_strong_context should be human-reviewed as weaker than direct_definition or contextual_synthesis")

        if field_name == "scope":
            if mode not in {"direct_scope", "contextual_synthesis", "single_strong_context"}:
                errors.append(f"scope: invalid grounding_mode {mode!r}")

            if mode == "direct_scope":
                if not any(x in scope_ids for x in ids):
                    errors.append("scope: direct_scope lacks scope_lane support")

            if mode == "contextual_synthesis":
                if len(ids) < 2:
                    warnings.append("scope: contextual_synthesis has fewer than two supporting evidence ids")

            if mode == "single_strong_context":
                if len(ids) != 1:
                    errors.append("scope: single_strong_context requires exactly one supporting evidence id")
                if not any(x in definition_ids or x in scope_ids or x in context_ids for x in ids):
                    errors.append("scope: single_strong_context requires one definition, scope, or context lane id")
                if any(x in definition_ids for x in ids):
                    warnings.append(
                        "scope: single_strong_context uses one definition_lane id; "
                        "human review required because scope is inferred from definition-support evidence"
                    )
                warnings.append("scope: single_strong_context should be human-reviewed as weaker than direct_scope or contextual_synthesis")

            context_only = ids and all(x in context_ids for x in ids)
            if context_only and mode != "single_strong_context":
                warnings.append("scope: grounded only from context_lane")

    return errors, warnings



def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lanes", required=True)
    parser.add_argument("--drafts", required=True)
    parser.add_argument("--out-root", default="data/processed/step67_sidecar_lane_validated_generic")
    args = parser.parse_args()

    lanes_path = Path(args.lanes)
    drafts_path = Path(args.drafts)

    packets = load_jsonl(lanes_path)
    drafts = load_jsonl(drafts_path)
    packet_by_kc = {str(packet.get("kc_id") or ""): packet for packet in packets}

    run_id = utc_run_id()
    out_dir = Path(args.out_root) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    issue_counter = Counter()
    status_counter = Counter()
    mode_counter = Counter()

    for draft in drafts:
        kc_id = str(draft.get("kc_id") or "")
        packet = packet_by_kc.get(kc_id)
        parsed = draft.get("parsed") if isinstance(draft.get("parsed"), dict) else {}

        errors: list[str] = []
        warnings: list[str] = []

        if packet is None:
            errors.append("missing lane packet for kc_id")
            lane_id_sets: dict[str, set[str]] = {}
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

        definition_status = definition.get("status")
        scope_status = scope.get("status")
        definition_mode = definition.get("grounding_mode")
        scope_mode = scope.get("grounding_mode")

        status_counter[f"definition::{definition_status}"] += 1
        status_counter[f"scope::{scope_status}"] += 1
        mode_counter[f"definition::{definition_mode}"] += 1
        mode_counter[f"scope::{scope_mode}"] += 1

        for error in errors:
            issue_counter[f"ERROR::{error}"] += 1
        for warning in warnings:
            issue_counter[f"WARNING::{warning}"] += 1

        rows.append({
            "kc_id": kc_id,
            "canonical_name": draft.get("canonical_name"),
            "model_call_ok": bool(draft.get("ok")),
            "definition_status": definition_status,
            "definition_grounding_mode": definition_mode,
            "definition_text": definition.get("text"),
            "definition_supporting_evidence_ids": support_ids(definition),
            "definition_supporting_lanes": supporting_lanes(definition),
            "scope_status": scope_status,
            "scope_grounding_mode": scope_mode,
            "scope_text": scope.get("text"),
            "scope_supporting_evidence_ids": support_ids(scope),
            "scope_supporting_lanes": supporting_lanes(scope),
            "lane_id_sets": {key: sorted(value) for key, value in lane_id_sets.items()},
            "errors": errors,
            "warnings": warnings,
        })

    valid_row_count = sum(1 for row in rows if not row["errors"])
    error_row_count = sum(1 for row in rows if row["errors"])
    warning_row_count = sum(1 for row in rows if row["warnings"])

    summary = {
        "stage": "step67c_validate_lane_aware_drafts_generic",
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
        "mode_counter": dict(mode_counter),
        "issue_counter": dict(issue_counter),
        "validation_policy": {
            "definition_direct": "direct_definition must cite at least one definition_lane id",
            "definition_contextual": "contextual_synthesis may cite definition, scope, or context ids, must cite at least two positive evidence ids, and must include scope/context support",
            "definition_single_strong_context": "single_strong_context may cite exactly one strong scope or context id and should be human-reviewed",
            "scope": "scope may cite definition, scope, or context ids; quarantine/sibling ids are errors",
            "scope_single_strong_context": "single_strong_context may cite exactly one strong definition, scope, or context id and should be human-reviewed",
            "abstained": "text, support ids, and supporting_lanes must be empty",
        },
        "active_pointer_policy": "do_not_update_current_alias_or_active_pointer",
    }

    summary_path = out_dir / "summary.json"
    rows_path = out_dir / "validation_rows.jsonl"
    md_path = out_dir / "review_snapshot.md"

    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    write_jsonl(rows_path, rows)

    md: list[str] = []
    md.append("# Step 6.7C generic lane-aware validation snapshot")
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
        md.append(f"- definition_grounding_mode: `{row['definition_grounding_mode']}`")
        md.append(f"- definition_text: {row['definition_text'] or ''}")
        md.append(f"- definition_supporting_evidence_ids: `{row['definition_supporting_evidence_ids']}`")
        md.append(f"- definition_supporting_lanes: `{row['definition_supporting_lanes']}`")
        md.append(f"- scope_status: `{row['scope_status']}`")
        md.append(f"- scope_grounding_mode: `{row['scope_grounding_mode']}`")
        md.append(f"- scope_text: {row['scope_text'] or ''}")
        md.append(f"- scope_supporting_evidence_ids: `{row['scope_supporting_evidence_ids']}`")
        md.append(f"- scope_supporting_lanes: `{row['scope_supporting_lanes']}`")
        md.append(f"- errors: `{row['errors']}`")
        md.append(f"- warnings: `{row['warnings']}`")
        md.append("")

    md_path.write_text("\n".join(md), encoding="utf-8")

    print("STEP67C_GENERIC_VALIDATION_RUN_ID =", run_id)
    print("STEP67C_GENERIC_VALIDATION_DIR =", out_dir.as_posix())
    print("STEP67C_GENERIC_SUMMARY_JSON =", summary_path.as_posix())
    print("STEP67C_GENERIC_VALIDATION_ROWS =", rows_path.as_posix())
    print("STEP67C_GENERIC_REVIEW_SNAPSHOT_MD =", md_path.as_posix())
    print("draft_row_count =", len(drafts))
    print("valid_row_count =", valid_row_count)
    print("error_row_count =", error_row_count)
    print("warning_row_count =", warning_row_count)
    print("status_counter =", json.dumps(dict(status_counter), ensure_ascii=False))
    print("mode_counter =", json.dumps(dict(mode_counter), ensure_ascii=False))
    print("issue_counter =", json.dumps(dict(issue_counter), ensure_ascii=False))
    print("STEP67C_GENERIC_VALIDATION_DONE")

    return 0 if error_row_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
