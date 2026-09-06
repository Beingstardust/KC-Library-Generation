from __future__ import annotations

import hashlib
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from kc_l.retrieval_gate.evidence_stage_v3_pack_composition import compose_evidence_packs_from_scored_candidates
from kc_l.retrieval_gate.evidence_stage_v3_scored_candidates import score_candidate_rows
from kc_l.retrieval_gate.profile_guidance import (
    alias_safe_terms_for_candidate_generation,
    guidance_from_profile,
)
from kc_l.retrieval_gate.semantic import match_normalize


def _candidate_row(
    *,
    candidate_id: str,
    kc_id: str,
    canonical_name: str,
    text: str,
    aliases: list[str] | None = None,
    topic_path_labels: list[str] | None = None,
    parent_topic_label: str = "",
    source_kc_id: str | None = None,
    source_canonical_name: str | None = None,
    support_profile: dict[str, object] | None = None,
    structural_flags: dict[str, object] | None = None,
    patch_id: str = "patch-1",
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "candidate_bank_version": "step5x_v3_candidate_bank_v1",
        "run_id": "targeted_semantic_regressions",
        "source_surface": "step5_3_nested_evidence",
        "source_manifest": "tests://targeted_semantic_regressions",
        "source_row_index": 0,
        "source_evidence_index": 0,
        "kc_id": kc_id,
        "canonical_name": canonical_name,
        "aliases": list(aliases or []),
        "topic_path_ids": [],
        "topic_path_labels": list(topic_path_labels or []),
        "parent_topic_id": "",
        "parent_topic_label": parent_topic_label,
        "source_kc_id": source_kc_id or kc_id,
        "source_canonical_name": source_canonical_name or canonical_name,
        "granularity": "sentence",
        "text": text,
        "source_block_text": text,
        "context_text": "",
        "doc_id": "DOC_TEST",
        "page_index": 1,
        "block_id": f"DOC_TEST:block:{candidate_id}",
        "sentence_id": f"DOC_TEST:block:{candidate_id}::s000",
        "sent_idx": 0,
        "patch_id": patch_id,
        "patch_heading": "Heading",
        "reveal_group_id": f"rg:{candidate_id}",
        "layer": "mineru",
        "bbox": [1.0, 2.0, 3.0, 4.0],
        "char_start": 0,
        "char_end": len(text),
        "retrieval_scores": {"combined": 0.8},
        "alignment_score": 7.5,
        "alignment_breakdown": {
            "canonical_name_token_hits": 0,
            "alias_token_hits": 0,
            "name_or_alias_token_hits": 0,
            "competitor_token_hits": 0,
            "doc_mismatch": False,
            "exact_name_phrase": False,
            "exact_alias_phrase": False,
            "flags": {},
        },
        "support_profile": {
            "anchor_quality": "weak",
            "preferred_support_role": "other",
            "formula_support_score": 0.0,
            "generic_context_only": False,
            "fragmentary_surface": False,
            "has_context_completion_source": False,
            "contamination_exclusion_hint": False,
            **dict(support_profile or {}),
        },
        "structural_flags": {
            "has_text": True,
            "has_source_block_text": True,
            "has_sentence_id": True,
            "has_patch_id": True,
            "has_page_index": True,
            "looks_formula_like": False,
            "looks_caption_like": False,
            "looks_prompt_like": False,
            "looks_fragmentary": False,
            **dict(structural_flags or {}),
        },
        "raw_text_hash": hashlib.sha256(match_normalize(text).encode("utf-8")).hexdigest(),
        "provenance": {
            "from_step": "step5_3",
            "source_manifest": "tests://targeted_semantic_regressions",
            "source_jsonl": "tests://targeted_semantic_regressions",
            "source_row_index": 0,
            "source_evidence_index": 0,
        },
    }


def _score_single(row: dict[str, object]) -> dict[str, object]:
    return score_candidate_rows([row])[0]


def _assert_not_positive_drafting(row: dict[str, object]) -> None:
    scored = _score_single(row)
    pack = compose_evidence_packs_from_scored_candidates([scored])[0]
    assert not scored["role_eligibility"]["positive_support_eligible"]
    assert scored["routing_recommendation"] != "positive_role_candidate"
    assert pack["ordered_pack_for_drafting"] == []


def test_non_deterministic_search_wrong_sense_row_is_not_positive_support() -> None:
    _assert_not_positive_drafting(
        _candidate_row(
            candidate_id="nondet_wrong_sense",
            kc_id="KC_FSEL_GEN_007",
            canonical_name="Non-Deterministic Search",
            aliases=["Non Deterministic Search"],
            topic_path_labels=["Feature Selection"],
            parent_topic_label="Search",
            text=(
                "This can be understood as the non-deterministic nature of the output variable, "
                "where the same set of attributes can have different output values."
            ),
        )
    )


def test_entropy_node_leaf_complexity_row_is_not_positive_support() -> None:
    _assert_not_positive_drafting(
        _candidate_row(
            candidate_id="entropy_leaf_complexity",
            kc_id="KC_CLF_DT_005",
            canonical_name="Entropy (Node)",
            aliases=["minimize the entropy of the leaf nodes"],
            topic_path_labels=["Classification", "Decision Trees"],
            parent_topic_label="Decision Trees",
            text=(
                "In the context of decision trees, the complexity of a decision tree can be estimated "
                "as the ratio of the number of leaf nodes to the number of training instances."
            ),
        )
    )


def test_binary_decision_tree_generalization_formula_is_not_positive_support() -> None:
    _assert_not_positive_drafting(
        _candidate_row(
            candidate_id="binary_tree_formula",
            kc_id="KC_CLF_DT_011",
            canonical_name="Binary Decision Tree",
            aliases=["binary decision trees"],
            topic_path_labels=["Classification", "Decision Trees"],
            parent_topic_label="Decision Trees",
            text="$$ errgen(T) = err(T) + Ω × k / Ntrain $$",
            structural_flags={"looks_formula_like": True},
        )
    )


def test_models_of_randomness_generic_sentence_is_not_positive_for_both_kcs() -> None:
    shared_text = (
        "In such cases, it is possible to filter the cells based on the statistical properties "
        "of one or more non-spatial attributes, e.g., average house price, and then form "
        "clusters based on geographic proximity."
    )
    rows = score_candidate_rows(
        [
            _candidate_row(
                candidate_id="mor_approach_1",
                kc_id="KC_CLU_EVAL_006",
                canonical_name="Models of Randomness (Approach 1)",
                aliases=["statistical tests for spatial randomness"],
                topic_path_labels=["Clustering", "Evaluation"],
                parent_topic_label="Cluster Evaluation",
                text=shared_text,
                patch_id="patch-shared-randomness",
            ),
            _candidate_row(
                candidate_id="mor_approach_2",
                kc_id="KC_CLU_EVAL_007",
                canonical_name="Models of Randomness (Approach 2)",
                aliases=["statistical tests for spatial randomness"],
                topic_path_labels=["Clustering", "Evaluation"],
                parent_topic_label="Cluster Evaluation",
                text=shared_text,
                patch_id="patch-shared-randomness",
            ),
        ]
    )
    packs = {
        pack["kc_id"]: pack
        for pack in compose_evidence_packs_from_scored_candidates(rows)
    }

    assert all(not row["role_eligibility"]["positive_support_eligible"] for row in rows)
    assert all(row["routing_recommendation"] != "positive_role_candidate" for row in rows)
    assert packs["KC_CLU_EVAL_006"]["ordered_pack_for_drafting"] == []
    assert packs["KC_CLU_EVAL_007"]["ordered_pack_for_drafting"] == []


def test_pearson_anchor_mention_stays_non_positive_without_local_explanation() -> None:
    _assert_not_positive_drafting(
        _candidate_row(
            candidate_id="pearson_anchor_only",
            kc_id="KC_FSEL_GOOD_002",
            canonical_name="Pearson Product-Moment Correlation",
            aliases=[
                "Pearson correlation coefficient",
                "degree of linear correlation between two variables",
            ],
            topic_path_labels=["Feature Selection"],
            parent_topic_label="Goodness Measures",
            text="Pearson's correlation coefficient and MI .",
        )
    )


def test_informative_missingness_source_equivalent_guidance_requires_provenance() -> None:
    profile = {
        "kc_id": "KC_DE_MISS_005",
        "canonical_name": "Informative Missingness",
        "profile_status": "usable",
        "accepted_source_cues": [
            {
                "term": "not missing at random",
                "active": True,
                "cue_type": "source_observed_equivalent",
                "provenance": [{"snippet_id": "s1", "field_path": "sentence_text"}],
            }
        ],
        "query_variants": [
            {
                "query": "NMAR",
                "active": True,
                "source": "model_suggested_unverified",
                "retrieval_role": "lexical_query",
                "retrieval_channels": ["lexical"],
                "step5x_eligible": True,
            }
        ],
        "audit": {"profile_input_status": "strict_windows_available"},
    }
    guidance = guidance_from_profile(profile)

    assert guidance.safe_to_use_for_step5x is True
    assert "not missing at random" in alias_safe_terms_for_candidate_generation(guidance)
    assert [query.query for query in guidance.profile_only_queries] == ["NMAR"]

    profile_without_provenance = dict(profile)
    profile_without_provenance["accepted_source_cues"] = [
        {
            "term": "missing not at random",
            "active": True,
            "cue_type": "source_observed_equivalent",
        }
    ]
    guidance_without_provenance = guidance_from_profile(profile_without_provenance)

    assert alias_safe_terms_for_candidate_generation(guidance_without_provenance) == []
    assert any(
        warning.startswith("accepted_cue_without_provenance")
        for warning in guidance_without_provenance.warnings
    )


def test_model_comparison_chi_square_independence_row_is_not_positive_support() -> None:
    _assert_not_positive_drafting(
        _candidate_row(
            candidate_id="independent_test_sets_chi_square",
            kc_id="KC_EVAL_COMP_003",
            canonical_name="Comparing Two Models on Independent Test Sets",
            aliases=["Comparing Two Models on Independent Test Sets"],
            topic_path_labels=["Evaluation"],
            parent_topic_label="Comparison Tests",
            text=(
                "The χ2 test checks the hypothesis that A and B are independent, "
                "with (r−1)×(c− 1) degrees of freedom."
            ),
        )
    )


def main() -> None:
    test_non_deterministic_search_wrong_sense_row_is_not_positive_support()
    test_entropy_node_leaf_complexity_row_is_not_positive_support()
    test_binary_decision_tree_generalization_formula_is_not_positive_support()
    test_models_of_randomness_generic_sentence_is_not_positive_for_both_kcs()
    test_pearson_anchor_mention_stays_non_positive_without_local_explanation()
    test_informative_missingness_source_equivalent_guidance_requires_provenance()
    test_model_comparison_chi_square_independence_row_is_not_positive_support()
    print("TEST_STEP5X_TARGETED_SEMANTIC_REGRESSIONS_OK")


if __name__ == "__main__":
    main()
