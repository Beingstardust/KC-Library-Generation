from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_SRC = REPO_ROOT / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from kc_l.retrieval_gate.evidence_stage_v3_candidate_bank import (
    INPUT_MODE_CLEAN_SLATE,
    REGISTRY_SOURCE_SEEDLESS,
    SOURCE_SURFACE_FALLBACK,
    STRUCTURAL_NEIGHBOR_REASON,
    run_candidate_bank_stage,
)


TEST_ROOT = REPO_ROOT / ".codex_tmp_test_step5x_clean_slate_candidate_bank"


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _sentence_row(
    text: str,
    *,
    heading: str = "Composition Techniques",
    sentence_id: str = "DOC_MUSIC:block_1::s000",
    block_id: str = "DOC_MUSIC:block_1",
    patch_id: str = "patch-1",
    reveal_group_id: str = "group-1",
    sent_idx: int = 0,
    page_index: int = 4,
    flags: dict[str, object] | None = None,
) -> dict[str, object]:
    row = {
        "sentence_text": text,
        "source_block_text": text,
        "doc_id": "DOC_MUSIC",
        "page_index": page_index,
        "block_id": block_id,
        "sentence_id": sentence_id,
        "sent_idx": sent_idx,
        "patch_id": patch_id,
        "patch_heading": heading,
        "reveal_group_id": reveal_group_id,
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
    row.update(dict(flags or {}))
    return row


def _profile_row() -> dict[str, object]:
    return {
        "kc_id": "KC_MUS_001",
        "canonical_name": "Theme Development",
        "profile_status": "usable",
        "query_variants": [
            {
                "query": "short musical idea",
                "active": True,
                "source": "accepted_source_cue",
                "cue_type": "definition_phrase",
                "retrieval_role": "lexical_query",
                "retrieval_channels": ["lexical"],
                "step5x_eligible": True,
                "provenance": [{"snippet_id": "S_PROFILE", "field_path": "sentence_text"}],
            },
            {
                "query": "transforming a motif across a piece",
                "active": True,
                "source": "accepted_source_cue",
                "cue_type": "process_phrase",
                "retrieval_role": "semantic_query",
                "retrieval_channels": ["semantic"],
                "step5x_eligible": True,
                "provenance": [{"snippet_id": "S_PROFILE", "field_path": "sentence_text"}],
            },
            {
                "query": "development",
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
                "term": "short musical idea",
                "active": True,
                "cue_type": "definition_phrase",
                "provenance": [{"snippet_id": "S_PROFILE", "field_path": "sentence_text"}],
            }
        ],
        "expected_evidence_shape_hints": [
            {
                "shape": "definition_phrase",
                "shape_family": "definition",
                "source": "accepted_source_cue",
                "confidence": "medium",
            }
        ],
        "rejected_candidates": [{"term": "harmonic cadence", "reason": "wrong_sense"}],
        "audit": {
            "profile_input_status": "exploratory_only",
            "exploratory_profile_windows": [
                {"snippet_id": "S_PROFILE", "text": "PROFILE WINDOW TEXT MUST NOT LEAK"}
            ],
        },
    }


def _metric_profile_row() -> dict[str, object]:
    return {
        "kc_id": "KC_MUS_002",
        "canonical_name": "Interval Ratio",
        "profile_status": "usable",
        "query_variants": [
            {
                "query": "interval ratio",
                "active": True,
                "source": "accepted_source_cue",
                "cue_type": "definition_phrase",
                "retrieval_role": "lexical_query",
                "retrieval_channels": ["lexical"],
                "step5x_eligible": True,
                "provenance": [{"snippet_id": "S_INTERVAL", "field_path": "sentence_text"}],
            },
            {
                "query": "consonant balance relation",
                "active": True,
                "source": "accepted_source_cue",
                "cue_type": "metric_phrase",
                "retrieval_role": "semantic_query",
                "retrieval_channels": ["semantic"],
                "step5x_eligible": True,
                "provenance": [{"snippet_id": "S_INTERVAL", "field_path": "sentence_text"}],
            },
        ],
        "accepted_source_cues": [
            {
                "term": "interval ratio",
                "active": True,
                "cue_type": "definition_phrase",
                "provenance": [{"snippet_id": "S_INTERVAL", "field_path": "sentence_text"}],
            }
        ],
        "expected_evidence_shape_hints": [
            {"shape": "formula_relation", "shape_family": "formula", "source": "accepted_source_cue", "confidence": "high"},
            {"shape": "metric_relation", "shape_family": "metric", "source": "accepted_source_cue", "confidence": "high"},
            {"shape": "definition_phrase", "shape_family": "definition", "source": "accepted_source_cue", "confidence": "medium"},
        ],
        "rejected_candidates": [{"term": "publisher address", "reason": "bibliographic_noise"}],
        "audit": {
            "profile_input_status": "exploratory_only",
            "exploratory_profile_windows": [
                {"snippet_id": "S_INTERVAL", "text": "PROFILE WINDOW TEXT MUST NOT LEAK"}
            ],
        },
    }


def test_clean_slate_mode_runs_without_step53_and_consumes_profile_guidance_as_control_metadata() -> None:
    root = TEST_ROOT
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    try:
        registry_jsonl = root / "seedless_registry.jsonl"
        source_overlay_jsonl = root / "sentence_overlay.jsonl"
        profile_jsonl = root / "profiles.jsonl"
        output_root = root / "out"
        set_manifest_root = output_root / "_sets"

        _write_jsonl(
            registry_jsonl,
            [
                {
                    "kc_id": "KC_MUS_001",
                    "canonical_name": "Theme Development",
                    "aliases": [],
                    "topic_path_labels": ["Music Theory", "Composition Techniques"],
                    "topic_path_ids": ["topic_music_theory", "topic_composition_techniques"],
                    "parent_topic_id": "topic_composition_techniques",
                    "parent_topic_label": "Composition Techniques",
                    "sibling_labels": ["Cadence Analysis"],
                    "seed_definition": "must not leak",
                    "seed_floor": {"status": "legacy_floor"},
                }
            ],
        )
        _write_jsonl(
            source_overlay_jsonl,
            [
                _sentence_row(
                    "A short musical idea is repeated and inverted to shape a larger composition."
                )
            ],
        )
        _write_jsonl(profile_jsonl, [_profile_row()])

        result = run_candidate_bank_stage(
            run_id="clean_slate_profile_guided",
            step5_3_set_manifest_spec=None,
            step5_3_candidates_jsonl_spec=None,
            registry_jsonl_spec=str(registry_jsonl),
            source_overlay_jsonl_spec=str(source_overlay_jsonl),
            profile_jsonl_spec=str(profile_jsonl),
            config_path="tests://clean_slate_profile_guided",
            exact_kc_ids=["KC_MUS_001"],
            limit_kcs=1,
            output_root=output_root,
            set_manifest_root=set_manifest_root,
            allow_reference_artifact_inputs=True,
            fail_if_no_candidate_source=True,
            exclude_seed_fields=True,
            preserve_raw_support_profile=True,
            preserve_raw_alignment_breakdown=True,
            source_surface_fallback_cfg={"enabled": False, "dynamic_broad_token_min_doc_frequency": 2},
            repo_root=root,
        )

        candidate_bank_path = output_root / "clean_slate_profile_guided" / "candidate_bank.jsonl"
        stats_path = output_root / "clean_slate_profile_guided" / "candidate_bank_stats.json"
        controls_path = output_root / "clean_slate_profile_guided" / "profile_guidance_controls.json"
        manifest_path = output_root / "clean_slate_profile_guided" / "candidate_bank_manifest.json"

        rows = [json.loads(line) for line in candidate_bank_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        stats = json.loads(stats_path.read_text(encoding="utf-8"))
        controls = json.loads(controls_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        assert result["total_candidate_rows_emitted"] == 1
        assert len(rows) == 1
        row = rows[0]

        assert row["source_surface"] == SOURCE_SURFACE_FALLBACK
        assert row["candidate_source"] == SOURCE_SURFACE_FALLBACK
        assert row["knowledge_unit_type"] == "kc"
        assert row["query_plan_id"]
        assert row["retrieval_intent"] in {"head_term_plus_definition_frame", "label_exact_surface", "label_normalized_surface"}
        assert row["candidate_origin"] == row["retrieval_intent"]
        assert row["authority_contract"] == "step5x_must_verify_against_source_rows"
        assert row["step5x_retrieval_policy_plan"]["profile_output_role"] == "retrieval_control_metadata_not_evidence"
        assert "short musical idea" in row["aliases"]
        assert "transforming a motif across a piece" not in row["aliases"]
        assert "development" not in row["aliases"]
        assert row["provenance"]["input_mode"] == INPUT_MODE_CLEAN_SLATE
        assert row["provenance"]["registry_source"] == REGISTRY_SOURCE_SEEDLESS
        assert row["provenance"]["step5p_profile_guidance_used"] is True
        assert row["provenance"]["step5p_profile_guidance_role"] == "retrieval_control_metadata_not_evidence"

        row_json = json.dumps(row, ensure_ascii=False)
        assert "PROFILE WINDOW TEXT MUST NOT LEAK" not in row_json
        assert "seed_definition" not in row_json
        assert "seed_floor" not in row_json

        assert stats["input_mode"] == INPUT_MODE_CLEAN_SLATE
        assert stats["registry_jsonl"].endswith("seedless_registry.jsonl")
        assert stats["source_overlay_jsonl"].endswith("sentence_overlay.jsonl")
        assert stats["source_surface_fallback"]["requested_enabled"] is False
        assert stats["source_surface_fallback"]["forced_for_clean_slate"] is True
        assert stats["step5p_profile_guidance"]["profile_available_count"] == 1
        assert stats["step5p_profile_guidance"]["safe_profile_count"] == 1
        assert stats["retrieval_policy"]["authority_contract"] == "step5x_must_verify_against_source_rows"
        assert stats["retrieval_policy"]["knowledge_unit_type_breakdown"]["kc"] == 1

        assert controls["KC_MUS_001"]["lexical_queries"][0]["query"] == "short musical idea"
        assert controls["KC_MUS_001"]["semantic_queries"][0]["query"] == "transforming a motif across a piece"
        assert controls["KC_MUS_001"]["profile_only_queries"][0]["query"] == "development"
        assert controls["KC_MUS_001"]["negative_constraints"][0]["term"] == "harmonic cadence"

        assert manifest["inputs"]["mode"] == INPUT_MODE_CLEAN_SLATE
        assert manifest["inputs"]["step5_3_set_manifest"] == ""
        assert manifest["inputs"]["registry_jsonl"].endswith("seedless_registry.jsonl")
        assert manifest["inputs"]["source_overlay_jsonl"].endswith("sentence_overlay.jsonl")
        assert manifest["artifacts"]["retrieval_policy_plans_json"].endswith("retrieval_policy_plans.json")
    finally:
        if root.exists():
            shutil.rmtree(root)


def test_structural_neighbor_expansion_recovers_formula_and_definition_neighbors_without_unsafe_rows() -> None:
    root = TEST_ROOT
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    try:
        registry_jsonl = root / "seedless_registry.jsonl"
        source_overlay_jsonl = root / "sentence_overlay.jsonl"
        profile_jsonl = root / "profiles.jsonl"
        output_root = root / "out"
        set_manifest_root = output_root / "_sets"

        _write_jsonl(
            registry_jsonl,
            [
                {
                    "kc_id": "KC_MUS_002",
                    "canonical_name": "Interval Ratio",
                    "aliases": [],
                    "topic_path_labels": ["Music Theory", "Composition Techniques"],
                    "topic_path_ids": ["topic_music_theory", "topic_composition_techniques"],
                    "parent_topic_id": "topic_composition_techniques",
                    "parent_topic_label": "Composition Techniques",
                }
            ],
        )
        _write_jsonl(
            source_overlay_jsonl,
            [
                _sentence_row(
                    "The interval ratio summarizes consonant balance in the passage.",
                    heading="Interval Ratio",
                    sentence_id="DOC_MUSIC:block_1::s000",
                    sent_idx=0,
                    patch_id="patch-interval",
                    reveal_group_id="group-interval",
                    flags={"is_definition_like": False, "is_procedure_like": False},
                ),
                _sentence_row(
                    "IR = 2 * consonant_intervals / total_intervals.",
                    heading="Interval Ratio",
                    sentence_id="DOC_MUSIC:block_1::s001",
                    sent_idx=1,
                    patch_id="patch-interval",
                    reveal_group_id="group-interval",
                    flags={"is_definition_like": False, "is_procedure_like": False, "is_formula_like": True},
                ),
                _sentence_row(
                    "It is the proportion of consonant intervals to total intervals.",
                    heading="Interval Ratio",
                    sentence_id="DOC_MUSIC:block_1::s002",
                    sent_idx=2,
                    patch_id="patch-interval",
                    reveal_group_id="group-interval",
                    flags={"is_definition_like": True, "is_procedure_like": False, "is_formula_like": False},
                ),
                _sentence_row(
                    "Department of Harmonic Studies, Example University.",
                    heading="Interval Ratio",
                    sentence_id="DOC_MUSIC:block_1::s003",
                    sent_idx=3,
                    patch_id="patch-interval",
                    reveal_group_id="group-interval",
                    flags={"is_author_affiliation": True, "is_definition_like": True, "is_procedure_like": False},
                ),
            ],
        )
        _write_jsonl(profile_jsonl, [_metric_profile_row()])

        run_candidate_bank_stage(
            run_id="clean_slate_structural_neighbors",
            step5_3_set_manifest_spec=None,
            step5_3_candidates_jsonl_spec=None,
            registry_jsonl_spec=str(registry_jsonl),
            source_overlay_jsonl_spec=str(source_overlay_jsonl),
            profile_jsonl_spec=str(profile_jsonl),
            config_path="tests://clean_slate_structural_neighbors",
            exact_kc_ids=["KC_MUS_002"],
            limit_kcs=1,
            output_root=output_root,
            set_manifest_root=set_manifest_root,
            allow_reference_artifact_inputs=True,
            fail_if_no_candidate_source=True,
            exclude_seed_fields=True,
            preserve_raw_support_profile=True,
            preserve_raw_alignment_breakdown=True,
            source_surface_fallback_cfg={"enabled": False, "dynamic_broad_token_min_doc_frequency": 2},
            repo_root=root,
        )

        candidate_bank_path = output_root / "clean_slate_structural_neighbors" / "candidate_bank.jsonl"
        stats_path = output_root / "clean_slate_structural_neighbors" / "candidate_bank_stats.json"

        rows = [json.loads(line) for line in candidate_bank_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        stats = json.loads(stats_path.read_text(encoding="utf-8"))
        texts = {str(row["text"]) for row in rows}

        assert "The interval ratio summarizes consonant balance in the passage." in texts
        assert "IR = 2 * consonant_intervals / total_intervals." in texts
        assert "It is the proportion of consonant intervals to total intervals." in texts
        assert "Department of Harmonic Studies, Example University." not in texts

        formula_row = next(row for row in rows if row["text"] == "IR = 2 * consonant_intervals / total_intervals.")
        assert formula_row["candidate_source"] == STRUCTURAL_NEIGHBOR_REASON
        assert formula_row["retrieval_intent"] == "section_neighbor_expansion"
        assert formula_row["candidate_origin"] == "section_neighbor_expansion"
        assert formula_row["evidence_shape_match"] == "formula_or_metric"
        assert formula_row["query_plan_id"]
        assert formula_row["authority_contract"] == "step5x_must_verify_against_source_rows"
        assert formula_row["provenance"]["anchor_sentence_id"] == "DOC_MUSIC:block_1::s000"
        assert formula_row["provenance"]["source_jsonl"].endswith("sentence_overlay.jsonl")
        assert formula_row["support_profile"]["shape_hint_formula_or_metric"] is True
        assert float(formula_row["support_profile"]["formula_support_score"]) > 1.0

        rendered = json.dumps(rows, ensure_ascii=False)
        assert "PROFILE WINDOW TEXT MUST NOT LEAK" not in rendered
        assert stats["input_mode"] == INPUT_MODE_CLEAN_SLATE
        assert stats["structural_anchor_expansion"]["neighbor_rows_added_by_kc"]["KC_MUS_002"] >= 2
    finally:
        if root.exists():
            shutil.rmtree(root)


def test_section_neighbor_expansion_recovers_adjacent_target_bound_sentence() -> None:
    test_structural_neighbor_expansion_recovers_formula_and_definition_neighbors_without_unsafe_rows()


def test_context_only_route_can_create_region_candidates_but_not_alias_queries() -> None:
    profile = _profile_row()
    profile["retrieval_routes"] = [
        {
            "route_id": "context_route",
            "route_type": "context_locator",
            "activation": "context_only",
            "primary_terms_any": ["broad neutral section phrase"],
            "can_create_candidates": True,
            "can_create_positive_support": False,
        }
    ]
    profile["query_variants"] = []
    from kc_l.retrieval_gate.profile_guidance import (
        alias_safe_terms_for_candidate_generation,
        guidance_from_profile,
        region_locator_terms_for_candidate_generation,
    )

    guidance = guidance_from_profile(profile)

    assert alias_safe_terms_for_candidate_generation(guidance) == []
    assert "broad neutral section phrase" in region_locator_terms_for_candidate_generation(guidance)


def main() -> None:
    test_clean_slate_mode_runs_without_step53_and_consumes_profile_guidance_as_control_metadata()
    test_structural_neighbor_expansion_recovers_formula_and_definition_neighbors_without_unsafe_rows()
    print("TEST_STEP5X_CLEAN_SLATE_CANDIDATE_BANK_OK")


if __name__ == "__main__":
    main()
