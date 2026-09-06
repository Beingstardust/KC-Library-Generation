from __future__ import annotations

import hashlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_SRC = REPO_ROOT / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from kc_l.retrieval_gate.evidence_stage_v3_scored_candidates import score_candidate_row  # noqa: E402
from kc_l.retrieval_gate.semantic import match_normalize  # noqa: E402


def _hash_text(text: str) -> str:
    return hashlib.sha256(match_normalize(text).encode("utf-8")).hexdigest()


def _route_block_eval() -> dict[str, object]:
    return {
        "route_contract_present": True,
        "matched_route_count": 1,
        "positive_route_match_count": 0,
        "context_only_route_match_count": 0,
        "route_positive_blocked_by_missing_support_count": 0,
        "context_only_match_without_positive_route": False,
        "matched_routes": [
            {
                "route_id": "route_other_observed",
                "activation": "active",
                "route_can_create_positive_support_here": False,
            }
        ],
        "route_control_role": "step5p_retrieval_control_metadata_not_evidence",
    }


def _candidate(
    *,
    candidate_id: str,
    canonical_name: str,
    text: str,
    support_profile: dict[str, object] | None = None,
    structural_flags: dict[str, object] | None = None,
    alignment_breakdown: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "candidate_bank_version": "step5x_v3_candidate_bank_v1",
        "run_id": "route_block_test",
        "source_surface": "source_surface_fallback",
        "source_manifest": "source_overlay.jsonl",
        "source_row_index": 0,
        "source_evidence_index": 0,
        "kc_id": "KC_SIGNAL_DEF_001",
        "canonical_name": canonical_name,
        "aliases": [],
        "topic_path_ids": [],
        "topic_path_labels": ["Signal Systems", "Signal Concepts"],
        "parent_topic_id": "topic_signal_concepts",
        "parent_topic_label": "Signal Concepts",
        "knowledge_unit_id": "KC_SIGNAL_DEF_001",
        "knowledge_unit_type": "kc",
        "query_plan_id": "qp_route_block_test",
        "retrieval_intent": "head_term_plus_definition_frame",
        "candidate_origin": "head_term_plus_definition_frame",
        "target_surface_origin": "source_text",
        "target_binding_basis": "source_text+route_contract",
        "evidence_shape_match": "definition_or_gloss",
        "anchor_scope": "same_sentence",
        "window_build_mode": "source_sentence",
        "review_only_candidate": False,
        "near_miss_reason": "",
        "retrieval_failure_signals": [],
        "authority_contract": "step5x_must_verify_against_source_rows",
        "source_kc_id": "KC_SIGNAL_DEF_001",
        "source_canonical_name": canonical_name,
        "granularity": "sentence",
        "text": text,
        "source_block_text": text,
        "context_text": "",
        "doc_id": "DOC_SIGNAL",
        "page_index": 1,
        "block_id": "DOC_SIGNAL:block_1",
        "sentence_id": "DOC_SIGNAL:block_1::s000",
        "sent_idx": 0,
        "patch_id": "patch-signal",
        "patch_heading": "Signal Concepts",
        "reveal_group_id": "group-signal",
        "layer": "synthetic",
        "bbox": [1.0, 2.0, 3.0, 4.0],
        "char_start": 0,
        "char_end": len(text),
        "retrieval_scores": {"combined": 4.2},
        "alignment_score": 4.2,
        "alignment_breakdown": {
            "exact_name_phrase": False,
            "exact_alias_phrase": False,
            "canonical_name_token_hits": 0,
            "alias_token_hits": 0,
            "name_or_alias_token_hits": 0,
            "competitor_token_hits": 0,
            "doc_mismatch": False,
            "flags": {},
            **dict(alignment_breakdown or {}),
        },
        "support_profile": {
            "anchor_quality": "source_observed",
            "preferred_support_role": "definitional_anchor",
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
        "raw_text_hash": _hash_text(text),
        "provenance": {
            "from_step": "step4_5_sentence_overlay",
            "candidate_source": "source_surface_fallback",
            "source_manifest": "source_overlay.jsonl",
        },
        "step5p_route_evaluation": _route_block_eval(),
    }


def test_direct_definition_statement_not_blocked_by_missing_profile_route_match() -> None:
    row = score_candidate_row(
        _candidate(
            candidate_id="cand_direct_definition",
            canonical_name="Signal Definition",
            text="A signal is a measurable event produced by a source.",
        )
    )
    assert row["target_statement_signal"]["is_direct_target_statement"] is True
    assert row["role_eligibility"]["definition_kernel"] is True
    assert row["role_eligibility"]["profile_route_positive_support_blocked"] is False
    assert row["role_eligibility"]["profile_route_positive_support_bypassed_by_independent_evidence"] is True
    assert row["routing_recommendation"] == "positive_role_candidate"
    assert "independent_step5x_positive_evidence_overrides_missing_profile_route_match" in row["debug_reasons"]["positive_signals"]


def test_missing_route_match_still_blocks_broad_neighbor_without_direct_evidence() -> None:
    row = score_candidate_row(
        _candidate(
            candidate_id="cand_broad_neighbor",
            canonical_name="Signal Definition",
            text="This method is useful in many applications.",
        )
    )
    assert row["role_eligibility"]["profile_route_positive_support_blocked"] is True
    assert row["role_eligibility"]["positive_support_eligible"] is False
    assert row["routing_recommendation"] != "positive_role_candidate"


def test_reference_like_direct_mention_still_blocked() -> None:
    row = score_candidate_row(
        _candidate(
            candidate_id="cand_reference_like",
            canonical_name="Signal Definition",
            text="Signal Definition, Journal of Measurement References, 2020.",
        )
    )
    assert row["reference_like_signal"]["is_reference_like"] or row["reference_like_signal"]["is_bibliography_like"]
    assert row["role_eligibility"]["positive_support_eligible"] is False
    assert row["routing_recommendation"] != "positive_role_candidate"


def test_formula_candidate_preserves_existing_formula_notation_contract() -> None:
    row = score_candidate_row(
        _candidate(
            candidate_id="cand_formula",
            canonical_name="Vector Balance Metric",
            text="Vector Balance Metric VBM = stable_vectors / total_vectors.",
            support_profile={
                "preferred_support_role": "formula_notation",
                "structural_anchor_support": True,
                "formula_support_score": 1.2,
                "shape_hint_formula_or_metric": True,
            },
            structural_flags={"looks_formula_like": True, "is_formula_like": True},
            alignment_breakdown={"exact_name_phrase": False, "canonical_name_token_hits": 3},
        )
    )
    assert row["formula_signal"]["is_actual_formula_notation"] is True
    assert row["role_eligibility"]["formula_notation"] is True
    assert row["role_eligibility"]["profile_route_positive_support_blocked"] is False
    assert row["positive_support_guard"]["blocked_from_positive_support"] is False


if __name__ == "__main__":
    test_direct_definition_statement_not_blocked_by_missing_profile_route_match()
    test_missing_route_match_still_blocks_broad_neighbor_without_direct_evidence()
    test_reference_like_direct_mention_still_blocked()
    test_formula_candidate_preserves_existing_formula_notation_contract()
    print("TEST_STEP5X_ROUTE_BLOCK_INDEPENDENT_EVIDENCE_OK")
