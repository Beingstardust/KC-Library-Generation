from __future__ import annotations

import hashlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from kc_l.retrieval_gate.profile_guidance import (
    guidance_from_profile,
    lexical_aliases_for_candidate_generation,
)
from kc_l.retrieval_gate.evidence_stage_v3_candidate_bank import _evaluate_profile_routes_for_sentence
from kc_l.retrieval_gate.evidence_stage_v3_scored_candidates import score_candidate_row
from kc_l.retrieval_windowing.semantic import match_normalize


def _hash_text(text: str) -> str:
    return hashlib.sha256(match_normalize(text).encode("utf-8")).hexdigest()


def _candidate_row(
    *,
    text: str,
    canonical_name: str = "Leaf Concept",
    aliases: list[str] | None = None,
    alignment: dict[str, object] | None = None,
    support_profile: dict[str, object] | None = None,
    route_eval: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "candidate_id": "cand_route_1",
        "candidate_bank_version": "step5x_v3_candidate_bank_v1",
        "run_id": "route_contract_demo",
        "source_surface": "source_surface_fallback",
        "source_manifest": "manifest.json",
        "source_row_index": 0,
        "source_evidence_index": 0,
        "kc_id": "KC_ROUTE_001",
        "canonical_name": canonical_name,
        "aliases": aliases or [],
        "topic_path_ids": [],
        "topic_path_labels": ["Broad Area", "Parent Region"],
        "parent_topic_id": "TOPIC_PARENT",
        "parent_topic_label": "Parent Region",
        "source_kc_id": "KC_ROUTE_001",
        "source_canonical_name": canonical_name,
        "granularity": "sentence",
        "text": text,
        "source_block_text": text,
        "context_text": "",
        "doc_id": "DOC_SYNTH",
        "page_index": 1,
        "block_id": "block_1",
        "sentence_id": "sent_1",
        "sent_idx": 0,
        "patch_id": "patch_1",
        "patch_heading": "Parent Region",
        "reveal_group_id": "rg_1",
        "layer": "synthetic",
        "bbox": [],
        "char_start": 0,
        "char_end": len(text),
        "retrieval_scores": {"combined": 0.8},
        "alignment_score": 7.5,
        "alignment_breakdown": alignment
        or {
            "canonical_name_token_hits": 0,
            "alias_token_hits": 2,
            "name_or_alias_token_hits": 2,
            "competitor_token_hits": 0,
            "doc_mismatch": False,
            "exact_name_phrase": False,
            "exact_alias_phrase": True,
            "flags": {},
        },
        "support_profile": support_profile
        or {
            "anchor_quality": "strong",
            "preferred_support_role": "definitional_anchor",
            "support_roles": ["definitional_anchor"],
            "formula_support_score": 0.0,
            "generic_context_only": False,
            "fragmentary_surface": False,
            "has_context_completion_source": False,
            "contamination_exclusion_hint": False,
            "fallback_tier": "definition_head",
            "fallback_score": 7.0,
            "fallback_reason": "synthetic",
            "candidate_source": "source_surface_fallback",
        },
        "structural_flags": {
            "looks_formula_like": False,
            "looks_caption_like": False,
            "looks_prompt_like": False,
            "looks_fragmentary": False,
        },
        "raw_text_hash": _hash_text(text),
        "provenance": {},
        "step5p_route_evaluation": route_eval or {},
    }


def test_context_only_route_is_not_alias_for_candidate_generation() -> None:
    profile = {
        "kc_id": "KC_ROUTE_001",
        "canonical_name": "Leaf Concept",
        "profile_status": "usable",
        "query_variants": [
            {"query": "Parent Region", "active": True, "source": "accepted_source_cue", "retrieval_role": "lexical_query", "step5x_eligible": True},
            {"query": "Observable Target", "active": True, "source": "accepted_source_cue", "retrieval_role": "lexical_query", "step5x_eligible": True},
        ],
        "retrieval_routes": [
            {
                "route_id": "context_route",
                "route_type": "context_locator",
                "activation": "context_only",
                "primary_terms_any": ["Parent Region"],
                "broad_context_only": True,
                "can_create_candidates": False,
                "can_create_positive_support": False,
            },
            {
                "route_id": "active_route",
                "route_type": "anchored_phrase",
                "activation": "active",
                "primary_terms_any": ["Observable Target"],
                "broad_context_only": False,
                "can_create_candidates": True,
                "can_create_positive_support": True,
            },
        ],
        "audit": {"profile_input_status": "synthetic"},
    }
    guidance = guidance_from_profile(profile)
    assert lexical_aliases_for_candidate_generation(guidance) == ["Observable Target"]


def test_context_only_route_blocks_positive_support_but_keeps_row_scorable() -> None:
    row = _candidate_row(
        text="Parent Region is useful background for the broader topic.",
        aliases=["Parent Region"],
        route_eval={
            "matched_route_count": 1,
            "positive_route_match_count": 0,
            "context_only_route_match_count": 1,
            "route_positive_blocked_by_missing_support_count": 0,
            "context_only_match_without_positive_route": True,
            "matched_routes": [],
        },
        support_profile={
            "anchor_quality": "strong",
            "preferred_support_role": "definitional_anchor",
            "support_roles": ["definitional_anchor"],
            "generic_context_only": True,
            "fragmentary_surface": False,
            "has_context_completion_source": False,
            "contamination_exclusion_hint": False,
        },
    )
    scored = score_candidate_row(row)
    assert scored["role_eligibility"]["positive_support_eligible"] is False
    assert scored["role_eligibility"]["profile_route_positive_support_blocked"] is True
    assert scored["step5p_route_evaluation"]["context_only_match_without_positive_route"] is True


def test_missing_route_support_blocks_only_profile_route_positive_not_direct_canonical() -> None:
    blocked = _candidate_row(
        text="Short Cue is defined here.",
        canonical_name="Leaf Concept",
        aliases=["Short Cue"],
        route_eval={
            "matched_route_count": 1,
            "positive_route_match_count": 0,
            "context_only_route_match_count": 0,
            "route_positive_blocked_by_missing_support_count": 1,
            "context_only_match_without_positive_route": False,
            "matched_routes": [],
        },
    )
    scored_blocked = score_candidate_row(blocked)
    assert scored_blocked["role_eligibility"]["positive_support_eligible"] is False
    assert scored_blocked["role_eligibility"]["profile_route_positive_support_blocked"] is True

    direct = _candidate_row(
        text="Leaf Concept is defined here.",
        canonical_name="Leaf Concept",
        aliases=["Short Cue"],
        alignment={
            "canonical_name_token_hits": 2,
            "alias_token_hits": 0,
            "name_or_alias_token_hits": 2,
            "competitor_token_hits": 0,
            "doc_mismatch": False,
            "exact_name_phrase": True,
            "exact_alias_phrase": False,
            "flags": {},
        },
        route_eval={
            "matched_route_count": 1,
            "positive_route_match_count": 0,
            "context_only_route_match_count": 0,
            "route_positive_blocked_by_missing_support_count": 1,
            "context_only_match_without_positive_route": False,
            "matched_routes": [],
        },
    )
    scored_direct = score_candidate_row(direct)
    assert scored_direct["role_eligibility"]["profile_route_positive_support_blocked"] is False



def test_active_context_locator_is_normalized_to_context_only() -> None:
    profile = {
        "kc_id": "KC_ROUTE_001",
        "canonical_name": "Leaf Concept",
        "profile_status": "usable",
        "query_variants": [
            {"query": "Parent Region", "active": True, "source": "accepted_source_cue", "retrieval_role": "lexical_query", "step5x_eligible": True},
        ],
        "retrieval_routes": [
            {
                "route_id": "bad_model_context_route",
                "route_type": "context_locator",
                "activation": "active",
                "primary_terms_any": ["Parent Region"],
                "broad_context_only": False,
                "can_create_candidates": True,
                "can_create_positive_support": True,
            },
        ],
        "audit": {"profile_input_status": "synthetic"},
    }
    guidance = guidance_from_profile(profile)
    assert len(guidance.retrieval_routes) == 1
    route = guidance.retrieval_routes[0]
    assert route.activation == "context_only"
    assert route.broad_context_only is True
    assert route.can_create_positive_support is False
    assert lexical_aliases_for_candidate_generation(guidance) == []


def test_route_contract_blocks_noncanonical_positive_without_positive_route_match() -> None:
    row = _candidate_row(
        text="Parent Region contains broad background that should not become leaf evidence.",
        canonical_name="Leaf Concept",
        aliases=["Parent Region"],
        route_eval={
            "route_contract_present": True,
            "matched_route_count": 0,
            "positive_route_match_count": 0,
            "context_only_route_match_count": 0,
            "route_positive_blocked_by_missing_support_count": 0,
            "context_only_match_without_positive_route": False,
            "positive_route_required_but_absent": True,
            "matched_routes": [],
        },
    )
    scored = score_candidate_row(row)
    assert scored["role_eligibility"]["positive_support_eligible"] is False
    assert scored["role_eligibility"]["profile_route_positive_support_blocked"] is True
    assert scored["role_eligibility"]["profile_route_positive_support_block_reason"] == "profile_route_contract_without_positive_route_match"


def test_positive_route_match_allows_profile_guided_positive_support() -> None:
    row = _candidate_row(
        text="Observable Target is explicitly defined here.",
        canonical_name="Leaf Concept",
        aliases=["Observable Target"],
        route_eval={
            "route_contract_present": True,
            "matched_route_count": 1,
            "positive_route_match_count": 1,
            "context_only_route_match_count": 0,
            "route_positive_blocked_by_missing_support_count": 0,
            "context_only_match_without_positive_route": False,
            "positive_route_required_but_absent": False,
            "matched_routes": [
                {"route_id": "active_route", "route_can_create_positive_support_here": True}
            ],
        },
    )
    scored = score_candidate_row(row)
    assert scored["role_eligibility"]["profile_route_positive_support_blocked"] is False



def test_positive_route_requires_primary_hit_in_candidate_text_not_only_source_block() -> None:
    profile = {
        "kc_id": "KC_ROUTE_001",
        "canonical_name": "Leaf Concept",
        "profile_status": "usable",
        "retrieval_routes": [
            {
                "route_id": "active_route",
                "route_type": "anchored_phrase",
                "activation": "active",
                "primary_terms_any": ["Observable Target"],
                "support_terms_any": [],
                "support_terms_all": [],
                "negative_terms_any": [],
                "broad_context_only": False,
                "can_create_candidates": True,
                "can_create_positive_support": True,
                "support_requirement": "none",
            },
        ],
        "audit": {"profile_input_status": "synthetic"},
    }
    guidance = guidance_from_profile(profile)
    route_eval = _evaluate_profile_routes_for_sentence(
        guidance,
        {
            "sentence_text": "Broad background near the target should not become positive leaf evidence.",
            "source_block_text": "Observable Target is the real route sentence. Broad background near the target should not become positive leaf evidence.",
            "patch_heading": "Parent Region",
        },
    )
    assert route_eval["matched_route_count"] == 1
    assert route_eval["positive_route_match_count"] == 0
    assert route_eval["matched_routes"][0]["primary_hits"] == ["Observable Target"]
    assert route_eval["matched_routes"][0]["primary_text_hits"] == []
    assert route_eval["matched_routes"][0]["primary_text_anchor_required_for_positive"] is True

    row = _candidate_row(
        text="Broad background near the target should not become positive leaf evidence.",
        canonical_name="Leaf Concept",
        aliases=["Broad background"],
        route_eval=route_eval,
    )
    scored = score_candidate_row(row)
    assert scored["role_eligibility"]["positive_support_eligible"] is False
    assert scored["role_eligibility"]["profile_route_positive_support_blocked"] is True


def test_positive_support_is_cleared_when_final_quality_is_not_target_bound() -> None:
    row = _candidate_row(
        text="The process of using a learning algorithm to build a model is induction.",
        canonical_name="Querying Phase",
        aliases=["classification model"],
        route_eval={
            "route_contract_present": True,
            "matched_route_count": 1,
            "positive_route_match_count": 1,
            "context_only_route_match_count": 0,
            "route_positive_blocked_by_missing_support_count": 0,
            "context_only_match_without_positive_route": False,
            "positive_route_required_but_absent": False,
            "matched_routes": [
                {"route_id": "active_route", "route_can_create_positive_support_here": True}
            ],
        },
    )
    scored = score_candidate_row(row)
    assert scored["candidate_quality"]["target_bound_positive_support"] is False
    assert scored["role_eligibility"]["positive_support_eligible"] is False
    # The scorer may block this before the final target-bound sanity gate fires.
    # The contract here is functional: non-target-bound rows must not remain positive.
    assert scored["role_eligibility"].get("positive_support_target_bound_blocked") in {False, True}

def main() -> None:
    test_context_only_route_is_not_alias_for_candidate_generation()
    test_active_context_locator_is_normalized_to_context_only()
    test_context_only_route_blocks_positive_support_but_keeps_row_scorable()
    test_route_contract_blocks_noncanonical_positive_without_positive_route_match()
    test_positive_route_match_allows_profile_guided_positive_support()
    test_missing_route_support_blocks_only_profile_route_positive_not_direct_canonical()
    test_positive_route_requires_primary_hit_in_candidate_text_not_only_source_block()
    test_positive_support_is_cleared_when_final_quality_is_not_target_bound()
    print("TEST_STEP5P_STEP5X_ROUTE_CONTRACT_OK")


if __name__ == "__main__":
    main()
