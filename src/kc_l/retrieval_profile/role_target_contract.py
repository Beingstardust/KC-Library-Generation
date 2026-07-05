from __future__ import annotations

"""Domain-agnostic Step5p role-target contract helpers.

This module is generic control-plane logic. It derives retrieval planning
metadata from source-confirmed profile cues, hierarchy metadata, and source
window locators. It never treats LLM output as evidence, and it never hardcodes
course-domain terms.
"""

import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence

PROFILE_OUTPUT_ROLE = "retrieval_control_metadata_not_evidence"
ROLE_TARGET_CONTRACT_VERSION = "step5p_role_target_contract_v1"
RETRIEVAL_STRATEGY_PLAN_VERSION = "step5p_retrieval_strategy_plan_v1"

VALID_TARGET_ROLES = {
    "primary_core",
    "explanation",
    "formula_or_procedure",
    "example_or_boundary",
    "bridge_context",
}

VALID_SUPPORT_SCOPES = {
    "branch_specific_core",
    "core_or_support",
    "support",
    "parent_or_generic_context",
    "boundary_or_example",
}

VALID_ACTIVATION_STATUSES = {
    "source_confirmed",
    "inactive_until_source_confirmed",
    "context_only",
    "quarantine",
}

GENERIC_DESCRIPTOR_TOKENS = {
    "algorithm",
    "approach",
    "approaches",
    "concept",
    "concepts",
    "criterion",
    "criteria",
    "definition",
    "definitions",
    "equation",
    "equations",
    "example",
    "examples",
    "formula",
    "formulas",
    "framework",
    "frameworks",
    "method",
    "methods",
    "metric",
    "metrics",
    "model",
    "models",
    "phase",
    "phases",
    "procedure",
    "procedures",
    "process",
    "processes",
    "score",
    "scores",
    "step",
    "steps",
    "strategy",
    "strategies",
    "search",
    "searches",
    "generation",
    "generations",
    "classification",
    "classifications",
    "term",
    "terms",
    "type",
    "types",
    "unit",
    "units",
}

FORMULA_DESCRIPTOR_TOKENS = {
    "formula",
    "equation",
    "coefficient",
    "ratio",
    "measure",
    "metric",
    "score",
    "test",
    "probability",
    "distance",
    "index",
    "criterion",
    "theorem",
    "rule",
    "law",
}

EXAMPLE_DESCRIPTOR_TOKENS = {
    "example",
    "case",
    "boundary",
    "limitation",
    "advantage",
    "disadvantage",
    "contrast",
}


def as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def as_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def unique(values: Iterable[Any]) -> List[Any]:
    seen: set[str] = set()
    out: List[Any] = []
    for value in values:
        key = str(value).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def tokens(text: Any, *, min_len: int = 3) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for raw in re.findall(r"[A-Za-z][A-Za-z0-9]+", str(text or "")):
        low = raw.lower()
        if len(low) < min_len or low in seen:
            continue
        seen.add(low)
        out.append(low)
    return out


def normalize_knowledge_unit_type(row: Mapping[str, Any]) -> str:
    raw = as_text(
        row.get("knowledge_unit_type")
        or row.get("node_type")
        or row.get("type")
        or row.get("kind")
        or "kc"
    ).lower()
    if raw in {"topic", "internal_topic", "curriculum_topic"}:
        return "topic"
    if raw in {"kc", "leaf", "knowledge_component", "atomic_kc"}:
        return "kc"
    return raw or "kc"


def normalize_knowledge_unit_id(row: Mapping[str, Any]) -> str:
    return as_text(
        row.get("knowledge_unit_id")
        or row.get("kc_id")
        or row.get("hier_node_id")
        or row.get("node_id")
        or row.get("id")
    )


def normalize_knowledge_unit_fields(row: Mapping[str, Any]) -> Dict[str, str]:
    return {
        "knowledge_unit_id": normalize_knowledge_unit_id(row),
        "knowledge_unit_type": normalize_knowledge_unit_type(row),
    }


def provenance_is_source_confirmed(item: Mapping[str, Any]) -> bool:
    provenance = item.get("provenance") or []
    if not isinstance(provenance, list) or not provenance:
        return False
    for prov in provenance:
        if not isinstance(prov, Mapping):
            continue
        if as_text(prov.get("snippet_id") or prov.get("sentence_id") or prov.get("source_id")):
            return True
    return False


def _content_tokens(text_value: Any, *, min_len: int = 3) -> set[str]:
    return {
        tok
        for tok in tokens(text_value, min_len=min_len)
        if tok not in GENERIC_DESCRIPTOR_TOKENS
    }


def _unit_label_token_set(unit_row: Mapping[str, Any] | None) -> set[str]:
    if not unit_row:
        return set()
    return _content_tokens(" ".join(unit_label_terms(unit_row)), min_len=2)


def _cue_label_overlap(cue: Mapping[str, Any], unit_row: Mapping[str, Any] | None) -> set[str]:
    return _content_tokens(cue.get("term"), min_len=2) & _unit_label_token_set(unit_row)




def _parent_context_token_set(unit_row: Mapping[str, Any] | None) -> set[str]:
    if not unit_row:
        return set()
    values: List[Any] = []
    for key in [
        "topic_path_labels",
        "ancestor_topic_labels",
        "hierarchy_path_labels",
        "path_labels",
        "parent_topic_label",
        "parent_label",
    ]:
        values.extend(as_list(unit_row.get(key)))
    return {
        tok
        for tok in _content_tokens(" ".join(as_text(v) for v in values), min_len=2)
        if tok not in GENERIC_DESCRIPTOR_TOKENS
    }


def _unit_specific_label_token_set(unit_row: Mapping[str, Any] | None) -> set[str]:
    """Return label/alias tokens that distinguish this unit from its parent context."""
    label_tokens = _unit_label_token_set(unit_row)
    parent_tokens = _parent_context_token_set(unit_row)
    specific = {tok for tok in label_tokens if tok not in parent_tokens and tok not in GENERIC_DESCRIPTOR_TOKENS}
    return specific or {tok for tok in label_tokens if tok not in GENERIC_DESCRIPTOR_TOKENS}


def _cue_unit_specific_overlap(cue: Mapping[str, Any], unit_row: Mapping[str, Any] | None) -> set[str]:
    return _content_tokens(cue.get("term"), min_len=2) & _unit_specific_label_token_set(unit_row)


def _cue_has_core_relation_signal(term: str) -> bool:
    low = term.lower()
    return bool(
        re.search(
            r"\b(guarantee|guarantees|guaranteed|optimality|optimal|basis for|relationship between|computed as|defined as|known as|called|denotes|presents|provides|describes|consists of|is used to|can be used to|ensures|requires|visits all|all possible)\b",
            low,
        )
    )

def _cue_has_formula_signal(term: str) -> bool:
    low = term.lower()
    return bool(
        re.search(r"[=∑Σ∏πλρσμ]|\bp\s*\(|\bprobability\b|\bconditional\b|\bequation\b|\bformula\b|\bcomputed\b|\bgiven by\b|\bratio\b|\bcoefficient\b|\bscore\b|\bmetric\b|\bmeasure\b", low)
    )


def _cue_has_definition_signal(term: str) -> bool:
    low = term.lower()
    return bool(
        re.search(r"\b(is|are|refers to|defined as|known as|called|denotes|presents|provides|describes|basis for|relationship between)\b", low)
    )


def _unit_is_formula_like(unit_row: Mapping[str, Any] | None) -> bool:
    if not unit_row:
        return False
    label = " ".join(unit_label_terms(unit_row))
    return bool(_content_tokens(label) & FORMULA_DESCRIPTOR_TOKENS)


def target_role_for_cue(
    cue: Mapping[str, Any],
    *,
    unit_row: Mapping[str, Any] | None = None,
    unit_type: str = "kc",
) -> str:
    """Classify a source-confirmed cue into a retrieval role.

    This remains domain-agnostic. It uses only the runtime unit label/aliases,
    cue text, cue type, and generic role signals. Domain terms belong in the
    profile artifact, not in this code.
    """
    cue_type = as_text(cue.get("cue_type")).lower()
    term = as_text(cue.get("term"))
    term_tokens = _content_tokens(term, min_len=2)
    label_overlap = _cue_label_overlap(cue, unit_row)
    unit_specific_overlap = _cue_unit_specific_overlap(cue, unit_row)
    formula_signal = _cue_has_formula_signal(term)
    definition_signal = _cue_has_definition_signal(term)
    core_relation_signal = _cue_has_core_relation_signal(term)
    formula_like_unit = _unit_is_formula_like(unit_row)

    if unit_type == "topic":
        if label_overlap or definition_signal or core_relation_signal:
            return "explanation"
        return "bridge_context"

    # Formula/theorem/metric/test-like units may use formula/procedure evidence
    # as strong support, but only when the cue is tied to unit-specific wording
    # or the unit itself is formula-like.
    if cue_type in {"formula_relation", "metric_relation"}:
        if unit_specific_overlap or formula_like_unit:
            return "formula_or_procedure"
        return "bridge_context"

    if formula_signal and (unit_specific_overlap or formula_like_unit):
        return "formula_or_procedure"

    # Context phrases are only bridge unless they explicitly mention the
    # unit-specific part of the label. Parent/topic overlap is not enough.
    if cue_type in {"context_phrase"} and not unit_specific_overlap:
        return "bridge_context"

    if any(tok in term_tokens for tok in EXAMPLE_DESCRIPTOR_TOKENS):
        return "example_or_boundary"

    # A source-confirmed cue becomes primary core only if it binds to
    # unit-specific label/alias wording and has definitional, explanatory, or
    # core-relation content. This blocks generic parent hits such as
    # "classification" for a branch-specific classification KC.
    if unit_specific_overlap and (definition_signal or core_relation_signal or cue_type not in {"context_phrase"}):
        return "primary_core"

    return "bridge_context"



def support_scope_for_role(role: str, unit_type: str) -> str:
    if role == "primary_core":
        return "branch_specific_core" if unit_type == "kc" else "support"
    if role == "formula_or_procedure":
        return "core_or_support"
    if role == "bridge_context":
        return "parent_or_generic_context"
    if role == "example_or_boundary":
        return "boundary_or_example"
    return "support"


def source_ids_from_provenance(provenance: Any) -> List[str]:
    ids: List[str] = []
    for prov in as_list(provenance):
        if not isinstance(prov, Mapping):
            continue
        sid = as_text(prov.get("snippet_id") or prov.get("sentence_id") or prov.get("source_id"))
        if sid and sid not in ids:
            ids.append(sid)
    return ids


def unit_label_terms(unit_row: Mapping[str, Any]) -> List[str]:
    values = [
        unit_row.get("canonical_name"),
        unit_row.get("label"),
        unit_row.get("name"),
        *as_list(unit_row.get("aliases")),
    ]
    return unique(as_text(v) for v in values if as_text(v))


def branch_terms_from_unit(
    unit_row: Mapping[str, Any],
    accepted_source_cues: Sequence[Mapping[str, Any]],
) -> List[str]:
    label_text = " ".join(unit_label_terms(unit_row))
    label_tokens = [t for t in tokens(label_text, min_len=2) if t not in GENERIC_DESCRIPTOR_TOKENS]
    acronym_tokens = [t.lower() for t in re.findall(r"\b[A-Z][A-Z0-9]{1,}\b", label_text)]

    source_tokens: List[str] = []
    for cue in accepted_source_cues:
        if not isinstance(cue, Mapping) or not provenance_is_source_confirmed(cue):
            continue
        if target_role_for_cue(cue, unit_row=unit_row, unit_type=normalize_knowledge_unit_type(unit_row)) == "bridge_context":
            continue
        source_tokens.extend(t for t in tokens(cue.get("term")) if t not in GENERIC_DESCRIPTOR_TOKENS)

    return unique([*label_tokens, *acronym_tokens, *source_tokens])[:16]


def generic_parent_terms_from_unit(unit_row: Mapping[str, Any]) -> List[str]:
    values = [
        *as_list(unit_row.get("topic_path_labels")),
        unit_row.get("parent_topic_label"),
        *as_list(unit_row.get("sibling_labels")),
    ]
    out: List[str] = []
    for value in values:
        for tok in tokens(value):
            if tok not in GENERIC_DESCRIPTOR_TOKENS:
                out.append(tok)
    return unique(out)[:24]


def source_section_targets_from_windows(windows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for idx, window in enumerate(windows, start=1):
        if not isinstance(window, Mapping):
            continue
        snippet_id = as_text(window.get("snippet_id") or window.get("surface_id") or window.get("window_id"))
        if not snippet_id:
            continue
        out.append({
            "section_target_id": f"source_section_{idx:03d}",
            "activation_status": "source_confirmed",
            "snippet_id": snippet_id,
            "doc_id": as_text(window.get("doc_id")),
            "page_index": window.get("page_index"),
            "patch_id": as_text(window.get("patch_id")),
            "profile_window_lane": as_text(window.get("profile_window_lane")),
            "profile_output_role": PROFILE_OUTPUT_ROLE,
            "step5x_verification_required": True,
        })
    return out


def build_role_target_contract(
    *,
    unit_row: Mapping[str, Any],
    accepted_source_cues: Sequence[Mapping[str, Any]],
    retrieval_routes: Sequence[Mapping[str, Any]],
    strict_source_windows: Sequence[Mapping[str, Any]],
    exploratory_profile_windows: Sequence[Mapping[str, Any]],
    quarantined_terms: Sequence[Mapping[str, Any]] = (),
    rejected_terms: Sequence[Mapping[str, Any]] = (),
    expected_evidence_shapes: Sequence[Any] = (),
    profile_input_status: str = "unknown",
    source_sparse_label_mismatch: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    unit = normalize_knowledge_unit_fields(unit_row)
    unit_type = unit["knowledge_unit_type"]

    role_targets: List[Dict[str, Any]] = []
    role_counts: Dict[str, int] = {}

    def next_id(role: str) -> str:
        role_counts[role] = role_counts.get(role, 0) + 1
        return f"{role}_{role_counts[role]:03d}"

    for cue in accepted_source_cues:
        if not isinstance(cue, Mapping):
            continue
        term = as_text(cue.get("term"))
        if not term or not provenance_is_source_confirmed(cue):
            continue
        role = target_role_for_cue(cue, unit_row=unit_row, unit_type=unit_type)
        provenance = [dict(p) for p in as_list(cue.get("provenance")) if isinstance(p, Mapping)]
        source_ids = source_ids_from_provenance(provenance)
        support_scope = support_scope_for_role(role, unit_type)
        cannot_be_sole_core = bool(role == "bridge_context" or support_scope == "parent_or_generic_context")
        role_targets.append({
            "role_target_id": next_id(role),
            "target_role": role,
            "support_scope": support_scope,
            "active_terms_any": [term],
            "required_terms_any": [] if role == "bridge_context" else [term],
            "negative_terms_any": [],
            "source_provenance_ids": source_ids,
            "activation_status": "source_confirmed",
            "can_create_candidates": role != "bridge_context",
            "can_create_positive_support": role != "bridge_context",
            "cannot_be_sole_core": cannot_be_sole_core,
            "provenance": provenance,
            "profile_output_role": PROFILE_OUTPUT_ROLE,
            "step5x_verification_required": True,
        })

    if not role_targets and (strict_source_windows or exploratory_profile_windows):
        locators = source_section_targets_from_windows([*strict_source_windows, *exploratory_profile_windows])[:4]
        role_targets.append({
            "role_target_id": "bridge_context_001",
            "target_role": "bridge_context",
            "support_scope": "parent_or_generic_context",
            "active_terms_any": [],
            "required_terms_any": [],
            "negative_terms_any": [],
            "source_section_target_ids": [x["section_target_id"] for x in locators],
            "activation_status": "context_only",
            "can_create_candidates": False,
            "can_create_positive_support": False,
            "cannot_be_sole_core": True,
            "profile_output_role": PROFILE_OUTPUT_ROLE,
            "step5x_verification_required": True,
        })

    shape_text = " ".join(as_text(x) for x in expected_evidence_shapes)
    label_text = " ".join(unit_label_terms(unit_row))
    formula_expected = bool(
        any(role.get("target_role") == "formula_or_procedure" for role in role_targets)
        or bool(set(tokens(shape_text + " " + label_text)) & FORMULA_DESCRIPTOR_TOKENS)
    )
    example_expected = bool(
        any(role.get("target_role") == "example_or_boundary" for role in role_targets)
        or bool(set(tokens(shape_text + " " + label_text)) & EXAMPLE_DESCRIPTOR_TOKENS)
    )

    source_sections = source_section_targets_from_windows([*strict_source_windows, *exploratory_profile_windows])
    branch_terms = branch_terms_from_unit(unit_row, [c for c in accepted_source_cues if isinstance(c, Mapping)])
    generic_parent_terms = generic_parent_terms_from_unit(unit_row)

    unconfirmed: List[Dict[str, Any]] = []
    for item in [*quarantined_terms, *rejected_terms]:
        if not isinstance(item, Mapping):
            continue
        term = as_text(item.get("term"))
        if not term:
            continue
        unconfirmed.append({
            "term": term,
            "status": "inactive_until_source_confirmed",
            "reason": as_text(item.get("reason")) or "not_source_confirmed_for_active_retrieval",
            "related_snippet_ids": [as_text(x) for x in as_list(item.get("related_snippet_ids")) if as_text(x)],
            "profile_output_role": PROFILE_OUTPUT_ROLE,
        })

    rescue_hints: List[Dict[str, Any]] = []
    if profile_input_status in {"no_windows", "exploratory_only", "topic_local_content_scout"}:
        rescue_hints.append({
            "failure_type": "weak_or_missing_profile_windows",
            "next_route": "source_section_targets_then_source_confirmed_role_targets",
            "profile_output_role": PROFILE_OUTPUT_ROLE,
        })
    if source_sparse_label_mismatch:
        rescue_hints.append({
            "failure_type": "source_label_mismatch",
            "next_route": "source_observed_equivalents_before_label_surface",
            "profile_output_role": PROFILE_OUTPUT_ROLE,
        })

    retrieval_strategy_plan = build_retrieval_strategy_plan(
        role_targets=role_targets,
        source_section_targets=source_sections,
        unconfirmed_probe_terms=unconfirmed,
        rescue_hints=rescue_hints,
    )

    return {
        "knowledge_unit_id": unit["knowledge_unit_id"],
        "knowledge_unit_type": unit_type,
        "role_target_contract_version": ROLE_TARGET_CONTRACT_VERSION,
        "role_targets": role_targets,
        "branch_policy": {
            "branch_required_for_core": bool(unit_type == "kc"),
            "branch_terms": branch_terms,
            "generic_parent_terms": generic_parent_terms,
            "generic_parent_terms_bridge_only": True,
            "source": "derived_from_registry_profile_and_source_confirmed_cues",
            "profile_output_role": PROFILE_OUTPUT_ROLE,
        },
        "coverage_goals": {
            "primary_core_required": bool(unit_type == "kc"),
            "support_required_if_available": True,
            "formula_or_procedure_expected": formula_expected,
            "example_or_boundary_expected": example_expected,
            "bridge_context_allowed": True,
            "profile_output_role": PROFILE_OUTPUT_ROLE,
        },
        "source_section_targets": source_sections,
        "unconfirmed_probe_terms": unconfirmed[:20],
        "rescue_hints": rescue_hints,
        "retrieval_strategy_plan": retrieval_strategy_plan,
        "retrieval_strategy_plan_summary": _v2_plan_level_summary(retrieval_strategy_plan),
    }


def _strategy_lane_for_role(role: str, activation_status: str) -> str:
    if activation_status in {"context_only", "quarantine", "inactive_until_source_confirmed"}:
        return "context_or_guardrail"
    if role == "formula_or_procedure":
        return "formula_or_procedure"
    if role == "example_or_boundary":
        return "example_or_boundary"
    if role == "bridge_context":
        return "bridge_context"
    return "primary_core"


def _strategy_priority_for_lane(lane: str) -> int:
    return {
        "primary_core": 10,
        "formula_or_procedure": 20,
        "example_or_boundary": 30,
        "bridge_context": 40,
        "context_or_guardrail": 50,
        "source_section_locator": 60,
        "rescue": 70,
    }.get(lane, 90)


def _role_target_terms(role_target: Mapping[str, Any], key: str) -> List[str]:
    return unique(as_text(x) for x in as_list(role_target.get(key)) if as_text(x))


def build_retrieval_strategy_plan(
    *,
    role_targets: Sequence[Mapping[str, Any]],
    source_section_targets: Sequence[Mapping[str, Any]],
    unconfirmed_probe_terms: Sequence[Mapping[str, Any]],
    rescue_hints: Sequence[Mapping[str, Any]],
    max_items: int = 12,
) -> List[Dict[str, Any]]:
    """Build a compact Step5x-facing strategy view from existing profile fields.

    This is derived retrieval-control metadata, not evidence. It deliberately
    does not ask the model for new content and does not change role_targets,
    retrieval_routes, accepted_source_cues, or fallback behavior.
    """
    plan: List[Dict[str, Any]] = []
    seen: set[tuple[str, tuple[str, ...], tuple[str, ...]]] = set()

    for target in role_targets:
        if not isinstance(target, Mapping):
            continue

        role = as_text(target.get("target_role")) or "bridge_context"
        activation = as_text(target.get("activation_status") or "source_confirmed")
        lane = _strategy_lane_for_role(role, activation)

        query_terms = _role_target_terms(target, "active_terms_any")
        required_terms = _role_target_terms(target, "required_terms_any")
        negative_terms = _role_target_terms(target, "negative_terms_any")
        source_section_ids = unique(
            as_text(x)
            for x in as_list(target.get("source_section_target_ids"))
            if as_text(x)
        )

        if not query_terms and not source_section_ids:
            continue

        key = (
            lane,
            tuple(x.lower() for x in query_terms),
            tuple(x.lower() for x in source_section_ids),
        )
        if key in seen:
            continue
        seen.add(key)

        can_create_candidates = bool(target.get("can_create_candidates") is True and activation == "source_confirmed")
        can_create_positive = bool(target.get("can_create_positive_support") is True and activation == "source_confirmed")
        cannot_be_sole_core = bool(target.get("cannot_be_sole_core") is True)

        risk_level = "low"
        if lane in {"bridge_context", "context_or_guardrail", "source_section_locator", "rescue"}:
            risk_level = "medium"
        if cannot_be_sole_core or not can_create_positive:
            risk_level = "medium"
        if activation in {"quarantine", "inactive_until_source_confirmed"}:
            risk_level = "high"

        if can_create_positive and not cannot_be_sole_core:
            positive_condition = "source text must satisfy this source-confirmed role target and normal Step5x evidence gates"
        elif can_create_candidates:
            positive_condition = "candidate generation only unless another source-confirmed core route is matched"
        else:
            positive_condition = "context only; must not create positive support by itself"

        role_target_id = as_text(target.get("role_target_id"))
        plan.append({
            "strategy_item_id": f"strategy_{len(plan) + 1:03d}",
            "strategy_plan_version": RETRIEVAL_STRATEGY_PLAN_VERSION,
            "lane": lane,
            "priority": _strategy_priority_for_lane(lane),
            "source_role_target_ids": [role_target_id] if role_target_id else [],
            "query_terms_any": query_terms,
            "required_support_terms_any": required_terms,
            "negative_terms_any": negative_terms,
            "source_section_target_ids": source_section_ids,
            "activation_status": activation,
            "can_create_candidates": can_create_candidates,
            "can_create_positive_support": can_create_positive and not cannot_be_sole_core,
            "cannot_be_sole_core": cannot_be_sole_core,
            "positive_support_condition": positive_condition,
            "risk_level": risk_level,
            "failure_mode_if_empty": "source_scarcity_or_label_mismatch" if lane != "bridge_context" else "parent_context_only",
            "profile_output_role": PROFILE_OUTPUT_ROLE,
            "step5x_verification_required": True,
        })

    active_plan = [item for item in plan if item.get("can_create_candidates")]
    if not active_plan and source_section_targets:
        section_ids = [
            as_text(item.get("section_target_id"))
            for item in source_section_targets
            if isinstance(item, Mapping) and as_text(item.get("section_target_id"))
        ]
        if section_ids:
            plan.append({
                "strategy_item_id": f"strategy_{len(plan) + 1:03d}",
                "strategy_plan_version": RETRIEVAL_STRATEGY_PLAN_VERSION,
                "lane": "source_section_locator",
                "priority": _strategy_priority_for_lane("source_section_locator"),
                "source_role_target_ids": [],
                "query_terms_any": [],
                "required_support_terms_any": [],
                "negative_terms_any": [],
                "source_section_target_ids": unique(section_ids)[:6],
                "activation_status": "context_only",
                "can_create_candidates": False,
                "can_create_positive_support": False,
                "cannot_be_sole_core": True,
                "positive_support_condition": "section locator only; Step5x must find separate source-confirmed support",
                "risk_level": "medium",
                "failure_mode_if_empty": "source_scarcity_or_window_locator_only",
                "profile_output_role": PROFILE_OUTPUT_ROLE,
                "step5x_verification_required": True,
            })

    for hint in rescue_hints:
        if not isinstance(hint, Mapping):
            continue
        failure_type = as_text(hint.get("failure_type"))
        next_route = as_text(hint.get("next_route"))
        if not (failure_type or next_route):
            continue

        inactive_terms = [
            as_text(item.get("term"))
            for item in unconfirmed_probe_terms
            if isinstance(item, Mapping) and as_text(item.get("term"))
        ]

        plan.append({
            "strategy_item_id": f"strategy_{len(plan) + 1:03d}",
            "strategy_plan_version": RETRIEVAL_STRATEGY_PLAN_VERSION,
            "lane": "rescue",
            "priority": _strategy_priority_for_lane("rescue"),
            "source_role_target_ids": [],
            "query_terms_any": [],
            "required_support_terms_any": [],
            "negative_terms_any": inactive_terms[:8],
            "source_section_target_ids": [],
            "activation_status": "context_only",
            "can_create_candidates": False,
            "can_create_positive_support": False,
            "cannot_be_sole_core": True,
            "positive_support_condition": "rescue hint only; Step5x must verify source support before promotion",
            "risk_level": "medium",
            "failure_mode_if_empty": failure_type or "retrieval_gap",
            "next_route_hint": next_route,
            "profile_output_role": PROFILE_OUTPUT_ROLE,
            "step5x_verification_required": True,
        })

    plan.sort(key=lambda item: (int(item.get("priority") or 99), str(item.get("strategy_item_id") or "")))
    return plan[:max_items]


def validate_role_target_contract_fields(profile: Mapping[str, Any]) -> Dict[str, List[str]]:
    errors: List[str] = []
    warnings: List[str] = []

    unit_type = as_text(profile.get("knowledge_unit_type") or "kc").lower()
    if unit_type not in {"kc", "topic"}:
        warnings.append(f"unknown_knowledge_unit_type:{unit_type}")

    role_targets = profile.get("role_targets") or []
    if role_targets and not isinstance(role_targets, list):
        errors.append("role_targets_not_list")
        role_targets = []

    for idx, target in enumerate(role_targets):
        if not isinstance(target, Mapping):
            errors.append(f"role_targets[{idx}]_not_object")
            continue

        role = as_text(target.get("target_role"))
        scope = as_text(target.get("support_scope"))
        activation = as_text(target.get("activation_status") or "source_confirmed")

        if role not in VALID_TARGET_ROLES:
            errors.append(f"role_targets[{idx}]_bad_target_role:{role}")
        if scope and scope not in VALID_SUPPORT_SCOPES:
            errors.append(f"role_targets[{idx}]_bad_support_scope:{scope}")
        if activation not in VALID_ACTIVATION_STATUSES:
            errors.append(f"role_targets[{idx}]_bad_activation_status:{activation}")

        if activation == "source_confirmed":
            provenance = target.get("provenance") or []
            source_ids = target.get("source_provenance_ids") or []
            if not provenance and not source_ids:
                errors.append(f"role_targets[{idx}]_source_confirmed_without_provenance")

        if target.get("can_create_positive_support") is True and target.get("cannot_be_sole_core") is True:
            warnings.append(f"role_targets[{idx}]_positive_support_but_cannot_be_sole_core")

    branch_policy = profile.get("branch_policy") or {}
    if branch_policy and not isinstance(branch_policy, Mapping):
        errors.append("branch_policy_not_object")

    coverage_goals = profile.get("coverage_goals") or {}
    if coverage_goals and not isinstance(coverage_goals, Mapping):
        errors.append("coverage_goals_not_object")

    for key in ("source_section_targets", "unconfirmed_probe_terms", "rescue_hints"):
        value = profile.get(key) or []
        if value and not isinstance(value, list):
            errors.append(f"{key}_not_list")

    for idx, term in enumerate(profile.get("unconfirmed_probe_terms") or []):
        if isinstance(term, Mapping) and term.get("active") is True:
            errors.append(f"unconfirmed_probe_terms[{idx}]_active_true")

    retrieval_strategy_plan = profile.get("retrieval_strategy_plan") or []
    if retrieval_strategy_plan and not isinstance(retrieval_strategy_plan, list):
        errors.append("retrieval_strategy_plan_not_list")
        retrieval_strategy_plan = []

    for idx, item in enumerate(retrieval_strategy_plan):
        if not isinstance(item, Mapping):
            errors.append(f"retrieval_strategy_plan[{idx}]_not_object")
            continue
        if as_text(item.get("profile_output_role")) != PROFILE_OUTPUT_ROLE:
            errors.append(f"retrieval_strategy_plan[{idx}]_bad_profile_output_role")
        if item.get("step5x_verification_required") is not True:
            errors.append(f"retrieval_strategy_plan[{idx}]_missing_step5x_verification_required")
        if item.get("can_create_positive_support") is True and item.get("cannot_be_sole_core") is True:
            errors.append(f"retrieval_strategy_plan[{idx}]_positive_support_but_cannot_be_sole_core")
        if not as_text(item.get("lane")):
            errors.append(f"retrieval_strategy_plan[{idx}]_missing_lane")

    for idx, item in enumerate(retrieval_strategy_plan):
        if not isinstance(item, Mapping):
            continue
        if as_text(item.get("strategy_item_contract_version")) == MAXIMAL_RETRIEVAL_PLANNING_CONTRACT_VERSION:
            if as_text(item.get("profile_output_role")) != PROFILE_OUTPUT_ROLE:
                errors.append(f"retrieval_strategy_plan_v2_bad_output_role[{idx}]")
            if item.get("step5x_verification_required") is not True:
                errors.append(f"retrieval_strategy_plan_v2_missing_step5x_verification[{idx}]")
            route_policy = item.get("route_policy") or {}
            if not isinstance(route_policy, Mapping):
                errors.append(f"retrieval_strategy_plan_v2_route_policy_not_object[{idx}]")
            else:
                if route_policy.get("must_not_be_used_as_evidence_directly") is not True:
                    errors.append(f"retrieval_strategy_plan_v2_evidence_boundary_missing[{idx}]")
                if route_policy.get("requires_source_grounding") is not True:
                    errors.append(f"retrieval_strategy_plan_v2_source_grounding_missing[{idx}]")
            lane = as_text(item.get("lane"))
            if lane in {"rescue", "context_or_guardrail", "source_section_locator", "bridge_context"}:
                if item.get("can_create_positive_support") is True:
                    errors.append(f"retrieval_strategy_plan_v2_context_lane_positive_enabled[{idx}]")
                if item.get("cannot_be_sole_core") is not True:
                    errors.append(f"retrieval_strategy_plan_v2_context_lane_can_be_sole_core[{idx}]")

    return {"errors": errors, "warnings": warnings}


# ---------------------------------------------------------------------------
# Step5p maximal retrieval-planning contract v2
# ---------------------------------------------------------------------------
#
# Purpose:
#   Enrich Step5p retrieval-control metadata without changing the evidence
#   boundary. This code does not create evidence, does not draft definitions,
#   and does not bypass Step5x verification. It only organizes already
#   source-grounded/profile-grounded planning signals into a fuller single-pass
#   retrieval plan for the next full 5p run.
#
# Design constraints:
#   - no seed-derived fields or fallback-floor fields in this retrieval-planning contract
#   - no domain-specific hardcoding
#   - no KC-count hardcoding
#   - backward compatible with v1 retrieval_strategy_plan
#   - rescue/context/source-locator material remains non-evidence
#   - every strategy item requires Step5x verification
#
MAXIMAL_RETRIEVAL_PLANNING_CONTRACT_VERSION = "step5p_maximal_retrieval_planning_contract_v2"


def _v2_lower_set(values: Sequence[str]) -> set[str]:
    return {as_text(v).lower() for v in values if as_text(v)}


def _v2_strategy_lane(item: Mapping[str, Any]) -> str:
    return as_text(item.get("lane")) or "primary_core"


def _v2_strategy_query_terms(item: Mapping[str, Any]) -> List[str]:
    return unique(as_text(v) for v in as_list(item.get("query_terms_any")) if as_text(v))


def _v2_required_support_terms(item: Mapping[str, Any]) -> List[str]:
    return unique(as_text(v) for v in as_list(item.get("required_support_terms_any")) if as_text(v))


def _v2_negative_terms(item: Mapping[str, Any]) -> List[str]:
    return unique(as_text(v) for v in as_list(item.get("negative_terms_any")) if as_text(v))


def _v2_source_section_target_ids(item: Mapping[str, Any]) -> List[str]:
    return unique(as_text(v) for v in as_list(item.get("source_section_target_ids")) if as_text(v))


def _v2_evidence_shape_targets(item: Mapping[str, Any]) -> List[str]:
    lane = _v2_strategy_lane(item)
    if lane == "primary_core":
        return ["definition_or_core_explanation", "target_bound_paraphrase", "canonical_label_use"]
    if lane == "formula_or_procedure":
        return ["formula_window", "computation_or_procedure_step", "equation_or_metric_definition"]
    if lane == "example_or_boundary":
        return ["example_window", "boundary_case", "contrastive_example"]
    if lane == "bridge_context":
        return ["local_context_bridge", "parent_topic_context"]
    if lane == "source_section_locator":
        return ["source_section_locator_only"]
    if lane == "rescue":
        return ["retrieval_failure_rescue_hint_only"]
    if lane == "context_or_guardrail":
        return ["guardrail_or_context_only"]
    return ["source_verified_retrieval_candidate"]


def _v2_positive_support_condition(item: Mapping[str, Any]) -> str:
    lane = _v2_strategy_lane(item)
    can_positive = item.get("can_create_positive_support") is True
    cannot_sole = item.get("cannot_be_sole_core") is True

    if lane in {"rescue", "context_or_guardrail", "source_section_locator", "bridge_context"}:
        return "context or locator only; cannot create positive support without a separate source-confirmed core/formula/example route"
    if can_positive and not cannot_sole:
        return "may create candidate support only after Step5x verifies target binding, source grounding, hierarchy sense, and normal evidence gates"
    if item.get("can_create_candidates") is True:
        return "candidate generation only unless Step5x finds independent positive-support evidence"
    return "non-candidate retrieval-control metadata only"


def _v2_hierarchy_sense_constraints(
    item: Mapping[str, Any],
    *,
    role_targets: Sequence[Mapping[str, Any]],
) -> List[str]:
    constraints: List[str] = []

    required = _v2_required_support_terms(item)
    negatives = _v2_negative_terms(item)
    source_sections = _v2_source_section_target_ids(item)

    if required:
        constraints.append("prefer local source windows where required_support_terms_any co-occur with the target or accepted cue")
    if negatives:
        constraints.append("demote or block windows dominated by sibling/negative terms unless a stronger target-bound route is also present")
    if source_sections:
        constraints.append("respect source_section_target_ids as locator context, not as evidence by itself")

    lane = _v2_strategy_lane(item)
    if lane == "formula_or_procedure":
        constraints.append("formula/procedure evidence must be tied to the target KC, not merely to the parent topic")
    elif lane == "primary_core":
        constraints.append("core evidence must explain the target KC sense under the current hierarchy branch")
    elif lane == "example_or_boundary":
        constraints.append("examples must remain examples or boundary cases, not replacement definitions")
    elif lane in {"bridge_context", "source_section_locator", "context_or_guardrail", "rescue"}:
        constraints.append("this lane may guide retrieval context but cannot serve as sole positive support")

    # Keep generic. Do not insert corpus/domain terms.
    return unique(constraints)


def _v2_failure_mode_if_empty(item: Mapping[str, Any]) -> str:
    existing = as_text(item.get("failure_mode_if_empty"))
    if existing:
        return existing

    lane = _v2_strategy_lane(item)
    if lane == "formula_or_procedure":
        return "formula_or_procedure_not_source_bound_to_target"
    if lane == "primary_core":
        return "source_scarcity_or_label_mismatch_for_core_target"
    if lane == "example_or_boundary":
        return "examples_absent_or_not_target_bound"
    if lane == "bridge_context":
        return "only_parent_context_or_bridge_context_found"
    if lane == "source_section_locator":
        return "source_locator_found_without_target_bound_support"
    if lane == "rescue":
        return "retrieval_gap_after_primary_routes"
    return "retrieval_route_empty_or_not_source_bound"


def _v2_route_policy(item: Mapping[str, Any]) -> Dict[str, Any]:
    lane = _v2_strategy_lane(item)
    can_candidate = item.get("can_create_candidates") is True
    can_positive = item.get("can_create_positive_support") is True
    cannot_sole = item.get("cannot_be_sole_core") is True

    return {
        "route_policy_version": MAXIMAL_RETRIEVAL_PLANNING_CONTRACT_VERSION,
        "candidate_generation_allowed": bool(can_candidate and lane not in {"rescue", "context_or_guardrail", "source_section_locator", "bridge_context"}),
        "positive_support_allowed": bool(can_positive and not cannot_sole and lane not in {"rescue", "context_or_guardrail", "source_section_locator", "bridge_context"}),
        "requires_target_binding": True,
        "requires_hierarchy_sense_check": True,
        "requires_source_grounding": True,
        "requires_step5x_verification": True,
        "must_not_be_used_as_evidence_directly": True,
    }


def _v2_enrich_strategy_item(
    item: Mapping[str, Any],
    *,
    role_targets: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    enriched = dict(item)

    lane = _v2_strategy_lane(enriched)
    query_terms = _v2_strategy_query_terms(enriched)
    required_terms = _v2_required_support_terms(enriched)
    negative_terms = _v2_negative_terms(enriched)

    enriched["strategy_item_contract_version"] = MAXIMAL_RETRIEVAL_PLANNING_CONTRACT_VERSION
    enriched["profile_output_role"] = PROFILE_OUTPUT_ROLE
    enriched["step5x_verification_required"] = True

    enriched["evidence_shape_targets"] = _v2_evidence_shape_targets(enriched)
    enriched["hierarchy_sense_constraints"] = _v2_hierarchy_sense_constraints(enriched, role_targets=role_targets)
    enriched["sibling_contrast_terms"] = negative_terms
    enriched["failure_mode_if_empty"] = _v2_failure_mode_if_empty(enriched)
    enriched["positive_support_condition"] = _v2_positive_support_condition(enriched)
    enriched["route_policy"] = _v2_route_policy(enriched)

    # Keep candidate/positive semantics conservative and backward compatible.
    if lane in {"rescue", "context_or_guardrail", "source_section_locator", "bridge_context"}:
        enriched["can_create_positive_support"] = False
        enriched["cannot_be_sole_core"] = True
        if lane in {"rescue", "context_or_guardrail", "source_section_locator"}:
            enriched["can_create_candidates"] = False

    # Lightweight retrieval planner view: not evidence, but gives 5x an explicit
    # route order and safety conditions after the full 5p rerun.
    enriched["retrieval_planner_view"] = {
        "planner_view_version": MAXIMAL_RETRIEVAL_PLANNING_CONTRACT_VERSION,
        "lane": lane,
        "query_terms_any": query_terms,
        "required_support_terms_any": required_terms,
        "negative_terms_any": negative_terms,
        "source_section_target_ids": _v2_source_section_target_ids(enriched),
        "evidence_shape_targets": enriched["evidence_shape_targets"],
        "failure_mode_if_empty": enriched["failure_mode_if_empty"],
        "route_policy": enriched["route_policy"],
    }

    return enriched


def _v2_plan_level_summary(plan: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    lane_counts: Dict[str, int] = {}
    candidate_enabled = 0
    positive_enabled = 0
    negative_term_count = 0
    evidence_shape_counts: Dict[str, int] = {}

    for item in plan:
        lane = _v2_strategy_lane(item)
        lane_counts[lane] = lane_counts.get(lane, 0) + 1
        if item.get("can_create_candidates") is True:
            candidate_enabled += 1
        if item.get("can_create_positive_support") is True:
            positive_enabled += 1
        negative_term_count += len(_v2_negative_terms(item))
        for shape in as_list(item.get("evidence_shape_targets")):
            shape_text = as_text(shape)
            if shape_text:
                evidence_shape_counts[shape_text] = evidence_shape_counts.get(shape_text, 0) + 1

    return {
        "summary_version": MAXIMAL_RETRIEVAL_PLANNING_CONTRACT_VERSION,
        "strategy_item_count": len(list(plan)),
        "lane_counts": lane_counts,
        "candidate_enabled_item_count": candidate_enabled,
        "positive_support_enabled_item_count": positive_enabled,
        "negative_term_count": negative_term_count,
        "evidence_shape_counts": evidence_shape_counts,
        "profile_output_role": PROFILE_OUTPUT_ROLE,
        "step5x_verification_required": True,
        "feedback_loop_status": "not_implemented_single_pass_only",
    }


_ORIGINAL_BUILD_RETRIEVAL_STRATEGY_PLAN_BEFORE_V2 = build_retrieval_strategy_plan


def build_retrieval_strategy_plan(
    *,
    role_targets: Sequence[Mapping[str, Any]],
    source_section_targets: Sequence[Mapping[str, Any]],
    unconfirmed_probe_terms: Sequence[Mapping[str, Any]],
    rescue_hints: Sequence[Mapping[str, Any]],
    max_items: int = 12,
) -> List[Dict[str, Any]]:
    v1_plan = _ORIGINAL_BUILD_RETRIEVAL_STRATEGY_PLAN_BEFORE_V2(
        role_targets=role_targets,
        source_section_targets=source_section_targets,
        unconfirmed_probe_terms=unconfirmed_probe_terms,
        rescue_hints=rescue_hints,
        max_items=max_items,
    )
    return [
        _v2_enrich_strategy_item(item, role_targets=role_targets)
        for item in v1_plan
        if isinstance(item, Mapping)
    ]


