from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List, Mapping, Sequence


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _tokens(text: Any) -> List[str]:
    return re.findall(r"[a-z0-9]+", _norm(text).lower())


def _token_set(text: Any) -> set[str]:
    return set(_tokens(text))


def _source_text(raw: Mapping[str, Any]) -> str:
    parts: List[str] = []
    for key in ("text", "source_block_text", "patch_heading", "page_heading", "section_heading"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
        elif isinstance(value, list):
            parts.extend(str(item).strip() for item in value if isinstance(item, str) and item.strip())
    return _norm(" ".join(parts))


def _raw_windows(audit: Mapping[str, Any]) -> List[tuple[str, Mapping[str, Any]]]:
    out: List[tuple[str, Mapping[str, Any]]] = []
    for surface in ("strict_source_windows", "exploratory_profile_windows", "candidate_snippets", "profile_candidate_snippets"):
        rows = audit.get(surface) or []
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, Mapping):
                out.append((surface, row))
    return out


def _window_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        _norm(row.get("snippet_id") or row.get("sentence_id") or row.get("source_id")),
        _norm(row.get("doc_id")),
        _norm(row.get("patch_id") or row.get("block_id")),
        _norm(row.get("sentence_id")),
    )


def _is_metadata_or_reference(text: str) -> bool:
    low = _norm(text).lower()
    if not low or len(low) < 4:
        return True
    if any(x in low for x in ("references", "bibliography", "doi:", "http://", "https://", "proceedings")):
        return True
    if low.count("[") + low.count("]") >= 4:
        return True
    if re.search(r"\[[0-9,\s-]{1,20}\]", low) and len(low.split()) < 14:
        return True
    return False


def _safe_public_window(raw: Mapping[str, Any], role: str, reasons: Sequence[str], risks: Sequence[str]) -> Dict[str, Any]:
    item: Dict[str, Any] = {
        "window_role": role,
        "selection_reason": sorted(set(str(x) for x in reasons if _norm(x))),
        "profile_output_role": "source_window_navigation_not_evidence",
        "step5x_verification_required": True,
    }

    for field in (
        "snippet_id",
        "sentence_id",
        "source_id",
        "doc_id",
        "page_index",
        "patch_id",
        "block_id",
        "patch_heading",
        "field_path",
        "match_type",
        "profile_window_role",
    ):
        value = raw.get(field)
        if value not in (None, ""):
            item[field] = value

    risk_flags = sorted(set(str(x) for x in risks if _norm(x)))
    if risk_flags:
        item["risk_flags"] = risk_flags

    return item


def _shape_hints_from_text(text: str) -> List[Dict[str, Any]]:
    low = _norm(text).lower()
    hints: List[Dict[str, Any]] = []

    patterns = [
        ("definition_like", r"\b(defined as|is defined as|refers to|means|is a|are a|is an|called)\b"),
        ("procedure_like", r"\b(step|algorithm|procedure|repeat|iterate|first|then|next)\b"),
        ("formula_like", r"(=|≤|>=|<=|∑|\\sum|\\frac|\\sqrt|\bformula\b|\bequation\b)"),
        ("comparison_like", r"\b(compare|compared|versus|vs\.?|difference|better than|worse than)\b"),
        ("metric_like", r"\b(measure|score|index|coefficient|ratio|distance|similarity)\b"),
    ]

    for shape, pattern in patterns:
        if re.search(pattern, low):
            hints.append({
                "shape": shape,
                "source": "structure_aware_source_window",
                "profile_output_role": "retrieval_guidance_not_evidence",
                "step5x_verification_required": True,
            })

    return hints


def _existing_shape_key(item: Mapping[str, Any]) -> str:
    for key in ("shape", "evidence_shape", "kind", "type"):
        if _norm(item.get(key)):
            return _norm(item.get(key)).lower()
    return ""


def _merge_shape_hints(existing: Sequence[Mapping[str, Any]], inferred: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for item in existing or []:
        if not isinstance(item, Mapping):
            continue
        clone = dict(item)
        key = _existing_shape_key(clone)
        if not key:
            key = _norm(clone)
        if key and key not in seen:
            seen.add(key)
            rows.append(clone)

    for item in inferred:
        key = _existing_shape_key(item)
        if key and key not in seen:
            seen.add(key)
            rows.append(dict(item))

    return rows


def _source_equiv_terms(source_equivalent_terms: Sequence[Mapping[str, Any]]) -> List[str]:
    terms: List[str] = []
    for item in source_equivalent_terms or []:
        if isinstance(item, Mapping) and _norm(item.get("term")):
            terms.append(_norm(item.get("term")).lower())
    return terms


def _source_equiv_hits(text: str, terms: Sequence[str]) -> bool:
    low = _norm(text).lower()
    for term in terms:
        if term and term in low:
            return True
    return False


def _sibling_hit(text: str, profile: Mapping[str, Any]) -> bool:
    low_tokens = _token_set(text)
    canonical_tokens = _token_set(profile.get("canonical_name"))
    for sibling in profile.get("sibling_labels") or []:
        sibling_tokens = _token_set(sibling)
        if not sibling_tokens:
            continue
        if len(sibling_tokens & low_tokens) >= max(1, min(2, len(sibling_tokens))) and len(canonical_tokens & low_tokens) == 0:
            return True
    return False


def _label_overlap_score(text: str, profile: Mapping[str, Any]) -> float:
    label_tokens = _token_set(profile.get("canonical_name"))
    if not label_tokens:
        return 0.0
    low_tokens = _token_set(text)
    return len(label_tokens & low_tokens) / max(1, len(label_tokens))


def _classify_windows(
    *,
    profile: Mapping[str, Any],
    audit: Mapping[str, Any],
    public_source_windows: Sequence[Mapping[str, Any]],
    source_equivalent_terms: Sequence[Mapping[str, Any]],
) -> tuple[List[Dict[str, Any]], Counter, List[Dict[str, Any]]]:
    source_terms = _source_equiv_terms(source_equivalent_terms)
    raw_by_key: Dict[tuple[str, str, str, str], tuple[str, Mapping[str, Any]]] = {}

    for surface, raw in _raw_windows(audit):
        raw_by_key[_window_key(raw)] = (surface, raw)

    rows: List[Dict[str, Any]] = []
    role_counts: Counter = Counter()
    inferred_shape_hints: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()

    input_windows = list(public_source_windows or [])
    if not input_windows:
        input_windows = [raw for _, raw in raw_by_key.values()]

    if not input_windows:
        role_counts["no_source_windows"] += 1
        return rows, role_counts, inferred_shape_hints

    for window in input_windows:
        if not isinstance(window, Mapping):
            continue

        key = _window_key(window)
        if key in seen:
            continue
        seen.add(key)

        surface, raw = raw_by_key.get(key, ("public_source_windows", window))
        text = _source_text(raw)

        reasons: List[str] = []
        risks: List[str] = list(raw.get("risk_flags") or raw.get("profile_window_risk_flags") or [])
        role = "anchor_only"

        if _is_metadata_or_reference(text):
            role = "metadata_or_reference"
            risks.append("metadata_or_reference_window")
            reasons.append("metadata_or_reference_filter")
        elif _source_equiv_hits(text, source_terms):
            role = "candidate_region"
            reasons.append("source_equivalent_term_present")
        elif _sibling_hit(text, profile):
            role = "wrong_sense_risk"
            risks.append("sibling_or_wrong_sense_overlap")
            reasons.append("sibling_overlap_without_target_anchor")
        else:
            overlap = _label_overlap_score(text, profile)
            if overlap >= 0.75:
                role = "candidate_region"
                reasons.append("high_label_overlap")
            elif overlap > 0:
                role = "needs_expansion"
                risks.append("partial_label_overlap_needs_local_context")
                reasons.append("partial_label_overlap")
            elif text:
                role = "anchor_only"
                reasons.append("source_window_without_target_binding")
            else:
                role = "anchor_only"
                reasons.append("no_text_available_in_public_window")

        role_counts[role] += 1
        inferred_shape_hints.extend(_shape_hints_from_text(text))
        rows.append(_safe_public_window(raw, role, reasons, risks))

    return rows, role_counts, inferred_shape_hints


def _extend_negative_constraints(profile: Mapping[str, Any], negative_constraints: Sequence[Mapping[str, Any]], role_counts: Counter) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = [dict(item) for item in negative_constraints if isinstance(item, Mapping)]
    seen = {
        (_norm(row.get("term_or_pattern")).lower(), _norm(row.get("constraint_type")).lower())
        for row in rows
    }

    if role_counts.get("wrong_sense_risk", 0) > 0:
        for sibling in profile.get("sibling_labels") or []:
            term = _norm(sibling)
            key = (term.lower(), "wrong_sense_sibling_guard")
            if term and key not in seen:
                seen.add(key)
                rows.append({
                    "term_or_pattern": term,
                    "constraint_type": "wrong_sense_sibling_guard",
                    "reason": "source_window_role_detected_sibling_or_wrong_sense_risk",
                    "active": False,
                    "profile_output_role": "retrieval_constraint_not_evidence",
                })

    return rows


def _decide_status_and_edge(
    *,
    role_counts: Counter,
    source_equivalent_terms: Sequence[Mapping[str, Any]],
    active_query_terms: Sequence[Mapping[str, Any]],
) -> tuple[str, bool, List[str], Dict[str, Any]]:
    source_equiv_count = len(source_equivalent_terms or [])
    active_count = len(active_query_terms or [])
    candidate_count = int(role_counts.get("candidate_region", 0))
    expansion_count = int(role_counts.get("needs_expansion", 0))
    wrong_sense_count = int(role_counts.get("wrong_sense_risk", 0))
    anchor_count = int(role_counts.get("anchor_only", 0))
    metadata_count = int(role_counts.get("metadata_or_reference", 0))
    no_source_windows_count = int(role_counts.get("no_source_windows", 0))
    total_windows = sum(int(v) for v in role_counts.values())

    reasons: List[str] = []
    llm_required = False
    llm_reasons: List[str] = []

    if no_source_windows_count > 0:
        status = "likely_corpus_insufficient"
        rescue = False
        reasons.append("no_source_windows")
    elif source_equiv_count > 0 and candidate_count > 0 and wrong_sense_count == 0:
        status = "usable"
        rescue = False
        reasons.append("source_equivalent_terms_and_candidate_regions_present")
    elif source_equiv_count > 0 and total_windows > 0:
        status = "weak"
        rescue = False
        reasons.append("source_equivalent_terms_present_but_windows_need_verification")
    elif wrong_sense_count > 0:
        status = "needs_rescue"
        rescue = True
        reasons.append("wrong_sense_or_sibling_risk_present")
        llm_required = True
        llm_reasons.append("ambiguous_window_sense_requires_edge_decision")
    elif expansion_count > 0:
        status = "needs_rescue"
        rescue = True
        reasons.append("partial_source_overlap_needs_expansion")
        llm_required = True
        llm_reasons.append("deterministic_binding_insufficient_but_source_context_exists")
    elif anchor_count > 0:
        status = "anchor_only"
        rescue = True
        reasons.append("anchor_only_windows_without_source_equivalent_terms")
        llm_required = True
        llm_reasons.append("source_mentions_exist_but_no_safe_equivalent_cue")
    elif total_windows == 0 and active_count == 0:
        status = "likely_corpus_insufficient"
        rescue = False
        reasons.append("no_active_terms_and_no_source_windows")
    elif total_windows == 0:
        status = "likely_corpus_insufficient"
        rescue = False
        reasons.append("no_source_windows")
    elif metadata_count == total_windows:
        status = "likely_corpus_insufficient"
        rescue = False
        reasons.append("only_metadata_or_reference_windows")
    else:
        status = "weak"
        rescue = False
        reasons.append("deterministic_guidance_weak_but_not_edge_required")

    llm_router = {
        "llm_required": bool(llm_required),
        "routing_decision": "llm_edge_candidate" if llm_required else "deterministic_only",
        "reasons": sorted(set(llm_reasons)),
        "allowed_outputs": [
            "source_equivalent_term_suggestions",
            "source_window_role_corrections",
            "ambiguity_or_wrong_sense_decision",
        ],
        "forbidden_outputs": [
            "final_kc_definition",
            "final_evidence_admission",
            "kc_specific_criteria",
            "teaching_explanation",
        ],
        "profile_output_role": "routing_metadata_not_evidence",
    }

    return status, rescue, sorted(set(reasons)), llm_router


def apply_structure_aware_profile(
    *,
    profile: Mapping[str, Any],
    audit: Mapping[str, Any],
    source_windows: Sequence[Mapping[str, Any]],
    source_equivalent_terms: Sequence[Mapping[str, Any]],
    active_query_terms: Sequence[Mapping[str, Any]],
    negative_constraints: Sequence[Mapping[str, Any]],
    expected_evidence_shape: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    structured_windows, role_counts, inferred_shapes = _classify_windows(
        profile=profile,
        audit=audit,
        public_source_windows=source_windows,
        source_equivalent_terms=source_equivalent_terms,
    )

    merged_shapes = _merge_shape_hints(expected_evidence_shape, inferred_shapes)
    merged_constraints = _extend_negative_constraints(profile, negative_constraints, role_counts)

    status, rescue, rescue_reasons, llm_router = _decide_status_and_edge(
        role_counts=role_counts,
        source_equivalent_terms=source_equivalent_terms,
        active_query_terms=active_query_terms,
    )

    return {
        "source_windows": structured_windows,
        "negative_constraints": merged_constraints,
        "expected_evidence_shape": merged_shapes,
        "profile_status_for_retrieval": status,
        "rescue_eligible": bool(rescue),
        "rescue_reason": rescue_reasons,
        "llm_edge_router": llm_router,
        "audit": {
            "structure_aware_profile_version": "step5p_v4_structure_aware_profile_v1",
            "source_window_role_counts": dict(role_counts),
            "inferred_evidence_shape_count": len(inferred_shapes),
            "merged_evidence_shape_count": len(merged_shapes),
            "negative_constraint_count": len(merged_constraints),
            "profile_output_is_guidance_not_evidence": True,
            "step5x_remains_evidence_authority": True,
        },
    }
