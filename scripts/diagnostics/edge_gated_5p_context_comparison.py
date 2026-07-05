from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping


REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_RUN_PREFIX = "full144_diagnostic_rehydrated_ctx32768_204794"
WATCHED_LABELS = [
    "Rand Index",
    "DBSCAN Parameters",
    "K-Means Algorithm",
    "F-Measure",
    "NB Learning Phase",
    "External Index: F-Measure",
    "Directly Density-Reachable",
    "Density-Reachable",
]


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def _find_latest_context_root() -> Path | None:
    matches = sorted(REPO_ROOT.glob("_sofja_inbound/edge_gated_5p_context_*/extracted/*"))
    return matches[-1] if matches else None


def _default_baseline_artifacts() -> Dict[str, Path]:
    repo_local = {
        "profile": REPO_ROOT / "data/processed/kc_retrieval_profiles" / f"{BASELINE_RUN_PREFIX}_profile" / "kc_retrieval_profiles.jsonl",
        "candidate": REPO_ROOT / "data/processed/evidence_stage_v3_candidate_bank" / f"{BASELINE_RUN_PREFIX}_candidate" / "candidate_bank.jsonl",
        "scored": REPO_ROOT / "data/processed/evidence_stage_v3_scored_candidates" / f"{BASELINE_RUN_PREFIX}_scored" / "scored_candidates.jsonl",
        "pack": REPO_ROOT / "data/processed/evidence_stage_v3_evidence_packs" / f"{BASELINE_RUN_PREFIX}_pack" / "kc_evidence_packs.jsonl",
    }
    if all(path.exists() for path in repo_local.values()):
        return repo_local

    context_root = _find_latest_context_root()
    if context_root is None:
        return repo_local

    baseline_root = context_root / "baseline_204794" / "data" / "processed"
    return {
        "profile": baseline_root / "kc_retrieval_profiles" / f"{BASELINE_RUN_PREFIX}_profile" / "kc_retrieval_profiles.jsonl",
        "candidate": baseline_root / "evidence_stage_v3_candidate_bank" / f"{BASELINE_RUN_PREFIX}_candidate" / "candidate_bank.jsonl",
        "scored": baseline_root / "evidence_stage_v3_scored_candidates" / f"{BASELINE_RUN_PREFIX}_scored" / "scored_candidates.jsonl",
        "pack": baseline_root / "evidence_stage_v3_evidence_packs" / f"{BASELINE_RUN_PREFIX}_pack" / "kc_evidence_packs.jsonl",
    }


def _path_or_default(value: str | None, default: Path) -> Path:
    if not value:
        return default
    path = Path(value)
    return path if path.is_absolute() else (REPO_ROOT / path)


def _unit_id(row: Mapping[str, Any]) -> str:
    return str(
        row.get("kc_id")
        or row.get("knowledge_unit_id")
        or row.get("node_id")
        or row.get("id")
        or ""
    )


def _pack_route(row: Mapping[str, Any]) -> str:
    pack_quality = row.get("pack_quality") if isinstance(row.get("pack_quality"), Mapping) else {}
    return str(pack_quality.get("route") or "")


def _ordered_pack_len(row: Mapping[str, Any]) -> int:
    ordered = row.get("ordered_pack_for_drafting")
    return len(ordered) if isinstance(ordered, list) else 0


def _profile_mode_counter(rows: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
    return dict(Counter(str(row.get("profile_mode") or "missing") for row in rows))


def _profile_status_counter(rows: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
    return dict(Counter(str(row.get("profile_status") or "missing") for row in rows))


def _sum_accepted_cues(rows: Iterable[Mapping[str, Any]]) -> int:
    return sum(len(row.get("accepted_source_cues") or []) for row in rows)


def _sum_retrieval_routes(rows: Iterable[Mapping[str, Any]]) -> int:
    return sum(len(row.get("retrieval_routes") or []) for row in rows)


def _sum_bucket_counts(rows: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
    counter = Counter()
    for row in rows:
        counts = row.get("validated_guidance_bucket_counts") if isinstance(row.get("validated_guidance_bucket_counts"), Mapping) else {}
        for key, value in counts.items():
            try:
                counter[str(key)] += int(value or 0)
            except Exception:
                continue
    return dict(counter)


def _approx_llm_call_count(rows: Iterable[Mapping[str, Any]]) -> int:
    count = 0
    for row in rows:
        audit = row.get("audit") if isinstance(row.get("audit"), Mapping) else {}
        if audit.get("model_call_attempted") is True or str(row.get("llm_invocation_decision") or "") == "invoke":
            count += 1
    return count


def _ordered_pack_length_distribution(rows: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
    counter = Counter(str(_ordered_pack_len(row)) for row in rows)
    return dict(counter)


def _pack_risk_flags(row: Mapping[str, Any]) -> List[str]:
    pack_quality = row.get("pack_quality") if isinstance(row.get("pack_quality"), Mapping) else {}
    flags: List[str] = []
    for key in ("pack_level_risk_flags", "review_risk_flags", "risk_flags"):
        value = pack_quality.get(key) if key in pack_quality else row.get(key)
        if isinstance(value, list):
            for item in value:
                text = str(item or "")
                if text and text not in flags:
                    flags.append(text)
    return flags


def _clean_core(row: Mapping[str, Any]) -> bool:
    route = _pack_route(row)
    ordered_len = _ordered_pack_len(row)
    return bool(
        ordered_len > 0
        and "review" not in route
        and "insufficient" not in route
        and "context_only" not in route
    )


def _review_only(row: Mapping[str, Any]) -> bool:
    route = _pack_route(row)
    return "review" in route


def _false_positive_like(row: Mapping[str, Any]) -> bool:
    route = _pack_route(row)
    flags = " ".join(_pack_risk_flags(row)).lower()
    return "false_positive" in flags or "suspected_false_positive" in route


def _pack_transition_summary(old_rows: List[Mapping[str, Any]], new_rows: List[Mapping[str, Any]]) -> Dict[str, int]:
    old_by_id = {_unit_id(row): row for row in old_rows if _unit_id(row)}
    new_by_id = {_unit_id(row): row for row in new_rows if _unit_id(row)}
    all_ids = sorted(set(old_by_id) | set(new_by_id))
    summary = Counter()
    for unit_id in all_ids:
        old_row = old_by_id.get(unit_id, {})
        new_row = new_by_id.get(unit_id, {})
        old_clean = _clean_core(old_row)
        new_clean = _clean_core(new_row)
        old_review = _review_only(old_row)
        new_review = _review_only(new_row)
        if old_clean and new_clean:
            summary["unchanged_clean"] += 1
        if old_review and new_review:
            summary["unchanged_review_only"] += 1
        if old_clean and new_review:
            summary["clean_to_review_only"] += 1
        if old_review and new_clean:
            summary["review_only_to_clean"] += 1
        if _ordered_pack_len(old_row) == 0 and _ordered_pack_len(new_row) == 0:
            summary["unchanged_empty"] += 1
        if _false_positive_like(new_row) and not _false_positive_like(old_row):
            summary["new_false_positive_like"] += 1
    return dict(summary)


def _watched_deltas(
    old_profiles: List[Mapping[str, Any]],
    new_profiles: List[Mapping[str, Any]],
    old_packs: List[Mapping[str, Any]],
    new_packs: List[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    old_profile_by_name = {str(row.get("canonical_name") or ""): row for row in old_profiles}
    new_profile_by_name = {str(row.get("canonical_name") or ""): row for row in new_profiles}
    old_pack_by_name = {str(row.get("canonical_name") or ""): row for row in old_packs}
    new_pack_by_name = {str(row.get("canonical_name") or ""): row for row in new_packs}
    deltas: List[Dict[str, Any]] = []
    for label in WATCHED_LABELS:
        old_profile = old_profile_by_name.get(label, {})
        new_profile = new_profile_by_name.get(label, {})
        old_pack = old_pack_by_name.get(label, {})
        new_pack = new_pack_by_name.get(label, {})
        deltas.append({
            "canonical_name": label,
            "old_profile_mode": old_profile.get("profile_mode"),
            "new_profile_mode": new_profile.get("profile_mode"),
            "old_profile_status": old_profile.get("profile_status"),
            "new_profile_status": new_profile.get("profile_status"),
            "old_llm_invocation_decision": old_profile.get("llm_invocation_decision"),
            "new_llm_invocation_decision": new_profile.get("llm_invocation_decision"),
            "old_accepted_source_cues": len(old_profile.get("accepted_source_cues") or []),
            "new_accepted_source_cues": len(new_profile.get("accepted_source_cues") or []),
            "old_bucket_counts": dict(old_profile.get("validated_guidance_bucket_counts") or {}),
            "new_bucket_counts": dict(new_profile.get("validated_guidance_bucket_counts") or {}),
            "old_pack_route": _pack_route(old_pack),
            "new_pack_route": _pack_route(new_pack),
            "old_ordered_pack_len": _ordered_pack_len(old_pack),
            "new_ordered_pack_len": _ordered_pack_len(new_pack),
            "old_pack_risk_flags": _pack_risk_flags(old_pack),
            "new_pack_risk_flags": _pack_risk_flags(new_pack),
        })
    return deltas


def _summary_block(
    *,
    label: str,
    profiles: List[Mapping[str, Any]],
    candidate_rows: List[Mapping[str, Any]],
    scored_rows: List[Mapping[str, Any]],
    packs: List[Mapping[str, Any]],
) -> Dict[str, Any]:
    return {
        "profile_mode_distribution": _profile_mode_counter(profiles),
        "approx_llm_call_count": _approx_llm_call_count(profiles),
        "profile_status_counts": _profile_status_counter(profiles),
        "accepted_source_cue_count": _sum_accepted_cues(profiles),
        "validated_guidance_bucket_totals": _sum_bucket_counts(profiles),
        "retrieval_route_count": _sum_retrieval_routes(profiles),
        "candidate_row_count": len(candidate_rows),
        "scored_row_count": len(scored_rows),
        "ordered_pack_length_distribution": _ordered_pack_length_distribution(packs),
        "empty_pack_count": sum(1 for row in packs if _ordered_pack_len(row) == 0),
        "clean_core_count": sum(1 for row in packs if _clean_core(row)),
        "review_only_count": sum(1 for row in packs if _review_only(row)),
        "false_positive_like_count": sum(1 for row in packs if _false_positive_like(row)),
        "label": label,
    }


def _load_artifacts(paths: Mapping[str, Path]) -> Dict[str, List[Dict[str, Any]]]:
    missing = [name for name, path in paths.items() if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing comparison artifacts: " + ", ".join(f"{name}={paths[name]}" for name in missing))
    return {name: _read_jsonl(path) for name, path in paths.items()}


def _render_text(report: Mapping[str, Any]) -> str:
    lines: List[str] = []
    lines.append("Edge-Gated 5p / 5x Comparison")
    lines.append("")
    lines.append(f"comparison_mode: {report['comparison_mode']}")
    lines.append("artifact_paths:")
    for group in ("baseline_paths", "new_paths"):
        lines.append(f"  {group}:")
        for name, path in sorted(report[group].items()):
            lines.append(f"    - {name}: {path}")
    for group in ("baseline_summary", "new_summary"):
        lines.append("")
        lines.append(f"{group}:")
        summary = report[group]
        lines.append(f"  profile_mode_distribution: {summary['profile_mode_distribution']}")
        lines.append(f"  approx_llm_call_count: {summary['approx_llm_call_count']}")
        lines.append(f"  profile_status_counts: {summary['profile_status_counts']}")
        lines.append(f"  accepted_source_cue_count: {summary['accepted_source_cue_count']}")
        lines.append(f"  validated_guidance_bucket_totals: {summary['validated_guidance_bucket_totals']}")
        lines.append(f"  retrieval_route_count: {summary['retrieval_route_count']}")
        lines.append(f"  candidate_row_count: {summary['candidate_row_count']}")
        lines.append(f"  scored_row_count: {summary['scored_row_count']}")
        lines.append(f"  ordered_pack_length_distribution: {summary['ordered_pack_length_distribution']}")
        lines.append(f"  clean_core_count: {summary['clean_core_count']}")
        lines.append(f"  review_only_count: {summary['review_only_count']}")
        lines.append(f"  empty_pack_count: {summary['empty_pack_count']}")
        lines.append(f"  false_positive_like_count: {summary['false_positive_like_count']}")
    lines.append("")
    lines.append(f"pack_transitions: {report['pack_transitions']}")
    lines.append("")
    lines.append("watched_kc_deltas:")
    for item in report["watched_kc_deltas"]:
        lines.append(
            "  - "
            + f"{item['canonical_name']} | "
            + f"profile_mode {item['old_profile_mode']} -> {item['new_profile_mode']} | "
            + f"pack_route {item['old_pack_route']} -> {item['new_pack_route']} | "
            + f"ordered_len {item['old_ordered_pack_len']} -> {item['new_ordered_pack_len']}"
        )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    default_baseline = _default_baseline_artifacts()
    p = argparse.ArgumentParser(description="Compare baseline Step 5p/5x artifacts against an edge-gated run.")
    p.add_argument("--baseline-profile", default=str(default_baseline["profile"]))
    p.add_argument("--baseline-candidate", default=str(default_baseline["candidate"]))
    p.add_argument("--baseline-scored", default=str(default_baseline["scored"]))
    p.add_argument("--baseline-pack", default=str(default_baseline["pack"]))
    p.add_argument("--new-profile", default=None)
    p.add_argument("--new-candidate", default=None)
    p.add_argument("--new-scored", default=None)
    p.add_argument("--new-pack", default=None)
    p.add_argument("--output-dir", default=None, help="Optional explicit output directory.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    baseline_paths = {
        "profile": _path_or_default(args.baseline_profile, _default_baseline_artifacts()["profile"]),
        "candidate": _path_or_default(args.baseline_candidate, _default_baseline_artifacts()["candidate"]),
        "scored": _path_or_default(args.baseline_scored, _default_baseline_artifacts()["scored"]),
        "pack": _path_or_default(args.baseline_pack, _default_baseline_artifacts()["pack"]),
    }

    if args.new_profile or args.new_candidate or args.new_scored or args.new_pack:
        new_paths = {
            "profile": _path_or_default(args.new_profile, baseline_paths["profile"]),
            "candidate": _path_or_default(args.new_candidate, baseline_paths["candidate"]),
            "scored": _path_or_default(args.new_scored, baseline_paths["scored"]),
            "pack": _path_or_default(args.new_pack, baseline_paths["pack"]),
        }
        comparison_mode = "baseline_vs_new_run"
    else:
        new_paths = dict(baseline_paths)
        comparison_mode = "baseline_self_compare_smoke"

    baseline = _load_artifacts(baseline_paths)
    new = _load_artifacts(new_paths)

    report = {
        "generated_at": utc_stamp(),
        "comparison_mode": comparison_mode,
        "baseline_paths": {name: path.as_posix() for name, path in baseline_paths.items()},
        "new_paths": {name: path.as_posix() for name, path in new_paths.items()},
        "baseline_summary": _summary_block(
            label="baseline",
            profiles=baseline["profile"],
            candidate_rows=baseline["candidate"],
            scored_rows=baseline["scored"],
            packs=baseline["pack"],
        ),
        "new_summary": _summary_block(
            label="new",
            profiles=new["profile"],
            candidate_rows=new["candidate"],
            scored_rows=new["scored"],
            packs=new["pack"],
        ),
        "pack_transitions": _pack_transition_summary(baseline["pack"], new["pack"]),
        "watched_kc_deltas": _watched_deltas(
            baseline["profile"],
            new["profile"],
            baseline["pack"],
            new["pack"],
        ),
    }

    output_dir = Path(args.output_dir) if args.output_dir else REPO_ROOT / "local_audits" / f"edge_gated_5p_context_comparison_{utc_stamp()}"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "edge_gated_5p_context_comparison.json"
    text_path = output_dir / "edge_gated_5p_context_comparison.txt"
    _write_json(json_path, report)
    text_path.write_text(_render_text(report), encoding="utf-8")

    print(f"COMPARISON_MODE {comparison_mode}")
    print(f"BASELINE_PROFILE_COUNT {len(baseline['profile'])}")
    print(f"NEW_PROFILE_COUNT {len(new['profile'])}")
    print(f"BASELINE_LLM_CALLS {report['baseline_summary']['approx_llm_call_count']}")
    print(f"NEW_LLM_CALLS {report['new_summary']['approx_llm_call_count']}")
    print(f"OUTPUT_DIR {output_dir.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
