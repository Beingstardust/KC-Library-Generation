from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from kc_l.kc.drafting_input_overlay import build_overlay_records
from kc_l.kc_drafting.heuristic_core import assess_overlay_candidate


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


STEP53_RUNNER = _load_module(
    REPO_ROOT / "steps/step_05_3_evidence_recalibrated/scripts/run_step5_3.py",
    "step53_support_composition_test",
)


def _step53_cfg():
    return {
        "runtime": {"heuristic_shortlist_per_kc": 64},
        "selection": {
            "max_candidates_per_kc": 6,
            "max_candidates_per_doc": 6,
            "max_candidates_per_page": 6,
            "reserve_structured_candidates": 1,
            "reserve_definition_anchor_candidates": 2,
            "reserve_explanatory_anchor_candidates": 2,
            "reserve_context_completion_candidates": 1,
            "max_formula_auxiliary_candidates": 1,
            "max_formula_only_candidates_without_definition_anchor": 1,
        },
        "scoring": {
            "weights": {
                "exact_name_phrase": 5.0,
                "exact_alias_phrase": 4.0,
                "canonical_token": 2.0,
                "alias_token": 1.5,
                "context_keyword": 0.9,
                "heading_name_token": 0.6,
                "doc_group_match": 1.8,
                "definition_like": 1.8,
                "formula_like": 1.8,
                "procedure_like": 1.4,
                "example_like": 0.5,
                "page_index_present": 0.3,
                "patch_id_present": 0.3,
                "canonical_reveal_page": 0.4,
                "rerank_target": 6.0,
                "rerank_margin": 4.0,
            },
            "support_profile_weights": {
                "strong_definition_anchor": 3.0,
                "usable_definition_anchor": 1.5,
                "explanatory_anchor": 1.0,
                "context_completion_available": 1.25,
                "formula_auxiliary_penalty": 2.0,
                "contamination_exclusion_penalty": 1.5,
            },
            "penalties": {
                "is_meta": 5.0,
                "is_nav_boilerplate": 6.0,
                "is_author_affiliation": 8.0,
                "is_transition_text": 4.0,
                "is_heading_like": 0.8,
                "missing_page_index": 0.8,
                "missing_patch_id": 0.4,
                "noncanonical_reveal_page": 0.4,
                "doc_group_mismatch": 4.5,
                "competitor_token_hit": 1.0,
                "short_sentence": 1.2,
                "very_short_sentence": 2.5,
            },
            "thresholds": {
                "short_sentence_chars": 42,
                "very_short_sentence_chars": 18,
                "strong_context_overlap_min": 1,
                "rerank_target_min": 0.55,
                "rerank_margin_min": 0.0,
                "exact_phrase_rerank_target_min": 0.52,
                "exact_phrase_rerank_margin_min": -0.01,
                "multi_token_rerank_margin_min": -0.01,
                "doc_mismatch_rerank_target_min": 0.7,
                "doc_mismatch_rerank_margin_min": 0.1,
                "strong_doc_mismatch_override_margin": 0.2,
                "high_risk_negative_margin": -0.03,
                "top_candidate_suppressed_max": 6,
            },
        },
    }


def _profile():
    canonical_name = "Target criterion"
    aliases = ["Target rule"]
    hierarchy_context = ["Demo topic"]
    return STEP53_RUNNER.KCProfile(
        kc_id="KC_TARGET_001",
        canonical_name=canonical_name,
        aliases=aliases,
        kc_path=["Demo topic", canonical_name],
        kc_group="other",
        query_text=STEP53_RUNNER.build_query_text(canonical_name, aliases, hierarchy_context),
        query_tokens={"target", "criterion"},
        name_terms=STEP53_RUNNER.build_name_context_terms(canonical_name, aliases, hierarchy_context, context_limit=24),
        competitor_ids=["KC_SIBLING_001"],
        competitor_tokens=["competing", "sibling"],
    )


def _row(
    text: str,
    *,
    source_block_text: str | None = None,
    doc_id: str = "doc_target",
    block_id: str = "doc_target:block:001",
    page_index: int = 1,
    patch_id: str = "patch-1",
    patch_heading: str = "Target criterion",
    is_definition_like: bool = False,
    is_formula_like: bool = False,
    is_procedure_like: bool = False,
    is_example_like: bool = False,
) -> dict[str, object]:
    return {
        "sentence_id": f"{doc_id}:{block_id}:{page_index}:{hash(text) & 0xffff}",
        "doc_id": doc_id,
        "block_id": block_id,
        "sent_idx": 0,
        "char_start": 0,
        "char_end": len(text),
        "page_index": page_index,
        "layer": "docling",
        "bbox": None,
        "reveal_group_id": None,
        "patch_id": patch_id,
        "patch_heading": patch_heading,
        "page_heading_norm": patch_heading,
        "sentence_text": text,
        "source_block_text": source_block_text or text,
        "is_meta": False,
        "is_nav_boilerplate": False,
        "is_author_affiliation": False,
        "is_transition_text": False,
        "is_heading_like": False,
        "is_formula_like": is_formula_like,
        "is_definition_like": is_definition_like,
        "is_procedure_like": is_procedure_like,
        "is_example_like": is_example_like,
    }


def _scored_candidate(row: dict[str, object], profile, cfg, *, rerank_target: float, rerank_margin: float):
    candidate = STEP53_RUNNER.score_sentence_candidate(row, profile, cfg, source_type="step4_5_sentence_overlay")
    assert candidate is not None
    candidate.rerank_target = rerank_target
    candidate.rerank_margin = rerank_margin
    candidate.rerank_best_other = max(0.0, rerank_target - rerank_margin)
    candidate.rerank_target_raw = rerank_target
    candidate.rerank_best_other_raw = candidate.rerank_best_other
    STEP53_RUNNER.finalize_candidate(candidate, cfg)
    return candidate


def test_step53_selection_prefers_definition_anchor_and_context_before_formula_only():
    cfg = _step53_cfg()
    profile = _profile()
    candidates = [
        _scored_candidate(
            _row(
                "Target criterion is a decision rule that assigns a label to each observation.",
                is_definition_like=True,
            ),
            profile,
            cfg,
            rerank_target=0.95,
            rerank_margin=0.30,
        ),
        _scored_candidate(
            _row(
                "For each observation, the label with the highest score is chosen.",
                source_block_text=(
                    "Target criterion is applied to each observation. "
                    "For each observation, the label with the highest score is chosen."
                ),
                block_id="doc_target:block:002",
            ),
            profile,
            cfg,
            rerank_target=0.88,
            rerank_margin=0.22,
        ),
        _scored_candidate(
            _row(
                "Target criterion = argmax_y score(y, x).",
                is_formula_like=True,
                block_id="doc_target:block:003",
            ),
            profile,
            cfg,
            rerank_target=0.90,
            rerank_margin=0.18,
        ),
    ]
    selected = STEP53_RUNNER.select_candidates(STEP53_RUNNER.dedupe_candidates(candidates), cfg)

    assert selected
    assert selected[0].support_profile["preferred_support_role"] == "definitional_anchor"
    assert any(candidate.support_profile["has_context_completion_source"] for candidate in selected)
    assert any(candidate.support_profile["formula_auxiliary_only"] for candidate in selected)
    summary = STEP53_RUNNER._support_pack_summary(selected)
    assert summary["definition_pack_ready"] is True
    assert "formula_only_support_pack" not in summary["weak_reasons"]


def test_step53_formula_only_summary_marks_weak_support_pack():
    cfg = _step53_cfg()
    profile = _profile()
    formula_only = _scored_candidate(
        _row(
            "Target criterion = argmax_y score(y, x).",
            is_formula_like=True,
        ),
        profile,
        cfg,
        rerank_target=0.92,
        rerank_margin=0.18,
    )
    summary = STEP53_RUNNER._support_pack_summary([formula_only])

    assert summary["definition_pack_ready"] is False
    assert "definition_anchor_missing" in summary["weak_reasons"]
    assert "formula_only_support_pack" in summary["weak_reasons"]


def test_overlay_propagates_support_profile_and_step53_support_summary():
    cfg = _step53_cfg()
    profile = _profile()
    candidate = _scored_candidate(
        _row(
            "Target criterion is a decision rule that assigns a label to each observation.",
            is_definition_like=True,
        ),
        profile,
        cfg,
        rerank_target=0.95,
        rerank_margin=0.30,
    )
    public_row = STEP53_RUNNER.public_candidate(candidate, profile)
    step5_row = {
        "kc_id": profile.kc_id,
        "canonical_name": profile.canonical_name,
        "aliases": profile.aliases,
        "evidence": [public_row],
        "support_pack_summary": STEP53_RUNNER._support_pack_summary([candidate]),
    }
    kc_row = {
        "kc_id": profile.kc_id,
        "canonical_name": profile.canonical_name,
        "aliases": profile.aliases,
        "kc_path": ["Demo topic", profile.canonical_name],
        "source_hierarchy_path": ["Demo topic", profile.canonical_name],
        "ancestor_hier_node_ids": [],
        "ancestor_labels": [],
        "leaf_hier_node_id": "leaf",
        "parent_hier_node_id": "parent",
    }
    records, stats = build_overlay_records(
        kc_rows=[kc_row],
        step5_rows_by_kc={profile.kc_id: step5_row},
        review_queue_by_kc={},
        provenance_index={},
        source_set_id="step5_3_set",
        source_run_id="step5_3_run",
        layer_preference=["docling", "mineru", "pymupdf"],
        role_hints_enabled=True,
    )

    assert len(records) == 1
    assert records[0]["support_profile"]["preferred_support_role"] == "definitional_anchor"
    assert records[0]["step5_3_support_pack_summary"]["definition_pack_ready"] is True
    assert stats["total_overlay_records"] == 1


def test_assess_overlay_candidate_respects_upstream_support_profile():
    definition_row = {
        "overlay_candidate_id": "ovl-1",
        "kc_id": "KC_TARGET_001",
        "canonical_name": "Target criterion",
        "aliases": ["Target rule"],
        "quote_surface": "Target criterion is a decision rule that assigns a label to each observation.",
        "source_block_text": "Target criterion is a decision rule that assigns a label to each observation.",
        "quote_verified": True,
        "provenance_normalization_status": "original",
        "doc_mismatch": False,
        "contamination_risk": "low",
        "is_formula_like": False,
        "is_definition_like": True,
        "is_heading_like": False,
        "is_procedure_like": False,
        "alignment_score": 12.0,
        "alignment_breakdown": {
            "exact_name_phrase": True,
            "exact_alias_phrase": False,
            "name_or_alias_hit": True,
            "context_keyword_hits": 2,
        },
        "support_profile": {
            "preferred_support_role": "definitional_anchor",
            "anchor_quality": "strong",
            "formula_auxiliary_only": False,
            "has_context_completion_source": False,
        },
        "role_hint": {"safe_role_hint": "definition", "top_role": "definition"},
    }
    formula_row = {
        **definition_row,
        "overlay_candidate_id": "ovl-2",
        "quote_surface": "Target criterion = argmax_y score(y, x).",
        "source_block_text": "Target criterion = argmax_y score(y, x).",
        "is_formula_like": True,
        "is_definition_like": False,
        "support_profile": {
            "preferred_support_role": "formula_or_parameter_anchor",
            "anchor_quality": "weak",
            "formula_auxiliary_only": True,
            "has_context_completion_source": False,
        },
        "role_hint": {"safe_role_hint": "equation", "top_role": "equation"},
    }

    definition_assessment = assess_overlay_candidate(definition_row)
    formula_assessment = assess_overlay_candidate(formula_row)

    assert definition_assessment["definition_candidate"] is True
    assert definition_assessment["selection_score"] > formula_assessment["selection_score"]
    assert formula_assessment["upstream_formula_auxiliary_only"] is True
    assert formula_assessment["upstream_support_role"] == "formula_or_parameter_anchor"
