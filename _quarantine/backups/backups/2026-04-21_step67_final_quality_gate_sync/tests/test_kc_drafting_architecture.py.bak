from __future__ import annotations

import json
import importlib.util
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from kc_l.kc_drafting.contracts import (
    AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED,
    AUTHORITATIVE_DEFINITION_STATUS_NORMALIZED_GROUNDED,
    AUTHORITATIVE_DEFINITION_STATUS_SEED_FLOOR_FALLBACK,
)
from kc_l.kc_drafting.backend import HeuristicDraftingBackend, OllamaDraftingBackend, build_drafting_backend
from kc_l.kc_drafting.canonicalization import (
    CANONICALIZATION_MODE_DETERMINISTIC_CLEANUP,
    CANONICALIZATION_MODE_EXTRACTIVE_SELECTION,
    CANONICALIZATION_MODE_IDENTITY,
    CANONICALIZATION_MODE_RAW_PASSTHROUGH,
    STEP675_CANONICALIZATION_CONTRACT_VERSION,
    canonicalize_draft_bundle_row,
    emit_canonicalized_draft_bundles,
)
from kc_l.kc_drafting.config import normalize_runner_config
from kc_l.kc_drafting.heuristic_core import (
    assess_overlay_candidate,
    build_definition_evidence_packet,
    build_kc_draft_bundles,
    select_definition_support_pack,
    selected_definition_review_quality,
)
from kc_l.kc_drafting.hierarchy_refs import typed_topic_hierarchy_fields
from kc_l.kc_drafting import orchestration as orchestration_module
from kc_l.kc_drafting import packetization as packetization_module
from kc_l.kc_drafting.packetization import (
    build_restarted_review_packet,
    emit_restarted_review_packets_from_draft_bundles,
    validate_restarted_review_packet,
)
from kc_l.kc_drafting.seed_floor_triage import (
    REVIEW_READINESS_NEEDS_ATTENTION,
    STEP67B_CONTRACT_VERSION,
    TRIAGE_BUCKET_PIPELINE_MISS_FORMULA_EXPLANATION_PAIRING,
    TRIAGE_BUCKET_PIPELINE_MISS_NEIGHBOR_BLEED_OR_LOCAL_ALIGNMENT,
    TRIAGE_BUCKET_STRUCTURAL_SEED_OR_HIERARCHY_ISSUE,
    triage_seed_floor_bundle_row,
)
from kc_l.runtime.current_step_artifacts import current_step_artifact_specs
from kc_l.utils import kc_step67_model_drafting as drafting_module
from kc_l.utils.kc_step67_model_drafting import (
    FieldCandidate,
    Step67DraftingPolicy,
    Step67ModelRuntime,
    _definition_candidates,
    _definition_draft_supported_single_span_fallback_candidate,
    _definition_draft_supported_single_span_fallback_salvage_value,
    _definition_draft_supported_single_span_fallback_value,
    _kc_descriptor,
    _repair_definition_support_binding,
    _run_definition_verification_phase,
    _rerank_definition_candidates,
    _source_faithful_normalized_definition_candidate,
    build_kc_draft_bundles_llm,
)
from kc_l.utils.json_io import read_json, read_jsonl


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STEP67_RUNNER = _load_module(
    REPO_ROOT / "steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py",
    "step67_runner_architecture_test",
)
STEP68_RUNNER = _load_module(
    REPO_ROOT / "steps/step_06_8_kc_review_packet_emission/scripts/run_step6_8_kc_review_packet_emission.py",
    "step68_runner_architecture_test",
)
STEP675_RUNNER = _load_module(
    REPO_ROOT / "steps/step_06_75_kc_draft_canonicalization/scripts/run_step6_75_kc_draft_canonicalization.py",
    "step675_runner_architecture_test",
)
STEP67B_RUNNER = _load_module(
    REPO_ROOT / "steps/step_06_7b_seed_floor_triage_and_rescue/scripts/run_step6_7b_seed_floor_triage_and_rescue.py",
    "step67b_runner_architecture_test",
)


def test_normalize_runner_config_records_domain_policy_authority():
    cfg = {
        "runtime_profile": {"name": "hpc_gpu"},
        "models": {
            "generation": {
                "provider": "ollama",
                "resolved_model_alias": "qwen3:30b",
                "base_url": "http://127.0.0.1:11567",
            },
            "gate_llm": {
                "resolved_model_alias": "qwen3:30b",
                "base_url": "http://127.0.0.1:11567",
            },
        },
        "step6_7": {
            "contract_version": "step6_7_authoritative_runtime_v1",
            "execution_mode": "llm",
            "llm_required": True,
            "fail_closed_when_llm_unavailable": True,
            "heuristic_mode_name": "heuristic_extract_grounded_v1",
            "inputs": {
                "step6_6_set_manifest": "data/work/cache/current_step_artifacts/step6_6_set_manifest.current.json",
            },
            "outputs": {
                "processed_root": "data/processed/kc_drafts",
                "sets_root": "data/processed/kc_drafts/_sets",
                "runs_root": "data/runs",
            },
            "selection": {
                "max_bundle_size": 6,
                "max_explanatory_candidates": 5,
            },
            "drafting_policy": {
                "domain_policy": "model_evaluation_background_v1",
                "definition_candidate_limit": 5,
                "scope_candidate_limit": 5,
                "family_context_limit": 4,
                "completion_context_limit": 4,
                "evidence_text_max_chars": 320,
                "short_definition_max_chars": 220,
                "short_definition_max_tokens": 32,
            },
        },
    }

    normalized = normalize_runner_config(
        cfg,
        config_path=REPO_ROOT / "data/work/cache/generated_configs/synthetic_main_quest.hpc_gpu.yaml",
        repo_root=REPO_ROOT,
    )
    execution = normalized["execution"]

    assert execution["domain_policy_name"] == "model_evaluation_background_v1"
    assert execution["domain_policy_field"] == "step6_7.drafting_policy.domain_policy"
    assert execution["builder_function"] == "build_kc_draft_bundles_llm"


def test_backend_factory_selects_llm_backend_contract():
    backend = build_drafting_backend(
        {
            "execution_mode": "llm",
            "provider": "ollama",
            "generation_model_alias": "qwen3:30b",
            "generation_base_url": "http://127.0.0.1:11567",
        },
        drafting_cfg={"domain_policy": "model_evaluation_background_v1"},
        selection_cfg={"max_bundle_size": 6, "max_explanatory_candidates": 5},
    )
    assert isinstance(backend, OllamaDraftingBackend)


def test_backend_factory_selects_heuristic_backend_contract():
    backend = build_drafting_backend(
        {
            "execution_mode": "heuristic",
        },
        drafting_cfg={"domain_policy": "none"},
        selection_cfg={"max_bundle_size": 4, "max_explanatory_candidates": 3},
    )
    assert isinstance(backend, HeuristicDraftingBackend)


def test_restarted_review_packet_preserves_empty_kc_specific_criteria_on_real_bundle():
    bundle_path = REPO_ROOT / "data/processed/kc_drafts/2026-04-08_131447/kc_draft_bundles.jsonl"
    bundle = next(
        item
        for item in read_jsonl(bundle_path)
        if str(item.get("draft_status") or "") in {"draft_ready", "draft_ready_with_holds"}
    )

    packet = build_restarted_review_packet(
        draft_bundle=bundle,
        step4_set_id="step4_set",
        step4_5_set_id="step4_5_set",
        step5_set_id="step5_set",
        step6_6_set_id="step6_6_set",
        step6_7_set_id="step6_7_set",
        step6_7b_set_id="",
        step6_8_run_id="2026-04-11_test",
    )

    assert "kc_specific_criteria" in packet
    assert packet["kc_specific_criteria"] == ""
    validate_restarted_review_packet(packet)


def _synthetic_evidence_item(*, kc_id: str, suffix: str = "01") -> dict[str, object]:
    return {
        "bundle_role": "definition_support",
        "overlay_candidate_id": f"{kc_id}:overlay:{suffix}",
        "selection_score": 8.5,
        "candidate_text": "Synthetic evidence sentence for packetization coverage.",
        "quote_surface": "Synthetic evidence sentence for packetization coverage.",
        "source_block_text": "Synthetic evidence sentence for packetization coverage.",
        "doc_id": "doc.synthetic",
        "block_id": f"block.{suffix}",
        "page_index": 0,
        "sentence_id": f"sent.{suffix}",
        "layer": "sentence",
        "alignment_score": 0.9,
        "contamination_risk": "low",
        "provenance_normalization_status": "normalized",
        "quote_verification_status": "verified",
        "assessment": {
            "classification": "definition_support",
            "definition_signal": True,
            "scope_signal": False,
            "bare_heading": False,
            "formula_lead_in": False,
            "question_like": False,
        },
    }


def _synthetic_field_provenance(status: str = "grounded") -> dict[str, object]:
    return {
        "status": status,
        "overlay_candidate_ids": ["KC_SYN:overlay:01"] if status == "grounded" else [],
        "source_set_ids": ["step6_6_set"],
        "source_run_ids": ["step6_7_run"],
    }


def _synthetic_hierarchy_fields(*, kc_id: str, canonical_name: str, topic_path_labels: list[str] | None = None) -> dict[str, object]:
    topic_labels = topic_path_labels or ["Synthetic Domain", "Synthetic Branch"]
    hierarchy_payload = {
        "kc_id": kc_id,
        "ancestor_hier_node_ids": [f"hier::{index + 1}" for index in range(len(topic_labels))],
        "ancestor_labels": list(topic_labels),
        "leaf_hier_node_id": f"kc::{kc_id}",
        "parent_hier_node_id": f"hier::{len(topic_labels)}" if topic_labels else "",
        "source_hierarchy_path": [*topic_labels, canonical_name],
    }
    return typed_topic_hierarchy_fields(hierarchy_payload)


def _synthetic_overlay_row(
    *,
    kc_id: str,
    canonical_name: str,
    suffix: str,
    text: str,
    topic_path_labels: list[str] | None = None,
) -> dict[str, object]:
    hierarchy_fields = _synthetic_hierarchy_fields(
        kc_id=kc_id,
        canonical_name=canonical_name,
        topic_path_labels=topic_path_labels,
    )
    ancestry = dict(hierarchy_fields["hierarchy_ancestry"])
    return {
        "kc_id": kc_id,
        "overlay_candidate_id": f"{kc_id}:overlay:{suffix}",
        "canonical_name": canonical_name,
        "aliases": [],
        "seed_definition": f"{canonical_name} seed definition.",
        "quote_surface": text,
        "source_block_text": text,
        "doc_id": "doc.synthetic",
        "block_id": f"block.{suffix}",
        "page_index": 0,
        "sentence_id": f"sent.{suffix}",
        "layer": "sentence",
        "alignment_score": 0.95,
        "contamination_risk": "low",
        "provenance_normalization_status": "normalized",
        "quote_verification_status": "verified",
        "ancestor_hier_node_ids": list(ancestry["ancestor_hier_node_ids"]),
        "ancestor_labels": list(ancestry["ancestor_labels"]),
        "leaf_hier_node_id": ancestry["leaf_hier_node_id"],
        "parent_hier_node_id": ancestry["parent_hier_node_id"],
        "source_hierarchy_path": list(ancestry["source_hierarchy_path"]),
    }


def _run_source_faithful_normalization(
    *,
    kc_id: str,
    canonical_name: str,
    draft_text: str,
    row_specs: list[tuple[str, str]],
    support_suffixes: list[str],
    topic_path_labels: list[str] | None = None,
) -> dict[str, object]:
    rows = [
        _synthetic_overlay_row(
            kc_id=kc_id,
            canonical_name=canonical_name,
            suffix=suffix,
            text=text,
            topic_path_labels=topic_path_labels,
        )
        for suffix, text in row_specs
    ]
    rows_by_id = {str(row["overlay_candidate_id"]): row for row in rows}
    assessments_by_id = {
        str(row["overlay_candidate_id"]): {"candidate_text": row["source_block_text"]}
        for row in rows
    }
    exemplar = dict(rows[0])
    return _source_faithful_normalized_definition_candidate(
        exemplar=exemplar,
        current_value={},
        draft_response={},
        verify_response={},
        definition_redraft_response={
            "definition": {
                "status": "grounded",
                "text": draft_text,
                "supporting_overlay_candidate_ids": [f"{kc_id}:overlay:{suffix}" for suffix in support_suffixes],
            }
        },
        definition_redraft_verify_response={},
        rows=rows,
        rows_by_id=rows_by_id,
        assessments_by_id=assessments_by_id,
        target_descriptor=_kc_descriptor(exemplar),
        sibling_descriptors=[],
    )


def _synthetic_assess_row(
    *,
    kc_id: str,
    canonical_name: str,
    quote_surface: str,
    source_block_text: str,
    topic_path_labels: list[str] | None = None,
) -> dict[str, object]:
    row = _synthetic_overlay_row(
        kc_id=kc_id,
        canonical_name=canonical_name,
        suffix="assess",
        text=source_block_text,
        topic_path_labels=topic_path_labels,
    )
    row["quote_surface"] = quote_surface
    row["source_block_text"] = source_block_text
    row["quote_verified"] = True
    row["provenance_normalization_status"] = "original"
    row["alignment_breakdown"] = {
        "exact_name_phrase": True,
        "exact_alias_phrase": False,
        "name_or_alias_hit": True,
        "seed_keyword_hits": 4,
    }
    return row


def _synthetic_support_pack_row(
    *,
    kc_id: str,
    canonical_name: str,
    suffix: str,
    text: str,
    topic_path_labels: list[str] | None = None,
    source_kc_id: str | None = None,
) -> dict[str, object]:
    row = _synthetic_overlay_row(
        kc_id=source_kc_id or kc_id,
        canonical_name=canonical_name,
        suffix=suffix,
        text=text,
        topic_path_labels=topic_path_labels,
    )
    row["quote_surface"] = text
    row["source_block_text"] = text
    row["quote_verified"] = True
    row["doc_mismatch"] = False
    row["provenance_normalization_status"] = "original"
    row["quote_verification_status"] = "verified_original"
    row["is_formula_like"] = "=" in text
    row["is_heading_like"] = False
    row["is_procedure_like"] = False
    row["strong_structured_candidate"] = True
    row["strong_same_topic"] = True
    row["alignment_breakdown"] = {
        "exact_name_phrase": canonical_name.lower() in text.lower(),
        "exact_alias_phrase": False,
        "name_or_alias_hit": canonical_name.split()[0].lower() in text.lower(),
        "seed_keyword_hits": 4,
    }
    return row


def _synthetic_definition_candidate(
    *,
    target_kc_id: str,
    source_kc_id: str,
    overlay_suffix: str,
    text: str,
    score: float,
    classification: str,
    positive_surface_type: str,
    issues: list[str] | None = None,
    single_span_accepted: bool = True,
    has_name_anchor: bool = True,
    title_overlap: int = 1,
    seed_overlap: int = 1,
    row_overrides: dict[str, object] | None = None,
    assessment_overrides: dict[str, object] | None = None,
) -> FieldCandidate:
    row_payload = {
        "kc_id": source_kc_id,
        "overlay_candidate_id": f"{target_kc_id}:overlay:{overlay_suffix}",
        "canonical_name": target_kc_id,
        "strong_same_topic": True,
    }
    row_payload.update(row_overrides or {})
    assessment_payload = {
        "classification": classification,
        "positive_surface_type": positive_surface_type,
        "definition_candidate": classification == "definition_support",
        "context_candidate": classification == "context_support",
        "equation_support": classification == "equation_support",
        "scope_signal": False,
        "definition_signal": classification in {"definition_support", "context_support"},
    }
    assessment_payload.update(assessment_overrides or {})
    return FieldCandidate(
        overlay_candidate_id=f"{target_kc_id}:overlay:{overlay_suffix}",
        score=score,
        text=text,
        source_text_field="quote_surface",
        candidate_kind="definition",
        row=row_payload,
        assessment=assessment_payload,
        issues=tuple(issues or []),
        has_name_anchor=has_name_anchor,
        title_overlap=title_overlap,
        seed_overlap=seed_overlap,
        single_span_accepted=single_span_accepted,
    )


def _synthetic_scope_candidate(
    *,
    kc_id: str,
    overlay_suffix: str,
    text: str,
    score: float = 18.0,
) -> FieldCandidate:
    overlay_candidate_id = f"{kc_id}:overlay:{overlay_suffix}"
    return FieldCandidate(
        overlay_candidate_id=overlay_candidate_id,
        score=score,
        text=text,
        source_text_field="quote_surface",
        candidate_kind="scope",
        row={"kc_id": kc_id, "overlay_candidate_id": overlay_candidate_id},
        assessment={
            "classification": "scope_support",
            "scope_signal": True,
            "definition_signal": False,
        },
        issues=(),
        has_name_anchor=True,
        title_overlap=1,
        seed_overlap=1,
        single_span_accepted=True,
    )


def _synthetic_low_trust_bundle() -> dict[str, object]:
    kc_id = "KC_SYN_LOW"
    hierarchy_fields = _synthetic_hierarchy_fields(kc_id=kc_id, canonical_name="Synthetic Low Trust KC")
    return {
        "semantic_contract_version": "step6_7_survival_semantics_v1",
        "draft_status": "draft_ready_with_holds",
        "kc_id": kc_id,
        "canonical_name": "Synthetic Low Trust KC",
        "aliases": [],
        "authoritative_definition_status": AUTHORITATIVE_DEFINITION_STATUS_SEED_FLOOR_FALLBACK,
        **hierarchy_fields,
        "seed_definition": "A synthetic seed definition used only as an explicit fallback floor.",
        "survival_floor": {
            "status": "seed_definition_floor",
            "text": "A synthetic seed definition used only as an explicit fallback floor.",
            "canonical_name": "Synthetic Low Trust KC",
            "source_field": "hierarchy.seed_definition",
            "used_as_definition_fallback": True,
        },
        "enrichment_layer": {
            "status": "missing",
            "text": "",
            "short_text": "",
            "supporting_overlay_candidate_ids": [],
            "source_field": "",
        },
        "context_layer": {
            "status": "fallback_context",
            "snippet_surfaces": ["Synthetic evidence sentence for packetization coverage."],
            "supporting_overlay_candidate_ids": [f"{kc_id}:overlay:01"],
            "source_document_ids": ["doc.synthetic"],
            "family_context_candidate_ids": [],
            "completion_context_candidate_ids": [],
            "selected_bundle_size": 1,
        },
        "scope_layer": {
            "status": "abstained",
            "text": "",
            "supporting_overlay_candidate_ids": [],
            "source_field": "",
        },
        "trust_state": {
            "label": "fallback_seed_floor_with_risks",
            "definition_grounded": False,
            "scope_grounded": False,
            "context_status": "fallback_context",
            "low_trust": True,
        },
        "risk_flags": [
            "seed_definition_floor_active",
            "definition_enrichment_missing",
            "context_fallback_active",
            "low_trust_survivor",
            "review_needs_attention",
            "scope_gap_reviewer_editable",
        ],
        "review_readiness": {
            "label": "low_trust",
            "survives_review_lane": True,
            "needs_attention": True,
            "draft_status_compatibility": "draft_ready_with_holds",
            "reasons": ["seed_definition_floor_active", "context_fallback_active"],
        },
        "definition_full_candidate": {
            "status": "abstained",
            "text": "",
            "supporting_overlay_candidate_ids": [],
            "selection_reason": "definition_full_candidate_abstained",
            "hold_reasons": ["definition_support_insufficient"],
            "source_text_field": "",
        },
        "definition_short_candidate": {
            "status": "abstained",
            "text": "",
            "supporting_overlay_candidate_ids": [],
            "selection_reason": "definition_short_candidate_abstained",
            "hold_reasons": ["definition_short_unavailable"],
            "source_text_field": "",
        },
        "scope_candidate": {
            "status": "abstained",
            "text": "",
            "supporting_overlay_candidate_ids": [],
            "selection_reason": "scope_candidate_abstained",
            "hold_reasons": ["scope_support_insufficient"],
            "source_text_field": "",
        },
        "evidence_bundle": [_synthetic_evidence_item(kc_id=kc_id)],
        "support_summary": {"support_state": "insufficient_support"},
        "contamination_flags": [],
        "hold_reasons": ["definition_support_insufficient", "scope_support_insufficient"],
        "field_hold_reasons": {
            "definition_full_candidate": ["definition_support_insufficient"],
            "scope_candidate": ["scope_support_insufficient"],
        },
        "field_provenance_map": {
            "definition_full_candidate": {
                "status": "abstained",
                "overlay_candidate_ids": [],
                "source_set_ids": ["step6_6_set"],
                "source_run_ids": ["step6_7_run"],
            },
            "definition_short_candidate": {
                "status": "abstained",
                "overlay_candidate_ids": [],
                "source_set_ids": ["step6_6_set"],
                "source_run_ids": ["step6_7_run"],
            },
            "scope_candidate": {
                "status": "abstained",
                "overlay_candidate_ids": [],
                "source_set_ids": ["step6_6_set"],
                "source_run_ids": ["step6_7_run"],
            },
            "evidence_bundle": {
                "status": "fallback_context",
                "overlay_candidate_ids": [f"{kc_id}:overlay:01"],
                "source_set_ids": ["step6_6_set"],
                "source_run_ids": ["step6_7_run"],
            },
        },
    }


def _synthetic_grounded_bundle() -> dict[str, object]:
    kc_id = "KC_SYN_HIGH"
    hierarchy_fields = _synthetic_hierarchy_fields(kc_id=kc_id, canonical_name="Synthetic Grounded KC")
    return {
        "semantic_contract_version": "step6_7_survival_semantics_v1",
        "draft_status": "draft_ready",
        "kc_id": kc_id,
        "canonical_name": "Synthetic Grounded KC",
        "aliases": [],
        "authoritative_definition_status": AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED,
        **hierarchy_fields,
        "seed_definition": "Seed definition.",
        "survival_floor": {
            "status": "seed_definition_floor",
            "text": "Seed definition.",
            "canonical_name": "Synthetic Grounded KC",
            "source_field": "hierarchy.seed_definition",
            "used_as_definition_fallback": False,
        },
        "enrichment_layer": {
            "status": "grounded",
            "text": "A grounded synthetic definition supported by corpus evidence.",
            "short_text": "A grounded synthetic definition.",
            "supporting_overlay_candidate_ids": [f"{kc_id}:overlay:01"],
            "source_field": "definition_full_candidate",
        },
        "context_layer": {
            "status": "grounded",
            "snippet_surfaces": ["Synthetic evidence sentence for packetization coverage."],
            "supporting_overlay_candidate_ids": [f"{kc_id}:overlay:01"],
            "source_document_ids": ["doc.synthetic"],
            "family_context_candidate_ids": [],
            "completion_context_candidate_ids": [],
            "selected_bundle_size": 1,
        },
        "scope_layer": {
            "status": "grounded",
            "text": "Applies when reviewing grounded synthetic examples.",
            "supporting_overlay_candidate_ids": [f"{kc_id}:overlay:01"],
            "source_field": "scope_candidate",
        },
        "trust_state": {
            "label": "grounded",
            "definition_grounded": True,
            "scope_grounded": True,
            "context_status": "grounded",
            "low_trust": False,
        },
        "risk_flags": [],
        "review_readiness": {
            "label": "ready",
            "survives_review_lane": True,
            "needs_attention": False,
            "draft_status_compatibility": "draft_ready",
            "reasons": [],
        },
        "definition_full_candidate": {
            "status": "grounded",
            "text": "A grounded synthetic definition supported by corpus evidence.",
            "supporting_overlay_candidate_ids": [f"{kc_id}:overlay:01"],
            "selection_reason": "synthetic",
            "hold_reasons": [],
            "source_text_field": "quote_surface",
        },
        "definition_short_candidate": {
            "status": "grounded",
            "text": "A grounded synthetic definition.",
            "supporting_overlay_candidate_ids": [f"{kc_id}:overlay:01"],
            "selection_reason": "synthetic_short",
            "hold_reasons": [],
            "source_text_field": "quote_surface",
        },
        "scope_candidate": {
            "status": "grounded",
            "text": "Applies when reviewing grounded synthetic examples.",
            "supporting_overlay_candidate_ids": [f"{kc_id}:overlay:01"],
            "selection_reason": "synthetic_scope",
            "hold_reasons": [],
            "source_text_field": "quote_surface",
        },
        "evidence_bundle": [_synthetic_evidence_item(kc_id=kc_id)],
        "support_summary": {"support_state": "strict_leaf_support"},
        "contamination_flags": [],
        "hold_reasons": [],
        "field_hold_reasons": {},
        "field_provenance_map": {
            "definition_full_candidate": {
                "status": "grounded",
                "overlay_candidate_ids": [f"{kc_id}:overlay:01"],
                "source_set_ids": ["step6_6_set"],
                "source_run_ids": ["step6_7_run"],
            },
            "definition_short_candidate": {
                "status": "grounded",
                "overlay_candidate_ids": [f"{kc_id}:overlay:01"],
                "source_set_ids": ["step6_6_set"],
                "source_run_ids": ["step6_7_run"],
            },
            "scope_candidate": {
                "status": "grounded",
                "overlay_candidate_ids": [f"{kc_id}:overlay:01"],
                "source_set_ids": ["step6_6_set"],
                "source_run_ids": ["step6_7_run"],
            },
            "evidence_bundle": {
                "status": "grounded",
                "overlay_candidate_ids": [f"{kc_id}:overlay:01"],
                "source_set_ids": ["step6_6_set"],
                "source_run_ids": ["step6_7_run"],
            },
        },
    }


def test_bayes_theorem_formula_faithful_normalization():
    normalized = _run_source_faithful_normalization(
        kc_id="KC_CLF_NB_001",
        canonical_name="Bayes' Theorem",
        draft_text="The posterior probability of a class H given evidence E is P(H|E) = P(E|H) * P(H) / P(E).",
        row_specs=[
            ("title", "Bayes' Theorem"),
            ("formula", "Bayes' Theorem: P(H|E) = P(E|H) * P(H) / P(E)."),
        ],
        support_suffixes=["formula"],
        topic_path_labels=["Data Mining", "Classification", "Naive Bayes"],
    )

    assert normalized["status"] == "grounded"
    assert normalized["text"] == "Bayes' Theorem states that P(H|E) = P(E|H) * P(H) / P(E)."
    assert normalized["selection_reason"] == "definition_full_candidate_source_faithful_formula_normalization"


def test_silhouette_coefficient_formula_faithful_normalization():
    normalized = _run_source_faithful_normalization(
        kc_id="KC_CLU_EVAL_005",
        canonical_name="Silhouette Coefficient",
        draft_text="For an object, the silhouette coefficient is s_i = (b_i - a_i) / max(a_i, b_i), where a_i is the average intra-cluster distance and b_i is the minimum average distance to any other cluster.",
        row_specs=[
            ("title", "Silhouette Coefficient"),
            ("formula", "The silhouette coefficient for an object is s_i = (b_i - a_i) / max(a_i, b_i)."),
        ],
        support_suffixes=["formula"],
        topic_path_labels=["Data Mining", "Clustering", "Evaluation"],
    )

    assert normalized["status"] == "grounded"
    assert normalized["text"].startswith("The silhouette coefficient for an object is s_i =")
    assert normalized["selection_reason"] == "definition_full_candidate_source_faithful_context_normalization"


def test_binary_decision_tree_trimmed_source_faithful_normalization():
    normalized = _run_source_faithful_normalization(
        kc_id="KC_CLF_DT_011",
        canonical_name="Binary Decision Tree",
        draft_text="A binary decision tree is a classification structure where every internal node performs a split on a single attribute-value pair, resulting in exactly two child nodes.",
        row_specs=[
            ("title", "Binary decision tree"),
            ("binary", "A binary decision tree uses only binary splits."),
        ],
        support_suffixes=["binary"],
        topic_path_labels=["Data Mining", "Classification", "Decision Trees"],
    )

    assert normalized["status"] == "grounded"
    assert normalized["text"] == "A binary decision tree uses only binary splits."
    assert normalized["selection_reason"] == "definition_full_candidate_source_faithful_trimmed_normalization"


def test_local_row_normalization_survives_safe_quote_when_source_block_continues():
    kc_id = "KC_EVAL_ENS_004"
    quote_surface = (
        "Boosting is an iterative procedure used to adaptively change the distribution of training examples "
        "for learning base classifiers so that they increasingly focus on examples that are hard to classify."
    )
    source_block_text = (
        f"{quote_surface} Unlike bagging, boosting assigns a weight to each training example and may adaptively "
        "change the weight at the end of each boosting round. The weights assigned to the training examples can "
        "be used in the following ways:"
    )
    row = _synthetic_overlay_row(
        kc_id=kc_id,
        canonical_name="Boosting",
        suffix="01",
        text=source_block_text,
        topic_path_labels=["Data Mining", "Model Evaluation", "Ensemble Methods"],
    )
    row["quote_surface"] = quote_surface

    rows = [row]
    rows_by_id = {str(row["overlay_candidate_id"]): row}
    assessments_by_id = {
        str(row["overlay_candidate_id"]): {
            "candidate_text": source_block_text,
        }
    }

    normalized = _source_faithful_normalized_definition_candidate(
        exemplar=dict(row),
        current_value={},
        draft_response={},
        verify_response={},
        definition_redraft_response={
            "definition": {
                "status": "grounded",
                "text": "A sequential ensemble method that adaptively adjusts sample weights to focus subsequent classifiers on misclassified instances.",
                "supporting_overlay_candidate_ids": [str(row["overlay_candidate_id"])],
            }
        },
        definition_redraft_verify_response={},
        rows=rows,
        rows_by_id=rows_by_id,
        assessments_by_id=assessments_by_id,
        target_descriptor=_kc_descriptor(row),
        sibling_descriptors=[],
    )

    assert normalized["status"] == "grounded"
    assert normalized["text"] == quote_surface
    assert normalized["selection_reason"] == "definition_full_candidate_source_faithful_local_row_normalization"
    assert normalized["source_text_field"] == "source_faithful_normalization"


def test_local_quote_normalization_recovers_relation_led_definition_sentence():
    normalized = _run_source_faithful_normalization(
        kc_id="KC_EVAL_SAMP_001",
        canonical_name="Holdout Method",
        draft_text="A single random partition of a dataset into training and test sets for model evaluation.",
        row_specs=[
            (
                "holdout",
                "The most basic technique for partitioning a labeled data set is the holdout method, where the "
                "labeled set D is randomly partitioned into two disjoint sets, called the training set D.train "
                "and the test set D.test.",
            )
        ],
        support_suffixes=["holdout"],
        topic_path_labels=["Data Mining", "Model Evaluation", "Sampling"],
    )

    assert normalized["status"] == "grounded"
    assert normalized["text"].startswith("The most basic technique for partitioning a labeled data set is the holdout method")
    assert normalized["selection_reason"] == "definition_full_candidate_source_faithful_local_quote_normalization"


def test_local_quote_normalization_recovers_parenthetical_name_variant():
    normalized = _run_source_faithful_normalization(
        kc_id="KC_FSEL_STAT_001",
        canonical_name="Null Hypothesis (H0)",
        draft_text="A statement assumed true until evidence suggests otherwise, typically asserting no effect or relationship.",
        row_specs=[
            (
                "null",
                "The null hypothesis is assumed to be true until there is sufficient evidence to indicate otherwise.",
            )
        ],
        support_suffixes=["null"],
        topic_path_labels=["Data Mining", "Data Engineering", "Feature Selection"],
    )

    assert normalized["status"] == "grounded"
    assert normalized["text"] == "The null hypothesis is assumed to be true until there is sufficient evidence to indicate otherwise."
    assert normalized["selection_reason"] == "definition_full_candidate_source_faithful_local_quote_normalization"


def test_local_quote_normalization_recovers_overview_called_name_variant():
    normalized = _run_source_faithful_normalization(
        kc_id="KC_CLU_EVAL_001",
        canonical_name="Internal Indices Overview",
        draft_text="Evaluation measures that assess cluster quality using only information present in the data set.",
        row_specs=[
            (
                "internal",
                "Unsupervised measures are often called internal indices because they use only information present in the data set.",
            )
        ],
        support_suffixes=["internal"],
        topic_path_labels=["Data Mining", "Clustering", "Cluster Evaluation"],
    )

    assert normalized["status"] == "grounded"
    assert normalized["text"] == "Unsupervised measures are often called internal indices because they use only information present in the data set."
    assert normalized["selection_reason"] == "definition_full_candidate_source_faithful_local_quote_normalization"


def test_local_quote_normalization_recovers_prefixed_definition_row():
    normalized = _run_source_faithful_normalization(
        kc_id="KC_CLF_NB_003",
        canonical_name="Conditional Probability (Likelihood)",
        draft_text="The probability of observing a specific attribute value given a class label, estimated from training data counts.",
        row_specs=[
            (
                "conditional",
                "For a categorical attribute, the conditional probability is estimated according to the fraction of "
                "training instances in class y where it takes on a particular categorical value c.",
            )
        ],
        support_suffixes=["conditional"],
        topic_path_labels=["Data Mining", "Classification", "Naive Bayes"],
    )

    assert normalized["status"] == "grounded"
    assert normalized["text"].startswith("For a categorical attribute, the conditional probability is estimated")
    assert normalized["selection_reason"] == "definition_full_candidate_source_faithful_local_quote_normalization"


def test_local_quote_normalization_rejects_example_specific_context():
    normalized = _run_source_faithful_normalization(
        kc_id="KC_CLF_DT_006",
        canonical_name="Information Gain",
        draft_text="A measure of expected reduction in entropy after splitting on an attribute.",
        row_specs=[
            (
                "gain",
                "The information gain for Marital Status is thus higher due to its lower weighted entropy, which "
                "will thus be considered for splitting.",
            )
        ],
        support_suffixes=["gain"],
        topic_path_labels=["Data Mining", "Classification", "Decision Trees"],
    )

    assert normalized == {}


def test_local_support_unit_normalization_recovers_parenthetical_name_variant_title_row():
    normalized = _run_source_faithful_normalization(
        kc_id="KC_CLF_DT_005",
        canonical_name="Entropy (Node)",
        draft_text="Entropy is the degree to which a node consists of objects from a single class.",
        row_specs=[
            (
                "entropy",
                "Entropy: The degree to which each cluster consists of objects of a single class.",
            )
        ],
        support_suffixes=["entropy"],
        topic_path_labels=["Data Mining", "Classification", "Decision Trees"],
    )

    assert normalized["status"] == "grounded"
    assert normalized["text"] == "Entropy is the degree to which each cluster consists of objects of a single class."
    assert normalized["selection_reason"] == "definition_full_candidate_source_faithful_local_support_unit_normalization"


def test_local_support_unit_normalization_can_recover_second_sentence_support_unit():
    normalized = _run_source_faithful_normalization(
        kc_id="KC_CLF_NB_002",
        canonical_name="Prior Probability",
        draft_text="Prior probability captures prior beliefs about the distribution of class labels.",
        row_specs=[
            (
                "prior",
                "The second term in the numerator of Equation 4.14 is the prior probability P(y). "
                "The prior probability captures our prior beliefs about the distribution of class labels.",
            )
        ],
        support_suffixes=["prior"],
        topic_path_labels=["Data Mining", "Classification", "Naive Bayes"],
    )

    assert normalized["status"] == "grounded"
    assert normalized["text"] == "The prior probability captures our prior beliefs about the distribution of class labels."
    assert normalized["selection_reason"] == "definition_full_candidate_source_faithful_local_support_unit_normalization"


def test_local_two_span_normalization_composes_exactly_two_same_kc_support_units():
    kc_id = "KC_CLF_DT_003"
    canonical_name = "Misclassification Rate"
    rows = [
        _synthetic_overlay_row(
            kc_id=kc_id,
            canonical_name=canonical_name,
            suffix="01",
            text="Misclassification rate is",
            topic_path_labels=["Data Mining", "Classification", "Decision Trees"],
        ),
        _synthetic_overlay_row(
            kc_id=kc_id,
            canonical_name=canonical_name,
            suffix="02",
            text="the probability of misclassifying a randomly chosen instance.",
            topic_path_labels=["Data Mining", "Classification", "Decision Trees"],
        ),
        _synthetic_overlay_row(
            kc_id=kc_id,
            canonical_name=canonical_name,
            suffix="03",
            text="when used to compare alternative split conditions.",
            topic_path_labels=["Data Mining", "Classification", "Decision Trees"],
        ),
    ]
    rows[0]["block_id"] = "doc.synthetic:1"
    rows[1]["block_id"] = "doc.synthetic:2"
    rows[2]["block_id"] = "doc.synthetic:3"
    rows_by_id = {str(row["overlay_candidate_id"]): row for row in rows}
    assessments_by_id = {
        str(row["overlay_candidate_id"]): {
            "candidate_text": row["source_block_text"],
            "definition_candidate": True,
            "question_like": False,
            "bare_heading": False,
            "background_drift_block": False,
            "concept_mix_block": False,
            "contamination_block": False,
        }
        for row in rows
    }

    normalized = _source_faithful_normalized_definition_candidate(
        exemplar=dict(rows[0]),
        current_value={},
        draft_response={},
        verify_response={},
        definition_redraft_response={
            "definition": {
                "status": "grounded",
                "text": "The misclassification rate measures the proportion of instances incorrectly classified.",
                "supporting_overlay_candidate_ids": [
                    str(rows[0]["overlay_candidate_id"]),
                    str(rows[1]["overlay_candidate_id"]),
                    str(rows[2]["overlay_candidate_id"]),
                ],
            }
        },
        definition_redraft_verify_response={},
        rows=rows,
        rows_by_id=rows_by_id,
        assessments_by_id=assessments_by_id,
        target_descriptor=_kc_descriptor(rows[0]),
        sibling_descriptors=[],
    )

    assert normalized["status"] == "grounded"
    assert normalized["text"] == "Misclassification rate is the probability of misclassifying a randomly chosen instance."
    assert normalized["selection_reason"] == "definition_full_candidate_source_faithful_two_span_local_normalization"
    assert normalized["supporting_overlay_candidate_ids"] == [
        str(rows[0]["overlay_candidate_id"]),
        str(rows[1]["overlay_candidate_id"]),
    ]


def test_assess_overlay_candidate_extracts_clean_quote_surface_from_overlong_block():
    row = _synthetic_assess_row(
        kc_id="KC_EVAL_BASIC_001",
        canonical_name="Confusion Matrix",
        quote_surface="This information can be summarized in a table called a confusion matrix.",
        source_block_text=(
            "In the general framework shown in Figure 3.3, the induction and deduction steps should be performed "
            "separately. The performance of a model can be evaluated by comparing the predicted labels against "
            "the true labels of instances. This information can be summarized in a table called a confusion "
            "matrix. Table 3.4 depicts the confusion matrix for a binary classification problem."
        ),
        topic_path_labels=["Data Mining", "Model Evaluation", "Classifier Evaluation Basics"],
    )

    assessment = assess_overlay_candidate(row)

    assert assessment["target_segment_extracted"] is True
    assert assessment["target_segment_kind"] == "anchored_same_kc_quote_sentence"
    assert assessment["candidate_text"] == "This information can be summarized in a table called a confusion matrix."


def test_assess_overlay_candidate_extracts_heading_tail_sentence_for_algorithm_block():
    row = _synthetic_assess_row(
        kc_id="KC_FSEL_GEN_001",
        canonical_name="Sequential Forward Generation (SFG)",
        quote_surface="Sequential Forward Generation (SFG):",
        source_block_text=(
            "Sequential Forward Generation (SFG): It starts with an empty set of features S. As the search starts, "
            "features are added into S according to some criterion that distinguishes the best feature from the others."
        ),
        topic_path_labels=["Data Mining", "Feature Selection", "Generation"],
    )

    assessment = assess_overlay_candidate(row)

    assert assessment["target_segment_extracted"] is True
    assert assessment["target_segment_kind"] == "anchored_same_kc_source_block_tail_heading_continuation"
    assert assessment["candidate_text"] == "Sequential Forward Generation (SFG) starts with an empty set of features S."


def test_assess_overlay_candidate_keeps_contextual_random_forest_hyperparameter_sentence():
    text = "The number of attributes selected at every node is a hyper-parameter of the random forest classifier."
    row = _synthetic_assess_row(
        kc_id="KC_EVAL_ENS_003",
        canonical_name="Random Forest",
        quote_surface=text,
        source_block_text=text,
        topic_path_labels=["Data Mining", "Model Evaluation", "Ensemble Methods"],
    )

    assessment = assess_overlay_candidate(row)

    assert assessment["target_segment_extracted"] is False
    assert assessment["candidate_text"] == text


def test_step67_bundle_emits_typed_hierarchy_fields():
    bundles, _ = build_kc_draft_bundles(
        [
            _synthetic_overlay_row(
                kc_id="KC_SYN_HIER",
                canonical_name="Synthetic Hierarchy KC",
                suffix="01",
                text="Synthetic Hierarchy KC is a grounded synthetic concept.",
                topic_path_labels=["Synthetic Domain", "Synthetic Branch"],
            )
        ]
    )

    bundle = bundles[0]

    assert bundle["topic_path_labels"] == ["Synthetic Domain", "Synthetic Branch"]
    assert len(bundle["topic_path_ids"]) == 2
    assert bundle["parent_topic_label"] == "Synthetic Branch"
    assert bundle["ancestor_topic_labels"] == ["Synthetic Domain", "Synthetic Branch"]
    assert bundle["hierarchy_ancestry"]["source_hierarchy_path"] == [
        "Synthetic Domain",
        "Synthetic Branch",
        "Synthetic Hierarchy KC",
    ]
    assert bundle["authoritative_definition_status"] in {
        AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED,
        AUTHORITATIVE_DEFINITION_STATUS_SEED_FLOOR_FALLBACK,
    }


def test_restarted_review_packet_survives_explicit_low_trust_bundle():
    packet = build_restarted_review_packet(
        draft_bundle=_synthetic_low_trust_bundle(),
        step4_set_id="step4_set",
        step4_5_set_id="step4_5_set",
        step5_set_id="step5_set",
        step6_6_set_id="step6_6_set",
        step6_7_set_id="step6_7_set",
        step6_7b_set_id="",
        step6_8_run_id="2026-04-11_semantics_test",
    )

    assert packet["definition_draft"] == "A synthetic seed definition used only as an explicit fallback floor."
    assert packet["draft_status"] == "draft_ready_with_holds"
    assert packet["authoritative_definition_status"] == AUTHORITATIVE_DEFINITION_STATUS_SEED_FLOOR_FALLBACK
    assert packet["topic_path_labels"] == ["Synthetic Domain", "Synthetic Branch"]
    assert packet["parent_topic_label"] == "Synthetic Branch"
    assert "low_trust_review" in packet["risk_flags"]
    assert packet["kc_specific_criteria"] == ""
    validate_restarted_review_packet(packet)


def test_restarted_review_packet_emits_hierarchy_fields_and_authoritative_status():
    packet = build_restarted_review_packet(
        draft_bundle=_synthetic_grounded_bundle(),
        step4_set_id="step4_set",
        step4_5_set_id="step4_5_set",
        step5_set_id="step5_set",
        step6_6_set_id="step6_6_set",
        step6_7_set_id="step6_7_set",
        step6_7b_set_id="",
        step6_8_run_id="2026-04-11_hierarchy_test",
    )

    assert packet["authoritative_definition_status"] == AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED
    assert packet["topic_path_labels"] == ["Synthetic Domain", "Synthetic Branch"]
    assert len(packet["topic_path_ids"]) == 2
    assert packet["parent_topic_label"] == "Synthetic Branch"
    assert packet["ancestor_topic_labels"] == ["Synthetic Domain", "Synthetic Branch"]
    assert packet["hierarchy_ancestry"]["source_hierarchy_path"] == [
        "Synthetic Domain",
        "Synthetic Branch",
        "Synthetic Grounded KC",
    ]
    validate_restarted_review_packet(packet)


def test_emit_restarted_review_packets_keeps_one_packet_per_bundle(monkeypatch):
    captured: dict[str, object] = {}

    def fake_write_json(path: Path, obj):
        captured[str(path)] = obj

    def fake_write_jsonl(path: Path, rows):
        captured[str(path)] = list(rows)

    def fake_write_text(self, text, encoding="utf-8"):
        captured[str(self)] = text
        return len(text)

    monkeypatch.setattr(packetization_module, "write_json", fake_write_json)
    monkeypatch.setattr(packetization_module, "write_jsonl", fake_write_jsonl)
    monkeypatch.setattr(Path, "write_text", fake_write_text)

    output_dir = REPO_ROOT / "data" / "work" / "cache"
    result = emit_restarted_review_packets_from_draft_bundles(
        source_processed_dir=REPO_ROOT / "data" / "work" / "cache",
        output_dir=output_dir,
        draft_rows=[_synthetic_grounded_bundle(), _synthetic_low_trust_bundle()],
        step4_set_id="step4_set",
        step4_5_set_id="step4_5_set",
        step5_set_id="step5_set",
        step6_6_set_id="step6_6_set",
        step6_7_set_id="step6_7_set",
        step6_7b_set_id="",
        step6_8_run_id="2026-04-11_semantics_test",
        step6_7_drafting_runtime={"execution_mode": "llm", "llm_path_invoked": True, "llm_calls": 2},
    )

    summary = captured[str(result.summary_path)]

    assert result.packet_count == 2
    assert result.excluded_candidate_count == 0
    assert summary["packet_count"] == 2
    assert summary["excluded_kcs"] == []
    assert summary["quarantined_kcs"] == []
    assert summary["low_trust_packet_count"] == 1
    assert summary["fallback_definition_count"] == 1
    assert summary["normalized_grounded_definition_count"] == 0
    assert summary["authoritative_definition_status_counts"] == {
        AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED: 1,
        AUTHORITATIVE_DEFINITION_STATUS_SEED_FLOOR_FALLBACK: 1,
    }


def test_rerank_definition_candidates_promotes_local_concise_definition_over_foreign_candidate():
    target_descriptor = _kc_descriptor(
        {
            "kc_id": "KC_SYN_FILTER",
            "canonical_name": "Filter Approach",
            "aliases": [],
            "seed_definition": "A feature-selection approach that operates independently of the downstream learner.",
            "parent_hier_node_id": "topic::feature_selection",
        }
    )
    candidates = [
        _synthetic_definition_candidate(
            target_kc_id="KC_SYN_FILTER",
            source_kc_id="KC_FOREIGN_TREE",
            overlay_suffix="foreign",
            text="A decision tree is a flow-chart-like structure used for classification.",
            score=42.0,
            classification="definition_support",
            positive_surface_type="prose_definition",
        ),
        _synthetic_definition_candidate(
            target_kc_id="KC_SYN_FILTER",
            source_kc_id="KC_SYN_FILTER",
            overlay_suffix="local",
            text="The filter approach operates independently of the learning method subsequently employed.",
            score=34.0,
            classification="definition_support",
            positive_surface_type="prose_definition",
        ),
    ]

    reranked = _rerank_definition_candidates(candidates, target_descriptor=target_descriptor)

    assert reranked[0].overlay_candidate_id == "KC_SYN_FILTER:overlay:local"


def test_rerank_definition_candidates_promotes_local_relation_led_definition_over_overlong_context():
    target_descriptor = _kc_descriptor(
        {
            "kc_id": "KC_SYN_SFG",
            "canonical_name": "Sequential Forward Generation",
            "aliases": ["SFG"],
            "seed_definition": "A wrapper search method that starts from an empty feature set.",
            "parent_hier_node_id": "topic::feature_selection",
        }
    )
    candidates = [
        _synthetic_definition_candidate(
            target_kc_id="KC_SYN_SFG",
            source_kc_id="KC_SYN_SFG",
            overlay_suffix="overlong",
            text=(
                "Sequential Forward Generation is discussed alongside other search strategies, and in this extended "
                "discussion the text walks through several examples, comparisons, and implementation details before "
                "eventually returning to the idea of iteratively constructing the selected feature subset."
            ),
            score=38.0,
            classification="context_support",
            positive_surface_type="prose_definition",
            issues=["overlong_surface"],
            has_name_anchor=True,
        ),
        _synthetic_definition_candidate(
            target_kc_id="KC_SYN_SFG",
            source_kc_id="KC_SYN_SFG",
            overlay_suffix="concise",
            text="Sequential Forward Generation (SFG) starts with an empty set of features.",
            score=31.0,
            classification="definition_support",
            positive_surface_type="prose_definition",
            has_name_anchor=True,
            title_overlap=2,
        ),
    ]

    reranked = _rerank_definition_candidates(candidates, target_descriptor=target_descriptor)

    assert reranked[0].overlay_candidate_id == "KC_SYN_SFG:overlay:concise"


def test_rerank_definition_candidates_does_not_blindly_promote_local_fragment():
    target_descriptor = _kc_descriptor(
        {
            "kc_id": "KC_SYN_SPEC",
            "canonical_name": "Specificity",
            "aliases": [],
            "seed_definition": "The fraction of negative instances correctly classified as negative.",
            "parent_hier_node_id": "topic::evaluation",
        }
    )
    candidates = [
        _synthetic_definition_candidate(
            target_kc_id="KC_SYN_SPEC",
            source_kc_id="KC_FOREIGN_RECALL",
            overlay_suffix="foreign_clean",
            text="Recall is the fraction of positive instances correctly classified as positive.",
            score=32.0,
            classification="definition_support",
            positive_surface_type="prose_definition",
        ),
        _synthetic_definition_candidate(
            target_kc_id="KC_SYN_SPEC",
            source_kc_id="KC_SYN_SPEC",
            overlay_suffix="local_fragment",
            text="specificity is defined as the fraction of negative test instances correctly",
            score=30.0,
            classification="context_support",
            positive_surface_type="prose_definition",
            issues=["fragment_lead_in"],
            has_name_anchor=False,
            title_overlap=0,
            seed_overlap=1,
        ),
    ]

    reranked = _rerank_definition_candidates(candidates, target_descriptor=target_descriptor)

    assert reranked[0].overlay_candidate_id == "KC_SYN_SPEC:overlay:foreign_clean"


def test_select_definition_support_pack_extracts_clean_same_kc_support_unit_and_stays_bounded():
    kc_id = "KC_CLF_NB_002"
    canonical_name = "Prior Probability"
    rows = [
        _synthetic_support_pack_row(
            kc_id=kc_id,
            canonical_name=canonical_name,
            suffix="01",
            text="In the following, we discuss prior probability and its role in classification.",
            topic_path_labels=["Data Mining", "Classification", "Naive Bayes"],
        ),
        _synthetic_support_pack_row(
            kc_id=kc_id,
            canonical_name=canonical_name,
            suffix="02",
            text=(
                "The second term in the numerator of Equation 4.14 is the prior probability P(y). "
                "The prior probability captures our prior beliefs about the distribution of class labels."
            ),
            topic_path_labels=["Data Mining", "Classification", "Naive Bayes"],
        ),
        _synthetic_support_pack_row(
            kc_id=kc_id,
            canonical_name=canonical_name,
            suffix="03",
            text="P(y)=count(y)/N, where count(y) is the number of training instances with class y.",
            topic_path_labels=["Data Mining", "Classification", "Naive Bayes"],
        ),
        _synthetic_support_pack_row(
            kc_id=kc_id,
            canonical_name=canonical_name,
            suffix="04",
            text="Prior Probability is a distribution over class labels before observing attribute values.",
            topic_path_labels=["Data Mining", "Classification", "Naive Bayes"],
            source_kc_id="KC_CLF_NB_999",
        ),
    ]
    rows[0]["block_id"] = "doc.synthetic:100"
    rows[1]["block_id"] = "doc.synthetic:101"
    rows[2]["block_id"] = "doc.synthetic:102"
    rows[3]["block_id"] = "doc.synthetic:103"

    rows_by_id = {str(row["overlay_candidate_id"]): row for row in rows}
    assessments_by_id = {
        str(row["overlay_candidate_id"]): assess_overlay_candidate(row)
        for row in rows
    }

    pack = select_definition_support_pack(
        rows_by_id,
        assessments_by_id,
        target_kc_id=kc_id,
        max_pack_size=3,
    )

    assert len(pack) <= 3
    assert [str(item["overlay_candidate_id"]) for item in pack] == [
        f"{kc_id}:overlay:02",
        f"{kc_id}:overlay:03",
    ]
    assert pack[0]["candidate_text"] == "The prior probability captures our prior beliefs about the distribution of class labels."
    assert all(str(item["overlay_candidate_id"]).startswith(f"{kc_id}:") for item in pack)


def test_build_definition_evidence_packet_enforces_role_anchor_rules():
    kc_id = "KC_CLF_NB_002"
    canonical_name = "Prior Probability"
    formula_row = _synthetic_support_pack_row(
        kc_id=kc_id,
        canonical_name=canonical_name,
        suffix="formula",
        text="P(y)=count(y)/N.",
    )
    example_row = _synthetic_support_pack_row(
        kc_id=kc_id,
        canonical_name=canonical_name,
        suffix="example",
        text="For example, a classifier may estimate prior probability from the training labels.",
    )
    example_row["is_example_like"] = True
    gloss_row = _synthetic_support_pack_row(
        kc_id=kc_id,
        canonical_name=canonical_name,
        suffix="gloss",
        text="Prior Probability is a distribution over class labels before attribute values are observed.",
    )
    sibling_row = _synthetic_support_pack_row(
        kc_id=kc_id,
        canonical_name="Posterior Probability",
        suffix="sibling",
        text="Posterior Probability is the updated probability of a class after observing attributes.",
        source_kc_id="KC_CLF_NB_999",
    )
    rows = [formula_row, example_row, gloss_row, sibling_row]
    rows_by_id = {str(row["overlay_candidate_id"]): row for row in rows}
    assessments_by_id = {
        str(row["overlay_candidate_id"]): assess_overlay_candidate(row)
        for row in rows
    }

    packet = build_definition_evidence_packet(
        rows_by_id,
        assessments_by_id,
        target_kc_id=kc_id,
    )

    assert packet["definitional_anchor_present"] is True
    assert packet["roles"]["definition_gloss"][0]["overlay_candidate_id"] == f"{kc_id}:overlay:gloss"
    assert packet["roles"]["definition_gloss"][0]["anchor_eligible"] is True
    assert packet["roles"]["formula_or_notation"][0]["anchor_eligible"] is False
    assert packet["roles"]["formula_or_notation"][0]["anchor_blocked_reason"] == (
        "formula_or_notation_without_definitional_gloss"
    )
    assert packet["roles"]["example_or_context"][0]["anchor_eligible"] is False
    assert packet["roles"]["contrastive_sibling"][0]["disambiguation_only"] is True


def test_build_kc_draft_bundles_llm_packet_multicandidate_selects_faithful_candidate_without_llm():
    kc_id = "KC_CLF_NB_002"
    canonical_name = "Prior Probability"
    rows = [
        _synthetic_support_pack_row(
            kc_id=kc_id,
            canonical_name=canonical_name,
            suffix="gloss",
            text="Prior Probability is a distribution over class labels before attribute values are observed.",
        ),
        _synthetic_support_pack_row(
            kc_id=kc_id,
            canonical_name=canonical_name,
            suffix="formula",
            text="Prior probability P(y)=count(y)/N.",
        ),
    ]
    calls: list[dict[str, object]] = []

    def fail_if_called(payload: dict[str, object]) -> dict[str, object]:
        calls.append(payload)
        raise AssertionError("packet_multicandidate_v1 should not call the one-shot LLM path")

    bundles, stats = build_kc_draft_bundles_llm(
        rows,
        runtime=Step67ModelRuntime(
            base_url="",
            model="test",
            draft_invoker=fail_if_called,
            verify_invoker=fail_if_called,
        ),
        policy=Step67DraftingPolicy(
            definition_generation_mode="packet_multicandidate_v1",
            max_llm_calls_per_kc=2,
        ),
    )

    bundle = bundles[0]
    assert calls == []
    assert stats["definition_packet_family_recoveries"] == 1
    assert bundle["definition_full_candidate"]["selection_reason"] in {
        "definition_full_candidate_packet_family_faithful_extractive",
        "definition_full_candidate_packet_family_formula_plus_gloss",
    }
    field_sets = bundle["selection_diagnostics"]["field_candidate_sets"]
    assert field_sets["definition_generation_mode"] == "packet_multicandidate_v1"
    assert field_sets["definition_evidence_packet"]["definitional_anchor_present"] is True
    assert field_sets["definition_candidate_family_selected"]["text"].startswith(
        "Prior Probability is a distribution over class labels"
    )
    assert "accepted_packet_multicandidate_definition" in bundle["selection_diagnostics"]["field_protection_actions"]


def test_selected_definition_review_quality_flags_formula_only_without_gloss():
    kc_id = "KC_CLF_NB_002"
    row = _synthetic_support_pack_row(
        kc_id=kc_id,
        canonical_name="Prior Probability",
        suffix="formula",
        text="P(y)=count(y)/N.",
    )
    rows_by_id = {str(row["overlay_candidate_id"]): row}
    assessments_by_id = {
        str(row["overlay_candidate_id"]): assess_overlay_candidate(row)
    }

    quality = selected_definition_review_quality(
        {
            "status": "grounded",
            "text": "P(y)=count(y)/N.",
            "supporting_overlay_candidate_ids": [str(row["overlay_candidate_id"])],
            "source_text_field": "quote_surface",
        },
        rows_by_id,
        assessments_by_id,
    )

    assert quality["suppressed"] is True
    assert "formula_only_anchor" in quality["surface_families"]
    assert "selected_definition_formula_only_anchor" in quality["risk_flags"]

    good_quality = selected_definition_review_quality(
        {
            "status": "grounded",
            "text": "Prior Probability is a distribution over class labels before attribute values are observed.",
            "supporting_overlay_candidate_ids": [str(row["overlay_candidate_id"])],
            "source_text_field": "quote_surface",
        },
        rows_by_id,
        assessments_by_id,
    )

    assert good_quality["suppressed"] is False


def test_selected_definition_review_quality_flags_context_and_procedure_surfaces():
    kc_id = "KC_SYN_PROC"
    row = _synthetic_support_pack_row(
        kc_id=kc_id,
        canonical_name="Synthetic Procedure",
        suffix="proc",
        text="One simple way is to exclude instances with missing values before training.",
    )
    rows_by_id = {str(row["overlay_candidate_id"]): row}
    assessments_by_id = {
        str(row["overlay_candidate_id"]): assess_overlay_candidate(row)
    }

    quality = selected_definition_review_quality(
        {
            "status": "grounded",
            "text": "One simple way is to exclude instances with missing values before training.",
            "supporting_overlay_candidate_ids": [str(row["overlay_candidate_id"])],
            "source_text_field": "quote_surface",
        },
        rows_by_id,
        assessments_by_id,
    )

    assert quality["suppressed"] is True
    assert "example_update_surface" in quality["surface_families"]

    definition_row = _synthetic_support_pack_row(
        kc_id="KC_CLU_DBS_002",
        canonical_name="Border Point",
        suffix="definition",
        text="A border point is a non-core point that lies within the neighborhood of a core point.",
    )
    definition_rows_by_id = {str(definition_row["overlay_candidate_id"]): definition_row}
    definition_assessments_by_id = {
        str(definition_row["overlay_candidate_id"]): assess_overlay_candidate(definition_row)
    }
    good_quality = selected_definition_review_quality(
        {
            "status": "grounded",
            "text": "A border point is a non-core point that lies within the neighborhood of a core point.",
            "supporting_overlay_candidate_ids": [str(definition_row["overlay_candidate_id"])],
            "source_text_field": "quote_surface",
        },
        definition_rows_by_id,
        definition_assessments_by_id,
    )

    assert good_quality["suppressed"] is False


def test_build_kc_draft_bundles_llm_suppresses_formula_only_review_ready_surface():
    kc_id = "KC_CLF_NB_002"
    row = _synthetic_support_pack_row(
        kc_id=kc_id,
        canonical_name="Prior Probability",
        suffix="formula",
        text="Prior Probability P(y)=count(y)/N.",
    )

    def draft_invoker(request: dict[str, object]):
        label = next(iter(dict(request["request_payload"]).get("label_to_overlay_candidate_id", {})))
        return {
            "definition": {
                "status": "grounded",
                "text": "P(y)=count(y)/N.",
                "supporting_evidence_labels": [label],
                "abstention_reason": "",
            },
            "scope": {
                "status": "grounded",
                "text": "Prior probability is used within class-label probability estimation.",
                "supporting_evidence_labels": [label],
                "abstention_reason": "",
            },
        }, {"source": "surface_quality_test"}

    def verify_invoker(request: dict[str, object]):
        label = next(iter(dict(request["request_payload"]).get("evidence_lookup", {})))
        return {
            "definition": {
                "status": "grounded",
                "text": "P(y)=count(y)/N.",
                "supporting_evidence_labels": [label],
                "abstention_reason": "",
            },
            "scope": {
                "status": "grounded",
                "text": "Prior probability is used within class-label probability estimation.",
                "supporting_evidence_labels": [label],
                "abstention_reason": "",
            },
        }, {"source": "surface_quality_test"}

    bundles, stats = build_kc_draft_bundles_llm(
        [row],
        runtime=Step67ModelRuntime(
            base_url="http://unit.test",
            model="synthetic-model",
            draft_invoker=draft_invoker,
            verify_invoker=verify_invoker,
        ),
        policy=Step67DraftingPolicy(max_llm_calls_per_kc=4),
    )

    bundle = bundles[0]
    assert bundle["definition_full_candidate"]["status"] == "grounded"
    assert bundle["selected_definition_review_suppressed"] is True
    assert "selected_definition_formula_only_anchor" in bundle["risk_flags"]
    assert bundle["trust_state"]["label"] != "grounded"
    assert bundle["review_readiness"]["label"] != "ready"
    assert bundle["draft_status"] == "draft_ready_with_holds"
    assert stats["selected_definition_review_suppressed_count"] == 1


def test_definition_candidates_use_same_kc_support_pack_before_llm_drafting():
    kc_id = "KC_CLF_NB_002"
    canonical_name = "Prior Probability"
    rows = [
        _synthetic_support_pack_row(
            kc_id=kc_id,
            canonical_name=canonical_name,
            suffix="01",
            text="In the following, we discuss prior probability and its role in classification.",
            topic_path_labels=["Data Mining", "Classification", "Naive Bayes"],
        ),
        _synthetic_support_pack_row(
            kc_id=kc_id,
            canonical_name=canonical_name,
            suffix="02",
            text=(
                "The second term in the numerator of Equation 4.14 is the prior probability P(y). "
                "The prior probability captures our prior beliefs about the distribution of class labels."
            ),
            topic_path_labels=["Data Mining", "Classification", "Naive Bayes"],
        ),
        _synthetic_support_pack_row(
            kc_id=kc_id,
            canonical_name=canonical_name,
            suffix="03",
            text="P(y)=count(y)/N, where count(y) is the number of training instances with class y.",
            topic_path_labels=["Data Mining", "Classification", "Naive Bayes"],
        ),
        _synthetic_support_pack_row(
            kc_id=kc_id,
            canonical_name=canonical_name,
            suffix="04",
            text="Bayes theorem provides a convenient way to combine our prior beliefs with the likelihood of obtaining the observed attribute values.",
            topic_path_labels=["Data Mining", "Classification", "Naive Bayes"],
        ),
    ]
    rows[0]["block_id"] = "doc.synthetic:100"
    rows[1]["block_id"] = "doc.synthetic:101"
    rows[2]["block_id"] = "doc.synthetic:102"
    rows[3]["block_id"] = "doc.synthetic:103"

    rows_by_id = {str(row["overlay_candidate_id"]): row for row in rows}
    assessments_by_id = {
        str(row["overlay_candidate_id"]): assess_overlay_candidate(row)
        for row in rows
    }

    candidates = _definition_candidates(
        rows_by_id,
        assessments_by_id,
        target_descriptor=_kc_descriptor(rows[0]),
        sibling_descriptors=[],
        limit=5,
    )

    assert [item.overlay_candidate_id for item in candidates[:3]] == [
        f"{kc_id}:overlay:02",
        f"{kc_id}:overlay:01",
        f"{kc_id}:overlay:03",
    ]


def test_definition_verification_phase_preserves_clean_direct_candidate_over_truncated_rescue():
    kc_id = "KC_CLU_DBS_003"
    canonical_name = "Noise Point"
    full_row = _synthetic_support_pack_row(
        kc_id=kc_id,
        canonical_name=canonical_name,
        suffix="full",
        text="A noise point is any point that is neither a core point nor a border point.",
        topic_path_labels=["Data Mining", "Clustering", "DBSCAN"],
    )
    truncated_row = _synthetic_support_pack_row(
        kc_id=kc_id,
        canonical_name=canonical_name,
        suffix="trunc",
        text="A noise point is any point that is neither a core point nor a",
        topic_path_labels=["Data Mining", "Clustering", "DBSCAN"],
    )
    rows_by_id = {
        str(full_row["overlay_candidate_id"]): full_row,
        str(truncated_row["overlay_candidate_id"]): truncated_row,
    }
    target_descriptor = _kc_descriptor(full_row)
    preserved_definition_candidate = {
        "status": "grounded",
        "text": "A noise point is a point that is neither a core point nor a border point.",
        "supporting_overlay_candidate_ids": [str(full_row["overlay_candidate_id"])],
        "selection_reason": "definition_full_candidate_llm_multispan_verified",
        "source_text_field": "quote_surface",
    }
    rescue_definition_candidate = {
        "status": "grounded",
        "text": "A noise point is any point that is neither a core point nor a.",
        "supporting_overlay_candidate_ids": [str(truncated_row["overlay_candidate_id"])],
        "selection_reason": "definition_full_candidate_source_faithful_local_support_unit_normalization",
        "source_text_field": "source_faithful_normalization",
    }

    final_definition_candidate, _, action = _run_definition_verification_phase(
        preserved_definition_candidate=preserved_definition_candidate,
        rescue_definition_candidate=rescue_definition_candidate,
        preserved_scope_candidate={},
        rescue_scope_candidate={},
        rows_by_id=rows_by_id,
        target_descriptor=target_descriptor,
        sibling_descriptors=[],
    )

    assert final_definition_candidate["text"] == preserved_definition_candidate["text"]
    assert action == "preserved_definition_over_non_monotonic_rescue"


def test_definition_verification_phase_allows_strictly_better_rescue_for_fragmentary_preserved_candidate():
    kc_id = "KC_EVAL_BASIC_005"
    canonical_name = "Specificity"
    fragment_row = _synthetic_support_pack_row(
        kc_id=kc_id,
        canonical_name=canonical_name,
        suffix="frag",
        text="specificity) is defined as the fraction of negative test instances correctly",
        topic_path_labels=["Data Mining", "Evaluation", "Basics"],
    )
    full_row = _synthetic_support_pack_row(
        kc_id=kc_id,
        canonical_name=canonical_name,
        suffix="full",
        text="Specificity is the fraction of negative test instances correctly classified as negative.",
        topic_path_labels=["Data Mining", "Evaluation", "Basics"],
    )
    rows_by_id = {
        str(fragment_row["overlay_candidate_id"]): fragment_row,
        str(full_row["overlay_candidate_id"]): full_row,
    }
    target_descriptor = _kc_descriptor(full_row)
    preserved_definition_candidate = {
        "status": "grounded",
        "text": "specificity) is defined as the fraction of negative test instances correctly",
        "supporting_overlay_candidate_ids": [str(fragment_row["overlay_candidate_id"])],
        "selection_reason": "definition_full_candidate_single_span_fallback",
        "source_text_field": "quote_surface",
    }
    rescue_definition_candidate = {
        "status": "grounded",
        "text": "Specificity is the fraction of negative test instances correctly classified as negative.",
        "supporting_overlay_candidate_ids": [str(full_row["overlay_candidate_id"])],
        "selection_reason": "definition_full_candidate_source_faithful_local_support_unit_normalization",
        "source_text_field": "source_faithful_normalization",
    }

    final_definition_candidate, _, action = _run_definition_verification_phase(
        preserved_definition_candidate=preserved_definition_candidate,
        rescue_definition_candidate=rescue_definition_candidate,
        preserved_scope_candidate={},
        rescue_scope_candidate={},
        rows_by_id=rows_by_id,
        target_descriptor=target_descriptor,
        sibling_descriptors=[],
    )

    assert final_definition_candidate["text"] == rescue_definition_candidate["text"]
    assert action == "replaced_preserved_definition_with_strictly_better_rescue"


def test_definition_verification_phase_rejects_foreign_rescue_candidate():
    target_row = _synthetic_support_pack_row(
        kc_id="KC_EVAL_BASIC_005",
        canonical_name="Specificity",
        suffix="target",
        text="Specificity is the fraction of negative instances correctly classified as negative.",
        topic_path_labels=["Data Mining", "Evaluation", "Basics"],
    )
    foreign_row = _synthetic_support_pack_row(
        kc_id="KC_EVAL_BASIC_004",
        canonical_name="Recall",
        suffix="foreign",
        text="Recall is the fraction of positive instances correctly classified as positive.",
        topic_path_labels=["Data Mining", "Evaluation", "Basics"],
        source_kc_id="KC_EVAL_BASIC_004",
    )
    rows_by_id = {
        str(target_row["overlay_candidate_id"]): target_row,
        str(foreign_row["overlay_candidate_id"]): foreign_row,
    }
    target_descriptor = _kc_descriptor(target_row)
    sibling_descriptor = _kc_descriptor(
        {
            **foreign_row,
            "kc_id": "KC_EVAL_BASIC_004",
            "canonical_name": "Recall",
            "seed_definition": "The fraction of positive instances correctly classified as positive.",
        }
    )
    preserved_definition_candidate = {
        "status": "grounded",
        "text": "Specificity is the fraction of negative instances correctly classified as negative.",
        "supporting_overlay_candidate_ids": [str(target_row["overlay_candidate_id"])],
        "selection_reason": "definition_full_candidate_llm_multispan_verified",
        "source_text_field": "quote_surface",
    }
    rescue_definition_candidate = {
        "status": "grounded",
        "text": "Recall is the fraction of positive instances correctly classified as positive.",
        "supporting_overlay_candidate_ids": [str(foreign_row["overlay_candidate_id"])],
        "selection_reason": "definition_full_candidate_source_faithful_local_support_unit_normalization",
        "source_text_field": "source_faithful_normalization",
    }

    final_definition_candidate, _, action = _run_definition_verification_phase(
        preserved_definition_candidate=preserved_definition_candidate,
        rescue_definition_candidate=rescue_definition_candidate,
        preserved_scope_candidate={},
        rescue_scope_candidate={},
        rows_by_id=rows_by_id,
        target_descriptor=target_descriptor,
        sibling_descriptors=[sibling_descriptor],
    )

    assert final_definition_candidate["text"] == preserved_definition_candidate["text"]
    assert action == "preserved_definition_over_non_monotonic_rescue"


def test_definition_support_binding_prefers_stronger_same_kc_definition_over_procedure_anchor():
    kc_id = "KC_SYN_BIND_PROC"
    target_descriptor = _kc_descriptor(
        {
            "kc_id": kc_id,
            "canonical_name": "Node Impurity",
            "aliases": [],
            "seed_definition": "A measure of heterogeneity at a node.",
        }
    )
    weak_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="weak",
        text="Measure impurity to identify the best attribute test condition for a node.",
        score=18.0,
        classification="context_support",
        positive_surface_type="anchored_descriptive_clause",
        issues=["procedural_fragment"],
        single_span_accepted=False,
        row_overrides={"is_procedure_like": True},
        assessment_overrides={"context_candidate": True, "definition_candidate": False},
    )
    strong_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="strong",
        text="Node impurity measures the heterogeneity of class labels at a tree node.",
        score=17.0,
        classification="definition_support",
        positive_surface_type="prose_definition",
        single_span_accepted=True,
    )
    repaired, diagnostics = _repair_definition_support_binding(
        current_value={
            "status": "grounded",
            "text": "Node impurity is a measure of the heterogeneity of class labels at a tree node.",
            "supporting_overlay_candidate_ids": [weak_candidate.overlay_candidate_id],
            "selection_reason": "definition_full_candidate_llm_multispan_verified",
            "source_text_field": "quote_surface",
        },
        definition_candidates=[weak_candidate, strong_candidate],
        rows_by_id={
            weak_candidate.overlay_candidate_id: weak_candidate.row,
            strong_candidate.overlay_candidate_id: strong_candidate.row,
        },
        target_descriptor=target_descriptor,
        sibling_descriptors=[],
        max_support_rows=2,
        max_chars=320,
    )

    assert repaired["supporting_overlay_candidate_ids"] == [strong_candidate.overlay_candidate_id]
    assert diagnostics["repair_state"] == "repair_attempted_and_applied"
    assert diagnostics["repair_applied"] is True
    assert diagnostics["repair_reason"] == "promoted_stronger_same_kc_definition_anchor"
    assert diagnostics["repair_attempt_reason"] == "promoted_stronger_same_kc_definition_anchor"
    assert diagnostics["stronger_same_kc_candidate_existed"] is True
    assert "procedure_or_example_anchor" in diagnostics["weaker_anchor_rejections"][weak_candidate.overlay_candidate_id]
    assert diagnostics["final_binding_mode"] == "single_row"


def test_definition_support_binding_blocks_out_of_pool_provenance():
    kc_id = "KC_SYN_BIND_POOL"
    target_descriptor = _kc_descriptor(
        {
            "kc_id": kc_id,
            "canonical_name": "Posterior Probability",
            "aliases": [],
            "seed_definition": "The probability after observing evidence.",
        }
    )
    pool_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="pool",
        text="Posterior probability is the probability of a class after observing the evidence.",
        score=20.0,
        classification="definition_support",
        positive_surface_type="prose_definition",
    )
    repaired, diagnostics = _repair_definition_support_binding(
        current_value={
            "status": "grounded",
            "text": "Posterior probability is the probability of a class after observing the evidence.",
            "supporting_overlay_candidate_ids": [f"{kc_id}:overlay:outside"],
            "selection_reason": "definition_full_candidate_llm_multispan_verified",
            "source_text_field": "quote_surface",
        },
        definition_candidates=[pool_candidate],
        rows_by_id={pool_candidate.overlay_candidate_id: pool_candidate.row},
        target_descriptor=target_descriptor,
        sibling_descriptors=[],
        max_support_rows=2,
        max_chars=320,
    )

    assert repaired["supporting_overlay_candidate_ids"] == [pool_candidate.overlay_candidate_id]
    assert diagnostics["repair_state"] == "repair_attempted_and_applied"
    assert diagnostics["out_of_pool_support_ids"] == [f"{kc_id}:overlay:outside"]
    assert diagnostics["repair_reason"] == "blocked_out_of_pool_definition_binding"
    assert diagnostics["repair_attempt_reason"] == "blocked_out_of_pool_definition_binding"


def test_definition_support_binding_allows_bounded_two_row_same_kc_binding_when_single_row_is_insufficient():
    kc_id = "KC_SYN_BIND_MULTI"
    target_descriptor = _kc_descriptor(
        {
            "kc_id": kc_id,
            "canonical_name": "Misclassification Rate",
            "aliases": [],
            "seed_definition": "A rate derived from the most frequent class.",
        }
    )
    formula_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="formula",
        text="Misclassification rate = 1 - max_y P(y|v).",
        score=19.0,
        classification="definition_support",
        positive_surface_type="named_formula",
        single_span_accepted=False,
        row_overrides={"is_formula_like": True},
    )
    gloss_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="gloss",
        text="Misclassification rate is the probability of assigning an instance to the wrong class.",
        score=18.0,
        classification="definition_support",
        positive_surface_type="prose_definition",
        single_span_accepted=False,
    )
    repaired, diagnostics = _repair_definition_support_binding(
        current_value={
            "status": "grounded",
            "text": "Misclassification rate is the probability of assigning an instance to the wrong class.",
            "supporting_overlay_candidate_ids": [formula_candidate.overlay_candidate_id],
            "selection_reason": "definition_full_candidate_llm_multispan_verified",
            "source_text_field": "quote_surface",
        },
        definition_candidates=[formula_candidate, gloss_candidate],
        rows_by_id={
            formula_candidate.overlay_candidate_id: formula_candidate.row,
            gloss_candidate.overlay_candidate_id: gloss_candidate.row,
        },
        target_descriptor=target_descriptor,
        sibling_descriptors=[],
        max_support_rows=2,
        max_chars=320,
    )

    assert repaired["supporting_overlay_candidate_ids"] == [
        gloss_candidate.overlay_candidate_id,
        formula_candidate.overlay_candidate_id,
    ]
    assert diagnostics["repair_state"] == "repair_attempted_and_applied"
    assert diagnostics["final_binding_mode"] == "multi_row"
    assert diagnostics["repair_reason"] == "promoted_bounded_multi_row_definition_binding"
    assert diagnostics["repair_attempt_reason"] == "promoted_bounded_multi_row_definition_binding"


def test_definition_support_binding_prefers_local_definition_over_weak_topic_or_crossconcept_anchor():
    target_kc_id = "KC_SYN_BIND_LOCAL"
    target_descriptor = _kc_descriptor(
        {
            "kc_id": target_kc_id,
            "canonical_name": "Specificity",
            "aliases": [],
            "seed_definition": "The fraction of negatives correctly classified.",
        }
    )
    weak_anchor = _synthetic_definition_candidate(
        target_kc_id=target_kc_id,
        source_kc_id="KC_SYN_BIND_FOREIGN",
        overlay_suffix="weak_topic",
        text="Specificity is discussed together with several related evaluation concepts in this section.",
        score=21.0,
        classification="context_support",
        positive_surface_type="anchored_descriptive_clause",
        has_name_anchor=False,
        title_overlap=0,
        seed_overlap=0,
        row_overrides={"strong_same_topic": False},
        assessment_overrides={"context_candidate": True, "definition_candidate": False},
    )
    strong_local = _synthetic_definition_candidate(
        target_kc_id=target_kc_id,
        source_kc_id=target_kc_id,
        overlay_suffix="local",
        text="Specificity is the fraction of negative instances correctly classified as negative.",
        score=18.0,
        classification="definition_support",
        positive_surface_type="prose_definition",
    )
    repaired, diagnostics = _repair_definition_support_binding(
        current_value={
            "status": "grounded",
            "text": "Specificity is the fraction of negative instances correctly classified as negative.",
            "supporting_overlay_candidate_ids": [weak_anchor.overlay_candidate_id],
            "selection_reason": "definition_full_candidate_llm_multispan_verified",
            "source_text_field": "quote_surface",
        },
        definition_candidates=[weak_anchor, strong_local],
        rows_by_id={
            weak_anchor.overlay_candidate_id: weak_anchor.row,
            strong_local.overlay_candidate_id: strong_local.row,
        },
        target_descriptor=target_descriptor,
        sibling_descriptors=[],
        max_support_rows=2,
        max_chars=320,
    )

    assert repaired["supporting_overlay_candidate_ids"] == [strong_local.overlay_candidate_id]
    assert diagnostics["repair_state"] == "repair_attempted_and_applied"
    assert diagnostics["stronger_same_kc_candidate_existed"] is True
    assert "non_local_source" in diagnostics["weaker_anchor_rejections"][weak_anchor.overlay_candidate_id]
    assert "weak_topic_anchor" in diagnostics["weaker_anchor_rejections"][weak_anchor.overlay_candidate_id]


def test_definition_support_binding_keeps_action_reason_separate_when_repair_not_applied():
    kc_id = "KC_SYN_BIND_NOOP"
    target_descriptor = _kc_descriptor(
        {
            "kc_id": kc_id,
            "canonical_name": "Holdout Method",
            "aliases": [],
            "seed_definition": "A single train test split.",
        }
    )
    current_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="current",
        text="The holdout method partitions the labeled dataset into a training set and a test set.",
        score=24.0,
        classification="definition_support",
        positive_surface_type="anchored_descriptive_clause",
        row_overrides={"is_procedure_like": True},
    )
    weaker_alternative = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="alt",
        text="Holdout is used to report a test estimate after one split.",
        score=16.0,
        classification="definition_support",
        positive_surface_type="anchored_descriptive_clause",
    )
    repaired, diagnostics = _repair_definition_support_binding(
        current_value={
            "status": "grounded",
            "text": "The holdout method partitions the labeled dataset into a training set and a test set.",
            "supporting_overlay_candidate_ids": [current_candidate.overlay_candidate_id],
            "selection_reason": "definition_full_candidate_source_faithful_local_quote_normalization",
            "source_text_field": "source_block_text",
        },
        definition_candidates=[current_candidate, weaker_alternative],
        rows_by_id={
            current_candidate.overlay_candidate_id: current_candidate.row,
            weaker_alternative.overlay_candidate_id: weaker_alternative.row,
        },
        target_descriptor=target_descriptor,
        sibling_descriptors=[],
        max_support_rows=2,
        max_chars=320,
    )

    assert repaired["supporting_overlay_candidate_ids"] == [current_candidate.overlay_candidate_id]
    assert diagnostics["repair_applied"] is False
    assert diagnostics["repair_state"] == "repair_attempted_but_rejected"
    assert diagnostics["repair_reason"] == "no_strictly_better_anchor_available"
    assert diagnostics["repair_attempt_reason"] == "replaced_weak_definition_anchor"


def test_definition_support_binding_blocks_non_monotonic_single_row_replacement():
    kc_id = "KC_SYN_BIND_MONO"
    target_descriptor = _kc_descriptor(
        {
            "kc_id": kc_id,
            "canonical_name": "Border Point",
            "aliases": [],
            "seed_definition": "A non-core point in the neighborhood of a core point.",
        }
    )
    current_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="current",
        text="A border point is a point that is not a core point, but it falls within the neighborhood of a core point.",
        score=24.0,
        classification="definition_support",
        positive_surface_type="anchored_descriptive_clause",
        row_overrides={"strong_same_topic": False},
    )
    superficially_stronger_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="surface",
        text="A border point is not a core point, but falls within the neighborhood of a core point.",
        score=44.0,
        classification="definition_support",
        positive_surface_type="anchored_descriptive_clause",
    )
    repaired, diagnostics = _repair_definition_support_binding(
        current_value={
            "status": "grounded",
            "text": "A border point is a point that is not a core point, but it falls within the neighborhood of a core point.",
            "supporting_overlay_candidate_ids": [current_candidate.overlay_candidate_id],
            "selection_reason": "definition_full_candidate_source_faithful_local_support_unit_normalization",
            "source_text_field": "source_block_text",
        },
        definition_candidates=[current_candidate, superficially_stronger_candidate],
        rows_by_id={
            current_candidate.overlay_candidate_id: current_candidate.row,
            superficially_stronger_candidate.overlay_candidate_id: superficially_stronger_candidate.row,
        },
        target_descriptor=target_descriptor,
        sibling_descriptors=[],
        max_support_rows=2,
        max_chars=320,
    )

    assert repaired["supporting_overlay_candidate_ids"] == [current_candidate.overlay_candidate_id]
    assert diagnostics["repair_applied"] is False
    assert diagnostics["repair_state"] == "repair_attempted_but_rejected"
    assert diagnostics["repair_reason"] == "non_monotonic_single_row_replacement_rejected"
    assert diagnostics["repair_attempt_reason"] == "promoted_stronger_same_kc_definition_anchor"
    assert diagnostics["chosen_support_ids"] == [current_candidate.overlay_candidate_id]


def test_build_kc_draft_bundles_llm_persists_definition_support_binding_diagnostics():
    kc_id = "KC_SYN_BIND_DIAG"
    canonical_name = "Node Impurity"
    rows = [
        _synthetic_overlay_row(
            kc_id=kc_id,
            canonical_name=canonical_name,
            suffix="01",
            text="Node impurity measures the heterogeneity of class labels at a tree node.",
            topic_path_labels=["Synthetic Domain", "Synthetic Branch"],
        ),
        _synthetic_overlay_row(
            kc_id=kc_id,
            canonical_name=canonical_name,
            suffix="02",
            text="Measure impurity to identify the best attribute test condition for a node.",
            topic_path_labels=["Synthetic Domain", "Synthetic Branch"],
        ),
    ]
    strong_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="01",
        text="Node impurity measures the heterogeneity of class labels at a tree node.",
        score=17.0,
        classification="definition_support",
        positive_surface_type="prose_definition",
    )
    weak_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="02",
        text="Measure impurity to identify the best attribute test condition for a node.",
        score=19.0,
        classification="context_support",
        positive_surface_type="anchored_descriptive_clause",
        issues=["procedural_fragment"],
        single_span_accepted=False,
        row_overrides={"is_procedure_like": True},
        assessment_overrides={"context_candidate": True, "definition_candidate": False},
    )

    original_definition_candidates = drafting_module._definition_candidates
    original_select_definition_support_pack = drafting_module.select_definition_support_pack
    original_scope_candidates = drafting_module._scope_candidates
    original_definition_rescue_candidates = drafting_module._definition_rescue_candidates
    drafting_module._definition_candidates = lambda *args, **kwargs: [weak_candidate, strong_candidate]
    drafting_module.select_definition_support_pack = lambda *args, **kwargs: []
    drafting_module._scope_candidates = lambda *args, **kwargs: []
    drafting_module._definition_rescue_candidates = lambda candidates, *, limit: list(candidates)[:limit]

    def draft_invoker(request: dict[str, object]):
        label = next(iter(dict(request["request_payload"]).get("label_to_overlay_candidate_id", {})))
        return {
            "definition": {
                "status": "grounded",
                "text": "Node impurity is a measure of the heterogeneity of class labels at a tree node.",
                "supporting_evidence_labels": [label],
                "abstention_reason": "",
            },
            "scope": {
                "status": "abstained",
                "text": "",
                "supporting_evidence_labels": [],
                "abstention_reason": "scope_gap",
            },
        }, {"source": "test_binding_diag"}

    def verify_invoker(request: dict[str, object]):
        label = next(iter(dict(request["request_payload"]).get("evidence_lookup", {})))
        return {
            "definition": {
                "status": "grounded",
                "text": "Node impurity is a measure of the heterogeneity of class labels at a tree node.",
                "supporting_evidence_labels": [label],
                "abstention_reason": "",
            },
            "scope": {
                "status": "abstained",
                "text": "",
                "supporting_evidence_labels": [],
                "abstention_reason": "scope_gap",
            },
        }, {"source": "test_binding_diag"}

    try:
        bundles, _ = build_kc_draft_bundles_llm(
            rows,
            runtime=Step67ModelRuntime(
                base_url="http://unit.test",
                model="synthetic-model",
                draft_invoker=draft_invoker,
                verify_invoker=verify_invoker,
            ),
            policy=Step67DraftingPolicy(max_definition_binding_support_rows=2, max_llm_calls_per_kc=8),
        )

        bundle = bundles[0]
        binding_diag = bundle["selection_diagnostics"]["definition_support_binding"]

        assert bundle["definition_full_candidate"]["supporting_overlay_candidate_ids"] == [strong_candidate.overlay_candidate_id]
        assert binding_diag["repair_state"] == "repair_attempted_and_applied"
        assert binding_diag["repair_applied"] is True
        assert binding_diag["repair_reason"] == "promoted_stronger_same_kc_definition_anchor"
        assert binding_diag["repair_attempt_reason"] == "promoted_stronger_same_kc_definition_anchor"
        assert binding_diag["final_binding_mode"] == "single_row"
        assert binding_diag["chosen_support_ids"] == [strong_candidate.overlay_candidate_id]
        assert any(
            item["overlay_candidate_id"] == weak_candidate.overlay_candidate_id
            and "procedure_or_example_anchor" in item["binding_reject_reasons"]
            for item in binding_diag["candidate_anchor_pool_considered"]
        )
    finally:
        drafting_module._definition_candidates = original_definition_candidates
        drafting_module.select_definition_support_pack = original_select_definition_support_pack
        drafting_module._scope_candidates = original_scope_candidates
        drafting_module._definition_rescue_candidates = original_definition_rescue_candidates


def test_build_kc_draft_bundles_llm_preservation_success_short_circuits_rescue_and_legacy_redraft(monkeypatch):
    kc_id = "KC_SYN_MONO_KEEP"
    canonical_name = "Metric Stability"
    rows = [
        _synthetic_overlay_row(
            kc_id=kc_id,
            canonical_name=canonical_name,
            suffix="01",
            text="Metric Stability is the consistency of a metric across repeated measurements.",
            topic_path_labels=["Synthetic Domain", "Synthetic Branch"],
        ),
        _synthetic_overlay_row(
            kc_id=kc_id,
            canonical_name=canonical_name,
            suffix="02",
            text="Metric Stability applies when repeated measurements are compared over time.",
            topic_path_labels=["Synthetic Domain", "Synthetic Branch"],
        ),
        _synthetic_overlay_row(
            kc_id=kc_id,
            canonical_name=canonical_name,
            suffix="03",
            text="Metric Stability is often discussed together with related evaluation procedures and examples.",
            topic_path_labels=["Synthetic Domain", "Synthetic Branch"],
        ),
    ]
    preservation_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="01",
        text="Metric Stability is the consistency of a metric across repeated measurements.",
        score=25.0,
        classification="definition_support",
        positive_surface_type="prose_definition",
    )
    rescue_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="03",
        text="Metric Stability is often discussed together with related evaluation procedures and examples.",
        score=24.0,
        classification="definition_support",
        positive_surface_type="prose_definition",
    )
    scope_candidates = [
        _synthetic_scope_candidate(
            kc_id=kc_id,
            overlay_suffix="02",
            text="Metric Stability applies when repeated measurements are compared over time.",
        )
    ]

    monkeypatch.setattr(
        drafting_module,
        "_definition_candidates",
        lambda *args, support_pack=None, **kwargs: [rescue_candidate] if support_pack else [preservation_candidate],
    )
    monkeypatch.setattr(
        drafting_module,
        "select_definition_support_pack",
        lambda *args, **kwargs: [{"overlay_candidate_id": f"{kc_id}:overlay:03"}],
    )
    monkeypatch.setattr(drafting_module, "_scope_candidates", lambda *args, **kwargs: list(scope_candidates))
    monkeypatch.setattr(drafting_module, "_definition_rescue_candidates", lambda candidates, *, limit: list(candidates)[:limit])

    phase_log: list[str] = []
    state = {"draft_calls": 0, "verify_calls": 0}

    def draft_invoker(request: dict[str, object]):
        phase = str(request["phase"])
        phase_log.append(phase)
        assert phase == "draft"
        state["draft_calls"] += 1
        assert state["draft_calls"] == 1
        label = next(iter(dict(request["request_payload"]).get("label_to_overlay_candidate_id", {})))
        return {
            "definition": {
                "status": "grounded",
                "text": preservation_candidate.text,
                "supporting_evidence_labels": [label],
                "abstention_reason": "",
            },
            "scope": {
                "status": "abstained",
                "text": "",
                "supporting_evidence_labels": [],
                "abstention_reason": "scope_gap",
            },
        }, {"source": "test_preservation"}

    def verify_invoker(request: dict[str, object]):
        phase = str(request["phase"])
        phase_log.append(phase)
        assert phase == "verify"
        state["verify_calls"] += 1
        assert state["verify_calls"] == 1
        label = next(iter(dict(request["request_payload"]).get("evidence_lookup", {})))
        return {
            "definition": {
                "status": "grounded",
                "text": preservation_candidate.text,
                "supporting_evidence_labels": [label],
                "abstention_reason": "",
            },
            "scope": {
                "status": "abstained",
                "text": "",
                "supporting_evidence_labels": [],
                "abstention_reason": "scope_gap",
            },
        }, {"source": "test_preservation"}

    bundles, stats = build_kc_draft_bundles_llm(
        rows,
        runtime=Step67ModelRuntime(
            base_url="http://unit.test",
            model="synthetic-model",
            draft_invoker=draft_invoker,
            verify_invoker=verify_invoker,
        ),
        policy=Step67DraftingPolicy(max_llm_calls_per_kc=8),
    )

    bundle = bundles[0]
    llm_diag = bundle["selection_diagnostics"]["llm_drafting"]
    grounding_diag = bundle["selection_diagnostics"]["definition_grounding_diagnostics"]

    assert bundle["definition_full_candidate"]["text"] == preservation_candidate.text
    assert llm_diag["effective_definition_phase"] == "preservation"
    assert llm_diag["preservation_short_circuited_rescue"] is True
    assert llm_diag["rescue_used"] is False
    assert llm_diag["legacy_redraft_path_enabled"] is False
    assert llm_diag["legacy_definition_redraft_allowed"] is False
    assert llm_diag["legacy_scope_redraft_allowed"] is False
    assert llm_diag["llm_call_budget"]["phase_call_order"] == ["draft", "verify"]
    assert llm_diag["llm_call_budget"]["calls_used"] == 2
    assert grounding_diag["control_fallback_applied"] is False
    assert grounding_diag["collapse_stage"] == "grounded_before_control_fallback"
    assert phase_log == ["draft", "verify"]
    assert stats["kcs_with_llm_budget_exhaustion"] == 0


def test_definition_draft_supported_single_span_fallback_requires_single_span_local_pool_match():
    kc_id = "KC_SYN_CONTROL_FALLBACK"
    candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="01",
        text="Control Fallback is the exact local support row.",
        score=21.0,
        classification="definition_support",
        positive_surface_type="prose_definition",
    )
    non_local = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id="KC_OTHER",
        overlay_suffix="02",
        text="Other concept support.",
        score=22.0,
        classification="definition_support",
        positive_surface_type="prose_definition",
        row_overrides={"kc_id": "KC_OTHER"},
    )
    rejected_single_span = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="03",
        text="Rejected local fragment",
        score=23.0,
        classification="definition_support",
        positive_surface_type="fragment",
        single_span_accepted=False,
    )

    picked, source_phase = _definition_draft_supported_single_span_fallback_candidate(
        definition_candidates=[non_local, rejected_single_span, candidate],
        preservation_draft_response={
            "definition": {
                "status": "grounded",
                "text": "fallback draft",
                "supporting_overlay_candidate_ids": [candidate.overlay_candidate_id],
            }
        },
        rescue_draft_response={"definition": {"status": "abstained", "text": "", "supporting_overlay_candidate_ids": []}},
        definition_redraft_response={"definition": {"status": "abstained", "text": "", "supporting_overlay_candidate_ids": []}},
        target_descriptor={"kc_id": kc_id, "canonical_name": "Control Fallback", "seed_definition": "seed"},
        sibling_descriptors=[],
    )

    assert picked == candidate
    assert source_phase == "preservation_draft_response"


def test_definition_draft_supported_single_span_fallback_value_prefers_quote_surface_for_direct():
    kc_id = "KC_SYN_QUOTE_DIRECT"
    candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="01",
        text="These techniques are known as ensemble or classifier combination methods.",
        score=21.0,
        classification="context_support",
        positive_surface_type="prose_definition",
        has_name_anchor=False,
        title_overlap=2,
        seed_overlap=0,
        row_overrides={
            "quote_surface": (
                "An ensemble classifier is a method that constructs a set of base classifiers from training "
                "data and performs classification by taking a vote on the predictions made by each base classifier."
            ),
            "source_block_text": (
                "This section presents techniques for improving classification accuracy by aggregating the "
                "predictions of multiple classifiers. These techniques are known as ensemble or classifier "
                "combination methods."
            ),
            "patch_heading": "Ensemble Methods",
            "is_procedure_like": True,
        },
    )

    value, normalized = _definition_draft_supported_single_span_fallback_value(
        field_name="definition_full_candidate",
        candidate=candidate,
        target_descriptor=_kc_descriptor(
            {
                "kc_id": kc_id,
                "canonical_name": "Ensemble Classifier",
                "aliases": [],
                "seed_definition": "A method that combines predictions from multiple base classifiers.",
            }
        ),
    )

    assert normalized is False
    assert value["selection_reason"] == "definition_full_candidate_draft_supported_single_span_fallback"
    assert value["source_text_field"] == "quote_surface"
    assert value["text"].startswith("An ensemble classifier is a method that constructs a set of base classifiers")


def test_definition_draft_supported_single_span_fallback_value_demotes_discourse_led_surface_to_normalized():
    kc_id = "KC_SYN_DISCOURSE_DIRECT"
    candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="01",
        text=(
            "In the following, we present different ways of measuring the impurity of a node and the "
            "collective impurity of its child nodes, both of which will be used to identify the best "
            "attribute test condition for a node."
        ),
        score=22.0,
        classification="definition_support",
        positive_surface_type="prose_definition",
        has_name_anchor=True,
        title_overlap=2,
        seed_overlap=2,
        row_overrides={
            "quote_surface": (
                "In the following, we present different ways of measuring the impurity of a node and the "
                "collective impurity of its child nodes, both of which will be used to identify the best "
                "attribute test condition for a node."
            ),
            "source_block_text": (
                "In the following, we present different ways of measuring the impurity of a node and the "
                "collective impurity of its child nodes, both of which will be used to identify the best "
                "attribute test condition for a node."
            ),
            "patch_heading": "Impurity Measure for a Single Node",
        },
    )

    value, normalized = _definition_draft_supported_single_span_fallback_value(
        field_name="definition_full_candidate",
        candidate=candidate,
        target_descriptor=_kc_descriptor(
            {
                "kc_id": kc_id,
                "canonical_name": "Node Impurity",
                "aliases": [],
                "seed_definition": "A measure of class-label heterogeneity at a tree node.",
            }
        ),
    )

    assert normalized is True
    assert value["selection_reason"] == "definition_full_candidate_source_faithful_fallback_surface_normalization"
    assert value["source_text_field"] == "quote_surface"
    assert value["text"].startswith("In the following, we present different ways of measuring the impurity")


def test_definition_draft_supported_single_span_fallback_value_rejects_procedure_prompt_without_safe_normalization():
    kc_id = "KC_SYN_PROMPT_DIRECT"
    candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="01",
        text="c. Calculate the weighted misclassification rate of the child nodes. Would",
        score=23.0,
        classification="definition_support",
        positive_surface_type="prose_definition",
        row_overrides={
            "quote_surface": "Calculate the weighted misclassification rate of the child nodes.",
            "source_block_text": "c. Calculate the weighted misclassification rate of the child nodes. Would",
            "patch_heading": "Exercises",
            "is_procedure_like": True,
        },
        assessment_overrides={"question_like": True},
    )

    value, normalized = _definition_draft_supported_single_span_fallback_value(
        field_name="definition_full_candidate",
        candidate=candidate,
        target_descriptor=_kc_descriptor(
            {
                "kc_id": kc_id,
                "canonical_name": "Misclassification Rate",
                "aliases": [],
                "seed_definition": "An impurity measure for a node.",
            }
        ),
    )

    assert value == {}
    assert normalized is False


def test_definition_draft_supported_single_span_fallback_value_blocks_weak_target_aligned_context_surface():
    kc_id = "KC_SYN_FALLBACK_WEAK_ALIGNMENT"
    candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="01",
        text=(
            "Definition 6.11 suggests that an itemset is negatively correlated if its support is below "
            "the expected support computed using the statistical independence assumption."
        ),
        score=23.0,
        classification="definition_support",
        positive_surface_type="formula_backed_explanatory_clause",
        issues=["weak_target_alignment"],
        has_name_anchor=False,
        title_overlap=1,
        seed_overlap=0,
        row_overrides={
            "quote_surface": (
                "Definition 6.11 suggests that an itemset is negatively correlated if its support is below "
                "the expected support computed using the statistical independence assumption."
            ),
            "source_block_text": (
                "Definition 6.11 suggests that an itemset is negatively correlated if its support is below "
                "the expected support computed using the statistical independence assumption."
            ),
            "patch_heading": "Bibliographic Notes",
            "is_definition_like": False,
            "is_procedure_like": True,
        },
    )

    value, normalized = _definition_draft_supported_single_span_fallback_value(
        field_name="definition_full_candidate",
        candidate=candidate,
        target_descriptor=_kc_descriptor(
            {
                "kc_id": kc_id,
                "canonical_name": "Naive Independence Assumption",
                "aliases": [],
                "seed_definition": "The assumption that attributes are conditionally independent given the class.",
            }
        ),
    )

    assert value == {}
    assert normalized is False


def test_definition_draft_supported_single_span_fallback_value_preserves_name_led_equation_identity_direct():
    kc_id = "KC_SYN_CLUSTER_SSE"
    candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="01",
        text="Cluster SSE = sum of squared distances from cluster members to the centroid.",
        score=22.0,
        classification="equation_support",
        positive_surface_type="formula_backed_explanatory_clause",
        has_name_anchor=True,
        title_overlap=2,
        seed_overlap=1,
        row_overrides={
            "quote_surface": "Cluster SSE = sum of squared distances from cluster members to the centroid.",
            "source_block_text": "Cluster SSE = sum of squared distances from cluster members to the centroid.",
            "patch_heading": "Figure 7.28.",
            "is_definition_like": True,
            "is_procedure_like": False,
        },
    )

    value, normalized = _definition_draft_supported_single_span_fallback_value(
        field_name="definition_full_candidate",
        candidate=candidate,
        target_descriptor=_kc_descriptor(
            {
                "kc_id": kc_id,
                "canonical_name": "Cluster SSE",
                "aliases": [],
                "seed_definition": "The sum of squared errors within a cluster.",
            }
        ),
    )

    assert normalized is False
    assert value["selection_reason"] == "definition_full_candidate_draft_supported_single_span_fallback"
    assert value["text"].startswith("Cluster SSE =")


def test_definition_draft_supported_single_span_fallback_value_demotes_name_led_contextual_surface_to_normalized():
    kc_id = "KC_SYN_FORWARD_GEN"
    candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="01",
        text="Sequential Forward Generation (SFG) starts with an empty set of features S.",
        score=22.5,
        classification="definition_support",
        positive_surface_type="prose_definition",
        has_name_anchor=True,
        title_overlap=3,
        seed_overlap=1,
        row_overrides={
            "quote_surface": "Sequential Forward Generation (SFG) starts with an empty set of features S.",
            "source_block_text": (
                "Sequential Forward Generation (SFG) starts with an empty set of features S. "
                "Features are then added one at a time."
            ),
            "patch_heading": "Search Directions",
            "is_definition_like": True,
            "is_procedure_like": False,
        },
    )

    value, normalized = _definition_draft_supported_single_span_fallback_value(
        field_name="definition_full_candidate",
        candidate=candidate,
        target_descriptor=_kc_descriptor(
            {
                "kc_id": kc_id,
                "canonical_name": "Sequential Forward Generation",
                "aliases": ["SFG"],
                "seed_definition": "A search strategy that builds a feature subset by adding one feature at a time.",
            }
        ),
    )

    assert normalized is True
    assert value["selection_reason"] == "definition_full_candidate_source_faithful_fallback_surface_normalization"
    assert value["text"].startswith("Sequential Forward Generation (SFG) starts with an empty set of features S.")


def test_definition_draft_supported_single_span_fallback_value_allows_explicit_definition_relation_quote_direct_when_relation_score_is_zero():
    kc_id = "KC_SYN_SINGLE_LINKAGE"
    candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="01",
        text=(
            "For the single link or MIN version of hierarchical clustering, the proximity of two clusters is "
            "defined as the minimum of the distance between any two points in the two different clusters."
        ),
        score=23.0,
        classification="definition_support",
        positive_surface_type="anchored_descriptive_clause",
        has_name_anchor=True,
        title_overlap=2,
        seed_overlap=2,
        row_overrides={
            "quote_surface": (
                "For the single link or MIN version of hierarchical clustering, the proximity of two clusters is "
                "defined as the minimum of the distance between any two points in the two different clusters."
            ),
            "source_block_text": (
                "For the single link or MIN version of hierarchical clustering, the proximity of two clusters is "
                "defined as the minimum of the distance between any two points in the two different clusters. "
                "Using graph terminology, shortest links are merged first."
            ),
            "patch_heading": "Single Link or MIN",
            "is_definition_like": True,
            "is_procedure_like": True,
        },
    )

    value, normalized = _definition_draft_supported_single_span_fallback_value(
        field_name="definition_full_candidate",
        candidate=candidate,
        target_descriptor=_kc_descriptor(
            {
                "kc_id": kc_id,
                "canonical_name": "MIN (Single Linkage)",
                "aliases": ["Single Linkage"],
                "seed_definition": "A hierarchical clustering linkage in which cluster proximity is the minimum pairwise distance.",
            }
        ),
    )

    assert normalized is False
    assert value["selection_reason"] == "definition_full_candidate_draft_supported_single_span_fallback"
    assert value["source_text_field"] == "quote_surface"


def test_definition_draft_supported_single_span_fallback_value_demotes_name_led_history_surface_to_normalized():
    kc_id = "KC_SYN_KMEANS_HISTORY"
    candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="01",
        text="The K-means algorithm was named by MacQueen, although its history is more extensive.",
        score=22.0,
        classification="definition_support",
        positive_surface_type="anchored_descriptive_clause",
        has_name_anchor=True,
        title_overlap=2,
        seed_overlap=1,
        row_overrides={
            "quote_surface": "The K-means algorithm was named by MacQueen, although its history is more extensive.",
            "source_block_text": "The K-means algorithm was named by MacQueen, although its history is more extensive.",
            "patch_heading": "Bibliographic Notes",
            "is_definition_like": True,
            "is_procedure_like": True,
        },
    )

    value, normalized = _definition_draft_supported_single_span_fallback_value(
        field_name="definition_full_candidate",
        candidate=candidate,
        target_descriptor=_kc_descriptor(
            {
                "kc_id": kc_id,
                "canonical_name": "K-Means Algorithm",
                "aliases": ["K-means"],
                "seed_definition": "A partitioning algorithm that iteratively assigns points to centroids and recomputes centroids.",
            }
        ),
    )

    assert normalized is True
    assert value["selection_reason"] == "definition_full_candidate_source_faithful_fallback_surface_normalization"
    assert value["source_text_field"] == "quote_surface"


def test_definition_draft_supported_single_span_fallback_value_allows_name_led_standalone_quote_direct_without_explicit_relation():
    kc_id = "KC_SYN_FILTER_APPROACH"
    candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="01",
        text="The filter approach operates independently of the downstream learning method.",
        score=22.0,
        classification="definition_support",
        positive_surface_type="prose_definition",
        has_name_anchor=True,
        title_overlap=2,
        seed_overlap=1,
        row_overrides={
            "quote_surface": "The filter approach operates independently of the downstream learning method.",
            "source_block_text": (
                "The filter approach operates independently of the downstream learning method. "
                "It filters undesirable features before learning."
            ),
            "patch_heading": "Filter, Wrapper and Embedded Feature Selection",
            "is_definition_like": False,
            "is_procedure_like": False,
        },
    )

    value, normalized = _definition_draft_supported_single_span_fallback_value(
        field_name="definition_full_candidate",
        candidate=candidate,
        target_descriptor=_kc_descriptor(
            {
                "kc_id": kc_id,
                "canonical_name": "Filter Approach",
                "aliases": [],
                "seed_definition": "A feature-selection approach that evaluates features independently of the downstream learning method.",
            }
        ),
    )

    assert normalized is False
    assert value["selection_reason"] == "definition_full_candidate_draft_supported_single_span_fallback"
    assert value["source_text_field"] == "quote_surface"


def test_definition_draft_supported_single_span_fallback_salvage_value_prefers_same_kc_direct_alternative():
    kc_id = "KC_SYN_FALLBACK_SALVAGE_DIRECT"
    blocked_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="blocked",
        text="Because all the positive examples are classified correctly and the negative examples are misclassified, .TPR=FPR=1",
        score=24.0,
        classification="definition_support",
        positive_surface_type="prose_definition",
        row_overrides={
            "quote_surface": "Because all the positive examples are classified correctly and the negative examples are misclassified, .TPR=FPR=1",
            "source_block_text": (
                "2. Select the lowest ranked test instance. Assign the selected instance and those ranked above it "
                "to the positive class. Because all the positive examples are classified correctly and the negative "
                "examples are misclassified, .TPR=FPR=1"
            ),
            "patch_heading": "ROC Curve",
            "is_procedure_like": True,
        },
    )
    salvage_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="salvage",
        text=(
            "Specificity is the fraction of negative test instances correctly predicted by the classifier."
        ),
        score=19.0,
        classification="definition_support",
        positive_surface_type="prose_definition",
        row_overrides={
            "quote_surface": (
                "Specificity is the fraction of negative test instances correctly predicted by the classifier."
            ),
            "source_block_text": (
                "Specificity is the fraction of negative test instances correctly predicted by the classifier."
            ),
            "patch_heading": "",
            "is_procedure_like": False,
        },
    )

    value, normalized, picked = _definition_draft_supported_single_span_fallback_salvage_value(
        definition_candidates=[blocked_candidate, salvage_candidate],
        blocked_candidate=blocked_candidate,
        target_descriptor=_kc_descriptor(
            {
                "kc_id": kc_id,
                "canonical_name": "Specificity",
                "aliases": ["True Negative Rate"],
                "seed_definition": "The fraction of negative instances correctly classified.",
            }
        ),
    )

    assert picked == salvage_candidate
    assert normalized is False
    assert value["selection_reason"] == "definition_full_candidate_draft_supported_single_span_fallback_same_kc_salvage"
    assert value["text"] == "Specificity is the fraction of negative test instances correctly predicted by the classifier."
    assert value["supporting_overlay_candidate_ids"] == [salvage_candidate.overlay_candidate_id]


def test_definition_draft_supported_single_span_fallback_salvage_value_uses_normalized_same_kc_alternative():
    kc_id = "KC_SYN_FALLBACK_SALVAGE_NORMALIZED"
    blocked_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="blocked",
        text="c. Calculate the weighted misclassification rate of the child nodes. Would",
        score=26.0,
        classification="definition_support",
        positive_surface_type="prose_definition",
        row_overrides={
            "quote_surface": "Calculate the weighted misclassification rate of the child nodes.",
            "source_block_text": "c. Calculate the weighted misclassification rate of the child nodes. Would",
            "patch_heading": "Exercises",
            "is_procedure_like": True,
        },
        assessment_overrides={"question_like": True},
    )
    salvage_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="salvage",
        text=(
            "Analogously to TPR, the true negative rate (TNR) (also known as specificity) is defined as the fraction of negative test instances correctly"
        ),
        score=18.0,
        classification="weak_support",
        positive_surface_type="prose_definition",
        row_overrides={
            "quote_surface": (
                "Analogously to TPR, the true negative rate (TNR) (also known as specificity) is defined as the fraction of negative test instances correctly"
            ),
            "source_block_text": (
                "Analogously to TPR, the true negative rate (TNR) (also known as specificity) is defined as the fraction of negative test instances correctly"
            ),
            "patch_heading": "True negative rate",
            "is_procedure_like": False,
        },
        has_name_anchor=True,
        title_overlap=1,
        seed_overlap=4,
    )

    value, normalized, picked = _definition_draft_supported_single_span_fallback_salvage_value(
        definition_candidates=[blocked_candidate, salvage_candidate],
        blocked_candidate=blocked_candidate,
        target_descriptor=_kc_descriptor(
            {
                "kc_id": kc_id,
                "canonical_name": "Specificity",
                "aliases": ["True Negative Rate"],
                "seed_definition": "The fraction of negative instances correctly classified.",
            }
        ),
    )

    assert picked == salvage_candidate
    assert normalized is True
    assert value["selection_reason"] == "definition_full_candidate_source_faithful_fallback_surface_same_kc_salvage_normalization"
    assert value["supporting_overlay_candidate_ids"] == [salvage_candidate.overlay_candidate_id]


def test_definition_draft_supported_single_span_fallback_salvage_value_rejects_contextual_same_kc_row_without_definition_relation():
    kc_id = "KC_SYN_FALLBACK_SALVAGE_BLOCKED"
    blocked_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="blocked",
        text="Because all the positive examples are classified correctly and the negative examples are misclassified, .TPR=FPR=1",
        score=26.0,
        classification="definition_support",
        positive_surface_type="prose_definition",
        row_overrides={
            "quote_surface": "Because all the positive examples are classified correctly and the negative examples are misclassified, .TPR=FPR=1",
            "source_block_text": (
                "2. Select the lowest ranked test instance. Assign the selected instance and those ranked above it "
                "to the positive class. Because all the positive examples are classified correctly and the negative "
                "examples are misclassified, .TPR=FPR=1"
            ),
            "patch_heading": "ROC Curve",
            "is_procedure_like": True,
        },
    )
    salvage_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="salvage",
        text=(
            "Another approach, known as the separate class method is used by the CHAID algorithm, where the missing value is treated as a separate categorical value distinct from other values of the splitting attribute."
        ),
        score=19.0,
        classification="definition_support",
        positive_surface_type="anchored_descriptive_clause",
        row_overrides={
            "quote_surface": (
                "Another approach, known as the separate class method is used by the CHAID algorithm, where the missing value is treated as a separate categorical value distinct from other values of the splitting attribute."
            ),
            "source_block_text": (
                "Another approach, known as the separate class method is used by the CHAID algorithm, where the missing value is treated as a separate categorical value distinct from other values of the splitting attribute."
            ),
            "patch_heading": "Figure 3.16.",
            "is_procedure_like": True,
        },
        has_name_anchor=True,
        title_overlap=2,
        seed_overlap=2,
    )

    value, normalized, picked = _definition_draft_supported_single_span_fallback_salvage_value(
        definition_candidates=[blocked_candidate, salvage_candidate],
        blocked_candidate=blocked_candidate,
        target_descriptor=_kc_descriptor(
            {
                "kc_id": kc_id,
                "canonical_name": "Missing Value",
                "aliases": [],
                "seed_definition": "An attribute value that was not recorded or is unavailable in the dataset.",
            }
        ),
    )

    assert value == {}
    assert normalized is False
    assert picked is None


def test_definition_draft_supported_single_span_fallback_salvage_value_allows_broad_expository_same_kc_definition_direct():
    kc_id = "KC_SYN_FALLBACK_SALVAGE_CONTEXT_DIRECT"
    blocked_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="blocked",
        text="Because all the positive examples are classified correctly and the negative examples are misclassified, .TPR=FPR=1",
        score=26.0,
        classification="definition_support",
        positive_surface_type="prose_definition",
        row_overrides={
            "quote_surface": "Because all the positive examples are classified correctly and the negative examples are misclassified, .TPR=FPR=1",
            "source_block_text": (
                "2. Select the lowest ranked test instance. Assign the selected instance and those ranked above it "
                "to the positive class. Because all the positive examples are classified correctly and the negative "
                "examples are misclassified, .TPR=FPR=1"
            ),
            "patch_heading": "ROC Curve",
            "is_procedure_like": True,
        },
    )
    salvage_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="salvage",
        text=(
            "For the group average version of hierarchical clustering, the proximity of two clusters is defined as "
            "the average pairwise proximity among all pairs of points in the different clusters."
        ),
        score=19.0,
        classification="context_support",
        positive_surface_type="prose_definition",
        row_overrides={
            "quote_surface": (
                "For the group average version of hierarchical clustering, the proximity of two clusters is defined as "
                "the average pairwise proximity among all pairs of points in the different clusters."
            ),
            "source_block_text": (
                "For the group average version of hierarchical clustering, the proximity of two clusters is defined as "
                "the average pairwise proximity among all pairs of points in the different clusters."
            ),
            "patch_heading": "Complete link clustering of the six points shown in Figure 7.15 .",
            "is_definition_like": True,
        },
        title_overlap=2,
        seed_overlap=5,
    )

    value, normalized, picked = _definition_draft_supported_single_span_fallback_salvage_value(
        definition_candidates=[blocked_candidate, salvage_candidate],
        blocked_candidate=blocked_candidate,
        target_descriptor=_kc_descriptor(
            {
                "kc_id": kc_id,
                "canonical_name": "Group Average Linkage",
                "aliases": [],
                "seed_definition": (
                    "The proximity between two clusters defined as the average pairwise proximity between points in the clusters."
                ),
            }
        ),
    )

    assert picked == salvage_candidate
    assert normalized is False
    assert value["selection_reason"] == "definition_full_candidate_draft_supported_single_span_fallback_same_kc_salvage"
    assert value["supporting_overlay_candidate_ids"] == [salvage_candidate.overlay_candidate_id]


def test_definition_draft_supported_single_span_fallback_salvage_value_allows_tail_trimmed_same_kc_direct():
    kc_id = "KC_SYN_FALLBACK_SALVAGE_TAIL_TRIM_DIRECT"
    blocked_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="blocked",
        text="Because all the positive examples are classified correctly and the negative examples are misclassified, .TPR=FPR=1",
        score=26.0,
        classification="definition_support",
        positive_surface_type="prose_definition",
        row_overrides={
            "quote_surface": "Because all the positive examples are classified correctly and the negative examples are misclassified, .TPR=FPR=1",
            "source_block_text": (
                "2. Select the lowest ranked test instance. Assign the selected instance and those ranked above it "
                "to the positive class. Because all the positive examples are classified correctly and the negative "
                "examples are misclassified, .TPR=FPR=1"
            ),
            "patch_heading": "ROC Curve",
            "is_procedure_like": True,
        },
    )
    salvage_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="salvage",
        text=(
            "Analogously to TPR, the true negative rate (TNR) (also known as specificity) is defined as the fraction "
            "of negative test instances correctly predicted by the classifier, i.e.,"
        ),
        score=19.0,
        classification="weak_support",
        positive_surface_type="",
        row_overrides={
            "quote_surface": (
                "Analogously to TPR, the true negative rate (TNR) (also known as specificity) is defined as the fraction "
                "of negative test instances correctly predicted by the classifier, i.e.,"
            ),
            "source_block_text": (
                "Analogously to TPR, the true negative rate (TNR) (also known as specificity) is defined as the fraction "
                "of negative test instances correctly predicted by the classifier, i.e.,"
            ),
            "patch_heading": "",
            "is_definition_like": True,
        },
        has_name_anchor=True,
        title_overlap=1,
        seed_overlap=4,
    )

    value, normalized, picked = _definition_draft_supported_single_span_fallback_salvage_value(
        definition_candidates=[blocked_candidate, salvage_candidate],
        blocked_candidate=blocked_candidate,
        target_descriptor=_kc_descriptor(
            {
                "kc_id": kc_id,
                "canonical_name": "Specificity",
                "aliases": ["True Negative Rate"],
                "seed_definition": "The fraction of negative test instances correctly predicted by the classifier.",
            }
        ),
    )

    assert picked == salvage_candidate
    assert normalized is False
    assert value["selection_reason"] == "definition_full_candidate_draft_supported_single_span_fallback_same_kc_salvage"
    assert value["text"] == (
        "Analogously to TPR, the true negative rate (TNR) (also known as specificity) is defined as the fraction "
        "of negative test instances correctly predicted by the classifier."
    )


def test_definition_draft_supported_single_span_fallback_salvage_value_blocks_weakly_aligned_formula_row():
    kc_id = "KC_SYN_FALLBACK_SALVAGE_FORMULA_BLOCKED"
    blocked_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="blocked",
        text="Because all the positive examples are classified correctly and the negative examples are misclassified, .TPR=FPR=1",
        score=26.0,
        classification="definition_support",
        positive_surface_type="prose_definition",
        row_overrides={
            "quote_surface": "Because all the positive examples are classified correctly and the negative examples are misclassified, .TPR=FPR=1",
            "source_block_text": (
                "2. Select the lowest ranked test instance. Assign the selected instance and those ranked above it "
                "to the positive class. Because all the positive examples are classified correctly and the negative "
                "examples are misclassified, .TPR=FPR=1"
            ),
            "patch_heading": "ROC Curve",
            "is_procedure_like": True,
        },
    )
    salvage_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="salvage",
        text="For example, if A = {1, 2, 3, 4} and B = {2, 3, 4}, then A - B = {1}.",
        score=19.0,
        classification="equation_support",
        positive_surface_type="",
        row_overrides={
            "quote_surface": "For example, if A = {1, 2, 3, 4} and B = {2, 3, 4}, then A - B = {1}.",
            "source_block_text": "For example, if A = {1, 2, 3, 4} and B = {2, 3, 4}, then A - B = {1}.",
            "patch_heading": "Set Difference",
            "is_definition_like": True,
        },
        has_name_anchor=False,
        title_overlap=0,
        seed_overlap=0,
    )

    value, normalized, picked = _definition_draft_supported_single_span_fallback_salvage_value(
        definition_candidates=[blocked_candidate, salvage_candidate],
        blocked_candidate=blocked_candidate,
        target_descriptor=_kc_descriptor(
            {
                "kc_id": kc_id,
                "canonical_name": "Sequential Backward Generation",
                "aliases": ["SBG"],
                "seed_definition": "A feature selection search direction that starts from all features and removes one at a time.",
            }
        ),
    )

    assert value == {}
    assert normalized is False
    assert picked is None


def test_definition_draft_supported_single_span_fallback_salvage_value_uses_same_kc_local_row_when_definition_pool_is_narrow():
    kc_id = "KC_SYN_FALLBACK_SALVAGE_LOCAL_ROW"
    blocked_row = _synthetic_overlay_row(
        kc_id=kc_id,
        canonical_name="Specificity",
        suffix="01",
        text="Because all the positive examples are classified correctly and the negative examples are misclassified, .TPR=FPR=1",
        topic_path_labels=["Synthetic Domain", "Synthetic Branch"],
    )
    blocked_row["quote_surface"] = blocked_row["source_block_text"]
    blocked_row["patch_heading"] = "ROC Curve"
    blocked_row["is_procedure_like"] = True
    salvage_row = _synthetic_overlay_row(
        kc_id=kc_id,
        canonical_name="Specificity",
        suffix="02",
        text="Specificity is the fraction of negative test instances correctly predicted by the classifier.",
        topic_path_labels=["Synthetic Domain", "Synthetic Branch"],
    )
    salvage_row["quote_surface"] = "Specificity is the fraction of negative test instances correctly predicted by the classifier."
    salvage_row["source_block_text"] = "Specificity is the fraction of negative test instances correctly predicted by the classifier."
    salvage_row["is_definition_like"] = True

    blocked_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="blocked",
        text=blocked_row["quote_surface"],
        score=26.0,
        classification="definition_support",
        positive_surface_type="prose_definition",
        row_overrides=dict(blocked_row),
    )

    value, normalized, picked = _definition_draft_supported_single_span_fallback_salvage_value(
        definition_candidates=[blocked_candidate],
        blocked_candidate=blocked_candidate,
        target_descriptor=_kc_descriptor(
            {
                "kc_id": kc_id,
                "canonical_name": "Specificity",
                "aliases": ["True Negative Rate"],
                "seed_definition": "The fraction of negative instances correctly classified.",
            }
        ),
        local_rows=[blocked_row, salvage_row],
        assessments_by_id={},
    )

    assert normalized is False
    assert value["selection_reason"] == "definition_full_candidate_draft_supported_single_span_fallback_same_kc_salvage"
    assert value["text"] == salvage_row["quote_surface"]
    assert picked is not None
    assert picked.overlay_candidate_id == salvage_row["overlay_candidate_id"]


def test_build_kc_draft_bundles_llm_applies_draft_supported_single_span_fallback_after_verify_abstention(monkeypatch):
    kc_id = "KC_SYN_CONTROL_RESTORE"
    canonical_name = "Control Restore"
    rows = [
        _synthetic_overlay_row(
            kc_id=kc_id,
            canonical_name=canonical_name,
            suffix="01",
            text="Control Restore is the exact local support row.",
            topic_path_labels=["Synthetic Domain", "Synthetic Branch"],
        ),
        _synthetic_overlay_row(
            kc_id=kc_id,
            canonical_name=canonical_name,
            suffix="02",
            text="Control Restore applies when every verify path abstains.",
            topic_path_labels=["Synthetic Domain", "Synthetic Branch"],
        ),
    ]
    fallback_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="01",
        text="Control Restore is the exact local support row.",
        score=25.0,
        classification="definition_support",
        positive_surface_type="prose_definition",
    )

    monkeypatch.setattr(drafting_module, "_definition_candidates", lambda *args, support_pack=None, **kwargs: [fallback_candidate])
    monkeypatch.setattr(drafting_module, "select_definition_support_pack", lambda *args, **kwargs: [])
    monkeypatch.setattr(drafting_module, "_scope_candidates", lambda *args, **kwargs: [])
    monkeypatch.setattr(drafting_module, "_definition_rescue_candidates", lambda candidates, *, limit: list(candidates)[:limit])
    monkeypatch.setattr(drafting_module, "_definition_context_completion_candidate", lambda *args, **kwargs: {})
    monkeypatch.setattr(drafting_module, "_definition_single_span_fallback_candidate", lambda *args, **kwargs: None)
    monkeypatch.setattr(drafting_module, "_source_faithful_normalized_definition_candidate", lambda *args, **kwargs: {})

    phase_log: list[str] = []

    def draft_invoker(request: dict[str, object]):
        phase = str(request["phase"])
        phase_log.append(phase)
        label = next(iter(dict(request["request_payload"]).get("label_to_overlay_candidate_id", {})))
        return {
            "definition": {
                "status": "grounded",
                "text": "Drafted paraphrase that verify will abstain on.",
                "supporting_evidence_labels": [label],
                "abstention_reason": "",
            },
            "scope": {
                "status": "abstained",
                "text": "",
                "supporting_evidence_labels": [],
                "abstention_reason": "scope_gap",
            },
        }, {"source": f"test_{phase}"}

    def verify_invoker(request: dict[str, object]):
        phase = str(request["phase"])
        phase_log.append(phase)
        return {
            "definition": {
                "status": "abstained",
                "text": "",
                "supporting_evidence_labels": [],
                "abstention_reason": "unsupported paraphrase",
            },
            "scope": {
                "status": "abstained",
                "text": "",
                "supporting_evidence_labels": [],
                "abstention_reason": "scope_gap",
            },
        }, {"source": f"test_{phase}"}

    bundles, stats = build_kc_draft_bundles_llm(
        rows,
        runtime=Step67ModelRuntime(
            base_url="http://unit.test",
            model="synthetic-model",
            draft_invoker=draft_invoker,
            verify_invoker=verify_invoker,
        ),
        policy=Step67DraftingPolicy(max_llm_calls_per_kc=8),
    )

    bundle = bundles[0]
    llm_diag = bundle["selection_diagnostics"]["llm_drafting"]
    grounding_diag = bundle["selection_diagnostics"]["definition_grounding_diagnostics"]

    assert bundle["definition_full_candidate"]["text"] == fallback_candidate.text
    assert bundle["definition_full_candidate"]["selection_reason"] == "definition_full_candidate_draft_supported_single_span_fallback"
    assert grounding_diag["control_fallback_candidate_present"] is True
    assert grounding_diag["control_fallback_applied"] is True
    assert grounding_diag["control_fallback_source_phase"] == "preservation_draft_response"
    assert grounding_diag["draft_supported_single_span_fallback_candidate_present"] is True
    assert grounding_diag["draft_supported_single_span_fallback_source_phase"] == "preservation_draft_response"
    assert grounding_diag["draft_supported_single_span_fallback_support_ids"] == [fallback_candidate.overlay_candidate_id]
    assert grounding_diag["draft_supported_single_span_fallback_applied"] is True
    assert grounding_diag["collapse_stage"] == "control_fallback_applied"
    assert llm_diag["draft_supported_single_span_fallback_applied"] is True
    assert llm_diag["legacy_definition_redraft_allowed"] is True
    assert stats["definition_draft_supported_single_span_fallback_recoveries"] == 1
    assert phase_log == ["draft", "verify", "draft", "verify", "definition_redraft", "definition_verify"]


def test_build_kc_draft_bundles_llm_demotes_discourse_led_control_fallback_to_normalized(monkeypatch):
    kc_id = "KC_SYN_CONTROL_NORMALIZED"
    canonical_name = "Node Impurity"
    row = _synthetic_overlay_row(
        kc_id=kc_id,
        canonical_name=canonical_name,
        suffix="01",
        text=(
            "In the following, we present different ways of measuring the impurity of a node and the "
            "collective impurity of its child nodes, both of which will be used to identify the best "
            "attribute test condition for a node."
        ),
        topic_path_labels=["Synthetic Domain", "Synthetic Branch"],
    )
    row["quote_surface"] = row["source_block_text"]
    row["patch_heading"] = "Impurity Measure for a Single Node"
    rows = [row]
    fallback_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="01",
        text=str(row["source_block_text"]),
        score=25.0,
        classification="definition_support",
        positive_surface_type="prose_definition",
        row_overrides=dict(row),
    )

    monkeypatch.setattr(drafting_module, "_definition_candidates", lambda *args, support_pack=None, **kwargs: [fallback_candidate])
    monkeypatch.setattr(drafting_module, "select_definition_support_pack", lambda *args, **kwargs: [])
    monkeypatch.setattr(drafting_module, "_scope_candidates", lambda *args, **kwargs: [])
    monkeypatch.setattr(drafting_module, "_definition_rescue_candidates", lambda candidates, *, limit: list(candidates)[:limit])
    monkeypatch.setattr(drafting_module, "_definition_context_completion_candidate", lambda *args, **kwargs: {})
    monkeypatch.setattr(drafting_module, "_definition_single_span_fallback_candidate", lambda *args, **kwargs: None)
    monkeypatch.setattr(drafting_module, "_source_faithful_normalized_definition_candidate", lambda *args, **kwargs: {})

    def draft_invoker(request: dict[str, object]):
        label = next(iter(dict(request["request_payload"]).get("label_to_overlay_candidate_id", {})))
        return {
            "definition": {
                "status": "grounded",
                "text": "Drafted paraphrase that verify will abstain on.",
                "supporting_evidence_labels": [label],
                "abstention_reason": "",
            },
            "scope": {
                "status": "abstained",
                "text": "",
                "supporting_evidence_labels": [],
                "abstention_reason": "scope_gap",
            },
        }, {"source": "test"}

    def verify_invoker(request: dict[str, object]):
        return {
            "definition": {
                "status": "abstained",
                "text": "",
                "supporting_evidence_labels": [],
                "abstention_reason": "unsupported paraphrase",
            },
            "scope": {
                "status": "abstained",
                "text": "",
                "supporting_evidence_labels": [],
                "abstention_reason": "scope_gap",
            },
        }, {"source": "test"}

    bundles, stats = build_kc_draft_bundles_llm(
        rows,
        runtime=Step67ModelRuntime(
            base_url="http://unit.test",
            model="synthetic-model",
            draft_invoker=draft_invoker,
            verify_invoker=verify_invoker,
        ),
        policy=Step67DraftingPolicy(max_llm_calls_per_kc=8),
    )

    bundle = bundles[0]
    grounding_diag = bundle["selection_diagnostics"]["definition_grounding_diagnostics"]

    assert bundle["authoritative_definition_status"] == AUTHORITATIVE_DEFINITION_STATUS_NORMALIZED_GROUNDED
    assert bundle["definition_full_candidate"]["selection_reason"] == "definition_full_candidate_source_faithful_fallback_surface_normalization"
    assert grounding_diag["draft_supported_single_span_fallback_applied"] is True
    assert grounding_diag["draft_supported_single_span_fallback_normalized_applied"] is True
    assert grounding_diag["collapse_stage"] == "control_fallback_surface_normalization_applied"
    assert stats["definition_source_faithful_normalization_recoveries"] == 1
    assert stats["definition_draft_supported_single_span_fallback_recoveries"] == 0


def test_build_kc_draft_bundles_llm_applies_same_kc_salvage_after_blocked_control_fallback(monkeypatch):
    kc_id = "KC_SYN_CONTROL_SALVAGE"
    canonical_name = "Specificity"
    blocked_row = _synthetic_overlay_row(
        kc_id=kc_id,
        canonical_name=canonical_name,
        suffix="01",
        text="Because all the positive examples are classified correctly and the negative examples are misclassified, .TPR=FPR=1",
        topic_path_labels=["Synthetic Domain", "Synthetic Branch"],
    )
    blocked_row["quote_surface"] = "Because all the positive examples are classified correctly and the negative examples are misclassified, .TPR=FPR=1"
    blocked_row["source_block_text"] = (
        "2. Select the lowest ranked test instance. Assign the selected instance and those ranked above it to the "
        "positive class. Because all the positive examples are classified correctly and the negative examples are "
        "misclassified, .TPR=FPR=1"
    )
    blocked_row["patch_heading"] = "ROC Curve"
    blocked_row["is_procedure_like"] = True
    salvage_row = _synthetic_overlay_row(
        kc_id=kc_id,
        canonical_name=canonical_name,
        suffix="02",
        text="Specificity is the fraction of negative test instances correctly predicted by the classifier.",
        topic_path_labels=["Synthetic Domain", "Synthetic Branch"],
    )
    salvage_row["quote_surface"] = "Specificity is the fraction of negative test instances correctly predicted by the classifier."
    salvage_row["source_block_text"] = "Specificity is the fraction of negative test instances correctly predicted by the classifier."
    rows = [blocked_row, salvage_row]

    blocked_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="01",
        text=blocked_row["quote_surface"],
        score=25.0,
        classification="definition_support",
        positive_surface_type="prose_definition",
        row_overrides=dict(blocked_row),
    )
    salvage_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="02",
        text=salvage_row["quote_surface"],
        score=19.0,
        classification="definition_support",
        positive_surface_type="prose_definition",
        row_overrides=dict(salvage_row),
    )

    monkeypatch.setattr(drafting_module, "_definition_candidates", lambda *args, support_pack=None, **kwargs: [blocked_candidate, salvage_candidate])
    monkeypatch.setattr(drafting_module, "select_definition_support_pack", lambda *args, **kwargs: [])
    monkeypatch.setattr(drafting_module, "_scope_candidates", lambda *args, **kwargs: [])
    monkeypatch.setattr(drafting_module, "_definition_rescue_candidates", lambda candidates, *, limit: list(candidates)[:limit])
    monkeypatch.setattr(drafting_module, "_definition_context_completion_candidate", lambda *args, **kwargs: {})
    monkeypatch.setattr(drafting_module, "_definition_single_span_fallback_candidate", lambda *args, **kwargs: None)
    monkeypatch.setattr(drafting_module, "_source_faithful_normalized_definition_candidate", lambda *args, **kwargs: {})

    def draft_invoker(request: dict[str, object]):
        label = next(iter(dict(request["request_payload"]).get("label_to_overlay_candidate_id", {})))
        return {
            "definition": {
                "status": "grounded",
                "text": "Drafted paraphrase that verify will abstain on.",
                "supporting_evidence_labels": [label],
                "abstention_reason": "",
            },
            "scope": {
                "status": "abstained",
                "text": "",
                "supporting_evidence_labels": [],
                "abstention_reason": "scope_gap",
            },
        }, {"source": "test"}

    def verify_invoker(request: dict[str, object]):
        return {
            "definition": {
                "status": "abstained",
                "text": "",
                "supporting_evidence_labels": [],
                "abstention_reason": "unsupported paraphrase",
            },
            "scope": {
                "status": "abstained",
                "text": "",
                "supporting_evidence_labels": [],
                "abstention_reason": "scope_gap",
            },
        }, {"source": "test"}

    bundles, stats = build_kc_draft_bundles_llm(
        rows,
        runtime=Step67ModelRuntime(
            base_url="http://unit.test",
            model="synthetic-model",
            draft_invoker=draft_invoker,
            verify_invoker=verify_invoker,
        ),
        policy=Step67DraftingPolicy(max_llm_calls_per_kc=8),
    )

    bundle = bundles[0]
    grounding_diag = bundle["selection_diagnostics"]["definition_grounding_diagnostics"]

    assert bundle["authoritative_definition_status"] == AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED
    assert bundle["definition_full_candidate"]["text"] == salvage_candidate.text
    assert bundle["definition_full_candidate"]["selection_reason"] == "definition_full_candidate_draft_supported_single_span_fallback_same_kc_salvage"
    assert grounding_diag["draft_supported_single_span_fallback_candidate_present"] is True
    assert grounding_diag["draft_supported_single_span_fallback_applied"] is True
    assert grounding_diag["draft_supported_single_span_fallback_salvage_candidate_present"] is True
    assert grounding_diag["draft_supported_single_span_fallback_salvage_support_ids"] == [salvage_candidate.overlay_candidate_id]
    assert grounding_diag["draft_supported_single_span_fallback_salvage_applied"] is True
    assert grounding_diag["collapse_stage"] == "control_fallback_same_kc_salvage_applied"
    assert stats["definition_draft_supported_single_span_fallback_recoveries"] == 1
    assert stats["definition_source_faithful_normalization_recoveries"] == 0


def test_build_kc_draft_bundles_llm_applies_same_kc_salvage_from_local_row_after_blocked_control_fallback(monkeypatch):
    kc_id = "KC_SYN_CONTROL_SALVAGE_LOCAL_ROW"
    canonical_name = "Specificity"
    blocked_row = _synthetic_overlay_row(
        kc_id=kc_id,
        canonical_name=canonical_name,
        suffix="01",
        text="Because all the positive examples are classified correctly and the negative examples are misclassified, .TPR=FPR=1",
        topic_path_labels=["Synthetic Domain", "Synthetic Branch"],
    )
    blocked_row["quote_surface"] = "Because all the positive examples are classified correctly and the negative examples are misclassified, .TPR=FPR=1"
    blocked_row["source_block_text"] = (
        "2. Select the lowest ranked test instance. Assign the selected instance and those ranked above it to the "
        "positive class. Because all the positive examples are classified correctly and the negative examples are "
        "misclassified, .TPR=FPR=1"
    )
    blocked_row["patch_heading"] = "ROC Curve"
    blocked_row["is_procedure_like"] = True
    salvage_row = _synthetic_overlay_row(
        kc_id=kc_id,
        canonical_name=canonical_name,
        suffix="02",
        text="Specificity is the fraction of negative test instances correctly predicted by the classifier.",
        topic_path_labels=["Synthetic Domain", "Synthetic Branch"],
    )
    salvage_row["quote_surface"] = "Specificity is the fraction of negative test instances correctly predicted by the classifier."
    salvage_row["source_block_text"] = "Specificity is the fraction of negative test instances correctly predicted by the classifier."
    rows = [blocked_row, salvage_row]

    blocked_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="01",
        text=blocked_row["quote_surface"],
        score=25.0,
        classification="definition_support",
        positive_surface_type="prose_definition",
        row_overrides=dict(blocked_row),
    )

    monkeypatch.setattr(drafting_module, "_definition_candidates", lambda *args, support_pack=None, **kwargs: [blocked_candidate])
    monkeypatch.setattr(drafting_module, "select_definition_support_pack", lambda *args, **kwargs: [])
    monkeypatch.setattr(drafting_module, "_scope_candidates", lambda *args, **kwargs: [])
    monkeypatch.setattr(drafting_module, "_definition_rescue_candidates", lambda candidates, *, limit: list(candidates)[:limit])
    monkeypatch.setattr(drafting_module, "_definition_context_completion_candidate", lambda *args, **kwargs: {})
    monkeypatch.setattr(drafting_module, "_definition_single_span_fallback_candidate", lambda *args, **kwargs: None)
    monkeypatch.setattr(drafting_module, "_source_faithful_normalized_definition_candidate", lambda *args, **kwargs: {})

    def draft_invoker(request: dict[str, object]):
        label = next(iter(dict(request["request_payload"]).get("label_to_overlay_candidate_id", {})))
        return {
            "definition": {
                "status": "grounded",
                "text": "Drafted paraphrase that verify will abstain on.",
                "supporting_evidence_labels": [label],
                "abstention_reason": "",
            },
            "scope": {
                "status": "abstained",
                "text": "",
                "supporting_evidence_labels": [],
                "abstention_reason": "scope_gap",
            },
        }, {"source": "test"}

    def verify_invoker(request: dict[str, object]):
        return {
            "definition": {
                "status": "abstained",
                "text": "",
                "supporting_evidence_labels": [],
                "abstention_reason": "unsupported paraphrase",
            },
            "scope": {
                "status": "abstained",
                "text": "",
                "supporting_evidence_labels": [],
                "abstention_reason": "scope_gap",
            },
        }, {"source": "test"}

    bundles, stats = build_kc_draft_bundles_llm(
        rows,
        runtime=Step67ModelRuntime(
            base_url="http://unit.test",
            model="synthetic-model",
            draft_invoker=draft_invoker,
            verify_invoker=verify_invoker,
        ),
        policy=Step67DraftingPolicy(max_llm_calls_per_kc=8),
    )

    bundle = bundles[0]
    grounding_diag = bundle["selection_diagnostics"]["definition_grounding_diagnostics"]

    assert bundle["authoritative_definition_status"] == AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED
    assert bundle["definition_full_candidate"]["text"] == salvage_row["quote_surface"]
    assert bundle["definition_full_candidate"]["selection_reason"] == "definition_full_candidate_draft_supported_single_span_fallback_same_kc_salvage"
    assert grounding_diag["draft_supported_single_span_fallback_candidate_present"] is True
    assert grounding_diag["draft_supported_single_span_fallback_salvage_candidate_present"] is True
    assert grounding_diag["draft_supported_single_span_fallback_salvage_applied"] is True
    assert grounding_diag["draft_supported_single_span_fallback_salvage_support_ids"] == [salvage_row["overlay_candidate_id"]]
    assert grounding_diag["collapse_stage"] == "control_fallback_same_kc_salvage_applied"
    assert stats["definition_draft_supported_single_span_fallback_recoveries"] == 1
    assert stats["definition_source_faithful_normalization_recoveries"] == 0


def test_build_kc_draft_bundles_llm_applies_tail_trimmed_same_kc_salvage_direct_after_blocked_control_fallback(monkeypatch):
    kc_id = "KC_SYN_CONTROL_SALVAGE_TAIL_TRIM"
    canonical_name = "Specificity"
    blocked_row = _synthetic_overlay_row(
        kc_id=kc_id,
        canonical_name=canonical_name,
        suffix="01",
        text="Because all the positive examples are classified correctly and the negative examples are misclassified, .TPR=FPR=1",
        topic_path_labels=["Synthetic Domain", "Synthetic Branch"],
    )
    blocked_row["quote_surface"] = "Because all the positive examples are classified correctly and the negative examples are misclassified, .TPR=FPR=1"
    blocked_row["source_block_text"] = (
        "2. Select the lowest ranked test instance. Assign the selected instance and those ranked above it to the "
        "positive class. Because all the positive examples are classified correctly and the negative examples are "
        "misclassified, .TPR=FPR=1"
    )
    blocked_row["patch_heading"] = "ROC Curve"
    blocked_row["is_procedure_like"] = True
    salvage_row = _synthetic_overlay_row(
        kc_id=kc_id,
        canonical_name=canonical_name,
        suffix="02",
        text=(
            "Analogously to TPR, the true negative rate (TNR) (also known as specificity) is defined as the fraction "
            "of negative test instances correctly predicted by the classifier, i.e.,"
        ),
        topic_path_labels=["Synthetic Domain", "Synthetic Branch"],
    )
    salvage_row["quote_surface"] = (
        "Analogously to TPR, the true negative rate (TNR) (also known as specificity) is defined as the fraction "
        "of negative test instances correctly predicted by the classifier, i.e.,"
    )
    salvage_row["source_block_text"] = salvage_row["quote_surface"]
    salvage_row["is_definition_like"] = True
    rows = [blocked_row, salvage_row]

    blocked_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="01",
        text=blocked_row["quote_surface"],
        score=25.0,
        classification="definition_support",
        positive_surface_type="prose_definition",
        row_overrides=dict(blocked_row),
    )

    monkeypatch.setattr(drafting_module, "_definition_candidates", lambda *args, support_pack=None, **kwargs: [blocked_candidate])
    monkeypatch.setattr(drafting_module, "select_definition_support_pack", lambda *args, **kwargs: [])
    monkeypatch.setattr(drafting_module, "_scope_candidates", lambda *args, **kwargs: [])
    monkeypatch.setattr(drafting_module, "_definition_rescue_candidates", lambda candidates, *, limit: list(candidates)[:limit])
    monkeypatch.setattr(drafting_module, "_definition_context_completion_candidate", lambda *args, **kwargs: {})
    monkeypatch.setattr(drafting_module, "_definition_single_span_fallback_candidate", lambda *args, **kwargs: None)
    monkeypatch.setattr(drafting_module, "_source_faithful_normalized_definition_candidate", lambda *args, **kwargs: {})

    def draft_invoker(request: dict[str, object]):
        label = next(iter(dict(request["request_payload"]).get("label_to_overlay_candidate_id", {})))
        return {
            "definition": {
                "status": "grounded",
                "text": "Drafted paraphrase that verify will abstain on.",
                "supporting_evidence_labels": [label],
                "abstention_reason": "",
            },
            "scope": {
                "status": "abstained",
                "text": "",
                "supporting_evidence_labels": [],
                "abstention_reason": "scope_gap",
            },
        }, {"source": "test"}

    def verify_invoker(request: dict[str, object]):
        return {
            "definition": {
                "status": "abstained",
                "text": "",
                "supporting_evidence_labels": [],
                "abstention_reason": "unsupported paraphrase",
            },
            "scope": {
                "status": "abstained",
                "text": "",
                "supporting_evidence_labels": [],
                "abstention_reason": "scope_gap",
            },
        }, {"source": "test"}

    bundles, stats = build_kc_draft_bundles_llm(
        rows,
        runtime=Step67ModelRuntime(
            base_url="http://unit.test",
            model="synthetic-model",
            draft_invoker=draft_invoker,
            verify_invoker=verify_invoker,
        ),
        policy=Step67DraftingPolicy(max_llm_calls_per_kc=8),
    )

    bundle = bundles[0]
    grounding_diag = bundle["selection_diagnostics"]["definition_grounding_diagnostics"]

    assert bundle["authoritative_definition_status"] == AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED
    assert bundle["definition_full_candidate"]["selection_reason"] == "definition_full_candidate_draft_supported_single_span_fallback_same_kc_salvage"
    assert bundle["definition_full_candidate"]["text"] == (
        "Analogously to TPR, the true negative rate (TNR) (also known as specificity) is defined as the fraction "
        "of negative test instances correctly predicted by the classifier."
    )
    assert grounding_diag["draft_supported_single_span_fallback_salvage_candidate_present"] is True
    assert grounding_diag["draft_supported_single_span_fallback_salvage_applied"] is True
    assert grounding_diag["draft_supported_single_span_fallback_salvage_support_ids"] == [salvage_row["overlay_candidate_id"]]
    assert grounding_diag["collapse_stage"] == "control_fallback_same_kc_salvage_applied"
    assert stats["definition_draft_supported_single_span_fallback_recoveries"] == 1


def test_build_kc_draft_bundles_llm_rescue_success_short_circuits_legacy_redraft(monkeypatch):
    kc_id = "KC_SYN_MONO_RESCUE"
    canonical_name = "Boundary Recall"
    rows = [
        _synthetic_overlay_row(
            kc_id=kc_id,
            canonical_name=canonical_name,
            suffix="01",
            text="Boundary Recall is",
            topic_path_labels=["Synthetic Domain", "Synthetic Branch"],
        ),
        _synthetic_overlay_row(
            kc_id=kc_id,
            canonical_name=canonical_name,
            suffix="02",
            text="the proportion of relevant boundary cases retrieved.",
            topic_path_labels=["Synthetic Domain", "Synthetic Branch"],
        ),
        _synthetic_overlay_row(
            kc_id=kc_id,
            canonical_name=canonical_name,
            suffix="03",
            text="Boundary Recall applies when boundary cases are explicitly evaluated.",
            topic_path_labels=["Synthetic Domain", "Synthetic Branch"],
        ),
    ]
    preservation_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="01",
        text="Boundary Recall is",
        score=12.0,
        classification="definition_support",
        positive_surface_type="fragment",
        single_span_accepted=False,
    )
    rescue_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="02",
        text="Boundary Recall is the proportion of relevant boundary cases retrieved.",
        score=21.0,
        classification="definition_support",
        positive_surface_type="prose_definition",
    )
    scope_candidates = [
        _synthetic_scope_candidate(
            kc_id=kc_id,
            overlay_suffix="03",
            text="Boundary Recall applies when boundary cases are explicitly evaluated.",
        )
    ]

    monkeypatch.setattr(
        drafting_module,
        "_definition_candidates",
        lambda *args, support_pack=None, **kwargs: [rescue_candidate] if support_pack else [preservation_candidate],
    )
    monkeypatch.setattr(
        drafting_module,
        "select_definition_support_pack",
        lambda *args, **kwargs: [{"overlay_candidate_id": f"{kc_id}:overlay:02"}],
    )
    monkeypatch.setattr(drafting_module, "_scope_candidates", lambda *args, **kwargs: list(scope_candidates))
    monkeypatch.setattr(drafting_module, "_definition_rescue_candidates", lambda candidates, *, limit: list(candidates)[:limit])

    phase_log: list[str] = []
    state = {"draft_calls": 0, "verify_calls": 0}

    def draft_invoker(request: dict[str, object]):
        phase = str(request["phase"])
        phase_log.append(phase)
        assert phase == "draft"
        state["draft_calls"] += 1
        label = next(iter(dict(request["request_payload"]).get("label_to_overlay_candidate_id", {})))
        if state["draft_calls"] == 1:
            return {
                "definition": {
                    "status": "abstained",
                    "text": "",
                    "supporting_evidence_labels": [],
                    "abstention_reason": "insufficient_evidence",
                },
                "scope": {
                    "status": "abstained",
                    "text": "",
                    "supporting_evidence_labels": [],
                    "abstention_reason": "scope_gap",
                },
            }, {"source": "test_preservation_abstain"}
        assert state["draft_calls"] == 2
        return {
            "definition": {
                "status": "grounded",
                "text": rescue_candidate.text,
                "supporting_evidence_labels": [label],
                "abstention_reason": "",
            },
            "scope": {
                "status": "abstained",
                "text": "",
                "supporting_evidence_labels": [],
                "abstention_reason": "scope_gap",
            },
        }, {"source": "test_rescue"}

    def verify_invoker(request: dict[str, object]):
        phase = str(request["phase"])
        phase_log.append(phase)
        assert phase == "verify"
        state["verify_calls"] += 1
        evidence_labels = list(dict(request["request_payload"]).get("evidence_lookup", {}).keys())
        if state["verify_calls"] == 1:
            return {
                "definition": {
                    "status": "abstained",
                    "text": "",
                    "supporting_evidence_labels": [],
                    "abstention_reason": "insufficient_evidence",
                },
                "scope": {
                    "status": "abstained",
                    "text": "",
                    "supporting_evidence_labels": [],
                    "abstention_reason": "scope_gap",
                },
            }, {"source": "test_preservation_abstain"}
        assert state["verify_calls"] == 2
        return {
            "definition": {
                "status": "grounded",
                "text": rescue_candidate.text,
                "supporting_evidence_labels": evidence_labels[:1],
                "abstention_reason": "",
            },
            "scope": {
                "status": "abstained",
                "text": "",
                "supporting_evidence_labels": [],
                "abstention_reason": "scope_gap",
            },
        }, {"source": "test_rescue"}

    bundles, _ = build_kc_draft_bundles_llm(
        rows,
        runtime=Step67ModelRuntime(
            base_url="http://unit.test",
            model="synthetic-model",
            draft_invoker=draft_invoker,
            verify_invoker=verify_invoker,
        ),
        policy=Step67DraftingPolicy(max_llm_calls_per_kc=8),
    )

    bundle = bundles[0]
    llm_diag = bundle["selection_diagnostics"]["llm_drafting"]

    assert bundle["definition_full_candidate"]["text"] == rescue_candidate.text
    assert llm_diag["effective_definition_phase"] == "rescue"
    assert llm_diag["preservation_short_circuited_rescue"] is False
    assert llm_diag["rescue_used"] is True
    assert llm_diag["legacy_redraft_path_enabled"] is False
    assert llm_diag["legacy_definition_redraft_allowed"] is False
    assert llm_diag["legacy_scope_redraft_allowed"] is False
    assert llm_diag["llm_call_budget"]["phase_call_order"] == ["draft", "verify", "draft", "verify"]
    assert llm_diag["llm_call_budget"]["calls_used"] == 4
    assert phase_log == ["draft", "verify", "draft", "verify"]


def test_build_kc_draft_bundles_llm_enforces_per_kc_llm_call_budget(monkeypatch):
    kc_id = "KC_SYN_MONO_BUDGET"
    canonical_name = "Deferred Coverage"
    rows = [
        _synthetic_overlay_row(
            kc_id=kc_id,
            canonical_name=canonical_name,
            suffix="01",
            text="Deferred Coverage is",
            topic_path_labels=["Synthetic Domain", "Synthetic Branch"],
        ),
        _synthetic_overlay_row(
            kc_id=kc_id,
            canonical_name=canonical_name,
            suffix="02",
            text="the share of coverage assigned after an additional review pass.",
            topic_path_labels=["Synthetic Domain", "Synthetic Branch"],
        ),
    ]
    preservation_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="01",
        text="Deferred Coverage is",
        score=10.0,
        classification="definition_support",
        positive_surface_type="fragment",
        single_span_accepted=False,
    )
    rescue_candidate = _synthetic_definition_candidate(
        target_kc_id=kc_id,
        source_kc_id=kc_id,
        overlay_suffix="02",
        text="the share of coverage assigned after an additional review pass.",
        score=11.0,
        classification="definition_support",
        positive_surface_type="fragment",
        single_span_accepted=False,
    )

    monkeypatch.setattr(
        drafting_module,
        "_definition_candidates",
        lambda *args, support_pack=None, **kwargs: [rescue_candidate] if support_pack else [preservation_candidate],
    )
    monkeypatch.setattr(
        drafting_module,
        "select_definition_support_pack",
        lambda *args, **kwargs: [{"overlay_candidate_id": f"{kc_id}:overlay:02"}],
    )
    monkeypatch.setattr(drafting_module, "_scope_candidates", lambda *args, **kwargs: [])
    monkeypatch.setattr(drafting_module, "_definition_rescue_candidates", lambda candidates, *, limit: list(candidates)[:limit])

    phase_log: list[str] = []
    state = {"draft_calls": 0, "verify_calls": 0, "definition_redraft_calls": 0}

    def draft_invoker(request: dict[str, object]):
        phase = str(request["phase"])
        phase_log.append(phase)
        if phase == "draft":
            state["draft_calls"] += 1
            return {
                "definition": {
                    "status": "abstained",
                    "text": "",
                    "supporting_evidence_labels": [],
                    "abstention_reason": "insufficient_evidence",
                },
                "scope": {
                    "status": "abstained",
                    "text": "",
                    "supporting_evidence_labels": [],
                    "abstention_reason": "scope_gap",
                },
            }, {"source": "test_budget_abstain"}
        assert phase == "definition_redraft"
        state["definition_redraft_calls"] += 1
        assert state["definition_redraft_calls"] == 1
        label = next(iter(dict(request["request_payload"]).get("label_to_overlay_candidate_id", {})))
        return {
            "definition": {
                "status": "grounded",
                "text": "Deferred Coverage is the share of coverage assigned after an additional review pass.",
                "supporting_evidence_labels": [label],
                "abstention_reason": "",
            }
        }, {"source": "test_budget_definition_redraft"}

    def verify_invoker(request: dict[str, object]):
        phase = str(request["phase"])
        phase_log.append(phase)
        assert phase == "verify"
        state["verify_calls"] += 1
        assert state["verify_calls"] <= 2
        return {
            "definition": {
                "status": "abstained",
                "text": "",
                "supporting_evidence_labels": [],
                "abstention_reason": "insufficient_evidence",
            },
            "scope": {
                "status": "abstained",
                "text": "",
                "supporting_evidence_labels": [],
                "abstention_reason": "scope_gap",
            },
        }, {"source": "test_budget_abstain"}

    bundles, stats = build_kc_draft_bundles_llm(
        rows,
        runtime=Step67ModelRuntime(
            base_url="http://unit.test",
            model="synthetic-model",
            draft_invoker=draft_invoker,
            verify_invoker=verify_invoker,
        ),
        policy=Step67DraftingPolicy(max_llm_calls_per_kc=5),
    )

    llm_diag = bundles[0]["selection_diagnostics"]["llm_drafting"]

    assert llm_diag["llm_call_budget"]["budget_exhausted"] is True
    assert llm_diag["llm_call_budget"]["max_calls"] == 5
    assert llm_diag["llm_call_budget"]["calls_used"] == 5
    assert llm_diag["llm_call_budget"]["phase_call_order"] == [
        "draft",
        "verify",
        "draft",
        "verify",
        "definition_redraft",
    ]
    assert "definition_verify" in llm_diag["llm_call_budget"]["blocked_phases"]
    assert llm_diag["definition_redraft_verify_error"].startswith("LLMCallBudgetExceededError:")
    assert stats["llm_call_budget_per_kc_max"] == 5
    assert stats["kcs_with_llm_budget_exhaustion"] == 1
    assert phase_log == ["draft", "verify", "draft", "verify", "definition_redraft"]


def test_canonicalize_draft_bundle_row_keeps_identity_when_raw_surface_is_already_clean():
    bundle = _synthetic_grounded_bundle()
    bundle["canonical_name"] = "Border Point"
    bundle["aliases"] = []
    bundle["definition_full_candidate"] = {
        "status": "grounded",
        "text": "A border point is a non-core point that lies within the neighborhood of a core point.",
        "supporting_overlay_candidate_ids": ["KC_SYN_HIGH:overlay:01", "KC_SYN_HIGH:overlay:02"],
        "selection_reason": "definition_full_candidate_llm_multispan_verified",
        "source_text_field": "quote_surface",
    }
    overlay_by_id = {
        "KC_SYN_HIGH:overlay:01": _synthetic_overlay_row(
            kc_id="KC_SYN_HIGH",
            canonical_name="Border Point",
            suffix="01",
            text="A border point is a non-core point that lies within the neighborhood of a core point.",
        ),
        "KC_SYN_HIGH:overlay:02": _synthetic_overlay_row(
            kc_id="KC_SYN_HIGH",
            canonical_name="Border Point",
            suffix="02",
            text="A point that is not a core point can still belong to a cluster when it falls within a core point neighborhood.",
        ),
    }

    canonicalized = canonicalize_draft_bundle_row(bundle, overlay_by_id=overlay_by_id)

    assert canonicalized["canonicalization_contract_version"] == STEP675_CANONICALIZATION_CONTRACT_VERSION
    assert canonicalized["definition_full_candidate_canonicalized"]["text"] == bundle["definition_full_candidate"]["text"]
    assert canonicalized["canonicalization_metadata"]["definition_full_candidate"]["canonicalization_mode"] == CANONICALIZATION_MODE_IDENTITY
    assert canonicalized["review_burden_estimate"] == "low"


def test_canonicalize_draft_bundle_row_applies_deterministic_cleanup_without_rewriting_meaning():
    bundle = _synthetic_grounded_bundle()
    bundle["canonical_name"] = "Specificity"
    bundle["definition_full_candidate"] = {
        "status": "grounded",
        "text": "Analogously to TPR, the true negative rate (TNR) (also known as specificity ) is defined as the fraction of negative test instances correctly predicted by the classifier, i.e.,",
        "supporting_overlay_candidate_ids": ["KC_SYN_HIGH:overlay:01"],
        "selection_reason": "definition_full_candidate_draft_supported_single_span_fallback_same_kc_salvage",
        "source_text_field": "quote_surface",
    }
    overlay_by_id = {
        "KC_SYN_HIGH:overlay:01": _synthetic_overlay_row(
            kc_id="KC_SYN_HIGH",
            canonical_name="Specificity",
            suffix="01",
            text="Analogously to TPR, the true negative rate (TNR) (also known as specificity ) is defined as the fraction of negative test instances correctly predicted by the classifier, i.e.,",
        ),
    }

    canonicalized = canonicalize_draft_bundle_row(bundle, overlay_by_id=overlay_by_id)
    field_meta = canonicalized["canonicalization_metadata"]["definition_full_candidate"]

    assert canonicalized["definition_full_candidate_canonicalized"]["text"].endswith("classifier.")
    assert "i.e.," not in canonicalized["definition_full_candidate_canonicalized"]["text"]
    assert "(also known as specificity)" in canonicalized["definition_full_candidate_canonicalized"]["text"]
    assert field_meta["canonicalization_mode"] == CANONICALIZATION_MODE_DETERMINISTIC_CLEANUP
    assert "trim_dangling_tail_fragment" in field_meta["canonicalization_actions"]


def test_canonicalize_draft_bundle_row_prefers_same_support_quote_surface_when_text_matches_cleanly():
    bundle = _synthetic_grounded_bundle()
    bundle["canonical_name"] = "Single Link"
    bundle["definition_full_candidate"] = {
        "status": "grounded",
        "text": "For the single link or MIN version of hierarchical clustering, the proximity of two clusters is defined as the minimum of the distance between any two points in the two different clusters.",
        "supporting_overlay_candidate_ids": ["KC_SYN_HIGH:overlay:01"],
        "selection_reason": "definition_full_candidate_draft_supported_single_span_fallback",
        "source_text_field": "source_block_text",
    }
    overlay_by_id = {
        "KC_SYN_HIGH:overlay:01": {
            **_synthetic_overlay_row(
                kc_id="KC_SYN_HIGH",
                canonical_name="Single Link",
                suffix="01",
                text="For the single link or MIN version of hierarchical clustering, the proximity of two clusters is defined as the minimum of the distance between any two points in the two different clusters.",
            ),
            "source_block_text": "For the single link or MIN version of hierarchical clustering, the proximity of two clusters is defined as the minimum of the distance between any two points in the two different clusters. The single link technique is sensitive to noise and outliers.",
            "quote_surface": "For the single link or MIN version of hierarchical clustering, the proximity of two clusters is defined as the minimum of the distance between any two points in the two different clusters.",
            "is_definition_like": True,
        },
    }

    canonicalized = canonicalize_draft_bundle_row(bundle, overlay_by_id=overlay_by_id)
    field_meta = canonicalized["canonicalization_metadata"]["definition_full_candidate"]

    assert canonicalized["definition_full_candidate_canonicalized"]["text"] == overlay_by_id["KC_SYN_HIGH:overlay:01"]["quote_surface"]
    assert canonicalized["definition_full_candidate_canonicalized"]["source_text_field"] == "quote_surface"
    assert field_meta["canonicalization_mode"] == CANONICALIZATION_MODE_EXTRACTIVE_SELECTION
    assert field_meta["surface_origin"] == "support_quote_surface"


def test_canonicalize_draft_bundle_row_preserves_raw_when_canonicalization_would_only_polish_bad_support():
    bundle = _synthetic_grounded_bundle()
    bundle["canonical_name"] = "Naive Independence Assumption"
    bundle["definition_full_candidate"] = {
        "status": "grounded",
        "text": "Definition 6.11 suggests that an itemset is negatively correlated if its support is below the expected support computed using the statistical independence assumption.",
        "supporting_overlay_candidate_ids": ["KC_SYN_HIGH:overlay:01"],
        "selection_reason": "definition_full_candidate_draft_supported_single_span_fallback",
        "source_text_field": "source_block_text",
    }
    overlay_by_id = {
        "KC_SYN_HIGH:overlay:01": {
            **_synthetic_overlay_row(
                kc_id="KC_SYN_HIGH",
                canonical_name="Naive Independence Assumption",
                suffix="01",
                text="Definition 6.11 suggests that an itemset is negatively correlated if its support is below the expected support computed using the statistical independence assumption.",
            ),
            "quote_surface": "Definition 6.11 suggests that an itemset is negatively correlated if its support is below the expected support computed using the statistical independence assumption.",
            "source_block_text": "Definition 6.11 suggests that an itemset is negatively correlated if its support is below the expected support computed using the statistical independence assumption. The smaller the support, the more negatively correlated is the pattern.",
            "is_definition_like": False,
            "is_procedure_like": True,
        },
    }

    canonicalized = canonicalize_draft_bundle_row(bundle, overlay_by_id=overlay_by_id)
    field_meta = canonicalized["canonicalization_metadata"]["definition_full_candidate"]

    assert canonicalized["definition_full_candidate_canonicalized"]["text"] == bundle["definition_full_candidate"]["text"]
    assert field_meta["canonicalization_mode"] == CANONICALIZATION_MODE_RAW_PASSTHROUGH
    assert field_meta["cannot_safely_canonicalize"] is True
    assert "history_or_provenance_surface" in field_meta["canonicalization_risk_flags"]
    assert canonicalized["review_burden_estimate"] == "high"


def test_emit_canonicalized_draft_bundles_persists_parallel_fields_and_stats():
    bundle = _synthetic_grounded_bundle()
    bundle["canonical_name"] = "Single Link"
    bundle["definition_full_candidate"] = {
        "status": "grounded",
        "text": "For the single link or MIN version of hierarchical clustering, the proximity of two clusters is defined as the minimum of the distance between any two points in the two different clusters.",
        "supporting_overlay_candidate_ids": ["KC_SYN_HIGH:overlay:01"],
        "selection_reason": "definition_full_candidate_draft_supported_single_span_fallback",
        "source_text_field": "source_block_text",
    }
    overlay_row = {
        **_synthetic_overlay_row(
            kc_id="KC_SYN_HIGH",
            canonical_name="Single Link",
            suffix="01",
            text="For the single link or MIN version of hierarchical clustering, the proximity of two clusters is defined as the minimum of the distance between any two points in the two different clusters.",
        ),
        "source_block_text": "For the single link or MIN version of hierarchical clustering, the proximity of two clusters is defined as the minimum of the distance between any two points in the two different clusters. The single link technique is sensitive to noise and outliers.",
        "quote_surface": "For the single link or MIN version of hierarchical clustering, the proximity of two clusters is defined as the minimum of the distance between any two points in the two different clusters.",
        "is_definition_like": True,
    }

    tmp_dir = REPO_ROOT / "data" / "work" / "cache" / f"test_step675_emit_{uuid4().hex}"
    try:
        tmp_dir.mkdir(parents=True, exist_ok=False)
        result = emit_canonicalized_draft_bundles(
            output_dir=tmp_dir,
            draft_rows=[bundle],
            overlay_rows=[overlay_row],
        )
        rows = read_jsonl(result.bundle_path)
        stats = read_json(result.stats_path)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    assert result.bundle_count == 1
    assert rows[0]["definition_full_candidate"]["text"] == bundle["definition_full_candidate"]["text"]
    assert rows[0]["definition_full_candidate_canonicalized"]["source_text_field"] == "quote_surface"
    assert rows[0]["canonicalization_contract_version"] == STEP675_CANONICALIZATION_CONTRACT_VERSION
    assert rows[0]["canonicalization_metadata"]["definition_full_candidate"]["canonicalization_mode"] == CANONICALIZATION_MODE_EXTRACTIVE_SELECTION
    assert rows[0]["review_burden_estimate"] == "low"
    assert stats["field_mode_counts"]["definition_full_candidate"][CANONICALIZATION_MODE_EXTRACTIVE_SELECTION] == 1


def test_step67_wrapper_main_delegates_to_new_orchestration(monkeypatch, capsys):
    calls = {}

    def fake_run_step6_7_pipeline(*, config_path: Path, repo_root: Path, limit_kcs: int | None):
        calls["config_path"] = config_path
        calls["repo_root"] = repo_root
        calls["limit_kcs"] = limit_kcs
        return 0, {"status": "ok", "delegated": "step6_7"}

    monkeypatch.setattr(STEP67_RUNNER, "run_step6_7_pipeline", fake_run_step6_7_pipeline)
    monkeypatch.setattr(
        STEP67_RUNNER,
        "parse_args",
        lambda: SimpleNamespace(config=Path("synthetic_step6_7.yaml"), limit_kcs=7),
    )

    result = STEP67_RUNNER.main()
    captured = capsys.readouterr()

    assert result == 0
    assert calls["config_path"] == Path("synthetic_step6_7.yaml")
    assert calls["repo_root"] == STEP67_RUNNER.REPO_ROOT
    assert calls["limit_kcs"] == 7
    assert '"delegated": "step6_7"' in captured.out


def test_step675_wrapper_main_delegates_to_new_orchestration(monkeypatch, capsys):
    calls = {}

    def fake_run_step6_75_pipeline(*, config_path: Path, repo_root: Path):
        calls["config_path"] = config_path
        calls["repo_root"] = repo_root
        return 0, {"status": "ok", "delegated": "step6_75"}

    monkeypatch.setattr(STEP675_RUNNER, "run_step6_75_pipeline", fake_run_step6_75_pipeline)
    monkeypatch.setattr(
        STEP675_RUNNER,
        "parse_args",
        lambda: SimpleNamespace(config=Path("synthetic_step6_75.yaml")),
    )

    result = STEP675_RUNNER.main()
    captured = capsys.readouterr()

    assert result == 0
    assert calls["config_path"] == Path("synthetic_step6_75.yaml")
    assert calls["repo_root"] == STEP675_RUNNER.REPO_ROOT
    assert '"delegated": "step6_75"' in captured.out


def test_step68_wrapper_main_delegates_to_new_orchestration(monkeypatch, capsys):
    calls = {}

    def fake_run_step6_8_pipeline(*, config_path: Path, repo_root: Path):
        calls["config_path"] = config_path
        calls["repo_root"] = repo_root
        return 0, {"status": "ok", "delegated": "step6_8"}

    monkeypatch.setattr(STEP68_RUNNER, "run_step6_8_pipeline", fake_run_step6_8_pipeline)
    monkeypatch.setattr(
        STEP68_RUNNER,
        "parse_args",
        lambda: SimpleNamespace(config=Path("synthetic_step6_8.yaml")),
    )

    result = STEP68_RUNNER.main()
    captured = capsys.readouterr()

    assert result == 0
    assert calls["config_path"] == Path("synthetic_step6_8.yaml")
    assert calls["repo_root"] == STEP68_RUNNER.REPO_ROOT
    assert '"delegated": "step6_8"' in captured.out


def test_step67b_wrapper_main_delegates_to_new_orchestration(monkeypatch, capsys):
    calls = {}

    def fake_run_step6_7b_pipeline(*, config_path: Path, repo_root: Path):
        calls["config_path"] = config_path
        calls["repo_root"] = repo_root
        return 0, {"status": "ok", "delegated": "step6_7b"}

    monkeypatch.setattr(STEP67B_RUNNER, "run_step6_7b_pipeline", fake_run_step6_7b_pipeline)
    monkeypatch.setattr(
        STEP67B_RUNNER,
        "parse_args",
        lambda: SimpleNamespace(config=Path("synthetic_step6_7b.yaml")),
    )

    result = STEP67B_RUNNER.main()
    captured = capsys.readouterr()

    assert result == 0
    assert calls["config_path"] == Path("synthetic_step6_7b.yaml")
    assert calls["repo_root"] == STEP67B_RUNNER.REPO_ROOT
    assert '"delegated": "step6_7b"' in captured.out


def test_current_step_artifact_specs_include_step67b_alias_support():
    specs = {spec.key: spec for spec in current_step_artifact_specs()}

    assert "step6_7b_set_manifest" in specs
    assert specs["step6_7b_set_manifest"].alias_filename == "step6_7b_set_manifest.current.json"
    assert "step6_7b_seed_floor_triage_and_rescue_set" in specs["step6_7b_set_manifest"].source_glob


def test_seed_floor_triage_assigns_formula_pairing_bucket_and_marks_rescue_eligible():
    bundle = _synthetic_low_trust_bundle()
    local_rows = [
        _synthetic_support_pack_row(
            kc_id="KC_SYN_LOW",
            canonical_name="Synthetic Low Trust KC",
            suffix="formula",
            text="P(low)=count(low)/N.",
        ),
        _synthetic_support_pack_row(
            kc_id="KC_SYN_LOW",
            canonical_name="Synthetic Low Trust KC",
            suffix="prose",
            text="Synthetic Low Trust KC is a conservative local definition used for edit-first review.",
        ),
    ]

    result = triage_seed_floor_bundle_row(
        bundle=bundle,
        overlay_rows_by_kc={"KC_SYN_LOW": local_rows},
    )

    assert result.triage_row is not None
    assert result.triage_row["primary_bucket"] == TRIAGE_BUCKET_PIPELINE_MISS_FORMULA_EXPLANATION_PAIRING
    assert result.triage_row["rescue_eligible"] is True


def test_seed_floor_triage_applies_deterministic_rescue_and_preserves_raw_snapshot():
    bundle = _synthetic_low_trust_bundle()
    local_rows = [
        _synthetic_support_pack_row(
            kc_id="KC_SYN_LOW",
            canonical_name="Synthetic Low Trust KC",
            suffix="rescue",
            text="Synthetic Low Trust KC is a conservative reviewer-editable concept.",
        ),
        _synthetic_support_pack_row(
            kc_id="KC_SYN_LOW",
            canonical_name="Synthetic Low Trust KC",
            suffix="support",
            text="Synthetic Low Trust KC refers to a concept that remains in the review lane for editing.",
        ),
    ]

    result = triage_seed_floor_bundle_row(
        bundle=bundle,
        overlay_rows_by_kc={"KC_SYN_LOW": local_rows},
    )

    assert result.triage_row is not None
    assert result.triage_row["deterministic_rescue_attempted"] is True
    assert result.triage_row["deterministic_rescue_outcome"] in {"rescued_direct", "rescued_normalized"}
    assert result.bundle["step6_7b_contract_version"] == STEP67B_CONTRACT_VERSION
    assert result.bundle["authoritative_definition_status"] in {
        AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED,
        AUTHORITATIVE_DEFINITION_STATUS_NORMALIZED_GROUNDED,
    }
    assert result.bundle["seed_floor_triage"]["original_step6_7_raw"]["authoritative_definition_status"] == (
        AUTHORITATIVE_DEFINITION_STATUS_SEED_FLOOR_FALLBACK
    )
    assert result.bundle["review_readiness"]["label"] == REVIEW_READINESS_NEEDS_ATTENTION


def test_seed_floor_triage_model_rescue_honors_structured_local_contract():
    bundle = _synthetic_low_trust_bundle()
    local_rows = [
        _synthetic_support_pack_row(
            kc_id="KC_SYN_LOW",
            canonical_name="Synthetic Low Trust KC",
            suffix="formula",
            text="P(low)=count(low)/N.",
        ),
        _synthetic_support_pack_row(
            kc_id="KC_SYN_LOW",
            canonical_name="Synthetic Low Trust KC",
            suffix="context",
            text="The quantity appears in the posterior update after observing evidence.",
        ),
    ]

    def fake_model_invoker(payload):
        evidence_ids = [item["overlay_candidate_id"] for item in payload["request_payload"]["evidence_items"]]
        return {
            "decision": {
                "status": AUTHORITATIVE_DEFINITION_STATUS_NORMALIZED_GROUNDED,
                "text": "Synthetic Low Trust KC is the local quantity used as a conservative reviewer-editable test concept.",
                "supporting_overlay_candidate_ids": evidence_ids,
                "abstention_reason": "",
            }
        }

    result = triage_seed_floor_bundle_row(
        bundle=bundle,
        overlay_rows_by_kc={"KC_SYN_LOW": local_rows},
        model_rescue_cfg={
            "execution_mode": "llm",
            "provider": "ollama",
            "generation_base_url": "http://127.0.0.1:11567",
            "generation_base_url_field": "test.base_url",
            "generation_model_alias": "synthetic-model",
            "generation_model_field": "test.model",
        },
        model_invoker=fake_model_invoker,
    )

    assert result.triage_row is not None
    assert result.triage_row["deterministic_rescue_outcome"] == "no_rescue"
    assert result.triage_row["bounded_model_rescue_attempted"] is True
    assert result.triage_row["bounded_model_rescue_outcome"] == "rescued_normalized"
    assert result.bundle["authoritative_definition_status"] == AUTHORITATIVE_DEFINITION_STATUS_NORMALIZED_GROUNDED


def test_seed_floor_triage_never_downgrades_already_grounded_bundle():
    bundle = _synthetic_grounded_bundle()

    result = triage_seed_floor_bundle_row(
        bundle=bundle,
        overlay_rows_by_kc={"KC_SYN_HIGH": []},
    )

    assert result.triage_row is None
    assert result.bundle["authoritative_definition_status"] == AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED
    assert result.bundle["step6_7b_contract_version"] == STEP67B_CONTRACT_VERSION


def test_run_step675_pipeline_prefers_step67b_output_when_present():
    with tempfile.TemporaryDirectory() as temp_dir:
        repo_root = Path(temp_dir)
        config_path = repo_root / "synthetic_step6_75.yaml"
        config_path.write_text(
            "\n".join(
                [
                    "inputs:",
                    "  step6_7b_set_manifest: data/work/cache/current_step_artifacts/step6_7b_set_manifest.current.json",
                    "  step6_7_set_manifest: data/work/cache/current_step_artifacts/step6_7_set_manifest.current.json",
                    "outputs:",
                    "  processed_root: data/processed/kc_draft_canonicalization",
                    "  sets_root: data/processed/kc_draft_canonicalization/_sets",
                    "  runs_root: data/runs",
                    "canonicalization:",
                    "  allow_definition_extractive_selection: true",
                    "  allow_scope_extractive_selection: false",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        rescued_bundle_path = repo_root / "data/processed/kc_seed_floor_triage_and_rescue/2026-04-20_000000/kc_draft_bundles_rescued.jsonl"
        rescued_bundle_path.parent.mkdir(parents=True, exist_ok=True)
        rescued_bundle_path.write_text(
            json.dumps(
                {
                    "kc_id": "KC_SYN_LOW",
                    "canonical_name": "Synthetic Low Trust KC",
                    "authoritative_definition_status": AUTHORITATIVE_DEFINITION_STATUS_NORMALIZED_GROUNDED,
                    "step6_7b_contract_version": STEP67B_CONTRACT_VERSION,
                    "definition_full_candidate": {"status": "grounded", "text": "Rescued synthetic definition."},
                    "scope_candidate": {"status": "abstained", "text": ""},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        triage_rows_path = repo_root / "data/processed/kc_seed_floor_triage_and_rescue/2026-04-20_000000/triage_rows.jsonl"
        triage_rows_path.write_text(json.dumps({"kc_id": "KC_SYN_LOW"}) + "\n", encoding="utf-8")
        triage_stats_path = repo_root / "data/processed/kc_seed_floor_triage_and_rescue/2026-04-20_000000/triage_stats.json"
        triage_stats_path.write_text(json.dumps({"rescued_normalized_count": 1}, indent=2), encoding="utf-8")

        overlay_path = repo_root / "data/processed/kc_drafting_input_overlay/2026-04-08_105028/candidate_sentence_overlay.jsonl"
        overlay_path.parent.mkdir(parents=True, exist_ok=True)
        overlay_path.write_text(
            json.dumps(
                _synthetic_overlay_row(
                    kc_id="KC_SYN_LOW",
                    canonical_name="Synthetic Low Trust KC",
                    suffix="01",
                    text="Synthetic overlay.",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        overlay_stats_path = repo_root / "data/processed/kc_drafting_input_overlay/2026-04-08_105028/overlay_stats.json"
        overlay_stats_path.write_text(json.dumps({"row_count": 1}, indent=2), encoding="utf-8")

        step6_6_set_path = repo_root / "data/work/cache/current_step_artifacts/step6_6_set_manifest.current.json"
        step6_6_set_path.parent.mkdir(parents=True, exist_ok=True)
        step6_6_set_path.write_text(
            json.dumps({"set_id": "step6_6_set"}, indent=2),
            encoding="utf-8",
        )

        step6_7_set_path = repo_root / "data/processed/kc_drafts/_sets/2026-04-19_012531_step6_7_kc_drafts_set.json"
        step6_7_set_path.parent.mkdir(parents=True, exist_ok=True)
        step6_7_set_path.write_text(
            json.dumps(
                {
                    "set_id": "2026-04-19_012531_step6_7_kc_drafts_set",
                    "slice": {"exact_kc_ids": ["KC_SYN_LOW"], "limit_kcs": 1},
                    "artifacts": {
                        "kc_draft_bundles_jsonl": "data/processed/kc_drafts/2026-04-19_012531/kc_draft_bundles.jsonl"
                    },
                    "upstream": {
                        "candidate_sentence_overlay_jsonl": "data/processed/kc_drafting_input_overlay/2026-04-08_105028/candidate_sentence_overlay.jsonl",
                        "overlay_stats_json": "data/processed/kc_drafting_input_overlay/2026-04-08_105028/overlay_stats.json",
                        "step6_6_set_manifest_json": "data/work/cache/current_step_artifacts/step6_6_set_manifest.current.json",
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        step6_7b_set_path = repo_root / "data/work/cache/current_step_artifacts/step6_7b_set_manifest.current.json"
        step6_7b_set_path.write_text(
            json.dumps(
                {
                    "set_id": "2026-04-20_000000_step6_7b_seed_floor_triage_and_rescue_set",
                    "artifacts": {
                        "kc_draft_bundles_rescued_jsonl": "data/processed/kc_seed_floor_triage_and_rescue/2026-04-20_000000/kc_draft_bundles_rescued.jsonl",
                        "triage_rows_jsonl": "data/processed/kc_seed_floor_triage_and_rescue/2026-04-20_000000/triage_rows.jsonl",
                        "triage_stats_json": "data/processed/kc_seed_floor_triage_and_rescue/2026-04-20_000000/triage_stats.json",
                    },
                    "upstream": {
                        "step6_7_set_manifest_json": "data/processed/kc_drafts/_sets/2026-04-19_012531_step6_7_kc_drafts_set.json",
                        "candidate_sentence_overlay_jsonl": "data/processed/kc_drafting_input_overlay/2026-04-08_105028/candidate_sentence_overlay.jsonl",
                        "overlay_stats_json": "data/processed/kc_drafting_input_overlay/2026-04-08_105028/overlay_stats.json",
                        "step6_6_set_manifest_json": "data/work/cache/current_step_artifacts/step6_6_set_manifest.current.json",
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        captured = {}
        original_emit = orchestration_module.emit_canonicalized_draft_bundles

        def fake_emit_canonicalized_draft_bundles(
            *,
            output_dir,
            draft_rows,
            overlay_rows,
            allow_definition_extractive_selection,
            allow_scope_extractive_selection,
        ):
            captured["draft_rows"] = list(draft_rows)
            output_dir.mkdir(parents=True, exist_ok=True)
            bundle_path = output_dir / "kc_draft_bundles_canonicalized.jsonl"
            stats_path = output_dir / "canonicalization_stats.json"
            bundle_path.write_text(json.dumps(captured["draft_rows"][0]) + "\n", encoding="utf-8")
            stats_path.write_text(json.dumps({"bundle_count": len(captured["draft_rows"])}, indent=2), encoding="utf-8")
            return SimpleNamespace(
                bundle_path=bundle_path,
                stats_path=stats_path,
                bundle_count=len(captured["draft_rows"]),
                stats={"bundle_count": len(captured["draft_rows"])},
            )

        orchestration_module.emit_canonicalized_draft_bundles = fake_emit_canonicalized_draft_bundles
        try:
            exit_code, payload = orchestration_module.run_step6_75_pipeline(
                config_path=config_path,
                repo_root=repo_root,
            )
        finally:
            orchestration_module.emit_canonicalized_draft_bundles = original_emit

        assert exit_code == 0
        assert payload["bundle_count"] == 1
        assert captured["draft_rows"][0]["authoritative_definition_status"] == AUTHORITATIVE_DEFINITION_STATUS_NORMALIZED_GROUNDED
        assert captured["draft_rows"][0]["step6_7b_contract_version"] == STEP67B_CONTRACT_VERSION


def test_restarted_review_packet_marks_structurally_valid_fallback_as_review_edit_required():
    bundle = _synthetic_low_trust_bundle()
    bundle["seed_floor_triage"] = {
        "primary_bucket": TRIAGE_BUCKET_PIPELINE_MISS_NEIGHBOR_BLEED_OR_LOCAL_ALIGNMENT,
        "rescue_mode": "retained_seed_floor",
    }

    packet = build_restarted_review_packet(
        draft_bundle=bundle,
        step4_set_id="step4_set",
        step4_5_set_id="step4_5_set",
        step5_set_id="step5_set",
        step6_6_set_id="step6_6_set",
        step6_7_set_id="step6_7_set",
        step6_7b_set_id="step6_7b_set",
        step6_75_set_id="step6_75_set",
        step6_8_run_id="2026-04-20_review_edit_required_test",
    )

    assert packet["source_provenance"]["source_set_ids"]["step6_7b_set_id"] == "step6_7b_set"
    assert packet["system_recommendation"]["label"] == "review_needed"
    assert "review_edit_required" in packet["system_recommendation"]["reason_codes"]


def test_restarted_review_packet_preserves_reject_for_structural_seed_floor_issue():
    bundle = _synthetic_low_trust_bundle()
    bundle["seed_floor_triage"] = {
        "primary_bucket": TRIAGE_BUCKET_STRUCTURAL_SEED_OR_HIERARCHY_ISSUE,
        "rescue_mode": "retained_seed_floor",
    }

    packet = build_restarted_review_packet(
        draft_bundle=bundle,
        step4_set_id="step4_set",
        step4_5_set_id="step4_5_set",
        step5_set_id="step5_set",
        step6_6_set_id="step6_6_set",
        step6_7_set_id="step6_7_set",
        step6_7b_set_id="step6_7b_set",
        step6_75_set_id="step6_75_set",
        step6_8_run_id="2026-04-20_structural_reject_test",
    )

    assert packet["system_recommendation"]["label"] == "reject_recommended"
