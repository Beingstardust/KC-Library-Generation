
from __future__ import annotations

from kc_l.retrieval_gate.evidence_stage_v3_pack_composition import _pack_admission_decision

def _base_row_with_flag(flag: str):
    return {
        "risk_flags": [flag],
        "candidate_quality": {
            "target_bound_positive_support": True,
            "target_bound_positive_support_basis": {
                "direct_target_statement": True,
            },
        },
        "role_eligibility": {
            "positive_support_eligible": True,
            "definition_kernel": True,
        },
        "lexical_target_binding": {
            "is_target_bound": True,
            "binding_strength": "strong",
            "exact_target_phrase_in_text": True,
            "text_target_match_count": 1,
        },
    }

def test_needs_stronger_anchor_context_blocks_ordered_positive_pack():
    decision = _pack_admission_decision(
        _base_row_with_flag("needs_stronger_anchor_context"),
        role="definition_kernel",
    )
    assert decision["admitted"] is False
    assert any("needs_stronger_anchor_context" in reason for reason in decision["reasons"])

def test_suspected_false_positive_blocks_ordered_positive_pack():
    decision = _pack_admission_decision(
        _base_row_with_flag("suspected_false_positive"),
        role="definition_kernel",
    )
    assert decision["admitted"] is False
    assert any("suspected_false_positive" in reason for reason in decision["reasons"])

def test_clean_positive_pack_still_admitted():
    row = _base_row_with_flag("")
    row["risk_flags"] = []
    decision = _pack_admission_decision(row, role="definition_kernel")
    assert decision["admitted"] is True

def main():
    test_needs_stronger_anchor_context_blocks_ordered_positive_pack()
    test_suspected_false_positive_blocks_ordered_positive_pack()
    test_clean_positive_pack_still_admitted()
    print("TEST_STEP5X_PACK_V4E_RISK_BLOCKERS_OK")

if __name__ == "__main__":
    main()
