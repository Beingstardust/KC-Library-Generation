#!/usr/bin/env python3
"""Tier 1 automated metrics for a completed KC_L pipeline run.

Computes six comparable metrics directly from a run's existing artifacts (no new
instrumentation) so any future ablation run can be quickly compared against the baseline
before deciding whether a full manual (Tier 2) audit is warranted:

  1. Real-draft rate       - (grounded + partial) / total units
  2. Abstention rate       - abstained / total units
  3. Citation-resolution rate - % of cited supporting_evidence_ids that resolve to a real
     candidate_id/source_candidate_id known to that unit's own evidence pack
  4. Evidence sufficiency distribution - % of units per source_packet.packet_support_state
     (observed values: draftable / insufficient_support / weak_fallback / none-recorded;
     these are this pipeline's actual field values, not the generic
     standard_drafting/partial_grounded_packet/insufficient_support_packet naming used
     descriptively in the brief that requested this script)
  5. Average draft length  - mean character count of the drafted text field
  6. Average admitted evidence items per unit - mean len(ordered_pack_for_drafting)

All paths are resolved dynamically from the run's own RUN_STATE.json (stage output_root),
never hardcoded - a run's stage output directory naming can and does vary
(e.g. step_06_7_kc_draft_generation's output_root is itself a symlink to a differently-named
physical directory).

Usage: python3 compute_tier1_metrics.py --run-id <run_id> [--repo-root <path>] [--out <path>]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_REPO_ROOT = "/path/to/projects/kc_l_v2_clean"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_run_state(repo_root: Path, run_id: str) -> Dict[str, Any]:
    path = repo_root / "data" / "processed" / "runs" / run_id / "RUN_STATE.json"
    if not path.exists():
        raise SystemExit(f"RUN_STATE.json not found for run {run_id!r} at {path}")
    return read_json(path)


def stage_output_root(run_state: Dict[str, Any], stage_id: str) -> Path:
    entry = (run_state.get("stages") or {}).get(stage_id)
    if entry is None:
        raise SystemExit(f"Stage {stage_id!r} not found in RUN_STATE.json")
    if entry.get("status") != "completed":
        raise SystemExit(f"Stage {stage_id!r} is not completed (status={entry.get('status')!r})")
    output_root = entry.get("output_root")
    if not output_root:
        raise SystemExit(f"Stage {stage_id!r} has no recorded output_root")
    return Path(output_root)


def draft_status_and_text(rec: Dict[str, Any]) -> Tuple[str, str]:
    """A draft record's unit_type determines whether the draft surface is
    contextual_kc_draft or contextual_topic_draft."""
    draft = rec.get("draft") or {}
    unit_type = str(rec.get("knowledge_unit_type") or "").lower()
    surface_key = "contextual_topic_draft" if unit_type == "topic" else "contextual_kc_draft"
    surface = draft.get(surface_key) or {}
    status = str(surface.get("status") or "unknown")
    text = str(surface.get("text") or "")
    return status, text


def cited_evidence_ids(rec: Dict[str, Any]) -> List[str]:
    draft = rec.get("draft") or {}
    unit_type = str(rec.get("knowledge_unit_type") or "").lower()
    surface_key = "contextual_topic_draft" if unit_type == "topic" else "contextual_kc_draft"
    surface = draft.get(surface_key) or {}
    ids = list(surface.get("supporting_evidence_ids") or [])
    for item in draft.get("evidence_map") or []:
        ids.extend(item.get("supporting_evidence_ids") or [])
    return ids


def evidence_pack_known_ids(pack: Dict[str, Any]) -> set:
    known = set()
    for list_key in (
        "ordered_pack_for_drafting",
        "drafting_core_evidence",
        "auxiliary_evidence",
        "review_needed_evidence",
        "rejected_false_positive_evidence",
    ):
        for item in pack.get(list_key) or []:
            if not isinstance(item, dict):
                continue
            for id_key in ("candidate_id", "source_candidate_id", "scored_candidate_id"):
                v = item.get(id_key)
                if v:
                    known.add(v)
    return known


def load_overlay_known_ids_by_unit(overlay_dir: Path) -> Dict[str, set]:
    """Some units' evidence comes from step 6.6's overlay-fallback lane instead of the
    standard step5x evidence pack (packet_evidence_source == "step66_overlay_target_bound_
    fallback", confirmed 2026-07-30 for ~38 units via provenance_quality_counter's
    fallback_source_lane count). Those units cite overlay_candidate_id values
    (unit_id:overlay:<hash>) that only exist in candidate_sentence_overlay.jsonl, not in the
    step5x evidence packs - checking only the step5x pool without this one produces false-
    negative "unresolved" citations for every overlay-lane unit, confirmed directly by finding
    cited IDs that only resolve once this file is included.
    """
    by_unit: Dict[str, set] = {}
    for overlay_file in overlay_dir.glob("*/candidate_sentence_overlay.jsonl"):
        for rec in read_jsonl(overlay_file):
            uid = rec.get("kc_id") or rec.get("knowledge_unit_id")
            cand_id = rec.get("overlay_candidate_id")
            if uid and cand_id:
                by_unit.setdefault(uid, set()).add(cand_id)
    return by_unit


def compute_metrics(repo_root: Path, run_id: str) -> Dict[str, Any]:
    run_state = load_run_state(repo_root, run_id)

    draft_dir = stage_output_root(run_state, "step_06_7_kc_draft_generation")
    draft_files = list(draft_dir.glob("*.jsonl"))
    if len(draft_files) != 1:
        raise SystemExit(f"Expected exactly one draft JSONL in {draft_dir}, found {len(draft_files)}: {draft_files}")
    drafts = read_jsonl(draft_files[0])

    kc_evidence_dir = stage_output_root(run_state, "step_05x_kc_evidence_stage_v3")
    kc_packs = read_jsonl(kc_evidence_dir / "kc_evidence_packs.jsonl")

    topic_evidence_dir = stage_output_root(run_state, "topic_05x_evidence_stage_v3")
    topic_pack_file = topic_evidence_dir / "topic_evidence_packs.jsonl"
    topic_packs = read_jsonl(topic_pack_file) if topic_pack_file.exists() else []

    packs_by_unit: Dict[str, Dict[str, Any]] = {}
    for pack in kc_packs + topic_packs:
        uid = pack.get("knowledge_unit_id")
        if uid:
            packs_by_unit[uid] = pack

    overlay_dir = stage_output_root(run_state, "step_06_6_drafting_input_overlay")
    overlay_ids_by_unit = load_overlay_known_ids_by_unit(overlay_dir)

    # Topic units legitimately synthesize across, and cite, their CHILD KCs' evidence ids -
    # confirmed 2026-07-30 by finding topic citations that resolve cleanly against child-KC
    # packs but never against the topic's own pack. A KC citing evidence outside its own pack
    # would instead be a genuine cross-contamination bug and should stay flagged - so this
    # global pool is only unioned in for topic-type units, not KC-type ones.
    all_kc_known_ids: set = set()
    for pack in kc_packs:
        all_kc_known_ids |= evidence_pack_known_ids(pack)
    all_overlay_known_ids: set = set()
    for ids in overlay_ids_by_unit.values():
        all_overlay_known_ids |= ids

    total = len(drafts)
    status_counts: Dict[str, int] = {}
    draft_lengths: List[int] = []
    admitted_counts: List[int] = []
    support_state_counts: Dict[str, int] = {}
    total_citations = 0
    resolved_citations = 0
    per_unit_rows: List[Dict[str, Any]] = []

    for rec in drafts:
        uid = rec.get("knowledge_unit_id")
        status, text = draft_status_and_text(rec)
        status_counts[status] = status_counts.get(status, 0) + 1
        draft_lengths.append(len(text))

        source_packet = rec.get("source_packet") or {}
        support_state = source_packet.get("packet_support_state")
        support_state_key = str(support_state) if support_state is not None else "none_recorded"
        support_state_counts[support_state_key] = support_state_counts.get(support_state_key, 0) + 1

        pack = packs_by_unit.get(uid)
        admitted = None
        if pack is not None:
            admitted = len(pack.get("ordered_pack_for_drafting") or [])
            admitted_counts.append(admitted)

        cited = cited_evidence_ids(rec)
        known_ids = evidence_pack_known_ids(pack) if pack is not None else set()
        known_ids = known_ids | overlay_ids_by_unit.get(uid, set())
        if str(rec.get("knowledge_unit_type") or "").lower() == "topic":
            known_ids = known_ids | all_kc_known_ids | all_overlay_known_ids
        unresolved = [cid for cid in cited if cid not in known_ids]
        total_citations += len(cited)
        resolved_citations += len(cited) - len(unresolved)

        per_unit_rows.append(
            {
                "unit_id": uid,
                "unit_type": rec.get("knowledge_unit_type"),
                "canonical_name": rec.get("canonical_name"),
                "draft_status": status,
                "draft_length": len(text),
                "packet_support_state": support_state_key,
                "admitted_evidence_items": admitted,
                "cited_evidence_count": len(cited),
                "unresolved_citations": unresolved,
            }
        )

    grounded = status_counts.get("grounded", 0)
    partial = status_counts.get("partial", 0)
    abstained = status_counts.get("abstained", 0)

    report = {
        "run_id": run_id,
        "total_units": total,
        "draft_status_counts": status_counts,
        "metric_1_real_draft_rate": round((grounded + partial) / total, 4) if total else None,
        "metric_2_abstention_rate": round(abstained / total, 4) if total else None,
        "metric_3_citation_resolution_rate": round(resolved_citations / total_citations, 4) if total_citations else None,
        "metric_3_detail": {
            "total_citations": total_citations,
            "resolved_citations": resolved_citations,
            "unresolved_citations": total_citations - resolved_citations,
        },
        "metric_4_evidence_sufficiency_distribution": {
            k: round(v / total, 4) for k, v in support_state_counts.items()
        } if total else {},
        "metric_4_raw_counts": support_state_counts,
        "metric_5_average_draft_length_chars": round(statistics.mean(draft_lengths), 1) if draft_lengths else None,
        "metric_5_detail": {
            "mean_all_units": round(statistics.mean(draft_lengths), 1) if draft_lengths else None,
            "mean_non_abstained_units": round(
                statistics.mean([r["draft_length"] for r in per_unit_rows if r["draft_status"] != "abstained"]), 1
            ) if any(r["draft_status"] != "abstained" for r in per_unit_rows) else None,
        },
        "metric_6_average_admitted_evidence_items": round(statistics.mean(admitted_counts), 3) if admitted_counts else None,
        "metric_6_detail": {
            "units_with_pack_found": len(admitted_counts),
            "units_missing_pack": total - len(admitted_counts),
        },
        "per_unit": per_unit_rows,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--repo-root", default=DEFAULT_REPO_ROOT)
    parser.add_argument("--out", default=None, help="Output path (default: print to stdout)")
    parser.add_argument("--no-per-unit", action="store_true", help="Omit the per_unit breakdown from output")
    args = parser.parse_args()

    report = compute_metrics(Path(args.repo_root), args.run_id)
    if args.no_per_unit:
        report = {k: v for k, v in report.items() if k != "per_unit"}

    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"Wrote report to {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
