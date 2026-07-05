from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from kc_l.retrieval_gate.shapeaware_shadow import (
    build_shapeaware_guidance,
    classify_shapeaware_candidate,
    compose_shapeaware_shadow_pack,
)


def _row(
    canonical_name: str,
    text: str,
    *,
    parent_topic_label: str = "",
    aliases: list[str] | None = None,
    route: str = "manual_review_candidate",
    target_bound: bool = True,
    binding_strength: str = "strong",
    exact_target_phrase_in_text: bool | None = None,
    text_target_match_count: int | None = None,
    subject_alignment: str = "aligned",
    definition_style: str = "implicit",
    procedure_score: float = 0.0,
    example_score: float = 0.0,
    formula_score: float = 0.0,
    formula_notation: bool = False,
    context_completion_candidate: bool = False,
    same_region_auxiliary_only: bool = False,
    broad_topic_only: bool = False,
    generic_context_only: bool = False,
    sibling_signal: bool = False,
    review_only: bool = False,
    context_text: str = "",
    evidence_window_text: str = "",
    source_block_text: str = "",
    support_roles: list[str] | None = None,
    matched_surface_terms: list[str] | None = None,
    risk_flags: list[str] | None = None,
    sibling_labels: list[str] | None = None,
) -> dict[str, object]:
    role_eligibility = {
        "definition_kernel": False,
        "explanatory_gloss": False,
        "scope_condition": False,
        "formula_notation": False,
        "context_completion_candidate": bool(context_completion_candidate),
        "example_or_procedure": False,
        "sibling_contrast": bool(sibling_signal),
        "positive_support_eligible": False,
        "auxiliary_support_eligible": bool(context_completion_candidate),
        "guardrail_support_eligible": bool(sibling_signal),
        "review_only_candidate": bool(review_only),
        "independent_step5x_positive_basis": bool(target_bound),
    }
    if exact_target_phrase_in_text is None:
        exact_target_phrase_in_text = bool(target_bound)
    if text_target_match_count is None:
        text_target_match_count = 2 if target_bound else 0
    return {
        "candidate_id": f"{canonical_name}::{abs(hash(text))}",
        "scored_candidate_id": f"{canonical_name}::{abs(hash(text))}",
        "kc_id": f"KC::{canonical_name}",
        "knowledge_unit_id": f"KC::{canonical_name}",
        "knowledge_unit_type": "kc",
        "canonical_name": canonical_name,
        "aliases": list(aliases or []),
        "topic_path_labels": ["Root", parent_topic_label] if parent_topic_label else ["Root"],
        "parent_topic_label": parent_topic_label,
        "sibling_labels": list(sibling_labels or []),
        "text": text,
        "candidate_text": text,
        "context_text": context_text,
        "evidence_window_text": evidence_window_text,
        "source_block_text": source_block_text,
        "routing_recommendation": route,
        "candidate_quality": {
            "overall_score": 6.4,
            "target_bound_positive_support": bool(target_bound),
            "same_region_auxiliary_only": bool(same_region_auxiliary_only),
        },
        "positive_support_guard": {
            "blocked_from_positive_support": route != "positive_role_candidate" and not same_region_auxiliary_only,
            "blocker_flags": ["definition_subject_mismatch"] if subject_alignment == "mismatch" else [],
        },
        "lexical_target_binding": {
            "is_target_bound": bool(target_bound),
            "binding_strength": binding_strength,
            "exact_target_phrase_in_text": bool(exact_target_phrase_in_text),
            "text_target_match_count": int(text_target_match_count),
            "score": 4.5 if target_bound else 1.0,
            "offtarget_reasons": [] if target_bound else ["no_target_binding"],
        },
        "definition_framing_score": {
            "subject_alignment": subject_alignment,
            "definition_style": definition_style,
            "score": 5.0 if subject_alignment == "aligned" else 0.8,
        },
        "direct_target_statement": {"is_direct_target_statement": subject_alignment == "aligned"},
        "formula_signal": {
            "score": formula_score,
            "is_actual_formula_notation": bool(formula_notation),
            "looks_mathish_prose": False,
        },
        "procedure_or_example_signal": {
            "procedure_score": procedure_score,
            "example_score": example_score,
            "prompt_score": 0.0,
        },
        "fragment_or_caption_signal": {"fragment_score": 0.0, "caption_score": 0.0},
        "contamination_signals": {
            "score": 0.0,
            "broad_topic_only": bool(broad_topic_only),
            "doc_mismatch": False,
            "source_kc_mismatch": False,
        },
        "meta_guidance_signal": {"score": 0.0, "is_meta_guidance": False},
        "reference_like_signal": {
            "reference_like_penalty": 0.0,
            "bibliography_penalty": 0.0,
            "is_reference_like": False,
            "is_bibliography_like": False,
        },
        "sibling_or_competitor_signals": {
            "score": 3.2 if sibling_signal else 0.0,
            "genuine_sibling_signal": bool(sibling_signal),
            "contrastive_target_mention": False,
        },
        "support_profile": {
            "support_roles": list(support_roles or []),
            "preferred_support_role": "definitional_anchor" if "definitional_anchor" in (support_roles or []) else "other",
            "generic_context_only": bool(generic_context_only),
            "has_context_completion_source": bool(context_completion_candidate),
            "fragmentary_surface": False,
            "review_only_candidate": bool(review_only),
            "candidate_source": "profile_provenance_rehydration",
            "matched_surface_terms": list(matched_surface_terms or []),
            "matched_target_tokens": [],
        },
        "role_eligibility": role_eligibility,
        "role_scores": {
            "definition_kernel": 6.2,
            "explanatory_gloss": 5.0,
            "scope_condition": 2.5,
            "formula_notation": 6.0 if formula_notation else 2.0,
            "context_completion_candidate": 4.1 if context_completion_candidate else 0.0,
            "example_or_procedure": 6.2 if procedure_score else 0.0,
            "sibling_contrast": 3.4 if sibling_signal else 0.0,
        },
        "risk_flags": list(risk_flags or []),
        "step5x_retrieval_policy_plan": {},
    }


def test_shapeaware_guidance_emits_multi_label_priorities() -> None:
    guidance = build_shapeaware_guidance(
        {
            "canonical_name": "K-Means Algorithm",
            "parent_topic_label": "Clustering",
            "aliases": ["basic K-means algorithm"],
        },
        query_variants=[{"query": "K Means Algorithm"}],
        expected_evidence_shape_hints=[
            {"shape_family": "process"},
            {"shape_family": "definition"},
        ],
    )
    needs = guidance["expected_evidence_needs"]
    assert needs[0]["need"] == "algorithm_procedure"
    assert needs[0]["priority"] == "primary"
    assert any(item["need"] == "definition_concept" and item["priority"] == "secondary" for item in needs)
    assert any(item["need"] == "parameter_relationship" and item["priority"] == "tertiary" for item in needs)


def test_algorithm_procedure_support_can_be_clean_without_definition_wording() -> None:
    guidance = build_shapeaware_guidance({"canonical_name": "K-Means Algorithm"})
    row = _row(
        "K-Means Algorithm",
        "The algorithm alternates between assigning each item to the closest centroid and recomputing each centroid.",
        route="manual_review_candidate",
        subject_alignment="mismatch",
        definition_style="explicit",
        procedure_score=1.8,
        support_roles=["process_or_procedure"],
        risk_flags=["definition_subject_mismatch", "procedure_like"],
    )
    assessment = classify_shapeaware_candidate(row, guidance["expected_evidence_needs"])
    assert "algorithm_procedure_anchor" in assessment["shapeaware_support_roles"]
    assert assessment["shapeaware_bucket"] == "drafting_core"


def test_parameter_relationship_support_requires_parameters_and_relation() -> None:
    guidance = build_shapeaware_guidance({"canonical_name": "Neighborhood Parameters"})
    row = _row(
        "Neighborhood Parameters",
        "The parameters Eps and MinPts jointly determine whether a point qualifies for expansion.",
        route="manual_review_candidate",
        subject_alignment="mismatch",
        definition_style="none",
        support_roles=["process_or_procedure"],
    )
    assessment = classify_shapeaware_candidate(row, guidance["expected_evidence_needs"])
    assert "parameter_relationship_anchor" in assessment["shapeaware_support_roles"]
    assert assessment["shapeaware_bucket"] == "drafting_core"


def test_metric_formula_support_can_be_relational_not_definition_only() -> None:
    guidance = build_shapeaware_guidance({"canonical_name": "F-Measure"})
    row = _row(
        "F-Measure",
        "The F-measure is computed as the harmonic combination of precision and recall and increases when both improve.",
        route="manual_review_candidate",
        subject_alignment="mismatch",
        definition_style="none",
        support_roles=["formula_or_metric"],
        formula_score=1.2,
    )
    assessment = classify_shapeaware_candidate(row, guidance["expected_evidence_needs"])
    assert "metric_formula_anchor" in assessment["shapeaware_support_roles"]
    assert assessment["shapeaware_bucket"] == "drafting_core"


def test_formal_relation_support_accepts_hyphen_surface_normalization() -> None:
    guidance = build_shapeaware_guidance({"canonical_name": "Density-Reachable"})
    assert "Density Reachable" in guidance["normalized_surface_variants"]
    row = _row(
        "Density-Reachable",
        "Point q is density reachable from p when there exists a chain of directly density reachable points.",
        route="manual_review_candidate",
        subject_alignment="mismatch",
        definition_style="none",
    )
    assessment = classify_shapeaware_candidate(row, guidance["expected_evidence_needs"])
    assert "formal_relation_anchor" in assessment["shapeaware_support_roles"]
    assert assessment["shapeaware_bucket"] == "drafting_core"


def test_phase_process_support_uses_generic_parent_qualified_acronym_expansion() -> None:
    guidance = build_shapeaware_guidance(
        {
            "canonical_name": "NB Learning Phase",
            "parent_topic_label": "Naive Bayes",
        }
    )
    assert "Naive Bayes Learning Phase" in guidance["expanded_aliases"]
    row = _row(
        "NB Learning Phase",
        "During Naive Bayes learning, the model estimates class priors from the training set.",
        parent_topic_label="Naive Bayes",
        route="manual_review_candidate",
        subject_alignment="mismatch",
        definition_style="none",
        procedure_score=1.2,
    )
    assessment = classify_shapeaware_candidate(row, guidance["expected_evidence_needs"])
    assert "phase_process_anchor" in assessment["shapeaware_support_roles"]
    assert assessment["shapeaware_bucket"] == "drafting_core"


def test_variant_only_metric_support_is_review_needed_not_clean() -> None:
    guidance = build_shapeaware_guidance({"canonical_name": "Rand Index"})
    row = _row(
        "Rand Index",
        "The adjusted Rand index corrects for chance agreement between two partitions.",
        route="manual_review_candidate",
        subject_alignment="mismatch",
        definition_style="none",
        support_roles=["formula_or_metric"],
    )
    assessment = classify_shapeaware_candidate(row, guidance["expected_evidence_needs"])
    assert "variant_metric_anchor" in assessment["shapeaware_support_roles"]
    assert assessment["shapeaware_bucket"] == "review_needed"


def test_variant_only_metric_routes_to_variant_review_packet_without_base_target_support() -> None:
    guidance = build_shapeaware_guidance({"canonical_name": "Rand Index"})
    row = _row(
        "Rand Index",
        "The adjusted Rand index corrects for chance agreement between two partitions.",
        route="manual_review_candidate",
        subject_alignment="mismatch",
        definition_style="none",
        support_roles=["formula_or_metric"],
        exact_target_phrase_in_text=False,
        text_target_match_count=0,
    )
    shadow_pack = compose_shapeaware_shadow_pack("KC_RAND", [row], guidance["expected_evidence_needs"])
    assert shadow_pack["shapeaware_route"] == "variant_only_review_packet"
    assert shadow_pack["drafting_core_evidence"] == []
    assert len(shadow_pack["review_needed_evidence"]) == 1


def test_broad_generic_context_does_not_become_clean_support() -> None:
    guidance = build_shapeaware_guidance({"canonical_name": "External Index: F-Measure"})
    row = _row(
        "External Index: F-Measure",
        "An external index compares discovered labels against class labels.",
        route="review_only_candidate",
        target_bound=False,
        binding_strength="weak",
        broad_topic_only=True,
        generic_context_only=True,
        review_only=True,
        support_roles=["definitional_anchor"],
        risk_flags=["broad_topic_only"],
    )
    assessment = classify_shapeaware_candidate(row, guidance["expected_evidence_needs"])
    assert assessment["shapeaware_bucket"] != "drafting_core"
    assert "context_only" in assessment["review_risk_flags"]


def test_context_completion_cannot_become_drafting_core_without_anchor() -> None:
    guidance = build_shapeaware_guidance({"canonical_name": "K-Means Algorithm"})
    row = _row(
        "K-Means Algorithm",
        "Then recompute the centroid.",
        route="auxiliary_only_candidate",
        target_bound=False,
        binding_strength="weak",
        context_completion_candidate=True,
        same_region_auxiliary_only=True,
    )
    assessment = classify_shapeaware_candidate(row, guidance["expected_evidence_needs"])
    assert "context_completion" in assessment["shapeaware_support_roles"]
    assert assessment["shapeaware_bucket"] == "auxiliary"


def test_sibling_overlap_can_be_review_needed_for_formal_relation() -> None:
    guidance = build_shapeaware_guidance({"canonical_name": "Directly Density-Reachable"})
    row = _row(
        "Directly Density-Reachable",
        "Point q is directly density reachable from p when q lies within the neighborhood of a core point.",
        route="manual_review_candidate",
        subject_alignment="mismatch",
        definition_style="none",
        sibling_signal=True,
        sibling_labels=["Density-Reachable"],
    )
    assessment = classify_shapeaware_candidate(row, guidance["expected_evidence_needs"])
    assert "formal_relation_anchor" in assessment["shapeaware_support_roles"]
    assert assessment["shapeaware_bucket"] == "review_needed"
    assert "sibling_overlap" in assessment["review_risk_flags"]


def test_missing_secondary_or_tertiary_needs_do_not_fail_primary_route() -> None:
    guidance = build_shapeaware_guidance({"canonical_name": "K-Means Algorithm"})
    row = _row(
        "K-Means Algorithm",
        "The algorithm alternates between assigning points and recomputing the centroid.",
        route="manual_review_candidate",
        subject_alignment="mismatch",
        definition_style="none",
        procedure_score=1.8,
        support_roles=["process_or_procedure"],
    )
    shadow_pack = compose_shapeaware_shadow_pack("KC_A", [row], guidance["expected_evidence_needs"])
    assert shadow_pack["shapeaware_route"] == "standard_procedure_packet"
    assert shadow_pack["evidence_need_satisfaction"]["algorithm_procedure"]["status"] == "satisfied"
    assert shadow_pack["evidence_need_satisfaction"]["definition_concept"]["status"] == "missing"


def test_missing_primary_need_triggers_partial_or_review_route() -> None:
    guidance = build_shapeaware_guidance({"canonical_name": "F-Measure"})
    row = _row(
        "F-Measure",
        "The F-measure is a useful evaluation concept.",
        route="positive_role_candidate",
        subject_alignment="aligned",
        definition_style="explicit",
        support_roles=["definitional_anchor"],
    )
    shadow_pack = compose_shapeaware_shadow_pack("KC_B", [row], guidance["expected_evidence_needs"])
    assert shadow_pack["shapeaware_route"] == "partial_grounded_packet"
    assert shadow_pack["evidence_need_satisfaction"]["metric_formula"]["status"] == "missing"
    assert shadow_pack["evidence_need_satisfaction"]["definition_concept"]["status"] == "satisfied"


def test_metric_formula_without_local_target_anchor_cannot_become_clean_standard() -> None:
    guidance = build_shapeaware_guidance({"canonical_name": "Rand Index"})
    row = _row(
        "Rand Index",
        "The random initialization process involves the analysis of the nearest neighbour distance distribution on a subset of samples.",
        route="manual_review_candidate",
        subject_alignment="aligned",
        definition_style="none",
        support_roles=["formula_or_metric"],
        formula_score=1.4,
        exact_target_phrase_in_text=False,
        text_target_match_count=0,
    )
    assessment = classify_shapeaware_candidate(row, guidance["expected_evidence_needs"])
    shadow_pack = compose_shapeaware_shadow_pack("KC_RAND_GENERIC", [row], guidance["expected_evidence_needs"])
    assert "metric_formula_anchor" in assessment["shapeaware_support_roles"]
    assert "metric_target_anchor_missing" in assessment["review_risk_flags"]
    assert assessment["shapeaware_bucket"] != "drafting_core"
    assert shadow_pack["shapeaware_route"] != "standard_metric_formula_packet"


def test_shallow_parameter_mentions_do_not_become_clean_parameter_packets() -> None:
    guidance = build_shapeaware_guidance({"canonical_name": "DBSCAN Parameters"})
    row = _row(
        "DBSCAN Parameters",
        "There is, of course, the issue of how to determine the parameters Eps and MinPts.",
        route="manual_review_candidate",
        subject_alignment="mismatch",
        definition_style="none",
        support_roles=["process_or_procedure"],
        exact_target_phrase_in_text=False,
        text_target_match_count=0,
    )
    assessment = classify_shapeaware_candidate(row, guidance["expected_evidence_needs"])
    shadow_pack = compose_shapeaware_shadow_pack("KC_DBS_PARAMS", [row], guidance["expected_evidence_needs"])
    assert "parameter_relationship_anchor" in assessment["shapeaware_support_roles"]
    assert "shallow_parameter_mention" in assessment["review_risk_flags"]
    assert assessment["shapeaware_bucket"] == "review_needed"
    assert shadow_pack["shapeaware_route"] != "standard_parameter_packet"


def test_component_metric_evidence_is_auxiliary_without_target_metric_head() -> None:
    guidance = build_shapeaware_guidance({"canonical_name": "F-Measure"})
    row = _row(
        "F-Measure",
        "Precision is also referred as the positive predicted value.",
        route="positive_role_candidate",
        subject_alignment="aligned",
        definition_style="explicit",
        support_roles=["definitional_anchor"],
        exact_target_phrase_in_text=True,
        text_target_match_count=1,
        matched_surface_terms=["precision"],
        source_block_text=(
            "Precision is also referred as the positive predicted value. "
            "A classifier that has a high precision is likely to have most of its positive predictions correct."
        ),
    )
    assessment = classify_shapeaware_candidate(row, guidance["expected_evidence_needs"])
    assert assessment["shapeaware_bucket"] == "auxiliary"
    assert "component_metric_only" in assessment["review_risk_flags"]


def test_pack_risk_flags_are_bucket_scoped() -> None:
    guidance = build_shapeaware_guidance({"canonical_name": "K-Means Algorithm"})
    core_row = _row(
        "K-Means Algorithm",
        "The K-Means algorithm alternates between assigning each point to the closest centroid and recomputing the centroid.",
        route="positive_role_candidate",
        subject_alignment="aligned",
        definition_style="none",
        procedure_score=1.8,
        support_roles=["process_or_procedure"],
    )
    noisy_row = _row(
        "K-Means Algorithm",
        "A fragmentary formula-like snippet.",
        route="manual_review_candidate",
        target_bound=False,
        binding_strength="weak",
        support_roles=["formula_or_metric"],
        risk_flags=["fragmentary"],
        exact_target_phrase_in_text=False,
        text_target_match_count=0,
    )
    shadow_pack = compose_shapeaware_shadow_pack("KC_BUCKETS", [core_row, noisy_row], guidance["expected_evidence_needs"])
    assert shadow_pack["drafting_core_risk_flags"] == []
    assert "suspected_false_positive" in shadow_pack["review_needed_risk_flags"] or "suspected_false_positive" in shadow_pack["rejected_false_positive_risk_flags"]
    assert "suspected_false_positive" in shadow_pack["pack_level_risk_flags"]
    assert shadow_pack["review_risk_flags"] == shadow_pack["pack_level_risk_flags"]



def test_context_only_hint_never_becomes_primary_need() -> None:
    guidance = build_shapeaware_guidance(
        {"canonical_name": "Generic Concept"},
        expected_evidence_shape_hints=[{"shape_family": "context"}],
    )
    needs = guidance["expected_evidence_needs"]
    assert needs[0]["need"] == "definition_concept"
    assert all(item["need"] != "context_only" for item in needs)


def test_context_only_with_definition_prefers_definition_primary() -> None:
    guidance = build_shapeaware_guidance(
        {"canonical_name": "Generic Concept"},
        expected_evidence_shape_hints=[
            {"shape_family": "context"},
            {"shape_family": "definition"},
        ],
    )
    needs = guidance["expected_evidence_needs"]
    assert needs[0]["need"] == "definition_concept"
    assert all(item["need"] != "context_only" for item in needs)


def test_context_only_expected_input_is_sanitized_before_pack_routing() -> None:
    row = _row(
        "Generic Concept",
        "A generic concept is a target-bound definition used for classification.",
        route="positive_role_candidate",
        subject_alignment="aligned",
        definition_style="explicit",
        support_roles=["definitional_anchor"],
    )
    shadow_pack = compose_shapeaware_shadow_pack(
        "KC_GENERIC",
        [row],
        expected_evidence_needs=[
            {"need": "context_only", "priority": "primary", "source": "old_hint"},
            {"need": "definition_concept", "priority": "secondary", "source": "old_hint"},
        ],
    )
    assert shadow_pack["expected_evidence_needs"][0]["need"] == "definition_concept"
    assert shadow_pack["shapeaware_route"] == "standard_definition_packet"



def test_adjusted_metric_variant_is_review_needed_not_clean_core() -> None:
    row = _row(
        "Rand Index",
        "Some measures can be modeled with a statistical distribution, e.g., the adjusted Rand index, which is based on the multivariate hypergeometric distribution.",
        support_roles=["definitional_anchor"],
        route="manual_review_candidate",
        subject_alignment="mismatch",
        definition_style="none",
        risk_flags=["definition_subject_mismatch"],
    )
    shadow_pack = compose_shapeaware_shadow_pack(
        "KC_RAND",
        [row],
        expected_evidence_needs=[
            {"need": "metric_formula", "priority": "primary", "source": "test"},
            {"need": "definition_concept", "priority": "secondary", "source": "test"},
            {"need": "variant_or_index", "priority": "tertiary", "source": "test"},
        ],
    )
    assert shadow_pack["shapeaware_route"] == "variant_only_review_packet"
    assert shadow_pack["drafting_core_evidence"] == []
    assert shadow_pack["review_needed_evidence"]
    roles = {
        role
        for item in shadow_pack["review_needed_evidence"]
        for role in item.get("shapeaware_support_roles", [])
    }
    assert "variant_metric_anchor" in roles
    assert "variant_only_support" in shadow_pack["review_needed_risk_flags"]


def main() -> None:
    test_shapeaware_guidance_emits_multi_label_priorities()
    test_adjusted_metric_variant_is_review_needed_not_clean_core()
    test_context_only_expected_input_is_sanitized_before_pack_routing()
    test_context_only_with_definition_prefers_definition_primary()
    test_context_only_hint_never_becomes_primary_need()
    test_algorithm_procedure_support_can_be_clean_without_definition_wording()
    test_parameter_relationship_support_requires_parameters_and_relation()
    test_metric_formula_support_can_be_relational_not_definition_only()
    test_formal_relation_support_accepts_hyphen_surface_normalization()
    test_phase_process_support_uses_generic_parent_qualified_acronym_expansion()
    test_variant_only_metric_support_is_review_needed_not_clean()
    test_variant_only_metric_routes_to_variant_review_packet_without_base_target_support()
    test_broad_generic_context_does_not_become_clean_support()
    test_context_completion_cannot_become_drafting_core_without_anchor()
    test_sibling_overlap_can_be_review_needed_for_formal_relation()
    test_missing_secondary_or_tertiary_needs_do_not_fail_primary_route()
    test_missing_primary_need_triggers_partial_or_review_route()
    test_metric_formula_without_local_target_anchor_cannot_become_clean_standard()
    test_shallow_parameter_mentions_do_not_become_clean_parameter_packets()
    test_component_metric_evidence_is_auxiliary_without_target_metric_head()
    test_pack_risk_flags_are_bucket_scoped()
    print("TEST_STEP5X_SHAPEAWARE_SHADOW_OK")


if __name__ == "__main__":
    main()
