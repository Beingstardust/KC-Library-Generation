from __future__ import annotations

"""Deterministic Step 5x retrieval-policy planning.

This module separates retrieval control from evidence authority.  It may use
profile guidance, hierarchy labels, and typed unit metadata to build a query
plan, but it never treats those inputs as source evidence.  Candidate rows must
still be dereferenced against Step 4.5/source-overlay rows by Step 5x.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


RETRIEVAL_POLICY_VERSION = "step5x_v3_retrieval_policy_v1"
AUTHORITY_CONTRACT = "step5x_must_verify_against_source_rows"

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")

DESCRIPTOR_TOKENS = {
    "algorithm",
    "approach",
    "approaches",
    "condition",
    "conditions",
    "concept",
    "concepts",
    "criteria",
    "criterion",
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
    "gloss",
    "method",
    "methods",
    "metric",
    "metrics",
    "model",
    "models",
    "overview",
    "phase",
    "phases",
    "problem",
    "problems",
    "procedure",
    "procedures",
    "process",
    "processes",
    "score",
    "scores",
    "scope",
    "step",
    "steps",
    "summary",
    "term",
    "terms",
    "type",
    "types",
}

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

SHAPE_BY_DESCRIPTOR = {
    "algorithm": "procedure",
    "approach": "scope_or_method",
    "condition": "scope_condition",
    "criterion": "scope_condition",
    "definition": "definition",
    "equation": "formula_or_metric",
    "example": "example_or_procedure",
    "formula": "formula_or_metric",
    "gloss": "explanatory_gloss",
    "method": "procedure",
    "metric": "metric_gloss",
    "model": "mechanism",
    "phase": "process",
    "problem": "scope_condition",
    "procedure": "procedure",
    "process": "process",
    "score": "metric_gloss",
    "scope": "scope_condition",
    "step": "procedure",
    "term": "definition",
    "type": "scope_condition",
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
    for item in _as_list(value):
        text = _clean_text(item)
        if text and text.lower() not in {x.lower() for x in out}:
            out.append(text)
    return out


def _tokens(value: Any) -> List[str]:
    return [tok.lower() for tok in _TOKEN_RE.findall(str(value or ""))]


def _unique(values: Iterable[str]) -> List[str]:
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


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _guidance_items(guidance: Any, key: str) -> List[Any]:
    return _as_list(_get(guidance, key, []))


def _term_from_payload(payload: Any) -> str:
    if isinstance(payload, Mapping):
        return _clean_text(payload.get("term") or payload.get("query") or payload.get("text") or payload.get("phrase"))
    return _clean_text(payload)


def _is_long_locator(text: str) -> bool:
    words = text.split()
    return bool(len(words) > 10 or len(text) > 120)


def _unit_type(unit_context: Mapping[str, Any]) -> str:
    raw = _clean_text(
        unit_context.get("knowledge_unit_type")
        or unit_context.get("node_type")
        or unit_context.get("unit_type")
        or unit_context.get("type")
    ).lower()
    if raw in {"topic", "kc"}:
        return raw
    node_id = _clean_text(unit_context.get("node_id") or unit_context.get("knowledge_unit_id"))
    if node_id.startswith("topic::"):
        return "topic"
    if _clean_text(unit_context.get("kc_id")):
        return "kc"
    return "kc"


def split_label_terms(label: str) -> tuple[List[str], List[str]]:
    descriptor_terms: List[str] = []
    head_terms: List[str] = []
    for token in _tokens(label):
        if token in GLUE_TOKENS:
            continue
        if token in DESCRIPTOR_TOKENS:
            descriptor_terms.append(token)
        else:
            head_terms.append(token)
    if not head_terms:
        # Preserve the only available semantic handle rather than leaving a
        # policy with descriptor-only residuals.
        for token in _tokens(label):
            if token not in GLUE_TOKENS:
                head_terms.append(token)
                break
    return _unique(head_terms), _unique(descriptor_terms)


def _shape_priors_from_descriptors(descriptors: Sequence[str], unit_type: str) -> List[str]:
    if unit_type == "topic":
        return ["topic_scope", "representative_coverage"]
    priors: List[str] = []
    for descriptor in descriptors:
        shape = SHAPE_BY_DESCRIPTOR.get(str(descriptor).lower())
        if shape:
            priors.append(shape)
    if not priors:
        priors.append("target_bound_concept_support")
    return _unique(priors)


def _query_plan_id(payload: Mapping[str, Any]) -> str:
    digest = hashlib.sha1(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    unit_id = _clean_text(payload.get("knowledge_unit_id") or payload.get("kc_id") or "unit")
    return f"qplan_{unit_id}_{digest}"


@dataclass(frozen=True)
class RetrievalPolicyPlan:
    query_plan_id: str
    knowledge_unit_id: str
    knowledge_unit_type: str
    canonical_name: str
    lexical_atoms: tuple[str, ...] = field(default_factory=tuple)
    concept_head: str = ""
    qualifiers: tuple[str, ...] = field(default_factory=tuple)
    expanded_aliases: tuple[str, ...] = field(default_factory=tuple)
    normalized_surface_variants: tuple[str, ...] = field(default_factory=tuple)
    concept_head_terms: tuple[str, ...] = field(default_factory=tuple)
    label_descriptor_terms: tuple[str, ...] = field(default_factory=tuple)
    region_locators: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    shape_priors: tuple[str, ...] = field(default_factory=tuple)
    expected_evidence_needs: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    route_specific_query_variants: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    route_specific_required_terms: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    route_specific_optional_terms: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    negative_terms: tuple[str, ...] = field(default_factory=tuple)
    negative_sibling_terms: tuple[str, ...] = field(default_factory=tuple)
    sibling_terms: tuple[str, ...] = field(default_factory=tuple)
    risk_hints: tuple[str, ...] = field(default_factory=tuple)
    failure_hypothesis: str = ""
    authority_contract: str = AUTHORITY_CONTRACT
    policy_version: str = RETRIEVAL_POLICY_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "query_plan_id": self.query_plan_id,
            "knowledge_unit_id": self.knowledge_unit_id,
            "knowledge_unit_type": self.knowledge_unit_type,
            "canonical_name": self.canonical_name,
            "lexical_atoms": list(self.lexical_atoms),
            "concept_head": self.concept_head,
            "qualifiers": list(self.qualifiers),
            "expanded_aliases": list(self.expanded_aliases),
            "normalized_surface_variants": list(self.normalized_surface_variants),
            "concept_head_terms": list(self.concept_head_terms),
            "label_descriptor_terms": list(self.label_descriptor_terms),
            "region_locators": [dict(item) for item in self.region_locators],
            "shape_priors": list(self.shape_priors),
            "expected_evidence_needs": [dict(item) for item in self.expected_evidence_needs],
            "route_specific_query_variants": [dict(item) for item in self.route_specific_query_variants],
            "route_specific_required_terms": [dict(item) for item in self.route_specific_required_terms],
            "route_specific_optional_terms": [dict(item) for item in self.route_specific_optional_terms],
            "negative_terms": list(self.negative_terms),
            "negative_sibling_terms": list(self.negative_sibling_terms),
            "sibling_terms": list(self.sibling_terms),
            "risk_hints": list(self.risk_hints),
            "failure_hypothesis": self.failure_hypothesis,
            "authority_contract": self.authority_contract,
            "profile_output_role": "retrieval_control_metadata_not_evidence",
        }


def build_retrieval_policy_plan(
    unit_context: Mapping[str, Any],
    guidance: Optional[Any] = None,
) -> RetrievalPolicyPlan:
    canonical_name = _clean_text(unit_context.get("canonical_name") or unit_context.get("label") or unit_context.get("name"))
    knowledge_unit_type = _unit_type(unit_context)
    knowledge_unit_id = _clean_text(
        unit_context.get("knowledge_unit_id")
        or unit_context.get("node_id")
        or unit_context.get("kc_id")
    )
    if not knowledge_unit_id:
        knowledge_unit_id = _clean_text(unit_context.get("kc_id")) or "unknown_unit"

    concept_heads, descriptors = split_label_terms(canonical_name)
    lexical_atoms: List[str] = [canonical_name]
    lexical_atoms.extend(_string_list(unit_context.get("aliases")))

    region_locators: List[Dict[str, Any]] = []
    negative_terms: List[str] = []
    concept_head = ""
    qualifiers: List[str] = []
    expanded_aliases: List[str] = []
    normalized_surface_variants: List[str] = []
    expected_evidence_needs: List[Dict[str, Any]] = []
    route_specific_query_variants: List[Dict[str, Any]] = []
    route_specific_required_terms: List[Dict[str, Any]] = []
    route_specific_optional_terms: List[Dict[str, Any]] = []
    negative_sibling_terms: List[str] = []
    risk_hints: List[str] = []

    if guidance is not None:
        concept_head = _clean_text(_get(guidance, "concept_head", ""))
        qualifiers = _string_list(_get(guidance, "qualifiers", []))
        expanded_aliases = _string_list(_get(guidance, "expanded_aliases", []))
        normalized_surface_variants = _string_list(_get(guidance, "normalized_surface_variants", []))
        expected_evidence_needs = [
            dict(item) for item in _guidance_items(guidance, "expected_evidence_needs") if isinstance(item, Mapping)
        ]
        route_specific_query_variants = [
            dict(item) for item in _guidance_items(guidance, "route_specific_query_variants") if isinstance(item, Mapping)
        ]
        route_specific_required_terms = [
            dict(item) for item in _guidance_items(guidance, "route_specific_required_terms") if isinstance(item, Mapping)
        ]
        route_specific_optional_terms = [
            dict(item) for item in _guidance_items(guidance, "route_specific_optional_terms") if isinstance(item, Mapping)
        ]
        negative_sibling_terms = _string_list(_get(guidance, "negative_sibling_terms", []))
        risk_hints = _string_list(_get(guidance, "risk_hints", []))
        lexical_atoms.extend(expanded_aliases)
        for atom in _guidance_items(guidance, "query_atoms"):
            text = _term_from_payload(atom)
            if text and not _is_long_locator(text):
                lexical_atoms.append(text)
            elif text:
                region_locators.append({"locator": text, "source": "query_atom_long_locator"})
        concept_heads.extend(_string_list(_get(guidance, "concept_head_terms_any", [])))
        descriptors.extend(_string_list(_get(guidance, "label_descriptor_terms_any", [])))

        for query in _guidance_items(guidance, "lexical_queries"):
            text = _clean_text(_get(query, "query", ""))
            risk_flags = set(_string_list(_get(query, "risk_flags", [])))
            source = _clean_text(_get(query, "source", ""))
            provenance = _as_list(_get(query, "provenance", []))
            if not text:
                continue
            if _is_long_locator(text) or "long_query_semantic_only" in risk_flags:
                region_locators.append({"locator": text, "source": source or "lexical_query_long_locator"})
                continue
            if source.startswith("model") and not provenance:
                continue
            lexical_atoms.append(text)

        for route in _guidance_items(guidance, "retrieval_routes"):
            primary_terms = _string_list(_get(route, "primary_terms_any", []))
            route_type = _clean_text(_get(route, "route_type", ""))
            activation = _clean_text(_get(route, "activation", ""))
            context_only = bool(_get(route, "broad_context_only", False) or activation == "context_only" or route_type == "context_locator")
            for term in primary_terms:
                if context_only or _is_long_locator(term):
                    region_locators.append({
                        "locator": term,
                        "source": "profile_region_locator",
                        "route_type": route_type,
                        "activation": activation or "context_only",
                    })
                else:
                    lexical_atoms.append(term)
            negative_terms.extend(_string_list(_get(route, "negative_terms_any", [])))

        for payload in _guidance_items(guidance, "region_locator_payloads"):
            text = _term_from_payload(payload)
            if text:
                item = dict(payload) if isinstance(payload, Mapping) else {"locator": text}
                item.setdefault("locator", text)
                item.setdefault("source", "profile_region_locator_payload")
                region_locators.append(item)

        for neg in _guidance_items(guidance, "negative_constraints"):
            text = _clean_text(_get(neg, "term", ""))
            if text:
                negative_terms.append(text)

    sibling_terms = _string_list(unit_context.get("sibling_labels") or unit_context.get("sibling_terms"))
    shape_priors = _shape_priors_from_descriptors(descriptors, knowledge_unit_type)
    if guidance is not None:
        for hint in _guidance_items(guidance, "evidence_shape_hints"):
            shape = _clean_text(_get(hint, "shape_family", "") or _get(hint, "shape", ""))
            if shape:
                shape_priors.append(shape)

    payload = {
        "knowledge_unit_id": knowledge_unit_id,
        "knowledge_unit_type": knowledge_unit_type,
        "canonical_name": canonical_name,
        "lexical_atoms": _unique(lexical_atoms),
        "concept_head_terms": _unique(concept_heads),
        "label_descriptor_terms": _unique(descriptors),
        "shape_priors": _unique(shape_priors),
        "negative_terms": _unique(negative_terms),
        "sibling_terms": _unique(sibling_terms),
    }

    failure_hypothesis = ""
    if guidance is not None:
        failure_hypothesis = _clean_text(_get(guidance, "retrieval_failure_hypothesis", ""))

    return RetrievalPolicyPlan(
        query_plan_id=_query_plan_id(payload),
        knowledge_unit_id=knowledge_unit_id,
        knowledge_unit_type=knowledge_unit_type,
        canonical_name=canonical_name,
        lexical_atoms=tuple(payload["lexical_atoms"]),
        concept_head=concept_head or canonical_name,
        qualifiers=tuple(qualifiers),
        expanded_aliases=tuple(expanded_aliases),
        normalized_surface_variants=tuple(normalized_surface_variants or payload["lexical_atoms"]),
        concept_head_terms=tuple(payload["concept_head_terms"]),
        label_descriptor_terms=tuple(payload["label_descriptor_terms"]),
        region_locators=tuple(region_locators),
        shape_priors=tuple(payload["shape_priors"]),
        expected_evidence_needs=tuple(expected_evidence_needs),
        route_specific_query_variants=tuple(route_specific_query_variants),
        route_specific_required_terms=tuple(route_specific_required_terms),
        route_specific_optional_terms=tuple(route_specific_optional_terms),
        negative_terms=tuple(payload["negative_terms"]),
        negative_sibling_terms=tuple(negative_sibling_terms),
        sibling_terms=tuple(payload["sibling_terms"]),
        risk_hints=tuple(risk_hints),
        failure_hypothesis=failure_hypothesis,
    )


__all__ = [
    "AUTHORITY_CONTRACT",
    "RETRIEVAL_POLICY_VERSION",
    "RetrievalPolicyPlan",
    "build_retrieval_policy_plan",
    "split_label_terms",
]
