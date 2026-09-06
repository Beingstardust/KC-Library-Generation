from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9']*")

GLUE_TOKENS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}

DESCRIPTOR_TOKENS = {
    "algorithm",
    "algorithms",
    "application",
    "applications",
    "approach",
    "approaches",
    "boundary",
    "boundaries",
    "condition",
    "conditions",
    "coefficient",
    "coefficients",
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
    "function",
    "functions",
    "index",
    "indices",
    "measure",
    "measures",
    "method",
    "methods",
    "metric",
    "metrics",
    "objective",
    "objectives",
    "parameter",
    "parameters",
    "phase",
    "phases",
    "process",
    "processes",
    "procedure",
    "procedures",
    "relationship",
    "relationships",
    "relation",
    "relations",
    "score",
    "scores",
    "stage",
    "stages",
    "step",
    "steps",
    "term",
    "terms",
}

PARAMETER_TOKENS = {
    "parameter",
    "parameters",
    "threshold",
    "thresholds",
    "setting",
    "settings",
    "radius",
    "minimum",
    "maximum",
}

METRIC_TOKENS = {
    "coefficient",
    "equation",
    "formula",
    "index",
    "indices",
    "measure",
    "metric",
    "score",
    "ratio",
    "rate",
}

OBJECTIVE_TOKENS = {
    "cost",
    "energy",
    "likelihood",
    "loss",
    "objective",
}

PROCESS_TOKENS = {
    "phase",
    "process",
    "stage",
    "phases",
    "processes",
    "stages",
}

RELATION_TOKENS = {
    "connected",
    "equivalent",
    "exclusive",
    "independent",
    "reachable",
    "related",
    "separable",
}

EXAMPLE_TOKENS = {
    "application",
    "applications",
    "example",
    "examples",
    "use",
}

BOUNDARY_TOKENS = {
    "boundary",
    "boundaries",
    "condition",
    "conditions",
    "criterion",
    "criteria",
}

PROCESS_CUES = (
    "alternates between",
    "assign",
    "compute",
    "estimate",
    "initialize",
    "iterat",
    "learning",
    "phase",
    "procedure",
    "recompute",
    "repeat",
    "step",
    "train",
    "update",
)

RELATION_CUES = (
    " iff ",
    " chain ",
    " connected ",
    " equivalent ",
    " if ",
    " only if ",
    " reachable ",
    " related ",
    " whenever ",
    " within ",
)

METRIC_CUES = (
    " computed as ",
    " combines ",
    " defined as ",
    " divided by ",
    " equals ",
    " formula ",
    " harmonic ",
    " ratio ",
    " sum of ",
)

OBJECTIVE_CUES = (
    " minimize ",
    " minimiz",
    " maximize ",
    " optimiz",
    " objective function",
    " loss ",
    " cost ",
)

VARIANT_PREFIXES = (
    "adjusted",
    "approximate",
    "extended",
    "generalized",
    "modified",
    "normalized",
    "regularized",
    "robust",
    "smoothed",
    "weighted",
)

PARAMETER_RELATION_CUES = (
    " control ",
    " controls ",
    " decrease ",
    " decreases ",
    " depends on ",
    " determine ",
    " determines ",
    " higher ",
    " increase ",
    " increasing ",
    " jointly ",
    " lower ",
    " reduces ",
    " threshold ",
)

STRONG_PARAMETER_RELATION_CUES = (
    " at least ",
    " at most ",
    " control ",
    " controls ",
    " determine whether ",
    " determines whether ",
    " distance of ",
    " exceeds ",
    " neighborhood ",
    " radius ",
    " supplied parameter ",
    " threshold ",
    " thresholds ",
    " user specified parameter ",
    " user-specified parameter ",
    " within ",
)

SHALLOW_PARAMETER_MENTION_CUES = (
    " choose the parameter ",
    " choose the parameters ",
    " determine the parameter ",
    " determine the parameters ",
    " determines the parameter ",
    " determines the parameters ",
    " how to determine the parameter ",
    " how to determine the parameters ",
    " selecting the parameter ",
    " selecting the parameters ",
    " set the parameter ",
    " set the parameters ",
)

COMPONENT_METRIC_CUES = (
    " false negative ",
    " false positive ",
    " negative predictive value ",
    " positive predictive value ",
    " precision ",
    " recall ",
    " sensitivity ",
    " specificity ",
    " true negative ",
    " true positive ",
)

GREEK_PARAMETER_TOKENS = {
    "alpha",
    "beta",
    "delta",
    "epsilon",
    "gamma",
    "lambda",
    "mu",
    "rho",
    "sigma",
    "tau",
    "theta",
}

NEED_TO_ROLE = {
    "algorithm_procedure": "algorithm_procedure_anchor",
    "boundary_condition": "boundary_condition_anchor",
    "definition_concept": "definition_anchor",
    "formal_relation": "formal_relation_anchor",
    "metric_formula": "metric_formula_anchor",
    "objective_function": "objective_function_anchor",
    "parameter_relationship": "parameter_relationship_anchor",
    "phase_process": "phase_process_anchor",
    "variant_or_index": "variant_metric_anchor",
}

STANDARD_ROUTE_BY_NEED = {
    "algorithm_procedure": "standard_procedure_packet",
    "definition_concept": "standard_definition_packet",
    "formal_relation": "standard_formal_relation_packet",
    "metric_formula": "standard_metric_formula_packet",
    "parameter_relationship": "standard_parameter_packet",
    "phase_process": "standard_phase_process_packet",
}

PRIMARY_NEEDS_BY_DESCRIPTOR = {
    "algorithm": ("algorithm_procedure", "definition_concept", "parameter_relationship"),
    "application": ("example_or_application", "definition_concept"),
    "approach": ("algorithm_procedure", "definition_concept"),
    "boundary": ("boundary_condition", "formal_relation", "definition_concept"),
    "condition": ("boundary_condition", "definition_concept", "formal_relation"),
    "coefficient": ("metric_formula", "definition_concept", "variant_or_index"),
    "criterion": ("boundary_condition", "definition_concept"),
    "definition": ("definition_concept",),
    "equation": ("metric_formula", "definition_concept"),
    "example": ("example_or_application", "definition_concept"),
    "formula": ("metric_formula", "definition_concept", "parameter_relationship"),
    "function": ("objective_function", "definition_concept", "parameter_relationship"),
    "index": ("metric_formula", "definition_concept", "variant_or_index"),
    "measure": ("metric_formula", "definition_concept", "variant_or_index"),
    "method": ("algorithm_procedure", "definition_concept"),
    "metric": ("metric_formula", "definition_concept", "variant_or_index"),
    "objective": ("objective_function", "definition_concept", "parameter_relationship"),
    "parameter": ("parameter_relationship", "definition_concept", "boundary_condition"),
    "phase": ("phase_process", "definition_concept", "algorithm_procedure"),
    "process": ("phase_process", "definition_concept", "algorithm_procedure"),
    "procedure": ("algorithm_procedure", "definition_concept", "parameter_relationship"),
    "relationship": ("formal_relation", "definition_concept", "boundary_condition"),
    "relation": ("formal_relation", "definition_concept", "boundary_condition"),
    "score": ("metric_formula", "definition_concept", "variant_or_index"),
    "stage": ("phase_process", "definition_concept", "algorithm_procedure"),
    "step": ("algorithm_procedure", "definition_concept", "parameter_relationship"),
    "term": ("definition_concept",),
}

SHAPE_HINT_TO_NEED = {
    "context": "context_only",
    "definition": "definition_concept",
    "definition_or_gloss": "definition_concept",
    "example": "example_or_application",
    "example_or_procedure": "algorithm_procedure",
    "formula_or_metric": "metric_formula",
    "mechanism": "algorithm_procedure",
    "metric_gloss": "metric_formula",
    "process": "phase_process",
    "procedure": "algorithm_procedure",
    "scope_condition": "boundary_condition",
}


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _string_list(value: Any) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for item in _as_list(value):
        text = _clean_text(item)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _tokens(text: Any) -> List[str]:
    return [token for token in TOKEN_RE.findall(str(text or ""))]


def _tokens_lower(text: Any) -> List[str]:
    return [token.lower() for token in _tokens(text)]


def _normalize_text(text: Any) -> str:
    text = _clean_text(text)
    text = text.replace("-", " ")
    text = text.replace(":", " ")
    text = text.replace("'", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _contains_phrase(text: str, phrase: str) -> bool:
    phrase_norm = _normalize_text(phrase).lower()
    if not phrase_norm:
        return False
    return f" {phrase_norm} " in f" {_normalize_text(text).lower()} "


def _contains_any(text: str, phrases: Sequence[str]) -> bool:
    return any(_contains_phrase(text, phrase) for phrase in phrases)


def _unique_preserve(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for value in values:
        text = _clean_text(value)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _normalized_surface_variants(values: Sequence[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        text = _clean_text(value)
        if not text:
            continue
        variants = [
            text,
            text.replace("-", " "),
            text.replace(" - ", " "),
            text.replace(": ", " "),
            text.replace(":", " "),
        ]
        for variant in variants:
            variant = _clean_text(variant)
            if variant:
                out.append(variant)
    return _unique_preserve(out)


def _initialism(text: str) -> str:
    parts = [token for token in _tokens(text) if token.lower() not in GLUE_TOKENS]
    if not parts:
        return ""
    return "".join(token[0].upper() for token in parts)


def _replace_acronym_with_parent(term: str, parent_phrase: str) -> Optional[str]:
    if not term or not parent_phrase:
        return None
    term_tokens = _tokens(term)
    if not term_tokens:
        return None
    parent_initials = _initialism(parent_phrase)
    if not parent_initials:
        return None
    replaced = False
    out_tokens: List[str] = []
    for token in term_tokens:
        if token.upper() == parent_initials:
            out_tokens.extend(_tokens(parent_phrase))
            replaced = True
        else:
            out_tokens.append(token)
    if not replaced:
        return None
    return _clean_text(" ".join(out_tokens))


def _split_label(canonical_name: str) -> tuple[str, List[str], List[str]]:
    label = _clean_text(canonical_name)
    qualifiers: List[str] = []
    descriptor_terms: List[str] = []
    concept_head = label

    if ":" in label:
        left, right = label.split(":", 1)
        qualifiers.append(_clean_text(left))
        concept_head = _clean_text(right)
    else:
        tokens = label.split()
        if len(tokens) >= 2 and len(tokens[0]) <= 4 and tokens[0].upper() == tokens[0]:
            qualifiers.append(tokens[0])
            concept_head = _clean_text(" ".join(tokens[1:]))
        elif len(tokens) >= 2 and tokens[-1].lower() in DESCRIPTOR_TOKENS:
            concept_head = _clean_text(" ".join(tokens[:-1]))

    for token in _tokens_lower(label):
        if token in DESCRIPTOR_TOKENS:
            descriptor_terms.append(token)
    return concept_head or label, _unique_preserve(qualifiers), _unique_preserve(descriptor_terms)


def _sanitize_evidence_need_items(items: Sequence[Mapping[str, str]]) -> List[Dict[str, str]]:
    # context_only is a bucket/risk hint, not a target evidence need.
    # It must never become primary, because missing context-only evidence should
    # not demote otherwise valid definition/formula/procedure evidence.
    target_items = [dict(item) for item in items if item.get("need") != "context_only"]
    if not target_items:
        target_items = [
            {
                "need": "definition_concept",
                "priority": "primary",
                "source": "fallback_definition",
            }
        ]
    for index, item in enumerate(target_items):
        item["priority"] = "primary" if index == 0 else "secondary" if index == 1 else "tertiary"
    return target_items


def _need_priority_items(
    primary: Optional[str],
    secondary: Sequence[str] = (),
    tertiary: Sequence[str] = (),
    *,
    sources: Optional[Mapping[str, str]] = None,
) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    if primary:
        items.append({"need": primary, "priority": "primary", "source": (sources or {}).get(primary, "inferred")})
    for need in secondary:
        if need and need != primary and need not in {item["need"] for item in items}:
            items.append({"need": need, "priority": "secondary", "source": (sources or {}).get(need, "inferred")})
    for need in tertiary:
        if need and need not in {item["need"] for item in items}:
            items.append({"need": need, "priority": "tertiary", "source": (sources or {}).get(need, "inferred")})
    return _sanitize_evidence_need_items(items)


def build_shapeaware_guidance(
    unit_context: Mapping[str, Any],
    *,
    query_variants: Optional[Sequence[Mapping[str, Any]]] = None,
    retrieval_routes: Optional[Sequence[Mapping[str, Any]]] = None,
    expected_evidence_shape_hints: Optional[Sequence[Mapping[str, Any]]] = None,
    negative_terms: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    canonical_name = _clean_text(unit_context.get("canonical_name") or unit_context.get("label") or unit_context.get("name"))
    aliases = _string_list(unit_context.get("aliases"))
    sibling_labels = _string_list(unit_context.get("sibling_labels") or unit_context.get("sibling_terms"))
    parent_topic_label = _clean_text(unit_context.get("parent_topic_label"))
    topic_path_labels = _string_list(unit_context.get("topic_path_labels"))

    concept_head, qualifiers, descriptor_terms = _split_label(canonical_name)
    parent_context = [parent_topic_label, *topic_path_labels]
    expanded_aliases: List[str] = []
    for term in [canonical_name, *aliases]:
        for parent_phrase in parent_context:
            expanded = _replace_acronym_with_parent(term, parent_phrase)
            if expanded:
                expanded_aliases.append(expanded)

    raw_surface_terms = [canonical_name, concept_head, *aliases, *expanded_aliases]
    if query_variants:
        raw_surface_terms.extend(_clean_text(item.get("query")) for item in query_variants if _clean_text(item.get("query")))
    normalized_surface_variants = _normalized_surface_variants(raw_surface_terms)

    sources: Dict[str, str] = {}
    ordered_needs: List[str] = []
    for descriptor in descriptor_terms:
        for idx, need in enumerate(PRIMARY_NEEDS_BY_DESCRIPTOR.get(descriptor, ())):
            if need not in ordered_needs:
                ordered_needs.append(need)
                sources[need] = "label_descriptor"

    label_tokens = set(_tokens_lower(canonical_name))
    if label_tokens & RELATION_TOKENS and "formal_relation" not in ordered_needs:
        ordered_needs.insert(0, "formal_relation")
        sources["formal_relation"] = "label_relation_token"
    if label_tokens & PARAMETER_TOKENS and "parameter_relationship" not in ordered_needs:
        ordered_needs.insert(0, "parameter_relationship")
        sources["parameter_relationship"] = "label_parameter_token"
    if label_tokens & PROCESS_TOKENS and "phase_process" not in ordered_needs:
        ordered_needs.insert(0, "phase_process")
        sources["phase_process"] = "label_process_token"
    if label_tokens & OBJECTIVE_TOKENS and "objective_function" not in ordered_needs:
        ordered_needs.insert(0, "objective_function")
        sources["objective_function"] = "label_objective_token"
    if label_tokens & METRIC_TOKENS and "metric_formula" not in ordered_needs:
        ordered_needs.insert(0, "metric_formula")
        sources["metric_formula"] = "label_metric_token"
    if label_tokens & EXAMPLE_TOKENS and "example_or_application" not in ordered_needs:
        ordered_needs.insert(0, "example_or_application")
        sources["example_or_application"] = "label_example_token"

    for hint in _as_list(expected_evidence_shape_hints):
        if not isinstance(hint, Mapping):
            continue
        shape = _clean_text(hint.get("shape_family") or hint.get("shape")).lower()
        need = SHAPE_HINT_TO_NEED.get(shape)
        if need and need not in ordered_needs:
            ordered_needs.append(need)
            sources[need] = "shape_hint"

    if not ordered_needs:
        ordered_needs.append("definition_concept")
        sources["definition_concept"] = "fallback_definition"

    primary = ordered_needs[0]
    secondary: List[str] = []
    tertiary: List[str] = []

    if primary == "algorithm_procedure":
        secondary.extend(["definition_concept"])
        tertiary.extend(["parameter_relationship"])
    elif primary == "metric_formula":
        secondary.extend(["definition_concept"])
        tertiary.extend(["variant_or_index"])
    elif primary == "formal_relation":
        secondary.extend(["definition_concept"])
        tertiary.extend(["boundary_condition"])
    elif primary == "phase_process":
        secondary.extend(["definition_concept"])
        tertiary.extend(["algorithm_procedure"])
    elif primary == "parameter_relationship":
        secondary.extend(["definition_concept"])
        tertiary.extend(["boundary_condition"])
    elif primary == "objective_function":
        secondary.extend(["definition_concept"])
        tertiary.extend(["parameter_relationship"])
    elif primary == "example_or_application":
        secondary.extend(["definition_concept"])
    else:
        secondary.extend([need for need in ordered_needs[1:2]])
        tertiary.extend([need for need in ordered_needs[2:3]])

    if "definition_concept" not in {primary, *secondary, *tertiary} and primary != "definition_concept":
        secondary.append("definition_concept")
        sources.setdefault("definition_concept", "fallback_definition")

    expected_evidence_needs = _need_priority_items(primary, secondary, tertiary, sources=sources)

    route_specific_query_variants: List[Dict[str, Any]] = []
    route_specific_required_terms: List[Dict[str, Any]] = []
    route_specific_optional_terms: List[Dict[str, Any]] = []
    for route in _as_list(retrieval_routes):
        if not isinstance(route, Mapping):
            continue
        route_id = _clean_text(route.get("route_id")) or f"route_{len(route_specific_query_variants) + 1:03d}"
        primary_terms = _string_list(route.get("primary_terms_any"))
        support_any = _string_list(route.get("support_terms_any"))
        support_all = _string_list(route.get("support_terms_all"))
        if primary_terms:
            route_specific_query_variants.append({"route_id": route_id, "queries": primary_terms})
        if support_all:
            route_specific_required_terms.append({"route_id": route_id, "terms": support_all})
        elif _clean_text(route.get("support_requirement")) in {
            "required_for_this_route",
            "required_for_positive_support_on_this_route",
        } and support_any:
            route_specific_required_terms.append({"route_id": route_id, "terms": support_any})
        elif support_any:
            route_specific_optional_terms.append({"route_id": route_id, "terms": support_any})

    negative_sibling_terms = _unique_preserve([*sibling_labels, *(_string_list(negative_terms))])
    risk_hints: List[str] = []
    if qualifiers:
        risk_hints.append("qualifier_dependent_target")
    if any(len(token) <= 4 and token.upper() == token for token in qualifiers):
        risk_hints.append("acronym_expansion_may_be_required")
    if primary == "formal_relation":
        risk_hints.append("hyphen_or_relation_surface_normalization")
    if primary == "metric_formula":
        risk_hints.append("variant_metric_review_possible")
    if primary == "parameter_relationship":
        risk_hints.append("parameter_names_may_be_symbolic")

    return {
        "concept_head": concept_head or canonical_name,
        "qualifiers": qualifiers,
        "expanded_aliases": _unique_preserve(expanded_aliases),
        "normalized_surface_variants": normalized_surface_variants,
        "expected_evidence_needs": expected_evidence_needs,
        "route_specific_query_variants": route_specific_query_variants,
        "route_specific_required_terms": route_specific_required_terms,
        "route_specific_optional_terms": route_specific_optional_terms,
        "negative_sibling_terms": negative_sibling_terms,
        "risk_hints": _unique_preserve(risk_hints),
    }


def _concept_head_from_needs(row: Mapping[str, Any], expected_evidence_needs: Optional[Sequence[Mapping[str, Any]]]) -> Dict[str, Any]:
    policy_plan = row.get("step5x_retrieval_policy_plan") or {}
    if not isinstance(policy_plan, Mapping):
        policy_plan = {}
    query_variants = _as_list(row.get("query_variants"))
    retrieval_routes = _as_list(row.get("retrieval_routes"))
    shape_hints = _as_list(row.get("expected_evidence_shape_hints"))
    negative_terms = _string_list(row.get("negative_terms"))
    guidance = build_shapeaware_guidance(
        row,
        query_variants=[item for item in query_variants if isinstance(item, Mapping)],
        retrieval_routes=[item for item in retrieval_routes if isinstance(item, Mapping)],
        expected_evidence_shape_hints=[item for item in shape_hints if isinstance(item, Mapping)],
        negative_terms=negative_terms,
    )
    concept_head = _clean_text(row.get("concept_head")) or _clean_text(policy_plan.get("concept_head"))
    if concept_head:
        guidance["concept_head"] = concept_head

    for field_name in (
        "qualifiers",
        "expanded_aliases",
        "normalized_surface_variants",
        "negative_sibling_terms",
        "risk_hints",
    ):
        values = _string_list(row.get(field_name))
        if not values:
            values = _string_list(policy_plan.get(field_name))
        if values:
            guidance[field_name] = values

    for field_name in (
        "route_specific_query_variants",
        "route_specific_required_terms",
        "route_specific_optional_terms",
    ):
        items = [dict(item) for item in _as_list(row.get(field_name)) if isinstance(item, Mapping)]
        if not items:
            items = [dict(item) for item in _as_list(policy_plan.get(field_name)) if isinstance(item, Mapping)]
        if items:
            guidance[field_name] = items

    if expected_evidence_needs:
        guidance["expected_evidence_needs"] = _sanitize_evidence_need_items(
            [dict(item) for item in expected_evidence_needs if isinstance(item, Mapping)]
        )
    else:
        policy_expected = [
            dict(item)
            for item in _as_list(row.get("expected_evidence_needs"))
            if isinstance(item, Mapping)
        ]
        if not policy_expected:
            policy_expected = [
                dict(item)
                for item in _as_list(policy_plan.get("expected_evidence_needs"))
                if isinstance(item, Mapping)
            ]
        if policy_expected:
            guidance["expected_evidence_needs"] = _sanitize_evidence_need_items(policy_expected)
    return guidance


def _row_score(row: Mapping[str, Any]) -> float:
    quality = row.get("candidate_quality") or {}
    try:
        return float(quality.get("overall_score") or 0.0)
    except Exception:
        return 0.0


def _parameter_like_token_count(text: str) -> int:
    count = 0
    for index, token in enumerate(_tokens(text)):
        low = token.lower()
        if token.lower() in GREEK_PARAMETER_TOKENS:
            count += 1
            continue
        if len(token) >= 2 and token.upper() == token and token.isalpha():
            count += 1
            continue
        if (
            index > 0
            and len(token) <= 8
            and token[:1].isupper()
            and token[1:].islower()
            and low not in GLUE_TOKENS
            and low not in PARAMETER_TOKENS
        ):
            count += 1
            continue
        if re.search(r"[A-Z].*[A-Z]", token):
            count += 1
            continue
        if re.search(r"[A-Za-z]+\d", token):
            count += 1
            continue
    return count



def _variant_only_metric(text: str, concept_head: str, normalized_variants: Sequence[str]) -> bool:
    """Detect metric/index variants that are review evidence, not clean core."""
    import re

    def norm(value: object) -> str:
        value = str(value or "").lower()
        value = value.replace("–", " ").replace("—", " ").replace("-", " ")
        value = re.sub(r"[^a-z0-9]+", " ", value)
        return re.sub(r"\s+", " ", value).strip()

    haystack = norm(text)
    head = norm(concept_head)
    variants = [norm(v) for v in (normalized_variants or []) if norm(v)]

    if not haystack or not head:
        return False

    metricish_terms = {
        "index",
        "measure",
        "metric",
        "coefficient",
        "score",
        "statistic",
        "similarity",
        "distance",
        "precision",
        "recall",
        "accuracy",
        "error",
        "loss",
    }

    target_blob = " ".join([head] + variants)
    if not any(term in target_blob.split() for term in metricish_terms):
        return False

    modifiers = [
        "adjusted",
        "modified",
        "weighted",
        "normalized",
        "normalised",
        "corrected",
        "regularized",
        "regularised",
        "smoothed",
        "robust",
        "generalized",
        "generalised",
        "extended",
        "approximate",
        "chance adjusted",
        "chance corrected",
        "corrected for chance",
    ]

    target_phrases: List[str] = []
    for phrase in [head] + variants:
        phrase = norm(phrase)
        if phrase and phrase not in target_phrases:
            target_phrases.append(phrase)

    # Source-observed aliases such as "adjusted Rand index" are variant evidence.
    for phrase in target_phrases:
        if phrase not in haystack:
            continue
        padded_phrase = " " + phrase + " "
        for modifier in modifiers:
            mod = norm(modifier)
            if padded_phrase.startswith(" " + mod + " ") or (" " + mod + " ") in padded_phrase:
                return True

    # Also catch modifier immediately before the canonical target phrase.
    for phrase in target_phrases:
        if len(phrase.split()) < 2:
            continue
        for modifier in modifiers:
            mod = norm(modifier)
            if re.search(r"\b" + re.escape(mod) + r"\s+" + re.escape(phrase) + r"\b", haystack):
                return True

    return False



def _local_window_text(row: Mapping[str, Any], text: str) -> str:
    parts = [text]
    for field_name in ("context_text", "evidence_window_text", "surrounding_text", "source_block_text"):
        part = _clean_text(row.get(field_name))
        if part and _normalize_text(part).lower() not in {
            _normalize_text(existing).lower() for existing in parts if existing
        }:
            parts.append(part)
    return _clean_text(" ".join(part for part in parts if part))


def _surface_anchor_present(text: str, concept_head: str, normalized_variants: Sequence[str]) -> bool:
    surface_terms = _unique_preserve([concept_head, *normalized_variants])
    return any(_contains_phrase(text, term) for term in surface_terms if _clean_text(term))


def _component_metric_only(text: str, concept_head: str, normalized_variants: Sequence[str]) -> bool:
    text_norm = f" {_normalize_text(text).lower()} "
    if _surface_anchor_present(text, concept_head, normalized_variants):
        return False
    return any(cue in text_norm for cue in COMPONENT_METRIC_CUES)


def _definition_anchor_candidate(
    row: Mapping[str, Any],
    text: str,
    subject_alignment: str,
    definition_style: str,
) -> bool:
    support_roles = _string_list((row.get("support_profile") or {}).get("support_roles"))
    if "definitional_anchor" in support_roles and subject_alignment in {"aligned", "compatible"}:
        return True
    if row.get("routing_recommendation") == "positive_role_candidate" and definition_style != "none" and subject_alignment in {"aligned", "compatible"}:
        return True
    return False


def _metric_formula_candidate(row: Mapping[str, Any], text: str) -> bool:
    formula_signal = row.get("formula_signal") or {}
    support_roles = set(_string_list((row.get("support_profile") or {}).get("support_roles")))
    text_norm = f" {_normalize_text(text).lower()} "
    if bool(formula_signal.get("is_actual_formula_notation")):
        return True
    if "formula_or_metric" in support_roles:
        return True
    return any(cue in text_norm for cue in METRIC_CUES)


def _procedure_candidate(row: Mapping[str, Any], text: str) -> bool:
    signal = row.get("procedure_or_example_signal") or {}
    support_roles = set(_string_list((row.get("support_profile") or {}).get("support_roles")))
    text_norm = _normalize_text(text).lower()
    if float(signal.get("procedure_score") or 0.0) > 0.0:
        return True
    if "process_or_procedure" in support_roles:
        return True
    return any(cue.strip() in text_norm for cue in PROCESS_CUES)


def _objective_candidate(text: str) -> bool:
    text_norm = f" {_normalize_text(text).lower()} "
    return any(cue in text_norm for cue in OBJECTIVE_CUES)


def _formal_relation_candidate(text: str, canonical_name: str) -> bool:
    label_tokens = set(_tokens_lower(canonical_name))
    text_norm = f" {_normalize_text(text).lower()} "
    relation_tokens = label_tokens & RELATION_TOKENS
    if relation_tokens and any(f" {token} " in text_norm for token in relation_tokens):
        return True
    return any(cue in text_norm for cue in RELATION_CUES)


def _phase_process_candidate(text: str, canonical_name: str) -> bool:
    label_tokens = set(_tokens_lower(canonical_name))
    text_norm = _normalize_text(text).lower()
    if label_tokens & {"phase", "process", "stage"} and _procedure_candidate({"procedure_or_example_signal": {}}, text):
        return True
    return any(cue.strip() in text_norm for cue in PROCESS_CUES)


def _parameter_relationship_candidate(text: str, canonical_name: str) -> bool:
    label_tokens = set(_tokens_lower(canonical_name))
    text_norm = f" {_normalize_text(text).lower()} "
    if not (label_tokens & PARAMETER_TOKENS):
        return False
    relation_like = any(cue in text_norm for cue in PARAMETER_RELATION_CUES)
    return relation_like and _parameter_like_token_count(text) >= 2


def _strong_parameter_relationship_candidate(text: str, canonical_name: str) -> bool:
    label_tokens = set(_tokens_lower(canonical_name))
    text_norm = f" {_normalize_text(text).lower()} "
    if not (label_tokens & PARAMETER_TOKENS):
        return False
    if not any(cue in text_norm for cue in STRONG_PARAMETER_RELATION_CUES):
        return False
    return _parameter_like_token_count(text) >= 1


def _shallow_parameter_mention(text: str, canonical_name: str) -> bool:
    label_tokens = set(_tokens_lower(canonical_name))
    text_norm = f" {_normalize_text(text).lower()} "
    return bool(label_tokens & PARAMETER_TOKENS) and any(cue in text_norm for cue in SHALLOW_PARAMETER_MENTION_CUES)


def classify_shapeaware_candidate(
    row: Mapping[str, Any],
    expected_evidence_needs: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    guidance = _concept_head_from_needs(row, expected_evidence_needs)
    expected = guidance["expected_evidence_needs"]
    primary_need = next((item["need"] for item in expected if item.get("priority") == "primary"), "definition_concept")
    concept_head = guidance["concept_head"]
    normalized_variants = guidance["normalized_surface_variants"]
    text = _clean_text(row.get("candidate_text") or row.get("text"))
    local_text = _local_window_text(row, text)
    support_profile = row.get("support_profile") or {}
    binding = row.get("lexical_target_binding") or {}
    definition = row.get("definition_framing_score") or {}
    contamination = row.get("contamination_signals") or {}
    guard = row.get("positive_support_guard") or {}
    sibling = row.get("sibling_or_competitor_signals") or {}
    role_eligibility = row.get("role_eligibility") or {}

    target_bound = bool(binding.get("is_target_bound"))
    binding_strength = _clean_text(binding.get("binding_strength"))
    subject_alignment = _clean_text(definition.get("subject_alignment"))
    definition_style = _clean_text(definition.get("definition_style"))
    review_only = bool(role_eligibility.get("review_only_candidate") or support_profile.get("review_only_candidate"))
    broad_topic_only = bool(contamination.get("broad_topic_only") or support_profile.get("generic_context_only"))
    generic_context_only = bool(support_profile.get("generic_context_only"))
    sibling_overlap = bool(sibling.get("genuine_sibling_signal"))
    guard_blockers = _string_list(guard.get("blocker_flags"))
    same_region_auxiliary_only = bool((row.get("candidate_quality") or {}).get("same_region_auxiliary_only"))
    formula_signal = row.get("formula_signal") or {}
    metric_surface_anchor = _surface_anchor_present(local_text, concept_head, normalized_variants)
    metric_target_anchor = bool(metric_surface_anchor)
    metric_component_only = bool(
        primary_need == "metric_formula"
        and _component_metric_only(local_text, concept_head, normalized_variants)
    )
    strong_parameter_relation = _strong_parameter_relationship_candidate(text, _clean_text(row.get("canonical_name")))
    shallow_parameter_mention = _shallow_parameter_mention(text, _clean_text(row.get("canonical_name")))

    support_roles: List[str] = []
    review_flags: List[str] = []

    if _definition_anchor_candidate(row, text, subject_alignment, definition_style):
        support_roles.append("definition_anchor")
    if _metric_formula_candidate(row, text):
        support_roles.append("metric_formula_anchor")
    if _procedure_candidate(row, text):
        support_roles.append("algorithm_procedure_anchor")
    if _objective_candidate(text):
        support_roles.append("objective_function_anchor")
    if _formal_relation_candidate(text, _clean_text(row.get("canonical_name"))):
        support_roles.append("formal_relation_anchor")
    if _phase_process_candidate(text, _clean_text(row.get("canonical_name"))):
        support_roles.append("phase_process_anchor")
    if _parameter_relationship_candidate(text, _clean_text(row.get("canonical_name"))):
        support_roles.append("parameter_relationship_anchor")
    if role_eligibility.get("context_completion_candidate") or bool((row.get("candidate_quality") or {}).get("same_region_auxiliary_only")):
        support_roles.append("context_completion")
    if generic_context_only or broad_topic_only or review_only:
        support_roles.append("auxiliary_context")

    # Variant evidence (for example adjusted/weighted/normalized forms of a
    # target metric/index) is useful review evidence even when it is not direct
    # base-target support. It must not be promoted to drafting core.
    variant_metric = _variant_only_metric(local_text, concept_head, normalized_variants)
    if variant_metric:
        support_roles.append("variant_metric_anchor")
        review_flags.append("variant_only_support")
    if primary_need == "metric_formula" and "metric_formula_anchor" in support_roles and not metric_target_anchor:
        review_flags.append("metric_target_anchor_missing")
    if metric_component_only:
        review_flags.append("component_metric_only")
    if primary_need == "parameter_relationship" and "parameter_relationship_anchor" in support_roles:
        if shallow_parameter_mention and not strong_parameter_relation:
            review_flags.append("shallow_parameter_mention")

    if sibling_overlap:
        review_flags.append("sibling_overlap")
    if generic_context_only or broad_topic_only or review_only:
        review_flags.append("context_only")
    if not target_bound:
        review_flags.append("no_target_binding")
    if "definition_subject_mismatch" in guard_blockers or subject_alignment == "mismatch":
        review_flags.append("definition_subject_mismatch")
        # 2026-07-26 fix: propagate the single-token-match granularity from
        # definition_framing_score's own "reasons" list (see
        # evidence_stage_v3_scored_candidates.py's _definition_subject_alignment) into
        # review_risk_flags - this function builds review_risk_flags independently of that
        # module's own risk_flags output, so without this the granularity was silently lost
        # for every review_needed_evidence item, even though the underlying candidate row
        # already carried it.
        if "definition_subject_mismatch_single_token_match" in _string_list(definition.get("reasons")):
            review_flags.append("definition_subject_mismatch_single_token_match")
    if any(flag in {"fragmentary", "heading_like", "caption_like"} for flag in _string_list(row.get("risk_flags"))):
        review_flags.append("suspected_false_positive")

    support_roles = _unique_preserve(support_roles)
    review_flags = _unique_preserve(review_flags)

    role_for_primary = NEED_TO_ROLE.get(primary_need, "definition_anchor")
    primary_supported = role_for_primary in support_roles
    anchor_roles_present = any(role in NEED_TO_ROLE.values() for role in support_roles)
    clean_non_definition_rescue = bool(
        primary_need != "definition_concept"
        and primary_supported
        and target_bound
        and binding_strength in {"usable", "strong"}
        and "definition_subject_mismatch" in review_flags
        and not broad_topic_only
        and not review_only
    )
    clean_anchor_support = bool(
        anchor_roles_present
        and not variant_metric
        and not broad_topic_only
        and not review_only
        and not sibling_overlap
        and "suspected_false_positive" not in review_flags
        and (primary_need != "metric_formula" or metric_target_anchor)
        and (primary_need != "parameter_relationship" or not primary_supported or strong_parameter_relation)
        and (
            not guard.get("blocked_from_positive_support")
            or clean_non_definition_rescue
        )
        and target_bound
    )

    if same_region_auxiliary_only and not target_bound:
        bucket = "auxiliary"
    elif metric_component_only and not metric_target_anchor:
        bucket = "auxiliary"
    elif clean_anchor_support:
        bucket = "drafting_core"
    elif primary_supported or support_roles:
        if "context_completion" in support_roles and not primary_supported and not target_bound:
            bucket = "auxiliary"
        elif primary_need == "parameter_relationship" and shallow_parameter_mention and not strong_parameter_relation:
            bucket = "review_needed"
        elif variant_metric or sibling_overlap or broad_topic_only or review_only:
            bucket = "review_needed"
        elif primary_need == "metric_formula" and "metric_formula_anchor" in support_roles and not metric_target_anchor:
            bucket = "review_needed"
        elif "context_completion" in support_roles and not primary_supported:
            bucket = "auxiliary"
        elif not target_bound and "auxiliary_context" not in support_roles:
            bucket = "review_needed"
        elif "suspected_false_positive" in review_flags and not primary_supported:
            bucket = "rejected_false_positive"
        elif primary_supported:
            bucket = "review_needed"
        else:
            bucket = "review_needed"
    else:
        bucket = "rejected_false_positive"

    return {
        "shapeaware_support_roles": support_roles,
        "review_risk_flags": review_flags,
        "shapeaware_bucket": bucket,
        "expected_evidence_needs": expected,
        "concept_head": concept_head,
        "normalized_surface_variants": normalized_variants,
    }


def _pack_item(row: Mapping[str, Any], assessment: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "candidate_id": _clean_text(row.get("candidate_id")),
        "scored_candidate_id": _clean_text(row.get("scored_candidate_id") or row.get("candidate_id")),
        "routing_recommendation": _clean_text(row.get("routing_recommendation")),
        "text": _clean_text(row.get("candidate_text") or row.get("text")),
        "shapeaware_support_roles": list(assessment.get("shapeaware_support_roles") or []),
        "review_risk_flags": list(assessment.get("review_risk_flags") or []),
        "overall_score": _row_score(row),
        "source_refs": {
            "doc_id": _clean_text(row.get("doc_id")),
            "page_index": row.get("page_index"),
            "block_id": _clean_text(row.get("block_id")),
            "sentence_id": _clean_text(row.get("sentence_id")),
            "patch_id": _clean_text(row.get("patch_id")),
        },
    }


def compose_shapeaware_shadow_pack(
    kc_id: str,
    kc_rows: Sequence[Mapping[str, Any]],
    expected_evidence_needs: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    if not kc_rows:
        return {
            "kc_id": kc_id,
            "expected_evidence_needs": [],
            "shapeaware_route": "insufficient_source_support_packet",
            "evidence_need_satisfaction": {},
            "drafting_core_risk_flags": [],
            "auxiliary_risk_flags": [],
            "review_needed_risk_flags": [],
            "rejected_false_positive_risk_flags": [],
            "pack_level_risk_flags": [],
            "review_risk_flags": [],
            "drafting_core_evidence": [],
            "auxiliary_evidence": [],
            "review_needed_evidence": [],
            "rejected_false_positive_evidence": [],
        }

    guidance = _concept_head_from_needs(kc_rows[0], expected_evidence_needs)
    expected = guidance["expected_evidence_needs"]
    assessments = [
        (row, classify_shapeaware_candidate(row, expected))
        for row in kc_rows
    ]

    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    bucket_risk_flags: Dict[str, List[str]] = defaultdict(list)
    need_status: Dict[str, Dict[str, Any]] = {}
    role_to_needs = {role: need for need, role in NEED_TO_ROLE.items()}

    for row, assessment in assessments:
        item = _pack_item(row, assessment)
        bucket = str(assessment["shapeaware_bucket"])
        buckets[bucket].append(item)
        bucket_risk_flags[bucket].extend(_string_list(assessment.get("review_risk_flags")))
        matched_needs = {
            role_to_needs[role]
            for role in _string_list(assessment.get("shapeaware_support_roles"))
            if role in role_to_needs
        }
        for spec in expected:
            need = _clean_text(spec.get("need"))
            entry = need_status.setdefault(
                need,
                {
                    "priority": _clean_text(spec.get("priority")),
                    "status": "missing",
                    "drafting_core_count": 0,
                    "review_needed_count": 0,
                    "auxiliary_count": 0,
                    "rejected_false_positive_count": 0,
                },
            )
            if need not in matched_needs:
                continue
            if bucket == "drafting_core":
                entry["drafting_core_count"] += 1
            elif bucket == "review_needed":
                entry["review_needed_count"] += 1
            elif bucket == "auxiliary":
                entry["auxiliary_count"] += 1
            else:
                entry["rejected_false_positive_count"] += 1

    for entry in need_status.values():
        if entry["drafting_core_count"] > 0:
            entry["status"] = "satisfied"
        elif entry["review_needed_count"] > 0:
            entry["status"] = "review_needed"
        elif entry["auxiliary_count"] > 0:
            entry["status"] = "auxiliary_only"
        elif entry["rejected_false_positive_count"] > 0:
            entry["status"] = "rejected"
        else:
            entry["status"] = "missing"

    primary_need = next((item["need"] for item in expected if item.get("priority") == "primary"), "definition_concept")
    primary_status = need_status.get(primary_need, {}).get("status", "missing")
    any_drafting_core = bool(buckets.get("drafting_core"))
    drafting_core_risk_flags = _unique_preserve(bucket_risk_flags.get("drafting_core", []))
    auxiliary_risk_flags = _unique_preserve(bucket_risk_flags.get("auxiliary", []))
    review_needed_risk_flags = _unique_preserve(bucket_risk_flags.get("review_needed", []))
    rejected_false_positive_risk_flags = _unique_preserve(bucket_risk_flags.get("rejected_false_positive", []))
    non_drafting_risk_flags = _unique_preserve(
        [*auxiliary_risk_flags, *review_needed_risk_flags, *rejected_false_positive_risk_flags]
    )
    pack_level_risk_flags = _unique_preserve(
        [*drafting_core_risk_flags, *non_drafting_risk_flags]
    )
    non_primary_grounding = any(
        need != primary_need and str(entry.get("status") or "") in {"satisfied", "review_needed", "auxiliary_only"}
        for need, entry in need_status.items()
    )
    variant_only = "variant_only_support" in non_drafting_risk_flags and not any_drafting_core
    sibling_overlap = "sibling_overlap" in non_drafting_risk_flags and not any_drafting_core
    context_only = "context_only" in non_drafting_risk_flags and not any_drafting_core
    suspected_false_positive = "suspected_false_positive" in non_drafting_risk_flags and not any_drafting_core

    if primary_status == "satisfied":
        route = STANDARD_ROUTE_BY_NEED.get(primary_need, "partial_grounded_packet")
    elif any_drafting_core:
        route = "partial_grounded_packet"
    elif primary_status == "review_needed":
        if variant_only:
            route = "variant_only_review_packet"
        elif sibling_overlap:
            route = "sibling_overlap_review_packet"
        elif context_only:
            route = "context_only_review_packet"
        else:
            route = "partial_grounded_packet"
    elif buckets.get("review_needed"):
        if variant_only:
            route = "variant_only_review_packet"
        elif sibling_overlap:
            route = "sibling_overlap_review_packet"
        elif context_only:
            route = "context_only_review_packet"
        elif non_primary_grounding:
            route = "partial_grounded_packet"
        else:
            route = "suspected_false_positive_review_packet" if suspected_false_positive else "insufficient_source_support_packet"
    elif buckets.get("rejected_false_positive"):
        route = "suspected_false_positive_review_packet"
    else:
        route = "insufficient_source_support_packet"

    for key in ("drafting_core", "auxiliary", "review_needed", "rejected_false_positive"):
        buckets[key].sort(key=lambda item: (-float(item.get("overall_score") or 0.0), _clean_text(item.get("candidate_id"))))

    return {
        "kc_id": kc_id,
        "expected_evidence_needs": expected,
        "shapeaware_route": route,
        "evidence_need_satisfaction": need_status,
        "drafting_core_risk_flags": drafting_core_risk_flags,
        "auxiliary_risk_flags": auxiliary_risk_flags,
        "review_needed_risk_flags": review_needed_risk_flags,
        "rejected_false_positive_risk_flags": rejected_false_positive_risk_flags,
        "pack_level_risk_flags": pack_level_risk_flags,
        "review_risk_flags": pack_level_risk_flags,
        "drafting_core_evidence": buckets["drafting_core"],
        "auxiliary_evidence": buckets["auxiliary"],
        "review_needed_evidence": buckets["review_needed"],
        "rejected_false_positive_evidence": buckets["rejected_false_positive"],
    }
