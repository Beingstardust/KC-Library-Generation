from __future__ import annotations

from kc_l.retrieval_gate.feedback_loop import build_retrieval_gap_requests, merge_profile_feedback


def test_target_bound_contradiction_gap_request_is_emitted() -> None:
    scored = [
        {
            "kc_id": "KC_X",
            "candidate_id": "c1",
            "candidate_source": "source_surface_fallback",
            "text": "A broad row that should not be positive support.",
            "role_eligibility": {"positive_support_eligible": True},
            "candidate_quality": {"target_bound_positive_support": False},
            "step5p_profile_guidance": {
                "profile_status": "usable",
                "profile_input_status": "strict_windows_available",
                "retrieval_route_count": 1,
                "active_retrieval_route_count": 1,
                "context_only_route_count": 0,
                "safe_to_use_for_step5x": True,
            },
        }
    ]
    packs = [{"kc_id": "KC_X", "ordered_pack_for_drafting": [{"candidate_id": "c1"}], "slots": {}}]
    requests = build_retrieval_gap_requests(scored_rows=scored, packs=packs, exact_kc_ids=["KC_X"])
    assert len(requests) == 1
    assert "target_bound_contradiction" in requests[0]["gap_types"]
    assert requests[0]["target_bound_false_positive_count"] == 1
    assert any(task["task"] == "repair_target_binding_or_deactivate_bad_routes" for task in requests[0]["requested_route_tasks"])


def test_zero_positive_and_pack_empty_gap_request_is_emitted() -> None:
    scored = [
        {
            "kc_id": "KC_Y",
            "candidate_id": "c2",
            "candidate_source": "structural_anchor_from_profile_or_label",
            "text": "A context row that found a region but no positive support.",
            "role_eligibility": {"positive_support_eligible": False},
            "candidate_quality": {"target_bound_positive_support": False},
            "step5p_profile_guidance": {
                "profile_status": "weak",
                "profile_input_status": "topic_local_content_scout",
                "retrieval_route_count": 0,
                "safe_to_use_for_step5x": False,
            },
        }
    ]
    packs = [{"kc_id": "KC_Y", "ordered_pack_for_drafting": [], "slots": {}}]
    requests = build_retrieval_gap_requests(scored_rows=scored, packs=packs, exact_kc_ids=["KC_Y"])
    assert len(requests) == 1
    assert "zero_positive_support" in requests[0]["gap_types"]
    assert "candidate_present_pack_empty" in requests[0]["gap_types"]
    assert "model_timeout_or_no_routes" in requests[0]["gap_types"]


def test_zero_candidate_gap_request_preserves_requested_kc() -> None:
    requests = build_retrieval_gap_requests(scored_rows=[], packs=[], exact_kc_ids=["KC_Z"])
    assert len(requests) == 1
    assert requests[0]["kc_id"] == "KC_Z"
    assert requests[0]["primary_gap_type"] == "zero_candidates"


def test_merge_profile_feedback_appends_route_metadata_without_seed_fields() -> None:
    base = {
        "kc_id": "KC_X",
        "canonical_name": "Example KC",
        "profile_status": "weak",
        "accepted_source_cues": [],
        "query_variants": [{"query": "Example KC", "active": True, "source": "deterministic_label_variant"}],
        "retrieval_routes": [],
        "audit": {"retrieval_route_count": 0},
    }
    repair = {
        "kc_id": "KC_X",
        "profile_status": "usable",
        "accepted_source_cues": [
            {"term": "source observed phrase", "cue_type": "definition_phrase", "active": True, "provenance": [{"snippet_id": "s1", "field_path": "sentence_text"}]}
        ],
        "query_variants": [{"query": "source observed phrase", "active": True, "source": "accepted_source_cue"}],
        "retrieval_routes": [
            {
                "route_id": "r1",
                "route_type": "anchored_phrase",
                "activation": "active",
                "primary_terms_any": ["source observed phrase"],
                "can_create_candidates": True,
                "can_create_positive_support": True,
                "seed_definition": "forbidden",
            }
        ],
        "seed_definition": "forbidden",
        "audit": {"model_used": True, "model_error": ""},
    }
    gap = {"gap_request_id": "gap_KC_X", "gap_types": ["zero_positive_support"]}
    merged = merge_profile_feedback(base_profile=base, repair_profile=repair, gap_request=gap, feedback_round=1)
    assert merged["profile_status"] == "usable"
    assert len(merged["accepted_source_cues"]) == 1
    assert len(merged["retrieval_routes"]) == 1
    assert "seed_definition" not in merged
    assert "seed_definition" not in merged["retrieval_routes"][0]
    assert merged["audit"]["feedback_round"] == 1
    assert merged["audit"]["feedback_repairs"][0]["gap_request_id"] == "gap_KC_X"


def test_selector_skips_kc_that_already_meets_thresholds() -> None:
    requests = [{"kc_id": "KC_GOOD", "gap_types": ["context_only_support"], "positive_support_count": 2, "ordered_pack_count": 2}]
    scored = [
        {"kc_id": "KC_GOOD", "role_eligibility": {"positive_support_eligible": True}},
        {"kc_id": "KC_GOOD", "role_eligibility": {"positive_support_eligible": True}},
    ]
    packs = [{"kc_id": "KC_GOOD", "ordered_pack_for_drafting": [{"candidate_id": "a"}, {"candidate_id": "b"}]}]
    from kc_l.retrieval_gate.feedback_loop import select_feedback_repair_kcs
    selected = select_feedback_repair_kcs(gap_requests=requests, packs=packs, scored_rows=scored)
    assert selected == []


def test_selector_selects_only_failed_kc() -> None:
    requests = [
        {"kc_id": "KC_FAIL", "gap_types": ["zero_positive_support"], "positive_support_count": 0, "ordered_pack_count": 0},
        {"kc_id": "KC_GOOD", "gap_types": [], "positive_support_count": 2, "ordered_pack_count": 2},
    ]
    from kc_l.retrieval_gate.feedback_loop import select_feedback_repair_kcs
    selected = select_feedback_repair_kcs(gap_requests=requests)
    assert [x["kc_id"] for x in selected] == ["KC_FAIL"]


def test_merge_keeps_initial_when_repair_regresses() -> None:
    from kc_l.retrieval_gate.feedback_loop import merge_feedback_outputs_by_kc
    initial_profiles = [{"kc_id": "KC_X", "profile_status": "usable", "audit": {"model_error": ""}}]
    repair_profiles = [{"kc_id": "KC_X", "profile_status": "weak", "audit": {"model_error": "TimeoutError('timed out')"}}]
    initial_scored = [{"kc_id": "KC_X", "candidate_id": "i1", "role_eligibility": {"positive_support_eligible": True}, "candidate_quality": {"target_bound_positive_support": True}}]
    repair_scored = []
    initial_packs = [{"kc_id": "KC_X", "ordered_pack_for_drafting": [{"candidate_id": "i1"}]}]
    repair_packs = [{"kc_id": "KC_X", "ordered_pack_for_drafting": []}]
    merged = merge_feedback_outputs_by_kc(
        initial_profiles=initial_profiles,
        repair_profiles=repair_profiles,
        initial_scored_rows=initial_scored,
        repair_scored_rows=repair_scored,
        initial_packs=initial_packs,
        repair_packs=repair_packs,
        selected_kc_ids=["KC_X"],
    )
    assert merged["merge_stats"]["accepted_repair_kcs"] == []
    assert merged["final_profiles"][0]["profile_status"] == "usable"
    assert merged["final_packs"][0]["ordered_pack_for_drafting"]


def test_merge_uses_repair_when_it_improves_failed_kc() -> None:
    from kc_l.retrieval_gate.feedback_loop import merge_feedback_outputs_by_kc
    initial_profiles = [{"kc_id": "KC_X", "profile_status": "weak", "audit": {"model_error": ""}}]
    repair_profiles = [{"kc_id": "KC_X", "profile_status": "usable", "audit": {"model_error": ""}}]
    initial_scored = []
    repair_scored = [{"kc_id": "KC_X", "candidate_id": "r1", "role_eligibility": {"positive_support_eligible": True}, "candidate_quality": {"target_bound_positive_support": True}}]
    initial_packs = [{"kc_id": "KC_X", "ordered_pack_for_drafting": []}]
    repair_packs = [{"kc_id": "KC_X", "ordered_pack_for_drafting": [{"candidate_id": "r1"}]}]
    merged = merge_feedback_outputs_by_kc(
        initial_profiles=initial_profiles,
        repair_profiles=repair_profiles,
        initial_scored_rows=initial_scored,
        repair_scored_rows=repair_scored,
        initial_packs=initial_packs,
        repair_packs=repair_packs,
        selected_kc_ids=["KC_X"],
    )
    assert merged["merge_stats"]["accepted_repair_kcs"] == ["KC_X"]
    assert merged["final_profiles"][0]["profile_status"] == "usable"
    assert merged["final_packs"][0]["ordered_pack_for_drafting"][0]["candidate_id"] == "r1"


def main() -> None:
    test_target_bound_contradiction_gap_request_is_emitted()
    test_zero_positive_and_pack_empty_gap_request_is_emitted()
    test_zero_candidate_gap_request_preserves_requested_kc()
    test_merge_profile_feedback_appends_route_metadata_without_seed_fields()
    test_selector_skips_kc_that_already_meets_thresholds()
    test_selector_selects_only_failed_kc()
    test_merge_keeps_initial_when_repair_regresses()
    test_merge_uses_repair_when_it_improves_failed_kc()
    print("TEST_STEP5P_STEP5X_FEEDBACK_LOOP_OK")


if __name__ == "__main__":
    main()
