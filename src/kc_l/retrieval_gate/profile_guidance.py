from __future__ import annotations

"""Step 5x consumer adapter for Step 5p retrieval profiles.

Step 5p profiles are retrieval-control metadata. They are not evidence.
Step 5p source windows are profiler inputs. They are not candidate evidence.
"""

from dataclasses import dataclass, field
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from kc_l.retrieval_gate.shapeaware_shadow import build_shapeaware_guidance


PROFILE_OUTPUT_ROLE = "retrieval_control_metadata_not_evidence"


@dataclass(frozen=True)
class Step5xQueryPlan:
    query: str
    retrieval_role: str
    retrieval_channels: tuple[str, ...]
    source: str
    variant_type: str = ""
    cue_type: str = ""
    step5x_eligible: bool = True
    requires_hierarchy_guard: bool = False
    risk_flags: tuple[str, ...] = field(default_factory=tuple)
    provenance: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    support_authority: str = "candidate_hint_step5x_must_verify"
    step5x_verification_required: bool = True
    route_trust: str = "guidance"
    profile_output_role: str = PROFILE_OUTPUT_ROLE


@dataclass(frozen=True)
class Step5xNegativeConstraint:
    term: str
    reason: str
    source: str
    related_snippet_ids: tuple[str, ...] = field(default_factory=tuple)
    profile_output_role: str = PROFILE_OUTPUT_ROLE


@dataclass(frozen=True)
class Step5xEvidenceShapeHint:
    shape: str
    shape_family: str
    source: str
    confidence: str
    provenance: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    support_authority: str = "candidate_hint_step5x_must_verify"
    step5x_verification_required: bool = True
    route_trust: str = "guidance"
    profile_output_role: str = PROFILE_OUTPUT_ROLE


@dataclass(frozen=True)
class Step5xRetrievalRoute:
    route_id: str
    route_type: str
    activation: str
    route_strength: str
    verification_status: str
    primary_terms_any: tuple[str, ...] = field(default_factory=tuple)
    support_terms_any: tuple[str, ...] = field(default_factory=tuple)
    support_terms_all: tuple[str, ...] = field(default_factory=tuple)
    negative_terms_any: tuple[str, ...] = field(default_factory=tuple)
    local_window_scope: str = "same_sentence_or_patch"
    support_requirement: str = "boost_only"
    can_create_candidates: bool = True
    can_create_positive_support: bool = True
    broad_context_only: bool = False
    source_provenance_ids: tuple[str, ...] = field(default_factory=tuple)
    provenance: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    support_authority: str = "candidate_hint_step5x_must_verify"
    step5x_verification_required: bool = True
    route_trust: str = "guidance"
    profile_output_role: str = PROFILE_OUTPUT_ROLE


@dataclass(frozen=True)
class Step5xProfileGuidance:
    kc_id: str
    profile_status: str
    profile_input_status: str
    lexical_queries: tuple[Step5xQueryPlan, ...]
    semantic_queries: tuple[Step5xQueryPlan, ...]
    profile_only_queries: tuple[Step5xQueryPlan, ...]
    retrieval_routes: tuple[Step5xRetrievalRoute, ...]
    negative_constraints: tuple[Step5xNegativeConstraint, ...]
    evidence_shape_hints: tuple[Step5xEvidenceShapeHint, ...]
    query_atoms: tuple[str, ...]
    concept_head: str
    qualifiers: tuple[str, ...]
    expanded_aliases: tuple[str, ...]
    normalized_surface_variants: tuple[str, ...]
    expected_evidence_needs: tuple[Mapping[str, Any], ...]
    route_specific_query_variants: tuple[Mapping[str, Any], ...]
    route_specific_required_terms: tuple[Mapping[str, Any], ...]
    route_specific_optional_terms: tuple[Mapping[str, Any], ...]
    negative_sibling_terms: tuple[str, ...]
    risk_hints: tuple[str, ...]
    concept_head_terms_any: tuple[str, ...]
    label_descriptor_terms_any: tuple[str, ...]
    region_locator_payloads: tuple[Mapping[str, Any], ...]
    retrieval_failure_hypothesis: str
    accepted_source_cue_count: int
    source_window_ids: tuple[str, ...]
    knowledge_unit_id: str = ""
    knowledge_unit_type: str = "kc"
    role_targets: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    branch_policy: Mapping[str, Any] = field(default_factory=dict)
    coverage_goals: Mapping[str, Any] = field(default_factory=dict)
    source_section_targets: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    unconfirmed_probe_terms: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    rescue_hints: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    safe_to_use_for_step5x: bool = False
    profile_output_role: str = PROFILE_OUTPUT_ROLE


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _clean_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _tuple_of_strings(value: Any) -> tuple[str, ...]:
    out: List[str] = []
    for item in _as_list(value):
        text = _clean_text(item)
        if text and text not in out:
            out.append(text)
    return tuple(out)


def _tuple_of_mappings(value: Any) -> tuple[Mapping[str, Any], ...]:
    out: List[Mapping[str, Any]] = []
    for item in _as_list(value):
        if isinstance(item, Mapping):
            out.append(dict(item))
    return tuple(out)


def _query_plan_from_variant(raw: Mapping[str, Any]) -> Optional[Step5xQueryPlan]:
    query = _clean_text(raw.get("query"))
    if not query:
        return None
    if not _clean_bool(raw.get("active", True), default=True):
        return None

    role = _clean_text(raw.get("retrieval_role")) or "lexical_query"
    channels = _tuple_of_strings(raw.get("retrieval_channels"))

    if not channels:
        if role == "semantic_query":
            channels = ("semantic",)
        elif role == "profile_only_query":
            channels = tuple()
        else:
            channels = ("lexical",)

    eligible = _clean_bool(raw.get("step5x_eligible", True), default=True)
    if role == "profile_only_query":
        eligible = False

    return Step5xQueryPlan(
        query=query,
        retrieval_role=role,
        retrieval_channels=channels,
        source=_clean_text(raw.get("source")) or "unknown",
        variant_type=_clean_text(raw.get("variant_type")),
        cue_type=_clean_text(raw.get("cue_type")),
        step5x_eligible=eligible,
        requires_hierarchy_guard=_clean_bool(raw.get("requires_hierarchy_guard", False)),
        risk_flags=_tuple_of_strings(raw.get("risk_flags")),
        provenance=_tuple_of_mappings(raw.get("provenance")),
        support_authority=_clean_text(raw.get("support_authority")) or "candidate_hint_step5x_must_verify",
        step5x_verification_required=_clean_bool(raw.get("step5x_verification_required"), default=True),
        route_trust=_clean_text(raw.get("route_trust")) or "guidance",
    )


def _negative_from_raw(raw: Mapping[str, Any], *, source: str, default_reason: str) -> Optional[Step5xNegativeConstraint]:
    term = _clean_text(raw.get("term") or raw.get("query") or raw.get("text"))
    if not term:
        return None
    return Step5xNegativeConstraint(
        term=term,
        reason=_clean_text(raw.get("reason")) or default_reason,
        source=source,
        related_snippet_ids=_tuple_of_strings(raw.get("related_snippet_ids")),
    )


def _shape_hint_from_raw(raw: Mapping[str, Any]) -> Optional[Step5xEvidenceShapeHint]:
    shape = _clean_text(raw.get("shape") or raw.get("evidence_shape") or raw.get("type"))
    if not shape:
        return None
    return Step5xEvidenceShapeHint(
        shape=shape,
        shape_family=_clean_text(raw.get("shape_family")) or shape,
        source=_clean_text(raw.get("source")) or "profile_shape",
        confidence=_clean_text(raw.get("confidence")) or "low",
        provenance=_tuple_of_mappings(raw.get("provenance")),
    )


def _route_from_raw(raw: Mapping[str, Any], *, default_id: str) -> Optional[Step5xRetrievalRoute]:
    primary_terms = _tuple_of_strings(raw.get("primary_terms_any") or raw.get("primary_terms") or raw.get("terms"))
    support_any = _tuple_of_strings(raw.get("support_terms_any"))
    support_all = _tuple_of_strings(raw.get("support_terms_all"))
    negative_any = _tuple_of_strings(raw.get("negative_terms_any"))

    if not primary_terms and not support_any and not support_all:
        return None

    activation = _clean_text(raw.get("activation")) or "active"
    if activation not in {"active", "context_only", "quarantine"}:
        activation = "quarantine"

    route_type = _clean_text(raw.get("route_type")) or "anchored_phrase"
    route_strength = _clean_text(raw.get("route_strength")) or "weak"
    verification_status = _clean_text(raw.get("verification_status")) or "model_suggested_unverified"
    support_requirement = _clean_text(raw.get("support_requirement")) or "boost_only"
    if support_requirement not in {
        "none",
        "boost_only",
        "required_for_this_route",
        "required_for_positive_support_on_this_route",
    }:
        support_requirement = "boost_only"

    # A context-locator route is allowed to identify a relevant source region,
    # but it is not leaf-KC evidence. Treat it as context-only even if a model
    # accidentally emits activation="active" or can_create_positive_support=true.
    route_is_context_locator = route_type == "context_locator"
    broad_context_only = (
        _clean_bool(raw.get("broad_context_only"), default=False)
        or activation == "context_only"
        or route_is_context_locator
    )
    if broad_context_only:
        activation = "context_only"
    can_create_positive_support = _clean_bool(raw.get("can_create_positive_support"), default=True)
    if broad_context_only or activation != "active":
        can_create_positive_support = False

    return Step5xRetrievalRoute(
        route_id=_clean_text(raw.get("route_id")) or default_id,
        route_type=route_type,
        activation=activation,
        route_strength=route_strength,
        verification_status=verification_status,
        primary_terms_any=primary_terms,
        support_terms_any=support_any,
        support_terms_all=support_all,
        negative_terms_any=negative_any,
        local_window_scope=_clean_text(raw.get("local_window_scope")) or "same_sentence_or_patch",
        support_requirement=support_requirement,
        can_create_candidates=_clean_bool(raw.get("can_create_candidates"), default=True) and activation != "quarantine",
        can_create_positive_support=can_create_positive_support,
        broad_context_only=broad_context_only,
        source_provenance_ids=_tuple_of_strings(raw.get("source_provenance_ids")),
        provenance=_tuple_of_mappings(raw.get("provenance")),
    )


_ROUTE_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")
_ROUTE_GENERIC_TOKENS = {
    "approach", "approaches", "basic", "concept", "concepts", "context",
    "data", "definition", "definitions", "example", "examples", "general",
    "information", "measure", "measures", "method", "methods", "model",
    "models", "phase", "phases", "problem", "problems", "process",
    "score", "scores", "system", "systems", "technique", "techniques",
    "type", "types", "value", "values",
}
_LABEL_DESCRIPTOR_TOKENS = {
    "algorithm", "approach", "approaches", "condition", "conditions",
    "concept", "concepts", "criterion", "criteria", "definition",
    "definitions", "equation", "equations", "example", "examples",
    "formula", "formulas", "framework", "frameworks", "method",
    "methods", "metric", "metrics", "model", "models", "overview",
    "phase", "phases", "problem", "problems", "procedure",
    "procedures", "process", "processes", "score", "scores",
    "scope", "step", "steps", "term", "terms", "type", "types",
}


def _route_tokens(text: Any) -> tuple[str, ...]:
    out: List[str] = []
    seen: set[str] = set()
    for raw in _ROUTE_TOKEN_RE.findall(str(text or "").lower()):
        if len(raw) < 3 or raw in _ROUTE_GENERIC_TOKENS:
            continue
        if raw in seen:
            continue
        seen.add(raw)
        out.append(raw)
    return tuple(out)


def _raw_terms(value: Any) -> tuple[str, ...]:
    out: List[str] = []
    for item in _as_list(value):
        if isinstance(item, Mapping):
            text = _clean_text(item.get("term") or item.get("query") or item.get("text") or item.get("phrase"))
        else:
            text = _clean_text(item)
        if text and text.lower() not in {x.lower() for x in out}:
            out.append(text)
    return tuple(out)


def _dedupe_preserve_case(values: Iterable[str]) -> List[str]:
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


def _split_label_terms(label: Any) -> tuple[tuple[str, ...], tuple[str, ...]]:
    head_terms: List[str] = []
    descriptors: List[str] = []
    for token in _ROUTE_TOKEN_RE.findall(str(label or "").lower()):
        if token in _ROUTE_GENERIC_TOKENS or token in _LABEL_DESCRIPTOR_TOKENS:
            descriptors.append(token)
        elif token not in head_terms:
            head_terms.append(token)
    if not head_terms:
        for token in _ROUTE_TOKEN_RE.findall(str(label or "").lower()):
            if len(token) >= 2 and token not in head_terms:
                head_terms.append(token)
                break
    return tuple(head_terms), tuple(dict.fromkeys(descriptors))


def _is_long_locator_term(text: str) -> bool:
    words = text.split()
    return bool(len(words) > 10 or len(text) > 120)


def _source_ids_from_provenance(provenance: Any) -> tuple[str, ...]:
    out: List[str] = []
    for item in _as_list(provenance):
        if not isinstance(item, Mapping):
            continue
        sid = _clean_text(item.get("snippet_id") or item.get("sentence_id") or item.get("source_id"))
        if sid and sid not in out:
            out.append(sid)
    return tuple(out)


def _derive_routes_from_accepted_cues(profile: Mapping[str, Any]) -> List[Step5xRetrievalRoute]:
    accepted = [item for item in _as_list(profile.get("accepted_source_cues")) if isinstance(item, Mapping)]
    if not accepted:
        return []
    canonical_tokens = set(_route_tokens(profile.get("canonical_name")))
    topic_tokens = set(_route_tokens(" ".join([
        _clean_text(profile.get("parent_topic_label")),
        *[_clean_text(x) for x in _as_list(profile.get("topic_path_labels"))],
    ])))
    routes: List[Step5xRetrievalRoute] = []
    for idx, cue in enumerate(accepted, start=1):
        term = _clean_text(cue.get("term"))
        if not term:
            continue
        cue_type = _clean_text(cue.get("cue_type")) or "context_phrase"
        term_tokens = set(_route_tokens(term))
        target_overlap = bool(term_tokens & canonical_tokens)
        topic_overlap = bool(term_tokens & topic_tokens)
        source_ids = _source_ids_from_provenance(cue.get("provenance"))

        support_terms: List[str] = []
        for other in accepted:
            if other is cue:
                continue
            other_term = _clean_text(other.get("term"))
            if not other_term or other_term.lower() == term.lower():
                continue
            if source_ids and source_ids and not (set(source_ids) & set(_source_ids_from_provenance(other.get("provenance")))):
                continue
            if len(_route_tokens(other_term)) < 2 and len(other_term) < 24:
                continue
            if other_term.lower() not in {x.lower() for x in support_terms}:
                support_terms.append(other_term)

        context_only = bool(cue_type == "context_phrase")
        missing_source_provenance = not bool(source_ids)
        if cue_type == "definition_phrase" and not target_overlap and topic_overlap and len(term_tokens) <= 4:
            context_only = True
        if cue_type in {"formula_relation", "metric_relation"}:
            route_type = "formula_or_metric"
        elif context_only:
            route_type = "context_locator"
        elif support_terms:
            route_type = "cooccurrence_constrained"
        else:
            route_type = "anchored_phrase"
        support_requirement = "none"
        if support_terms:
            support_requirement = "required_for_positive_support_on_this_route" if len(term_tokens) <= 2 or len(term) <= 24 else "boost_only"
        elif not context_only:
            support_requirement = "boost_only"

        routes.append(Step5xRetrievalRoute(
            route_id=f"derived_accepted_cue_route_{idx:03d}",
            route_type=route_type,
            activation="quarantine" if missing_source_provenance else ("context_only" if context_only else "active"),
            route_strength="weak" if context_only or missing_source_provenance else "strong",
            verification_status="source_observed_same_window" if source_ids else "model_suggested_unverified",
            primary_terms_any=(term,),
            support_terms_any=tuple(support_terms[:4]),
            support_terms_all=tuple(),
            negative_terms_any=tuple(),
            local_window_scope="same_sentence_or_patch",
            support_requirement=support_requirement,
            can_create_candidates=not context_only and not missing_source_provenance,
            can_create_positive_support=not context_only and not missing_source_provenance,
            broad_context_only=context_only or missing_source_provenance,
            source_provenance_ids=source_ids,
            provenance=_tuple_of_mappings(cue.get("provenance")),
            support_authority="candidate_hint_step5x_must_verify",
            step5x_verification_required=True,
            route_trust="derived_source_observed_guidance",
        ))
    return routes


def _route_to_control(route: Step5xRetrievalRoute) -> Dict[str, Any]:
    return {
        "route_id": route.route_id,
        "route_type": route.route_type,
        "activation": route.activation,
        "route_strength": route.route_strength,
        "verification_status": route.verification_status,
        "primary_terms_any": list(route.primary_terms_any),
        "support_terms_any": list(route.support_terms_any),
        "support_terms_all": list(route.support_terms_all),
        "negative_terms_any": list(route.negative_terms_any),
        "local_window_scope": route.local_window_scope,
        "support_requirement": route.support_requirement,
        "can_create_candidates": route.can_create_candidates,
        "can_create_positive_support": route.can_create_positive_support,
        "broad_context_only": route.broad_context_only,
        "source_provenance_ids": list(route.source_provenance_ids),
        "provenance": list(route.provenance),
        "support_authority": route.support_authority,
        "step5x_verification_required": route.step5x_verification_required,
        "route_trust": route.route_trust,
        "profile_output_role": route.profile_output_role,
    }


def _collect_source_window_ids(profile: Mapping[str, Any]) -> tuple[str, ...]:
    audit = profile.get("audit") if isinstance(profile.get("audit"), Mapping) else {}
    out: List[str] = []
    for key in ("strict_source_windows", "exploratory_profile_windows", "candidate_snippets"):
        for item in _as_list(audit.get(key)):
            if not isinstance(item, Mapping):
                continue
            sid = _clean_text(item.get("snippet_id") or item.get("surface_id") or item.get("window_id"))
            if sid and sid not in out:
                out.append(sid)
    return tuple(out)


def guidance_from_profile(profile: Mapping[str, Any]) -> Step5xProfileGuidance:
    kc_id = _clean_text(profile.get("kc_id"))
    if not kc_id:
        raise ValueError("profile row missing kc_id")

    profile_status = _clean_text(profile.get("profile_status")) or "unknown"
    audit = profile.get("audit") if isinstance(profile.get("audit"), Mapping) else {}
    profile_input_status = _clean_text(audit.get("profile_input_status")) or "unknown"

    lexical: List[Step5xQueryPlan] = []
    semantic: List[Step5xQueryPlan] = []
    profile_only: List[Step5xQueryPlan] = []
    warnings: List[str] = []
    seen_queries: set[tuple[str, str]] = set()

    for raw_q in _as_list(profile.get("query_variants")):
        if not isinstance(raw_q, Mapping):
            continue
        plan = _query_plan_from_variant(raw_q)
        if plan is None:
            continue

        key = (plan.query.lower(), plan.retrieval_role)
        if key in seen_queries:
            continue
        seen_queries.add(key)

        model_only_unverified = plan.source.startswith("model") and not plan.provenance
        if model_only_unverified:
            profile_only.append(plan)
            warnings.append(f"model_only_query_without_source_confirmation:{plan.query[:80]}")
            continue

        if not plan.step5x_eligible or plan.retrieval_role == "profile_only_query":
            profile_only.append(plan)
        elif plan.retrieval_role == "semantic_query" or "semantic" in plan.retrieval_channels:
            semantic.append(plan)
        elif plan.retrieval_role == "lexical_query" or "lexical" in plan.retrieval_channels:
            lexical.append(plan)
        else:
            profile_only.append(plan)
            warnings.append(f"unknown_query_role:{plan.retrieval_role}")

    routes: List[Step5xRetrievalRoute] = []
    seen_routes: set[tuple[str, str, tuple[str, ...]]] = set()
    for idx, raw_route in enumerate(_as_list(profile.get("retrieval_routes"))):
        if not isinstance(raw_route, Mapping):
            continue
        route = _route_from_raw(raw_route, default_id=f"route_{idx + 1:03d}")
        if route is None:
            continue
        key = (route.route_id, route.activation, tuple(t.lower() for t in route.primary_terms_any))
        if key in seen_routes:
            continue
        seen_routes.add(key)
        routes.append(route)

    if not routes:
        routes.extend(_derive_routes_from_accepted_cues(profile))

    negatives: List[Step5xNegativeConstraint] = []

    for raw in _as_list(profile.get("rejected_candidates")):
        if isinstance(raw, Mapping):
            item = _negative_from_raw(raw, source="rejected_candidate", default_reason="rejected_by_profile")
            if item:
                negatives.append(item)

    for raw in _as_list(profile.get("quarantined_terms") or profile.get("quarantined_model_suggestions")):
        if isinstance(raw, Mapping):
            item = _negative_from_raw(raw, source="quarantined_term", default_reason="quarantined_by_profile")
            if item:
                negatives.append(item)

    shape_hints: List[Step5xEvidenceShapeHint] = []
    for raw in _as_list(profile.get("expected_evidence_shape_hints") or profile.get("expected_evidence_shapes")):
        if isinstance(raw, Mapping):
            item = _shape_hint_from_raw(raw)
            if item:
                shape_hints.append(item)
        elif isinstance(raw, str):
            item = _shape_hint_from_raw({"shape": raw, "source": "profile_shape", "confidence": "low"})
            if item:
                shape_hints.append(item)

    accepted_cues = _as_list(profile.get("accepted_source_cues"))
    accepted_cue_count = sum(1 for item in accepted_cues if isinstance(item, Mapping))

    explicit_query_atoms = list(_raw_terms(profile.get("query_atoms")))
    explicit_heads = list(_raw_terms(profile.get("concept_head_terms_any")))
    explicit_descriptors = list(_raw_terms(profile.get("label_descriptor_terms_any")))
    derived_heads, derived_descriptors = _split_label_terms(profile.get("canonical_name"))
    derived_shapeaware = build_shapeaware_guidance(
        profile,
        query_variants=[item for item in _as_list(profile.get("query_variants")) if isinstance(item, Mapping)],
        retrieval_routes=[item for item in _as_list(profile.get("retrieval_routes")) if isinstance(item, Mapping)],
        expected_evidence_shape_hints=[
            item for item in _as_list(profile.get("expected_evidence_shape_hints")) if isinstance(item, Mapping)
        ],
        negative_terms=[
            _clean_text(item.get("term"))
            for item in _as_list(profile.get("rejected_candidates"))
            if isinstance(item, Mapping) and _clean_text(item.get("term"))
        ],
    )
    query_atoms: List[str] = list(explicit_query_atoms)
    concept_heads: List[str] = [*explicit_heads, *derived_heads]
    label_descriptors: List[str] = [*explicit_descriptors, *derived_descriptors]
    region_locator_payloads: List[Mapping[str, Any]] = [
        dict(item) for item in _as_list(profile.get("region_locator_payloads")) if isinstance(item, Mapping)
    ]

    for cue in accepted_cues:
        if not isinstance(cue, Mapping):
            continue
        term = _clean_text(cue.get("term"))
        provenance = _tuple_of_mappings(cue.get("provenance"))
        if term and not provenance:
            warnings.append(f"accepted_cue_without_provenance:{term[:80]}")
        if not term:
            continue
        cue_type = _clean_text(cue.get("cue_type")) or "context_phrase"
        if cue_type == "context_phrase" or _is_long_locator_term(term):
            if provenance:
                region_locator_payloads.append({
                    "locator": term,
                    "source": "accepted_source_cue",
                    "cue_type": cue_type,
                    "provenance": list(provenance),
                    "profile_output_role": PROFILE_OUTPUT_ROLE,
                })
        elif provenance:
            query_atoms.append(term)

    safe = bool(lexical or semantic) and profile_status not in {"reject", "unusable"}

    return Step5xProfileGuidance(
        kc_id=kc_id,
        profile_status=profile_status,
        profile_input_status=profile_input_status,
        lexical_queries=tuple(lexical),
        semantic_queries=tuple(semantic),
        profile_only_queries=tuple(profile_only),
        retrieval_routes=tuple(routes),
        negative_constraints=tuple(negatives),
        evidence_shape_hints=tuple(shape_hints),
        query_atoms=tuple(_dedupe_preserve_case(query_atoms)),
        concept_head=_clean_text(profile.get("concept_head")) or _clean_text(derived_shapeaware.get("concept_head")),
        qualifiers=_tuple_of_strings(profile.get("qualifiers")) or _tuple_of_strings(derived_shapeaware.get("qualifiers")),
        expanded_aliases=_tuple_of_strings(profile.get("expanded_aliases")) or _tuple_of_strings(derived_shapeaware.get("expanded_aliases")),
        normalized_surface_variants=_tuple_of_strings(profile.get("normalized_surface_variants")) or _tuple_of_strings(derived_shapeaware.get("normalized_surface_variants")),
        expected_evidence_needs=_tuple_of_mappings(profile.get("expected_evidence_needs")) or _tuple_of_mappings(derived_shapeaware.get("expected_evidence_needs")),
        route_specific_query_variants=_tuple_of_mappings(profile.get("route_specific_query_variants")) or _tuple_of_mappings(derived_shapeaware.get("route_specific_query_variants")),
        route_specific_required_terms=_tuple_of_mappings(profile.get("route_specific_required_terms")) or _tuple_of_mappings(derived_shapeaware.get("route_specific_required_terms")),
        route_specific_optional_terms=_tuple_of_mappings(profile.get("route_specific_optional_terms")) or _tuple_of_mappings(derived_shapeaware.get("route_specific_optional_terms")),
        negative_sibling_terms=_tuple_of_strings(profile.get("negative_sibling_terms")) or _tuple_of_strings(derived_shapeaware.get("negative_sibling_terms")),
        risk_hints=_tuple_of_strings(profile.get("risk_hints")) or _tuple_of_strings(derived_shapeaware.get("risk_hints")),
        concept_head_terms_any=tuple(_dedupe_preserve_case(concept_heads)),
        label_descriptor_terms_any=tuple(_dedupe_preserve_case(label_descriptors)),
        region_locator_payloads=tuple(region_locator_payloads),
        retrieval_failure_hypothesis=_clean_text(profile.get("retrieval_failure_hypothesis")),
        accepted_source_cue_count=accepted_cue_count,
        source_window_ids=_collect_source_window_ids(profile),
        knowledge_unit_id=_clean_text(profile.get("knowledge_unit_id") or profile.get("kc_id")),
        knowledge_unit_type=_clean_text(profile.get("knowledge_unit_type") or "kc"),
        role_targets=_tuple_of_mappings(profile.get("role_targets")),
        branch_policy=dict(profile.get("branch_policy") or {}) if isinstance(profile.get("branch_policy"), Mapping) else {},
        coverage_goals=dict(profile.get("coverage_goals") or {}) if isinstance(profile.get("coverage_goals"), Mapping) else {},
        source_section_targets=_tuple_of_mappings(profile.get("source_section_targets")),
        unconfirmed_probe_terms=_tuple_of_mappings(profile.get("unconfirmed_probe_terms")),
        rescue_hints=_tuple_of_mappings(profile.get("rescue_hints")),
        warnings=tuple(warnings),
        safe_to_use_for_step5x=safe,
    )


def guidance_to_candidate_bank_controls(guidance: Step5xProfileGuidance) -> Dict[str, Any]:
    return {
        "kc_id": guidance.kc_id,
        "knowledge_unit_id": guidance.knowledge_unit_id or guidance.kc_id,
        "knowledge_unit_type": guidance.knowledge_unit_type or "kc",
        "role_targets": [dict(item) for item in guidance.role_targets],
        "branch_policy": dict(guidance.branch_policy or {}),
        "coverage_goals": dict(guidance.coverage_goals or {}),
        "source_section_targets": [dict(item) for item in guidance.source_section_targets],
        "unconfirmed_probe_terms": [dict(item) for item in guidance.unconfirmed_probe_terms],
        "rescue_hints": [dict(item) for item in guidance.rescue_hints],
        "profile_status": guidance.profile_status,
        "profile_input_status": guidance.profile_input_status,
        "safe_to_use_for_step5x": guidance.safe_to_use_for_step5x,
        "lexical_queries": [
            {
                "query": q.query,
                "source": q.source,
                "variant_type": q.variant_type,
                "cue_type": q.cue_type,
                "requires_hierarchy_guard": q.requires_hierarchy_guard,
                "risk_flags": list(q.risk_flags),
                "provenance": list(q.provenance),
                "profile_output_role": q.profile_output_role,
            }
            for q in guidance.lexical_queries
        ],
        "semantic_queries": [
            {
                "query": q.query,
                "source": q.source,
                "variant_type": q.variant_type,
                "cue_type": q.cue_type,
                "requires_hierarchy_guard": q.requires_hierarchy_guard,
                "risk_flags": list(q.risk_flags),
                "provenance": list(q.provenance),
                "profile_output_role": q.profile_output_role,
            }
            for q in guidance.semantic_queries
        ],
        "retrieval_routes": [
            _route_to_control(route)
            for route in guidance.retrieval_routes
        ],
        "profile_only_queries": [
            {
                "query": q.query,
                "source": q.source,
                "reason": "not_eligible_for_direct_step5x_retrieval",
                "risk_flags": list(q.risk_flags),
                "profile_output_role": q.profile_output_role,
            }
            for q in guidance.profile_only_queries
        ],
        "negative_constraints": [
            {
                "term": n.term,
                "reason": n.reason,
                "source": n.source,
                "related_snippet_ids": list(n.related_snippet_ids),
                "profile_output_role": n.profile_output_role,
            }
            for n in guidance.negative_constraints
        ],
        "evidence_shape_hints": [
            {
                "shape": h.shape,
                "shape_family": h.shape_family,
                "source": h.source,
                "confidence": h.confidence,
                "provenance": list(h.provenance),
                "profile_output_role": h.profile_output_role,
            }
            for h in guidance.evidence_shape_hints
        ],
        "query_atoms": list(guidance.query_atoms),
        "concept_head": guidance.concept_head,
        "qualifiers": list(guidance.qualifiers),
        "expanded_aliases": list(guidance.expanded_aliases),
        "normalized_surface_variants": list(guidance.normalized_surface_variants),
        "expected_evidence_needs": [dict(item) for item in guidance.expected_evidence_needs],
        "route_specific_query_variants": [dict(item) for item in guidance.route_specific_query_variants],
        "route_specific_required_terms": [dict(item) for item in guidance.route_specific_required_terms],
        "route_specific_optional_terms": [dict(item) for item in guidance.route_specific_optional_terms],
        "negative_sibling_terms": list(guidance.negative_sibling_terms),
        "risk_hints": list(guidance.risk_hints),
        "concept_head_terms_any": list(guidance.concept_head_terms_any),
        "label_descriptor_terms_any": list(guidance.label_descriptor_terms_any),
        "region_locator_payloads": [dict(item) for item in guidance.region_locator_payloads],
        "retrieval_failure_hypothesis": guidance.retrieval_failure_hypothesis,
        "accepted_source_cue_count": guidance.accepted_source_cue_count,
        "source_window_ids": list(guidance.source_window_ids),
        "warnings": list(guidance.warnings),
        "control_role": "step5x_retrieval_control_metadata_not_evidence",
    }


def alias_safe_terms_for_candidate_generation(guidance: Step5xProfileGuidance) -> List[str]:
    if not guidance.safe_to_use_for_step5x:
        return []
    out: List[str] = []

    # When Step 5p emits retrieval routes, only active non-context routes become
    # alias-like candidate-generation terms. Context-only routes may locate a
    # region through source-window rehydration, but they must not be wired as
    # direct aliases because that turns broad parent-topic terms into leaf-KC
    # evidence.
    if guidance.retrieval_routes:
        for route in guidance.retrieval_routes:
            if not route.can_create_candidates or route.activation != "active" or route.broad_context_only:
                continue
            for term in route.primary_terms_any:
                text = _clean_text(term)
                if not text or _is_long_locator_term(text) or len(text) > 180:
                    continue
                if text.lower() not in {x.lower() for x in out}:
                    out.append(text)
        return out

    for atom in guidance.query_atoms:
        text = _clean_text(atom)
        if not text or _is_long_locator_term(text):
            continue
        if text.lower() not in {x.lower() for x in out}:
            out.append(text)

    for query in guidance.lexical_queries:
        if not query.step5x_eligible:
            continue
        if "generic_suffix_stripped_broad_risk" in query.risk_flags:
            continue
        text = _clean_text(query.query)
        if not text:
            continue
        if len(text) > 140:
            continue
        if text.lower() not in {x.lower() for x in out}:
            out.append(text)
    return out


def lexical_aliases_for_candidate_generation(guidance: Step5xProfileGuidance) -> List[str]:
    return alias_safe_terms_for_candidate_generation(guidance)


def region_locator_terms_for_candidate_generation(guidance: Step5xProfileGuidance) -> List[str]:
    out: List[str] = []
    for payload in guidance.region_locator_payloads:
        text = _clean_text(payload.get("locator") or payload.get("term") or payload.get("text") or payload.get("query"))
        if text and text.lower() not in {x.lower() for x in out}:
            out.append(text)
    for route in guidance.retrieval_routes:
        if route.activation != "context_only" and not route.broad_context_only and route.route_type != "context_locator":
            continue
        for term in route.primary_terms_any:
            text = _clean_text(term)
            if text and text.lower() not in {x.lower() for x in out}:
                out.append(text)
    for query in guidance.lexical_queries:
        text = _clean_text(query.query)
        if text and (_is_long_locator_term(text) or "long_query_semantic_only" in set(query.risk_flags)):
            if text.lower() not in {x.lower() for x in out}:
                out.append(text)
    return out


def guidance_summary_for_candidate_row(guidance: Step5xProfileGuidance) -> Dict[str, Any]:
    return {
        "profile_available": True,
        "profile_status": guidance.profile_status,
        "profile_input_status": guidance.profile_input_status,
        "safe_to_use_for_step5x": guidance.safe_to_use_for_step5x,
        "lexical_query_count": len(guidance.lexical_queries),
        "semantic_query_count": len(guidance.semantic_queries),
        "profile_only_query_count": len(guidance.profile_only_queries),
        "retrieval_route_count": len(guidance.retrieval_routes),
        "active_retrieval_route_count": sum(1 for route in guidance.retrieval_routes if route.activation == "active"),
        "context_only_route_count": sum(1 for route in guidance.retrieval_routes if route.activation == "context_only" or route.broad_context_only),
        "negative_constraint_count": len(guidance.negative_constraints),
        "evidence_shape_hint_count": len(guidance.evidence_shape_hints),
        "query_atom_count": len(guidance.query_atoms),
        "region_locator_count": len(guidance.region_locator_payloads),
        "accepted_source_cue_count": guidance.accepted_source_cue_count,
        "source_window_count": len(guidance.source_window_ids),
        "role_target_count": len(guidance.role_targets),
        "source_section_target_count": len(guidance.source_section_targets),
        "unconfirmed_probe_term_count": len(guidance.unconfirmed_probe_terms),
        "rescue_hint_count": len(guidance.rescue_hints),
        "knowledge_unit_type": guidance.knowledge_unit_type or "kc",
        "profile_output_role": PROFILE_OUTPUT_ROLE,
    }


def load_profile_guidance(profile_jsonl: str | Path, *, exact_kc_ids: Optional[Iterable[str]] = None) -> Dict[str, Step5xProfileGuidance]:
    path = Path(profile_jsonl)
    if not path.exists():
        raise FileNotFoundError(f"Step 5p profile JSONL not found: {path}")

    allowed = {str(x) for x in exact_kc_ids} if exact_kc_ids is not None else None
    out: Dict[str, Step5xProfileGuidance] = {}

    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            guidance = guidance_from_profile(json.loads(line))
            if allowed is not None and guidance.kc_id not in allowed:
                continue
            if guidance.kc_id in out:
                raise ValueError(f"duplicate profile guidance row for kc_id={guidance.kc_id} at line {line_no}")
            out[guidance.kc_id] = guidance

    return out


__all__ = [
    "PROFILE_OUTPUT_ROLE",
    "Step5xEvidenceShapeHint",
    "Step5xNegativeConstraint",
    "Step5xProfileGuidance",
    "Step5xQueryPlan",
    "Step5xRetrievalRoute",
    "alias_safe_terms_for_candidate_generation",
    "guidance_from_profile",
    "guidance_summary_for_candidate_row",
    "guidance_to_candidate_bank_controls",
    "lexical_aliases_for_candidate_generation",
    "load_profile_guidance",
    "region_locator_terms_for_candidate_generation",
]
