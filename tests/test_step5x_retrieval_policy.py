from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from kc_l.retrieval_gate.evidence_stage_v3_pack_composition import compose_evidence_packs_from_scored_candidates
from kc_l.retrieval_gate.evidence_stage_v3_retrieval_policy import build_retrieval_policy_plan


def _topic_unit() -> dict[str, object]:
    return {
        "knowledge_unit_id": "T_VECTOR_REASONING",
        "node_id": "T_VECTOR_REASONING",
        "node_type": "topic",
        "knowledge_unit_type": "topic",
        "canonical_name": "Vector Reasoning",
        "child_node_ids": ["KC_VECTOR_MAG_001", "KC_VECTOR_DIR_001"],
        "sibling_labels": ["Scalar Reasoning"],
        "topic_path_labels": ["Neutral Curriculum", "Vector Reasoning"],
    }


def _kc_unit() -> dict[str, object]:
    return {
        "kc_id": "KC_VECTOR_MAG_001",
        "node_id": "KC_VECTOR_MAG_001",
        "node_type": "kc",
        "knowledge_unit_type": "kc",
        "canonical_name": "Magnitude Interpretation",
        "sibling_labels": ["Direction Interpretation"],
        "topic_path_labels": ["Neutral Curriculum", "Vector Reasoning"],
    }


def _scored_topic_row(**overrides: object) -> dict[str, object]:
    row = {
        "knowledge_unit_id": "T_VECTOR_REASONING",
        "knowledge_unit_type": "topic",
        "kc_id": "T_VECTOR_REASONING",
        "canonical_name": "Vector Reasoning",
        "text": "This section introduces vector reasoning through magnitude and direction examples.",
        "candidate_text": "This section introduces vector reasoning through magnitude and direction examples.",
        "doc_id": "DOC_NEUTRAL",
        "page_index": 3,
        "block_id": "b1",
        "sentence_id": "s1",
        "patch_id": "p1",
        "patch_heading": "Vector Reasoning",
        "routing_recommendation": "review_only_candidate",
        "role_eligibility": {"positive_support_eligible": False},
        "candidate_quality": {"overall_score": 3.2, "target_bound_positive_support": False},
        "role_scores": {},
        "lexical_target_binding": {"binding_strength": "usable", "is_target_bound": True},
        "risk_flags": ["context_only_support"],
        "support_profile": {
            "topic_scope_evidence": True,
            "representative_source_region": {"doc_id": "DOC_NEUTRAL", "section": "Vector Reasoning"},
            "child_kc_coverage_summary": {
                "KC_VECTOR_MAG_001": "represented",
                "KC_VECTOR_DIR_001": "represented",
            },
        },
    }
    row.update(overrides)
    return row


def test_retrieval_policy_accepts_kc_and_topic_unit_types() -> None:
    kc_plan = build_retrieval_policy_plan(_kc_unit())
    topic_plan = build_retrieval_policy_plan(_topic_unit())

    assert kc_plan.knowledge_unit_type == "kc"
    assert topic_plan.knowledge_unit_type == "topic"
    assert "Magnitude Interpretation" in kc_plan.lexical_atoms
    assert "Vector Reasoning" in topic_plan.lexical_atoms


def test_topic_unit_does_not_require_definition_anchor() -> None:
    pack = compose_evidence_packs_from_scored_candidates([_scored_topic_row()])[0]

    assert pack["knowledge_unit_type"] == "topic"
    assert pack["pack_quality"]["route"] == "topic_scope_support_packet"
    assert "definition_anchor_missing" not in pack["pack_quality"]["insufficient_reasons"]


def test_topic_pack_can_use_representative_source_regions() -> None:
    pack = compose_evidence_packs_from_scored_candidates([_scored_topic_row(support_profile={
        "representative_source_region": {"doc_id": "DOC_NEUTRAL", "section": "Vector Reasoning"}
    })])[0]

    assert pack["pack_quality"]["route"] == "topic_representative_coverage_packet"
    assert pack["representative_source_regions"][0]["section"] == "Vector Reasoning"


def test_topic_scope_evidence_is_not_treated_as_kc_definition_kernel() -> None:
    pack = compose_evidence_packs_from_scored_candidates([_scored_topic_row()])[0]

    assert pack["slots"]["definition_kernel"] == []
    assert pack["topic_scope_evidence"]


def test_child_kc_coverage_summary_is_sidecar_not_positive_kc_evidence() -> None:
    pack = compose_evidence_packs_from_scored_candidates([_scored_topic_row()])[0]

    assert pack["child_kc_coverage_summary"]["KC_VECTOR_MAG_001"] == "represented"
    assert pack["ordered_pack_for_drafting"] == []


def test_topic_and_kc_nodes_remain_typed_and_not_flattened() -> None:
    kc_plan = build_retrieval_policy_plan(_kc_unit())
    topic_plan = build_retrieval_policy_plan(_topic_unit())

    assert kc_plan.knowledge_unit_id != topic_plan.knowledge_unit_id
    assert kc_plan.knowledge_unit_type == "kc"
    assert topic_plan.knowledge_unit_type == "topic"
    assert "representative_coverage" in topic_plan.shape_priors
    assert "definition" not in topic_plan.shape_priors


def test_retrieval_policy_carries_shapeaware_guidance_fields() -> None:
    plan = build_retrieval_policy_plan(
        _kc_unit(),
        guidance={
            "concept_head": "Magnitude",
            "qualifiers": ["Interpretation"],
            "expanded_aliases": ["Vector Magnitude Interpretation"],
            "normalized_surface_variants": ["Magnitude Interpretation", "Magnitude-Interpretation"],
            "expected_evidence_needs": [{"need": "definition_concept", "priority": "primary", "source": "test"}],
            "route_specific_query_variants": [{"route_id": "route_001", "queries": ["magnitude interpretation"]}],
            "route_specific_required_terms": [{"route_id": "route_001", "terms": ["magnitude"]}],
            "route_specific_optional_terms": [{"route_id": "route_001", "terms": ["vector"]}],
            "negative_sibling_terms": ["Direction Interpretation"],
            "risk_hints": ["qualifier_dependent_target"],
        },
    )
    rendered = plan.to_dict()
    assert rendered["concept_head"] == "Magnitude"
    assert rendered["expanded_aliases"] == ["Vector Magnitude Interpretation"]
    assert rendered["expected_evidence_needs"][0]["need"] == "definition_concept"
    assert rendered["negative_sibling_terms"] == ["Direction Interpretation"]
    assert rendered["risk_hints"] == ["qualifier_dependent_target"]


def main() -> None:
    test_retrieval_policy_accepts_kc_and_topic_unit_types()
    test_topic_unit_does_not_require_definition_anchor()
    test_topic_pack_can_use_representative_source_regions()
    test_topic_scope_evidence_is_not_treated_as_kc_definition_kernel()
    test_child_kc_coverage_summary_is_sidecar_not_positive_kc_evidence()
    test_topic_and_kc_nodes_remain_typed_and_not_flattened()
    test_retrieval_policy_carries_shapeaware_guidance_fields()
    print("TEST_STEP5X_RETRIEVAL_POLICY_OK")


if __name__ == "__main__":
    main()
