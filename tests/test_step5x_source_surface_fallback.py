from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_SRC = REPO_ROOT / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from kc_l.retrieval_gate.source_surface_fallback import (
    SOURCE_SURFACE_FALLBACK,
    build_source_surface_fallback_candidates,
    compute_dynamic_broad_tokens,
)


def _kc_context(
    kc_id: str,
    canonical_name: str,
    *,
    aliases: list[str] | None = None,
    topic_path_labels: list[str] | None = None,
) -> dict[str, object]:
    labels = list(topic_path_labels or [])
    return {
        "kc_id": kc_id,
        "canonical_name": canonical_name,
        "aliases": list(aliases or []),
        "topic_path_ids": [],
        "topic_path_labels": labels,
        "parent_topic_id": "",
        "parent_topic_label": labels[-1] if labels else "",
    }


def _sentence_row(
    text: str,
    *,
    patch_heading: str,
    source_block_text: str | None = None,
    sentence_id: str = "DOC_1::block_1::s000",
    block_id: str = "DOC_1:block_1",
    doc_id: str = "DOC_1",
    sent_idx: int = 0,
    page_index: int = 1,
    is_formula_like: bool = False,
    is_definition_like: bool = False,
    is_heading_like: bool = False,
    is_procedure_like: bool = False,
) -> dict[str, object]:
    return {
        "sentence_text": text,
        "source_block_text": source_block_text or text,
        "doc_id": doc_id,
        "page_index": page_index,
        "block_id": block_id,
        "sentence_id": sentence_id,
        "sent_idx": sent_idx,
        "patch_id": "patch-1",
        "patch_heading": patch_heading,
        "reveal_group_id": "group-1",
        "layer": "mineru",
        "bbox": [1.0, 2.0, 3.0, 4.0],
        "char_start": 0,
        "char_end": len(text),
        "is_meta": False,
        "is_nav_boilerplate": False,
        "is_author_affiliation": False,
        "is_transition_text": False,
        "is_heading_like": is_heading_like,
        "is_formula_like": is_formula_like,
        "is_definition_like": is_definition_like,
        "is_procedure_like": is_procedure_like,
        "is_example_like": False,
    }


def _build_candidates(
    sentence_rows: list[dict[str, object]],
    *,
    selected_kcs: list[dict[str, object]],
    registry_kcs: list[dict[str, object]] | None = None,
    existing_candidate_rows: list[dict[str, object]] | None = None,
    config: dict[str, object] | None = None,
) -> dict[str, object]:
    merged_config = {
        "enabled": True,
        "max_fallback_per_kc": 8,
        "min_score": 4.0,
        "require_surface_match": True,
        "require_hierarchy_compatibility": True,
        "dynamic_broad_token_min_doc_frequency": 2,
        "allow_acronym_surface_match": True,
        "reject_prompt_like": True,
        "reject_fragmentary": True,
        "reject_formula_only_without_surface": True,
    }
    merged_config.update(config or {})
    return build_source_surface_fallback_candidates(
        sentence_rows,
        selected_kc_contexts=selected_kcs,
        registry_kc_contexts=registry_kcs or selected_kcs,
        existing_candidate_rows=existing_candidate_rows or [],
        config=merged_config,
        sentence_source_manifest="sentence_manifest.json",
        sentence_source_jsonl="sentence_corpus.jsonl",
    )


def test_exact_phrase_fallback_still_works() -> None:
    kc = _kc_context(
        "KC_A",
        "Learning Phase",
        topic_path_labels=["Classification", "Classification Underpinnings"],
    )
    registry = [
        kc,
        _kc_context("KC_B", "Entropy", topic_path_labels=["Classification", "Decision Trees"]),
        _kc_context("KC_C", "Prior Probability", topic_path_labels=["Classification", "Naive Bayes"]),
    ]
    result = _build_candidates(
        [
            _sentence_row(
                "The learning phase is the stage where the classifier is built from training data.",
                patch_heading="Classification Underpinnings",
                is_definition_like=True,
            )
        ],
        selected_kcs=[kc],
        registry_kcs=registry,
    )
    rows = result["rows"]
    assert len(rows) == 1
    row = rows[0]
    assert row["candidate_source"] == SOURCE_SURFACE_FALLBACK
    assert row["fallback_tier"] == "exact_surface"
    assert row["surface_match_type"] == "exact_canonical_text"
    assert row["hierarchy_match_type"] == "heading_branch_overlap"
    assert row["matched_surface_terms"] == ["Learning Phase"]


def test_unrelated_single_head_token_match_is_rejected() -> None:
    kc = _kc_context(
        "KC_A",
        "Cluster Definition",
        topic_path_labels=["Clustering", "Cluster Foundations"],
    )
    registry = [
        kc,
        _kc_context("KC_B", "Cluster Center", topic_path_labels=["Clustering", "Cluster Foundations"]),
        _kc_context("KC_C", "Silhouette Coefficient", topic_path_labels=["Clustering", "Cluster Evaluation"]),
    ]
    result = _build_candidates(
        [
            _sentence_row(
                "A cluster is evaluated with internal quality measures.",
                patch_heading="Cluster Evaluation",
                is_definition_like=True,
            )
        ],
        selected_kcs=[kc],
        registry_kcs=registry,
    )
    assert result["rows"] == []
    assert result["stats"]["rejected_counts"]["hierarchy_mismatch"] >= 1


def test_generic_suffix_stripping_recovers_definition_style_source_sentence() -> None:
    kc = _kc_context(
        "KC_A",
        "Cluster Definition",
        topic_path_labels=["Clustering", "Cluster Foundations"],
    )
    registry = [
        kc,
        _kc_context("KC_B", "Cluster Center", topic_path_labels=["Clustering", "Cluster Foundations"]),
        _kc_context("KC_C", "Silhouette Coefficient", topic_path_labels=["Clustering", "Cluster Evaluation"]),
    ]
    result = _build_candidates(
        [
            _sentence_row(
                "A cluster is a collection of data objects treated as a single group.",
                patch_heading="Cluster Foundations",
                is_definition_like=True,
            )
        ],
        selected_kcs=[kc],
        registry_kcs=registry,
    )
    rows = result["rows"]
    assert len(rows) == 1
    row = rows[0]
    assert row["fallback_tier"] == "definition_head"
    assert row["matched_target_tokens"] == ["cluster"]
    assert row["hierarchy_compatibility_signal"] == "heading_branch_overlap"


def test_token_fallback_with_hierarchy_and_scope_cue_is_retained() -> None:
    kc = _kc_context(
        "KC_A",
        "Zero-Frequency Problem",
        topic_path_labels=["Classification", "Naive Bayes", "Probability Estimation"],
    )
    registry = [
        kc,
        _kc_context("KC_B", "Prior Probability", topic_path_labels=["Classification", "Naive Bayes", "Probability Estimation"]),
        _kc_context("KC_C", "Posterior Probability", topic_path_labels=["Classification", "Naive Bayes", "Probability Estimation"]),
    ]
    result = _build_candidates(
        [
            _sentence_row(
                "Zero frequencies occur when a category is absent from the training data.",
                patch_heading="Naive Bayes Probability Estimation",
                is_definition_like=True,
            )
        ],
        selected_kcs=[kc],
        registry_kcs=registry,
    )
    rows = result["rows"]
    assert len(rows) == 1
    row = rows[0]
    assert row["fallback_tier"] == "target_token"
    assert row["matched_target_tokens"] == ["zero", "frequency"]
    assert row["surface_match_type"] == "target_token_overlap_text"


def test_token_fallback_without_relation_or_scope_is_rejected() -> None:
    kc = _kc_context(
        "KC_A",
        "Zero-Frequency Problem",
        topic_path_labels=["Classification", "Naive Bayes", "Probability Estimation"],
    )
    registry = [
        kc,
        _kc_context("KC_B", "Prior Probability", topic_path_labels=["Classification", "Naive Bayes", "Probability Estimation"]),
        _kc_context("KC_C", "Posterior Probability", topic_path_labels=["Classification", "Naive Bayes", "Probability Estimation"]),
    ]
    result = _build_candidates(
        [
            _sentence_row(
                "Zero frequency counts highlighted in bold in the table below.",
                patch_heading="Naive Bayes Probability Estimation",
            )
        ],
        selected_kcs=[kc],
        registry_kcs=registry,
    )
    assert result["rows"] == []
    assert result["stats"]["rejected_counts"]["token_match_without_relation_or_scope"] >= 1


def test_parenthetical_acronym_alias_match_works_generically() -> None:
    kc = _kc_context(
        "KC_A",
        "Term Frequency-Inverse Document Frequency (TF-IDF)",
        topic_path_labels=["Information Retrieval", "Text Weighting"],
    )
    registry = [
        kc,
        _kc_context("KC_B", "Bag of Words", topic_path_labels=["Information Retrieval", "Text Representation"]),
        _kc_context("KC_C", "Inverse Document Frequency", topic_path_labels=["Information Retrieval", "Text Weighting"]),
    ]
    result = _build_candidates(
        [
            _sentence_row(
                "TF-IDF weights rare terms more heavily than common terms.",
                patch_heading="Text Weighting",
            )
        ],
        selected_kcs=[kc],
        registry_kcs=registry,
    )
    rows = result["rows"]
    assert len(rows) == 1
    assert rows[0]["fallback_tier"] == "exact_surface"
    assert rows[0]["surface_match_type"] == "exact_acronym_text"
    assert "TF-IDF" in rows[0]["matched_surface_terms"]


def test_prompt_like_candidate_is_rejected() -> None:
    kc = _kc_context(
        "KC_A",
        "Cluster Definition",
        topic_path_labels=["Clustering", "Cluster Foundations"],
    )
    result = _build_candidates(
        [
            _sentence_row(
                "Explain what cluster definition means in your own words.",
                patch_heading="Cluster Foundations",
            )
        ],
        selected_kcs=[kc],
    )
    assert result["rows"] == []
    assert result["stats"]["rejected_counts"]["prompt_like"] >= 1


def test_fragmentary_candidate_is_rejected() -> None:
    kc = _kc_context(
        "KC_A",
        "Cluster Definition",
        topic_path_labels=["Clustering", "Cluster Foundations"],
    )
    result = _build_candidates(
        [
            _sentence_row(
                "Cluster definition and",
                patch_heading="Cluster Foundations",
            )
        ],
        selected_kcs=[kc],
    )
    assert result["rows"] == []
    assert result["stats"]["rejected_counts"]["fragmentary"] >= 1


def test_caption_only_candidate_is_rejected() -> None:
    kc = _kc_context(
        "KC_A",
        "Cluster Definition",
        topic_path_labels=["Clustering", "Cluster Foundations"],
    )
    result = _build_candidates(
        [
            _sentence_row(
                "Figure 3. Cluster definition in a toy dataset.",
                patch_heading="Cluster Foundations",
            )
        ],
        selected_kcs=[kc],
    )
    assert result["rows"] == []
    assert result["stats"]["rejected_counts"]["caption_like"] >= 1


def test_formula_only_candidate_without_target_binding_is_rejected() -> None:
    kc = _kc_context(
        "KC_A",
        "Silhouette Coefficient",
        topic_path_labels=["Clustering", "Cluster Evaluation"],
    )
    registry = [
        kc,
        _kc_context("KC_B", "Davies-Bouldin Index", topic_path_labels=["Clustering", "Cluster Evaluation"]),
        _kc_context("KC_C", "Cluster Center", topic_path_labels=["Clustering", "Cluster Foundations"]),
    ]
    result = _build_candidates(
        [
            _sentence_row(
                "s(i) = (b(i) - a(i)) / max(a(i), b(i))",
                patch_heading="Cluster Evaluation",
                source_block_text="Silhouette Coefficient: s(i) = (b(i) - a(i)) / max(a(i), b(i))",
                is_formula_like=True,
            )
        ],
        selected_kcs=[kc],
        registry_kcs=registry,
    )
    assert result["rows"] == []
    assert result["stats"]["rejected_counts"]["formula_only_without_surface"] >= 1


def test_deduplication_prevents_duplicate_fallback_candidates() -> None:
    kc = _kc_context(
        "KC_A",
        "Learning Phase",
        topic_path_labels=["Classification", "Classification Underpinnings"],
    )
    sentence = _sentence_row(
        "The learning phase is the stage where the classifier is built from training data.",
        patch_heading="Classification Underpinnings",
        sentence_id="DOC_1::block_1::s001",
        block_id="DOC_1:block_1",
        doc_id="DOC_1",
        is_definition_like=True,
    )
    existing = [
        {
            "kc_id": "KC_A",
            "sentence_id": "DOC_1::block_1::s001",
            "block_id": "DOC_1:block_1",
            "doc_id": "DOC_1",
            "text": sentence["sentence_text"],
        }
    ]
    result = _build_candidates(
        [sentence],
        selected_kcs=[kc],
        existing_candidate_rows=existing,
    )
    assert result["rows"] == []
    assert result["stats"]["dropped_duplicate_count"] == 1


def test_per_kc_cap_is_respected() -> None:
    kc = _kc_context(
        "KC_A",
        "Learning Phase",
        topic_path_labels=["Classification", "Classification Underpinnings"],
    )
    registry = [
        kc,
        _kc_context("KC_B", "Entropy", topic_path_labels=["Classification", "Decision Trees"]),
        _kc_context("KC_C", "Prior Probability", topic_path_labels=["Classification", "Naive Bayes"]),
    ]
    result = _build_candidates(
        [
            _sentence_row(
                "The learning phase is when the model parameters are estimated from training data.",
                patch_heading="Classification Underpinnings",
                sentence_id="DOC_1::block_1::s000",
                is_definition_like=True,
            ),
            _sentence_row(
                "The learning phase is the training stage of the classifier.",
                patch_heading="Classification Underpinnings",
                sentence_id="DOC_1::block_2::s000",
                is_definition_like=True,
            ),
            _sentence_row(
                "The learning phase is completed before prediction begins.",
                patch_heading="Classification Underpinnings",
                sentence_id="DOC_1::block_3::s000",
                is_definition_like=True,
            ),
        ],
        selected_kcs=[kc],
        registry_kcs=registry,
        config={"max_fallback_per_kc": 2},
    )
    assert len(result["rows"]) == 2
    assert result["stats"]["rejected_counts"]["per_kc_cap"] == 1


def test_broad_tokens_are_computed_dynamically_and_not_from_hardcoded_vocabulary() -> None:
    contexts = [
        _kc_context("KC_A", "Concept A", topic_path_labels=["SharedBranch", "Alpha Parent"]),
        _kc_context("KC_B", "Concept B", topic_path_labels=["SharedBranch", "Beta Parent"]),
        _kc_context("KC_C", "Concept C", topic_path_labels=["SharedBranch", "Gamma Parent"]),
    ]
    broad_tokens = compute_dynamic_broad_tokens(contexts, min_doc_frequency=2)
    assert "sharedbranch" in broad_tokens


def test_no_seed_fields_propagate_from_fallback_rows() -> None:
    kc = _kc_context(
        "KC_A",
        "Cluster Definition",
        topic_path_labels=["Clustering", "Cluster Foundations"],
    )
    result = _build_candidates(
        [
            _sentence_row(
                "A cluster is a collection of data objects treated as a single group.",
                patch_heading="Cluster Foundations",
                is_definition_like=True,
            )
        ],
        selected_kcs=[kc],
    )
    row_json = json.dumps(result["rows"][0], sort_keys=True)
    assert "seed_definition" not in row_json
    assert "seed_keywords" not in row_json


def test_fallback_metadata_is_explicit_and_auditable() -> None:
    kc = _kc_context(
        "KC_A",
        "Cluster Definition",
        topic_path_labels=["Clustering", "Cluster Foundations"],
    )
    result = _build_candidates(
        [
            _sentence_row(
                "A cluster is a collection of data objects treated as a single group.",
                patch_heading="Cluster Foundations",
                is_definition_like=True,
            )
        ],
        selected_kcs=[kc],
    )
    row = result["rows"][0]
    assert row["candidate_source"] == SOURCE_SURFACE_FALLBACK
    assert row["fallback_tier"] == "definition_head"
    assert row["fallback_reason"].startswith("definition_head:")
    assert row["fallback_score"] >= 4.0
    assert row["fallback_score_reasons"]
    assert row["matched_target_tokens"] == ["cluster"]
    assert row["hierarchy_compatibility_signal"] == "heading_branch_overlap"
    assert row["source_heading_text"] == "Cluster Foundations"


def test_pedagogical_descriptor_is_split_from_concept_head() -> None:
    kc = _kc_context(
        "KC_NEUTRAL_001",
        "Lumen Definition",
        topic_path_labels=["Neutral Systems", "Optical Concepts"],
    )
    result = _build_candidates(
        [
            _sentence_row(
                "A lumen is a unit used to describe emitted visible light.",
                patch_heading="Optical Concepts",
                is_definition_like=True,
            )
        ],
        selected_kcs=[kc],
    )

    row = result["rows"][0]
    assert row["fallback_tier"] == "definition_head"
    assert row["matched_target_tokens"] == ["lumen"]
    assert row["retrieval_intent"] == "head_term_plus_definition_frame"
    assert row["evidence_shape_match"] == "definition_or_gloss"


def test_broad_head_term_is_not_destroyed_when_it_is_the_only_semantic_head() -> None:
    kc = _kc_context(
        "KC_NEUTRAL_002",
        "Vector",
        topic_path_labels=["Neutral Systems", "Vector Reasoning"],
    )
    registry = [
        kc,
        _kc_context("KC_NEUTRAL_003", "Vector Magnitude", topic_path_labels=["Neutral Systems", "Vector Reasoning"]),
        _kc_context("KC_NEUTRAL_004", "Vector Direction", topic_path_labels=["Neutral Systems", "Vector Reasoning"]),
    ]
    result = _build_candidates(
        [
            _sentence_row(
                "A vector is a quantity with both size and orientation.",
                patch_heading="Vector Reasoning",
                is_definition_like=True,
            )
        ],
        selected_kcs=[kc],
        registry_kcs=registry,
        config={"dynamic_broad_token_min_doc_frequency": 2},
    )

    assert result["rows"]
    assert result["rows"][0]["matched_target_tokens"] == ["vector"]


def test_head_term_plus_definition_frame_beats_generic_object_sentence() -> None:
    kc = _kc_context(
        "KC_NEUTRAL_005",
        "Lumen Definition",
        topic_path_labels=["Neutral Systems", "Optical Concepts"],
    )
    result = _build_candidates(
        [
            _sentence_row(
                "An object may store a lumen attribute in a metadata table.",
                patch_heading="Optical Concepts",
                sentence_id="DOC_1::block_1::s001",
            ),
            _sentence_row(
                "A lumen is a measure of visible light emitted by a source.",
                patch_heading="Optical Concepts",
                sentence_id="DOC_1::block_1::s002",
                is_definition_like=True,
            ),
        ],
        selected_kcs=[kc],
    )

    assert result["rows"]
    assert result["rows"][0]["text"] == "A lumen is a measure of visible light emitted by a source."
    assert result["rows"][0]["retrieval_intent"] == "head_term_plus_definition_frame"


def test_metric_gloss_candidate_is_retained_when_exact_metric_surface_exists() -> None:
    kc = _kc_context(
        "KC_NEUTRAL_006",
        "Vector Balance Metric",
        topic_path_labels=["Neutral Systems", "Vector Reasoning"],
    )
    result = _build_candidates(
        [
            _sentence_row(
                "The vector balance metric is the ratio of balanced components to all components.",
                patch_heading="Vector Reasoning",
                is_definition_like=True,
            )
        ],
        selected_kcs=[kc],
    )

    row = result["rows"][0]
    assert row["fallback_tier"] == "exact_surface"
    assert row["retrieval_intent"] in {"label_exact_surface", "head_term_plus_metric_frame"}
    assert row["evidence_shape_match"] in {"definition_or_gloss", "formula_or_metric", "metric_gloss"}
    assert row["authority_contract"] == "step5x_must_verify_against_source_rows"


def test_legitimate_problem_term_is_not_prompt_rejected() -> None:
    kc = _kc_context(
        "KC_A",
        "Zero-Frequency Problem",
        topic_path_labels=["Classification", "Naive Bayes", "Probability Estimation"],
    )
    registry = [
        kc,
        _kc_context("KC_B", "Prior Probability", topic_path_labels=["Classification", "Naive Bayes", "Probability Estimation"]),
        _kc_context("KC_C", "Posterior Probability", topic_path_labels=["Classification", "Naive Bayes", "Probability Estimation"]),
    ]
    result = _build_candidates(
        [
            _sentence_row(
                "The zero-frequency problem occurs when a category is absent from the training data.",
                patch_heading="Naive Bayes Probability Estimation",
                is_definition_like=True,
            )
        ],
        selected_kcs=[kc],
        registry_kcs=registry,
    )
    rows = result["rows"]
    assert len(rows) == 1
    assert rows[0]["fallback_tier"] == "exact_surface"
    assert rows[0]["surface_match_type"] == "exact_canonical_text"
    assert "prompt_like" not in result["stats"].get("rejected_counts", {})


def test_problem_prefix_prompt_is_still_rejected() -> None:
    kc = _kc_context(
        "KC_A",
        "Posterior Probability",
        topic_path_labels=["Classification", "Naive Bayes", "Probability Estimation"],
    )
    result = _build_candidates(
        [
            _sentence_row(
                "Problem 3: posterior probability for the following instance.",
                patch_heading="Naive Bayes Probability Estimation",
                is_definition_like=True,
            )
        ],
        selected_kcs=[kc],
    )
    assert result["rows"] == []
    assert result["stats"]["rejected_counts"]["prompt_like"] >= 1


def test_source_block_only_anchor_cannot_emit_unanchored_sentence() -> None:
    kc = _kc_context(
        "KC_A",
        "Zero-Frequency Problem",
        topic_path_labels=["Classification", "Naive Bayes", "Probability Estimation"],
    )
    result = _build_candidates(
        [
            _sentence_row(
                "Many classification problems involve uncertainty.",
                patch_heading="Naive Bayes Probability Estimation",
                source_block_text=(
                    "Note that zero conditional probabilities arise when the number of training "
                    "instances is small and an attribute value is absent."
                ),
                is_definition_like=True,
            )
        ],
        selected_kcs=[kc],
    )
    assert result["rows"] == []
    assert result["stats"]["rejected_counts"]["source_block_only_anchor_without_emitted_text_anchor"] >= 1


def test_single_head_definition_rejects_modified_subject() -> None:
    kc = _kc_context(
        "KC_A",
        "Cluster Definition",
        topic_path_labels=["Clustering", "Cluster Foundations"],
    )
    result = _build_candidates(
        [
            _sentence_row(
                "A cluster centroid represents the mean value of the objects in the cluster.",
                patch_heading="Cluster Foundations",
                is_definition_like=True,
            )
        ],
        selected_kcs=[kc],
    )
    assert result["rows"] == []
    rejected = result["stats"]["rejected_counts"]
    assert (
        rejected.get("single_head_definition_without_strict_text_binding", 0) >= 1
        or rejected.get("formula_only_without_surface", 0) >= 1
        or rejected.get("hierarchy_mismatch", 0) >= 1
        or rejected.get("prompt_like", 0) >= 1
        or rejected.get("fragmentary", 0) >= 1
    )


def test_single_head_phase_bare_learning_process_without_strong_binding_is_rejected() -> None:
    kc = _kc_context(
        "KC_A",
        "Learning Phase",
        topic_path_labels=["Classification", "Classification Underpinnings"],
    )
    result = _build_candidates(
        [
            _sentence_row(
                "This transformation can speed up the learning process.",
                patch_heading="",
                is_definition_like=True,
            )
        ],
        selected_kcs=[kc],
    )
    assert result["rows"] == []
    rejected = result["stats"]["rejected_counts"]
    assert (
        rejected.get("hierarchy_mismatch", 0) >= 1
        or rejected.get("single_head_phase_without_process_binding", 0) >= 1
    )


def test_single_head_phase_process_binding_can_bypass_missing_branch_when_strong() -> None:
    kc = _kc_context(
        "KC_A",
        "Learning Phase",
        topic_path_labels=["Classification", "Classification Underpinnings"],
    )
    registry = [
        kc,
        _kc_context("KC_B", "Querying Phase", topic_path_labels=["Classification", "Classification Underpinnings"]),
        _kc_context("KC_C", "Prior Probability", topic_path_labels=["Classification", "Naive Bayes"]),
    ]
    result = _build_candidates(
        [
            _sentence_row(
                "The process of using a learning algorithm to build a classification model from training data is known as induction.",
                patch_heading="General Framework",
                is_definition_like=True,
            )
        ],
        selected_kcs=[kc],
        registry_kcs=registry,
    )
    rows = result["rows"]
    assert len(rows) == 1
    assert rows[0]["fallback_tier"] == "definition_head"
    assert rows[0]["matched_target_tokens"] == ["learning"]
    assert rows[0]["hierarchy_match_type"] == "strict_process_phase_binding"


def test_single_head_phase_process_binding_with_hierarchy_is_accepted() -> None:
    kc = _kc_context(
        "KC_A",
        "Learning Phase",
        topic_path_labels=["Classification", "Classification Underpinnings"],
    )
    registry = [
        kc,
        _kc_context("KC_B", "Querying Phase", topic_path_labels=["Classification", "Classification Underpinnings"]),
        _kc_context("KC_C", "Prior Probability", topic_path_labels=["Classification", "Naive Bayes"]),
    ]
    result = _build_candidates(
        [
            _sentence_row(
                "The process of using a learning algorithm to build a classification model from training data is known as induction.",
                patch_heading="Classification Underpinnings",
                is_definition_like=True,
            )
        ],
        selected_kcs=[kc],
        registry_kcs=registry,
    )
    rows = result["rows"]
    assert len(rows) == 1
    assert rows[0]["fallback_tier"] == "definition_head"
    assert rows[0]["matched_target_tokens"] == ["learning"]


def test_single_head_problem_binding_keeps_anchored_nonexact_sentence() -> None:
    kc = _kc_context(
        "KC_A",
        "Zero-Frequency Problem",
        topic_path_labels=["Classification", "Naive Bayes", "Probability Estimation"],
    )
    registry = [
        kc,
        _kc_context("KC_B", "Prior Probability", topic_path_labels=["Classification", "Naive Bayes", "Probability Estimation"]),
        _kc_context("KC_C", "Posterior Probability", topic_path_labels=["Classification", "Naive Bayes", "Probability Estimation"]),
    ]
    result = _build_candidates(
        [
            _sentence_row(
                "Note that zero conditional probabilities arise when the number of training instances is small.",
                patch_heading="",
                is_definition_like=True,
            )
        ],
        selected_kcs=[kc],
        registry_kcs=registry,
    )
    rows = result["rows"]
    assert len(rows) == 1
    assert rows[0]["fallback_tier"] == "definition_head"
    assert rows[0]["matched_target_tokens"] == ["zero"]



def test_single_head_definition_rejects_passive_cluster_use() -> None:
    kc = _kc_context(
        "KC_A",
        "Cluster Definition",
        topic_path_labels=["Clustering", "Cluster Foundations"],
    )
    result = _build_candidates(
        [
            _sentence_row(
                "Data objects that belong to the same cluster are taken to be nearest neighbors of each other.",
                patch_heading="",
                is_definition_like=True,
            )
        ],
        selected_kcs=[kc],
    )
    assert result["rows"] == []
    rejected = result["stats"]["rejected_counts"]
    assert (
        rejected.get("single_head_definition_without_strict_text_binding", 0) >= 1
        or rejected.get("formula_only_without_surface", 0) >= 1
        or rejected.get("hierarchy_mismatch", 0) >= 1
        or rejected.get("prompt_like", 0) >= 1
        or rejected.get("fragmentary", 0) >= 1
    )


def test_single_head_definition_rejects_equation_assignment_use() -> None:
    kc = _kc_context(
        "KC_A",
        "Cluster Definition",
        topic_path_labels=["Clustering", "Cluster Foundations"],
    )
    result = _build_candidates(
        [
            _sentence_row(
                "Each cluster is given by Equation 7.20.",
                patch_heading="",
                is_definition_like=True,
            )
        ],
        selected_kcs=[kc],
    )
    assert result["rows"] == []
    rejected = result["stats"]["rejected_counts"]
    assert (
        rejected.get("single_head_definition_without_strict_text_binding", 0) >= 1
        or rejected.get("formula_only_without_surface", 0) >= 1
        or rejected.get("hierarchy_mismatch", 0) >= 1
        or rejected.get("prompt_like", 0) >= 1
        or rejected.get("fragmentary", 0) >= 1
    )


def test_single_head_definition_accepts_notion_of_target_definition_sentence_with_hierarchy() -> None:
    kc = _kc_context(
        "KC_A",
        "Cluster Definition",
        topic_path_labels=["Clustering", "Cluster Foundations"],
    )
    result = _build_candidates(
        [
            _sentence_row(
                "In many applications, the notion of a cluster is not well defined.",
                patch_heading="Cluster Foundations",
                is_definition_like=True,
            )
        ],
        selected_kcs=[kc],
    )
    rows = result["rows"]
    assert len(rows) == 1
    assert rows[0]["fallback_tier"] == "definition_head"
    assert rows[0]["matched_target_tokens"] == ["cluster"]


def test_single_head_phase_rejects_cross_branch_feature_selection_learning() -> None:
    kc = _kc_context(
        "KC_A",
        "Learning Phase",
        topic_path_labels=["Classification", "Classification Underpinnings"],
    )
    registry = [
        kc,
        _kc_context("KC_B", "Querying Phase", topic_path_labels=["Classification", "Classification Underpinnings"]),
        _kc_context("KC_C", "Prior Probability", topic_path_labels=["Classification", "Naive Bayes"]),
    ]
    result = _build_candidates(
        [
            _sentence_row(
                "The name filter proceeds from filtering the undesirable features out before learning.",
                patch_heading="Filter, Wrapper and Embedded Feature Selection",
                source_block_text=(
                    "There is an extensive research effort in the development of indirect performance measures "
                    "for selecting features. This model is called the filter model. The filter approach operates "
                    "independently of the method subsequently employed. The name filter proceeds from filtering "
                    "the undesirable features out before learning."
                ),
                is_definition_like=True,
            )
        ],
        selected_kcs=[kc],
        registry_kcs=registry,
    )
    assert result["rows"] == []
    rejected = result["stats"]["rejected_counts"]
    assert (
        rejected.get("single_head_phase_without_process_binding", 0) >= 1
        or rejected.get("hierarchy_mismatch", 0) >= 1
        or rejected.get("context_mismatch", 0) >= 1
    )


def _run_direct() -> None:
    module = sys.modules[__name__]
    for name in sorted(dir(module)):
        if not name.startswith("test_"):
            continue
        value = getattr(module, name)
        if callable(value):
            value()
    print("TEST_STEP5X_SOURCE_SURFACE_FALLBACK_OK")


if __name__ == "__main__":
    _run_direct()
