
from kc_l.retrieval_gate.evidence_stage_v3_candidate_bank import (
    SOURCE_OVERLAY_TARGET_SUPPLEMENT,
    _build_direct_overlay_supplement_candidates,
)


def test_direct_overlay_promotes_fragmentary_source_overlay_row_from_target_bound_source_block() -> None:
    contexts = [
        {
            "kc_id": "KC_SYNTH_WINDOW",
            "canonical_name": "Omega Score",
            "aliases": [],
            "topic_path_labels": ["Synthetic Topic"],
            "parent_topic_label": "Synthetic Topic",
        }
    ]
    supplement_rows = [
        {
            "kc_id": "KC_SYNTH_WINDOW",
            "knowledge_unit_id": "KC_SYNTH_WINDOW",
            "canonical_name": "Omega Score",
            "target_signals": ["Omega Score"],
            "matched_surface_terms": ["Omega Score"],
            "signal_terms": ["Omega Score"],
            "reason_codes": [SOURCE_OVERLAY_TARGET_SUPPLEMENT, "target_phrase_in_source_block"],
            "candidate_source": SOURCE_OVERLAY_TARGET_SUPPLEMENT,
            "sentence_text": "is useful.",
            "source_block_text": "The Omega Score is a measure used to compare two system outputs.",
            "doc_id": "DOC_SYNTH",
            "block_id": "b_window",
            "sentence_id": "s_fragment",
            "patch_id": "p_window",
            "is_meta": False,
            "is_nav_boilerplate": False,
            "is_author_affiliation": False,
            "is_transition_text": False,
            "is_heading_like": False,
            "is_formula_like": False,
            "is_definition_like": False,
            "is_procedure_like": False,
            "is_example_like": False,
        }
    ]

    candidate_rows, stats = _build_direct_overlay_supplement_candidates(
        run_id="test_direct_source_window",
        supplement_rows=supplement_rows,
        supplement_manifest="synthetic_source_overlay.jsonl",
        selected_kc_context_rows=contexts,
        guidance_lookup={},
        existing_rows=[],
        cfg={
            "enabled": True,
            "max_candidates_per_kc": 8,
            "min_score": 4.8,
            "reject_prompt_like": True,
            "reject_fragmentary": True,
            "reject_reference_like": True,
            "reject_formula_only_without_target_signal": True,
            "source_overlay_promote_source_block_window": True,
            "source_overlay_source_block_window_max_chars": 900,
        },
    )

    assert stats["candidate_rows_added"] == 1
    assert stats["rehydration_queue_count"] == 0
    assert stats["rejected_counts"] == {}
    assert len(candidate_rows) == 1
    row = candidate_rows[0]
    assert row["kc_id"] == "KC_SYNTH_WINDOW"
    assert row["text"] == "The Omega Score is a measure used to compare two system outputs."
    assert row["support_profile"]["source_overlay_source_block_window"] is True
    assert row["provenance"]["source_overlay_source_block_window"] is True


def test_direct_overlay_does_not_promote_non_source_overlay_rows() -> None:
    contexts = [
        {
            "kc_id": "KC_SYNTH_WINDOW",
            "canonical_name": "Omega Score",
            "aliases": [],
            "topic_path_labels": ["Synthetic Topic"],
            "parent_topic_label": "Synthetic Topic",
        }
    ]
    supplement_rows = [
        {
            "kc_id": "KC_SYNTH_WINDOW",
            "knowledge_unit_id": "KC_SYNTH_WINDOW",
            "canonical_name": "Omega Score",
            "target_signals": ["Omega Score"],
            "matched_surface_terms": ["Omega Score"],
            "signal_terms": ["Omega Score"],
            "reason_codes": ["other_lane"],
            "candidate_source": "other_lane",
            "sentence_text": "is useful.",
            "source_block_text": "The Omega Score is a measure used to compare two system outputs.",
            "doc_id": "DOC_SYNTH",
            "block_id": "b_window",
            "sentence_id": "s_fragment",
            "patch_id": "p_window",
        }
    ]

    candidate_rows, stats = _build_direct_overlay_supplement_candidates(
        run_id="test_direct_source_window_negative",
        supplement_rows=supplement_rows,
        supplement_manifest="synthetic_source_overlay.jsonl",
        selected_kc_context_rows=contexts,
        guidance_lookup={},
        existing_rows=[],
        cfg={
            "enabled": True,
            "max_candidates_per_kc": 8,
            "min_score": 4.8,
            "reject_prompt_like": True,
            "reject_fragmentary": True,
            "reject_reference_like": True,
            "reject_formula_only_without_target_signal": True,
            "source_overlay_promote_source_block_window": True,
            "source_overlay_source_block_window_max_chars": 900,
        },
    )

    assert candidate_rows == []
    assert stats["candidate_rows_added"] == 0
    assert stats["rehydration_queue_count"] == 1
    assert stats["rejected_counts"]["rehydration_required"] == 1


if __name__ == "__main__":
    test_direct_overlay_promotes_fragmentary_source_overlay_row_from_target_bound_source_block()
    test_direct_overlay_does_not_promote_non_source_overlay_rows()
    print("TEST_STEP5X_DIRECT_OVERLAY_SOURCE_WINDOW_REHYDRATION_OK")
