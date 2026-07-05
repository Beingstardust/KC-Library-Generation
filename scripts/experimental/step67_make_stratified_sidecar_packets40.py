#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SMOKE_KCS = [
    "KC_CLU_EVAL_001",
    "KC_CLU_EVAL_002",
    "KC_DE_PREP_003",
    "KC_EVAL_SAMP_003",
    "KC_CLU_DBS_003",
    "KC_CLU_CORE_002",
    "KC_CLU_DBS_001",
    "KC_CLF_NB_011",
    "KC_CLU_EVAL_012",
    "KC_EVAL_BASIC_005",
]


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


def norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def first_text(row: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def first_dict(row: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    for key in keys:
        value = row.get(key)
        if isinstance(value, dict):
            return value
    return {}


def first_list(row: dict[str, Any], keys: list[str]) -> list[Any]:
    for key in keys:
        value = row.get(key)
        if isinstance(value, list):
            return value
    return []


def support_summary(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("step5_3_support_pack_summary")
    return value if isinstance(value, dict) else {}


def review_aux(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("step5_3_review_queue_aux")
    return value if isinstance(value, dict) else {}


def topic_path(row: dict[str, Any]) -> list[str]:
    value = row.get("topic_path_labels")
    if isinstance(value, list):
        return [str(x) for x in value if str(x).strip()]

    value = row.get("source_hierarchy_path")
    if isinstance(value, list):
        return [str(x) for x in value if str(x).strip()]

    return []


def canonical_name(row: dict[str, Any], kc_id: str) -> str:
    for key in ("canonical_name", "kc_name", "name"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value
    path = topic_path(row)
    if path:
        return path[-1]
    return kc_id


def has_upper_abbrev(text: str) -> bool:
    return bool(re.search(r"\b[A-Z]{2,}\b", text or ""))


def candidate_sort_key(row: dict[str, Any]) -> tuple[int, float, float]:
    idx = as_int(row.get("source_candidate_index"), 10**9)
    scores = row.get("retrieval_scores") if isinstance(row.get("retrieval_scores"), dict) else {}
    combined = as_float(scores.get("combined"))
    align = as_float(row.get("alignment_score"))
    return (idx, -combined, -align)


def kc_stats(kc_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    first = rows[0]
    summary = support_summary(first)
    aux = review_aux(first)
    name = canonical_name(first, kc_id)
    path = topic_path(first)
    joined = " ".join([name, " ".join(path), str(first.get("seed_definition") or "")])

    strong_def = as_int(summary.get("strong_definition_anchor_candidates"))
    def_anchors = as_int(summary.get("definition_anchor_candidates"))
    high_contam = as_int(summary.get("high_contamination_candidates"))
    contam_excl = as_int(summary.get("contamination_exclusion_candidates"))
    in_review = bool(aux.get("in_review_queue"))
    selected_count = as_int(aux.get("selected_candidate_count"))

    return {
        "kc_id": kc_id,
        "canonical_name": name,
        "topic_path_labels": path,
        "topic_key": path[1] if len(path) > 1 else "",
        "row_count": len(rows),
        "strong_definition_anchor_candidates": strong_def,
        "definition_anchor_candidates": def_anchors,
        "high_contamination_candidates": high_contam,
        "contamination_exclusion_candidates": contam_excl,
        "in_review_queue": in_review,
        "review_reasons": aux.get("reasons") if isinstance(aux.get("reasons"), list) else [],
        "selected_candidate_count": selected_count,
        "has_abbrev": has_upper_abbrev(joined),
    }


def add_selected(
    selected: list[str],
    selected_set: set[str],
    candidates: list[dict[str, Any]],
    predicate,
    limit: int,
) -> None:
    for stat in candidates:
        kc_id = stat["kc_id"]
        if len(selected) >= limit:
            return
        if kc_id in selected_set:
            continue
        if predicate(stat):
            selected.append(kc_id)
            selected_set.add(kc_id)


def evidence_from_overlay_row(row: dict[str, Any], evidence_index: int) -> dict[str, Any]:
    support_profile = row.get("support_profile") if isinstance(row.get("support_profile"), dict) else {}
    role_hint = row.get("role_hint") if isinstance(row.get("role_hint"), dict) else {}
    retrieval_scores = row.get("retrieval_scores") if isinstance(row.get("retrieval_scores"), dict) else {}

    role_hints = []
    for value in support_profile.get("support_roles", []):
        role_hints.append(str(value))
    for key in ("preferred_support_role",):
        value = support_profile.get(key)
        if value:
            role_hints.append(str(value))
    for key in ("safe_role_hint", "top_role", "second_role"):
        value = role_hint.get(key)
        if value:
            role_hints.append(str(value))

    risk_hints = []
    contamination_risk = str(row.get("contamination_risk") or "")
    if contamination_risk:
        risk_hints.append(contamination_risk)
    for value in row.get("contamination_signals", []) if isinstance(row.get("contamination_signals"), list) else []:
        risk_hints.append(str(value))
    for key in (
        "fragmentary_surface",
        "generic_context_only",
        "contamination_exclusion_hint",
        "formula_auxiliary_only",
        "needs_context_completion",
    ):
        if support_profile.get(key):
            risk_hints.append(key)

    quote_text = first_text(
        row,
        ["quote_surface", "original_quote_surface", "text", "candidate_text", "sentence_text", "source_block_text"],
    )

    return {
        "evidence_id": f"E{evidence_index}",
        "overlay_candidate_id": str(row.get("overlay_candidate_id") or ""),
        "source_candidate_index": as_int(row.get("source_candidate_index"), evidence_index - 1),
        "text": quote_text,
        "text_source": str(row.get("text_source") or row.get("original_text_source") or ""),
        "role_hints": sorted(set(x for x in role_hints if x)),
        "risk_hints": sorted(set(x for x in risk_hints if x)),
        "definition_score": 14.0 - 0.2 * (evidence_index - 1),
        "scope_score": 6.0 - 0.2 * (evidence_index - 1),
        "provenance": {
            "doc_id": row.get("doc_id"),
            "page_index": row.get("page_index"),
            "block_id": row.get("block_id"),
            "sentence_id": row.get("sentence_id"),
            "patch_id": row.get("patch_id") or row.get("original_patch_id"),
            "patch_heading": row.get("patch_heading") or row.get("original_patch_heading"),
            "patch_type": row.get("patch_type") or row.get("original_patch_type"),
            "layer": row.get("layer") or row.get("source_layer"),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--overlay",
        default="data/processed/kc_drafting_input_overlay/2026-04-28_002730/candidate_sentence_overlay.jsonl",
    )
    ap.add_argument("--out-root", default="data/processed/step67_sidecar_packets_40")
    ap.add_argument("--target-count", type=int, default=40)
    ap.add_argument("--evidence-per-kc", type=int, default=8)
    args = ap.parse_args()

    overlay_path = Path(args.overlay)
    out_root = Path(args.out_root)

    overlay_rows = load_jsonl(overlay_path)

    by_kc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in overlay_rows:
        kc_id = str(row.get("kc_id") or "").strip()
        if kc_id:
            by_kc[kc_id].append(row)

    for kc_id in list(by_kc):
        by_kc[kc_id].sort(key=candidate_sort_key)

    stats = [kc_stats(kc_id, rows) for kc_id, rows in by_kc.items()]
    stats_by_kc = {s["kc_id"]: s for s in stats}

    stats_sorted = sorted(
        stats,
        key=lambda s: (
            s["topic_key"],
            not s["in_review_queue"],
            -s["high_contamination_candidates"],
            -s["strong_definition_anchor_candidates"],
            s["kc_id"],
        ),
    )

    selected: list[str] = []
    selected_set: set[str] = set()

    for kc_id in SMOKE_KCS:
        if kc_id in by_kc and kc_id not in selected_set and len(selected) < args.target_count:
            selected.append(kc_id)
            selected_set.add(kc_id)

    add_selected(
        selected,
        selected_set,
        stats_sorted,
        lambda s: s["in_review_queue"],
        min(args.target_count, len(selected) + 8),
    )
    add_selected(
        selected,
        selected_set,
        stats_sorted,
        lambda s: s["high_contamination_candidates"] >= 2 or s["contamination_exclusion_candidates"] >= 1,
        min(args.target_count, len(selected) + 8),
    )
    add_selected(
        selected,
        selected_set,
        stats_sorted,
        lambda s: s["has_abbrev"],
        min(args.target_count, len(selected) + 5),
    )
    add_selected(
        selected,
        selected_set,
        stats_sorted,
        lambda s: s["strong_definition_anchor_candidates"] < 2,
        min(args.target_count, len(selected) + 6),
    )
    add_selected(
        selected,
        selected_set,
        stats_sorted,
        lambda s: (
            s["strong_definition_anchor_candidates"] >= 4
            and s["high_contamination_candidates"] == 0
            and not s["in_review_queue"]
        ),
        min(args.target_count, len(selected) + 8),
    )
    add_selected(
        selected,
        selected_set,
        stats_sorted,
        lambda s: True,
        args.target_count,
    )

    run_id = utc_run_id()
    out_dir = out_root / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    packets = []
    selection_rows = []

    for kc_id in selected:
        rows = by_kc[kc_id]
        first = rows[0]
        stat = stats_by_kc[kc_id]

        selected_rows = rows[: args.evidence_per_kc]
        evidence = [
            evidence_from_overlay_row(row, i)
            for i, row in enumerate(selected_rows, start=1)
        ]

        packet = {
            "packet_contract_version": "step67_sidecar_evidence_packet_40_from_overlay_v1",
            "kc_id": kc_id,
            "canonical_name": stat["canonical_name"],
            "aliases": first_list(first, ["aliases"]),
            "seed_definition": str(first.get("seed_definition") or ""),
            "seed_definition_is_not_evidence": True,
            "topic_path_labels": stat["topic_path_labels"],
            "query_text": f"{stat['canonical_name']} | {' ; '.join(stat['topic_path_labels'])}",
            "review_queue_aux": review_aux(first),
            "support_pack_summary": support_summary(first),
            "source_candidate_row_count_for_kc": len(rows),
            "source_overlay_path": overlay_path.as_posix(),
            "source_rows_sha256": "",
            "source_step6_6_set_manifest": str(first.get("source_set_id") or ""),
            "packet_notes": [
                "diagnostic stratified 40-KC packet set",
                "seed definition is metadata only and must not be used as evidence",
                "do not update active pointers from this diagnostic output",
            ],
            "evidence": evidence,
        }
        packets.append(packet)

        selection_rows.append({
            **stat,
            "selected_order": len(selection_rows) + 1,
            "evidence_count": len(evidence),
        })

    category_counter = Counter()
    for row in selection_rows:
        if row["kc_id"] in SMOKE_KCS:
            category_counter["smoke_seed"] += 1
        if row["in_review_queue"]:
            category_counter["review_queue"] += 1
        if row["high_contamination_candidates"] >= 2 or row["contamination_exclusion_candidates"] >= 1:
            category_counter["contamination_risk"] += 1
        if row["has_abbrev"]:
            category_counter["abbreviation"] += 1
        if row["strong_definition_anchor_candidates"] < 2:
            category_counter["sparse_or_weak_definition_support"] += 1
        if row["strong_definition_anchor_candidates"] >= 4 and row["high_contamination_candidates"] == 0 and not row["in_review_queue"]:
            category_counter["strong_clean"] += 1

    packets_path = out_dir / "evidence_packets.jsonl"
    selection_path = out_dir / "selection_rows.jsonl"
    summary_path = out_dir / "summary.json"
    md_path = out_dir / "selection_audit.md"

    write_jsonl(packets_path, packets)
    write_jsonl(selection_path, selection_rows)

    summary = {
        "stage": "step67_make_stratified_sidecar_packets40",
        "run_id": run_id,
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "overlay_path": overlay_path.as_posix(),
        "out_dir": out_dir.as_posix(),
        "packets_path": packets_path.as_posix(),
        "selection_rows_path": selection_path.as_posix(),
        "overlay_row_count": len(overlay_rows),
        "available_kc_count": len(by_kc),
        "selected_kc_count": len(selected),
        "evidence_per_kc": args.evidence_per_kc,
        "category_counter": dict(category_counter),
        "active_pointer_policy": "do_not_update_current_alias_or_active_pointer",
    }

    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    md = []
    md.append("# Step 6.7 stratified 40-KC sidecar packet selection")
    md.append("")
    md.append("## Summary")
    md.append("")
    md.append("```json")
    md.append(json.dumps(summary, indent=2, ensure_ascii=False))
    md.append("```")
    md.append("")
    md.append("## Selected KCs")
    md.append("")
    for row in selection_rows:
        md.append(
            f"- {row['selected_order']:02d}. `{row['kc_id']}` | {row['canonical_name']} | "
            f"topic=`{row['topic_key']}` | review={row['in_review_queue']} | "
            f"strong_def={row['strong_definition_anchor_candidates']} | "
            f"high_contam={row['high_contamination_candidates']} | abbrev={row['has_abbrev']}"
        )

    md_path.write_text("\n".join(md), encoding="utf-8")

    print("STEP67_PACKETS40_RUN_ID =", run_id)
    print("STEP67_PACKETS40_DIR =", out_dir.as_posix())
    print("STEP67_PACKETS40_JSONL =", packets_path.as_posix())
    print("STEP67_PACKETS40_SELECTION_MD =", md_path.as_posix())
    print("selected_kc_count =", len(selected))
    print("category_counter =", json.dumps(dict(category_counter), indent=2, ensure_ascii=False))
    print("STEP67_STRATIFIED_PACKETS40_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
