from __future__ import annotations

from kc_l.retrieval_gate.evidence_admission import decide_evidence_admission


def clean_positive_row():
    return {
        "routing_recommendation": "positive_role_candidate",
        "shapeaware_bucket": "drafting_core",
        "risk_flags": [],
        "review_risk_flags": [],
        "candidate_quality": {"target_bound_positive_support": True},
        "positive_support_guard": {"blocked_from_positive_support": False, "blocker_flags": []},
        "role_eligibility": {"definition_kernel": True, "positive_support_eligible": True},
    }


def test_clean_positive_is_ordered():
    admission = decide_evidence_admission(clean_positive_row())
    assert admission["decision"] == "ordered_evidence"
    assert admission["role"] == "definition_kernel"


def test_rejected_false_positive_bucket_is_rejected():
    row = clean_positive_row()
    row["shapeaware_bucket"] = "rejected_false_positive"
    admission = decide_evidence_admission(row)
    assert admission["decision"] == "reject"
    assert "shapeaware_rejected_false_positive" in admission["hard_reasons"]


def test_review_needed_bucket_is_review_not_ordered():
    row = clean_positive_row()
    row["shapeaware_bucket"] = "review_needed"
    admission = decide_evidence_admission(row)
    assert admission["decision"] == "review"
    assert admission["role"] == "definition_kernel"
    assert "shapeaware_bucket_review_needed" in admission["basis"]


def test_auxiliary_bucket_is_auxiliary_not_ordered():
    row = clean_positive_row()
    row["shapeaware_bucket"] = "auxiliary"
    admission = decide_evidence_admission(row)
    assert admission["decision"] == "auxiliary_context"
    assert admission["role"] == "context_completion"
    assert "shapeaware_bucket_auxiliary" in admission["basis"]


def test_seed_field_is_rejected():
    row = clean_positive_row()
    row["seed_definition"] = "forbidden"
    admission = decide_evidence_admission(row)
    assert admission["decision"] == "reject"
    assert "seed_or_legacy_field_present" in admission["hard_reasons"]


def test_manual_review_candidate_is_review():
    row = clean_positive_row()
    row["routing_recommendation"] = "manual_review_candidate"
    row["candidate_quality"] = {"target_bound_positive_support": False}
    row["role_eligibility"] = {}
    admission = decide_evidence_admission(row)
    assert admission["decision"] == "review"


def test_auxiliary_candidate_is_auxiliary_context():
    row = clean_positive_row()
    row["routing_recommendation"] = "auxiliary_only_candidate"
    row["candidate_quality"] = {"auxiliary_support": True, "same_region_auxiliary_only": True}
    row["role_eligibility"] = {"context_completion_candidate": True}
    admission = decide_evidence_admission(row)
    assert admission["decision"] == "auxiliary_context"
    assert admission["role"] == "context_completion"


def test_guardrail_candidate_is_guardrail():
    row = clean_positive_row()
    row["routing_recommendation"] = "guardrail_only_candidate"
    row["candidate_quality"] = {"guardrail_only": True}
    row["role_eligibility"] = {"sibling_contrast": True, "guardrail_support_eligible": True}
    admission = decide_evidence_admission(row)
    assert admission["decision"] == "guardrail"
    assert admission["role"] == "sibling_contrast"


if __name__ == "__main__":
    tests = [
        test_clean_positive_is_ordered,
        test_rejected_false_positive_bucket_is_rejected,
        test_review_needed_bucket_is_review_not_ordered,
        test_auxiliary_bucket_is_auxiliary_not_ordered,
        test_seed_field_is_rejected,
        test_manual_review_candidate_is_review,
        test_auxiliary_candidate_is_auxiliary_context,
        test_guardrail_candidate_is_guardrail,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
