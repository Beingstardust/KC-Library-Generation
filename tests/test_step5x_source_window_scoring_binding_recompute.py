from kc_l.retrieval_gate.evidence_stage_v3_scored_candidates import (
    _recompute_source_window_binding_and_roles_for_row,
)


def test_source_window_recompute_promotes_exact_target_bound_row() -> None:
    row = {
        "kc_id": "KC_SYNTH_WINDOW",
        "canonical_name": "Omega Score",
        "text": "The Omega Score is a measure used to compare two system outputs.",
        "source_block_text": "The Omega Score is a measure used to compare two system outputs.",
        "support_profile": {
            "source_overlay_source_block_window": True,
            "source_overlay_window_promotion": {
                "promoted": True,
            },
        },
        "lexical_target_binding": {
            "binding_strength": "weak",
        },
        "role_eligibility": {},
        "risk_flags": [],
        "candidate_quality": {
            "decision": "keep",
        },
    }

    out, changed = _recompute_source_window_binding_and_roles_for_row(row)

    assert changed is True
    assert out["lexical_target_binding"]["binding_strength"] == "usable"
    assert out["role_eligibility"]["explanatory_gloss"] is True
    assert out["role_eligibility"]["positive_support_eligible"] is True
    assert out["role_eligibility"]["independent_step5x_positive_basis"] is True
    assert out["routing_recommendation"] == "positive_role_candidate"
    assert out["source_window_scoring_binding_recompute"]["applied"] is True


def test_source_window_recompute_rejects_missing_exact_target_hit() -> None:
    row = {
        "kc_id": "KC_SYNTH_WINDOW",
        "canonical_name": "Omega Score",
        "text": "This sentence discusses another score.",
        "support_profile": {
            "source_overlay_source_block_window": True,
            "source_overlay_window_promotion": {
                "promoted": True,
            },
        },
        "lexical_target_binding": {
            "binding_strength": "weak",
        },
        "role_eligibility": {},
    }

    out, changed = _recompute_source_window_binding_and_roles_for_row(row)

    assert changed is False
    assert out["lexical_target_binding"]["binding_strength"] == "weak"
    assert out["role_eligibility"] == {}


def test_source_window_recompute_rejects_non_promoted_row() -> None:
    row = {
        "kc_id": "KC_SYNTH_WINDOW",
        "canonical_name": "Omega Score",
        "text": "The Omega Score is a measure used to compare two system outputs.",
        "lexical_target_binding": {
            "binding_strength": "weak",
        },
        "role_eligibility": {},
    }

    out, changed = _recompute_source_window_binding_and_roles_for_row(row)

    assert changed is False
    assert out["lexical_target_binding"]["binding_strength"] == "weak"
    assert out["role_eligibility"] == {}


if __name__ == "__main__":
    test_source_window_recompute_promotes_exact_target_bound_row()
    test_source_window_recompute_rejects_missing_exact_target_hit()
    test_source_window_recompute_rejects_non_promoted_row()
    print("TEST_STEP5X_SOURCE_WINDOW_SCORING_BINDING_RECOMPUTE_OK")
