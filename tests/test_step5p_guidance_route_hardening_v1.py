from __future__ import annotations

from kc_l.retrieval_profile.builder import _preserve_current_run_llm_policy_after_feedback_merge
from kc_l.retrieval_gate.profile_guidance import guidance_from_profile, guidance_to_candidate_bank_controls


def test_feedback_merge_dedupes_guidance_and_rebuilds_contract_fields():
    base = {
        "kc_id": "KC_TEST",
        "canonical_name": "Binary Example",
        "profile_status": "usable",
        "profile_mode": "deterministic_only",
        "llm_policy": "never",
        "query_variants": [],
        "accepted_source_cues": [
            {
                "term": "binary examples",
                "cue_type": "source_observed_equivalent",
                "validation_bucket": "source_observed",
                "active": True,
                "provenance": [{"snippet_id": "s1", "field_path": "sentence_text"}],
            }
        ],
        "retrieval_routes": [
            {
                "route_id": "accepted_cue_route_001",
                "route_type": "anchored_phrase",
                "activation": "active",
                "route_strength": "strong",
                "verification_status": "source_observed_same_window",
                "primary_terms_any": ["binary examples"],
                "source_provenance_ids": ["s1"],
                "provenance": [{"snippet_id": "s1", "field_path": "sentence_text"}],
                "can_create_candidates": True,
                "can_create_positive_support": True,
            }
        ],
        "validated_guidance_buckets": {
            "source_observed": [],
            "source_supported_near_target": [],
            "model_suggested_unverified": [],
            "rejected": [],
        },
        "audit": {
            "strict_source_windows": [
                {"snippet_id": "s1", "field_path": "sentence_text", "text": "binary examples"}
            ]
        },
    }

    repair = dict(base)
    repair["profile_mode"] = "llm_policy_always"
    repair["llm_policy"] = "always"
    repair["model_call_attempted"] = True
    repair["model_call_succeeded"] = True
    repair["accepted_source_cues"] = [
        {**base["accepted_source_cues"][0], "feedback_round": 1, "source": "step5p_feedback_round_1"}
    ]
    repair["retrieval_routes"] = [
        {**base["retrieval_routes"][0], "feedback_round": 1}
    ]
    repair["validated_guidance_buckets"] = {
        "source_observed": repair["accepted_source_cues"],
        "source_supported_near_target": [],
        "model_suggested_unverified": [],
        "rejected": [],
    }
    repair["audit"] = dict(
        base["audit"],
        llm_policy="always",
        model_call_attempted=True,
        model_call_succeeded=True,
    )

    merged = dict(base)
    merged["accepted_source_cues"] = [
        *repair["accepted_source_cues"],
        *base["accepted_source_cues"],
    ]
    merged["retrieval_routes"] = [
        *repair["retrieval_routes"],
        *base["retrieval_routes"],
    ]
    merged["validated_guidance_buckets"] = {
        "source_observed": merged["accepted_source_cues"],
        "source_supported_near_target": [],
        "model_suggested_unverified": [],
        "rejected": [],
    }

    out = _preserve_current_run_llm_policy_after_feedback_merge(
        merged_profile=merged,
        repair_profile=repair,
        effective_llm_policy="always",
        use_model=True,
        feedback_round=1,
    )

    assert out["llm_policy"] == "always"
    assert out["model_call_attempted"] is True
    assert out["model_call_succeeded"] is True
    assert len(out["accepted_source_cues"]) == 1
    assert len(out["retrieval_routes"]) == 1
    assert len(out["source_equivalent_terms"]) == 1
    assert len(out["active_query_terms"]) >= 1
    assert out["audit"]["base_profile_policy_overwrite_blocked"] is True


def test_profile_guidance_route_controls_emit_term_and_query_aliases():
    profile = {
        "kc_id": "KC_TEST",
        "canonical_name": "Binary Example",
        "profile_status": "usable",
        "profile_mode": "llm_policy_always",
        "llm_invocation_decision": "invoke",
        "retrieval_routes": [
            {
                "route_id": "r1",
                "route_type": "anchored_phrase",
                "activation": "active",
                "route_strength": "strong",
                "verification_status": "source_observed_same_window",
                "primary_terms_any": ["binary examples"],
                "source_provenance_ids": ["s1"],
                "provenance": [{"snippet_id": "s1"}],
                "can_create_candidates": True,
                "can_create_positive_support": True,
            }
        ],
        "accepted_source_cues": [],
        "source_equivalent_terms": [],
        "query_variants": [],
        "audit": {},
    }

    controls = guidance_to_candidate_bank_controls(guidance_from_profile(profile))
    route = controls["retrieval_routes"][0]
    assert route["term"] == "binary examples"
    assert route["query"] == "binary examples"
    assert route["primary_terms_any"] == ["binary examples"]


def main():
    test_feedback_merge_dedupes_guidance_and_rebuilds_contract_fields()
    test_profile_guidance_route_controls_emit_term_and_query_aliases()
    print("TEST_STEP5P_GUIDANCE_ROUTE_HARDENING_V1_OK")


if __name__ == "__main__":
    main()
