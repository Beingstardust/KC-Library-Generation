from __future__ import annotations

from kc_l.retrieval_profile.builder import (
    _build_deterministic_timeout_fallback_profile_parts,
    _detect_source_sparse_label_mismatch,
    _enforce_profile_window_budget,
)


def test_window_budget_enforced() -> None:
    strict = [{"snippet_id": f"s{i}", "text": f"strict {i}"} for i in range(3)]
    exploratory = [{"snippet_id": f"e{i}", "text": f"exploratory {i}"} for i in range(5)]
    kept_strict, kept_exploratory, audit = _enforce_profile_window_budget(
        strict, exploratory, max_snippets_per_kc=4
    )
    assert len(kept_strict) == 3
    assert len(kept_exploratory) == 1
    assert audit["trimmed_window_count"] == 4
    assert audit["budget_enforced"] is True


def test_timeout_fallback_builds_source_observed_route() -> None:
    parts = _build_deterministic_timeout_fallback_profile_parts(
        kc_row={"kc_id": "KC_TEST", "canonical_name": "Example Phase", "aliases": []},
        snippets=[
            {
                "snippet_id": "s1",
                "text": "The process of using the learned model on new cases is known as example deduction.",
                "field_path": "sentence_text",
                "score": 9.0,
                "score_reasons": ["strong_relation_or_definition"],
                "evidence_shapes": ["definition_shape"],
                "target_overlap": ["example"],
                "branch_overlap": ["model"],
            }
        ],
    )
    assert parts["accepted_source_cues"]
    assert parts["retrieval_routes"]
    route = parts["retrieval_routes"][0]
    assert route["source"] == "deterministic_model_timeout_fallback"
    assert route["verification_status"] == "source_observed_timeout_fallback"
    assert route["can_create_candidates"] is True
    assert route["support_authority"] == "candidate_hint_step5x_must_verify"
    assert route["step5x_verification_required"] is True
    assert route["profile_output_role"] == "retrieval_control_metadata_not_evidence"


def test_label_mismatch_is_context_only_review_flag() -> None:
    audit = _detect_source_sparse_label_mismatch(
        kc_row={"kc_id": "KC_TEST", "canonical_name": "Unseen Label", "aliases": []},
        snippets=[
            {
                "snippet_id": "s1",
                "text": "A nearby denominator concept is explained here with useful branch context.",
                "branch_overlap": ["denominator", "branch"],
                "source_neighborhood_anchor_terms": ["nearby concept"],
            }
        ],
        accepted=[],
        retrieval_routes=[],
    )
    assert audit["source_sparse_label_mismatch"] is True
    assert audit["neighbor_context_window_count"] == 1



def test_timeout_fallback_reference_like_route_is_context_only() -> None:
    parts = _build_deterministic_timeout_fallback_profile_parts(
        kc_row={"kc_id": "KC_TEST", "canonical_name": "Example Measure", "aliases": []},
        snippets=[
            {
                "snippet_id": "s_ref",
                "text": "The original source of the example measure is an article by Example and Author [123].",
                "field_path": "sentence_text",
                "score": 9.0,
                "score_reasons": ["strong_relation_or_definition"],
                "evidence_shapes": ["definition_shape"],
                "target_overlap": ["example", "measure"],
                "branch_overlap": ["example"],
            }
        ],
    )
    assert parts["retrieval_routes"]
    route = parts["retrieval_routes"][0]
    assert route["can_create_candidates"] is True
    assert route["can_create_positive_support"] is False
    assert route["broad_context_only"] is True
    assert route["fallback_reference_like"] is True


def test_timeout_fallback_generic_support_terms_are_filtered() -> None:
    parts = _build_deterministic_timeout_fallback_profile_parts(
        kc_row={"kc_id": "KC_TEST", "canonical_name": "Example Phase", "aliases": []},
        snippets=[
            {
                "snippet_id": "s_generic",
                "text": "A useful process phrase is known as an example phase in this source window.",
                "field_path": "sentence_text",
                "score": 9.0,
                "score_reasons": ["strong_relation_or_definition"],
                "evidence_shapes": ["definition_shape"],
                "target_overlap": ["example"],
                "branch_overlap": ["underpinning"],
            }
        ],
    )
    assert parts["retrieval_routes"]
    route = parts["retrieval_routes"][0]
    assert "underpinning" not in [x.lower() for x in route.get("support_terms_any", [])]


def main() -> None:
    test_window_budget_enforced()
    test_timeout_fallback_builds_source_observed_route()
    test_label_mismatch_is_context_only_review_flag()
    print("TEST_STEP5P_V3_TIMEOUT_FALLBACK_OK")


if __name__ == "__main__":
    main()
