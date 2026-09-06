
from __future__ import annotations

from kc_l.retrieval_profile.builder import _preserve_current_run_llm_policy_after_feedback_merge


def test_feedback_merge_preserves_current_run_llm_policy_and_model_accounting():
    base_like_merged = {
        "kc_id": "KC_TEST_001",
        "canonical_name": "Test KC",
        "profile_status": "usable",
        "profile_mode": "deterministic_only",
        "llm_policy": "never",
        "llm_invocation_decision": "skip",
        "llm_skipped_reason": "policy_never",
        "model_call_attempted": False,
        "model_call_succeeded": False,
        "accepted_source_cues": [{"term": "old cue", "cue_type": "context_phrase"}],
        "retrieval_routes": [],
        "validated_guidance_buckets": {
            "source_observed": [{"term": "old cue", "cue_type": "context_phrase"}],
            "source_supported_near_target": [],
            "model_suggested_unverified": [],
            "rejected": [],
        },
        "audit": {
            "llm_policy": "never",
            "model_call_attempted": False,
            "model_call_succeeded": False,
            "llm_invocation_decision": "skip",
            "llm_skipped_reason": "policy_never",
        },
    }

    current_repair = {
        "kc_id": "KC_TEST_001",
        "canonical_name": "Test KC",
        "profile_status": "usable",
        "profile_mode": "llm_policy_always",
        "llm_policy": "always",
        "llm_invocation_decision": "invoke",
        "llm_skipped_reason": "",
        "model_call_attempted": True,
        "model_call_succeeded": True,
        "accepted_source_cues": [{"term": "new source cue", "cue_type": "definition_phrase"}],
        "model_suggested_unverified_terms": [{"term": "new model cue", "cue_type": "context_phrase"}],
        "retrieval_routes": [{"route_type": "source_observed", "term": "new source cue"}],
        "validated_guidance_buckets": {
            "source_observed": [{"term": "new source cue", "cue_type": "definition_phrase"}],
            "source_supported_near_target": [],
            "model_suggested_unverified": [{"term": "new model cue", "cue_type": "context_phrase"}],
            "rejected": [],
        },
        "audit": {
            "llm_policy": "always",
            "model_used": True,
            "model_call_attempted": True,
            "model_call_succeeded": True,
            "profile_mode": "llm_policy_always",
            "llm_invocation_decision": "invoke",
            "llm_skipped_reason": "",
        },
    }

    out = _preserve_current_run_llm_policy_after_feedback_merge(
        merged_profile=base_like_merged,
        repair_profile=current_repair,
        effective_llm_policy="always",
        use_model=True,
        feedback_round=1,
    )

    assert out["llm_policy"] == "always"
    assert out["profile_mode"] == "llm_policy_always"
    assert out["llm_invocation_decision"] == "invoke"
    assert out["llm_skipped_reason"] == ""
    assert out["model_call_attempted"] is True
    assert out["model_call_succeeded"] is True
    assert out["audit"]["llm_policy"] == "always"
    assert out["audit"]["model_call_attempted"] is True
    assert out["audit"]["model_call_succeeded"] is True
    assert out["audit"]["base_profile_policy_overwrite_blocked"] is True
    assert any(item.get("term") == "new source cue" for item in out["accepted_source_cues"])
    assert any(item.get("term") == "new model cue" for item in out["model_suggested_unverified_terms"])
    assert any(item.get("term") == "new source cue" for item in out["retrieval_routes"])


def main():
    test_feedback_merge_preserves_current_run_llm_policy_and_model_accounting()
    print("TEST_STEP5P_FEEDBACK_MERGE_POLICY_PRECEDENCE_OK")


if __name__ == "__main__":
    main()
