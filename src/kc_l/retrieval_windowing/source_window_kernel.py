from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

from kc_l.retrieval_windowing.embedding_tie_break import (
    apply_source_diversity_floor,
    rerank_windows_with_embedding_tie_break,
)
from kc_l.retrieval_windowing.source_surface_fallback import (
    SOURCE_SURFACE_FALLBACK,
    build_source_surface_fallback_candidates,
)


PROFILE_WINDOW_SUPPLIER = "source_surface_kernel_profile_mode"


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _as_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return []


def _as_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def _kc_context(row: Mapping[str, Any]) -> Dict[str, Any]:
    topic_path_labels = _as_list(
        row.get("topic_path_labels")
        or row.get("ancestor_topic_labels")
        or row.get("hierarchy_path_labels")
        or row.get("path_labels")
        or row.get("source_hierarchy_path")
        or []
    )
    return {
        **dict(row),
        "kc_id": _as_text(row.get("kc_id") or row.get("node_id") or row.get("id")),
        "canonical_name": _as_text(row.get("canonical_name") or row.get("label") or row.get("name")),
        "aliases": _as_list(row.get("aliases")),
        "topic_path_ids": _as_list(row.get("topic_path_ids")),
        "topic_path_labels": topic_path_labels,
        "parent_topic_id": _as_text(row.get("parent_topic_id") or row.get("parent_node_id") or row.get("parent_id")),
        "parent_topic_label": _as_text(row.get("parent_topic_label") or row.get("parent_label") or (topic_path_labels[-1] if topic_path_labels else "")),
    }


def _risk_flags(candidate: Mapping[str, Any]) -> List[str]:
    flags: List[str] = []

    structural = candidate.get("structural_flags") if isinstance(candidate.get("structural_flags"), Mapping) else {}
    support = candidate.get("support_profile") if isinstance(candidate.get("support_profile"), Mapping) else {}

    text = _as_text(candidate.get("text"))
    lowered = text.lower()
    fallback_tier = _as_text(candidate.get("fallback_tier"))
    hierarchy_signal = _as_text(candidate.get("hierarchy_match_type") or candidate.get("hierarchy_compatibility_signal"))
    caution = _as_text(candidate.get("fallback_caution_reason"))

    if caution:
        flags.append("fallback_caution")

    if structural.get("looks_prompt_like"):
        flags.append("prompt_like")

    if structural.get("looks_fragmentary"):
        flags.append("fragmentary")

    if structural.get("looks_caption_like"):
        flags.append("caption_like")

    if "?" in text and len(text) < 240:
        flags.append("exercise_or_question_like")

    if lowered.startswith(("what are ", "explain ", "describe ", "compare ", "discuss ")):
        flags.append("exercise_or_question_like")

    if fallback_tier in {"branch_local_heading"}:
        flags.append("heading_heavy")

    if not hierarchy_signal:
        flags.append("missing_hierarchy_signal")

    if hierarchy_signal in {"strong_surface_no_heading_contradiction", "surface_anchor_no_branch_tokens", "weak_surface_no_heading"}:
        flags.append("weak_hierarchy_anchor")

    if support.get("anchor_quality") in {"weak", "ambiguous"}:
        flags.append("weak_support_anchor")

    return sorted(set(flags))


def _lane_for_candidate(candidate: Mapping[str, Any], *, strict_min_score: float) -> str:
    score = _as_float(candidate.get("fallback_score") or candidate.get("alignment_score"))
    risk_flags = set(_risk_flags(candidate))
    hierarchy_signal = _as_text(candidate.get("hierarchy_match_type") or candidate.get("hierarchy_compatibility_signal"))
    fallback_tier = _as_text(candidate.get("fallback_tier"))

    hard_risks = {"prompt_like", "caption_like", "fragmentary", "exercise_or_question_like"}

    if risk_flags.intersection(hard_risks):
        return "exploratory_profile_window"

    strong_hierarchy = hierarchy_signal in {
        "heading_branch_overlap",
        "local_context_branch_overlap",
        "strict_process_phase_binding",
    }

    strong_tier = fallback_tier in {
        "exact_surface",
        "target_token",
        "definition_head",
    }

    if score >= strict_min_score and strong_hierarchy and strong_tier and not risk_flags.intersection({"fallback_caution", "weak_support_anchor"}):
        return "strict_source_window"

    return "exploratory_profile_window"


def _window_from_candidate(candidate: Mapping[str, Any], *, lane: str) -> Dict[str, Any]:
    score = _as_float(candidate.get("fallback_score") or candidate.get("alignment_score"))
    risk_flags = _risk_flags(candidate)

    return {
        "snippet_id": _as_text(candidate.get("sentence_id") or candidate.get("candidate_id") or candidate.get("block_id")),
        "candidate_id": _as_text(candidate.get("candidate_id")),
        "text": _as_text(candidate.get("text"))[:1600],
        "source_block_text": _as_text(candidate.get("source_block_text"))[:2400],
        "field_path": "sentence_text",
        "doc_id": candidate.get("doc_id"),
        "page_index": candidate.get("page_index"),
        "patch_id": candidate.get("patch_id"),
        "patch_heading": candidate.get("patch_heading"),
        "reveal_group_id": candidate.get("reveal_group_id"),
        "block_id": candidate.get("block_id"),
        "sentence_id": candidate.get("sentence_id"),
        "layer": candidate.get("layer"),
        "score": round(score, 6),
        "score_reasons": list(candidate.get("fallback_score_reasons") or []),
        "exact_terms": list(candidate.get("matched_surface_terms") or []),
        "stripped_terms": [],
        "target_overlap": list(candidate.get("matched_target_tokens") or []),
        "branch_overlap": list(candidate.get("target_branch_tokens") or []),
        "sibling_hits": [],
        "evidence_shapes": list((candidate.get("support_profile") or {}).get("support_roles") or []),
        "profile_window_lane": lane,
        "profile_window_role": "profiler_input_only_not_evidence",
        "window_supplier": PROFILE_WINDOW_SUPPLIER,
        "source_surface": candidate.get("candidate_source") or SOURCE_SURFACE_FALLBACK,
        "fallback_tier": candidate.get("fallback_tier"),
        "surface_match_type": candidate.get("surface_match_type"),
        "hierarchy_match_type": candidate.get("hierarchy_match_type") or candidate.get("hierarchy_compatibility_signal"),
        "fallback_caution_reason": candidate.get("fallback_caution_reason") or "",
        "risk_flags": risk_flags,
        "provenance": candidate.get("provenance") or {},
    }


def _dedupe_windows(windows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    out: List[Dict[str, Any]] = []
    for window in windows:
        key = (
            _as_text(window.get("snippet_id")),
            _as_text(window.get("doc_id")),
            _as_text(window.get("text"))[:300],
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(window))
    return out


def collect_profile_windows_with_source_surface_kernel(
    *,
    kc_row: Mapping[str, Any],
    all_kc_rows: Sequence[Mapping[str, Any]],
    source_rows: Sequence[Mapping[str, Any]],
    max_snippets_per_kc: int,
    min_score: float,
    dynamic_broad_token_min_df: int = 12,
    sentence_source_manifest: str = "step4_5_sentence_overlay",
    sentence_source_jsonl: str = "sentence_corpus.jsonl",
    embedding_index_root: Path | None = None,
    ollama_host: str | None = None,
    embedding_model: str = "qwen3-embedding:8b",
) -> Dict[str, Any]:
    """Return Step 5p profile windows using the shared source-surface kernel.

    This function does not use historical Step 5x artifacts. It only reuses
    generic source-surface code over the current Step 4.5 sentence overlay.
    Returned windows are profiler inputs only, never final evidence.

    embedding_index_root/ollama_host: when both are provided, the score-sorted
    strict/exploratory pools are passed through rerank_windows_with_embedding_tie_break
    before the final max_snippets_per_kc truncation - embedding similarity only ever reorders
    within a score band that already passed this kernel's own lexical relevance gate, never
    expands the candidate set. When either is None (the default), behavior is unchanged from
    before this parameter existed: plain score-sort then truncate.
    """

    selected_contexts = [_kc_context(kc_row)]
    registry_contexts = [_kc_context(row) for row in all_kc_rows]

    kernel_min_score = max(2.0, float(min_score) - 2.0)
    max_kernel_rows = max(int(max_snippets_per_kc) * 3, int(max_snippets_per_kc))

    result = build_source_surface_fallback_candidates(
        list(source_rows),
        selected_kc_contexts=selected_contexts,
        registry_kc_contexts=registry_contexts,
        existing_candidate_rows=[],
        config={
            "enabled": True,
            "max_fallback_per_kc": max_kernel_rows,
            "min_score": kernel_min_score,
            "require_surface_match": True,
            # Profile mode must not be a hard evidence gate. Let the shared
            # source-surface kernel return surface-anchored windows even when
            # hierarchy compatibility is weak or unavailable, then keep strict
            # lane admission conservative in _lane_for_candidate.
            "require_hierarchy_compatibility": False,
            "dynamic_broad_token_min_doc_frequency": int(dynamic_broad_token_min_df),
            "allow_acronym_surface_match": False,
            "reject_prompt_like": True,
            "reject_fragmentary": True,
            "reject_formula_only_without_surface": True,
        },
        sentence_source_manifest=sentence_source_manifest,
        sentence_source_jsonl=sentence_source_jsonl,
    )

    strict: List[Dict[str, Any]] = []
    exploratory: List[Dict[str, Any]] = []
    risk_counter: Dict[str, int] = defaultdict(int)

    for candidate in result.get("rows") or []:
        lane = _lane_for_candidate(candidate, strict_min_score=float(min_score))
        window = _window_from_candidate(candidate, lane=lane)

        for flag in window.get("risk_flags") or []:
            risk_counter[str(flag)] += 1

        if lane == "strict_source_window":
            strict.append(window)
        else:
            exploratory.append(window)

    strict = _dedupe_windows(strict)
    exploratory = _dedupe_windows(exploratory)

    strict.sort(key=lambda row: float(row.get("score") or 0.0), reverse=True)
    exploratory.sort(key=lambda row: float(row.get("score") or 0.0), reverse=True)

    if embedding_index_root is not None and ollama_host:
        strict_pre_rerank = list(strict)
        exploratory_pre_rerank = list(exploratory)
        strict = rerank_windows_with_embedding_tie_break(
            strict,
            kc_row,
            embedding_index_root=embedding_index_root,
            ollama_host=ollama_host,
            embedding_model=embedding_model,
        )
        exploratory = rerank_windows_with_embedding_tie_break(
            exploratory,
            kc_row,
            embedding_index_root=embedding_index_root,
            ollama_host=ollama_host,
            embedding_model=embedding_model,
        )
        strict = apply_source_diversity_floor(strict, strict_pre_rerank, int(max_snippets_per_kc))
        exploratory = apply_source_diversity_floor(
            exploratory, exploratory_pre_rerank, int(max_snippets_per_kc)
        )
    else:
        strict = strict[: int(max_snippets_per_kc)]
        exploratory = exploratory[: int(max_snippets_per_kc)]

    supplier_stats = {
        "supplier": PROFILE_WINDOW_SUPPLIER,
        "kernel_source_surface": SOURCE_SURFACE_FALLBACK,
        "kernel_rows": len(result.get("rows") or []),
        "strict_source_windows": len(strict),
        "exploratory_profile_windows": len(exploratory),
        "risk_flag_counter": dict(sorted(risk_counter.items())),
        "kernel_stats": result.get("stats") or {},
        "historical_step5x_artifacts_used": False,
        "profile_windows_are_evidence": False,
        "profile_mode_policy": "surface_anchored_windows_allowed_as_exploratory_when_hierarchy_weak",
    }

    return {
        "strict_source_windows": strict,
        "exploratory_profile_windows": exploratory,
        "source_window_supplier_stats": supplier_stats,
    }
