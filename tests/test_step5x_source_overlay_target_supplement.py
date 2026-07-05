from __future__ import annotations

from kc_l.retrieval_gate.evidence_stage_v3_candidate_bank import (
    SOURCE_OVERLAY_TARGET_SUPPLEMENT,
    _build_direct_overlay_supplement_candidates,
    _build_source_overlay_target_supplement_rows,
    _source_overlay_target_phrase_index,
)


def test_source_overlay_target_supplement_is_generic_and_target_bound() -> None:
    contexts = [
        {
            "kc_id": "KC_SYNTH_001",
            "canonical_name": "Omega Score",
            "aliases": [],
            "topic_path_labels": ["Synthetic Topic"],
            "parent_topic_label": "Synthetic Topic",
        },
        {
            "kc_id": "KC_SYNTH_002",
            "canonical_name": "General Method",
            "aliases": [],
            "topic_path_labels": ["Synthetic Topic"],
            "parent_topic_label": "Synthetic Topic",
        },
    ]
    sentence_rows = [
        {
            "doc_id": "DOC_SYNTH",
            "sentence_id": "s1",
            "block_id": "b1",
            "patch_id": "p1",
            "sentence_text": "The Omega Score is a measure used to compare two system outputs.",
            "source_block_text": "The Omega Score is a measure used to compare two system outputs.",
        },
        {
            "doc_id": "DOC_SYNTH",
            "sentence_id": "s2",
            "block_id": "b2",
            "patch_id": "p2",
            "sentence_text": "References for Omega Score are listed in the bibliography.",
            "source_block_text": "References for Omega Score are listed in the bibliography.",
        },
    ]
    cfg = {
        "enabled": True,
        "generate_from_source_overlay": True,
        "max_candidates_per_kc": 8,
        "source_overlay_min_scan_score": 5.8,
        "source_overlay_dynamic_broad_phrase_kc_fraction": 0.25,
    }

    rows, stats = _build_source_overlay_target_supplement_rows(
        sentence_rows=sentence_rows,
        selected_kc_context_rows=contexts,
        guidance_lookup={},
        cfg=cfg,
    )

    assert stats["enabled"] is True
    assert stats["domain_specific_logic"] is False
    assert stats["model_specific_logic"] is False
    assert len(rows) == 1
    assert rows[0]["kc_id"] == "KC_SYNTH_001"
    assert rows[0]["candidate_source"] == SOURCE_OVERLAY_TARGET_SUPPLEMENT
    assert "Omega Score" in rows[0]["target_signals"]
    assert "bibliography" not in rows[0]["sentence_text"].lower()


def test_source_overlay_phrase_index_rejects_shared_broad_single_token() -> None:
    contexts = [
        {"kc_id": "KC_SYNTH_A", "canonical_name": "Shared", "aliases": ["shared"]},
        {"kc_id": "KC_SYNTH_B", "canonical_name": "Shared", "aliases": ["shared"]},
        {"kc_id": "KC_SYNTH_C", "canonical_name": "Zeta Ratio", "aliases": []},
    ]
    cfg = {
        "source_overlay_dynamic_broad_phrase_kc_fraction": 0.25,
        "source_overlay_min_single_token_len": 5,
        "source_overlay_allow_uppercase_acronym": True,
    }

    phrase_index = _source_overlay_target_phrase_index(contexts, {}, cfg)

    assert "shared" not in {p.lower() for p in phrase_index["KC_SYNTH_A"]}
    assert "Zeta Ratio" in phrase_index["KC_SYNTH_C"]


def test_source_overlay_phrase_index_preserves_specific_uppercase_acronym() -> None:
    contexts = [
        {"kc_id": "KC_SYNTH_ACR_A", "canonical_name": "Alpha Beta Construct (ABC)", "aliases": ["ABC"]},
        {"kc_id": "KC_SYNTH_ACR_B", "canonical_name": "Another Base Construct (ABC)", "aliases": ["ABC"]},
        {"kc_id": "KC_SYNTH_SHARED_A", "canonical_name": "Shared", "aliases": ["shared"]},
        {"kc_id": "KC_SYNTH_SHARED_B", "canonical_name": "Shared", "aliases": ["shared"]},
        {"kc_id": "KC_SYNTH_C", "canonical_name": "Zeta Ratio", "aliases": []},
    ]
    cfg = {
        "source_overlay_dynamic_broad_phrase_kc_fraction": 0.25,
        "source_overlay_min_single_token_len": 5,
        "source_overlay_allow_uppercase_acronym": True,
    }

    phrase_index = _source_overlay_target_phrase_index(contexts, {}, cfg)

    assert "ABC" in phrase_index["KC_SYNTH_ACR_A"]
    assert "ABC" in phrase_index["KC_SYNTH_ACR_B"]
    assert "shared" not in {p.lower() for p in phrase_index["KC_SYNTH_SHARED_A"]}
    assert "Zeta Ratio" in phrase_index["KC_SYNTH_C"]





def test_source_overlay_source_block_window_rehydrates_fragmentary_sentence() -> None:
    contexts = [
        {
            "kc_id": "KC_SYNTH_WINDOW",
            "canonical_name": "Omega Score",
            "aliases": [],
            "topic_path_labels": ["Synthetic Topic"],
            "parent_topic_label": "Synthetic Topic",
        }
    ]
    sentence_rows = [
        {
            "doc_id": "DOC_SYNTH",
            "sentence_id": "s_fragment",
            "block_id": "b_window",
            "patch_id": "p_window",
            "sentence_text": "is useful.",
            "source_block_text": "The Omega Score is a measure used to compare two system outputs.",
        }
    ]

    supplement_rows, supplement_stats = _build_source_overlay_target_supplement_rows(
        sentence_rows=sentence_rows,
        selected_kc_context_rows=contexts,
        guidance_lookup={},
        cfg={
            "enabled": True,
            "generate_from_source_overlay": True,
            "max_candidates_per_kc": 8,
            "source_overlay_min_scan_score": 5.8,
            "source_overlay_dynamic_broad_phrase_kc_fraction": 0.25,
            "source_overlay_promote_source_block_window": True,
            "source_overlay_source_block_window_max_chars": 900,
        },
    )

    assert supplement_stats["supplement_rows_added"] == 1
    assert supplement_rows[0]["candidate_source"] == SOURCE_OVERLAY_TARGET_SUPPLEMENT
    assert supplement_rows[0]["sentence_text"] == "The Omega Score is a measure used to compare two system outputs."
    assert supplement_rows[0]["source_window_promotion"]["promoted"] is True

    candidate_rows, direct_stats = _build_direct_overlay_supplement_candidates(
        run_id="test_source_window",
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

    assert direct_stats["candidate_rows_added"] == 1
    assert len(candidate_rows) == 1
    assert candidate_rows[0]["kc_id"] == "KC_SYNTH_WINDOW"
    candidate_text = (
        candidate_rows[0].get("sentence_text")
        or candidate_rows[0].get("candidate_text")
        or candidate_rows[0].get("text")
        or candidate_rows[0].get("quote")
        or ""
    )
    assert candidate_text == "The Omega Score is a measure used to compare two system outputs."
    assert candidate_rows[0]["support_profile"]["source_overlay_source_block_window"] is True
    assert candidate_rows[0]["provenance"]["source_overlay_source_block_window"] is True

if __name__ == "__main__":
    test_source_overlay_target_supplement_is_generic_and_target_bound()
    test_source_overlay_phrase_index_rejects_shared_broad_single_token()
    test_source_overlay_phrase_index_preserves_specific_uppercase_acronym()
    test_source_overlay_source_block_window_rehydrates_fragmentary_sentence()
    print("TEST_STEP5X_SOURCE_OVERLAY_TARGET_SUPPLEMENT_OK")
