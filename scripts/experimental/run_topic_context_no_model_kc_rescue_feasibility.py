from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

# This script is intentionally standalone and audit-only. It reads accepted
# Step5x/Topic5x artifacts and writes proposal artifacts only. It must not
# mutate production Step5p/Step5x modules, accepted packs, or pointers.

try:
    from kc_l.retrieval_gate.evidence_stage_v3_candidate_bank import (
        _build_direct_overlay_supplement_candidates,
        _build_source_overlay_target_supplement_rows,
    )
    from kc_l.retrieval_gate.evidence_stage_v3_scored_candidates import score_candidate_row
    from kc_l.retrieval_gate.evidence_stage_v3_pack_composition import compose_pack_for_kc
except Exception as exc:  # pragma: no cover
    print("IMPORT_ERROR: failed to import existing Step5x mechanisms", file=sys.stderr)
    print(repr(exc), file=sys.stderr)
    raise

SCRIPT_VERSION = "topic_context_no_model_kc_rescue_feasibility_v1"

EXERCISE_PROMPT_RE = re.compile(
    r"(?:^|\b)(?:"
    r"this\s+exercise\b|"
    r"exercise\s*,\s*inspired\b|"
    r"given\b.{0,120}\bexercise\s+\d+\b.{0,160}\b(?:compute|calculate|determine|find)\b|"
    r"\b(?:compute|calculate|determine|find)\b.{0,160}\bexercise\s+\d+\b|"
    r"determine\s+the\s+error\s+rate\b|"
    r"using\s+the\s+following\s+methods\b"
    r")",
    re.IGNORECASE,
)

REFERENCE_RE = re.compile(r"\b(?:references|bibliography|doi|isbn|et\s+al\.?|proceedings|lecture notes in computer science)\b", re.I)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except Exception as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_no}: {exc}") from exc
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def as_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def as_str_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        text = as_text(item)
        if text and text not in out:
            out.append(text)
    return out


def norm(text: Any) -> str:
    return re.sub(r"\s+", " ", as_text(text).lower()).strip()


def token_set(text: Any) -> set[str]:
    return {tok for tok in re.findall(r"[a-zA-Z0-9]+", norm(text)) if len(tok) >= 3}


def row_unit_id(row: Mapping[str, Any]) -> str:
    for key in ("topic_id", "node_id", "knowledge_unit_id", "kc_id", "unit_id", "id"):
        value = as_text(row.get(key))
        if value:
            return value
    return ""


def ordered_items(row: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    for key in ("ordered_pack_for_drafting", "ordered_evidence", "ordered_pack_items", "evidence_items", "selected_evidence"):
        value = row.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
    return []


def item_text(item: Mapping[str, Any]) -> str:
    for key in ("selected_text", "candidate_text", "text", "quote", "evidence_text", "source_text", "candidate_sentence_text"):
        value = as_text(item.get(key))
        if value:
            return value
    return ""


def item_score(row: Mapping[str, Any]) -> float:
    cq = row.get("candidate_quality")
    if isinstance(cq, Mapping):
        try:
            return float(cq.get("overall_score") or 0.0)
        except Exception:
            return 0.0
    for key in ("alignment_score", "fallback_score"):
        try:
            return float(row.get(key) or 0.0)
        except Exception:
            pass
    return 0.0


def is_positive_topic_scored(row: Mapping[str, Any]) -> bool:
    role = row.get("role_eligibility")
    quality = row.get("candidate_quality")
    support = row.get("support_profile")
    risk_flags = set(as_str_list(row.get("risk_flags"))) | set(as_str_list(row.get("review_risk_flags")))
    if bool(row.get("review_only_candidate")):
        return False
    if any(flag in risk_flags for flag in ("bibliography_like", "reference_like", "prompt_like")):
        return False
    if isinstance(support, Mapping) and bool(support.get("generic_context_only")):
        return False
    if isinstance(role, Mapping) and bool(role.get("positive_support_eligible")):
        return True
    if isinstance(quality, Mapping) and bool(quality.get("target_bound_positive_support")):
        return True
    return False


def row_text_for_screening(row: Mapping[str, Any]) -> str:
    parts = []
    for key in ("sentence_text", "text", "candidate_text", "quote", "source_block_text", "patch_heading", "source_heading_text"):
        value = as_text(row.get(key))
        if value:
            parts.append(value)
    return "\n".join(parts)


def hard_screen_source_row(row: Mapping[str, Any]) -> Optional[str]:
    text = row_text_for_screening(row)
    if not as_text(row.get("doc_id")):
        return "missing_doc_id"
    if bool(row.get("is_meta")) or bool(row.get("is_nav_boilerplate")) or bool(row.get("is_author_affiliation")):
        return "unsafe_overlay_metadata"
    if REFERENCE_RE.search(text):
        return "reference_or_bibliography_like"
    if EXERCISE_PROMPT_RE.search(text):
        return "exercise_or_task_prompt_like"
    return None


def build_overlay_indices(sentence_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    by_sentence: Dict[str, int] = {}
    by_patch: Dict[str, List[int]] = defaultdict(list)
    by_reveal: Dict[str, List[int]] = defaultdict(list)
    by_doc_page: Dict[Tuple[str, int], List[int]] = defaultdict(list)
    by_doc: Dict[str, List[int]] = defaultdict(list)

    for idx, row in enumerate(sentence_rows):
        sid = as_text(row.get("sentence_id"))
        if sid and sid not in by_sentence:
            by_sentence[sid] = idx
        patch_id = as_text(row.get("patch_id"))
        if patch_id:
            by_patch[patch_id].append(idx)
        reveal_id = as_text(row.get("reveal_group_id"))
        if reveal_id:
            by_reveal[reveal_id].append(idx)
        doc_id = as_text(row.get("doc_id"))
        if doc_id:
            by_doc[doc_id].append(idx)
            try:
                page = int(row.get("page_index"))
                by_doc_page[(doc_id, page)].append(idx)
            except Exception:
                pass
    return {
        "by_sentence": by_sentence,
        "by_patch": by_patch,
        "by_reveal": by_reveal,
        "by_doc_page": by_doc_page,
        "by_doc": by_doc,
    }


def collect_locator_rows(
    *,
    topic_id: str,
    topic_pack_by_id: Mapping[str, Mapping[str, Any]],
    topic_scored_by_id: Mapping[str, Sequence[Mapping[str, Any]]],
    max_scored_locators_per_topic: int,
) -> List[Dict[str, Any]]:
    locators: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str, str, str, str]] = set()

    def add(raw: Mapping[str, Any], source: str, rank_score: float = 0.0) -> None:
        loc = {
            "locator_source": source,
            "topic_id": topic_id,
            "doc_id": as_text(raw.get("doc_id")),
            "page_index": raw.get("page_index"),
            "sentence_id": as_text(raw.get("sentence_id")),
            "patch_id": as_text(raw.get("patch_id")),
            "reveal_group_id": as_text(raw.get("reveal_group_id")),
            "block_id": as_text(raw.get("block_id")),
            "source_row_index": raw.get("source_row_index"),
            "rank_score": rank_score,
            "text_preview": item_text(raw)[:300] if isinstance(raw, Mapping) else "",
        }
        key = (loc["doc_id"], as_text(loc["page_index"]), loc["sentence_id"], loc["patch_id"], loc["reveal_group_id"])
        if not any(key):
            return
        if key in seen:
            return
        seen.add(key)
        locators.append(loc)

    topic_pack = topic_pack_by_id.get(topic_id)
    if topic_pack:
        for item in ordered_items(topic_pack):
            add(item, "topic_final_ordered_pack", item_score(item))
        for item in as_list(topic_pack.get("representative_source_regions")):
            if isinstance(item, Mapping):
                add(item, "topic_representative_source_region", 0.0)

    scored = [r for r in topic_scored_by_id.get(topic_id, []) if is_positive_topic_scored(r)]
    scored.sort(key=item_score, reverse=True)
    for row in scored[:max_scored_locators_per_topic]:
        add(row, "topic_scored_positive_trace", item_score(row))

    return locators


def indices_for_locators(
    *,
    locators: Sequence[Mapping[str, Any]],
    overlay_indices: Mapping[str, Any],
    page_radius: int,
    max_rows_per_kc: int,
) -> Tuple[List[int], Dict[str, int]]:
    selected: List[int] = []
    seen: set[int] = set()
    counts = Counter()

    def add_idx(idx: int, reason: str) -> None:
        if idx in seen:
            return
        seen.add(idx)
        selected.append(idx)
        counts[reason] += 1

    for loc in locators:
        sid = as_text(loc.get("sentence_id"))
        if sid and sid in overlay_indices["by_sentence"]:
            add_idx(overlay_indices["by_sentence"][sid], "exact_sentence")

        patch_id = as_text(loc.get("patch_id"))
        if patch_id:
            for idx in overlay_indices["by_patch"].get(patch_id, []):
                add_idx(idx, "same_patch")

        reveal_id = as_text(loc.get("reveal_group_id"))
        if reveal_id:
            for idx in overlay_indices["by_reveal"].get(reveal_id, []):
                add_idx(idx, "same_reveal_group")

        doc_id = as_text(loc.get("doc_id"))
        try:
            page = int(loc.get("page_index"))
        except Exception:
            page = None
        if doc_id and page is not None:
            for p in range(page - page_radius, page + page_radius + 1):
                for idx in overlay_indices["by_doc_page"].get((doc_id, p), []):
                    add_idx(idx, "same_doc_page_radius")

        if len(selected) >= max_rows_per_kc:
            break

    return selected[:max_rows_per_kc], dict(counts)


def candidate_context_from_kc_pack(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "kc_id": as_text(row.get("kc_id") or row.get("knowledge_unit_id")),
        "knowledge_unit_id": as_text(row.get("kc_id") or row.get("knowledge_unit_id")),
        "knowledge_unit_type": "kc",
        "canonical_name": as_text(row.get("canonical_name")),
        "aliases": as_str_list(row.get("aliases")),
        "topic_path_ids": as_str_list(row.get("topic_path_ids")),
        "topic_path_labels": as_str_list(row.get("topic_path_labels")),
        "parent_topic_id": as_text(row.get("parent_topic_id")),
        "parent_topic_label": as_text(row.get("parent_topic_label")),
        "sibling_labels": as_str_list(row.get("sibling_labels")),
    }


def make_global_usage(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    raw_hash_to_kcs: Dict[str, set[str]] = defaultdict(set)
    normalized_text_to_kcs: Dict[str, set[str]] = defaultdict(set)
    patch_id_to_kcs: Dict[str, set[str]] = defaultdict(set)
    for row in rows:
        kc_id = as_text(row.get("kc_id") or row.get("knowledge_unit_id"))
        if not kc_id:
            continue
        raw_hash = as_text(row.get("raw_text_hash"))
        if raw_hash:
            raw_hash_to_kcs[raw_hash].add(kc_id)
        text = as_text(row.get("candidate_text") or row.get("text"))
        if text:
            normalized_text_to_kcs[norm(text)].add(kc_id)
        patch_id = as_text(row.get("patch_id"))
        if patch_id:
            patch_id_to_kcs[patch_id].add(kc_id)
    return {
        "raw_text_hash_to_kcs": {k: sorted(v) for k, v in raw_hash_to_kcs.items()},
        "normalized_text_to_kcs": {k: sorted(v) for k, v in normalized_text_to_kcs.items()},
        "patch_id_to_kcs": {k: sorted(v) for k, v in patch_id_to_kcs.items()},
    }


def classify_scored_candidate(row: Mapping[str, Any]) -> Tuple[str, str]:
    text = as_text(row.get("candidate_text") or row.get("text"))
    if not text:
        return "blocked", "missing_candidate_text"
    if EXERCISE_PROMPT_RE.search(text):
        return "blocked", "exercise_or_task_prompt_like"
    if REFERENCE_RE.search(text):
        return "blocked", "reference_or_bibliography_like"
    if bool(row.get("review_only_candidate")):
        return "blocked", "review_only_candidate"
    role = row.get("role_eligibility") if isinstance(row.get("role_eligibility"), Mapping) else {}
    quality = row.get("candidate_quality") if isinstance(row.get("candidate_quality"), Mapping) else {}
    routing = as_text(row.get("routing_recommendation"))
    if bool(role.get("positive_support_eligible")) or bool(quality.get("target_bound_positive_support")) or routing == "positive_role_candidate":
        return "positive_signal", "positive_support_eligible"
    flags = as_str_list(row.get("risk_flags")) + as_str_list(row.get("review_risk_flags"))
    if "no_target_binding" in flags or "candidate_pool_membership_only" in flags:
        return "blocked", "no_target_binding"
    return "near_miss", routing or "not_positive_support_eligible"


def pack_ordered_count(pack: Mapping[str, Any]) -> int:
    return len(ordered_items(pack))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Audit-only no-model KC rescue feasibility using Topic5x context as locator context.")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--sentence-overlay-jsonl", required=True)
    parser.add_argument("--kc-pack-jsonl", required=True)
    parser.add_argument("--kc-gap-jsonl", required=True)
    parser.add_argument("--topic-pack-jsonl", required=True)
    parser.add_argument("--topic-scored-jsonl", required=True)
    parser.add_argument("--topic5p-profiles-jsonl", required=False, default="")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--max-targets", type=int, default=0)
    parser.add_argument("--exact-kc-ids", default="")
    parser.add_argument("--page-radius", type=int, default=1)
    parser.add_argument("--max-local-rows-per-kc", type=int, default=1200)
    parser.add_argument("--max-scored-locators-per-topic", type=int, default=16)
    parser.add_argument("--max-candidates-per-kc", type=int, default=8)
    parser.add_argument("--min-source-overlay-score", type=float, default=5.8)
    parser.add_argument("--min-direct-overlay-score", type=float, default=4.8)
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    failures: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    artifact_paths = {
        "sentence_overlay_jsonl": str(Path(args.sentence_overlay_jsonl)),
        "kc_pack_jsonl": str(Path(args.kc_pack_jsonl)),
        "kc_gap_jsonl": str(Path(args.kc_gap_jsonl)),
        "topic_pack_jsonl": str(Path(args.topic_pack_jsonl)),
        "topic_scored_jsonl": str(Path(args.topic_scored_jsonl)),
        "topic5p_profiles_jsonl": args.topic5p_profiles_jsonl,
    }

    for label, raw in artifact_paths.items():
        if not raw:
            continue
        if not Path(raw).exists():
            failures.append({"code": "missing_input", "label": label, "path": raw})
    if failures:
        summary = {"decision": "NO_MODEL_TOPIC_CONTEXT_RESCUE_BLOCKED_BY_ARTIFACT_CONTRACT", "failures": failures}
        write_json(out_dir / "topic_context_rescue_feasibility_summary.json", summary)
        return 2

    kc_pack = read_jsonl(Path(args.kc_pack_jsonl))
    kc_gap = read_jsonl(Path(args.kc_gap_jsonl))
    topic_pack = read_jsonl(Path(args.topic_pack_jsonl))
    topic_scored = read_jsonl(Path(args.topic_scored_jsonl))
    sentence_rows = read_jsonl(Path(args.sentence_overlay_jsonl))
    topic_profiles = read_jsonl(Path(args.topic5p_profiles_jsonl)) if args.topic5p_profiles_jsonl else []

    # Target only final zero-evidence / gap KCs in pass 1.
    gap_ids = {as_text(row.get("kc_id") or row.get("knowledge_unit_id")) for row in kc_gap}
    targets = [row for row in kc_pack if as_text(row.get("kc_id")) in gap_ids or not ordered_items(row)]
    targets = [row for row in targets if as_text(row.get("knowledge_unit_type")) == "kc"]

    exact_ids = {x.strip() for x in args.exact_kc_ids.split(",") if x.strip()}
    if exact_ids:
        targets = [row for row in targets if as_text(row.get("kc_id")) in exact_ids]
    if args.max_targets and args.max_targets > 0:
        targets = targets[: args.max_targets]

    topic_pack_by_id = {row_unit_id(row): row for row in topic_pack if row_unit_id(row)}
    topic_scored_by_id: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for row in topic_scored:
        tid = row_unit_id(row)
        if tid:
            topic_scored_by_id[tid].append(row)

    overlay_indices = build_overlay_indices(sentence_rows)
    target_reports: List[Dict[str, Any]] = []
    all_supplement_rows: List[Dict[str, Any]] = []
    all_candidate_rows: List[Dict[str, Any]] = []
    all_scored_rows: List[Dict[str, Any]] = []
    all_proposal_packs: List[Dict[str, Any]] = []
    worth_replay: List[str] = []

    source_overlay_cfg = {
        "enabled": True,
        "generate_from_source_overlay": True,
        "max_candidates_per_kc": args.max_candidates_per_kc,
        "source_overlay_min_scan_score": args.min_source_overlay_score,
        "source_overlay_dynamic_broad_phrase_kc_fraction": 0.25,
        "source_overlay_min_single_token_len": 5,
        "source_overlay_allow_uppercase_acronym": True,
        "source_overlay_promote_source_block_window": True,
        "source_overlay_source_block_window_max_chars": 900,
    }
    direct_overlay_cfg = {
        "enabled": True,
        "max_candidates_per_kc": args.max_candidates_per_kc,
        "min_score": args.min_direct_overlay_score,
        "reject_prompt_like": True,
        "reject_fragmentary": True,
        "reject_reference_like": True,
        "reject_formula_only_without_target_signal": True,
        "source_overlay_promote_source_block_window": True,
        "source_overlay_source_block_window_max_chars": 900,
    }

    for target in targets:
        kc_id = as_text(target.get("kc_id") or target.get("knowledge_unit_id"))
        parent_topic_id = as_text(target.get("parent_topic_id"))
        report: Dict[str, Any] = {
            "kc_id": kc_id,
            "canonical_name": as_text(target.get("canonical_name")),
            "parent_topic_id": parent_topic_id,
            "parent_topic_label": as_text(target.get("parent_topic_label")),
            "status": "not_started",
        }
        if not parent_topic_id:
            report.update({"status": "blocked", "block_reason": "missing_parent_topic_id"})
            target_reports.append(report)
            continue
        locators = collect_locator_rows(
            topic_id=parent_topic_id,
            topic_pack_by_id=topic_pack_by_id,
            topic_scored_by_id=topic_scored_by_id,
            max_scored_locators_per_topic=args.max_scored_locators_per_topic,
        )
        report["locator_count"] = len(locators)
        report["locator_source_counter"] = dict(Counter(as_text(l.get("locator_source")) for l in locators))
        if not locators:
            report.update({"status": "blocked", "block_reason": "no_parent_topic_locators"})
            target_reports.append(report)
            continue

        local_indices, local_reason_counts = indices_for_locators(
            locators=locators,
            overlay_indices=overlay_indices,
            page_radius=args.page_radius,
            max_rows_per_kc=args.max_local_rows_per_kc,
        )
        local_rows_raw = [dict(sentence_rows[idx], __full_source_row_index=idx) for idx in local_indices]
        screen_counts = Counter()
        local_rows = []
        for row in local_rows_raw:
            reason = hard_screen_source_row(row)
            if reason:
                screen_counts[reason] += 1
                continue
            local_rows.append(row)

        report["local_overlay_row_count_before_screen"] = len(local_rows_raw)
        report["local_overlay_row_count_after_screen"] = len(local_rows)
        report["local_row_selection_reason_counter"] = local_reason_counts
        report["screen_rejected_counter"] = dict(screen_counts)
        if not local_rows:
            report.update({"status": "blocked", "block_reason": "no_local_rows_after_screen"})
            target_reports.append(report)
            continue

        context = candidate_context_from_kc_pack(target)
        supplement_rows, supplement_stats = _build_source_overlay_target_supplement_rows(
            sentence_rows=local_rows,
            selected_kc_context_rows=[context],
            guidance_lookup={},
            cfg=source_overlay_cfg,
        )
        for row in supplement_rows:
            row["topic_context_rescue_run_id"] = args.run_id
            row["topic_context_parent_topic_id"] = parent_topic_id
            row["topic_context_rescue_stage"] = "source_overlay_target_supplement"
        all_supplement_rows.extend(supplement_rows)
        report["supplement_stats"] = supplement_stats
        if not supplement_rows:
            report.update({"status": "no_signal", "block_reason": "no_source_overlay_target_supplement_hits"})
            target_reports.append(report)
            continue

        candidate_rows, candidate_stats = _build_direct_overlay_supplement_candidates(
            run_id=args.run_id,
            supplement_rows=supplement_rows,
            supplement_manifest=str(Path(args.sentence_overlay_jsonl)),
            selected_kc_context_rows=[context],
            guidance_lookup={},
            existing_rows=[],
            cfg=direct_overlay_cfg,
        )
        for row in candidate_rows:
            row["topic_context_rescue_run_id"] = args.run_id
            row["topic_context_parent_topic_id"] = parent_topic_id
            row["topic_context_rescue_stage"] = "direct_overlay_candidate"
        all_candidate_rows.extend(candidate_rows)
        report["candidate_stats"] = candidate_stats
        if not candidate_rows:
            report.update({"status": "no_signal", "block_reason": "no_direct_overlay_candidates_after_existing_gates"})
            target_reports.append(report)
            continue

        usage = make_global_usage(candidate_rows)
        scored_rows: List[Dict[str, Any]] = []
        classified = Counter()
        for row in candidate_rows:
            scored = score_candidate_row(row, global_candidate_usage=usage)
            cls, reason = classify_scored_candidate(scored)
            scored["topic_context_rescue_class"] = cls
            scored["topic_context_rescue_class_reason"] = reason
            scored["topic_context_rescue_run_id"] = args.run_id
            scored["topic_context_parent_topic_id"] = parent_topic_id
            classified[f"{cls}:{reason}"] += 1
            scored_rows.append(scored)
        all_scored_rows.extend(scored_rows)
        report["scored_class_counter"] = dict(classified)

        positive_rows = [row for row in scored_rows if row.get("topic_context_rescue_class") == "positive_signal"]
        if positive_rows:
            try:
                pack = compose_pack_for_kc(kc_id, positive_rows, {})
                pack["topic_context_rescue_run_id"] = args.run_id
                pack["topic_context_rescue_status"] = "proposal_only_not_accepted_evidence"
                pack["topic_context_parent_topic_id"] = parent_topic_id
                pack["topic_context_rescue_warning"] = "This is an audit-only proposal pack. It must not overwrite accepted Step5x output without a separate replay/closeout."
                all_proposal_packs.append(pack)
                ordered = pack_ordered_count(pack)
                report["proposal_ordered_count"] = ordered
                report["proposal_pack_quality"] = pack.get("pack_quality")
                if ordered > 0:
                    report.update({"status": "strict_signal", "recommendation": "RUN_BOUNDED_REPLAY_FOR_THIS_KC"})
                    worth_replay.append(kc_id)
                else:
                    report.update({"status": "near_miss", "recommendation": "DO_NOT_REPLAY_YET"})
            except Exception as exc:
                report.update({"status": "pack_compose_failed", "error": repr(exc), "recommendation": "INSPECT_SCORING_ROWS"})
        else:
            report.update({"status": "near_miss", "recommendation": "DO_NOT_REPLAY_YET"})
        target_reports.append(report)

    status_counter = Counter(as_text(r.get("status")) for r in target_reports)
    decision = "NO_MODEL_TOPIC_CONTEXT_RESCUE_HAS_SIGNAL_RUN_BOUNDED_REPLAY" if worth_replay else "NO_MODEL_TOPIC_CONTEXT_RESCUE_NOT_JUSTIFIED"
    if failures:
        decision = "NO_MODEL_TOPIC_CONTEXT_RESCUE_BLOCKED_BY_ARTIFACT_CONTRACT"

    summary = {
        "schema_version": SCRIPT_VERSION,
        "created_utc": now_utc(),
        "run_id": args.run_id,
        "decision": decision,
        "repo_root": str(repo_root),
        "input_artifacts": artifact_paths,
        "input_hashes": {label: sha256_file(Path(path)) for label, path in artifact_paths.items() if path and Path(path).exists()},
        "parameters": vars(args),
        "counts": {
            "kc_pack_rows": len(kc_pack),
            "kc_gap_rows": len(kc_gap),
            "target_kc_count": len(targets),
            "sentence_overlay_rows": len(sentence_rows),
            "topic_pack_rows": len(topic_pack),
            "topic_scored_rows": len(topic_scored),
            "topic5p_profile_rows": len(topic_profiles),
            "supplement_rows": len(all_supplement_rows),
            "candidate_rows": len(all_candidate_rows),
            "scored_rows": len(all_scored_rows),
            "proposal_pack_rows": len(all_proposal_packs),
            "strict_signal_kc_count": len(worth_replay),
        },
        "target_status_counter": dict(status_counter),
        "worth_bounded_replay_kc_ids": worth_replay,
        "failures": failures,
        "warnings": warnings + ([{"code": "topic_candidate_bank_bridge_not_used", "detail": "This feasibility audit uses final topic pack and trace-rehydrated scored topic rows as locators. It does not consume raw topic candidate bank as Step6 evidence."}]),
        "policy": {
            "no_model_calls": True,
            "domain_agnostic_code": True,
            "topic_context_is_locator_not_evidence": True,
            "accepted_step5x_pack_not_mutated": True,
            "best_or_active_pointers_not_mutated": True,
            "proposal_packs_not_accepted_evidence": True,
            "bounded_replay_required_before_any_promotion": True,
        },
    }

    write_json(out_dir / "topic_context_rescue_feasibility_summary.json", summary)
    write_jsonl(out_dir / "topic_context_rescue_target_reports.jsonl", target_reports)
    write_jsonl(out_dir / "topic_context_rescue_supplement_rows.jsonl", all_supplement_rows)
    write_jsonl(out_dir / "topic_context_rescue_candidate_rows.jsonl", all_candidate_rows)
    write_jsonl(out_dir / "topic_context_rescue_scored_rows.jsonl", all_scored_rows)
    write_jsonl(out_dir / "topic_context_rescue_proposal_packs.jsonl", all_proposal_packs)

    md: List[str] = []
    md.append("# Topic-context no-model KC rescue feasibility")
    md.append("")
    md.append(f"- decision: `{decision}`")
    md.append(f"- run_id: `{args.run_id}`")
    md.append(f"- target_kc_count: `{len(targets)}`")
    md.append(f"- strict_signal_kc_count: `{len(worth_replay)}`")
    md.append(f"- candidate_rows: `{len(all_candidate_rows)}`")
    md.append(f"- scored_rows: `{len(all_scored_rows)}`")
    md.append(f"- proposal_pack_rows: `{len(all_proposal_packs)}`")
    md.append("")
    md.append("## Status counter")
    for key, value in sorted(status_counter.items()):
        md.append(f"- `{key}`: `{value}`")
    md.append("")
    md.append("## KCs worth bounded replay")
    if worth_replay:
        for kc_id in worth_replay:
            row = next((r for r in target_reports if r.get("kc_id") == kc_id), {})
            md.append(f"- `{kc_id}`: {row.get('canonical_name')} | proposal_ordered_count={row.get('proposal_ordered_count')}")
    else:
        md.append("- none")
    md.append("")
    md.append("## Contract")
    md.append("- This is audit-only and no-model.")
    md.append("- Topic context is locator context only, not KC evidence.")
    md.append("- Proposal packs are not accepted evidence.")
    md.append("- Existing Step5p/Step5x production files and pointers are not modified.")
    md.append("")
    md.append("## Output files")
    for name in [
        "topic_context_rescue_feasibility_summary.json",
        "topic_context_rescue_target_reports.jsonl",
        "topic_context_rescue_supplement_rows.jsonl",
        "topic_context_rescue_candidate_rows.jsonl",
        "topic_context_rescue_scored_rows.jsonl",
        "topic_context_rescue_proposal_packs.jsonl",
    ]:
        md.append(f"- `{out_dir / name}`")
    (out_dir / "topic_context_rescue_feasibility_summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print("===== TOPIC CONTEXT NO-MODEL KC RESCUE FEASIBILITY SUMMARY =====")
    print(json.dumps({
        "decision": decision,
        "target_kc_count": len(targets),
        "target_status_counter": dict(status_counter),
        "strict_signal_kc_count": len(worth_replay),
        "worth_bounded_replay_kc_ids": worth_replay,
        "supplement_rows": len(all_supplement_rows),
        "candidate_rows": len(all_candidate_rows),
        "scored_rows": len(all_scored_rows),
        "proposal_pack_rows": len(all_proposal_packs),
        "out_dir": str(out_dir),
    }, indent=2, ensure_ascii=False))
    print("")
    print("TOPIC_CONTEXT_RESCUE_FEASIBILITY_SUMMARY_JSON=" + str(out_dir / "topic_context_rescue_feasibility_summary.json"))
    print("TOPIC_CONTEXT_RESCUE_FEASIBILITY_SUMMARY_MD=" + str(out_dir / "topic_context_rescue_feasibility_summary.md"))
    print("TOPIC_CONTEXT_RESCUE_TARGET_REPORTS_JSONL=" + str(out_dir / "topic_context_rescue_target_reports.jsonl"))
    print("TOPIC_CONTEXT_RESCUE_PROPOSAL_PACKS_JSONL=" + str(out_dir / "topic_context_rescue_proposal_packs.jsonl"))
    print("TOPIC_CONTEXT_NO_MODEL_KC_RESCUE_FEASIBILITY_COMPLETE")
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
