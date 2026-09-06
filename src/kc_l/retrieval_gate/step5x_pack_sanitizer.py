from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple

from kc_l.utils.json_io import read_json, write_json, write_jsonl

# Folds the one genuinely non-canonical step in the KC-track evidence-pack chain into the
# canonical pack_composition runner. Confirmed this session (backward provenance trace +
# direct A/B comparison) that everything else in the ~20-script `local_audits/` gate chain
# that produced BEST_STEP5X_FINAL_SANITIZED_GAPAWARE_SET.txt was iterative development of
# src/kc_l/retrieval_gate/evidence_admission.py, which is already permanently live in current
# source (confirmed by re-running the 3 canonical scripts against the real historical inputs:
# 139/144 KC rows came out byte-identical to the real "best" pack's ordered_pack_for_drafting).
# The remaining 5/144 KCs differed only by this one script's own dedup + exercise-prompt
# removal + quality-flagging, ported here verbatim from the original one-off
# finalize_best_step5x_pack_gapaware_v2.py (found in
# _archive/repo_cleanup_candidates/local_audits/finalize_best_step5x_pack_gapaware_20260519T160140Z/).

SANITIZER_VERSION = "step5x_pack_sanitizer_canonical_v1_folded_from_gapaware_v2_20260519"

EXPLICIT_EXERCISE_PROMPT_RE = re.compile(
    r"(?:^|\b)(?:"
    r"this\s+exercise\b|"
    r"exercise\s*,\s*inspired\b|"
    r"given\b.{0,160}\bexercise\s+\d+\b.{0,220}\b(?:compute|calculate|determine|find|rank|compare)\b|"
    r"\b(?:compute|calculate|determine|find|rank|compare)\b.{0,220}\bexercise\s+\d+\b|"
    r"given\s+the\s+rankings\s+you\s+had\s+obtained\s+in\s+exercise\b|"
    r"determine\s+the\s+error\s+rate\b|"
    r"using\s+the\s+following\s+methods\b"
    r")",
    re.IGNORECASE,
)

OCR_TABLE_NOISE_RE = re.compile(
    r"\bRobs\b|\bRL\b|\bRH\b|\[RL,RH\]|\btable\s+\d+\b|\bfigure\s+\d+\b",
    re.IGNORECASE,
)

GENERIC_CONTEXT_RE = re.compile(
    r"^\s*(?:this|that|these|those|it|they)\b|\bthis\s+algorithm\b|\bthe\s+algorithm\b",
    re.IGNORECASE,
)

TABLE_OR_FIGURE_REFERENCE_RE = re.compile(r"\b(?:table|figure)\s+\d+\b", re.IGNORECASE)


def _text_of(item: Mapping[str, Any]) -> str:
    return str(
        item.get("text")
        or item.get("selected_text")
        or item.get("quote")
        or item.get("candidate_sentence_text")
        or item.get("candidate_text")
        or ""
    )


def _norm_text(text: str) -> str:
    text = str(text or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text


def _add_flag(item: Dict[str, Any], flag: str) -> None:
    current = item.get("selected_text_quality_flags")
    if not isinstance(current, list):
        current = [str(current)] if current is not None else []
    if flag not in current:
        current.append(flag)
    item["selected_text_quality_flags"] = current


def _item_priority(item: Mapping[str, Any]) -> float:
    text = _text_of(item)
    role = str(item.get("role") or "")
    mode = str(item.get("selected_text_mode") or "")
    flags = item.get("selected_text_quality_flags")
    flags = flags if isinstance(flags, list) else ([str(flags)] if flags else [])

    role_priority = {"definition_kernel": 50, "formula_notation": 45, "explanatory_gloss": 35}.get(role, 20)
    mode_priority = {"source_block_context_completion": 20, "candidate_text": 15}.get(mode, 10)
    completeness = min(len(text), 800) / 40.0
    penalty = len(flags) * 3
    return role_priority + mode_priority + completeness - penalty


def _sanitize_pack_row(
    pack: Dict[str, Any], *, source_pack_jsonl: str
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Returns (new_pack, removed_exercise_records, dropped_duplicate_records) for one KC row."""
    kc_id = str(pack.get("kc_id") or "")
    items = pack.get("ordered_pack_for_drafting")
    if not isinstance(items, list):
        return pack, [], []

    removed_exercise: List[Dict[str, Any]] = []
    staged: List[Tuple[int, Dict[str, Any]]] = []

    for idx, raw_item in enumerate(items):
        if not isinstance(raw_item, dict):
            staged.append((idx, raw_item))
            continue
        item = dict(raw_item)
        text = _text_of(item)

        if EXPLICIT_EXERCISE_PROMPT_RE.search(text):
            removed_exercise.append(
                {
                    "kc_id": kc_id,
                    "index": idx,
                    "candidate_id": item.get("candidate_id"),
                    "role": item.get("role"),
                    "selected_text_mode": item.get("selected_text_mode"),
                    "text": text[:1200],
                    "action": "removed_explicit_exercise_or_task_prompt",
                }
            )
            continue

        if OCR_TABLE_NOISE_RE.search(text):
            _add_flag(item, "ocr_or_table_noise")
        if GENERIC_CONTEXT_RE.search(text):
            _add_flag(item, "weak_isolated_context")
        if TABLE_OR_FIGURE_REFERENCE_RE.search(text):
            _add_flag(item, "table_or_figure_reference_dependency")

        staged.append((idx, item))

    best_by_norm: Dict[str, Tuple[int, Dict[str, Any]]] = {}
    dropped_duplicates: List[Dict[str, Any]] = []
    for idx, item in staged:
        if not isinstance(item, dict):
            best_by_norm[f"__nondict__{idx}"] = (idx, item)
            continue
        nt = _norm_text(_text_of(item))
        key = nt if nt else f"__empty__{idx}"

        if key not in best_by_norm:
            best_by_norm[key] = (idx, item)
            continue

        old_idx, old_item = best_by_norm[key]
        old_score = _item_priority(old_item)
        new_score = _item_priority(item)

        if new_score > old_score:
            dropped_duplicates.append(
                {
                    "kc_id": kc_id,
                    "dropped_index": old_idx,
                    "kept_index": idx,
                    "action": "dropped_duplicate_normalized_text_within_kc",
                    "dropped_candidate_id": old_item.get("candidate_id"),
                    "kept_candidate_id": item.get("candidate_id"),
                    "text": _text_of(old_item)[:1200],
                }
            )
            best_by_norm[key] = (idx, item)
        else:
            dropped_duplicates.append(
                {
                    "kc_id": kc_id,
                    "dropped_index": idx,
                    "kept_index": old_idx,
                    "action": "dropped_duplicate_normalized_text_within_kc",
                    "dropped_candidate_id": item.get("candidate_id"),
                    "kept_candidate_id": old_item.get("candidate_id"),
                    "text": _text_of(item)[:1200],
                }
            )

    final_items = [item for _idx, item in sorted(best_by_norm.values(), key=lambda pair: pair[0])]

    new_pack = dict(pack)
    new_pack["ordered_pack_for_drafting"] = final_items
    new_pack["step5x_final_sanitizer"] = {
        "version": SANITIZER_VERSION,
        "source_pack_jsonl": source_pack_jsonl,
        "actions": [
            "remove_explicit_exercise_or_task_prompt_ordered_items",
            "dedupe_normalized_ordered_text_within_kc",
            "add_quality_flags_without_deleting_noisy_but_usable_items",
            "add_gap_request_for_kcs_emptied_only_by_invalid_exercise_prompt_removal",
        ],
    }
    return new_pack, removed_exercise, dropped_duplicates


def sanitize_packs(
    packs: List[Dict[str, Any]], *, source_pack_jsonl: str
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Apply dedup + exercise-prompt removal + noisy-item flagging to a list of already-composed
    step5x_v3 evidence pack rows (each with an `ordered_pack_for_drafting` list). Returns
    (sanitized_packs, stats). Pure in-memory transform, no I/O.
    """
    final_rows: List[Dict[str, Any]] = []
    removed_exercise: List[Dict[str, Any]] = []
    dropped_duplicates: List[Dict[str, Any]] = []
    removed_by_kc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    before_counts: Dict[str, int] = {}
    after_counts: Dict[str, int] = {}

    for pack in packs:
        kc_id = str(pack.get("kc_id") or "")
        items = pack.get("ordered_pack_for_drafting")
        before_counts[kc_id] = len(items) if isinstance(items, list) else 0

        new_pack, removed, dropped = _sanitize_pack_row(pack, source_pack_jsonl=source_pack_jsonl)
        final_rows.append(new_pack)
        removed_exercise.extend(removed)
        dropped_duplicates.extend(dropped)
        for rec in removed:
            removed_by_kc[kc_id].append(rec)

        after_items = new_pack.get("ordered_pack_for_drafting")
        after_counts[kc_id] = len(after_items) if isinstance(after_items, list) else 0

    newly_zero_kcs = sorted(
        kc_id
        for kc_id, before in before_counts.items()
        if before > 0 and after_counts.get(kc_id, 0) == 0 and removed_by_kc.get(kc_id)
    )

    stats = {
        "version": SANITIZER_VERSION,
        "removed_exercise_count": len(removed_exercise),
        "dropped_duplicate_count": len(dropped_duplicates),
        "flagged_item_count": sum(
            1
            for pack in final_rows
            for item in (pack.get("ordered_pack_for_drafting") or [])
            if isinstance(item, dict) and item.get("selected_text_quality_flags")
        ),
        "newly_zero_kcs": newly_zero_kcs,
        "removed_exercise_items": removed_exercise,
        "dropped_duplicate_items": dropped_duplicates,
    }
    return final_rows, stats


def build_gap_requests_for_newly_empty_kcs(
    *,
    newly_zero_kcs: List[str],
    removed_by_kc: Mapping[str, List[Dict[str, Any]]],
    existing_gap_kcs: set,
    run_id: str,
    source_pack_jsonl: str,
    source_scored_jsonl: str,
    source_candidate_jsonl: str,
) -> List[Dict[str, Any]]:
    added_gap_rows: List[Dict[str, Any]] = []
    for kc_id in newly_zero_kcs:
        if kc_id in existing_gap_kcs:
            continue
        added_gap_rows.append(
            {
                "schema_version": "step5x_final_sanitizer_gap_request_v1",
                "run_id": run_id,
                "kc_id": kc_id,
                "gap_reason": "all_ordered_evidence_removed_by_final_sanitizer",
                "gap_subreason": "explicit_exercise_or_task_prompt_was_only_ordered_evidence",
                "source_pack_jsonl": source_pack_jsonl,
                "source_scored_jsonl": source_scored_jsonl,
                "source_candidate_jsonl": source_candidate_jsonl,
                "removed_items": removed_by_kc.get(kc_id, []),
                "status": "held_for_insufficient_clean_ordered_evidence",
                "active_pointer_updated": False,
            }
        )
    return added_gap_rows


def finalize_step5x_pack_in_place(
    *,
    kc_evidence_packs_jsonl: Path,
    retrieval_gap_requests_jsonl: Path,
    evidence_pack_stats_json: Path,
    source_scored_candidates_jsonl: str,
    source_candidate_bank_jsonl: str,
    run_id: str,
) -> Dict[str, Any]:
    """Reads the just-written pack_composition output, applies the folded-in finalizer logic,
    and overwrites kc_evidence_packs.jsonl / retrieval_gap_requests.jsonl in place. Extends
    (does not replace) evidence_pack_stats.json with a `step5x_pack_sanitizer` sub-key.
    """
    packs = [row for row in _read_jsonl(kc_evidence_packs_jsonl)]
    gap_rows = [row for row in _read_jsonl(retrieval_gap_requests_jsonl)] if retrieval_gap_requests_jsonl.exists() else []

    before_counts = {
        str(p.get("kc_id") or ""): len(p.get("ordered_pack_for_drafting") or [])
        for p in packs
    }

    sanitized_packs, stats = sanitize_packs(packs, source_pack_jsonl=str(kc_evidence_packs_jsonl))

    removed_by_kc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for rec in stats["removed_exercise_items"]:
        removed_by_kc[str(rec["kc_id"])].append(rec)

    after_counts = {
        str(p.get("kc_id") or ""): len(p.get("ordered_pack_for_drafting") or [])
        for p in sanitized_packs
    }
    newly_zero_kcs = sorted(
        kc_id
        for kc_id, before in before_counts.items()
        if before > 0 and after_counts.get(kc_id, 0) == 0 and removed_by_kc.get(kc_id)
    )

    existing_gap_kcs = {str(row.get("kc_id") or "") for row in gap_rows if row.get("kc_id")}
    added_gap_rows = build_gap_requests_for_newly_empty_kcs(
        newly_zero_kcs=newly_zero_kcs,
        removed_by_kc=removed_by_kc,
        existing_gap_kcs=existing_gap_kcs,
        run_id=run_id,
        source_pack_jsonl=str(kc_evidence_packs_jsonl),
        source_scored_jsonl=source_scored_candidates_jsonl,
        source_candidate_jsonl=source_candidate_bank_jsonl,
    )
    new_gap_rows = gap_rows + added_gap_rows

    write_jsonl(kc_evidence_packs_jsonl, sanitized_packs)
    write_jsonl(retrieval_gap_requests_jsonl, new_gap_rows)

    stats["newly_zero_kcs"] = newly_zero_kcs
    stats["added_gap_count"] = len(added_gap_rows)
    stats["added_gap_rows"] = added_gap_rows

    if evidence_pack_stats_json.exists():
        existing_stats = read_json(evidence_pack_stats_json)
    else:
        existing_stats = {}
    existing_stats["step5x_pack_sanitizer"] = {
        k: v
        for k, v in stats.items()
        if k not in ("removed_exercise_items", "dropped_duplicate_items", "added_gap_rows")
    }
    write_json(evidence_pack_stats_json, existing_stats)

    return stats


def _read_jsonl(path: Path):
    import json

    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows
