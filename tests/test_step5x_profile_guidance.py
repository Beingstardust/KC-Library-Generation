from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

TEST_ROOT = REPO_ROOT / ".codex_tmp_test_step5x_profile_guidance"

from kc_l.retrieval_gate.profile_guidance import (
    PROFILE_OUTPUT_ROLE,
    alias_safe_terms_for_candidate_generation,
    guidance_from_profile,
    guidance_to_candidate_bank_controls,
    lexical_aliases_for_candidate_generation,
    load_profile_guidance,
    region_locator_terms_for_candidate_generation,
)


def sample_profile() -> dict[str, object]:
    return {
        "kc_id": "KC_TEST_001",
        "canonical_name": "Zero-Frequency Problem",
        "profile_status": "usable",
        "accepted_source_cues": [
            {
                "term": "zero conditional probability",
                "cue_type": "mechanism_description",
                "active": True,
                "provenance": [{"snippet_id": "s1", "field_path": "sentence_text"}],
            }
        ],
        "query_variants": [
            {
                "query": "Zero-Frequency Problem",
                "active": True,
                "source": "deterministic_label_variant",
                "variant_type": "exact_label",
                "retrieval_role": "lexical_query",
                "retrieval_channels": ["lexical"],
                "step5x_eligible": True,
            },
            {
                "query": "zero frequency",
                "active": True,
                "source": "deterministic_label_variant",
                "variant_type": "generic_suffix_stripped",
                "retrieval_role": "profile_only_query",
                "retrieval_channels": [],
                "risk_flags": ["generic_suffix_stripped_broad_risk"],
                "step5x_eligible": False,
            },
            {
                "query": "a combination of attribute values and class labels are never observed",
                "active": True,
                "source": "accepted_source_cue",
                "cue_type": "mechanism_description",
                "retrieval_role": "semantic_query",
                "retrieval_channels": ["semantic"],
                "risk_flags": ["long_query_semantic_only"],
                "step5x_eligible": True,
                "provenance": [{"snippet_id": "s2", "field_path": "sentence_text"}],
            },
            {
                "query": "inactive hallucinated synonym",
                "active": False,
                "source": "model_suggestion",
                "retrieval_role": "semantic_query",
                "retrieval_channels": ["semantic"],
                "step5x_eligible": True,
            },
        ],
        "expected_evidence_shape_hints": [
            {
                "shape": "mechanism_description",
                "shape_family": "mechanism",
                "source": "accepted_source_cue",
                "confidence": "medium",
                "provenance": [{"snippet_id": "s2", "field_path": "sentence_text"}],
            }
        ],
        "concept_head": "Frequency",
        "qualifiers": ["Zero"],
        "expanded_aliases": ["Zero Frequency Problem"],
        "normalized_surface_variants": ["Zero Frequency Problem", "Zero-Frequency Problem"],
        "expected_evidence_needs": [
            {"need": "definition_concept", "priority": "primary", "source": "label_descriptor"},
            {"need": "boundary_condition", "priority": "secondary", "source": "accepted_source_cue"},
        ],
        "route_specific_query_variants": [
            {"route_id": "route_001", "queries": ["zero conditional probability"]},
        ],
        "route_specific_required_terms": [
            {"route_id": "route_001", "terms": ["class labels"]},
        ],
        "route_specific_optional_terms": [
            {"route_id": "route_001", "terms": ["attribute values"]},
        ],
        "negative_sibling_terms": ["laplace estimator"],
        "risk_hints": ["generic_single_token_broad_risk"],
        "rejected_candidates": [
            {
                "term": "zero impurity value",
                "reason": "wrong_sense",
                "related_snippet_ids": ["bad1"],
            }
        ],
        "quarantined_terms": [
            {
                "term": "unconfirmed smoothing alias",
                "reason": "model_only_unconfirmed",
                "related_snippet_ids": [],
            }
        ],
        "audit": {
            "profile_input_status": "exploratory_only",
            "strict_source_windows": [],
            "exploratory_profile_windows": [
                {
                    "snippet_id": "s1",
                    "text": "this window text must not become evidence",
                    "profile_window_role": "profiler_input_only_not_evidence",
                }
            ],
        },
    }


def test_guidance_separates_query_roles() -> None:
    guidance = guidance_from_profile(sample_profile())

    assert guidance.safe_to_use_for_step5x is True
    assert len(guidance.lexical_queries) == 1
    assert len(guidance.semantic_queries) == 1
    assert len(guidance.profile_only_queries) == 1
    assert guidance.profile_only_queries[0].step5x_eligible is False


def test_controls_do_not_copy_window_text_as_evidence() -> None:
    guidance = guidance_from_profile(sample_profile())
    controls = guidance_to_candidate_bank_controls(guidance)
    serialized = json.dumps(controls, ensure_ascii=False)

    assert "this window text must not become evidence" not in serialized
    assert controls["control_role"] == "step5x_retrieval_control_metadata_not_evidence"
    assert controls["source_window_ids"] == ["s1"]


def test_lexical_aliases_exclude_profile_only_and_semantic_queries() -> None:
    guidance = guidance_from_profile(sample_profile())
    aliases = lexical_aliases_for_candidate_generation(guidance)

    assert aliases == ["zero conditional probability"]


def test_negative_constraints_and_shape_hints_are_soft_controls() -> None:
    controls = guidance_to_candidate_bank_controls(guidance_from_profile(sample_profile()))

    assert controls["negative_constraints"][0]["term"] == "zero impurity value"
    assert controls["negative_constraints"][1]["source"] == "quarantined_term"
    assert controls["evidence_shape_hints"][0]["shape"] == "mechanism_description"
    assert controls["evidence_shape_hints"][0]["profile_output_role"] == PROFILE_OUTPUT_ROLE


def test_load_profile_guidance_jsonl_and_exact_filter() -> None:
    profile = sample_profile()
    other = dict(profile)
    other["kc_id"] = "KC_OTHER"

    if TEST_ROOT.exists():
        shutil.rmtree(TEST_ROOT)
    TEST_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        path = TEST_ROOT / "profiles.jsonl"
        path.write_text(json.dumps(profile) + "\n" + json.dumps(other) + "\n", encoding="utf-8")
        loaded = load_profile_guidance(path, exact_kc_ids=["KC_TEST_001"])
    finally:
        if TEST_ROOT.exists():
            shutil.rmtree(TEST_ROOT)

    assert sorted(loaded) == ["KC_TEST_001"]


def test_reject_profile_is_not_safe_for_step5x() -> None:
    profile = sample_profile()
    profile["profile_status"] = "reject"

    guidance = guidance_from_profile(profile)

    assert guidance.safe_to_use_for_step5x is False
    assert lexical_aliases_for_candidate_generation(guidance) == []


def test_accepted_cue_without_provenance_warns_but_does_not_crash() -> None:
    profile = sample_profile()
    profile["accepted_source_cues"] = [{"term": "unsupported cue", "active": True}]

    guidance = guidance_from_profile(profile)

    assert any(w.startswith("accepted_cue_without_provenance") for w in guidance.warnings)


def test_timeout_fallback_emits_region_locator_not_alias_atom() -> None:
    profile = sample_profile()
    long_locator = (
        "A neutral timeout fallback passage gives broad section context across several "
        "sentences but should not become an alias query term."
    )
    profile["accepted_source_cues"] = [
        {
            "term": long_locator,
            "active": True,
            "cue_type": "context_phrase",
            "provenance": [{"snippet_id": "s-locator", "field_path": "sentence_text"}],
        }
    ]

    guidance = guidance_from_profile(profile)

    assert long_locator in region_locator_terms_for_candidate_generation(guidance)
    assert long_locator not in alias_safe_terms_for_candidate_generation(guidance)
    assert long_locator not in guidance.query_atoms


def test_profile_guidance_contract_still_marks_all_routes_as_non_evidence() -> None:
    controls = guidance_to_candidate_bank_controls(guidance_from_profile(sample_profile()))

    assert controls["control_role"] == "step5x_retrieval_control_metadata_not_evidence"
    assert all(route["profile_output_role"] == PROFILE_OUTPUT_ROLE for route in controls["retrieval_routes"])
    assert all(query["profile_output_role"] == PROFILE_OUTPUT_ROLE for query in controls["lexical_queries"])
    assert all(hint["profile_output_role"] == PROFILE_OUTPUT_ROLE for hint in controls["evidence_shape_hints"])


def test_descriptor_and_head_term_export_is_seedless_and_auditable() -> None:
    profile = sample_profile()
    profile["canonical_name"] = "Lumen Definition"
    profile["query_atoms"] = ["Lumen Definition"]

    guidance = guidance_from_profile(profile)
    controls = guidance_to_candidate_bank_controls(guidance)
    serialized = json.dumps(controls, ensure_ascii=False)

    assert "lumen" in controls["concept_head_terms_any"]
    assert "definition" in controls["label_descriptor_terms_any"]
    assert "Lumen Definition" in controls["query_atoms"]
    assert "seed_definition" not in serialized
    assert "seed_floor" not in serialized


def test_model_only_suggestion_remains_quarantined_without_source_confirmation() -> None:
    profile = {
        "kc_id": "KC_TEST_MODEL_ONLY",
        "canonical_name": "Boundary Drift Problem",
        "profile_status": "usable",
        "query_variants": [
            {
                "query": "unverified model synonym",
                "active": True,
                "source": "model_suggestion",
                "retrieval_role": "lexical_query",
                "retrieval_channels": ["lexical"],
                "step5x_eligible": True,
            }
        ],
        "audit": {"profile_input_status": "exploratory_only"},
    }

    guidance = guidance_from_profile(profile)

    assert "unverified model synonym" not in alias_safe_terms_for_candidate_generation(guidance)
    assert [query.query for query in guidance.profile_only_queries] == ["unverified model synonym"]
    assert any(w.startswith("model_only_query_without_source_confirmation") for w in guidance.warnings)


def test_shapeaware_guidance_fields_are_preserved_in_controls() -> None:
    guidance = guidance_from_profile(sample_profile())
    controls = guidance_to_candidate_bank_controls(guidance)

    assert controls["concept_head"] == "Frequency"
    assert controls["qualifiers"] == ["Zero"]
    assert controls["expanded_aliases"] == ["Zero Frequency Problem"]
    assert "Zero Frequency Problem" in controls["normalized_surface_variants"]
    assert controls["expected_evidence_needs"][0]["need"] == "definition_concept"
    assert controls["route_specific_required_terms"][0]["terms"] == ["class labels"]
    assert controls["route_specific_optional_terms"][0]["terms"] == ["attribute values"]
    assert controls["negative_sibling_terms"] == ["laplace estimator"]
    assert controls["risk_hints"] == ["generic_single_token_broad_risk"]


def main() -> None:
    test_guidance_separates_query_roles()
    test_controls_do_not_copy_window_text_as_evidence()
    test_lexical_aliases_exclude_profile_only_and_semantic_queries()
    test_negative_constraints_and_shape_hints_are_soft_controls()
    test_load_profile_guidance_jsonl_and_exact_filter()
    test_reject_profile_is_not_safe_for_step5x()
    test_accepted_cue_without_provenance_warns_but_does_not_crash()
    test_timeout_fallback_emits_region_locator_not_alias_atom()
    test_profile_guidance_contract_still_marks_all_routes_as_non_evidence()
    test_descriptor_and_head_term_export_is_seedless_and_auditable()
    test_model_only_suggestion_remains_quarantined_without_source_confirmation()
    test_shapeaware_guidance_fields_are_preserved_in_controls()
    print("TEST_STEP5X_PROFILE_GUIDANCE_OK")


if __name__ == "__main__":
    main()
