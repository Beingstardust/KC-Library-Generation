from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from kc_l.retrieval_gate.evidence_stage_v3_candidate_bank import run_candidate_bank_stage


TEST_ROOT = REPO_ROOT / ".codex_tmp_test_step5x_profile_guided_candidate_bank"


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _sentence_row(
    text: str,
    *,
    heading: str = "Classification Underpinnings",
    sentence_id: str = "DOC_TEST:block_1::s000",
) -> dict[str, object]:
    return {
        "sentence_text": text,
        "source_block_text": text,
        "doc_id": "DOC_TEST",
        "page_index": 1,
        "block_id": "DOC_TEST:block_1",
        "sentence_id": sentence_id,
        "sent_idx": 0,
        "patch_id": "patch-1",
        "patch_heading": heading,
        "reveal_group_id": "group-1",
        "layer": "mineru",
        "bbox": [1.0, 2.0, 3.0, 4.0],
        "char_start": 0,
        "char_end": len(text),
        "is_meta": False,
        "is_nav_boilerplate": False,
        "is_author_affiliation": False,
        "is_transition_text": False,
        "is_heading_like": False,
        "is_formula_like": False,
        "is_definition_like": True,
        "is_procedure_like": True,
        "is_example_like": False,
    }


def _profile_row() -> dict[str, object]:
    return {
        "kc_id": "KC_A",
        "canonical_name": "Target Phase",
        "profile_status": "usable",
        "query_variants": [
            {
                "query": "learning algorithm",
                "active": True,
                "source": "accepted_source_cue",
                "cue_type": "definition_phrase",
                "retrieval_role": "lexical_query",
                "retrieval_channels": ["lexical"],
                "step5x_eligible": True,
                "provenance": [{"snippet_id": "S_PROFILE", "field_path": "sentence_text"}],
            },
            {
                "query": "learning process with training examples",
                "active": True,
                "source": "accepted_source_cue",
                "cue_type": "process_phrase",
                "retrieval_role": "semantic_query",
                "retrieval_channels": ["semantic"],
                "step5x_eligible": True,
                "provenance": [{"snippet_id": "S_PROFILE", "field_path": "sentence_text"}],
            },
            {
                "query": "target",
                "active": True,
                "source": "deterministic_label_variant",
                "variant_type": "generic_suffix_stripped",
                "retrieval_role": "profile_only_query",
                "retrieval_channels": [],
                "step5x_eligible": False,
                "risk_flags": ["generic_suffix_stripped_broad_risk"],
            },
        ],
        "accepted_source_cues": [
            {
                "term": "learning algorithm",
                "active": True,
                "cue_type": "definition_phrase",
                "provenance": [{"snippet_id": "S_PROFILE", "field_path": "sentence_text"}],
            }
        ],
        "expected_evidence_shape_hints": [
            {"shape": "definition_phrase", "shape_family": "definition", "source": "accepted_source_cue", "confidence": "medium"}
        ],
        "rejected_candidates": [{"term": "wrong sibling phrase", "reason": "wrong_sense"}],
        "audit": {
            "profile_input_status": "exploratory_only",
            "exploratory_profile_windows": [
                {"snippet_id": "S_PROFILE", "text": "window text must not be emitted as evidence"}
            ],
        },
    }


def test_profile_guided_candidate_bank_uses_eligible_lexical_profile_query_without_treating_windows_as_evidence() -> None:
    root = TEST_ROOT
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    try:
        registry_path = root / "data" / "work" / "cache" / "current_step_artifacts" / "step1_seedless_hierarchy_registry.current.jsonl"
        _write_jsonl(
            registry_path,
            [
                {
                    "kc_id": "KC_A",
                    "canonical_name": "Target Phase",
                    "aliases": [],
                    "kc_path": ["Classification", "Classification Underpinnings", "Target Phase"],
                }
            ],
        )

        sentence_corpus = root / "sentence_corpus.jsonl"
        _write_jsonl(
            sentence_corpus,
            [
                _sentence_row(
                    "A learning algorithm is the systematic method used to build a classification model from training data.",
                    sentence_id="S_PROFILE",
                )
            ],
        )

        step5_jsonl = root / "step5_3_candidates.jsonl"
        _write_jsonl(step5_jsonl, [{"kc_id": "KC_A", "canonical_name": "Target Phase", "evidence": []}])

        profile_jsonl = root / "profiles.jsonl"
        _write_jsonl(profile_jsonl, [_profile_row()])

        step5_manifest = root / "step5_3_set.json"
        step5_manifest.write_text(
            json.dumps(
                {
                    "artifacts": {
                        "kc_evidence_candidates_recalibrated_jsonl": str(step5_jsonl),
                    },
                    "upstream": {
                        "step4_5_sentence_corpus_jsonl": str(sentence_corpus),
                    },
                }
            ),
            encoding="utf-8",
        )

        output_root = root / "out"
        sets_root = output_root / "_sets"

        result = run_candidate_bank_stage(
            run_id="profile_guided",
            step5_3_set_manifest_spec=str(step5_manifest),
            step5_3_candidates_jsonl_spec=None,
            profile_jsonl_spec=str(profile_jsonl),
            config_path="tests://profile_guided",
            exact_kc_ids=["KC_A"],
            limit_kcs=1,
            output_root=output_root,
            set_manifest_root=sets_root,
            allow_reference_artifact_inputs=True,
            fail_if_no_candidate_source=True,
            exclude_seed_fields=True,
            preserve_raw_support_profile=True,
            preserve_raw_alignment_breakdown=True,
            source_surface_fallback_cfg={"enabled": True, "dynamic_broad_token_min_doc_frequency": 2},
            repo_root=root,
        )

        candidate_bank_path = output_root / "profile_guided" / "candidate_bank.jsonl"
        controls_path = output_root / "profile_guided" / "profile_guidance_controls.json"
        stats_path = output_root / "profile_guided" / "candidate_bank_stats.json"

        rows = [json.loads(line) for line in candidate_bank_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        controls = json.loads(controls_path.read_text(encoding="utf-8"))
        stats = json.loads(stats_path.read_text(encoding="utf-8"))

        assert result["total_candidate_rows_emitted"] == 1
        assert len(rows) == 1
        row = rows[0]

        assert row["source_surface"] == "profile_provenance_rehydration"
        assert row["candidate_source"] == "profile_provenance_rehydration"
        assert "learning algorithm" in row["aliases"]
        assert row["step5p_profile_guidance"]["safe_to_use_for_step5x"] is True
        assert row["step5p_profile_guidance"]["lexical_query_count"] == 1
        assert row["step5p_profile_guidance"]["semantic_query_count"] == 1
        assert row["provenance"]["step5p_profile_guidance_role"] == "retrieval_control_metadata_not_evidence"

        row_json = json.dumps(row, ensure_ascii=False)
        assert "window text must not be emitted as evidence" not in row_json

        assert controls["KC_A"]["lexical_queries"][0]["query"] == "learning algorithm"
        assert controls["KC_A"]["semantic_queries"][0]["query"] == "learning process with training examples"
        assert controls["KC_A"]["profile_only_queries"][0]["query"] == "target"
        assert controls["KC_A"]["negative_constraints"][0]["term"] == "wrong sibling phrase"
        assert stats["step5p_profile_guidance"]["profile_available_count"] == 1
        assert stats["step5p_profile_guidance"]["safe_profile_count"] == 1
    finally:
        if root.exists():
            shutil.rmtree(root)


def test_profile_source_window_ids_rehydrate_actual_sentence_rows_without_window_text_leakage() -> None:
    root = TEST_ROOT
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    try:
        registry_path = root / "data" / "work" / "cache" / "current_step_artifacts" / "step1_seedless_hierarchy_registry.current.jsonl"
        _write_jsonl(
            registry_path,
            [
                {
                    "kc_id": "KC_A",
                    "canonical_name": "Querying Phase",
                    "aliases": [],
                    "kc_path": ["Classification", "Classification Underpinnings", "Querying Phase"],
                }
            ],
        )

        sentence_corpus = root / "sentence_corpus.jsonl"
        row = _sentence_row(
            "A classification model can be used to predict the class label of previously unseen test instances.",
            heading="3.2 General Framework for Classification",
        )
        row["sentence_id"] = "S_PROFILE"
        row["patch_id"] = "patch-profile"
        row["is_definition_like"] = False
        row["is_procedure_like"] = True
        _write_jsonl(sentence_corpus, [row])

        step5_jsonl = root / "step5_3_candidates.jsonl"
        _write_jsonl(step5_jsonl, [{"kc_id": "KC_A", "canonical_name": "Querying Phase", "evidence": []}])

        profile = {
            "kc_id": "KC_A",
            "canonical_name": "Querying Phase",
            "profile_status": "usable",
            "query_variants": [
                {
                    "query": "Querying Phase",
                    "active": True,
                    "source": "deterministic_label_variant",
                    "retrieval_role": "lexical_query",
                    "retrieval_channels": ["lexical"],
                    "step5x_eligible": True,
                }
            ],
            "accepted_source_cues": [
                {
                    "term": "classification model predicts class labels for unseen test instances",
                    "active": True,
                    "cue_type": "process_phrase",
                    "provenance": [{"snippet_id": "S_PROFILE", "field_path": "sentence_text"}],
                }
            ],
            "audit": {
                "profile_input_status": "topic_local_content_scout",
                "exploratory_profile_windows": [
                    {
                        "snippet_id": "S_PROFILE",
                        "text": "THIS PROFILE WINDOW TEXT MUST NOT BECOME CANDIDATE EVIDENCE",
                    }
                ],
            },
        }
        profile_jsonl = root / "profiles.jsonl"
        _write_jsonl(profile_jsonl, [profile])

        step5_manifest = root / "step5_3_set.json"
        step5_manifest.write_text(
            json.dumps(
                {
                    "artifacts": {
                        "kc_evidence_candidates_recalibrated_jsonl": str(step5_jsonl),
                    },
                    "upstream": {
                        "step4_5_sentence_corpus_jsonl": str(sentence_corpus),
                    },
                }
            ),
            encoding="utf-8",
        )

        output_root = root / "out_source_window"
        sets_root = output_root / "_sets"

        result = run_candidate_bank_stage(
            run_id="profile_source_window",
            step5_3_set_manifest_spec=None,
            step5_3_candidates_jsonl_spec=None,
            registry_jsonl_spec=str(registry_path),
            source_overlay_jsonl_spec=str(sentence_corpus),
            profile_jsonl_spec=str(profile_jsonl),
            config_path="tests://profile_source_window",
            exact_kc_ids=["KC_A"],
            limit_kcs=1,
            output_root=output_root,
            set_manifest_root=sets_root,
            allow_reference_artifact_inputs=True,
            fail_if_no_candidate_source=True,
            exclude_seed_fields=True,
            preserve_raw_support_profile=True,
            preserve_raw_alignment_breakdown=True,
            source_surface_fallback_cfg={"enabled": True, "dynamic_broad_token_min_doc_frequency": 2},
            repo_root=root,
        )

        candidate_bank_path = output_root / "profile_source_window" / "candidate_bank.jsonl"
        stats_path = output_root / "profile_source_window" / "candidate_bank_stats.json"
        rows = [json.loads(line) for line in candidate_bank_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        stats = json.loads(stats_path.read_text(encoding="utf-8"))

        assert result["total_candidate_rows_emitted"] >= 1
        assert len(rows) >= 1
        row = rows[0]
        assert row["text"] == "A classification model can be used to predict the class label of previously unseen test instances."
        assert row["provenance"]["from_step"] == "step4_5_sentence_overlay"
        assert row["candidate_source"] == "structural_anchor_from_profile_or_label"
        assert row["support_profile"]["fallback_reason"] == "step5p_source_window_rehydration"
        assert "step5p_source_window_rehydrated" in row["support_profile"]["fallback_score_reasons"]
        assert row["provenance"]["step5p_profile_guidance_used"] is True
        assert row["provenance"]["step5p_profile_guidance_role"] == "retrieval_control_metadata_not_evidence"
        assert stats["structural_anchor_expansion"]["source_window_anchor_rows_added_by_kc"]["KC_A"] >= 1

        serialized = json.dumps(rows, ensure_ascii=False)
        assert "THIS PROFILE WINDOW TEXT MUST NOT BECOME CANDIDATE EVIDENCE" not in serialized
    finally:
        if root.exists():
            shutil.rmtree(root)


def main() -> None:
    test_profile_guided_candidate_bank_uses_eligible_lexical_profile_query_without_treating_windows_as_evidence()
    test_profile_source_window_ids_rehydrate_actual_sentence_rows_without_window_text_leakage()
    print("TEST_STEP5X_PROFILE_GUIDED_CANDIDATE_BANK_OK")


if __name__ == "__main__":
    main()
