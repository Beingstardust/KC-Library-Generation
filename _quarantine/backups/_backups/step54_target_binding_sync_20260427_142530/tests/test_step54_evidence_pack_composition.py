from __future__ import annotations

from kc_l.kc.drafting_input_overlay import build_overlay_records
from kc_l.retrieval_gate.evidence_pack_composition import (
    build_pack_candidate_id,
    compose_evidence_pack,
    compose_evidence_packs,
)


def _cfg() -> dict[str, object]:
    return {
        "composition": {
            "max_slots_total": 10,
            "max_definition_kernel": 2,
            "max_explanatory_gloss": 3,
            "max_formula_notation": 2,
            "max_scope_condition": 2,
            "max_context_completion": 2,
            "max_example_or_procedure": 1,
            "max_sibling_contrast": 2,
            "max_context_completion_items": 2,
            "max_context_completion_chars": 240,
            "max_chars_for_drafting": 900,
            "max_candidates_considered_per_kc": 12,
            "context_window_sentences": 1,
            "min_definition_score": 3.0,
            "min_explanatory_score": 2.0,
            "min_formula_score": 2.0,
            "min_scope_score": 2.0,
            "min_example_score": 2.0,
            "min_sibling_score": 1.5,
        },
        "routing": {
            "standard_min_coverage_score": 0.55,
            "standard_min_density_score": 0.2,
            "partial_min_coverage_score": 0.2,
        },
    }


def _kc_row(kc_id: str = "KC_TARGET_001", canonical_name: str = "Target criterion") -> dict[str, object]:
    return {
        "kc_id": kc_id,
        "canonical_name": canonical_name,
        "aliases": ["Target rule"],
        "kc_path": ["Demo topic", canonical_name],
        "source_hierarchy_path": ["Demo topic", canonical_name],
        "ancestor_hier_node_ids": ["topic-root"],
        "ancestor_labels": ["Demo topic"],
        "leaf_hier_node_id": "leaf",
        "parent_hier_node_id": "topic-root",
    }


def _candidate(
    text: str,
    *,
    source_block_text: str | None = None,
    doc_id: str = "doc-target",
    block_id: str = "doc-target:block:001",
    page_index: int = 1,
    sent_idx: int = 0,
    patch_id: str = "patch-1",
    patch_heading: str = "Target criterion",
    exact_name_phrase: bool = True,
    context_keyword_hits: int = 1,
    competitor_token_hits: int = 0,
    contamination_risk: str = "low",
    is_formula_like: bool = False,
    is_definition_like: bool = False,
    is_procedure_like: bool = False,
    is_example_like: bool = False,
    preferred_support_role: str = "definitional_anchor",
    anchor_quality: str = "strong",
    formula_auxiliary_only: bool = False,
    has_context_completion_source: bool = False,
    relation_like: bool = True,
    contamination_exclusion_hint: bool = False,
    alignment_score: float = 12.0,
) -> dict[str, object]:
    return {
        "doc_id": doc_id,
        "block_id": block_id,
        "page_index": page_index,
        "bbox": None,
        "layer": "docling",
        "reveal_group_id": None,
        "patch_id": patch_id,
        "patch_heading": patch_heading,
        "sentence_id": f"{doc_id}:{block_id}:{sent_idx}",
        "sent_idx": sent_idx,
        "char_start": 0,
        "char_end": len(text),
        "snippet": text,
        "source_block_text": source_block_text or text,
        "retrieval_scores": {"rerank_target": 0.9, "rerank_margin": 0.2},
        "alignment_score": alignment_score,
        "alignment_breakdown": {
            "name_or_alias_hit": exact_name_phrase,
            "exact_name_phrase": exact_name_phrase,
            "exact_alias_phrase": False,
            "context_keyword_hits": context_keyword_hits,
            "competitor_token_hits": competitor_token_hits,
            "doc_mismatch": False,
            "strong_same_topic": True,
            "strong_structured_candidate": True,
            "contamination_risk": contamination_risk,
            "contamination_signals": ["sibling_bleed"] if contamination_risk != "low" else [],
            "flags": {
                "is_formula_like": is_formula_like,
                "is_definition_like": is_definition_like,
                "is_procedure_like": is_procedure_like,
                "is_example_like": is_example_like,
                "is_heading_like": False,
            },
        },
        "support_profile": {
            "preferred_support_role": preferred_support_role,
            "anchor_quality": anchor_quality,
            "formula_auxiliary_only": formula_auxiliary_only,
            "has_context_completion_source": has_context_completion_source,
            "needs_context_completion": has_context_completion_source,
            "relation_like": relation_like,
            "contamination_exclusion_hint": contamination_exclusion_hint,
        },
        "quote_verified": True,
        "provenance_normalization_status": "original",
    }


def _step5_row(*evidence: dict[str, object], kc_id: str = "KC_TARGET_001") -> dict[str, object]:
    return {
        "kc_id": kc_id,
        "canonical_name": "Target criterion",
        "aliases": ["Target rule"],
        "support_pack_summary": {"definition_pack_ready": True, "weak_reasons": []},
        "evidence": list(evidence),
    }


def _source_manifests() -> dict[str, str]:
    return {
        "step5_3_set_manifest": "data/processed/kc_evidence_recalibrated/_sets/demo.json",
        "step4_5_sentence_overlay_manifest": "data/processed/retrieval_sentence_overlay/_sets/demo.json",
    }


def test_formula_only_candidate_is_auxiliary_when_explanatory_text_exists():
    kc_row = _kc_row()
    step5_row = _step5_row(
        _candidate(
            "Target criterion is the rule used to decide which label is assigned.",
            is_definition_like=True,
            preferred_support_role="definitional_anchor",
        ),
        _candidate(
            "Target criterion = argmax_y score(y, x).",
            block_id="doc-target:block:002",
            sent_idx=1,
            is_formula_like=True,
            is_definition_like=False,
            preferred_support_role="formula_or_parameter_anchor",
            anchor_quality="weak",
            formula_auxiliary_only=True,
            relation_like=False,
        ),
    )

    pack = compose_evidence_pack(
        kc_row=kc_row,
        step5_row=step5_row,
        sentence_context_index=None,
        cfg=_cfg(),
        source_manifests=_source_manifests(),
    )

    assert pack["slots"]["definition_kernel"]
    assert pack["slots"]["formula_notation"]
    assert all(
        item["text"] != "Target criterion = argmax_y score(y, x)."
        for item in pack["slots"]["definition_kernel"]
    )
    assert pack["pack_quality"]["formula_auxiliary_only"] is True


def test_formula_can_be_primary_only_without_natural_language_anchor():
    kc_row = _kc_row()
    formula_only = _candidate(
        "Target criterion = argmax_y score(y, x).",
        is_formula_like=True,
        is_definition_like=False,
        preferred_support_role="formula_or_parameter_anchor",
        anchor_quality="weak",
        formula_auxiliary_only=False,
        relation_like=True,
        exact_name_phrase=True,
        context_keyword_hits=0,
        alignment_score=10.0,
    )
    pack = compose_evidence_pack(
        kc_row=kc_row,
        step5_row=_step5_row(formula_only),
        sentence_context_index=None,
        cfg=_cfg(),
        source_manifests=_source_manifests(),
    )

    assert pack["pack_quality"]["formula_primary"] is True
    assert pack["pack_quality"]["route"] != "standard_drafting"
    assert any(item["text"] == formula_only["snippet"] for item in pack["slots"]["definition_kernel"])


def test_fragmentary_definition_receives_context_completion():
    kc_row = _kc_row()
    fragmentary = _candidate(
        "It assigns the label with the highest score.",
        source_block_text=(
            "Target criterion assigns the label with the highest score to each observation. "
            "It assigns the label with the highest score."
        ),
        is_definition_like=True,
        preferred_support_role="context_completion_anchor",
        anchor_quality="usable",
        has_context_completion_source=True,
    )
    pack = compose_evidence_pack(
        kc_row=kc_row,
        step5_row=_step5_row(fragmentary),
        sentence_context_index=None,
        cfg=_cfg(),
        source_manifests=_source_manifests(),
    )

    assert pack["slots"]["context_completion"]
    assert pack["pack_quality"]["context_completion_used"] is True


def test_sibling_evidence_is_not_positive_support():
    kc_row = _kc_row()
    target = _candidate(
        "Target criterion is the rule used to decide which label is assigned.",
        is_definition_like=True,
        preferred_support_role="definitional_anchor",
    )
    sibling = _candidate(
        "Competing sibling criterion uses a different score to choose the label.",
        block_id="doc-target:block:002",
        sent_idx=1,
        exact_name_phrase=False,
        context_keyword_hits=0,
        competitor_token_hits=2,
        contamination_risk="high",
        preferred_support_role="contamination_or_sibling_exclusion",
        anchor_quality="weak",
        contamination_exclusion_hint=True,
        alignment_score=8.0,
    )
    pack = compose_evidence_pack(
        kc_row=kc_row,
        step5_row=_step5_row(target, sibling),
        sentence_context_index=None,
        cfg=_cfg(),
        source_manifests=_source_manifests(),
    )
    sibling_id = build_pack_candidate_id(kc_row["kc_id"], 1, sibling)

    positive_ids = {
        item["source_candidate_id"]
        for role in ("definition_kernel", "explanatory_gloss", "formula_notation", "scope_condition")
        for item in pack["slots"][role]
    }
    assert sibling_id not in positive_ids
    assert sibling_id in {
        item["source_candidate_id"]
        for item in pack["slots"]["sibling_contrast"]
    } or sibling_id in pack["provenance_sidecar"]["dropped_candidate_ids"]


def test_ordered_pack_for_drafting_preserves_source_order():
    kc_row = _kc_row()
    later_page = _candidate(
        "Target criterion is the rule used to decide which label is assigned.",
        page_index=2,
        sent_idx=4,
        is_definition_like=True,
        preferred_support_role="definitional_anchor",
    )
    earlier_page = _candidate(
        "It applies when the classifier must pick the highest-scoring label.",
        block_id="doc-target:block:002",
        page_index=1,
        sent_idx=1,
        preferred_support_role="explanatory_anchor",
        anchor_quality="usable",
    )
    pack = compose_evidence_pack(
        kc_row=kc_row,
        step5_row=_step5_row(later_page, earlier_page),
        sentence_context_index=None,
        cfg=_cfg(),
        source_manifests=_source_manifests(),
    )

    page_indexes = [item["page_index"] for item in pack["ordered_pack_for_drafting"]]
    assert page_indexes == sorted(page_indexes)


def test_every_input_kc_gets_exactly_one_output_record():
    kc_rows = [_kc_row("KC_TARGET_001"), _kc_row("KC_TARGET_002", canonical_name="Another criterion")]
    step5_rows_by_kc = {
        "KC_TARGET_001": _step5_row(
            _candidate(
                "Target criterion is the rule used to decide which label is assigned.",
                is_definition_like=True,
            ),
            kc_id="KC_TARGET_001",
        )
    }

    packs, _ = compose_evidence_packs(
        kc_rows=kc_rows,
        step5_rows_by_kc=step5_rows_by_kc,
        sentence_context_index=None,
        cfg=_cfg(),
        source_manifests=_source_manifests(),
    )

    assert len(packs) == 2
    assert {pack["kc_id"] for pack in packs} == {"KC_TARGET_001", "KC_TARGET_002"}


def test_pack_route_is_deterministic():
    kc_row = _kc_row()
    step5_row = _step5_row(
        _candidate(
            "Target criterion is the rule used to decide which label is assigned.",
            is_definition_like=True,
            preferred_support_role="definitional_anchor",
        ),
        _candidate(
            "It applies when the classifier must pick the highest-scoring label.",
            block_id="doc-target:block:002",
            sent_idx=1,
            preferred_support_role="explanatory_anchor",
            anchor_quality="usable",
        ),
    )

    first = compose_evidence_pack(
        kc_row=kc_row,
        step5_row=step5_row,
        sentence_context_index=None,
        cfg=_cfg(),
        source_manifests=_source_manifests(),
    )
    second = compose_evidence_pack(
        kc_row=kc_row,
        step5_row=step5_row,
        sentence_context_index=None,
        cfg=_cfg(),
        source_manifests=_source_manifests(),
    )

    assert first["pack_quality"]["route"] == second["pack_quality"]["route"]
    assert [item["candidate_id"] for item in first["ordered_pack_for_drafting"]] == [
        item["candidate_id"] for item in second["ordered_pack_for_drafting"]
    ]


def test_provenance_sidecar_records_selected_and_dropped_candidates():
    kc_row = _kc_row()
    selected = _candidate(
        "Target criterion is the rule used to decide which label is assigned.",
        is_definition_like=True,
        preferred_support_role="definitional_anchor",
    )
    dropped = _candidate(
        "General background overview.",
        block_id="doc-target:block:002",
        sent_idx=1,
        preferred_support_role="other",
        anchor_quality="weak",
        exact_name_phrase=False,
        context_keyword_hits=0,
        alignment_score=0.5,
    )
    pack = compose_evidence_pack(
        kc_row=kc_row,
        step5_row=_step5_row(selected, dropped),
        sentence_context_index=None,
        cfg=_cfg(),
        source_manifests=_source_manifests(),
    )
    dropped_id = build_pack_candidate_id(kc_row["kc_id"], 1, dropped)

    assert pack["provenance_sidecar"]["selected_candidate_ids"]
    assert dropped_id in pack["provenance_sidecar"]["dropped_candidate_ids"]
    assert pack["provenance_sidecar"]["drop_reasons"][dropped_id] in {
        "lower_priority_support",
        "sibling_contamination_risk",
    }


def test_step66_propagates_evidence_pack_metadata():
    kc_row = _kc_row()
    evidence = _candidate(
        "Target criterion is the rule used to decide which label is assigned.",
        is_definition_like=True,
        preferred_support_role="definitional_anchor",
    )
    step5_row = _step5_row(evidence)
    pack = compose_evidence_pack(
        kc_row=kc_row,
        step5_row=step5_row,
        sentence_context_index=None,
        cfg=_cfg(),
        source_manifests=_source_manifests(),
    )

    records, _ = build_overlay_records(
        kc_rows=[kc_row],
        step5_rows_by_kc={kc_row["kc_id"]: step5_row},
        review_queue_by_kc={},
        evidence_packs_by_kc={kc_row["kc_id"]: pack},
        provenance_index={},
        source_set_id="step5_3_set",
        source_run_id="step5_3_run",
        layer_preference=["docling", "mineru", "pymupdf"],
        role_hints_enabled=False,
    )

    assert len(records) == 1
    assert records[0]["evidence_pack_available"] is True
    assert records[0]["evidence_pack_version"] == pack["pack_version"]
    assert records[0]["evidence_pack_quality"]["route"] == pack["pack_quality"]["route"]
    assert "definition_kernel" in records[0]["evidence_pack_membership"]["slot_roles"]


def test_step66_fallback_still_works_without_evidence_pack():
    kc_row = _kc_row()
    step5_row = _step5_row(
        _candidate(
            "Target criterion is the rule used to decide which label is assigned.",
            is_definition_like=True,
            preferred_support_role="definitional_anchor",
        )
    )
    records, stats = build_overlay_records(
        kc_rows=[kc_row],
        step5_rows_by_kc={kc_row["kc_id"]: step5_row},
        review_queue_by_kc={},
        evidence_packs_by_kc={},
        provenance_index={},
        source_set_id="step5_3_set",
        source_run_id="step5_3_run",
        layer_preference=["docling", "mineru", "pymupdf"],
        role_hints_enabled=False,
    )

    assert len(records) == 1
    assert records[0]["evidence_pack_available"] is False
    assert records[0]["evidence_pack_quality"] == {}
    assert stats["evidence_pack_available_count"] == 0
