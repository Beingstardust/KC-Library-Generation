from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import kc_l.retrieval_profile.builder as builder_mod
from kc_l.retrieval_profile.builder import build_profiles, collect_profile_windows, post_validate_model_output
from kc_l.retrieval_profile.output_hardening import harden_profile_output, harden_query_variants
from kc_l.retrieval_windowing.source_window_kernel import collect_profile_windows_with_source_surface_kernel
from kc_l.retrieval_profile.deterministic import deterministic_label_variants, phrase_present, score_snippet_for_kc
from kc_l.retrieval_profile.schema import ACTIVE_CUE_TYPES, PROFILE_CONTRACT_VERSION, validate_profile_collection


TMP = REPO_ROOT / ".codex_tmp_step5p_profile_test"


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_deterministic_variants():
    variants = deterministic_label_variants("Zero-Frequency Problem", [])
    terms = {v["term"].lower() for v in variants}
    assert "zero-frequency problem" in terms
    assert "zero frequency problem" in terms
    assert "zero frequency" in terms


def test_profile_builder_no_model():
    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir(parents=True)

    registry = TMP / "kc_registry.jsonl"
    source = TMP / "sentence_overlay.jsonl"

    write_jsonl(registry, [
        {
            "kc_id": "KC_TEST_001",
            "canonical_name": "Zero-Frequency Problem",
            "aliases": [],
            "parent_topic_id": "topic::nb",
            "parent_topic_label": "Naive Bayes",
            "topic_path_labels": ["Classification", "Naive Bayes"],
        },
        {
            "kc_id": "KC_TEST_002",
            "canonical_name": "Laplace Estimator",
            "aliases": [],
            "parent_topic_id": "topic::nb",
            "parent_topic_label": "Naive Bayes",
            "topic_path_labels": ["Classification", "Naive Bayes"],
        },
    ])

    write_jsonl(source, [
        {
            "sentence_id": "s1",
            "text": "The zero-frequency problem occurs when a combination of attribute values and class labels is never observed, resulting in a zero conditional probability.",
            "field_path": "sentence.text",
            "doc_id": "DOC_TEST",
            "page_index": 10,
            "patch_heading": "Handling Zero Conditional Probabilities",
        },
        {
            "sentence_id": "s2",
            "text": "References: Zero-frequency effects in unrelated signal processing literature.",
            "field_path": "references.text",
            "doc_id": "DOC_TEST",
            "page_index": 99,
        },
        {
            "sentence_id": "s2b",
            "patch_heading": "Zero-Frequency Problem",
            "doc_id": "DOC_TEST",
            "page_index": 12,
        },
        {
            "sentence_id": "s3",
            "text": "The Laplace estimator adds one to every count.",
            "field_path": "sentence.text",
            "doc_id": "DOC_TEST",
            "page_index": 11,
            "patch_heading": "Laplace Estimator",
        },
    ])

    result = build_profiles(
        registry_jsonl=registry,
        source_overlay_jsonl=source,
        output_root=TMP / "out",
        set_manifest_root=TMP / "out" / "_sets",
        run_id="test_no_model",
        exact_kc_ids=["KC_TEST_001"],
        limit_kcs=None,
        max_snippets_per_kc=10,
        min_snippet_score=1.0,
        use_model=False,
        model_config={},
    )

    assert result["stats"]["counts"]["profiles"] == 1
    rows = []
    profile_path = TMP / "out" / "test_no_model" / "kc_retrieval_profiles.jsonl"
    for line in profile_path.read_text(encoding="utf-8").splitlines():
        rows.append(json.loads(line))

    assert rows[0]["kc_id"] == "KC_TEST_001"
    assert rows[0]["profile_status"] in {"weak", "usable"}
    assert "seed_definition" not in json.dumps(rows[0]).lower()
    assert rows[0]["audit"]["candidate_snippet_count"] >= 1
    assert any(s.get("snippet_id") == "s1" for s in rows[0]["audit"]["candidate_snippets"])
    assert rows[0]["concept_head"]
    assert rows[0]["normalized_surface_variants"]
    assert rows[0]["expected_evidence_needs"]

    validation = validate_profile_collection(rows)
    assert validation["ok"], validation


def test_quarantined_model_suggestion_not_active():
    profile = {
        "profile_contract_version": "kc_retrieval_profile_v1",
        "kc_id": "KC_TEST_003",
        "canonical_name": "Some KC",
        "aliases": [],
        "topic_path_labels": [],
        "parent_topic_label": "",
        "sibling_labels": [],
        "deterministic_label_variants": [],
        "accepted_source_cues": [],
        "query_variants": [],
        "expected_evidence_shapes": ["context_phrase"],
        "branch_constraints": {},
        "sibling_constraint_checks": [],
        "quarantined_terms": [
            {"term": "invented term", "reason": "not source confirmed", "active": False}
        ],
        "rejected_candidates": [],
        "profile_status": "reject",
        "audit": {},
    }
    validation = validate_profile_collection([profile])
    assert validation["ok"], validation

    bad = json.loads(json.dumps(profile))
    bad["quarantined_terms"][0]["active"] = True
    validation2 = validate_profile_collection([bad])
    assert not validation2["ok"]



def test_seedless_registry_parent_and_sibling_contract():
    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir(parents=True)

    registry = TMP / "seedless_kc_registry.jsonl"
    source = TMP / "sentence_overlay.jsonl"

    write_jsonl(registry, [
        {
            "schema_version": "seedless_kc_registry_v1",
            "node_id": "KC_SAFE_001",
            "node_type": "kc",
            "kc_id": "KC_SAFE_001",
            "canonical_name": "Target Concept",
            "topic_path_labels": ["Course", "Unit", "Parent Topic"],
            "parent_node_id": "topic::course__unit__parent_topic",
            "sibling_labels": ["Sibling Concept"],
            "semantic_fields_status": "ignored_by_construction",
        },
        {
            "schema_version": "seedless_kc_registry_v1",
            "node_id": "KC_SAFE_002",
            "node_type": "kc",
            "kc_id": "KC_SAFE_002",
            "canonical_name": "Sibling Concept",
            "topic_path_labels": ["Course", "Unit", "Parent Topic"],
            "parent_node_id": "topic::course__unit__parent_topic",
            "sibling_labels": ["Target Concept"],
            "semantic_fields_status": "ignored_by_construction",
        },
    ])

    write_jsonl(source, [
        {
            "sentence_id": "safe_s1",
            "sentence_text": "The target concept is defined as a structural relationship in the system.",
            "source_block_text": "The target concept is defined as a structural relationship in the system.",
            "field_path": "sentence_text",
            "doc_id": "DOC_SAFE",
            "page_index": 1,
            "patch_id": "patch_safe_target",
            "reveal_group_id": "reveal_safe_target",
            "patch_heading": "Parent Topic Safe Target Concept",
            "page_heading_norm": "parent topic safe target concept",
            "is_meta": False,
            "is_nav_boilerplate": False,
            "is_author_affiliation": False,
            "is_definition_like": True,
        },
        {
            "sentence_id": "unsafe_meta",
            "sentence_text": "Target Concept",
            "source_block_text": "Target Concept",
            "field_path": "sentence_text",
            "doc_id": "DOC_SAFE",
            "page_index": 0,
            "is_meta": True,
            "is_nav_boilerplate": False,
            "is_author_affiliation": False,
        },
    ])

    result = build_profiles(
        registry_jsonl=registry,
        source_overlay_jsonl=source,
        output_root=TMP / "out_seedless",
        set_manifest_root=TMP / "out_seedless" / "_sets",
        run_id="test_seedless_contract",
        exact_kc_ids=["KC_SAFE_001"],
        limit_kcs=None,
        max_snippets_per_kc=10,
        min_snippet_score=1.0,
        use_model=False,
        model_config={},
    )

    assert result["ok"], result

    profile_path = TMP / "out_seedless" / "test_seedless_contract" / "kc_retrieval_profiles.jsonl"
    rows = [json.loads(line) for line in profile_path.read_text(encoding="utf-8").splitlines()]
    profile = rows[0]

    assert profile["parent_topic_label"] == "Parent Topic"
    assert "Sibling Concept" in profile["sibling_labels"]
    assert profile["audit"]["candidate_snippet_count"] >= 1
    assert any(s.get("snippet_id") == "safe_s1" for s in profile["audit"]["candidate_snippets"])


def test_candidate_harvest_rejects_unsafe_acronym_and_broad_single_token_matches():
    q_phase_variants = deterministic_label_variants("Querying Phase", [])
    q_terms = {v["term"] for v in q_phase_variants}
    assert "QP" not in q_terms

    bayes_variants = deterministic_label_variants("Bayes' Theorem", [])
    bayes_terms = {v["term"] for v in bayes_variants}
    assert "BT" not in bayes_terms

    learning_variants = deterministic_label_variants("Learning Phase", [])
    learning_terms = {v["term"].lower() for v in learning_variants}
    assert "learning" not in learning_terms

    cluster_variants = deterministic_label_variants("Cluster Definition", [])
    cluster_terms = {v["term"].lower() for v in cluster_variants}
    assert "cluster" not in cluster_terms

    assert not phrase_present("QP", "standard solvers for QPP")
    assert phrase_present("F Measure", "The F-measure combines precision and recall.")

    q_score = score_snippet_for_kc(
        text="Because of these differences, it is useful to solve the dual optimization problem using any of the standard solvers for QPP.",
        variants=q_phase_variants,
        topic_path_labels=["Classification", "Classification Underpinnings"],
        sibling_labels=[],
        dynamic_broad_tokens=set(),
    )
    assert q_score["score"] < 4.0, q_score
    assert "insufficient_target_binding" in q_score["reasons"]

    learning_score = score_snippet_for_kc(
        text="The classifier performance improves as learning methods estimate missing values more accurately.",
        variants=learning_variants,
        topic_path_labels=["Data Mining", "Classification"],
        sibling_labels=[],
        dynamic_broad_tokens=set(),
    )
    assert learning_score["score"] < 4.0, learning_score

    zero_score = score_snippet_for_kc(
        text="The zero-frequency problem occurs when a combination of attribute values and class labels is never observed, resulting in a zero conditional probability.",
        variants=deterministic_label_variants("Zero-Frequency Problem", []),
        topic_path_labels=["Classification", "Naive Bayes"],
        sibling_labels=[],
        dynamic_broad_tokens=set(),
    )
    assert zero_score["score"] >= 4.0, zero_score


def test_shapeaware_profile_fields_use_generic_parent_acronym_expansion():
    guidance = builder_mod._build_shapeaware_profile_fields(  # type: ignore[attr-defined]
        {
            "canonical_name": "NB Learning Phase",
            "aliases": [],
            "parent_topic_label": "Naive Bayes",
            "topic_path_labels": ["Classification", "Naive Bayes"],
            "sibling_labels": ["NB Querying Phase"],
        },
        query_variants=[{"query": "NB Learning Phase"}],
        retrieval_routes=[],
        expected_evidence_shape_hints=[{"shape_family": "process"}],
        negative_terms=[],
    )

    assert guidance["concept_head"] == "Learning Phase"
    assert guidance["qualifiers"] == ["NB"]
    assert "Naive Bayes Learning Phase" in guidance["expanded_aliases"]
    assert "NB Learning Phase" in guidance["normalized_surface_variants"]
    assert guidance["expected_evidence_needs"][0]["need"] == "phase_process"
    assert "NB Querying Phase" in guidance["negative_sibling_terms"]


def test_two_lane_profile_windows_separate_strict_and_exploratory_inputs():
    kc_row = {
        "kc_id": "KC_TEST_LANE",
        "canonical_name": "Zero-Frequency Problem",
        "aliases": [],
        "topic_path_labels": ["Classification", "Naive Bayes"],
        "parent_topic_label": "Naive Bayes",
        "sibling_labels": ["Laplace Estimator"],
    }
    source_rows = [
        {
            "sentence_id": "strict_zero",
            "sentence_text": "The zero-frequency problem occurs when an attribute value and class label combination is never observed, producing a zero conditional probability.",
            "field_path": "sentence_text",
            "doc_id": "DOC_TEST",
            "page_index": 1,
        },
        {
            "sentence_id": "exploratory_context",
            "sentence_text": "A classifier estimates probabilities from training instances and can suffer when counts are sparse.",
            "field_path": "sentence_text",
            "doc_id": "DOC_TEST",
            "page_index": 2,
        },
        {
            "sentence_id": "discard_generic",
            "sentence_text": "This chapter provides an overview of data mining and preprocessing tasks.",
            "field_path": "sentence_text",
            "doc_id": "DOC_TEST",
            "page_index": 3,
        },
    ]

    windows = collect_profile_windows(
        kc_row=kc_row,
        all_kc_rows=[kc_row],
        source_rows=source_rows,
        dynamic_broad_tokens=set(),
        max_snippets_per_kc=10,
        min_score=4.0,
    )

    strict_ids = {w["snippet_id"] for w in windows["strict_source_windows"]}
    exploratory_ids = {w["snippet_id"] for w in windows["exploratory_profile_windows"]}

    assert "strict_zero" in strict_ids, windows
    assert "discard_generic" not in strict_ids
    assert "discard_generic" not in exploratory_ids
    for win in windows["strict_source_windows"] + windows["exploratory_profile_windows"]:
        assert win["profile_window_role"] == "profiler_input_only_not_evidence"


def test_shared_source_window_kernel_rejects_wrong_branch_and_recovers_anchored_windows():
    kc_zero = {
        "kc_id": "KC_ZERO",
        "canonical_name": "Zero-Frequency Problem",
        "aliases": [],
        "topic_path_labels": ["Classification", "Naive Bayes", "Probability Estimation"],
        "parent_topic_id": "topic::nb",
        "parent_topic_label": "Probability Estimation",
    }
    kc_cluster = {
        "kc_id": "KC_CLUSTER",
        "canonical_name": "Cluster Definition",
        "aliases": [],
        "topic_path_labels": ["Clustering", "Cluster Foundations"],
        "parent_topic_id": "topic::cluster",
        "parent_topic_label": "Cluster Foundations",
    }
    source_rows = [
        {
            "sentence_id": "zero_wrong_branch",
            "sentence_text": "All three measures give a zero impurity value if a node contains instances from a single class.",
            "source_block_text": "All three measures give a zero impurity value if a node contains instances from a single class.",
            "doc_id": "DOC_TEST",
            "page_index": 20,
            "block_id": "b1",
            "patch_id": "p_decision_tree",
            "patch_heading": "Decision Tree Impurity Measures",
            "reveal_group_id": "r1",
            "is_definition_like": True,
            "is_formula_like": True,
            "is_meta": False,
            "is_nav_boilerplate": False,
            "is_author_affiliation": False,
        },
        {
            "sentence_id": "zero_right_branch",
            "sentence_text": "The zero-frequency problem occurs when an attribute value and class label combination is never observed.",
            "source_block_text": "The zero-frequency problem occurs when an attribute value and class label combination is never observed.",
            "doc_id": "DOC_TEST",
            "page_index": 30,
            "block_id": "b2",
            "patch_id": "p_naive_bayes",
            "patch_heading": "Naive Bayes Probability Estimation",
            "reveal_group_id": "r2",
            "is_definition_like": True,
            "is_formula_like": False,
            "is_meta": False,
            "is_nav_boilerplate": False,
            "is_author_affiliation": False,
        },
        {
            "sentence_id": "cluster_definition",
            "sentence_text": "A cluster is a collection of data objects treated as a single group.",
            "source_block_text": "A cluster is a collection of data objects treated as a single group.",
            "doc_id": "DOC_TEST",
            "page_index": 40,
            "block_id": "b3",
            "patch_id": "p_cluster",
            "patch_heading": "Cluster Foundations",
            "reveal_group_id": "r3",
            "is_definition_like": True,
            "is_formula_like": False,
            "is_meta": False,
            "is_nav_boilerplate": False,
            "is_author_affiliation": False,
        },
    ]

    zero_windows = collect_profile_windows_with_source_surface_kernel(
        kc_row=kc_zero,
        all_kc_rows=[kc_zero, kc_cluster],
        source_rows=source_rows,
        max_snippets_per_kc=8,
        min_score=4.0,
    )
    zero_all = zero_windows["strict_source_windows"] + zero_windows["exploratory_profile_windows"]
    zero_ids = {w["snippet_id"] for w in zero_all}

    assert "zero_right_branch" in zero_ids, zero_windows
    assert "zero_wrong_branch" not in zero_ids, zero_windows
    assert zero_windows["source_window_supplier_stats"]["historical_step5x_artifacts_used"] is False

    cluster_windows = collect_profile_windows_with_source_surface_kernel(
        kc_row=kc_cluster,
        all_kc_rows=[kc_zero, kc_cluster],
        source_rows=source_rows,
        max_snippets_per_kc=8,
        min_score=4.0,
    )
    cluster_ids = {w["snippet_id"] for w in cluster_windows["strict_source_windows"] + cluster_windows["exploratory_profile_windows"]}
    assert "cluster_definition" in cluster_ids, cluster_windows

    for win in zero_all + cluster_windows["strict_source_windows"] + cluster_windows["exploratory_profile_windows"]:
        assert win["profile_window_role"] == "profiler_input_only_not_evidence"
        assert win["window_supplier"] == "source_surface_kernel_profile_mode"


def test_output_hardening_module_marks_query_roles_and_risks():
    queries = [
        {
            "query": "Zero-Frequency Problem",
            "source": "deterministic_label_variant",
            "variant_type": "exact_label",
            "active": True,
        },
        {
            "query": "zero frequency",
            "source": "deterministic_label_variant",
            "variant_type": "generic_suffix_stripped",
            "active": True,
        },
        {
            "query": "a combination of attribute values and class labels are never observed, resulting in a zero conditional probability",
            "source": "accepted_source_cue",
            "cue_type": "mechanism_description",
            "active": True,
            "provenance": [{"snippet_id": "s1", "field_path": "sentence_text"}],
        },
        {
            "query": "learning algorithm",
            "source": "accepted_source_cue",
            "cue_type": "definition_phrase",
            "active": True,
            "provenance": [{"snippet_id": "s2", "field_path": "sentence_text"}],
        },
    ]

    hardened = harden_query_variants(queries)
    by_query = {row["query"]: row for row in hardened}

    assert by_query["Zero-Frequency Problem"]["retrieval_role"] == "lexical_query"
    assert by_query["Zero-Frequency Problem"]["step5x_eligible"] is True

    assert by_query["zero frequency"]["retrieval_role"] == "profile_only_query"
    assert by_query["zero frequency"]["step5x_eligible"] is False
    assert "generic_suffix_stripped_broad_risk" in by_query["zero frequency"]["risk_flags"]

    long_query = "a combination of attribute values and class labels are never observed, resulting in a zero conditional probability"
    assert by_query[long_query]["retrieval_role"] == "semantic_query"
    assert by_query[long_query]["retrieval_channels"] == ["semantic"]

    assert by_query["learning algorithm"]["retrieval_role"] == "lexical_query"
    assert "lexical" in by_query["learning algorithm"]["retrieval_channels"]


def test_output_hardening_module_adds_shape_hints_to_profile():
    profile = {
        "accepted_source_cues": [
            {
                "term": "A cluster is a dense region of objects surrounded by low density.",
                "cue_type": "definition_phrase",
                "active": True,
                "provenance": [{"snippet_id": "s1", "field_path": "sentence_text"}],
            }
        ],
        "query_variants": [
            {"query": "Cluster Definition", "source": "deterministic_label_variant", "variant_type": "exact_label", "active": True},
            {
                "query": "A cluster is a dense region of objects surrounded by low density.",
                "source": "accepted_source_cue",
                "cue_type": "definition_phrase",
                "active": True,
                "provenance": [{"snippet_id": "s1", "field_path": "sentence_text"}],
            },
        ],
        "expected_evidence_shapes": ["definition_shape"],
        "audit": {
            "candidate_snippets": [
                {"evidence_shapes": ["definition_shape"], "snippet_id": "s1"}
            ]
        },
    }

    hardened = harden_profile_output(profile)
    assert hardened["query_variants"][0]["retrieval_role"] == "lexical_query"
    assert hardened["query_variants"][1]["retrieval_role"] == "semantic_query"
    assert hardened["expected_evidence_shape_hints"]
    assert hardened["audit"]["profile_output_hardening"]["step5x_eligible_query_count"] >= 1


def test_composite_model_cue_types_are_normalized_before_profile_validation():
    snippets = [
        {
            "snippet_id": "s1",
            "text": "The F-measure is computed as the harmonic mean of precision and recall.",
            "field_path": "sentence_text",
            "profile_window_role": "profiler_input_only_not_evidence",
            "evidence_shapes": ["formula_relation"],
        },
        {
            "snippet_id": "s2",
            "text": "A cluster is a dense region of objects that are similar to one another.",
            "field_path": "sentence_text",
            "profile_window_role": "profiler_input_only_not_evidence",
            "evidence_shapes": ["definition_phrase"],
        },
        {
            "snippet_id": "s3",
            "text": "This score is included for illustration only.",
            "field_path": "sentence_text",
            "profile_window_role": "profiler_input_only_not_evidence",
            "evidence_shapes": ["context_phrase"],
        },
    ]
    validated = post_validate_model_output(
        kc_row={
            "kc_id": "KC_TEST_004",
            "canonical_name": "Cluster Definition",
            "aliases": [],
            "topic_path_labels": ["Course", "Unit"],
            "parent_topic_label": "Unit",
            "sibling_labels": ["Sibling Concept"],
        },
        model_obj={
            "accepted_source_cues": [
                {
                    "term": "harmonic mean",
                    "cue_type": "definition_phrase|metric_relation",
                    "active": True,
                    "why_target_relevant": "The metric is defined by a harmonic mean relation.",
                    "provenance": [{"snippet_id": "s1", "field_path": "sentence_text"}],
                },
                {
                    "term": "dense region",
                    "cue_type": "process_phrase|mechanism_description",
                    "active": True,
                    "why_target_relevant": "The text describes how the cluster behaves and what it is.",
                    "provenance": [{"snippet_id": "s2", "field_path": "sentence_text"}],
                },
                {
                    "term": "precision and recall",
                    "cue_type": "metric_relation/unsupported_noise",
                    "active": True,
                    "why_target_relevant": "The sentence names the quantities linked by the metric.",
                    "provenance": [{"snippet_id": "s1", "field_path": "sentence_text"}],
                },
                {
                    "term": "illustration only",
                    "cue_type": "unsupported_noise|still_invalid",
                    "active": True,
                    "why_target_relevant": "This should not remain active.",
                    "provenance": [{"snippet_id": "s3", "field_path": "sentence_text"}],
                },
            ],
            "quarantined_terms": [],
            "rejected_terms": [],
            "sibling_constraint_checks": [],
        },
        snippets=snippets,
        deterministic_variants=deterministic_label_variants("Cluster Definition", []),
    )

    accepted = validated["accepted_source_cues"]
    assert len(accepted) == 3, validated
    assert all(cue["cue_type"] in ACTIVE_CUE_TYPES for cue in accepted)
    assert all("|" not in cue["cue_type"] for cue in accepted)

    by_term = {cue["term"]: cue for cue in accepted}
    assert by_term["harmonic mean"]["cue_type"] == "definition_phrase"
    assert by_term["harmonic mean"]["cue_type_raw"] == "definition_phrase|metric_relation"
    assert by_term["harmonic mean"]["secondary_cue_types"] == ["metric_relation"]

    assert by_term["dense region"]["cue_type"] == "mechanism_description"
    assert by_term["dense region"]["cue_type_raw"] == "process_phrase|mechanism_description"
    assert by_term["dense region"]["secondary_cue_types"] == ["process_phrase"]

    assert by_term["precision and recall"]["cue_type"] == "metric_relation"
    assert by_term["precision and recall"]["cue_type_raw"] == "metric_relation/unsupported_noise"
    assert by_term["precision and recall"]["unsupported_cue_type_parts"] == ["unsupported_noise"]

    quarantined = validated["quarantined_terms"]
    assert any(item["reason"] == "unsupported_cue_type_after_normalization" for item in quarantined)
    unsupported_only = next(item for item in quarantined if item["reason"] == "unsupported_cue_type_after_normalization")
    assert unsupported_only["cue_type_raw"] == "unsupported_noise|still_invalid"

    profile = harden_profile_output({
        "profile_contract_version": PROFILE_CONTRACT_VERSION,
        "kc_id": "KC_TEST_004",
        "canonical_name": "Cluster Definition",
        "aliases": [],
        "topic_path_labels": ["Course", "Unit"],
        "parent_topic_label": "Unit",
        "sibling_labels": ["Sibling Concept"],
        "deterministic_label_variants": deterministic_label_variants("Cluster Definition", []),
        "accepted_source_cues": accepted,
        "query_variants": [
            {
                "query": "Cluster Definition",
                "source": "deterministic_label_variant",
                "variant_type": "exact_label",
                "active": True,
            },
            *[
                {
                    "query": cue["term"],
                    "source": "accepted_source_cue",
                    "cue_type": cue["cue_type"],
                    "cue_type_raw": cue.get("cue_type_raw"),
                    "secondary_cue_types": cue.get("secondary_cue_types", []),
                    "unsupported_cue_type_parts": cue.get("unsupported_cue_type_parts", []),
                    "active": True,
                    "provenance": cue["provenance"],
                }
                for cue in accepted
            ],
        ],
        "expected_evidence_shapes": ["definition_phrase", "formula_relation"],
        "branch_constraints": {"topic_path_labels": ["Course", "Unit"]},
        "sibling_constraint_checks": validated["sibling_constraint_checks"],
        "quarantined_terms": quarantined,
        "rejected_candidates": validated["rejected_candidates"],
        "profile_status": "usable",
        "audit": {
            "profile_input_status": "strict_windows_available",
            "strict_source_windows": snippets,
            "exploratory_profile_windows": [],
            "candidate_snippets": snippets,
        },
    })

    validation = validate_profile_collection([profile])
    assert validation["ok"], validation
    assert profile["accepted_source_cues"][0]["profile_output_role"] == "retrieval_control_metadata_not_evidence"
    assert profile["query_variants"][0]["profile_output_role"] == "retrieval_control_metadata_not_evidence"
    assert profile["audit"]["strict_source_windows"][0]["profile_window_role"] == "profiler_input_only_not_evidence"



def test_topic_local_content_scout_rescues_label_mismatch_without_heading_only_leak():
    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir(parents=True)

    registry = TMP / "topic_local_kc_registry.jsonl"
    source = TMP / "topic_local_sentence_overlay.jsonl"

    write_jsonl(registry, [
        {
            "kc_id": "KC_QUERY_PHASE",
            "canonical_name": "Querying Phase",
            "aliases": [],
            "topic_path_labels": ["Course Root", "Classification", "Classification Underpinnings"],
            "parent_node_id": "topic::classification_underpinnings",
            "sibling_labels": ["Learning Phase", "Training Set vs. Test Set Split"],
        }
    ])

    write_jsonl(source, [
        {
            "sentence_id": "heading_only_bad",
            "sentence_text": "Classification. Classification Underpinnings Heading",
            "source_block_text": "Classification. Classification Underpinnings Heading",
            "field_path": "sentence_text",
            "doc_id": "DOC_TOPIC",
            "page_index": 1,
            "patch_heading": "Classification Underpinnings",
            "is_meta": False,
            "is_nav_boilerplate": False,
            "is_author_affiliation": False,
        },
        {
            "sentence_id": "off_topic_bad",
            "sentence_text": "Marine biology classifies organisms by habitat and body structure, but this is not part of the target course section.",
            "source_block_text": "Marine biology classifies organisms by habitat and body structure, but this is not part of the target course section.",
            "field_path": "sentence_text",
            "doc_id": "DOC_TOPIC",
            "page_index": 2,
            "patch_heading": "Marine Biology",
            "is_meta": False,
            "is_nav_boilerplate": False,
            "is_author_affiliation": False,
        },
        {
            "sentence_id": "topic_content_good",
            "sentence_text": "A classification model is learned from a training set and is then used to classify records whose class labels are unknown, so the fitted model can be applied to unseen instances.",
            "source_block_text": "A classification model is learned from a training set and is then used to classify records whose class labels are unknown, so the fitted model can be applied to unseen instances.",
            "field_path": "sentence_text",
            "doc_id": "DOC_TOPIC",
            "page_index": 3,
            "patch_heading": "3.1 Classification",
            "is_meta": False,
            "is_nav_boilerplate": False,
            "is_author_affiliation": False,
            "is_definition_like": False,
            "is_formula_like": False,
            "is_procedure_like": True,
            "is_example_like": False,
        },
    ])

    result = build_profiles(
        registry_jsonl=registry,
        source_overlay_jsonl=source,
        output_root=TMP / "out_topic_local",
        set_manifest_root=TMP / "out_topic_local" / "_sets",
        run_id="topic_local_content_scout",
        exact_kc_ids=["KC_QUERY_PHASE"],
        limit_kcs=None,
        max_snippets_per_kc=6,
        min_snippet_score=4.0,
        use_model=False,
        model_config={},
    )

    assert result["stats"]["counts"]["profiles"] == 1
    profile_path = TMP / "out_topic_local" / "topic_local_content_scout" / "kc_retrieval_profiles.jsonl"
    rows = [json.loads(line) for line in profile_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1
    profile = rows[0]

    assert profile["profile_status"] == "weak", profile
    assert profile["audit"]["profile_input_status"] == "topic_local_content_scout", profile["audit"]
    assert profile["audit"]["topic_local_content_scout_used"] is True
    assert profile["audit"]["topic_local_content_scout_window_count"] >= 1

    scout_texts = [w.get("text", "") for w in profile["audit"]["topic_local_content_scout_windows"]]
    assert any("classify records" in text for text in scout_texts), scout_texts
    assert not any("Heading" in text for text in scout_texts), scout_texts
    assert all(w.get("profile_window_role") == "profiler_input_only_not_evidence" for w in profile["audit"]["topic_local_content_scout_windows"])

    validation = validate_profile_collection(rows)
    assert validation["ok"], validation


def test_model_retrieval_routes_are_serialized_at_profile_root():
    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir(parents=True)

    registry = TMP / "route_serialization_kc_registry.jsonl"
    source = TMP / "route_serialization_sentence_overlay.jsonl"

    write_jsonl(registry, [
        {
            "kc_id": "KC_ROUTE_SERIALIZE",
            "canonical_name": "Route Anchor",
            "aliases": [],
            "parent_topic_id": "topic::route_parent",
            "parent_topic_label": "Route Parent",
            "topic_path_labels": ["Course", "Route Parent"],
        }
    ])

    write_jsonl(source, [
        {
            "sentence_id": "route_s1",
            "sentence_text": "Route Anchor is a source-observed concept used to test route serialization.",
            "source_block_text": "Route Anchor is a source-observed concept used to test route serialization.",
            "field_path": "sentence_text",
            "doc_id": "DOC_ROUTE",
            "page_index": 1,
            "patch_heading": "Route Parent",
            "is_meta": False,
            "is_nav_boilerplate": False,
            "is_author_affiliation": False,
            "is_definition_like": True,
        }
    ])

    old_chat = builder_mod.ollama_chat_json
    old_validate = builder_mod.post_validate_model_output

    def fake_chat_json(**kwargs):
        return {"accepted_source_cues": [], "retrieval_routes": []}

    def fake_post_validate_model_output(**kwargs):
        return {
            "accepted_source_cues": [],
            "quarantined_terms": [],
            "rejected_candidates": [],
            "sibling_constraint_checks": [],
            "retrieval_routes": [
                {
                    "route_id": "fake_route_001",
                    "route_type": "anchored_phrase",
                    "activation": "active",
                    "route_strength": "strong",
                    "verification_status": "source_observed_same_window",
                    "primary_terms_any": ["Route Anchor"],
                    "support_terms_any": [],
                    "support_terms_all": [],
                    "negative_terms_any": [],
                    "local_window_scope": "same_sentence_or_patch",
                    "support_requirement": "boost_only",
                    "can_create_candidates": True,
                    "can_create_positive_support": True,
                    "broad_context_only": False,
                    "source_provenance_ids": ["route_s1"],
                    "provenance": [{"snippet_id": "route_s1", "field_path": "sentence_text"}],
                    "profile_output_role": "retrieval_control_metadata_not_evidence",
                }
            ],
        }

    try:
        builder_mod.ollama_chat_json = fake_chat_json
        builder_mod.post_validate_model_output = fake_post_validate_model_output
        result = build_profiles(
            registry_jsonl=registry,
            source_overlay_jsonl=source,
            output_root=TMP / "out_route_serialization",
            set_manifest_root=TMP / "out_route_serialization" / "_sets",
            run_id="route_serialization",
            exact_kc_ids=["KC_ROUTE_SERIALIZE"],
            limit_kcs=None,
            max_snippets_per_kc=4,
            min_snippet_score=1.0,
            use_model=True,
            model_config={"model": "fake-model"},
        )
    finally:
        builder_mod.ollama_chat_json = old_chat
        builder_mod.post_validate_model_output = old_validate

    assert result["stats"]["counts"]["profiles"] == 1

    profile_path = TMP / "out_route_serialization" / "route_serialization" / "kc_retrieval_profiles.jsonl"
    rows = [json.loads(line) for line in profile_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1
    profile = rows[0]

    assert profile["audit"]["retrieval_route_count"] == 1, profile["audit"]
    assert isinstance(profile.get("retrieval_routes"), list), profile
    assert len(profile["retrieval_routes"]) == 1, profile
    assert profile["retrieval_routes"][0]["route_id"] == "fake_route_001"
    assert profile["retrieval_routes"][0]["profile_output_role"] == "retrieval_control_metadata_not_evidence"

    validation = validate_profile_collection(rows)
    assert validation["ok"], validation


def test_topic_local_scout_prioritizes_target_neighborhood_over_sibling_sections():
    variants = [
        {"term": "Models of Randomness (Approach 1)", "variant_type": "exact_label", "active": True},
        {"term": "Models of Randomness", "variant_type": "parenthetical_removed", "active": True},
    ]
    kc_row = {
        "kc_id": "KC_RANDOMNESS",
        "canonical_name": "Models of Randomness (Approach 1)",
        "topic_path_labels": ["Data Mining", "Clustering", "Cluster Evaluation"],
        "parent_topic_label": "Cluster Evaluation",
        "sibling_labels": ["Cohesion", "Separation", "Silhouette Coefficient", "Entropy", "Purity"],
    }
    source_rows = [
        {
            "sentence_id": "sib_1",
            "sentence_text": "Many internal measures of cluster validity are based on the notions of cohesion and separation for partitional clustering schemes.",
            "doc_id": "DOC", "page_index": 848, "patch_id": "p_sibling", "patch_heading": "7.5.2 Unsupervised Cluster Evaluation Using Cohesion and Separation",
            "is_meta": False, "is_nav_boilerplate": False, "is_author_affiliation": False,
        },
        {
            "sentence_id": "target_heading",
            "sentence_text": "statistical tests for spatial randomness.",
            "doc_id": "DOC", "page_index": 867, "patch_id": "p_target", "patch_heading": "7.5.6 Clustering Tendency",
            "is_meta": False, "is_nav_boilerplate": False, "is_author_affiliation": False,
        },
        {
            "sentence_id": "target_context",
            "sentence_text": "The hypothesis that the data is non-random can be quite challenging, so the Hopkins statistic compares nearest-neighbor distances for randomly distributed points and actual data points.",
            "doc_id": "DOC", "page_index": 867, "patch_id": "p_target", "patch_heading": "7.5.6 Clustering Tendency",
            "is_meta": False, "is_nav_boilerplate": False, "is_author_affiliation": False,
            "is_procedure_like": True,
        },
    ]
    windows = builder_mod._topic_local_content_scout_windows(
        kc_row=kc_row,
        source_rows=source_rows,
        variants=variants,
        max_snippets_per_kc=4,
        dynamic_broad_tokens=set(),
    )
    assert windows, windows
    texts = [w.get("text", "") for w in windows]
    assert any("Hopkins statistic" in text for text in texts), windows
    target_windows = [w for w in windows if w.get("target_source_neighborhood_anchor_count")]
    assert target_windows, windows
    assert all("cohesion" not in w.get("target_overlap", []) for w in windows)


def test_topic_local_scout_keeps_bounded_sibling_context_for_low_signal_label_source_mismatch():
    variants = [{"term": "Intrinsic Information", "variant_type": "exact_label", "active": True}]
    kc_row = {
        "kc_id": "KC_INTRINSIC",
        "canonical_name": "Intrinsic Information",
        "topic_path_labels": ["Data Mining", "Classification", "Decision Trees"],
        "parent_topic_label": "Decision Trees",
        "sibling_labels": ["Information Gain", "Gain Ratio", "Gini Index"],
    }
    source_rows = [
        {
            "sentence_id": "broad_tree",
            "sentence_text": "Decision trees recursively split nodes and can overfit when model complexity is high.",
            "doc_id": "DOC", "page_index": 188, "patch_id": "p_broad", "patch_heading": "Decision Trees",
            "is_meta": False, "is_nav_boilerplate": False, "is_author_affiliation": False,
        },
        {
            "sentence_id": "gain_ratio_target",
            "sentence_text": "Instead, information gain ratio was suggested to balance the effect of many values when selecting a split.",
            "doc_id": "DOC", "page_index": 167, "patch_id": "p_gain", "patch_heading": "Gain Ratio",
            "is_meta": False, "is_nav_boilerplate": False, "is_author_affiliation": False,
            "is_definition_like": True,
        },
    ]
    windows = builder_mod._topic_local_content_scout_windows(
        kc_row=kc_row,
        source_rows=source_rows,
        variants=variants,
        max_snippets_per_kc=4,
        dynamic_broad_tokens={"information"},
    )
    assert any("gain ratio" in w.get("text", "").lower() for w in windows), windows
    gain_windows = [w for w in windows if "gain ratio" in w.get("text", "").lower()]
    assert gain_windows[0]["topic_local_anchor_reason"] == "sibling_context_scout"
    assert gain_windows[0]["profile_window_role"] == "profiler_input_only_not_evidence"
    assert gain_windows[0]["target_overlap"] == []


def main():
    test_deterministic_variants()
    test_profile_builder_no_model()
    test_quarantined_model_suggestion_not_active()
    test_seedless_registry_parent_and_sibling_contract()
    test_candidate_harvest_rejects_unsafe_acronym_and_broad_single_token_matches()
    test_shapeaware_profile_fields_use_generic_parent_acronym_expansion()
    test_two_lane_profile_windows_separate_strict_and_exploratory_inputs()
    test_shared_source_window_kernel_rejects_wrong_branch_and_recovers_anchored_windows()
    test_output_hardening_module_marks_query_roles_and_risks()
    test_output_hardening_module_adds_shape_hints_to_profile()
    test_composite_model_cue_types_are_normalized_before_profile_validation()
    test_topic_local_content_scout_rescues_label_mismatch_without_heading_only_leak()
    test_topic_local_scout_prioritizes_target_neighborhood_over_sibling_sections()
    test_topic_local_scout_keeps_bounded_sibling_context_for_low_signal_label_source_mismatch()
    test_model_retrieval_routes_are_serialized_at_profile_root()
    print("TEST_STEP5P_KC_RETRIEVAL_PROFILE_OK")


if __name__ == "__main__":
    main()
