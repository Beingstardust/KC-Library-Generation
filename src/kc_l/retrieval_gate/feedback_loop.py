from __future__ import annotations

"""Bounded Step 5x to Step 5p feedback-loop support.

This module is deliberately domain-agnostic.  It does not know any course,
KC, or model-specific vocabulary.  It summarizes evidence-retrieval failure
modes into route-repair requests that Step 5p can use to ask the same model
for better retrieval-control routes.  It never turns Step 5p output into final
evidence; Step 5x remains the evidence engine.
"""

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _as_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _bool_nested(row: Mapping[str, Any], *keys: str) -> bool:
    cur: Any = row
    for key in keys:
        if not isinstance(cur, Mapping):
            return False
        cur = cur.get(key)
    return bool(cur)


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _candidate_text(row: Mapping[str, Any]) -> str:
    for key in ("text", "candidate_text", "sentence_text", "source_block_text", "evidence_text", "preview"):
        value = _text(row.get(key))
        if value:
            return value
    return ""


def _row_score(row: Mapping[str, Any]) -> float:
    for key in ("final_score", "score", "ranking_score", "evidence_score"):
        try:
            value = row.get(key)
            if value is not None:
                return float(value)
        except Exception:
            pass
    score_breakdown = _as_dict(row.get("score_breakdown"))
    for key in ("final_score", "total_score", "overall_score"):
        try:
            value = score_breakdown.get(key)
            if value is not None:
                return float(value)
        except Exception:
            pass
    quality = _as_dict(row.get("candidate_quality"))
    try:
        return float(quality.get("overall_score") or 0.0)
    except Exception:
        return 0.0


def read_jsonl(path: Path | str) -> List[Dict[str, Any]]:
    p = Path(path)
    rows: List[Dict[str, Any]] = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path | str, rows: Sequence[Mapping[str, Any]]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_json(path: Path | str, obj: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def _profile_summary_from_scored_rows(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    for row in rows:
        guidance = _as_dict(row.get("step5p_profile_guidance"))
        if guidance:
            return {
                "profile_status": _text(guidance.get("profile_status")),
                "profile_input_status": _text(guidance.get("profile_input_status")),
                "retrieval_route_count": _int(guidance.get("retrieval_route_count") or guidance.get("active_retrieval_route_count")),
                "active_retrieval_route_count": _int(guidance.get("active_retrieval_route_count")),
                "context_only_route_count": _int(guidance.get("context_only_route_count")),
                "accepted_source_cue_count": _int(guidance.get("accepted_source_cue_count")),
                "safe_to_use_for_step5x": bool(guidance.get("safe_to_use_for_step5x")),
            }
    return {
        "profile_status": "unknown",
        "profile_input_status": "unknown",
        "retrieval_route_count": 0,
        "active_retrieval_route_count": 0,
        "context_only_route_count": 0,
        "accepted_source_cue_count": 0,
        "safe_to_use_for_step5x": False,
    }


def _pack_for_kc(packs_by_kc: Mapping[str, Sequence[Mapping[str, Any]]], kc_id: str) -> Mapping[str, Any]:
    packs = list(packs_by_kc.get(kc_id) or [])
    return packs[0] if packs else {}


def _ordered_pack_count(pack: Mapping[str, Any]) -> int:
    return len(_as_list(pack.get("ordered_pack_for_drafting")))


def _slot_count(pack: Mapping[str, Any]) -> int:
    slots = _as_dict(pack.get("slots"))
    return sum(len(_as_list(v)) for v in slots.values())


def _candidate_summary(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "candidate_id": _text(row.get("candidate_id")),
        "candidate_source": _text(row.get("candidate_source") or row.get("stage1_source_surface") or row.get("source_surface")),
        "fallback_tier": _text(row.get("fallback_tier")),
        "patch_heading": _text(row.get("patch_heading")),
        "score": round(_row_score(row), 6),
        "positive_support_eligible": _bool_nested(row, "role_eligibility", "positive_support_eligible"),
        "target_bound_positive_support": _bool_nested(row, "candidate_quality", "target_bound_positive_support"),
        "binding_strength": _text(_as_dict(row.get("lexical_target_binding")).get("binding_strength")),
        "risk_flags": _as_list(row.get("risk_flags"))[:10],
        "route_eval": {
            "route_contract_present": _bool_nested(row, "step5p_route_evaluation", "route_contract_present"),
            "positive_route_match_count": _int(_as_dict(row.get("step5p_route_evaluation")).get("positive_route_match_count")),
            "context_only_route_match_count": _int(_as_dict(row.get("step5p_route_evaluation")).get("context_only_route_match_count")),
            "positive_support_block_reason": _text(_as_dict(row.get("step5p_route_evaluation")).get("positive_support_block_reason")),
        },
        "preview": _candidate_text(row)[:500],
    }


def _gap_tasks_for_types(gap_types: Sequence[str]) -> List[Dict[str, Any]]:
    tasks: List[Dict[str, Any]] = []
    for gap_type in gap_types:
        if gap_type == "zero_candidates":
            tasks.append({
                "task": "find_source_observed_route_terms",
                "instruction": "Identify source-observed phrases, aliases, or local context terms that can retrieve candidate rows for this KC.",
            })
        elif gap_type == "zero_positive_support":
            tasks.append({
                "task": "tighten_positive_support_routes",
                "instruction": "Provide route terms that can create positive support, or explain that only context-only routes are justified by the supplied windows.",
            })
        elif gap_type == "target_bound_contradiction":
            tasks.append({
                "task": "repair_target_binding_or_deactivate_bad_routes",
                "instruction": "Suggest source-observed discriminators, required local support terms, negative constraints, or route deactivations that prevent off-target candidates becoming positive support.",
            })
        elif gap_type == "context_only_support":
            tasks.append({
                "task": "upgrade_or_keep_context_only",
                "instruction": "Decide whether source-observed discriminators can upgrade the context route, otherwise keep it context-only.",
            })
        elif gap_type == "model_timeout_or_no_routes":
            tasks.append({
                "task": "recover_missing_routes_after_timeout_or_empty_profile",
                "instruction": "Using the supplied snippets and candidate summaries, produce a minimal route contract if source-observed evidence exists.",
            })
        elif gap_type == "candidate_present_pack_empty":
            tasks.append({
                "task": "explain_pack_empty_after_candidates",
                "instruction": "Use blocked candidate summaries to identify whether routes need stricter support terms, better aliases, or negative constraints.",
            })
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for task in tasks:
        key = str(task.get("task"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(task)
    return deduped


def build_retrieval_gap_requests(
    *,
    scored_rows: Sequence[Mapping[str, Any]],
    packs: Sequence[Mapping[str, Any]],
    exact_kc_ids: Optional[Sequence[str]] = None,
    source_paths: Optional[Mapping[str, str]] = None,
) -> List[Dict[str, Any]]:
    by_kc: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for row in scored_rows:
        kc_id = _text(row.get("kc_id"))
        if kc_id:
            by_kc[kc_id].append(row)

    packs_by_kc: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for pack in packs:
        kc_id = _text(pack.get("kc_id"))
        if kc_id:
            packs_by_kc[kc_id].append(pack)

    ordered_kcs: List[str] = []
    for kc_id in exact_kc_ids or []:
        text = _text(kc_id)
        if text and text not in ordered_kcs:
            ordered_kcs.append(text)
    for kc_id in sorted(set(by_kc) | set(packs_by_kc)):
        if kc_id not in ordered_kcs:
            ordered_kcs.append(kc_id)

    requests: List[Dict[str, Any]] = []
    for kc_id in ordered_kcs:
        rows = list(by_kc.get(kc_id) or [])
        pack = _pack_for_kc(packs_by_kc, kc_id)
        profile_summary = _profile_summary_from_scored_rows(rows)
        candidate_count = len(rows)
        positive_rows = [r for r in rows if _bool_nested(r, "role_eligibility", "positive_support_eligible")]
        target_bound_false_positive_rows = [
            r for r in positive_rows
            if not _bool_nested(r, "candidate_quality", "target_bound_positive_support")
        ]
        ordered_count = _ordered_pack_count(pack)
        slot_count = _slot_count(pack)
        route_count = _int(profile_summary.get("retrieval_route_count"))
        context_only_route_count = _int(profile_summary.get("context_only_route_count"))
        profile_status = _text(profile_summary.get("profile_status"))

        gap_types: List[str] = []
        if candidate_count == 0:
            gap_types.append("zero_candidates")
        if candidate_count > 0 and len(positive_rows) == 0:
            gap_types.append("zero_positive_support")
        if target_bound_false_positive_rows:
            gap_types.append("target_bound_contradiction")
        if candidate_count > 0 and ordered_count == 0:
            gap_types.append("candidate_present_pack_empty")
        if context_only_route_count > 0 and len(positive_rows) == 0:
            gap_types.append("context_only_support")
        if route_count == 0 and profile_status in {"weak", "reject", "unknown", ""}:
            gap_types.append("model_timeout_or_no_routes")

        if not gap_types:
            continue

        source_counter = Counter(
            _text(row.get("candidate_source") or row.get("stage1_source_surface") or row.get("source_surface"))
            for row in rows
        )
        tier_counter = Counter(_text(row.get("fallback_tier")) for row in rows)
        blocked_rows = [r for r in rows if not _bool_nested(r, "role_eligibility", "positive_support_eligible")]
        top_rows = sorted(rows, key=_row_score, reverse=True)[:8]
        blocked_top = sorted(blocked_rows, key=_row_score, reverse=True)[:8]

        request = {
            "gap_request_version": "step5x_to_step5p_gap_request_v1",
            "gap_request_id": f"gap_{kc_id}",
            "created_at": now_utc_iso(),
            "kc_id": kc_id,
            "gap_types": list(dict.fromkeys(gap_types)),
            "primary_gap_type": gap_types[0],
            "profile_status": profile_status,
            "profile_input_status": _text(profile_summary.get("profile_input_status")),
            "profile_safe_to_use_for_step5x": bool(profile_summary.get("safe_to_use_for_step5x")),
            "route_count": route_count,
            "active_route_count": _int(profile_summary.get("active_retrieval_route_count")),
            "context_only_route_count": context_only_route_count,
            "accepted_source_cue_count": _int(profile_summary.get("accepted_source_cue_count")),
            "candidate_count": candidate_count,
            "positive_support_count": len(positive_rows),
            "ordered_pack_count": ordered_count,
            "slot_item_count": slot_count,
            "candidate_source_counts": dict(source_counter),
            "fallback_tier_counts": dict(tier_counter),
            "target_bound_false_positive_count": len(target_bound_false_positive_rows),
            "top_candidate_summaries": [_candidate_summary(row) for row in top_rows],
            "blocked_candidate_summaries": [_candidate_summary(row) for row in blocked_top],
            "target_bound_false_positive_summaries": [_candidate_summary(row) for row in target_bound_false_positive_rows[:8]],
            "requested_route_tasks": _gap_tasks_for_types(gap_types),
            "feedback_policy": {
                "step5p_role": "route_repair_only_not_final_evidence",
                "step5x_role": "official_evidence_engine",
                "max_feedback_rounds_currently_supported": 1,
                "domain_agnostic": True,
            },
            "source_paths": dict(source_paths or {}),
        }
        requests.append(request)

    return requests


def write_retrieval_gap_artifacts(
    *,
    scored_rows: Sequence[Mapping[str, Any]],
    packs: Sequence[Mapping[str, Any]],
    output_jsonl: Path,
    output_stats_json: Path,
    exact_kc_ids: Optional[Sequence[str]] = None,
    source_paths: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    requests = build_retrieval_gap_requests(
        scored_rows=scored_rows,
        packs=packs,
        exact_kc_ids=exact_kc_ids,
        source_paths=source_paths,
    )
    write_jsonl(output_jsonl, requests)
    stats = {
        "gap_request_version": "step5x_to_step5p_gap_request_v1",
        "created_at": now_utc_iso(),
        "gap_request_count": len(requests),
        "gap_type_breakdown": dict(Counter(g for r in requests for g in _as_list(r.get("gap_types")))),
        "kc_ids_with_gap_requests": [str(r.get("kc_id")) for r in requests],
        "source_paths": dict(source_paths or {}),
    }
    write_json(output_stats_json, stats)
    return stats


def merge_profile_feedback(
    *,
    base_profile: Mapping[str, Any],
    repair_profile: Mapping[str, Any],
    gap_request: Optional[Mapping[str, Any]] = None,
    feedback_round: int = 1,
) -> Dict[str, Any]:
    """Merge one repaired Step 5p profile into a base profile.

    The repair profile is treated as route-control metadata only.  All original
    fields are preserved unless new route/cue/query metadata is added.  The merge
    is deliberately conservative: it only appends non-duplicate cues, queries, and
    routes, and records an audit trail.  It never imports evidence packs or seed
    fields.
    """
    forbidden = {"seed_definition", "seed_floor", "seed_floor_fallback", "seed_keywords"}
    merged: Dict[str, Any] = {k: v for k, v in dict(base_profile).items() if k not in forbidden}

    def append_unique_list(field: str, key_fn) -> int:
        base_items = [dict(x) if isinstance(x, Mapping) else x for x in _as_list(merged.get(field))]
        seen = {key_fn(x) for x in base_items if key_fn(x)}
        added = 0
        for item in _as_list(repair_profile.get(field)):
            if not isinstance(item, Mapping):
                continue
            item_dict = {k: v for k, v in dict(item).items() if k not in forbidden}
            key = key_fn(item_dict)
            if not key or key in seen:
                continue
            item_dict.setdefault("feedback_round", int(feedback_round))
            item_dict.setdefault("source", f"step5p_feedback_round_{int(feedback_round)}")
            base_items.append(item_dict)
            seen.add(key)
            added += 1
        merged[field] = base_items
        return added

    added_cues = append_unique_list(
        "accepted_source_cues",
        lambda x: _text(x.get("term")).lower() if isinstance(x, Mapping) else "",
    )
    added_queries = append_unique_list(
        "query_variants",
        lambda x: _text(x.get("query")).lower() if isinstance(x, Mapping) else "",
    )
    added_routes = append_unique_list(
        "retrieval_routes",
        lambda x: "|".join([
            _text(x.get("route_id")),
            _text(x.get("route_type")),
            ";".join(_text(t).lower() for t in _as_list(x.get("primary_terms_any"))),
        ]) if isinstance(x, Mapping) else "",
    )

    for field in ("quarantined_terms", "rejected_candidates", "sibling_constraint_checks"):
        existing = [dict(x) if isinstance(x, Mapping) else x for x in _as_list(merged.get(field))]
        for item in _as_list(repair_profile.get(field)):
            if isinstance(item, Mapping):
                item_dict = {k: v for k, v in dict(item).items() if k not in forbidden}
                item_dict.setdefault("feedback_round", int(feedback_round))
                existing.append(item_dict)
        merged[field] = existing

    if added_cues or added_routes:
        merged["profile_status"] = "usable"
    elif _text(merged.get("profile_status")) not in {"usable", "weak", "reject"}:
        merged["profile_status"] = _text(repair_profile.get("profile_status")) or "weak"

    audit = dict(merged.get("audit") or {}) if isinstance(merged.get("audit"), Mapping) else {}
    feedback_audit = list(audit.get("feedback_repairs") or [])
    feedback_audit.append({
        "feedback_round": int(feedback_round),
        "gap_request_id": _text((gap_request or {}).get("gap_request_id")),
        "gap_types": _as_list((gap_request or {}).get("gap_types")),
        "repair_profile_status": _text(repair_profile.get("profile_status")),
        "repair_model_used": bool(_as_dict(repair_profile.get("audit")).get("model_used")),
        "repair_model_error": _text(_as_dict(repair_profile.get("audit")).get("model_error")),
        "added_accepted_source_cues": added_cues,
        "added_query_variants": added_queries,
        "added_retrieval_routes": added_routes,
        "repair_source": "step5x_gap_request",
        "role": "route_control_repair_not_final_evidence",
    })
    audit["feedback_round"] = int(feedback_round)
    audit["feedback_repairs"] = feedback_audit
    audit["retrieval_route_count"] = len(_as_list(merged.get("retrieval_routes")))
    audit["accepted_source_cue_count"] = len(_as_list(merged.get("accepted_source_cues")))
    merged["audit"] = audit
    return merged


def _profile_model_error(profile: Mapping[str, Any]) -> str:
    audit = _as_dict(profile.get("audit"))
    return _text(audit.get("model_error"))


def _phase_kc_metric_from_pack(pack: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "ordered_pack_count": _ordered_pack_count(pack),
        "slot_item_count": _slot_count(pack),
    }


def select_feedback_repair_kcs(
    *,
    gap_requests: Sequence[Mapping[str, Any]],
    packs: Sequence[Mapping[str, Any]] = (),
    scored_rows: Sequence[Mapping[str, Any]] = (),
    min_positive_support: int = 1,
    min_ordered_pack_items: int = 1,
    trigger_gap_types: Optional[Sequence[str]] = None,
    context_only_support_triggers_only_if_no_positive_support: bool = True,
    max_selected_kcs: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Select only KCs that should enter an optional feedback repair pass.

    The selector is intentionally conservative.  A gap request is not enough by
    itself if the KC already meets minimum usable evidence thresholds.  This
    prevents the feedback pass from reprocessing good KCs and damaging them due
    to a model timeout or unstable route generation.
    """
    trigger_set = set(trigger_gap_types or [
        "zero_candidates",
        "zero_positive_support",
        "candidate_present_pack_empty",
        "model_timeout_or_no_routes",
        "route_missing_support_terms",
        "target_bound_contradiction",
    ])

    packs_by_kc: Dict[str, Mapping[str, Any]] = {}
    for pack in packs:
        kc_id = _text(pack.get("kc_id"))
        if kc_id and kc_id not in packs_by_kc:
            packs_by_kc[kc_id] = pack

    scored_by_kc: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for row in scored_rows:
        kc_id = _text(row.get("kc_id"))
        if kc_id:
            scored_by_kc[kc_id].append(row)

    selected: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for request in gap_requests:
        kc_id = _text(request.get("kc_id"))
        if not kc_id or kc_id in seen:
            continue

        gap_types = [_text(x) for x in _as_list(request.get("gap_types")) if _text(x)]
        triggered = [g for g in gap_types if g in trigger_set]
        if context_only_support_triggers_only_if_no_positive_support and "context_only_support" in gap_types:
            if _int(request.get("positive_support_count")) <= 0:
                triggered.append("context_only_support")

        pack = packs_by_kc.get(kc_id, {})
        rows = scored_by_kc.get(kc_id, [])
        positive_count = sum(1 for row in rows if _bool_nested(row, "role_eligibility", "positive_support_eligible"))
        if not rows:
            positive_count = _int(request.get("positive_support_count"))
        ordered_count = _ordered_pack_count(pack) if pack else _int(request.get("ordered_pack_count"))

        meets_threshold = positive_count >= int(min_positive_support) and ordered_count >= int(min_ordered_pack_items)
        if not triggered or meets_threshold:
            continue

        selected.append({
            "feedback_selection_version": "step5x_to_step5p_feedback_selection_v1",
            "kc_id": kc_id,
            "gap_request_id": _text(request.get("gap_request_id")),
            "selected": True,
            "selected_gap_types": list(dict.fromkeys(triggered)),
            "all_gap_types": gap_types,
            "positive_support_count": positive_count,
            "ordered_pack_count": ordered_count,
            "selection_reason": "below_threshold_with_trigger_gap_type",
            "policy": {
                "min_positive_support": int(min_positive_support),
                "min_ordered_pack_items": int(min_ordered_pack_items),
                "repair_scope": "kc_local_only",
            },
        })
        seen.add(kc_id)
        if max_selected_kcs is not None and len(selected) >= int(max_selected_kcs):
            break

    return selected


def _rows_by_kc(rows: Sequence[Mapping[str, Any]]) -> Dict[str, List[Mapping[str, Any]]]:
    out: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        kc_id = _text(row.get("kc_id"))
        if kc_id:
            out[kc_id].append(row)
    return out


def _profile_by_kc(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Mapping[str, Any]]:
    out: Dict[str, Mapping[str, Any]] = {}
    for row in rows:
        kc_id = _text(row.get("kc_id"))
        if kc_id:
            out[kc_id] = row
    return out


def _positive_count(rows: Sequence[Mapping[str, Any]]) -> int:
    return sum(1 for row in rows if _bool_nested(row, "role_eligibility", "positive_support_eligible"))


def _target_bound_contradiction_count(rows: Sequence[Mapping[str, Any]]) -> int:
    count = 0
    for row in rows:
        if not _bool_nested(row, "role_eligibility", "positive_support_eligible"):
            continue
        quality = _as_dict(row.get("candidate_quality"))
        if quality.get("target_bound_positive_support") is False:
            count += 1
    return count


def choose_feedback_merge_decision(
    *,
    kc_id: str,
    initial_profile: Mapping[str, Any],
    repair_profile: Mapping[str, Any],
    initial_scored_rows: Sequence[Mapping[str, Any]],
    repair_scored_rows: Sequence[Mapping[str, Any]],
    initial_pack: Mapping[str, Any],
    repair_pack: Mapping[str, Any],
    keep_initial_on_repair_model_error: bool = True,
    keep_initial_if_repair_reduces_positive_support: bool = True,
    keep_initial_if_repair_reduces_ordered_pack: bool = True,
    reject_repair_with_target_bound_contradictions: bool = True,
) -> Dict[str, Any]:
    initial_positive = _positive_count(initial_scored_rows)
    repair_positive = _positive_count(repair_scored_rows)
    initial_ordered = _ordered_pack_count(initial_pack)
    repair_ordered = _ordered_pack_count(repair_pack)
    repair_contradictions = _target_bound_contradiction_count(repair_scored_rows)
    repair_error = _profile_model_error(repair_profile)

    reject_reasons: List[str] = []
    if keep_initial_on_repair_model_error and repair_error:
        reject_reasons.append("repair_model_error")
    if reject_repair_with_target_bound_contradictions and repair_contradictions > 0:
        reject_reasons.append("repair_target_bound_contradiction")
    if keep_initial_if_repair_reduces_positive_support and repair_positive < initial_positive:
        reject_reasons.append("repair_reduces_positive_support")
    if keep_initial_if_repair_reduces_ordered_pack and repair_ordered < initial_ordered:
        reject_reasons.append("repair_reduces_ordered_pack")

    decision = "keep_initial" if reject_reasons else "use_repair"
    return {
        "kc_id": kc_id,
        "decision": decision,
        "reject_reasons": reject_reasons,
        "initial_positive_support_count": initial_positive,
        "repair_positive_support_count": repair_positive,
        "initial_ordered_pack_count": initial_ordered,
        "repair_ordered_pack_count": repair_ordered,
        "repair_target_bound_contradiction_count": repair_contradictions,
        "repair_model_error": repair_error,
    }


def merge_feedback_outputs_by_kc(
    *,
    initial_profiles: Sequence[Mapping[str, Any]],
    repair_profiles: Sequence[Mapping[str, Any]],
    initial_scored_rows: Sequence[Mapping[str, Any]],
    repair_scored_rows: Sequence[Mapping[str, Any]],
    initial_packs: Sequence[Mapping[str, Any]],
    repair_packs: Sequence[Mapping[str, Any]],
    selected_kc_ids: Sequence[str],
) -> Dict[str, Any]:
    """Merge KC-local repair results back into the initial outputs.

    Only selected KCs are eligible for replacement.  A repair is accepted only
    when it does not introduce target-bound contradictions and does not regress
    positive support or ordered-pack counts.  This gives the feedback loop the
    architecture the user intended: repair failed KCs without perturbing good
    KCs.
    """
    selected = {_text(x) for x in selected_kc_ids if _text(x)}
    initial_profile_map = _profile_by_kc(initial_profiles)
    repair_profile_map = _profile_by_kc(repair_profiles)
    initial_scored_by_kc = _rows_by_kc(initial_scored_rows)
    repair_scored_by_kc = _rows_by_kc(repair_scored_rows)
    initial_pack_map = _profile_by_kc(initial_packs)
    repair_pack_map = _profile_by_kc(repair_packs)

    decisions: List[Dict[str, Any]] = []
    accepted_repair_kcs: set[str] = set()

    for kc_id in sorted(selected):
        decision = choose_feedback_merge_decision(
            kc_id=kc_id,
            initial_profile=initial_profile_map.get(kc_id, {}),
            repair_profile=repair_profile_map.get(kc_id, {}),
            initial_scored_rows=initial_scored_by_kc.get(kc_id, []),
            repair_scored_rows=repair_scored_by_kc.get(kc_id, []),
            initial_pack=initial_pack_map.get(kc_id, {}),
            repair_pack=repair_pack_map.get(kc_id, {}),
        )
        decisions.append(decision)
        if decision["decision"] == "use_repair":
            accepted_repair_kcs.add(kc_id)

    def merge_rows(initial_rows: Sequence[Mapping[str, Any]], repair_rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        repair_by_kc = _rows_by_kc(repair_rows)
        emitted: List[Dict[str, Any]] = []
        emitted_kcs: set[str] = set()
        for row in initial_rows:
            kc_id = _text(row.get("kc_id"))
            if kc_id in accepted_repair_kcs:
                if kc_id not in emitted_kcs:
                    emitted.extend(dict(x) for x in repair_by_kc.get(kc_id, []))
                    emitted_kcs.add(kc_id)
            else:
                emitted.append(dict(row))
                if kc_id:
                    emitted_kcs.add(kc_id)
        for kc_id in accepted_repair_kcs:
            if kc_id not in emitted_kcs:
                emitted.extend(dict(x) for x in repair_by_kc.get(kc_id, []))
        return emitted

    final_profiles = merge_rows(initial_profiles, repair_profiles)
    final_scored_rows = merge_rows(initial_scored_rows, repair_scored_rows)
    final_packs = merge_rows(initial_packs, repair_packs)

    stats = {
        "feedback_merge_version": "kc_local_feedback_merge_v1",
        "created_at": now_utc_iso(),
        "selected_kc_count": len(selected),
        "accepted_repair_kc_count": len(accepted_repair_kcs),
        "kept_initial_kc_count": len(selected) - len(accepted_repair_kcs),
        "accepted_repair_kcs": sorted(accepted_repair_kcs),
        "decisions": decisions,
        "policy": {
            "repair_scope": "selected_kcs_only",
            "unselected_kcs": "always_keep_initial",
            "reject_repair_with_target_bound_contradictions": True,
            "keep_initial_on_repair_model_error": True,
            "keep_initial_if_repair_reduces_positive_support": True,
            "keep_initial_if_repair_reduces_ordered_pack": True,
        },
    }

    return {
        "final_profiles": final_profiles,
        "final_scored_rows": final_scored_rows,
        "final_packs": final_packs,
        "merge_stats": stats,
    }
