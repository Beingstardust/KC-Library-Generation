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
            "max_context_completion_chars": 320,
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


def _kc_row(
    kc_id: str = "KC_TARGET_001",
    canonical_name: str = "Target criterion",
    *,
    aliases: list[str] | None = None,
    path: list[str] | None = None,
) -> dict[str, object]:
    hierarchy_path = list(path or ["Demo topic", canonical_name])
    return {
        "kc_id": kc_id,
        "canonical_name": canonical_name,
        "aliases": list(aliases or []),
        "kc_path": hierarchy_path,
        "source_hierarchy_path": hierarchy_path,
        "ancestor_hier_node_ids": ["topic-root"],
        "ancestor_labels": hierarchy_path[:-1],
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
    page_heading_norm: str | None = None,
    source_kc_id: str | None = None,
    exact_name_phrase: bool = False,
    exact_alias_phrase: bool = False,
    canonical_name_token_hits: int = 0,
    alias_token_hits: int = 0,
    name_or_alias_token_hits: int = 0,
    context_keyword_hits: int = 0,
    competitor_token_hits: int = 0,
    contamination_risk: str = "low",
    is_formula_like: bool = False,
    is_definition_like: bool = False,
    is_procedure_like: bool = False,
    is_example_like: bool = False,
    is_heading_like: bool = False,
    preferred_support_role: str = "definitional_anchor",
    anchor_quality: str = "strong",
    formula_auxiliary_only: bool = False,
    has_context_completion_source: bool = False,
    relation_like: bool = True,
    generic_context_only: bool = False,
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
        "page_heading_norm": page_heading_norm or patch_heading,
        "sentence_id": f"{doc_id}:{block_id}:{sent_idx}",
        "sent_idx": sent_idx,
        "char_start": 0,
        "char_end": len(text),
        "snippet": text,
        "source_block_text": source_block_text or text,
        "retrieval_scores": {"rerank_target": 0.9, "rerank_margin": 0.2},
        "alignment_score": alignment_score,
        "alignment_breakdown": {
            "name_or_alias_hit": bool(exact_name_phrase or exact_alias_phrase or name_or_alias_token_hits),
            "exact_name_phrase": exact_name_phrase,
            "exact_alias_phrase": exact_alias_phrase,
            "canonical_name_token_hits": canonical_name_token_hits,
            "alias_token_hits": alias_token_hits,
            "name_or_alias_token_hits": name_or_alias_token_hits,
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
                "is_heading_like": is_heading_like,
            },
        },
        "support_profile": {
            "preferred_support_role": preferred_support_role,
            "anchor_quality": anchor_quality,
            "formula_auxiliary_only": formula_auxiliary_only,
            "has_context_completion_source": has_context_completion_source,
            "needs_context_completion": has_context_completion_source,
            "relation_like": relation_like,
            "generic_context_only": generic_context_only,
            "contamination_exclusion_hint": contamination_exclusion_hint,
        },
        "source_kc_id": source_kc_id,
        "quote_verified": True,
        "provenance_normalization_status": "original",
    }


def _step5_row(
    *evidence: dict[str, object],
    kc_id: str = "KC_TARGET_001",
    canonical_name: str = "Target criterion",
    aliases: list[str] | None = None,
) -> dict[str, object]:
    return {
        "kc_id": kc_id,
        "canonical_name": canonical_name,
        "aliases": list(aliases or []),
        "support_pack_summary": {"definition_pack_ready": True, "weak_reasons": []},
        "evidence": list(evidence),
    }


def _source_manifests() -> dict[str, str]:
    return {
        "step5_3_set_manifest": "data/processed/kc_evidence_recalibrated/_sets/demo.json",
        "step4_5_sentence_overlay_manifest": "data/processed/retrieval_sentence_overlay/_sets/demo.json",
    }


def _positive_slot_texts(pack: dict[str, object]) -> list[str]:
    texts: list[str] = []
    for role in (
        "definition_kernel",
        "explanatory_gloss",
        "formula_notation",
        "scope_condition",
        "context_completion",
        "example_or_procedure",
    ):
        texts.extend([str(item["text"]) for item in pack["slots"][role]])
    return texts


def _slot_candidate_ids(pack: dict[str, object], *roles: str) -> set[str]:
    values: set[str] = set()
    for role in roles:
        for item in pack["slots"][role]:
            values.add(str(item["source_candidate_id"]))
    return values


def test_offtarget_definitional_row_is_rejected_despite_anchor_quality_strong():
    kc_row = _kc_row(
        "KC_CLU_CORE_002",
        "Intra-cluster Distance",
        path=["Clustering", "Core Concepts", "Intra-cluster Distance"],
    )
    fraud = _candidate(
        "However, if the data is highly skewed, then the precision is only 0.167.",
        patch_heading="Fraud Detection",
        page_heading_norm="Fraud Detection",
        preferred_support_role="definitional_anchor",
        anchor_quality="strong",
        relation_like=True,
    )
    target = _candidate(
        "In K-means clustering, the intra-cluster distance is measured by summing the distances from points to their cluster centroid.",
        block_id="doc-target:block:002",
        sent_idx=1,
        patch_heading="Intra-cluster Distance",
        page_heading_norm="Intra-cluster Distance",
        is_definition_like=True,
        relation_like=True,
        canonical_name_token_hits=3,
        name_or_alias_token_hits=3,
    )
    pack = compose_evidence_pack(
        kc_row=kc_row,
        step5_row=_step5_row(fraud, target, kc_id=kc_row["kc_id"], canonical_name=kc_row["canonical_name"]),
        sentence_context_index=None,
        cfg=_cfg(),
        source_manifests=_source_manifests(),
    )

    assert fraud["snippet"] not in _positive_slot_texts(pack)
    assert target["snippet"] in _positive_slot_texts(pack)


def test_candidate_pool_membership_alone_does_not_count_as_target_binding():
    kc_row = _kc_row("KC_TARGET_002", "Noise Point", path=["Clustering", "DBSCAN", "Noise Point"])
    generic = _candidate(
        "General background overview for this chapter.",
        patch_heading="Chapter Overview",
        page_heading_norm="Chapter Overview",
        preferred_support_role="definitional_anchor",
        anchor_quality="strong",
        relation_like=False,
    )
    pack = compose_evidence_pack(
        kc_row=kc_row,
        step5_row=_step5_row(generic, kc_id=kc_row["kc_id"], canonical_name=kc_row["canonical_name"]),
        sentence_context_index=None,
        cfg=_cfg(),
        source_manifests=_source_manifests(),
    )
    generic_id = build_pack_candidate_id(kc_row["kc_id"], 0, generic)

    assert not _positive_slot_texts(pack)
    assert pack["pack_quality"]["route"] == "insufficient_support_packet"
    assert pack["provenance_sidecar"]["drop_reasons"][generic_id] == "candidate_pool_membership_only"


def test_source_kc_mismatch_candidate_needs_explicit_target_cue():
    kc_row = _kc_row(
        "KC_EVAL_SAMP_003",
        "k-Fold Cross Validation",
        aliases=["cross validation"],
        path=["Evaluation", "Sampling", "k-Fold Cross Validation"],
    )
    mismatched_generic = _candidate(
        "This procedure tunes hyperparameters by repeated validation.",
        source_kc_id="KC_OTHER_001",
        patch_heading="Model Selection",
        page_heading_norm="Model Selection",
        relation_like=False,
    )
    mismatched_target = _candidate(
        "This approach is called k-fold cross-validation because each fold is used once for validation.",
        block_id="doc-target:block:002",
        sent_idx=1,
        source_kc_id="KC_OTHER_002",
        patch_heading="k-Fold Cross Validation",
        page_heading_norm="k-Fold Cross Validation",
        is_definition_like=True,
        relation_like=True,
        canonical_name_token_hits=3,
        name_or_alias_token_hits=3,
    )
    pack = compose_evidence_pack(
        kc_row=kc_row,
        step5_row=_step5_row(
            mismatched_generic,
            mismatched_target,
            kc_id=kc_row["kc_id"],
            canonical_name=kc_row["canonical_name"],
            aliases=["cross validation"],
        ),
        sentence_context_index=None,
        cfg=_cfg(),
        source_manifests=_source_manifests(),
    )

    assert mismatched_generic["snippet"] not in _positive_slot_texts(pack)
    assert mismatched_target["snippet"] in _positive_slot_texts(pack)


def test_formula_only_candidate_without_target_binding_is_dropped():
    kc_row = _kc_row(
        "KC_CLU_EVAL_001",
        "Internal Indices Overview",
        path=["Clustering", "Evaluation", "Internal Indices Overview"],
    )
    formula = _candidate(
        "In this case, Ic is the set of indices of the training examples belonging to class c, and Sigma is the covariance.",
        is_formula_like=True,
        preferred_support_role="formula_or_parameter_anchor",
        anchor_quality="strong",
        relation_like=False,
        patch_heading="Covariance",
        page_heading_norm="Covariance",
    )
    pack = compose_evidence_pack(
        kc_row=kc_row,
        step5_row=_step5_row(formula, kc_id=kc_row["kc_id"], canonical_name=kc_row["canonical_name"]),
        sentence_context_index=None,
        cfg=_cfg(),
        source_manifests=_source_manifests(),
    )
    formula_id = build_pack_candidate_id(kc_row["kc_id"], 0, formula)

    assert pack["slots"]["formula_notation"] == []
    assert pack["pack_quality"]["route"] == "insufficient_support_packet"
    assert pack["provenance_sidecar"]["drop_reasons"][formula_id] == "offtarget_formula_not_target_bound"


def test_formula_only_target_bound_candidate_is_kept_auxiliary_and_not_fake_standard():
    kc_row = _kc_row("KC_TARGET_003", "Target criterion")
    formula = _candidate(
        "Target criterion = argmax_y score(y, x).",
        is_formula_like=True,
        preferred_support_role="formula_or_parameter_anchor",
        anchor_quality="weak",
        relation_like=False,
        patch_heading="Target criterion",
        page_heading_norm="Target criterion",
        canonical_name_token_hits=2,
        name_or_alias_token_hits=2,
    )
    pack = compose_evidence_pack(
        kc_row=kc_row,
        step5_row=_step5_row(formula, kc_id=kc_row["kc_id"], canonical_name=kc_row["canonical_name"]),
        sentence_context_index=None,
        cfg=_cfg(),
        source_manifests=_source_manifests(),
    )

    assert pack["slots"]["definition_kernel"] == []
    assert [item["text"] for item in pack["slots"]["formula_notation"]] == [formula["snippet"]]
    assert pack["pack_quality"]["route"] in {"partial_grounded_packet", "escalated_evidence_rescue"}
    assert pack["pack_quality"]["route"] != "standard_drafting"


def test_natural_language_target_bound_anchor_beats_offtarget_formula():
    kc_row = _kc_row(
        "KC_CLU_EVAL_001",
        "Internal Indices Overview",
        path=["Clustering", "Evaluation", "Internal Indices Overview"],
    )
    target = _candidate(
        "Unsupervised measures are often called internal indices because they use only information present in the data set.",
        patch_heading="Internal Indices",
        page_heading_norm="Internal Indices",
        is_definition_like=True,
        relation_like=True,
        canonical_name_token_hits=2,
        name_or_alias_token_hits=2,
    )
    formula = _candidate(
        "In this case, Ic is the set of indices of the training examples belonging to class c, and Sigma is the covariance.",
        block_id="doc-target:block:002",
        sent_idx=1,
        patch_heading="Covariance",
        page_heading_norm="Covariance",
        is_formula_like=True,
        preferred_support_role="formula_or_parameter_anchor",
        relation_like=False,
    )
    pack = compose_evidence_pack(
        kc_row=kc_row,
        step5_row=_step5_row(target, formula, kc_id=kc_row["kc_id"], canonical_name=kc_row["canonical_name"]),
        sentence_context_index=None,
        cfg=_cfg(),
        source_manifests=_source_manifests(),
    )

    assert target["snippet"] in _positive_slot_texts(pack)
    assert formula["snippet"] not in [item["text"] for item in pack["slots"]["definition_kernel"]]


def test_context_completion_only_fires_for_target_bound_fragmentary_anchor():
    kc_row = _kc_row("KC_TARGET_004", "Target criterion")
    fragmentary = _candidate(
        "It assigns the label with the highest score.",
        source_block_text=(
            "Target criterion assigns the label with the highest score to each observation. "
            "It assigns the label with the highest score."
        ),
        patch_heading="Target criterion",
        page_heading_norm="Target criterion",
        is_definition_like=True,
        preferred_support_role="context_completion_anchor",
        anchor_quality="usable",
        has_context_completion_source=True,
        relation_like=False,
    )
    pack = compose_evidence_pack(
        kc_row=kc_row,
        step5_row=_step5_row(fragmentary, kc_id=kc_row["kc_id"], canonical_name=kc_row["canonical_name"]),
        sentence_context_index=None,
        cfg=_cfg(),
        source_manifests=_source_manifests(),
    )

    assert pack["pack_quality"]["context_completion_attempted"] is True
    assert pack["pack_quality"]["context_completion_used"] is True
    assert pack["slots"]["context_completion"]


def test_context_completion_does_not_fire_without_target_bound_anchor():
    kc_row = _kc_row("KC_TARGET_005", "Noise Point", path=["Clustering", "DBSCAN", "Noise Point"])
    fragmentary = _candidate(
        "It improves the result in this setting.",
        source_block_text="It improves the result in this setting by tuning the model.",
        patch_heading="Model Tuning",
        page_heading_norm="Model Tuning",
        preferred_support_role="context_completion_anchor",
        anchor_quality="strong",
        has_context_completion_source=True,
        relation_like=False,
    )
    pack = compose_evidence_pack(
        kc_row=kc_row,
        step5_row=_step5_row(fragmentary, kc_id=kc_row["kc_id"], canonical_name=kc_row["canonical_name"]),
        sentence_context_index=None,
        cfg=_cfg(),
        source_manifests=_source_manifests(),
    )

    assert pack["pack_quality"]["context_completion_used"] is False
    assert pack["slots"]["context_completion"] == []


def test_sibling_contrast_remains_empty_without_real_sibling_signal():
    kc_row = _kc_row("KC_TARGET_006", "Target criterion")
    target = _candidate(
        "Target criterion is the rule used to decide which label is assigned.",
        patch_heading="Target criterion",
        page_heading_norm="Target criterion",
        is_definition_like=True,
        relation_like=True,
        canonical_name_token_hits=2,
        name_or_alias_token_hits=2,
    )
    unrelated = _candidate(
        "General chapter background and setup information.",
        block_id="doc-target:block:002",
        sent_idx=1,
        contamination_risk="medium",
        relation_like=False,
        preferred_support_role="other",
    )
    pack = compose_evidence_pack(
        kc_row=kc_row,
        step5_row=_step5_row(target, unrelated, kc_id=kc_row["kc_id"], canonical_name=kc_row["canonical_name"]),
        sentence_context_index=None,
        cfg=_cfg(),
        source_manifests=_source_manifests(),
    )

    assert pack["slots"]["sibling_contrast"] == []


def test_medium_sibling_risk_alone_does_not_force_escalation():
    kc_row = _kc_row("KC_TARGET_007", "Target criterion")
    definition = _candidate(
        "Target criterion is the rule used to decide which label is assigned.",
        patch_heading="Target criterion",
        page_heading_norm="Target criterion",
        contamination_risk="medium",
        is_definition_like=True,
        relation_like=True,
        canonical_name_token_hits=2,
        name_or_alias_token_hits=2,
    )
    gloss = _candidate(
        "The target criterion favors the highest-scoring label for each observation.",
        block_id="doc-target:block:002",
        sent_idx=1,
        patch_heading="Target criterion",
        page_heading_norm="Target criterion",
        preferred_support_role="explanatory_anchor",
        anchor_quality="usable",
        relation_like=False,
        canonical_name_token_hits=2,
        name_or_alias_token_hits=2,
    )
    pack = compose_evidence_pack(
        kc_row=kc_row,
        step5_row=_step5_row(definition, gloss, kc_id=kc_row["kc_id"], canonical_name=kc_row["canonical_name"]),
        sentence_context_index=None,
        cfg=_cfg(),
        source_manifests=_source_manifests(),
    )

    assert pack["pack_quality"]["sibling_contamination_risk"] == "medium"
    assert pack["pack_quality"]["route"] == "standard_drafting"


def test_coverage_and_density_are_low_for_mostly_offtarget_rows():
    kc_row = _kc_row("KC_TARGET_008", "Intra-cluster Distance", path=["Clustering", "Core", "Intra-cluster Distance"])
    rows = [
        _candidate(
            "However, if the data is highly skewed, then the precision is only 0.167.",
            patch_heading="Fraud Detection",
            page_heading_norm="Fraud Detection",
            relation_like=True,
        ),
        _candidate(
            "Sigma = covariance(z - zi).",
            block_id="doc-target:block:002",
            sent_idx=1,
            patch_heading="Covariance",
            page_heading_norm="Covariance",
            is_formula_like=True,
            preferred_support_role="formula_or_parameter_anchor",
            relation_like=False,
        ),
        _candidate(
            "General background overview for the topic.",
            block_id="doc-target:block:003",
            sent_idx=2,
            patch_heading="Overview",
            page_heading_norm="Overview",
            relation_like=False,
        ),
    ]
    pack = compose_evidence_pack(
        kc_row=kc_row,
        step5_row=_step5_row(*rows, kc_id=kc_row["kc_id"], canonical_name=kc_row["canonical_name"]),
        sentence_context_index=None,
        cfg=_cfg(),
        source_manifests=_source_manifests(),
    )

    assert pack["pack_quality"]["coverage_score"] <= 0.45
    assert pack["pack_quality"]["density_score"] <= 0.3


def test_every_input_kc_gets_exactly_one_output_record():
    kc_rows = [
        _kc_row("KC_TARGET_009", "Target criterion"),
        _kc_row("KC_TARGET_010", "Another criterion"),
    ]
    step5_rows_by_kc = {
        "KC_TARGET_009": _step5_row(
            _candidate(
                "Target criterion is the rule used to decide which label is assigned.",
                patch_heading="Target criterion",
                page_heading_norm="Target criterion",
                is_definition_like=True,
                relation_like=True,
                canonical_name_token_hits=2,
                name_or_alias_token_hits=2,
            ),
            kc_id="KC_TARGET_009",
            canonical_name="Target criterion",
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
    assert {pack["kc_id"] for pack in packs} == {"KC_TARGET_009", "KC_TARGET_010"}


def test_recurrent_global_candidate_without_target_binding_is_dropped():
    shared = _candidate(
        "General background overview shared across many topics.",
        preferred_support_role="other",
        anchor_quality="strong",
        relation_like=False,
        patch_heading="Overview",
        page_heading_norm="Overview",
        patch_id="shared-patch",
    )
    kc_rows = [
        _kc_row("KC_A", "Noise Point", path=["Clustering", "DBSCAN", "Noise Point"]),
        _kc_row("KC_B", "Internal Indices Overview", path=["Clustering", "Evaluation", "Internal Indices Overview"]),
        _kc_row("KC_C", "k-Fold Cross Validation", path=["Evaluation", "Sampling", "k-Fold Cross Validation"]),
    ]
    step5_rows_by_kc = {
        "KC_A": _step5_row(
            shared,
            _candidate(
                "A noise point is any point that is neither a core point nor a border point.",
                block_id="doc-target:block:002",
                sent_idx=1,
                patch_heading="Noise Point",
                page_heading_norm="Noise Point",
                is_definition_like=True,
                relation_like=True,
                canonical_name_token_hits=2,
                name_or_alias_token_hits=2,
            ),
            kc_id="KC_A",
            canonical_name="Noise Point",
        ),
        "KC_B": _step5_row(
            shared,
            _candidate(
                "Unsupervised measures are often called internal indices because they use only information present in the data set.",
                block_id="doc-target:block:003",
                sent_idx=1,
                patch_heading="Internal Indices",
                page_heading_norm="Internal Indices",
                is_definition_like=True,
                relation_like=True,
                canonical_name_token_hits=2,
                name_or_alias_token_hits=2,
            ),
            kc_id="KC_B",
            canonical_name="Internal Indices Overview",
        ),
        "KC_C": _step5_row(
            shared,
            _candidate(
                "This approach is called k-fold cross-validation because each fold is used once for validation.",
                block_id="doc-target:block:004",
                sent_idx=1,
                patch_heading="k-Fold Cross Validation",
                page_heading_norm="k-Fold Cross Validation",
                is_definition_like=True,
                relation_like=True,
                canonical_name_token_hits=3,
                name_or_alias_token_hits=3,
            ),
            kc_id="KC_C",
            canonical_name="k-Fold Cross Validation",
        ),
    }

    packs, _ = compose_evidence_packs(
        kc_rows=kc_rows,
        step5_rows_by_kc=step5_rows_by_kc,
        sentence_context_index=None,
        cfg=_cfg(),
        source_manifests=_source_manifests(),
    )
    pack_a = next(pack for pack in packs if pack["kc_id"] == "KC_A")
    shared_id = build_pack_candidate_id("KC_A", 0, shared)

    assert shared["snippet"] not in _positive_slot_texts(pack_a)
    assert pack_a["provenance_sidecar"]["drop_reasons"][shared_id] == "recurring_global_candidate_without_target_binding"


def test_regression_intra_cluster_distance_drops_fraud_and_keeps_target_support():
    kc_row = _kc_row(
        "KC_CLU_CORE_002",
        "Intra-cluster Distance",
        path=["Clustering", "Core", "Intra-cluster Distance"],
    )
    fraud = _candidate(
        "However, if the data is highly skewed, then the precision is only 0.167.",
        patch_heading="Fraud Detection",
        page_heading_norm="Fraud Detection",
        relation_like=True,
    )
    cluster_distance = _candidate(
        "Given a set of objects, the overall objective is to minimize the intra-cluster distance within each cluster.",
        block_id="doc-target:block:002",
        sent_idx=1,
        patch_heading="Intra-cluster Distance",
        page_heading_norm="Intra-cluster Distance",
        is_definition_like=True,
        relation_like=True,
        canonical_name_token_hits=3,
        name_or_alias_token_hits=3,
    )
    pack = compose_evidence_pack(
        kc_row=kc_row,
        step5_row=_step5_row(fraud, cluster_distance, kc_id=kc_row["kc_id"], canonical_name=kc_row["canonical_name"]),
        sentence_context_index=None,
        cfg=_cfg(),
        source_manifests=_source_manifests(),
    )

    assert fraud["snippet"] not in _positive_slot_texts(pack)
    assert cluster_distance["snippet"] in _positive_slot_texts(pack)
    assert pack["pack_quality"]["route"] in {"standard_drafting", "escalated_evidence_rescue"}


def test_regression_kfold_cross_validation_prefers_target_sentence():
    kc_row = _kc_row(
        "KC_EVAL_SAMP_003",
        "k-Fold Cross Validation",
        aliases=["cross validation"],
        path=["Evaluation", "Sampling", "k-Fold Cross Validation"],
    )
    hyperparameter = _candidate(
        "At the end of this algorithm, we obtain the best choice of the hyper-parameter value and the final classification model.",
        patch_heading="Hyper-parameter Selection",
        page_heading_norm="Hyper-parameter Selection",
        relation_like=True,
    )
    target = _candidate(
        "This approach is called k-fold cross-validation because each fold is used once for validation.",
        block_id="doc-target:block:002",
        sent_idx=1,
        patch_heading="k-Fold Cross Validation",
        page_heading_norm="k-Fold Cross Validation",
        is_definition_like=True,
        relation_like=True,
        canonical_name_token_hits=3,
        name_or_alias_token_hits=3,
    )
    pack = compose_evidence_pack(
        kc_row=kc_row,
        step5_row=_step5_row(
            hyperparameter,
            target,
            kc_id=kc_row["kc_id"],
            canonical_name=kc_row["canonical_name"],
            aliases=["cross validation"],
        ),
        sentence_context_index=None,
        cfg=_cfg(),
        source_manifests=_source_manifests(),
    )

    assert hyperparameter["snippet"] not in _positive_slot_texts(pack)
    assert target["snippet"] in _positive_slot_texts(pack)


def test_regression_internal_indices_prefers_target_sentence():
    kc_row = _kc_row(
        "KC_CLU_EVAL_001",
        "Internal Indices Overview",
        path=["Clustering", "Evaluation", "Internal Indices Overview"],
    )
    target = _candidate(
        "Unsupervised measures are often called internal indices because they use only information present in the data set.",
        patch_heading="Internal Indices",
        page_heading_norm="Internal Indices",
        is_definition_like=True,
        relation_like=True,
        canonical_name_token_hits=2,
        name_or_alias_token_hits=2,
    )
    covariance = _candidate(
        "In this case, Ic is the set of indices of the training examples belonging to class c, and Sigma is the covariance.",
        block_id="doc-target:block:002",
        sent_idx=1,
        patch_heading="Covariance",
        page_heading_norm="Covariance",
        is_formula_like=True,
        preferred_support_role="formula_or_parameter_anchor",
        relation_like=False,
    )
    pack = compose_evidence_pack(
        kc_row=kc_row,
        step5_row=_step5_row(target, covariance, kc_id=kc_row["kc_id"], canonical_name=kc_row["canonical_name"]),
        sentence_context_index=None,
        cfg=_cfg(),
        source_manifests=_source_manifests(),
    )

    assert target["snippet"] in [item["text"] for item in pack["slots"]["definition_kernel"]] or target["snippet"] in [
        item["text"] for item in pack["slots"]["explanatory_gloss"]
    ]
    assert covariance["snippet"] not in [item["text"] for item in pack["slots"]["definition_kernel"]]


def test_step66_propagates_evidence_pack_metadata():
    kc_row = _kc_row("KC_TARGET_011", "Target criterion")
    evidence = _candidate(
        "Target criterion is the rule used to decide which label is assigned.",
        patch_heading="Target criterion",
        page_heading_norm="Target criterion",
        is_definition_like=True,
        relation_like=True,
        canonical_name_token_hits=2,
        name_or_alias_token_hits=2,
    )
    step5_row = _step5_row(evidence, kc_id=kc_row["kc_id"], canonical_name=kc_row["canonical_name"])
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
    kc_row = _kc_row("KC_TARGET_012", "Target criterion")
    step5_row = _step5_row(
        _candidate(
            "Target criterion is the rule used to decide which label is assigned.",
            patch_heading="Target criterion",
            page_heading_norm="Target criterion",
            is_definition_like=True,
            relation_like=True,
            canonical_name_token_hits=2,
            name_or_alias_token_hits=2,
        ),
        kc_id=kc_row["kc_id"],
        canonical_name=kc_row["canonical_name"],
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
