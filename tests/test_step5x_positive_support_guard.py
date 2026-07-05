from __future__ import annotations

from kc_l.retrieval_gate.evidence_stage_v3_pack_composition import compose_evidence_packs_from_scored_candidates
from kc_l.retrieval_gate.evidence_stage_v3_scored_candidates import _positive_support_guard


def _row(*, risk_flags=None, strict_basis=False, unit_type="kc") -> dict:
    row = {
        "kc_id": "KC_SYN_001" if unit_type == "kc" else "TOPIC_SYN_001",
        "knowledge_unit_id": "KC_SYN_001" if unit_type == "kc" else "TOPIC_SYN_001",
        "knowledge_unit_type": unit_type,
        "canonical_name": "Synthetic Unit",
        "candidate_id": "cand1",
        "scored_candidate_id": "cand1",
        "text": "A synthetic unit is a bounded concept.",
        "candidate_text": "A synthetic unit is a bounded concept.",
        "routing_recommendation": "positive_role_candidate",
        "risk_flags": list(risk_flags or []),
        "role_scores": {
            "definition_kernel": 7.0,
            "explanatory_gloss": 1.0,
            "scope_condition": 1.0,
            "formula_notation": 1.0,
            "example_or_procedure": 1.0,
            "context_completion_candidate": 1.0,
            "sibling_contrast": 0.0,
        },
        "role_eligibility": {
            "definition_kernel": True,
            "positive_support_eligible": True,
        },
        "candidate_quality": {
            "overall_score": 6.0,
            "target_bound_positive_support": True,
            "target_bound_positive_support_basis": {
                "direct_target_statement": bool(strict_basis),
            },
        },
        "lexical_target_binding": {
            "is_target_bound": bool(strict_basis),
            "binding_strength": "strong" if strict_basis else "weak",
        },
        "definition_framing_score": {
            "subject_alignment": "aligned" if strict_basis else "unknown",
        },
        "positive_support_guard": {
            "guard_version": "step5x_positive_support_guard_v1",
            "blocked_from_positive_support": bool(risk_flags and ("definition_subject_mismatch" in risk_flags or ("needs_stronger_anchor_context" in risk_flags and not strict_basis))),
            "blocker_flags": list(risk_flags or []) if risk_flags and ("definition_subject_mismatch" in risk_flags or ("needs_stronger_anchor_context" in risk_flags and not strict_basis)) else [],
            "strict_target_basis": bool(strict_basis),
            "pack_action": "near_miss_review_only" if risk_flags and ("definition_subject_mismatch" in risk_flags or ("needs_stronger_anchor_context" in risk_flags and not strict_basis)) else "allow_positive_support_candidate",
        },
        "doc_id": "DOC_SYNTH",
        "page_index": 1,
        "sentence_id": "s1",
        "patch_id": "p1",
    }
    return row


def test_scorer_guard_sidecar_does_not_mutate_role_eligibility_contract() -> None:
    eligibility = {"formula_notation": True, "positive_support_eligible": True}
    guard = _positive_support_guard(
        risk_flags=["definition_subject_mismatch"],
        role_eligibility=eligibility,
        lexical_target_binding={"is_target_bound": True, "binding_strength": "strong"},
        definition_framing={"subject_alignment": "aligned"},
        direct_target_statement={"is_direct_target_statement": True},
        candidate_quality={"target_bound_positive_support_basis": {"structural_anchor_formula_support": True}},
        unit_type="kc",
    )
    assert eligibility["formula_notation"] is True
    assert eligibility["positive_support_eligible"] is True
    assert guard["blocked_from_positive_support"] is True
    assert "definition_subject_mismatch" in guard["blocker_flags"]


def test_pack_blocks_guarded_positive_row_but_preserves_near_miss() -> None:
    pack = compose_evidence_packs_from_scored_candidates([
        _row(risk_flags=["definition_subject_mismatch"], strict_basis=True)
    ])[0]
    assert pack["ordered_pack_for_drafting"] == [], pack
    assert pack["near_miss_review_items"], pack
    assert "definition_subject_mismatch" in pack["near_miss_review_items"][0]["risk_flags"]


def test_pack_allows_conditional_needs_stronger_when_strict_basis_exists() -> None:
    pack = compose_evidence_packs_from_scored_candidates([
        _row(risk_flags=["needs_stronger_anchor_context"], strict_basis=True)
    ])[0]
    assert len(pack["ordered_pack_for_drafting"]) == 1, pack


def test_pack_blocks_conditional_needs_stronger_without_strict_basis() -> None:
    pack = compose_evidence_packs_from_scored_candidates([
        _row(risk_flags=["needs_stronger_anchor_context"], strict_basis=False)
    ])[0]
    assert pack["ordered_pack_for_drafting"] == [], pack
    assert pack["near_miss_review_items"], pack


def test_topic_unit_not_blocked_by_kc_positive_support_guard() -> None:
    topic = _row(risk_flags=["needs_stronger_anchor_context"], strict_basis=False, unit_type="topic")
    topic["positive_support_guard"] = {
        "guard_version": "step5x_positive_support_guard_v1",
        "blocked_from_positive_support": False,
        "blocker_flags": [],
        "strict_target_basis": True,
        "pack_action": "allow_pack_composer_to_apply_topic_policy",
    }
    pack = compose_evidence_packs_from_scored_candidates([topic])[0]
    assert pack["knowledge_unit_type"] == "topic"
    assert len(pack["ordered_pack_for_drafting"]) == 1, pack


def test_formula_without_target_binding_blocks_structural_formula_basis() -> None:
    guard = _positive_support_guard(
        risk_flags=["formula_without_target_binding"],
        role_eligibility={
            "formula_notation": True,
            "positive_support_eligible": True,
            "structural_anchor_formula_support": True,
        },
        lexical_target_binding={"is_target_bound": False, "binding_strength": "weak"},
        definition_framing={"subject_alignment": "aligned"},
        direct_target_statement={"is_direct_target_statement": False},
        candidate_quality={
            "target_bound_positive_support_basis": {
                "structural_anchor_formula_support": True,
            },
        },
        unit_type="kc",
    )
    assert guard["blocked_from_positive_support"] is True, guard
    assert "formula_without_target_binding" in guard["blocker_flags"], guard
    assert "formula_without_target_binding" in guard["conditional_blocker_flags"], guard


def test_formula_without_target_binding_can_pass_with_direct_target_basis() -> None:
    guard = _positive_support_guard(
        risk_flags=["formula_without_target_binding"],
        role_eligibility={
            "formula_notation": True,
            "positive_support_eligible": True,
            "structural_anchor_formula_support": True,
        },
        lexical_target_binding={"is_target_bound": False, "binding_strength": "weak"},
        definition_framing={"subject_alignment": "unknown"},
        direct_target_statement={"is_direct_target_statement": True},
        candidate_quality={
            "target_bound_positive_support_basis": {
                "structural_anchor_formula_support": True,
                "direct_target_statement": True,
            },
        },
        unit_type="kc",
    )
    assert guard["blocked_from_positive_support"] is False, guard
    assert "structural_anchor_formula_support" in guard["strict_target_basis_reasons"], guard
    assert "direct_target_statement" in guard["strict_target_basis_reasons"], guard


def test_formula_without_target_binding_can_pass_with_strong_lexical_target_basis() -> None:
    guard = _positive_support_guard(
        risk_flags=["formula_without_target_binding"],
        role_eligibility={
            "formula_notation": True,
            "positive_support_eligible": True,
            "structural_anchor_formula_support": True,
        },
        lexical_target_binding={"is_target_bound": True, "binding_strength": "strong"},
        definition_framing={"subject_alignment": "unknown"},
        direct_target_statement={"is_direct_target_statement": False},
        candidate_quality={
            "target_bound_positive_support_basis": {
                "structural_anchor_formula_support": True,
                "lexical_target_bound": True,
            },
        },
        unit_type="kc",
    )
    assert guard["blocked_from_positive_support"] is False, guard
    assert "target_bound_lexical_binding" in guard["strict_target_basis_reasons"], guard


def test_formula_without_target_binding_does_not_block_topic_units() -> None:
    guard = _positive_support_guard(
        risk_flags=["formula_without_target_binding"],
        role_eligibility={
            "formula_notation": True,
            "positive_support_eligible": True,
            "structural_anchor_formula_support": True,
        },
        lexical_target_binding={"is_target_bound": False, "binding_strength": "weak"},
        definition_framing={"subject_alignment": "unknown"},
        direct_target_statement={"is_direct_target_statement": False},
        candidate_quality={},
        unit_type="topic",
    )
    assert guard["blocked_from_positive_support"] is False, guard


def main() -> None:
    test_scorer_guard_sidecar_does_not_mutate_role_eligibility_contract()
    test_pack_blocks_guarded_positive_row_but_preserves_near_miss()
    test_pack_allows_conditional_needs_stronger_when_strict_basis_exists()
    test_pack_blocks_conditional_needs_stronger_without_strict_basis()
    test_topic_unit_not_blocked_by_kc_positive_support_guard()
    test_formula_without_target_binding_blocks_structural_formula_basis()
    test_formula_without_target_binding_can_pass_with_direct_target_basis()
    test_formula_without_target_binding_can_pass_with_strong_lexical_target_basis()
    test_formula_without_target_binding_does_not_block_topic_units()
    print("TEST_STEP5X_POSITIVE_SUPPORT_GUARD_OK")


if __name__ == "__main__":
    main()
