
from __future__ import annotations

from kc_l.retrieval_gate.profile_guidance import guidance_from_profile

def test_v4d_consumes_source_equivalent_terms_and_source_windows():
    profile = {
        "kc_id": "KC_TEST_001",
        "canonical_name": "Pearson Product-Moment Correlation",
        "profile_status": "weak",
        "profile_input_status": "exploratory_only",
        "profile_policy_version": "step5p_deterministic_edge_policy_v2",
        "query_variants": [],
        "active_query_terms": [
            {
                "term": "Pearson Product-Moment Correlation",
                "source": "deterministic_label_variant",
                "retrieval_channels": ["lexical"],
                "retrieval_role": "lexical_query",
                "step5x_eligible": True,
                "provenance": [{"source": "registry", "source_id": "KC_TEST_001"}],
            }
        ],
        "source_equivalent_terms": [
            {
                "term": "pearson correlation",
                "source": "source_observed_window_cue",
                "cue_type": "compact_first_last_label_token_source_span",
                "step5x_eligible": True,
                "provenance": [
                    {
                        "snippet_id": "sent-1",
                        "sentence_id": "sent-1",
                        "doc_id": "doc",
                        "field_path": "sentence_text",
                    }
                ],
            }
        ],
        "source_windows": [
            {
                "window_role": "candidate_region",
                "snippet_id": "sent-1",
                "sentence_id": "sent-1",
                "doc_id": "doc",
                "patch_heading": "Correlation measures",
                "text": "Pearson correlation is used as a goodness measure.",
            }
        ],
        "negative_constraints": [
            {
                "term_or_pattern": "Spearman Rank Correlation",
                "constraint_type": "sibling_label",
                "reason": "sibling_collision_check",
                "active": False,
            }
        ],
    }

    guidance = guidance_from_profile(profile)

    assert guidance.safe_to_use_for_step5x is True
    assert guidance.accepted_source_cue_count == 1
    assert any(q.query == "pearson correlation" for q in guidance.lexical_queries)
    assert any(route.activation == "active" and "pearson correlation" in route.primary_terms_any for route in guidance.retrieval_routes)
    assert any(payload.get("source") == "v4_source_window" for payload in guidance.region_locator_payloads)
    assert len(guidance.negative_constraints) == 0

def main():
    test_v4d_consumes_source_equivalent_terms_and_source_windows()
    print("TEST_STEP5X_PROFILE_GUIDANCE_V4D_BRIDGE_OK")

if __name__ == "__main__":
    main()
