from kc_l.retrieval_profile.role_target_contract import build_role_target_contract, validate_role_target_contract_fields
from kc_l.retrieval_profile.schema import validate_profile
from kc_l.retrieval_gate.profile_guidance import guidance_from_profile, guidance_to_candidate_bank_controls
from kc_l.retrieval_gate.evidence_pack_finalizer import SourceWindowIndex, finalize_pack


def _base_profile():
    return {
        "profile_contract_version": "kc_retrieval_profile_v1",
        "kc_id": "KC_TEST_001",
        "knowledge_unit_id": "KC_TEST_001",
        "knowledge_unit_type": "kc",
        "canonical_name": "Target Rule",
        "profile_status": "usable",
        "accepted_source_cues": [
            {
                "term": "source confirmed target rule",
                "cue_type": "definition_phrase",
                "active": True,
                "provenance": [{"snippet_id": "s1", "field_path": "sentence_text"}],
            }
        ],
        "query_variants": [
            {
                "query": "source confirmed target rule",
                "active": True,
                "source": "accepted_source_cue",
                "step5x_verification_required": True,
            }
        ],
        "quarantined_terms": [],
        "source_windows": [{"snippet_id": "s1", "step5x_verification_required": True}],
    }


def test_role_target_contract_is_source_confirmed_and_validates():
    profile = _base_profile()
    profile.update(build_role_target_contract(
        unit_row={
            "kc_id": "KC_TEST_001",
            "canonical_name": "Target Rule",
            "node_type": "leaf",
            "topic_path_labels": ["Parent Topic"],
        },
        accepted_source_cues=profile["accepted_source_cues"],
        retrieval_routes=[],
        strict_source_windows=[
            {
                "snippet_id": "s1",
                "doc_id": "DOC",
                "page_index": 1,
                "patch_id": "p1",
                "step5x_verification_required": True,
            }
        ],
        exploratory_profile_windows=[],
        expected_evidence_shapes=["definition_phrase"],
        profile_input_status="strict_windows_available",
    ))

    assert validate_role_target_contract_fields(profile)["errors"] == []
    assert validate_profile(profile)["ok"] is True

    guidance = guidance_from_profile(profile)
    controls = guidance_to_candidate_bank_controls(guidance)

    assert controls["role_targets"]
    assert controls["role_targets"][0]["target_role"] == "primary_core"
    assert controls["knowledge_unit_type"] == "kc"


def test_topic_unit_contract_is_supported_without_hardcoded_counts():
    contract = build_role_target_contract(
        unit_row={
            "hier_node_id": "topic::1",
            "label": "Parent Topic",
            "node_type": "topic",
            "topic_path_labels": ["Root", "Parent Topic"],
        },
        accepted_source_cues=[],
        retrieval_routes=[],
        strict_source_windows=[
            {
                "snippet_id": "topic_s1",
                "doc_id": "DOC",
                "page_index": 1,
                "patch_id": "p1",
                "step5x_verification_required": True,
            }
        ],
        exploratory_profile_windows=[],
        expected_evidence_shapes=[],
        profile_input_status="strict_windows_available",
    )

    assert contract["knowledge_unit_type"] == "topic"
    assert contract["coverage_goals"]["primary_core_required"] is False
    assert contract["role_targets"][0]["target_role"] == "bridge_context"


def test_finalizer_generic_parent_context_is_bridge_not_core():
    profile = _base_profile()
    profile.update({
        "role_targets": [],
        "branch_policy": {
            "branch_required_for_core": True,
            "branch_terms": ["target"],
            "generic_parent_terms": ["parent"],
            "generic_parent_terms_bridge_only": True,
        },
        "coverage_goals": {"primary_core_required": True},
    })

    pack = {
        "kc_id": "KC_TEST_001",
        "knowledge_unit_id": "KC_TEST_001",
        "knowledge_unit_type": "kc",
        "canonical_name": "Target Rule",
        "topic_path_labels": ["Parent Topic"],
        "ordered_pack_for_drafting": [
            {
                "candidate_id": "c1",
                "role": "definition_kernel",
                "text": "Parent material is a broad context statement that explains the parent topic generally.",
                "source_row_index": 0,
            }
        ],
    }

    overlay = [
        {
            "sentence_text": "Parent material is a broad context statement that explains the parent topic generally.",
            "source_row_index": 0,
            "doc_id": "DOC",
        }
    ]

    final = finalize_pack(
        pack,
        profile=profile,
        registry_row={},
        scored_rows=[],
        source_index=SourceWindowIndex(overlay),
        cfg={},
    )
    item = final["ordered_pack_for_drafting"][0]
    assert item["finalizer_role"] == "bridge_context"



def test_finalizer_preserves_adjacent_core_and_bridge_when_windows_overlap():
    profile = {
        "profile_contract_version": "kc_retrieval_profile_v1",
        "kc_id": "KC_SYNTH_FORMULA_001",
        "knowledge_unit_id": "KC_SYNTH_FORMULA_001",
        "knowledge_unit_type": "kc",
        "canonical_name": "Synthetic Probability Rule",
        "profile_status": "usable",
        "accepted_source_cues": [
            {
                "term": "posterior probability",
                "cue_type": "formula_relation",
                "active": True,
                "provenance": [{"snippet_id": "s1", "field_path": "sentence_text"}],
            }
        ],
        "query_variants": [
            {
                "query": "posterior probability",
                "active": True,
                "source": "accepted_source_cue",
                "step5x_verification_required": True,
            }
        ],
        "source_windows": [{"snippet_id": "s1", "step5x_verification_required": True}],
        "quarantined_terms": [],
    }
    profile.update(build_role_target_contract(
        unit_row={
            "kc_id": "KC_SYNTH_FORMULA_001",
            "canonical_name": "Synthetic Probability Rule",
            "node_type": "leaf",
            "topic_path_labels": ["Generic Parent"],
        },
        accepted_source_cues=profile["accepted_source_cues"],
        retrieval_routes=[],
        strict_source_windows=[{"snippet_id": "s1", "doc_id": "DOC", "source_row_index": 0}],
        exploratory_profile_windows=[],
        expected_evidence_shapes=["formula_relation"],
        profile_input_status="strict_windows_available",
    ))

    pack = {
        "kc_id": "KC_SYNTH_FORMULA_001",
        "knowledge_unit_id": "KC_SYNTH_FORMULA_001",
        "knowledge_unit_type": "kc",
        "canonical_name": "Synthetic Probability Rule",
        "topic_path_labels": ["Generic Parent"],
        "ordered_pack_for_drafting": [
            {
                "candidate_id": "core_candidate",
                "role": "formula_notation",
                "text": "The posterior probability p(class | instance) is computed from source confirmed evidence.",
                "source_row_index": 0,
            },
            {
                "candidate_id": "bridge_candidate",
                "role": "definition_kernel",
                "text": "Generic parent material describes the parent area broadly without binding to the target rule.",
                "source_row_index": 1,
            },
        ],
    }
    overlay = [
        {
            "sentence_text": "The posterior probability p(class | instance) is computed from source confirmed evidence.",
            "source_row_index": 0,
            "doc_id": "DOC",
        },
        {
            "sentence_text": "Generic parent material describes the parent area broadly without binding to the target rule.",
            "source_row_index": 1,
            "doc_id": "DOC",
        },
    ]

    final = finalize_pack(
        pack,
        profile=profile,
        registry_row={},
        scored_rows=[],
        source_index=SourceWindowIndex(overlay),
        cfg={},
    )
    roles = [item.get("finalizer_role") for item in final["ordered_pack_for_drafting"]]
    assert "core" in roles
    assert "bridge_context" in roles
    assert len(final["ordered_pack_for_drafting"]) >= 2



def test_role_target_semantics_promotes_label_bound_theorem_cue():
    contract = build_role_target_contract(
        unit_row={
            "kc_id": "KC_SYNTH_THEOREM_001",
            "canonical_name": "Synthetic Theorem",
            "node_type": "leaf",
            "topic_path_labels": ["Synthetic Topic"],
        },
        accepted_source_cues=[
            {
                "term": "Synthetic theorem provides a relationship between the conditional probabilities.",
                "cue_type": "context_phrase",
                "active": True,
                "provenance": [{"snippet_id": "s1", "field_path": "sentence_text"}],
            }
        ],
        retrieval_routes=[],
        strict_source_windows=[{"snippet_id": "s1", "doc_id": "DOC"}],
        exploratory_profile_windows=[],
    )
    roles = [target["target_role"] for target in contract["role_targets"]]
    assert "primary_core" in roles or "formula_or_procedure" in roles


def test_role_target_semantics_demotes_generic_classification_for_branch_kc():
    contract = build_role_target_contract(
        unit_row={
            "kc_id": "KC_SYNTH_BRANCH_001",
            "canonical_name": "Specific Branch Phase",
            "node_type": "leaf",
            "topic_path_labels": ["Classification"],
        },
        accepted_source_cues=[
            {
                "term": "The same process in regression or classification can be applied to predict missing values.",
                "cue_type": "definition_phrase",
                "active": True,
                "provenance": [{"snippet_id": "s1", "field_path": "sentence_text"}],
            }
        ],
        retrieval_routes=[],
        strict_source_windows=[{"snippet_id": "s1", "doc_id": "DOC"}],
        exploratory_profile_windows=[],
    )
    roles = [target["target_role"] for target in contract["role_targets"]]
    assert "primary_core" not in roles
    assert "bridge_context" in roles


def test_role_target_semantics_topic_label_overlap_becomes_explanation():
    contract = build_role_target_contract(
        unit_row={
            "hier_node_id": "topic::classification",
            "label": "Classification",
            "node_type": "topic",
            "topic_path_labels": ["Data Mining", "Classification"],
        },
        accepted_source_cues=[
            {
                "term": "Classification is the task of assigning objects to predefined categories.",
                "cue_type": "definition_phrase",
                "active": True,
                "provenance": [{"snippet_id": "s1", "field_path": "sentence_text"}],
            }
        ],
        retrieval_routes=[],
        strict_source_windows=[{"snippet_id": "s1", "doc_id": "DOC"}],
        exploratory_profile_windows=[],
    )
    roles = [target["target_role"] for target in contract["role_targets"]]
    assert "explanation" in roles



def test_role_target_semantics_v3_blocks_parent_overlap_for_branch_kc():
    contract = build_role_target_contract(
        unit_row={
            "kc_id": "KC_SYNTH_BRANCH_002",
            "canonical_name": "NB Classification Phase",
            "node_type": "leaf",
            "topic_path_labels": ["Classification"],
        },
        accepted_source_cues=[
            {
                "term": "Classification can be applied to predict missing values.",
                "cue_type": "definition_phrase",
                "active": True,
                "provenance": [{"snippet_id": "s1", "field_path": "sentence_text"}],
            }
        ],
        retrieval_routes=[],
        strict_source_windows=[{"snippet_id": "s1", "doc_id": "DOC"}],
        exploratory_profile_windows=[],
    )
    roles = [target["target_role"] for target in contract["role_targets"]]
    assert "primary_core" not in roles
    assert "bridge_context" in roles


def test_role_target_semantics_v3_blocks_strategy_only_for_deletion_strategy():
    contract = build_role_target_contract(
        unit_row={
            "kc_id": "KC_SYNTH_DELETE_001",
            "canonical_name": "Deletion Strategy",
            "node_type": "leaf",
            "topic_path_labels": ["Missing Values"],
        },
        accepted_source_cues=[
            {
                "term": "This strategy reduces the number of candidate split positions.",
                "cue_type": "formula_relation",
                "active": True,
                "provenance": [{"snippet_id": "s1", "field_path": "sentence_text"}],
            }
        ],
        retrieval_routes=[],
        strict_source_windows=[{"snippet_id": "s1", "doc_id": "DOC"}],
        exploratory_profile_windows=[],
    )
    roles = [target["target_role"] for target in contract["role_targets"]]
    assert "primary_core" not in roles
    assert "formula_or_procedure" not in roles
    assert "bridge_context" in roles


def test_role_target_semantics_v3_promotes_exhaustive_search_core_property():
    contract = build_role_target_contract(
        unit_row={
            "kc_id": "KC_SYNTH_EXHAUSTIVE_001",
            "canonical_name": "Exhaustive Search",
            "node_type": "leaf",
            "topic_path_labels": ["Feature Selection Search"],
        },
        accepted_source_cues=[
            {
                "term": "Only exhaustive search can guarantee the optimality.",
                "cue_type": "context_phrase",
                "active": True,
                "provenance": [{"snippet_id": "s1", "field_path": "sentence_text"}],
            }
        ],
        retrieval_routes=[],
        strict_source_windows=[{"snippet_id": "s1", "doc_id": "DOC"}],
        exploratory_profile_windows=[],
    )
    roles = [target["target_role"] for target in contract["role_targets"]]
    assert "primary_core" in roles
