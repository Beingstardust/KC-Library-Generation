from __future__ import annotations

"""Central Step 5x evidence-admission contract.

Minimal purpose:
- scored candidates own the evidence-admission decision;
- pack composition consumes that decision;
- Step 5p profile guidance remains retrieval metadata, not evidence.
"""

import re
from typing import Any, Dict, Iterable, Mapping, Sequence

POSITIVE_ROLES = (
    "definition_kernel",
    "explanatory_gloss",
    "scope_condition",
    "formula_notation",
    "example_or_procedure",
)
AUXILIARY_ROLE = "context_completion"
GUARDRAIL_ROLE = "sibling_contrast"
NONE_ROLE = "none"

DECISION_VALUES = {"ordered_evidence", "auxiliary_context", "guardrail", "review", "reject"}
ROLE_VALUES = set(POSITIVE_ROLES) | {AUXILIARY_ROLE, GUARDRAIL_ROLE, NONE_ROLE}

FORBIDDEN_SEED_OR_LEGACY_FIELDS = {
    "seed_definition",
    "seed_keywords",
    "seed_floor",
    "seed_floor_fallback",
    "seed_definition_text",
    "seed_scope",
    "legacy_eligibility",
}

ALWAYS_REJECT_RISK_FLAGS = {
    "reference_like",
    "bibliography_like",
    "meta_guidance",
    "caption_like",
    "source_kc_mismatch",
}

ORDERED_EVIDENCE_BLOCKER_FLAGS = {
    "suspected_false_positive",
    "reference_like",
    "bibliography_like",
    "meta_guidance",
    "caption_like",
    "formula_without_target_binding",
    "fake_formula_prose",
    "definition_subject_mismatch",
    "sibling_competitor_dominant",
    "source_kc_mismatch",
    "no_target_binding",
    "candidate_pool_membership_only",
}


def _as_mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Iterable) and not isinstance(value, (Mapping, bytes)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)] if str(value).strip() else []


def _unique(values: Sequence[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _as_bool(value: Any) -> bool:
    return value is True or str(value).strip().lower() == "true"


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except Exception:
        return default


def _candidate_text(row: Mapping[str, Any]) -> str:
    for key in ("text", "candidate_text", "source_text", "quote"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _dict_value(row: Mapping[str, Any], key: str) -> Dict[str, Any]:
    value = row.get(key)
    return dict(value) if isinstance(value, Mapping) else {}


def _derived_ordered_evidence_blockers(row: Mapping[str, Any], role: str) -> list[str]:
    """Narrow final-admission blockers from bounded Step5x false-positive audit.

    These blockers do not suppress candidate generation or review visibility.
    They only prevent fragile evidence from entering ordered_pack_for_drafting.
    """
    blockers: list[str] = []

    text = _candidate_text(row)
    lowered = text.lower().strip()
    lexical = _dict_value(row, "lexical_target_binding")
    support = _dict_value(row, "support_profile")
    route_eval = _dict_value(row, "step5p_route_evaluation")
    formula_signal = _dict_value(row, "formula_signal")

    exact_target = _as_bool(lexical.get("exact_target_phrase_in_text"))
    parent_hits = _as_int(lexical.get("parent_topic_token_hits"), 0)
    heading_hits = _as_int(lexical.get("heading_target_match_count"), 0)
    positive_route_hits = _as_int(route_eval.get("positive_route_match_count"), 0)

    matched_tokens = _string_list(
        support.get("matched_target_tokens")
        or (_dict_value(row, "alignment_breakdown").get("matched_target_tokens"))
    )
    surface_match_type = str(
        support.get("surface_match_type")
        or _dict_value(row, "alignment_breakdown").get("surface_match_type")
        or ""
    ).strip()

    candidate_source = str(
        support.get("candidate_source")
        or row.get("candidate_source")
        or ""
    ).strip()

    candidate_origin = str(
        support.get("candidate_origin")
        or row.get("candidate_origin")
        or ""
    ).strip()

    short_alias_surface = (
        candidate_source == "source_surface_fallback"
        and surface_match_type in {"exact_acronym_text", "exact_alias_text"}
        and len([token for token in matched_tokens if token.strip()]) <= 2
        and not exact_target
        and parent_hits == 0
        and heading_hits == 0
        and positive_route_hits == 0
    )
    if short_alias_surface:
        blockers.append("short_alias_surface_without_profile_or_topic_context")

    formula_neighbor_without_profile_or_exact_target = (
        role == "formula_notation"
        and _as_bool(formula_signal.get("is_actual_formula_notation"))
        and not exact_target
        and positive_route_hits == 0
        and (
            candidate_source == "structural_neighbor_from_profile_or_label_anchor"
            or candidate_origin == "section_neighbor_expansion"
        )
    )
    if formula_neighbor_without_profile_or_exact_target:
        blockers.append("formula_neighbor_without_profile_positive_route_or_exact_target")

    unfinished_tail_tokens = {
        "a", "an", "and", "as", "at", "by", "for", "from", "in", "into",
        "is", "of", "on", "or", "the", "to", "with",
    }
    tail = lowered.rstrip(" .,:;")
    last_token = tail.split()[-1] if tail.split() else ""
    if len(lowered) < 120 and last_token in unfinished_tail_tokens:
        blockers.append("truncated_fragment_tail")

    # V2-lite final-admission hardening from bounded31 semantic audit.
    # These checks apply only to ordered drafting evidence, not to review rows.
    # Keep this block narrow. It blocks only proven false-positive shapes.
    definition_framing = _dict_value(row, "definition_framing_score")

    canonical = str(
        row.get("canonical_name")
        or row.get("target_label")
        or row.get("kc_label")
        or row.get("knowledge_unit_label")
        or row.get("source_canonical_name")
        or ""
    ).lower()
    parent_topic = str(row.get("parent_topic_label") or "").lower()
    topic_path = " ".join(str(x).lower() for x in (row.get("topic_path_labels") or []))
    text_tokens = set(t for t in re.findall(r"[a-z0-9]+", lowered) if t)

    citation_like_count = len(re.findall(r"\[\d+\]", text))
    repeated_acronym_count = len(re.findall(r"\b[A-Z]{2,}\b", text))
    semicolon_count = text.count(";")
    comma_count = text.count(",")

    if citation_like_count >= 4 or (
        len(text) > 350
        and repeated_acronym_count >= 8
        and (semicolon_count + comma_count) >= 6
    ):
        blockers.append("table_or_list_like_ordered_evidence")

    unfinished_phrase_tails = {
        "at least",
        "such as",
        "based on",
        "rather than",
        "as a",
        "the following",
    }
    if any(tail.endswith(phrase) for phrase in unfinished_phrase_tails):
        blockers.append("truncated_fragment_tail")

    if re.match(r"^\s*(?:\(?\d+\)?[.)]|[-•])\s+", text):
        blockers.append("numbered_or_bullet_fragment")

    has_predicate = bool(re.search(
        r"\b(is|are|was|were|be|being|been|known|called|defined|measures?|computed?|used|uses|performs?|assigns?|selects?|chooses?|constructs?|obtained|represented|displayed|given|treated|focus(?:es)?|changes?|eliminates?|rejects?)\b",
        lowered,
    ))

    subject_missing = str(definition_framing.get("subject_alignment") or "").lower() == "missing"
    role_is_positive_prose = role in {"definition_kernel", "explanatory_gloss"}

    if role_is_positive_prose and subject_missing and not has_predicate and len(text_tokens) <= 14:
        blockers.append("caption_like_positive_evidence_without_predicate")

    generic_family_tokens = {
        "algorithm", "approach", "criterion", "method", "model", "phase", "probability",
        "search", "test", "tree", "index", "measure", "quality", "target", "targets",
        "values", "attributes",
    }

    branch_tokens = set()
    for raw in re.findall(r"[a-z0-9]+", parent_topic + " " + topic_path):
        if len(raw) >= 5 and raw not in generic_family_tokens:
            branch_tokens.add(raw)

    label_has_parenthetical = "(" in canonical and ")" in canonical
    branch_hit = bool(text_tokens & branch_tokens)

    semantic_parenthetical_terms = []
    for parenthetical_text in re.findall(r"\(([^)]+)\)", canonical):
        raw_terms = [
            raw_term
            for raw_term in re.findall(r"[a-z0-9]+", parenthetical_text)
            if raw_term
        ]
        for raw_term in raw_terms:
            # Treat short symbolic qualifiers such as H0, p, x1, or v2 as notation,
            # not as semantic branch qualifiers that must appear in prose evidence.
            if len(raw_term) >= 4 and raw_term not in generic_family_tokens:
                semantic_parenthetical_terms.append(raw_term)

    parenthetical_hit = False
    if role_is_positive_prose and semantic_parenthetical_terms:
        source_block_text = str(
            row.get("source_block_text")
            or support.get("source_block_text")
            or ""
        ).lower()
        qualifier_text = lowered + " " + source_block_text
        qualifier_tokens = set(re.findall(r"[a-z0-9]+", qualifier_text))

        for term in semantic_parenthetical_terms:
            variants = {term}
            if term.endswith("y") and len(term) > 4:
                variants.add(term[:-1] + "ies")
            else:
                variants.add(term + "s")
            if qualifier_tokens & variants:
                parenthetical_hit = True
                break

        if not parenthetical_hit:
            blockers.append("parenthetical_target_qualifier_missing")

    if (
        role_is_positive_prose
        and semantic_parenthetical_terms
        and not parenthetical_hit
        and not branch_hit
        and parent_hits == 0
        and not exact_target
    ):
        blockers.append("branch_qualified_target_without_branch_context")

    profile_guidance = _dict_value(row, "step5p_profile_guidance")
    profile_status = str(profile_guidance.get("profile_status") or "").strip().lower()
    role_eligibility = _dict_value(row, "role_eligibility")
    candidate_source = str(
        support.get("candidate_source")
        or row.get("candidate_source")
        or ""
    ).strip()

    route_positive_required_without_match = (
        role_is_positive_prose
        and profile_status == "usable"
        and _as_int(route_eval.get("positive_route_match_count"), 0) == 0
        and (
            _as_bool(route_eval.get("route_contract_positive_match_required"))
            or str(route_eval.get("positive_support_block_reason") or "").strip()
            == "profile_route_contract_without_positive_route_match"
        )
        and _as_bool(role_eligibility.get("profile_route_positive_support_bypassed_by_independent_evidence"))
        and candidate_source != "profile_provenance_rehydration"
    )
    if route_positive_required_without_match:
        blockers.append("profile_route_required_without_positive_match")

    return _unique(blockers)


def _contains_forbidden_field(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key) in FORBIDDEN_SEED_OR_LEGACY_FIELDS:
                return True
            if _contains_forbidden_field(nested):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_field(item) for item in value)
    return False


def _primary_positive_role(row: Mapping[str, Any]) -> str:
    eligibility = _as_mapping(row.get("role_eligibility"))
    for role in POSITIVE_ROLES:
        if bool(eligibility.get(role)):
            return role
    return ""


def _warnings(row: Mapping[str, Any], *extra: Iterable[Any]) -> list[str]:
    values: list[Any] = []
    values.extend(_string_list(row.get("risk_flags")))
    values.extend(_string_list(row.get("review_risk_flags")))
    guard = _as_mapping(row.get("positive_support_guard"))
    values.extend(_string_list(guard.get("blocker_flags")))
    for item in extra:
        values.extend(_string_list(item))
    return _unique(values)


def _result(
    decision: str,
    role: str,
    *,
    hard_reasons: Sequence[Any] | None = None,
    warnings: Sequence[Any] | None = None,
    basis: Sequence[Any] | None = None,
) -> Dict[str, Any]:
    return {
        "decision": decision if decision in DECISION_VALUES else "review",
        "role": role if role in ROLE_VALUES else NONE_ROLE,
        "hard_reasons": _unique(list(hard_reasons or [])),
        "warnings": _unique(list(warnings or [])),
        "basis": _unique(list(basis or [])),
    }


def normalize_evidence_admission(row: Mapping[str, Any]) -> Dict[str, Any]:
    existing = row.get("evidence_admission")
    if isinstance(existing, Mapping) and str(existing.get("decision") or "") in DECISION_VALUES:
        return _result(
            str(existing.get("decision") or ""),
            str(existing.get("role") or NONE_ROLE),
            hard_reasons=_string_list(existing.get("hard_reasons")),
            warnings=_string_list(existing.get("warnings")),
            basis=_string_list(existing.get("basis")),
        )
    return decide_evidence_admission(row)


def decide_evidence_admission(row: Mapping[str, Any]) -> Dict[str, Any]:
    if _contains_forbidden_field(row):
        return _result(
            "reject",
            NONE_ROLE,
            hard_reasons=["seed_or_legacy_field_present"],
            basis=["seedless_output_contract"],
        )

    routing = str(row.get("routing_recommendation") or "").strip()
    shapeaware_bucket = str(row.get("shapeaware_bucket") or "").strip()
    risk_flags = set(_string_list(row.get("risk_flags")))
    review_flags = set(_string_list(row.get("review_risk_flags")))

    candidate_quality = _as_mapping(row.get("candidate_quality"))
    role_eligibility = _as_mapping(row.get("role_eligibility"))
    guard = _as_mapping(row.get("positive_support_guard"))

    guard_flags = set(_string_list(guard.get("blocker_flags")))
    guard_blocked = bool(guard.get("blocked_from_positive_support"))

    if shapeaware_bucket == "rejected_false_positive":
        return _result(
            "reject",
            NONE_ROLE,
            hard_reasons=["shapeaware_rejected_false_positive"],
            warnings=_warnings(row),
            basis=["shapeaware_bucket_rejected_false_positive"],
        )

    if shapeaware_bucket == "review_needed":
        return _result(
            "review",
            _primary_positive_role(row) or NONE_ROLE,
            warnings=_warnings(row),
            basis=["shapeaware_bucket_review_needed"],
        )

    if shapeaware_bucket == "auxiliary":
        return _result(
            "auxiliary_context",
            AUXILIARY_ROLE,
            warnings=_warnings(row),
            basis=["shapeaware_bucket_auxiliary"],
        )

    hard_reject_flags = sorted(ALWAYS_REJECT_RISK_FLAGS & risk_flags)
    if hard_reject_flags:
        return _result(
            "reject",
            NONE_ROLE,
            hard_reasons=[f"risk_flag_{flag}" for flag in hard_reject_flags],
            warnings=_warnings(row),
            basis=["hard_reject_risk_flag"],
        )

    if (
        routing == "guardrail_only_candidate"
        or bool(candidate_quality.get("guardrail_only"))
        or bool(role_eligibility.get("sibling_contrast"))
        or bool(role_eligibility.get("guardrail_support_eligible"))
    ):
        return _result(
            "guardrail",
            GUARDRAIL_ROLE,
            warnings=_warnings(row),
            basis=["guardrail_support"],
        )

    if (
        routing == "auxiliary_only_candidate"
        or bool(candidate_quality.get("auxiliary_support"))
        or bool(candidate_quality.get("same_region_auxiliary_only"))
        or bool(role_eligibility.get("context_completion_candidate"))
    ):
        return _result(
            "auxiliary_context",
            AUXILIARY_ROLE,
            warnings=_warnings(row),
            basis=["auxiliary_support"],
        )

    if routing == "positive_role_candidate":
        role = _primary_positive_role(row)
        target_bound = bool(candidate_quality.get("target_bound_positive_support"))
        positive_support_eligible = bool(role_eligibility.get("positive_support_eligible"))
        ordered_blockers = sorted(
            (ORDERED_EVIDENCE_BLOCKER_FLAGS & risk_flags)
            | guard_flags
            | set(_derived_ordered_evidence_blockers(row, role or NONE_ROLE))
        )

        if role and target_bound and positive_support_eligible and not guard_blocked and not ordered_blockers:
            return _result(
                "ordered_evidence",
                role,
                warnings=sorted((risk_flags | review_flags | guard_flags) - ORDERED_EVIDENCE_BLOCKER_FLAGS),
                basis=[
                    "routing_positive_role_candidate",
                    "target_bound_positive_support",
                    "positive_support_guard_unblocked",
                    f"role_{role}",
                ],
            )

        return _result(
            "review",
            role or NONE_ROLE,
            warnings=_warnings(row, ordered_blockers),
            basis=["positive_candidate_not_safe_for_ordered_evidence"],
        )

    if routing in {"manual_review_candidate", "review_only_candidate"} or bool(row.get("review_only_candidate")):
        return _result(
            "review",
            _primary_positive_role(row) or NONE_ROLE,
            warnings=_warnings(row),
            basis=[f"routing_{routing or 'review_candidate'}"],
        )

    lexical = _as_mapping(row.get("lexical_target_binding"))
    if bool(candidate_quality.get("target_bound_positive_support")) or bool(lexical.get("is_target_bound")):
        return _result(
            "review",
            _primary_positive_role(row) or NONE_ROLE,
            warnings=_warnings(row),
            basis=["target_bound_candidate_without_ordered_admission"],
        )

    if "suspected_false_positive" in risk_flags or "fake_formula_prose" in risk_flags:
        return _result(
            "reject",
            NONE_ROLE,
            hard_reasons=[
                flag for flag in ("suspected_false_positive", "fake_formula_prose")
                if flag in risk_flags
            ],
            warnings=_warnings(row),
            basis=["non_admissible_risk_flag"],
        )

    return _result(
        "reject",
        NONE_ROLE,
        hard_reasons=["not_admissible_for_evidence"],
        warnings=_warnings(row),
        basis=[f"routing_{routing or 'empty'}"],
    )
