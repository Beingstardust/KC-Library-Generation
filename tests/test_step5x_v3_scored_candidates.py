from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_SRC = REPO_ROOT / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from kc_l.retrieval_gate.evidence_stage_v3_scored_candidates import (
    FORBIDDEN_PACK_FIELDS,
    FORBIDDEN_SEED_FIELDS,
    build_scored_candidate_artifacts,
    load_candidate_bank_rows,
    score_candidate_row,
    score_candidate_rows,
)
from kc_l.retrieval_gate.semantic import match_normalize

TEST_ROOT = REPO_ROOT / ".codex_tmp_test_step5x_v3_scored_candidates"


def _hash_text(text: str) -> str:
    return hashlib.sha256(match_normalize(text).encode("utf-8")).hexdigest()


def _stage1_candidate_row(
    *,
    candidate_id: str,
    kc_id: str,
    canonical_name: str,
    text: str,
    aliases: list[str] | None = None,
    topic_path_labels: list[str] | None = None,
    parent_topic_label: str = "",
    parent_topic_id: str = "",
    source_kc_id: str | None = None,
    source_canonical_name: str | None = None,
    doc_id: str = "DOC_1",
    page_index: int | None = 1,
    block_id: str = "DOC_1:block:001",
    sentence_id: str = "DOC_1:block:001::s000",
    sent_idx: int | None = 0,
    patch_id: str = "patch-1",
    patch_heading: str = "Heading",
    reveal_group_id: str = "rg-1",
    source_block_text: str | None = None,
    alignment_breakdown: dict[str, object] | None = None,
    support_profile: dict[str, object] | None = None,
    structural_flags: dict[str, object] | None = None,
    retrieval_scores: dict[str, object] | None = None,
    seed_definition: str | None = None,
    seed_keywords: list[str] | None = None,
) -> dict[str, object]:
    row: dict[str, object] = {
        "candidate_id": candidate_id,
        "candidate_bank_version": "step5x_v3_candidate_bank_v1",
        "run_id": "stage1_demo",
        "source_surface": "step5_3_nested_evidence",
        "source_manifest": "stage1_manifest.json",
        "source_row_index": 0,
        "source_evidence_index": 0,
        "kc_id": kc_id,
        "canonical_name": canonical_name,
        "aliases": list(aliases or []),
        "topic_path_ids": [],
        "topic_path_labels": list(topic_path_labels or []),
        "parent_topic_id": parent_topic_id,
        "parent_topic_label": parent_topic_label,
        "source_kc_id": source_kc_id or kc_id,
        "source_canonical_name": source_canonical_name or canonical_name,
        "granularity": "sentence",
        "text": text,
        "source_block_text": source_block_text or text,
        "context_text": "",
        "doc_id": doc_id,
        "page_index": page_index,
        "block_id": block_id,
        "sentence_id": sentence_id,
        "sent_idx": sent_idx,
        "patch_id": patch_id,
        "patch_heading": patch_heading,
        "reveal_group_id": reveal_group_id,
        "layer": "mineru",
        "bbox": [1.0, 2.0, 3.0, 4.0],
        "char_start": 0,
        "char_end": len(text),
        "retrieval_scores": dict(retrieval_scores or {"combined": 0.8}),
        "alignment_score": 7.5,
        "alignment_breakdown": dict(
            alignment_breakdown
            or {
                "canonical_name_token_hits": 0,
                "alias_token_hits": 0,
                "name_or_alias_token_hits": 0,
                "competitor_token_hits": 0,
                "doc_mismatch": False,
                "exact_name_phrase": False,
                "exact_alias_phrase": False,
                "flags": {},
            }
        ),
        "support_profile": dict(
            support_profile
            or {
                "anchor_quality": "weak",
                "preferred_support_role": "other",
                "formula_support_score": 0.0,
                "generic_context_only": False,
                "fragmentary_surface": False,
                "has_context_completion_source": False,
                "contamination_exclusion_hint": False,
            }
        ),
        "structural_flags": dict(
            structural_flags
            or {
                "has_text": True,
                "has_source_block_text": True,
                "has_sentence_id": True,
                "has_patch_id": True,
                "has_page_index": page_index is not None,
                "looks_formula_like": False,
                "looks_caption_like": False,
                "looks_prompt_like": False,
                "looks_fragmentary": False,
            }
        ),
        "raw_text_hash": _hash_text(text),
        "provenance": {
            "from_step": "step5_3",
            "source_manifest": "nested_manifest.json",
            "source_jsonl": "nested.jsonl",
            "source_row_index": 0,
            "source_evidence_index": 0,
        },
    }
    if seed_definition is not None:
        row["seed_definition"] = seed_definition
    if seed_keywords is not None:
        row["seed_keywords"] = list(seed_keywords)
    return row


def _score_rows(*rows: dict[str, object]) -> list[dict[str, object]]:
    return score_candidate_rows(list(rows))


def test_one_output_row_per_input_candidate():
    rows = _score_rows(
        _stage1_candidate_row(candidate_id="cand_a", kc_id="KC_A", canonical_name="Concept A", text="Concept A is defined here."),
        _stage1_candidate_row(candidate_id="cand_b", kc_id="KC_A", canonical_name="Concept A", text="Another sentence."),
    )
    assert len(rows) == 2


def test_candidate_id_preserved_and_scored_candidate_id_matches():
    row = _score_rows(
        _stage1_candidate_row(candidate_id="cand_keep", kc_id="KC_A", canonical_name="Concept A", text="Concept A is defined here.")
    )[0]
    assert row["candidate_id"] == "cand_keep"
    assert row["scored_candidate_id"] == "cand_keep"


def test_no_seed_fields_propagated_and_no_pack_fields_emitted():
    row = _score_rows(
        _stage1_candidate_row(
            candidate_id="cand_seed",
            kc_id="KC_A",
            canonical_name="Concept A",
            text="Concept A is defined here.",
            seed_definition="forbidden",
            seed_keywords=["forbidden"],
        )
    )[0]
    rendered = json.dumps(row, sort_keys=True)
    for field in FORBIDDEN_SEED_FIELDS:
        assert field not in row
        assert field not in rendered
    for field in FORBIDDEN_PACK_FIELDS:
        assert field not in row


def test_shapeaware_shadow_fields_are_emitted_for_reviewable_rows():
    row = _score_rows(
        _stage1_candidate_row(
            candidate_id="cand_shapeaware",
            kc_id="KC_KMEANS_001",
            canonical_name="K-Means Algorithm",
            text="The K-Means algorithm alternates between assigning each point to the closest centroid and recomputing the centroid.",
            support_profile={"support_roles": ["process_or_procedure"]},
        )
    )[0]
    assert row["expected_evidence_needs"][0]["need"] == "algorithm_procedure"
    assert "algorithm_procedure_anchor" in row["shapeaware_support_roles"]
    assert row["shapeaware_bucket"] == "drafting_core"
    assert "definition_subject_mismatch" in row["review_risk_flags"]


def test_source_and_provenance_fields_are_preserved():
    row = _score_rows(
        _stage1_candidate_row(
            candidate_id="cand_prov",
            kc_id="KC_A",
            canonical_name="Concept A",
            text="Concept A is defined here.",
            doc_id="DOC_X",
            page_index=9,
            block_id="DOC_X:block:009",
            sentence_id="DOC_X:block:009::s003",
            sent_idx=3,
            patch_id="patch-x",
            patch_heading="Patch Heading",
            reveal_group_id="rg-9",
            source_block_text="Full block text for Concept A is defined here.",
        )
    )[0]
    assert row["doc_id"] == "DOC_X"
    assert row["page_index"] == 9
    assert row["block_id"] == "DOC_X:block:009"
    assert row["sentence_id"] == "DOC_X:block:009::s003"
    assert row["patch_id"] == "patch-x"
    assert row["patch_heading"] == "Patch Heading"
    assert row["reveal_group_id"] == "rg-9"
    assert row["provenance"]["source_manifest"] == "nested_manifest.json"


def test_target_bound_candidate_scores_higher_than_off_target_for_same_kc():
    good, bad = _score_rows(
        _stage1_candidate_row(
            candidate_id="cand_good",
            kc_id="KC_A",
            canonical_name="Concept A",
            text="Concept A is a representation of the target relation.",
            alignment_breakdown={"exact_name_phrase": True, "canonical_name_token_hits": 2, "flags": {}, "competitor_token_hits": 0},
        ),
        _stage1_candidate_row(
            candidate_id="cand_bad",
            kc_id="KC_A",
            canonical_name="Concept A",
            text="A different process is unrelated to the target.",
            source_kc_id="KC_OTHER",
            source_canonical_name="Other Concept",
        ),
    )
    assert good["candidate_quality"]["overall_score"] > bad["candidate_quality"]["overall_score"]


def test_broad_missing_values_rows_do_not_score_as_nb_specific_positive_support():
    good, generic, tree = _score_rows(
        _stage1_candidate_row(
            candidate_id="cand_nb_good",
            kc_id="KC_CLF_NB_011",
            canonical_name="Handling Missing Values in NB",
            aliases=["Missing Values in Naive Bayes"],
            topic_path_labels=["Data Mining", "Classification", "Naive Bayes"],
            parent_topic_label="Naive Bayes",
            text="In Naive Bayes, missing values can be handled by ignoring the absent attribute in the likelihood term.",
            alignment_breakdown={"exact_alias_phrase": False, "canonical_name_token_hits": 3, "flags": {}, "competitor_token_hits": 0},
        ),
        _stage1_candidate_row(
            candidate_id="cand_nb_generic",
            kc_id="KC_CLF_NB_011",
            canonical_name="Handling Missing Values in NB",
            aliases=["Missing Values in Naive Bayes"],
            topic_path_labels=["Data Mining", "Classification", "Naive Bayes"],
            parent_topic_label="Naive Bayes",
            text="Patients have missing values in many data sets.",
            support_profile={"generic_context_only": True},
        ),
        _stage1_candidate_row(
            candidate_id="cand_nb_tree",
            kc_id="KC_CLF_NB_011",
            canonical_name="Handling Missing Values in NB",
            aliases=["Missing Values in Naive Bayes"],
            topic_path_labels=["Data Mining", "Classification", "Naive Bayes"],
            parent_topic_label="Naive Bayes",
            text="A decision tree classifier handles missing values by surrogate splits.",
            source_kc_id="KC_TREE_001",
            source_canonical_name="Handling Missing Values in Trees",
            alignment_breakdown={"competitor_token_hits": 1, "flags": {}, "canonical_name_token_hits": 2},
        ),
    )
    assert good["routing_recommendation"] == "positive_role_candidate"
    assert not generic["role_eligibility"]["positive_support_eligible"]
    assert not tree["role_eligibility"]["positive_support_eligible"]


def test_same_kc_broad_missing_values_row_still_needs_family_alignment():
    row = _score_rows(
        _stage1_candidate_row(
            candidate_id="cand_nb_same_kc_generic",
            kc_id="KC_CLF_NB_011",
            canonical_name="Handling Missing Values in NB",
            aliases=["Missing Values in Naive Bayes"],
            topic_path_labels=["Data Mining", "Classification", "Naive Bayes"],
            parent_topic_label="Naive Bayes",
            source_kc_id="KC_CLF_NB_011",
            source_canonical_name="Handling Missing Values in NB",
            text="Unfortunately, since some of the patients have missing values for this field, it is impossible to say whether a 0 in this field is a real 0 or a 10.",
            source_block_text="Unfortunately, since some of the patients have missing values for this field, it is impossible to say whether a 0 in this field is a real 0 or a 10.",
        )
    )[0]
    assert not row["role_eligibility"]["positive_support_eligible"]
    assert row["lexical_target_binding"]["binding_strength"] in {"weak", "none"}
    assert "family_alignment_missing_for_broad_target" in row["lexical_target_binding"]["offtarget_reasons"]


def test_broad_missing_data_mechanism_row_does_not_become_same_kc_positive_support():
    row = _score_rows(
        _stage1_candidate_row(
            candidate_id="cand_nb_mar_generic",
            kc_id="KC_CLF_NB_011",
            canonical_name="Handling Missing Values in NB",
            aliases=["Missing Values in Naive Bayes"],
            topic_path_labels=["Data Mining", "Classification", "Naive Bayes"],
            parent_topic_label="Naive Bayes",
            source_kc_id="KC_CLF_NB_011",
            source_canonical_name="Handling Missing Values in NB",
            text="In the case of MAR missing data mechanism, given a particular value or values for a set of features, the distribution of the rest of features is the same among the observed cases as it is among the missing cases.",
            source_block_text="In the case of MAR missing data mechanism, given a particular value or values for a set of features, the distribution of the rest of features is the same among the observed cases as it is among the missing cases.",
        )
    )[0]
    assert not row["role_eligibility"]["positive_support_eligible"]
    assert row["routing_recommendation"] in {"drop_from_positive_roles", "manual_review_candidate", "guardrail_only_candidate"}


def test_border_point_definition_does_not_become_core_point_definition_support():
    bad, good = _score_rows(
        _stage1_candidate_row(
            candidate_id="cand_core_bad",
            kc_id="KC_CLU_DBS_001",
            canonical_name="Core Point",
            topic_path_labels=["Clustering", "Density-based Clustering"],
            parent_topic_label="Density-based Clustering",
            text="A border point is not a core point.",
            alignment_breakdown={"exact_name_phrase": True, "canonical_name_token_hits": 2, "competitor_token_hits": 1, "flags": {}},
        ),
        _stage1_candidate_row(
            candidate_id="cand_core_good",
            kc_id="KC_CLU_DBS_001",
            canonical_name="Core Point",
            topic_path_labels=["Clustering", "Density-based Clustering"],
            parent_topic_label="Density-based Clustering",
            text="A core point is a point whose neighborhood contains at least minPts objects.",
            alignment_breakdown={"exact_name_phrase": True, "canonical_name_token_hits": 2, "flags": {}, "competitor_token_hits": 0},
        ),
    )
    assert not bad["role_eligibility"]["definition_kernel"]
    assert bad["role_eligibility"]["sibling_contrast"] or bad["routing_recommendation"] in {"guardrail_only_candidate", "manual_review_candidate", "drop_from_positive_roles"}
    assert good["role_eligibility"]["definition_kernel"]


def test_pure_context_completion_candidate_does_not_make_positive_support_eligible_true():
    row = _score_rows(
        _stage1_candidate_row(
            candidate_id="cand_core_context_only",
            kc_id="KC_CLU_DBS_001",
            canonical_name="Core Point",
            topic_path_labels=["Clustering", "Density-based Clustering"],
            parent_topic_label="Density-based Clustering",
            text="neighborhood of a core point.",
            source_block_text="A border point is not a core point, but falls within the neighborhood of a core point.",
            structural_flags={"looks_fragmentary": True},
            support_profile={"has_context_completion_source": True},
            alignment_breakdown={"exact_name_phrase": True, "canonical_name_token_hits": 2, "competitor_token_hits": 1, "flags": {}},
        )
    )[0]
    assert row["role_eligibility"]["context_completion_candidate"]
    assert row["role_eligibility"]["auxiliary_support_eligible"]
    assert not row["role_eligibility"]["positive_support_eligible"]
    assert row["routing_recommendation"] == "auxiliary_only_candidate"


def test_core_point_transition_or_sibling_context_does_not_become_positive_support():
    sibling_row, transition_row = _score_rows(
        _stage1_candidate_row(
            candidate_id="cand_core_likewise",
            kc_id="KC_CLU_DBS_001",
            canonical_name="Core Point",
            topic_path_labels=["Clustering", "Density-based Clustering"],
            parent_topic_label="Density-based Clustering",
            text="Likewise, any border point that is close enough to a core point is put in the same cluster as the core point.",
            alignment_breakdown={"exact_name_phrase": True, "canonical_name_token_hits": 2, "competitor_token_hits": 3, "flags": {}},
            support_profile={"contamination_exclusion_hint": True},
        ),
        _stage1_candidate_row(
            candidate_id="cand_core_transition",
            kc_id="KC_CLU_DBS_001",
            canonical_name="Core Point",
            topic_path_labels=["Clustering", "Density-based Clustering"],
            parent_topic_label="Density-based Clustering",
            text="Given the previous definitions of core points, border points, and noise points, the DBSCAN algorithm can be informally described as follows.",
            source_block_text="Given the previous definitions of core points, border points, and noise points, the DBSCAN algorithm can be informally described as follows. A core point is then expanded into a cluster.",
            structural_flags={"looks_fragmentary": True},
            support_profile={"has_context_completion_source": True, "contamination_exclusion_hint": True},
            alignment_breakdown={"canonical_name_token_hits": 1, "competitor_token_hits": 3, "flags": {}},
        ),
    )
    assert not sibling_row["role_eligibility"]["positive_support_eligible"]
    assert sibling_row["routing_recommendation"] in {"guardrail_only_candidate", "manual_review_candidate", "drop_from_positive_roles"}
    assert not transition_row["role_eligibility"]["positive_support_eligible"]
    assert transition_row["routing_recommendation"] in {"auxiliary_only_candidate", "guardrail_only_candidate", "manual_review_candidate", "drop_from_positive_roles"}


def test_measurement_noise_context_does_not_become_noise_point_positive_support():
    bad, good = _score_rows(
        _stage1_candidate_row(
            candidate_id="cand_noise_bad",
            kc_id="KC_CLU_DBS_003",
            canonical_name="Noise Point",
            topic_path_labels=["Clustering", "Density-based Clustering"],
            parent_topic_label="Density-based Clustering",
            text="Noise is the random component of a measurement error.",
            source_kc_id="KC_MEAS_001",
            source_canonical_name="Measurement Noise",
        ),
        _stage1_candidate_row(
            candidate_id="cand_noise_good",
            kc_id="KC_CLU_DBS_003",
            canonical_name="Noise Point",
            topic_path_labels=["Clustering", "Density-based Clustering"],
            parent_topic_label="Density-based Clustering",
            text="A noise point is any point that is neither a core point nor a border point.",
            alignment_breakdown={"exact_name_phrase": True, "canonical_name_token_hits": 2, "competitor_token_hits": 1, "flags": {}},
        ),
    )
    assert not bad["role_eligibility"]["positive_support_eligible"]
    assert good["role_eligibility"]["positive_support_eligible"]
    assert good["role_eligibility"]["definition_kernel"]


def test_hyperparameter_selection_prose_does_not_become_formula_notation():
    bad, good = _score_rows(
        _stage1_candidate_row(
            candidate_id="cand_cv_bad",
            kc_id="KC_EVAL_SAMP_003",
            canonical_name="k-Fold Cross Validation",
            topic_path_labels=["Evaluation", "Sampling"],
            parent_topic_label="Sampling",
            text="Hence, at step t we obtain the best choice of the hyper-parameter value.",
            structural_flags={"looks_formula_like": True},
            support_profile={"formula_support_score": 2.0},
        ),
        _stage1_candidate_row(
            candidate_id="cand_cv_good",
            kc_id="KC_EVAL_SAMP_003",
            canonical_name="k-Fold Cross Validation",
            topic_path_labels=["Evaluation", "Sampling"],
            parent_topic_label="Sampling",
            text="In k-fold cross validation, the data are partitioned into k folds and each fold is used once for testing.",
            alignment_breakdown={"exact_name_phrase": True, "canonical_name_token_hits": 3, "flags": {}, "competitor_token_hits": 0},
        ),
    )
    assert not bad["role_eligibility"]["formula_notation"]
    assert not bad["role_eligibility"]["positive_support_eligible"]
    assert good["candidate_quality"]["overall_score"] > bad["candidate_quality"]["overall_score"]
    assert good["role_eligibility"]["positive_support_eligible"]


def test_source_block_only_procedure_row_does_not_become_positive_example_support():
    row = _score_rows(
        _stage1_candidate_row(
            candidate_id="cand_cv_sourceblock_only",
            kc_id="KC_EVAL_SAMP_003",
            canonical_name="k-Fold Cross Validation",
            topic_path_labels=["Evaluation", "Sampling"],
            parent_topic_label="Sampling",
            source_kc_id="KC_EVAL_SAMP_003",
            source_canonical_name="k-Fold Cross Validation",
            text="Hence, at step t we obtain the best choice of the hyper-parameter value.",
            source_block_text="In k-fold cross validation, each fold is used once for testing. Hence, at step t we obtain the best choice of the hyper-parameter value.",
            structural_flags={"looks_formula_like": True, "looks_caption_like": False, "looks_prompt_like": False, "looks_fragmentary": False},
            support_profile={"formula_support_score": 2.0},
        )
    )[0]
    assert not row["role_eligibility"]["positive_support_eligible"]
    assert not row["role_eligibility"]["example_or_procedure"]
    assert row["routing_recommendation"] in {"auxiliary_only_candidate", "drop_from_positive_roles", "manual_review_candidate"}



def test_common_mistake_cross_validation_guidance_is_not_standalone_positive_support():
    row = _score_rows(
        _stage1_candidate_row(
            candidate_id="cand_cv_common_mistake",
            kc_id="KC_EVAL_SAMP_003",
            canonical_name="k-Fold Cross Validation",
            topic_path_labels=["Evaluation", "Sampling"],
            parent_topic_label="Sampling",
            text="One of the common mistakes while using cross-validation is to perform pre-processing operations using the entire data set and not within the training fold of every cross-validation run.",
            alignment_breakdown={"canonical_name_token_hits": 2, "flags": {}, "competitor_token_hits": 0},
        )
    )[0]
    assert row["meta_guidance_signal"]["is_meta_guidance"]
    assert "meta_guidance" in row["risk_flags"]
    assert not row["role_eligibility"]["positive_support_eligible"]
    assert not row["role_eligibility"]["explanatory_gloss"]
    assert row["routing_recommendation"] in {"drop_from_positive_roles", "manual_review_candidate", "auxiliary_only_candidate"}


def test_clean_cross_validation_definition_is_standalone_positive_definition():
    # Definition-score inputs strengthened 2026-08-05 (audit codebase-audit-20260805 item 6
    # follow-up): the original construction used a partial-name text match ("Cross-validation"
    # for canonical_name "k-Fold Cross Validation") plus competitor_token_hits=2 and
    # contamination_exclusion_hint=True - real off-target/uncertainty signals that made this a
    # genuinely borderline case, not the "clean...standalone positive" case its name promises.
    # It scored 5.32 under min_definition_score's real, empirically-calibrated value (6.0, commit
    # ab1b7d2, 2026-07-27, 360 hand-judged examples, verified live against real production data) -
    # below that bar, though it had cleared the stale pre-calibration Python fallback (3.9) this
    # test apparently was never re-verified against after ab1b7d2 landed. The calibrated threshold
    # is trusted here (it's real, production-verified; this synthetic case is not), so the input is
    # corrected to be unambiguous rather than the assertion weakened: full canonical-name text
    # match (real exact_target_phrase_in_text binding, not a partial paraphrase) and no artificial
    # competitor/contamination signals, matching what a genuinely clean definition looks like.
    row = _score_rows(
        _stage1_candidate_row(
            candidate_id="cand_cv_definition",
            kc_id="KC_EVAL_SAMP_003",
            canonical_name="k-Fold Cross Validation",
            topic_path_labels=["Evaluation", "Sampling"],
            parent_topic_label="Sampling",
            text="k-Fold Cross Validation is a widely-used model evaluation method that aims to make effective use of all labeled instances in D for both training and testing.",
            alignment_breakdown={"canonical_name_token_hits": 4, "exact_name_phrase": True, "flags": {}, "competitor_token_hits": 0},
        )
    )[0]
    assert row["role_eligibility"]["definition_kernel"]
    assert row["role_eligibility"]["positive_support_eligible"]
    assert row["routing_recommendation"] == "positive_role_candidate"


def test_internal_indices_sentence_beats_covariance_row():
    good, bad = _score_rows(
        _stage1_candidate_row(
            candidate_id="cand_idx_good",
            kc_id="KC_CLU_EVAL_001",
            canonical_name="Internal Indices Overview",
            aliases=["Internal Indices"],
            topic_path_labels=["Clustering", "Cluster Evaluation"],
            parent_topic_label="Cluster Evaluation",
            text="Unsupervised measures are often called internal indices because they use only information present in the data set.",
            alignment_breakdown={"exact_alias_phrase": True, "canonical_name_token_hits": 2, "flags": {}, "competitor_token_hits": 0},
        ),
        _stage1_candidate_row(
            candidate_id="cand_idx_bad",
            kc_id="KC_CLU_EVAL_001",
            canonical_name="Internal Indices Overview",
            aliases=["Internal Indices"],
            topic_path_labels=["Clustering", "Cluster Evaluation"],
            parent_topic_label="Cluster Evaluation",
            text="The covariance of the random variable provides the index term.",
            source_kc_id="KC_STAT_001",
            source_canonical_name="Covariance",
        ),
    )
    assert good["candidate_quality"]["overall_score"] > bad["candidate_quality"]["overall_score"]
    assert good["role_eligibility"]["positive_support_eligible"]


def test_duplicate_tuples_support_beats_prompt_like_guardrail():
    good, prompt = _score_rows(
        _stage1_candidate_row(
            candidate_id="cand_dup_good",
            kc_id="KC_DE_PREP_003",
            canonical_name="Duplicate Tuples",
            topic_path_labels=["Data Engineering", "Data Preparation"],
            parent_topic_label="Data Preparation",
            text="Duplicate tuples can create inconsistent records when the same entity appears multiple times.",
            alignment_breakdown={"exact_name_phrase": True, "canonical_name_token_hits": 2, "flags": {}, "competitor_token_hits": 0},
        ),
        _stage1_candidate_row(
            candidate_id="cand_dup_prompt",
            kc_id="KC_DE_PREP_003",
            canonical_name="Duplicate Tuples",
            topic_path_labels=["Data Engineering", "Data Preparation"],
            parent_topic_label="Data Preparation",
            text="Explain how duplicate tuples should be handled.",
            structural_flags={"looks_prompt_like": True},
        ),
    )
    assert good["candidate_quality"]["overall_score"] > prompt["candidate_quality"]["overall_score"]
    assert prompt["routing_recommendation"] != "positive_role_candidate"


def test_duplicate_tuples_inconsistency_sentence_is_explanatory_not_example_or_procedure():
    row = _score_rows(
        _stage1_candidate_row(
            candidate_id="cand_dup_expl",
            kc_id="KC_DE_PREP_003",
            canonical_name="Duplicate Tuples",
            topic_path_labels=["Data Engineering", "Data Preparation"],
            parent_topic_label="Data Preparation",
            text="Having duplicate tuples can be troublesome, not only wasting space and computing time for the algorithm, but they can also be a source of inconsistency.",
            alignment_breakdown={"exact_name_phrase": True, "canonical_name_token_hits": 2, "flags": {}, "competitor_token_hits": 0},
        )
    )[0]
    assert row["role_eligibility"]["explanatory_gloss"]
    assert row["role_eligibility"]["positive_support_eligible"]
    assert not row["role_eligibility"]["example_or_procedure"]


def test_weak_broad_specificity_or_external_recall_evidence_stays_weak():
    weak, strong = _score_rows(
        _stage1_candidate_row(
            candidate_id="cand_spec_weak",
            kc_id="KC_EVAL_BASIC_005",
            canonical_name="Specificity",
            topic_path_labels=["Evaluation", "Basic Measures"],
            parent_topic_label="Basic Measures",
            text="External recall is discussed in many search settings.",
            source_kc_id="KC_SEARCH_001",
            source_canonical_name="External Recall",
        ),
        _stage1_candidate_row(
            candidate_id="cand_spec_good",
            kc_id="KC_EVAL_BASIC_005",
            canonical_name="Specificity",
            topic_path_labels=["Evaluation", "Basic Measures"],
            parent_topic_label="Basic Measures",
            text="Specificity is the proportion of actual negatives that are correctly identified.",
            alignment_breakdown={"exact_name_phrase": True, "canonical_name_token_hits": 1, "flags": {}, "competitor_token_hits": 0},
        ),
    )
    assert not weak["role_eligibility"]["positive_support_eligible"]
    assert strong["role_eligibility"]["definition_kernel"]


def test_sibling_contrast_candidate_cannot_be_positive_support():
    row = _score_rows(
        _stage1_candidate_row(
            candidate_id="cand_sib",
            kc_id="KC_CLU_DBS_001",
            canonical_name="Core Point",
            topic_path_labels=["Clustering", "Density-based Clustering"],
            parent_topic_label="Density-based Clustering",
            text="A border point is not a core point but lies near a core point.",
            alignment_breakdown={"exact_name_phrase": True, "canonical_name_token_hits": 2, "competitor_token_hits": 2, "flags": {}},
        )
    )[0]
    assert row["role_eligibility"]["sibling_contrast"]
    assert not row["role_eligibility"]["positive_support_eligible"]


def test_fragmentary_candidate_only_gets_context_completion_candidate_when_target_bound():
    good, bad = _score_rows(
        _stage1_candidate_row(
            candidate_id="cand_frag_good",
            kc_id="KC_CLU_EVAL_012",
            canonical_name="Silhouette Coefficient",
            topic_path_labels=["Clustering", "Cluster Evaluation"],
            parent_topic_label="Cluster Evaluation",
            text="when the silhouette coefficient is high",
            source_block_text="The silhouette coefficient is useful when the silhouette coefficient is high for most instances.",
            structural_flags={"looks_fragmentary": True},
            support_profile={"has_context_completion_source": True, "fragmentary_surface": True},
            alignment_breakdown={"exact_name_phrase": True, "canonical_name_token_hits": 2, "flags": {}, "competitor_token_hits": 0},
        ),
        _stage1_candidate_row(
            candidate_id="cand_frag_bad",
            kc_id="KC_CLU_EVAL_012",
            canonical_name="Silhouette Coefficient",
            topic_path_labels=["Clustering", "Cluster Evaluation"],
            parent_topic_label="Cluster Evaluation",
            text="when the data are missing",
            source_block_text="when the data are missing",
            structural_flags={"looks_fragmentary": True},
            support_profile={"has_context_completion_source": True, "fragmentary_surface": True},
        ),
    )
    assert good["role_eligibility"]["context_completion_candidate"]
    assert not bad["role_eligibility"]["context_completion_candidate"]


def test_actual_formula_gets_credit_while_mathish_prose_gets_penalty():
    formula, prose = _score_rows(
        _stage1_candidate_row(
            candidate_id="cand_formula",
            kc_id="KC_EVAL_BASIC_005",
            canonical_name="Specificity",
            topic_path_labels=["Evaluation", "Basic Measures"],
            parent_topic_label="Basic Measures",
            text="Specificity = TN / (TN + FP).",
            alignment_breakdown={"exact_name_phrase": True, "canonical_name_token_hits": 1, "flags": {}, "competitor_token_hits": 0},
        ),
        _stage1_candidate_row(
            candidate_id="cand_mathish",
            kc_id="KC_EVAL_BASIC_005",
            canonical_name="Specificity",
            topic_path_labels=["Evaluation", "Basic Measures"],
            parent_topic_label="Basic Measures",
            text="The best parameter value is obtained after many iterations.",
            structural_flags={"looks_formula_like": True},
            support_profile={"formula_support_score": 2.0},
        ),
    )
    assert formula["formula_signal"]["is_actual_formula_notation"]
    assert formula["formula_signal"]["score"] > prose["formula_signal"]["score"]
    assert "fake_formula_prose" in prose["risk_flags"]


def test_structural_anchor_formula_candidate_can_be_formula_notation_without_exact_label_text():
    row = _score_rows(
        _stage1_candidate_row(
            candidate_id="cand_interval_formula",
            kc_id="KC_MUS_002",
            canonical_name="Interval Ratio",
            topic_path_labels=["Music Theory", "Composition Techniques"],
            parent_topic_label="Composition Techniques",
            patch_heading="Pitch Relations",
            text="IR = 2 * consonant_intervals / total_intervals.",
            source_block_text="IR = 2 * consonant_intervals / total_intervals.",
            structural_flags={"looks_formula_like": True, "looks_caption_like": False, "looks_prompt_like": False, "looks_fragmentary": False},
            support_profile={
                "formula_support_score": 1.75,
                "structural_anchor_support": True,
                "structural_anchor_support_score": 1.4,
                "shape_hint_formula_or_metric": True,
                "candidate_source": "structural_neighbor_from_profile_or_label_anchor",
            },
            alignment_breakdown={"canonical_name_token_hits": 0, "flags": {}, "competitor_token_hits": 0},
        )
    )[0]
    assert row["formula_signal"]["is_actual_formula_notation"]
    assert "structural_anchor_formula_support" in row["formula_signal"]["reasons"]
    assert "shape_hint_formula_metric_support" in row["formula_signal"]["reasons"]
    assert row["role_eligibility"]["formula_notation"]
    assert row["role_eligibility"]["positive_support_eligible"]


def test_cluster_definition_core_subject_overlap_is_definition_compatible():
    row = _score_rows(
        _stage1_candidate_row(
            candidate_id="cand_cluster_definition",
            kc_id="KC_CLU_CORE_001",
            canonical_name="Cluster Definition",
            topic_path_labels=["Clustering", "Core Concepts"],
            parent_topic_label="Core Concepts",
            text="A cluster is a dense region of objects that is surrounded by a region of low density.",
            source_block_text="A cluster is a dense region of objects that is surrounded by a region of low density.",
            support_profile={"preferred_support_role": "definitional_anchor"},
            alignment_breakdown={"canonical_name_token_hits": 1, "flags": {}, "competitor_token_hits": 0},
        )
    )[0]
    assert row["definition_framing_score"]["subject_alignment"] in {"aligned", "compatible"}
    assert row["role_eligibility"]["definition_kernel"]
    assert row["routing_recommendation"] == "positive_role_candidate"


def test_source_kc_mismatch_penalizes_unless_direct_target_cues_are_strong():
    weak, strong = _score_rows(
        _stage1_candidate_row(
            candidate_id="cand_mismatch_weak",
            kc_id="KC_CLU_CORE_002",
            canonical_name="Intra-cluster Distance",
            topic_path_labels=["Clustering", "Core Concepts"],
            parent_topic_label="Core Concepts",
            text="Distances are useful in many settings.",
            source_kc_id="KC_OTHER",
            source_canonical_name="Other Distance",
        ),
        _stage1_candidate_row(
            candidate_id="cand_mismatch_strong",
            kc_id="KC_CLU_CORE_002",
            canonical_name="Intra-cluster Distance",
            topic_path_labels=["Clustering", "Core Concepts"],
            parent_topic_label="Core Concepts",
            text="Intra-cluster distance is the total distance from cluster members to their centroid.",
            source_kc_id="KC_OTHER",
            source_canonical_name="Other Distance",
            alignment_breakdown={"exact_name_phrase": True, "canonical_name_token_hits": 2, "flags": {}, "competitor_token_hits": 0},
        ),
    )
    assert not weak["role_eligibility"]["positive_support_eligible"]
    assert strong["candidate_quality"]["overall_score"] > weak["candidate_quality"]["overall_score"]


def test_recurring_global_candidate_risk_is_flagged_deterministically():
    rows = _score_rows(
        _stage1_candidate_row(candidate_id="cand_r1", kc_id="KC_A", canonical_name="Concept A", text="A generic formula text.", patch_id="patch-r"),
        _stage1_candidate_row(candidate_id="cand_r2", kc_id="KC_B", canonical_name="Concept B", text="A generic formula text.", patch_id="patch-r"),
        _stage1_candidate_row(candidate_id="cand_r3", kc_id="KC_C", canonical_name="Concept C", text="A generic formula text.", patch_id="patch-r"),
    )
    for row in rows:
        assert "recurring_global_candidate" in row["risk_flags"]


def test_debug_reasons_and_risk_flags_are_deterministic():
    candidate = _stage1_candidate_row(
        candidate_id="cand_det",
        kc_id="KC_A",
        canonical_name="Concept A",
        text="Concept A is a target concept.",
        alignment_breakdown={"exact_name_phrase": True, "canonical_name_token_hits": 2, "flags": {}, "competitor_token_hits": 0},
    )
    first = score_candidate_row(candidate)
    second = score_candidate_row(candidate)
    assert first["debug_reasons"] == second["debug_reasons"]
    assert first["risk_flags"] == second["risk_flags"]


def _strict_fallback_definition_candidate(
    *,
    candidate_id: str,
    kc_id: str,
    canonical_name: str,
    text: str,
    topic_path_labels: list[str],
    parent_topic_label: str,
    matched_target_tokens: list[str],
    hierarchy_match_type: str = "local_context_branch_overlap",
    fallback_score: float = 6.05,
) -> dict[str, object]:
    """Build a generic source_surface_fallback definition-head candidate.

    This helper intentionally uses abstract curriculum terms. It should test the
    routing contract without depending on Data Mining, classification, clustering,
    or any specific course vocabulary.
    """
    support_profile = {
        "support_roles": ["fallback_surface_match", "definitional_anchor"],
        "preferred_support_role": "definitional_anchor",
        "definition_anchor_score": fallback_score,
        "explanatory_anchor_score": 5.3,
        "formula_support_score": 0.0,
        "context_completion_score": 0.0,
        "contamination_penalty": 0.0,
        "anchor_quality": "strong",
        "needs_context_completion": False,
        "has_context_completion_source": False,
        "formula_auxiliary_only": False,
        "contamination_exclusion_hint": False,
        "relation_like": True,
        "generic_context_only": False,
        "fragmentary_surface": False,
        "source_block_completion_used": False,
        "candidate_source": "source_surface_fallback",
        "fallback_tier": "definition_head",
        "fallback_reason": f"definition_head:head_token_text+{hierarchy_match_type}",
        "fallback_score": fallback_score,
        "fallback_score_reasons": [
            "tier:definition_head",
            "surface:text",
            "match:head_token_text",
            f"hierarchy:{hierarchy_match_type}",
            "strong_relation_or_definition",
        ],
        "matched_surface_terms": [],
        "matched_target_tokens": list(matched_target_tokens),
        "surface_match_type": "head_token_text",
        "hierarchy_match_type": hierarchy_match_type,
        "hierarchy_compatibility_signal": hierarchy_match_type,
        "target_branch_tokens": [],
        "fallback_caution_reason": "single_head_token_anchor",
    }

    alignment_breakdown = {
        "canonical_name_token_hits": 0,
        "alias_token_hits": 0,
        "name_or_alias_token_hits": 0,
        "competitor_token_hits": 0,
        "doc_mismatch": False,
        "exact_name_phrase": False,
        "exact_alias_phrase": False,
        "flags": {},
        "fallback_tier": "definition_head",
        "fallback_score": fallback_score,
        "hierarchy_match_type": hierarchy_match_type,
    }

    row = _stage1_candidate_row(
        candidate_id=candidate_id,
        kc_id=kc_id,
        canonical_name=canonical_name,
        topic_path_labels=topic_path_labels,
        parent_topic_label=parent_topic_label,
        text=text,
        source_block_text=text,
        support_profile=support_profile,
        alignment_breakdown=alignment_breakdown,
    )

    row["source_surface"] = "source_surface_fallback"
    row["provenance"].update(
        {
            "candidate_source": "source_surface_fallback",
            "fallback_tier": "definition_head",
            "fallback_reason": f"definition_head:head_token_text+{hierarchy_match_type}",
            "fallback_score": fallback_score,
            "fallback_score_reasons": [
                "tier:definition_head",
                "surface:text",
                "match:head_token_text",
                f"hierarchy:{hierarchy_match_type}",
                "strong_relation_or_definition",
            ],
            "matched_surface_terms": [],
            "matched_target_tokens": list(matched_target_tokens),
            "surface_match_type": "head_token_text",
            "hierarchy_match_type": hierarchy_match_type,
            "hierarchy_compatibility_signal": hierarchy_match_type,
            "candidate_bank_source_surface": "source_surface_fallback",
        }
    )
    return row


def test_strict_fallback_definition_head_can_rescue_clean_local_definition_candidate():
    row = _score_rows(
        _strict_fallback_definition_candidate(
            candidate_id="cand_fb_clean_definition",
            kc_id="KC_GENERIC_001",
            canonical_name="Coverage Problem",
            topic_path_labels=["Evidence Systems", "Coverage"],
            parent_topic_label="Coverage",
            text="Coverage failures are cases where observations are sparse and possible categories are not seen.",
            matched_target_tokens=["coverage"],
            hierarchy_match_type="local_context_branch_overlap",
        )
    )[0]

    assert row["lexical_target_binding"]["binding_strength"] == "weak"
    assert not row["lexical_target_binding"]["is_target_bound"]
    assert row["definition_framing_score"]["definition_style"] != "none"
    assert row["role_eligibility"]["strict_fallback_definition_kernel_override"]
    assert row["role_eligibility"]["definition_kernel"]
    assert row["role_eligibility"]["positive_support_eligible"]
    assert row["routing_recommendation"] == "positive_role_candidate"


def test_strict_fallback_definition_override_does_not_activate_for_process_phase_binding_route():
    row = _score_rows(
        _strict_fallback_definition_candidate(
            candidate_id="cand_fb_process_phase",
            kc_id="KC_GENERIC_002",
            canonical_name="Planning Phase",
            topic_path_labels=["Workflow", "Phases"],
            parent_topic_label="Phases",
            text="Planning is the process used to prepare an activity before execution.",
            matched_target_tokens=["planning"],
            hierarchy_match_type="strict_process_phase_binding",
        )
    )[0]

    assert row["lexical_target_binding"]["binding_strength"] == "weak"
    assert not row["role_eligibility"]["strict_fallback_definition_kernel_override"]


def test_strict_fallback_definition_override_rejects_wrong_source_kc_process_phase_route():
    candidate = _strict_fallback_definition_candidate(
        candidate_id="cand_fb_wrong_source_process_phase",
        kc_id="KC_GENERIC_002",
        canonical_name="Planning Phase",
        topic_path_labels=["Workflow", "Phases"],
        parent_topic_label="Phases",
        text="Planning is the process used to prepare an activity before execution.",
        matched_target_tokens=["planning"],
        hierarchy_match_type="strict_process_phase_binding",
    )
    candidate["source_kc_id"] = "KC_OTHER"
    candidate["source_canonical_name"] = "Other Concept"
    row = _score_rows(candidate)[0]

    assert row["lexical_target_binding"]["binding_strength"] == "weak"
    assert not row["role_eligibility"]["strict_fallback_definition_kernel_override"]
    assert not row["role_eligibility"]["positive_support_eligible"]
    assert row["routing_recommendation"] != "positive_role_candidate"


def test_definition_frame_with_head_binding_becomes_definition_kernel_candidate():
    row = _score_rows(
        _stage1_candidate_row(
            candidate_id="cand_lumen_definition",
            kc_id="KC_NEUTRAL_DEF_001",
            canonical_name="Lumen Definition",
            text="A lumen is a unit used to describe emitted visible light.",
            support_profile={"preferred_support_role": "definitional_anchor"},
            alignment_breakdown={"canonical_name_token_hits": 1, "flags": {}, "competitor_token_hits": 0},
        )
    )[0]

    assert row["definition_framing_score"]["definition_style"] != "none"
    assert row["role_eligibility"]["definition_kernel"]
    assert row["routing_recommendation"] == "positive_role_candidate"


def test_metric_gloss_with_local_explanation_becomes_explanatory_or_formula_candidate():
    row = _score_rows(
        _stage1_candidate_row(
            candidate_id="cand_vector_metric",
            kc_id="KC_NEUTRAL_METRIC_001",
            canonical_name="Vector Balance Metric",
            text="Vector balance metric = balanced components / all components, so larger values indicate steadier balance.",
            alignment_breakdown={"exact_name_phrase": True, "canonical_name_token_hits": 3, "flags": {}, "competitor_token_hits": 0},
            support_profile={"shape_hint_formula_or_metric": True, "formula_support_score": 1.2},
        )
    )[0]

    assert row["metric_gloss_framing"] > 0.0
    assert row["role_eligibility"]["positive_support_eligible"]
    assert row["routing_recommendation"] == "positive_role_candidate"


def test_bibliographic_reference_cannot_be_positive_role_candidate_even_with_exact_match():
    row = _score_rows(
        _stage1_candidate_row(
            candidate_id="cand_reference_exact",
            kc_id="KC_NEUTRAL_REF_001",
            canonical_name="Vector Balance Metric",
            text="References: Mira N. (2024). Vector Balance Metric. Journal of Neutral Measures.",
            patch_heading="References",
            alignment_breakdown={"exact_name_phrase": True, "canonical_name_token_hits": 3, "flags": {}, "competitor_token_hits": 0},
        )
    )[0]

    assert row["reference_like_signal"]["is_reference_like"]
    assert not row["role_eligibility"]["positive_support_eligible"]
    assert row["routing_recommendation"] in {"manual_review_candidate", "drop_from_positive_roles", "review_only_candidate"}


def test_fragmentary_formula_without_explanation_is_not_positive_support():
    row = _score_rows(
        _stage1_candidate_row(
            candidate_id="cand_fragmentary_formula",
            kc_id="KC_NEUTRAL_FORMULA_001",
            canonical_name="Vector Balance Metric",
            text="VBM = b / t",
            structural_flags={"looks_formula_like": True, "looks_fragmentary": True},
            support_profile={"formula_support_score": 0.8, "fragmentary_surface": True},
        )
    )[0]

    assert "fragmentary" in row["risk_flags"]
    assert not row["role_eligibility"]["positive_support_eligible"]


def test_sibling_competitor_sentence_moves_to_guardrail_or_manual_review():
    row = _score_rows(
        _stage1_candidate_row(
            candidate_id="cand_sibling_competitor",
            kc_id="KC_VECTOR_MAG_001",
            canonical_name="Magnitude Interpretation",
            text="Direction interpretation describes orientation and should not be confused with magnitude interpretation.",
            alignment_breakdown={"exact_name_phrase": True, "canonical_name_token_hits": 2, "competitor_token_hits": 2, "flags": {}},
            support_profile={"contamination_exclusion_hint": True},
        )
    )[0]

    assert not row["role_eligibility"]["positive_support_eligible"]
    assert row["routing_recommendation"] in {"guardrail_only_candidate", "manual_review_candidate", "drop_from_positive_roles"}


def test_load_candidate_bank_rows_supports_stage1_set_manifest_and_exact_kc_filter():
    root = TEST_ROOT
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    try:
        bank_path = root / "candidate_bank.jsonl"
        set_path = root / "stage1_set.json"
        rows = [
            _stage1_candidate_row(candidate_id="cand_a", kc_id="KC_A", canonical_name="Concept A", text="Concept A is here."),
            _stage1_candidate_row(candidate_id="cand_b", kc_id="KC_B", canonical_name="Concept B", text="Concept B is here."),
        ]
        bank_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        set_path.write_text(
            json.dumps({"artifacts": {"candidate_bank_jsonl": str(bank_path)}}),
            encoding="utf-8",
        )
        loaded, info = load_candidate_bank_rows(stage1_set_manifest=str(set_path), exact_kc_ids=["KC_B"])
        assert [row["kc_id"] for row in loaded] == ["KC_B"]
        assert Path(info["stage1_set_manifest"]).resolve() == set_path.resolve()
    finally:
        if root.exists():
            shutil.rmtree(root)


def test_build_scored_candidate_artifacts_creates_no_active_pointer():
    root = TEST_ROOT
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    try:
        out_root = root / "out"
        sets_root = out_root / "_sets"
        candidate_rows = [
            _stage1_candidate_row(candidate_id="cand_runner", kc_id="KC_A", canonical_name="Concept A", text="Concept A is defined here.")
        ]
        result = build_scored_candidate_artifacts(
            candidate_rows,
            run_id="runner_smoke",
            source_manifest="stage1_set.json",
            candidate_bank_jsonl_path="candidate_bank.jsonl",
            config_path="tests://stage2",
            output_root=out_root,
            set_manifest_root=sets_root,
        )
        assert result["run_id"] == "runner_smoke"
        assert not any(path.name.startswith("ACTIVE_STEP5X_V3") for path in sets_root.iterdir())
    finally:
        if root.exists():
            shutil.rmtree(root)


def main():
    test_one_output_row_per_input_candidate()
    test_candidate_id_preserved_and_scored_candidate_id_matches()
    test_no_seed_fields_propagated_and_no_pack_fields_emitted()
    test_shapeaware_shadow_fields_are_emitted_for_reviewable_rows()
    test_source_and_provenance_fields_are_preserved()
    test_target_bound_candidate_scores_higher_than_off_target_for_same_kc()
    test_broad_missing_values_rows_do_not_score_as_nb_specific_positive_support()
    test_same_kc_broad_missing_values_row_still_needs_family_alignment()
    test_broad_missing_data_mechanism_row_does_not_become_same_kc_positive_support()
    test_border_point_definition_does_not_become_core_point_definition_support()
    test_pure_context_completion_candidate_does_not_make_positive_support_eligible_true()
    test_core_point_transition_or_sibling_context_does_not_become_positive_support()
    test_measurement_noise_context_does_not_become_noise_point_positive_support()
    test_hyperparameter_selection_prose_does_not_become_formula_notation()
    test_source_block_only_procedure_row_does_not_become_positive_example_support()
    test_common_mistake_cross_validation_guidance_is_not_standalone_positive_support()
    test_clean_cross_validation_definition_is_standalone_positive_definition()
    test_internal_indices_sentence_beats_covariance_row()
    test_duplicate_tuples_support_beats_prompt_like_guardrail()
    test_duplicate_tuples_inconsistency_sentence_is_explanatory_not_example_or_procedure()
    test_weak_broad_specificity_or_external_recall_evidence_stays_weak()
    test_sibling_contrast_candidate_cannot_be_positive_support()
    test_fragmentary_candidate_only_gets_context_completion_candidate_when_target_bound()
    test_actual_formula_gets_credit_while_mathish_prose_gets_penalty()
    test_structural_anchor_formula_candidate_can_be_formula_notation_without_exact_label_text()
    test_cluster_definition_core_subject_overlap_is_definition_compatible()
    test_source_kc_mismatch_penalizes_unless_direct_target_cues_are_strong()
    test_recurring_global_candidate_risk_is_flagged_deterministically()
    test_debug_reasons_and_risk_flags_are_deterministic()
    test_strict_fallback_definition_head_can_rescue_clean_local_definition_candidate()
    test_strict_fallback_definition_override_does_not_activate_for_process_phase_binding_route()
    test_strict_fallback_definition_override_rejects_wrong_source_kc_process_phase_route()
    test_definition_frame_with_head_binding_becomes_definition_kernel_candidate()
    test_metric_gloss_with_local_explanation_becomes_explanatory_or_formula_candidate()
    test_bibliographic_reference_cannot_be_positive_role_candidate_even_with_exact_match()
    test_fragmentary_formula_without_explanation_is_not_positive_support()
    test_sibling_competitor_sentence_moves_to_guardrail_or_manual_review()
    test_load_candidate_bank_rows_supports_stage1_set_manifest_and_exact_kc_filter()
    test_build_scored_candidate_artifacts_creates_no_active_pointer()
    print("TEST_STEP5X_V3_SCORED_CANDIDATES_OK")


if __name__ == "__main__":
    main()
