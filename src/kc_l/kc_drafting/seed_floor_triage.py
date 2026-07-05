from __future__ import annotations

import copy
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kc_l.kc_drafting.backend import ensure_llm_runtime_available
from kc_l.kc_drafting.contracts import (
    AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED,
    AUTHORITATIVE_DEFINITION_STATUS_NORMALIZED_GROUNDED,
    AUTHORITATIVE_DEFINITION_STATUS_SEED_FLOOR_FALLBACK,
    CONTEXT_LAYER_STATUS_GROUNDED,
    REVIEW_READINESS_NEEDS_ATTENTION,
    SCOPE_LAYER_STATUS_GROUNDED,
    TRUST_STATE_GROUNDED,
    TRUST_STATE_GROUNDED_WITH_GAPS,
    as_text,
)
from kc_l.kc_drafting.heuristic_core import assess_overlay_candidate
from kc_l.kc_drafting.model_profile import (
    apply_step67_model_profile_to_messages,
    normalize_step67_model_profile,
    step67_model_profile_think_flag,
    validate_supported_step67_model_profile,
)
from kc_l.utils.json_io import write_json, write_jsonl
from kc_l.utils.kc_step67_model_drafting import (
    Step67ModelRuntime,
    _definition_draft_supported_single_span_fallback_salvage_value,
    _definition_draft_supported_single_span_fallback_value,
    _kc_descriptor,
    _supporting_lookup_candidate_from_row,
)
from kc_l.utils.ollama_json import ollama_chat_json


STEP67B_CONTRACT_VERSION = "step6_7b_seed_floor_triage_and_rescue_v1"
STEP67B_STAGE_NAME = "step6_7b_seed_floor_triage_and_rescue"
STEP67B_RUNNER_NAME = "step6_7b_seed_floor_triage_and_rescue"

TRIAGE_BUCKET_PIPELINE_MISS_SAME_KC_LOCAL_SUPPORT = "pipeline_miss_same_kc_local_support"
TRIAGE_BUCKET_PIPELINE_MISS_FORMULA_EXPLANATION_PAIRING = "pipeline_miss_formula_explanation_pairing"
TRIAGE_BUCKET_PIPELINE_MISS_BUNDLE_OR_CAPACITY_SELECTION = "pipeline_miss_bundle_or_capacity_selection"
TRIAGE_BUCKET_PIPELINE_MISS_NEIGHBOR_BLEED_OR_LOCAL_ALIGNMENT = "pipeline_miss_neighbor_bleed_or_local_alignment"
TRIAGE_BUCKET_SOURCE_SUPPORTED_BUT_TOO_THIN_FOR_DIRECT = "source_supported_but_too_thin_for_direct"
TRIAGE_BUCKET_GENUINE_SOURCE_SCARCITY = "genuine_source_scarcity"
TRIAGE_BUCKET_STRUCTURAL_SEED_OR_HIERARCHY_ISSUE = "structural_seed_or_hierarchy_issue"

TRIAGE_BUCKETS = (
    TRIAGE_BUCKET_PIPELINE_MISS_SAME_KC_LOCAL_SUPPORT,
    TRIAGE_BUCKET_PIPELINE_MISS_FORMULA_EXPLANATION_PAIRING,
    TRIAGE_BUCKET_PIPELINE_MISS_BUNDLE_OR_CAPACITY_SELECTION,
    TRIAGE_BUCKET_PIPELINE_MISS_NEIGHBOR_BLEED_OR_LOCAL_ALIGNMENT,
    TRIAGE_BUCKET_SOURCE_SUPPORTED_BUT_TOO_THIN_FOR_DIRECT,
    TRIAGE_BUCKET_GENUINE_SOURCE_SCARCITY,
    TRIAGE_BUCKET_STRUCTURAL_SEED_OR_HIERARCHY_ISSUE,
)

RESCUE_ELIGIBLE_BUCKETS = {
    TRIAGE_BUCKET_PIPELINE_MISS_SAME_KC_LOCAL_SUPPORT,
    TRIAGE_BUCKET_PIPELINE_MISS_FORMULA_EXPLANATION_PAIRING,
    TRIAGE_BUCKET_PIPELINE_MISS_BUNDLE_OR_CAPACITY_SELECTION,
    TRIAGE_BUCKET_PIPELINE_MISS_NEIGHBOR_BLEED_OR_LOCAL_ALIGNMENT,
    TRIAGE_BUCKET_SOURCE_SUPPORTED_BUT_TOO_THIN_FOR_DIRECT,
}

MODEL_RESCUE_DISABLED = "disabled"
MODEL_RESCUE_LLM = "llm"

DETERMINISTIC_RESCUE_MODE_SAME_KC_LOCAL_EXPLICIT = "same_kc_local_explicit_definition_rescue"
DETERMINISTIC_RESCUE_MODE_FORMULA_PAIR = "formula_plus_local_prose_rescue"
DETERMINISTIC_RESCUE_MODE_BUNDLE_SELECTION = "bundle_or_capacity_selection_rescue"
DETERMINISTIC_RESCUE_MODE_NEIGHBOR_RECOVERY = "same_kc_local_neighbor_recovery"
DETERMINISTIC_RESCUE_MODE_HEADING_EXPLANATION = "heading_plus_explanation_rescue"
DETERMINISTIC_RESCUE_MODE_QUOTE_SURFACE = "quote_surface_preference_rescue"
BOUNDED_MODEL_RESCUE_MODE = "bounded_model_focused_evidence_rescue"

RISK_FLAGS_RESOLVED_BY_RESCUE = {
    "definition_support_insufficient",
    "definition_candidate_verifier_rejected",
    "seed_definition_floor_active",
    "definition_enrichment_missing",
    "low_trust_survivor",
}
READINESS_REASONS_RESOLVED_BY_RESCUE = {
    "definition_support_insufficient",
    "definition_candidate_verifier_rejected",
    "seed_definition_floor_active",
}

MODEL_RESCUE_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": [
                        AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED,
                        AUTHORITATIVE_DEFINITION_STATUS_NORMALIZED_GROUNDED,
                        "abstain",
                    ],
                },
                "text": {"type": "string"},
                "supporting_overlay_candidate_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "abstention_reason": {"type": "string"},
            },
            "required": [
                "status",
                "text",
                "supporting_overlay_candidate_ids",
                "abstention_reason",
            ],
            "additionalProperties": False,
        }
    },
    "required": ["decision"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class SeedFloorBundleTriageResult:
    bundle: dict[str, Any]
    triage_row: dict[str, Any] | None


@dataclass(frozen=True)
class SeedFloorTriageEmissionResult:
    bundle_path: Path
    triage_path: Path
    stats_path: Path
    bundle_count: int
    triaged_count: int
    stats: dict[str, Any]


def _append_unique(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


def _normalize_string_list(values: Any) -> list[str]:
    out: list[str] = []
    for value in values or []:
        text = as_text(value)
        if text:
            _append_unique(out, text)
    return out


def _page_index(value: Any) -> int | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(value)
    except Exception:
        return None


def _status_is_grounded(status: str) -> bool:
    return status in {
        AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED,
        AUTHORITATIVE_DEFINITION_STATUS_NORMALIZED_GROUNDED,
    }


def _parent_topic_key_from_bundle(bundle: Mapping[str, Any]) -> tuple[str, ...]:
    topic_path_ids = _normalize_string_list(bundle.get("topic_path_ids"))
    if len(topic_path_ids) >= 2:
        return tuple(topic_path_ids[:-1])
    topic_path_labels = _normalize_string_list(bundle.get("topic_path_labels"))
    if len(topic_path_labels) >= 2:
        return tuple(topic_path_labels[:-1])
    return tuple()


def _build_sibling_success_anchor_index(
    *,
    draft_rows: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, ...], list[dict[str, Any]]]:
    anchor_index: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for bundle in draft_rows:
        status = as_text(bundle.get("authoritative_definition_status"))
        if not _status_is_grounded(status):
            continue
        parent_key = _parent_topic_key_from_bundle(bundle)
        if not parent_key:
            continue
        sibling_kc_id = as_text(bundle.get("kc_id"))
        sibling_name = as_text(bundle.get("canonical_name"))
        for item in bundle.get("evidence_bundle") or []:
            if not isinstance(item, Mapping):
                continue
            doc_id = as_text(item.get("doc_id"))
            page_index = _page_index(item.get("page_index"))
            if not doc_id or page_index is None:
                continue
            anchor_index.setdefault(parent_key, []).append(
                {
                    "sibling_kc_id": sibling_kc_id,
                    "sibling_name": sibling_name,
                    "doc_id": doc_id,
                    "page_index": page_index,
                    "block_id": as_text(item.get("block_id")),
                    "selection_score": float(item.get("selection_score") or item.get("alignment_score") or 0.0),
                }
            )

    compact_index: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for parent_key, anchors in anchor_index.items():
        best_by_doc_page: dict[tuple[str, int], dict[str, Any]] = {}
        for anchor in anchors:
            key = (as_text(anchor.get("doc_id")), int(anchor.get("page_index")))
            existing = best_by_doc_page.get(key)
            if existing is None or float(anchor.get("selection_score") or 0.0) > float(existing.get("selection_score") or 0.0):
                best_by_doc_page[key] = anchor
        compact = sorted(
            best_by_doc_page.values(),
            key=lambda item: (
                -float(item.get("selection_score") or 0.0),
                as_text(item.get("doc_id")),
                int(item.get("page_index") or 0),
                as_text(item.get("sibling_kc_id")),
            ),
        )
        compact_index[parent_key] = compact[:48]
    return compact_index


def _focus_bonus_from_sibling_anchors(
    *,
    row: Mapping[str, Any],
    sibling_anchors: Sequence[Mapping[str, Any]],
) -> tuple[float, list[str]]:
    if not sibling_anchors:
        return 0.0, []

    doc_id = as_text(row.get("doc_id"))
    if not doc_id:
        return 0.0, []

    same_doc = [item for item in sibling_anchors if as_text(item.get("doc_id")) == doc_id]
    if not same_doc:
        return 0.0, []

    bonus = 0.35
    reasons: list[str] = []
    _append_unique(reasons, "same_doc_as_sibling_success")

    page_index = _page_index(row.get("page_index"))
    if page_index is None:
        return bonus, reasons

    distances = [
        abs(page_index - int(item.get("page_index")))
        for item in same_doc
        if item.get("page_index") is not None
    ]
    if not distances:
        return bonus, reasons

    min_distance = min(distances)
    if min_distance == 0:
        bonus += 1.75
        _append_unique(reasons, "same_page_as_sibling_success")
    elif min_distance == 1:
        bonus += 1.25
        _append_unique(reasons, "adjacent_page_to_sibling_success")
    elif min_distance <= 2:
        bonus += 0.75
        _append_unique(reasons, "window2_page_to_sibling_success")
    elif min_distance <= 4:
        bonus += 0.35
        _append_unique(reasons, "window4_page_to_sibling_success")
    return bonus, reasons


def _focused_local_rows(
    *,
    bundle: Mapping[str, Any],
    overlay_rows_by_kc: Mapping[str, Sequence[Mapping[str, Any]]],
    sibling_anchor_index: Mapping[tuple[str, ...], Sequence[Mapping[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kc_id = as_text(bundle.get("kc_id"))
    rows = [dict(item) for item in overlay_rows_by_kc.get(kc_id) or []]
    sibling_anchors = [dict(item) for item in sibling_anchor_index.get(_parent_topic_key_from_bundle(bundle), [])]

    for row in rows:
        base_score = float(row.get("selection_score") or 0.0)
        bonus, reasons = _focus_bonus_from_sibling_anchors(row=row, sibling_anchors=sibling_anchors)
        row["step6_7b_focus_score"] = round(base_score + bonus, 6)
        row["step6_7b_focus_reasons"] = reasons

    rows.sort(
        key=lambda row: (
            -float(row.get("step6_7b_focus_score") or row.get("selection_score") or 0.0),
            -float(row.get("selection_score") or 0.0),
            as_text(row.get("overlay_candidate_id")),
        )
    )
    return rows, sibling_anchors


def _local_candidate_pack(
    *,
    local_rows: Sequence[Mapping[str, Any]],
) -> tuple[list[Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    assessments_by_id: dict[str, dict[str, Any]] = {}
    rows_by_id: dict[str, dict[str, Any]] = {}
    candidates: list[Any] = []
    for row in local_rows:
        candidate_id = as_text(row.get("overlay_candidate_id"))
        if not candidate_id:
            continue
        rows_by_id[candidate_id] = dict(row)
        assessment = dict(assess_overlay_candidate(row))
        assessments_by_id[candidate_id] = assessment
        candidate = _supporting_lookup_candidate_from_row(
            row,
            assessments_by_id=assessments_by_id,
        )
        if candidate is not None:
            candidates.append(candidate)

    candidates.sort(
        key=lambda item: (
            -float((rows_by_id.get(as_text(getattr(item, "overlay_candidate_id", "")), {}) or {}).get("step6_7b_focus_score") or getattr(item, "score", 0.0)),
            -float(getattr(item, "score", 0.0)),
            as_text(getattr(item, "overlay_candidate_id", "")),
        )
    )
    return candidates, rows_by_id, assessments_by_id


def _selection_diagnostics(bundle: Mapping[str, Any]) -> dict[str, Any]:
    return dict(bundle.get("selection_diagnostics") or {})


def _bucket_secondary_reasons(
    bundle: Mapping[str, Any],
    *,
    local_rows: Sequence[Mapping[str, Any]],
    sibling_anchors: Sequence[Mapping[str, Any]],
) -> list[str]:
    selection_diag = _selection_diagnostics(bundle)
    rejected_by_reason = dict((selection_diag.get("definition_candidate_diagnostics") or {}).get("rejected_by_reason") or {})
    excluded_by_reason = dict(selection_diag.get("excluded_by_reason") or {})
    risk_flags = _normalize_string_list(bundle.get("risk_flags"))
    reasons: list[str] = []

    for key in (
        "definition_support_insufficient",
        "definition_candidate_verifier_rejected",
        "formula_only_definition_risk",
        "bundle_capacity_reached",
        "explanatory_capacity_reached",
        "not_selected_for_bundle",
        "neighboring_concept_bleed",
        "high_contamination_candidates_present",
    ):
        if key in risk_flags:
            _append_unique(reasons, key)

    for key in ("weak_target_alignment", "ambiguous_retrieval", "surface_gate_rejected", "formula_dense_fragment"):
        if int(rejected_by_reason.get(key) or 0) > 0:
            _append_unique(reasons, f"rejected:{key}")

    for key in (
        "definition_verifier_bundle_block",
        "not_selected_for_bundle",
        "bundle_capacity_reached",
        "explanatory_capacity_reached",
        "neighboring_concept_bleed",
        "high_contamination",
        "formula_lead_in",
    ):
        if int(excluded_by_reason.get(key) or 0) > 0:
            _append_unique(reasons, f"excluded:{key}")

    if local_rows:
        _append_unique(reasons, f"same_kc_local_rows:{len(local_rows)}")
    if sibling_anchors:
        _append_unique(reasons, f"sibling_success_anchors:{len(sibling_anchors)}")
    return reasons


def _formula_pairing_signal(
    *,
    bundle: Mapping[str, Any],
    local_rows: Sequence[Mapping[str, Any]],
    assessments_by_id: Mapping[str, Mapping[str, Any]],
) -> bool:
    risk_flags = set(_normalize_string_list(bundle.get("risk_flags")))
    formula_like = "formula_only_definition_risk" in risk_flags
    prose_like = False

    for row in local_rows:
        candidate_id = as_text(row.get("overlay_candidate_id"))
        assessment = dict(assessments_by_id.get(candidate_id) or {})
        classification = as_text(assessment.get("classification"))
        candidate_text = as_text(
            assessment.get("candidate_text")
            or row.get("quote_surface")
            or row.get("source_block_text")
        )
        if classification in {"formula_only_support", "equation_support"} or "=" in candidate_text:
            formula_like = True
        if bool(assessment.get("definition_signal")) and classification not in {"formula_only_support", "equation_support"}:
            prose_like = True
    return formula_like and prose_like and len(local_rows) >= 2


def _capacity_signal(bundle: Mapping[str, Any]) -> bool:
    risk_flags = set(_normalize_string_list(bundle.get("risk_flags")))
    return bool(
        {
            "bundle_capacity_reached",
            "explanatory_capacity_reached",
            "not_selected_for_bundle",
        }
        & risk_flags
    )


def _neighbor_alignment_signal(bundle: Mapping[str, Any]) -> bool:
    selection_diag = _selection_diagnostics(bundle)
    rejected_by_reason = dict((selection_diag.get("definition_candidate_diagnostics") or {}).get("rejected_by_reason") or {})
    excluded_by_reason = dict(selection_diag.get("excluded_by_reason") or {})
    risk_flags = set(_normalize_string_list(bundle.get("risk_flags")))
    return bool(
        "neighboring_concept_bleed" in risk_flags
        or "high_contamination_candidates_present" in risk_flags
        or "background_drift_neighboring_concept_list" in risk_flags
        or int(rejected_by_reason.get("weak_target_alignment") or 0) > 0
        or int(excluded_by_reason.get("neighboring_concept_bleed") or 0) > 0
        or int(excluded_by_reason.get("high_contamination") or 0) > 0
    )


def _structural_issue_signal(bundle: Mapping[str, Any]) -> bool:
    hierarchy_fields_present = bool(bundle.get("topic_path_ids")) or bool(bundle.get("topic_path_labels"))
    survival_floor = dict(bundle.get("survival_floor") or {})
    seed_text = as_text(bundle.get("seed_definition") or survival_floor.get("text"))
    return not as_text(bundle.get("canonical_name")) or not seed_text or not hierarchy_fields_present


def _deterministic_rescue_mode(
    *,
    bundle: Mapping[str, Any],
    candidate: Any,
    value: Mapping[str, Any],
    selected_support_ids: set[str],
    assessments_by_id: Mapping[str, Mapping[str, Any]],
) -> str:
    candidate_id = as_text(getattr(candidate, "overlay_candidate_id", ""))
    assessment = dict(assessments_by_id.get(candidate_id) or getattr(candidate, "assessment", {}) or {})
    classification = as_text(assessment.get("classification"))
    source_text_field = as_text(value.get("source_text_field"))
    selection_reason = as_text(value.get("selection_reason"))
    if classification in {"formula_only_support", "equation_support"} or "formula_only_definition_risk" in _normalize_string_list(bundle.get("risk_flags")):
        return DETERMINISTIC_RESCUE_MODE_FORMULA_PAIR
    if selection_reason.endswith("same_kc_salvage_normalization") or selection_reason.endswith("same_kc_salvage"):
        if candidate_id and candidate_id not in selected_support_ids:
            return DETERMINISTIC_RESCUE_MODE_NEIGHBOR_RECOVERY
        return DETERMINISTIC_RESCUE_MODE_SAME_KC_LOCAL_EXPLICIT
    if _capacity_signal(bundle) and candidate_id and candidate_id not in selected_support_ids:
        return DETERMINISTIC_RESCUE_MODE_BUNDLE_SELECTION
    quote_surface = as_text((getattr(candidate, "row", {}) or {}).get("quote_surface"))
    if source_text_field == "quote_surface" and quote_surface and quote_surface != as_text((getattr(candidate, "row", {}) or {}).get("source_block_text")):
        return DETERMINISTIC_RESCUE_MODE_QUOTE_SURFACE
    if ":" in quote_surface:
        return DETERMINISTIC_RESCUE_MODE_HEADING_EXPLANATION
    return DETERMINISTIC_RESCUE_MODE_SAME_KC_LOCAL_EXPLICIT


def _deterministic_probe(
    *,
    bundle: Mapping[str, Any],
    local_rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any] | None, list[Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    candidates, rows_by_id, assessments_by_id = _local_candidate_pack(local_rows=local_rows)
    if not candidates:
        return None, candidates, rows_by_id, assessments_by_id

    target_descriptor = _kc_descriptor(bundle)
    selected_support_ids = {
        as_text(item.get("overlay_candidate_id"))
        for item in bundle.get("evidence_bundle") or []
        if as_text(item.get("overlay_candidate_id"))
    }

    for candidate in candidates[:12]:
        value, normalized = _definition_draft_supported_single_span_fallback_value(
            field_name="definition_full_candidate",
            candidate=candidate,
            target_descriptor=target_descriptor,
        )
        if not value:
            continue
        final_status = (
            AUTHORITATIVE_DEFINITION_STATUS_NORMALIZED_GROUNDED
            if normalized
            else AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED
        )
        return (
            {
                "candidate_value": value,
                "final_status": final_status,
                "supporting_evidence_ids": _normalize_string_list(value.get("supporting_overlay_candidate_ids")),
                "rescue_mode": _deterministic_rescue_mode(
                    bundle=bundle,
                    candidate=candidate,
                    value=value,
                    selected_support_ids=selected_support_ids,
                    assessments_by_id=assessments_by_id,
                ),
            },
            candidates,
            rows_by_id,
            assessments_by_id,
        )

    blocked_candidate = candidates[0]
    value, normalized, picked = _definition_draft_supported_single_span_fallback_salvage_value(
        definition_candidates=candidates,
        blocked_candidate=blocked_candidate,
        target_descriptor=target_descriptor,
        local_rows=local_rows,
        assessments_by_id=assessments_by_id,
    )
    if not value:
        return None, candidates, rows_by_id, assessments_by_id

    final_status = (
        AUTHORITATIVE_DEFINITION_STATUS_NORMALIZED_GROUNDED
        if normalized
        else AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED
    )
    return (
        {
            "candidate_value": value,
            "final_status": final_status,
            "supporting_evidence_ids": _normalize_string_list(value.get("supporting_overlay_candidate_ids")),
            "rescue_mode": _deterministic_rescue_mode(
                bundle=bundle,
                candidate=picked or blocked_candidate,
                value=value,
                selected_support_ids=selected_support_ids,
                assessments_by_id=assessments_by_id,
            ),
        },
        candidates,
        rows_by_id,
        assessments_by_id,
    )


def _primary_bucket(
    *,
    bundle: Mapping[str, Any],
    local_rows: Sequence[Mapping[str, Any]],
    sibling_anchors: Sequence[Mapping[str, Any]],
    assessments_by_id: Mapping[str, Mapping[str, Any]],
    deterministic_probe: Mapping[str, Any] | None,
) -> str:
    if _structural_issue_signal(bundle):
        return TRIAGE_BUCKET_STRUCTURAL_SEED_OR_HIERARCHY_ISSUE

    if deterministic_probe is not None:
        rescue_mode = as_text(deterministic_probe.get("rescue_mode"))
        if rescue_mode == DETERMINISTIC_RESCUE_MODE_FORMULA_PAIR:
            return TRIAGE_BUCKET_PIPELINE_MISS_FORMULA_EXPLANATION_PAIRING
        if rescue_mode == DETERMINISTIC_RESCUE_MODE_BUNDLE_SELECTION:
            return TRIAGE_BUCKET_PIPELINE_MISS_BUNDLE_OR_CAPACITY_SELECTION
        if rescue_mode == DETERMINISTIC_RESCUE_MODE_NEIGHBOR_RECOVERY:
            return TRIAGE_BUCKET_PIPELINE_MISS_NEIGHBOR_BLEED_OR_LOCAL_ALIGNMENT
        if deterministic_probe.get("final_status") == AUTHORITATIVE_DEFINITION_STATUS_NORMALIZED_GROUNDED:
            return TRIAGE_BUCKET_SOURCE_SUPPORTED_BUT_TOO_THIN_FOR_DIRECT
        return TRIAGE_BUCKET_PIPELINE_MISS_SAME_KC_LOCAL_SUPPORT

    if _neighbor_alignment_signal(bundle):
        return TRIAGE_BUCKET_PIPELINE_MISS_NEIGHBOR_BLEED_OR_LOCAL_ALIGNMENT

    if _capacity_signal(bundle) and (local_rows or sibling_anchors):
        return TRIAGE_BUCKET_PIPELINE_MISS_BUNDLE_OR_CAPACITY_SELECTION

    if local_rows and sibling_anchors:
        return TRIAGE_BUCKET_PIPELINE_MISS_SAME_KC_LOCAL_SUPPORT

    if _formula_pairing_signal(bundle=bundle, local_rows=local_rows, assessments_by_id=assessments_by_id):
        return TRIAGE_BUCKET_PIPELINE_MISS_FORMULA_EXPLANATION_PAIRING

    if local_rows:
        return TRIAGE_BUCKET_SOURCE_SUPPORTED_BUT_TOO_THIN_FOR_DIRECT

    if sibling_anchors:
        return TRIAGE_BUCKET_PIPELINE_MISS_BUNDLE_OR_CAPACITY_SELECTION

    return TRIAGE_BUCKET_GENUINE_SOURCE_SCARCITY


def _evidence_summary(
    *,
    local_rows: Sequence[Mapping[str, Any]],
    sibling_anchors: Sequence[Mapping[str, Any]],
    deterministic_probe: Mapping[str, Any] | None,
) -> str:
    summary_parts = [
        f"same_kc_local_rows={len(local_rows)}",
        f"sibling_success_anchors={len(sibling_anchors)}",
    ]
    if deterministic_probe is not None:
        summary_parts.append(f"deterministic_support_ids={len(_normalize_string_list(deterministic_probe.get('supporting_evidence_ids')))}")
        summary_parts.append(f"deterministic_mode={as_text(deterministic_probe.get('rescue_mode')) or 'none'}")
    return "; ".join(summary_parts)


def _short_text_from_rescue(text: str) -> dict[str, Any]:
    tokens = [item for item in as_text(text).split(" ") if item]
    if not text or len(as_text(text)) > 220 or len(tokens) > 32:
        return {
            "status": "abstained",
            "text": "",
            "supporting_overlay_candidate_ids": [],
            "selection_reason": "definition_short_candidate_step6_7b_abstained",
            "hold_reasons": ["definition_short_unavailable"],
            "source_text_field": "",
        }
    return {
        "status": "grounded",
        "text": as_text(text),
        "supporting_overlay_candidate_ids": [],
        "selection_reason": "definition_short_candidate_step6_7b_from_rescue",
        "hold_reasons": [],
        "source_text_field": "step6_7b_rescue",
    }


def _rescue_bundle_role(assessment: Mapping[str, Any]) -> str:
    classification = as_text(assessment.get("classification"))
    if classification in {"equation_support", "formula_only_support"}:
        return "equation_support"
    if bool(assessment.get("scope_signal")) and not bool(assessment.get("definition_signal")):
        return "context_support"
    return "definition_support"


def _rescue_evidence_item(
    *,
    row: Mapping[str, Any],
    assessment: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "bundle_role": _rescue_bundle_role(assessment),
        "overlay_candidate_id": as_text(row.get("overlay_candidate_id")),
        "selection_score": round(float(assessment.get("selection_score") or row.get("selection_score") or 0.0), 6),
        "candidate_text": as_text(assessment.get("candidate_text") or row.get("quote_surface") or row.get("source_block_text")),
        "quote_surface": as_text(row.get("quote_surface")),
        "source_block_text": as_text(row.get("source_block_text")),
        "doc_id": as_text(row.get("doc_id")),
        "block_id": as_text(row.get("block_id")),
        "page_index": row.get("page_index"),
        "sentence_id": as_text(row.get("sentence_id")),
        "layer": as_text(row.get("layer")),
        "alignment_score": float(row.get("alignment_score") or assessment.get("selection_score") or 0.0),
        "contamination_risk": as_text(row.get("contamination_risk") or "unknown"),
        "provenance_normalization_status": as_text(row.get("provenance_normalization_status") or "original"),
        "quote_verification_status": as_text(row.get("quote_verification_status") or "verified_original"),
        "assessment": {
            "classification": as_text(assessment.get("classification")),
            "definition_signal": bool(assessment.get("definition_signal")),
            "scope_signal": bool(assessment.get("scope_signal")),
            "bare_heading": bool(assessment.get("bare_heading")),
            "formula_lead_in": bool(assessment.get("formula_lead_in")),
            "question_like": bool(assessment.get("question_like")),
        },
    }


def _updated_evidence_bundle(
    *,
    bundle: Mapping[str, Any],
    supporting_ids: Sequence[str],
    rows_by_id: Mapping[str, Mapping[str, Any]],
    assessments_by_id: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    existing_items = [dict(item) for item in bundle.get("evidence_bundle") or [] if isinstance(item, Mapping)]
    existing_by_id = {
        as_text(item.get("overlay_candidate_id")): item
        for item in existing_items
        if as_text(item.get("overlay_candidate_id"))
    }
    ordered: list[dict[str, Any]] = []
    for candidate_id in _normalize_string_list(supporting_ids):
        if candidate_id in existing_by_id:
            ordered.append(existing_by_id[candidate_id])
            continue
        row = dict(rows_by_id.get(candidate_id) or {})
        if not row:
            continue
        assessment = dict(assessments_by_id.get(candidate_id) or assess_overlay_candidate(row))
        ordered.append(_rescue_evidence_item(row=row, assessment=assessment))
    seen_ids = {as_text(item.get("overlay_candidate_id")) for item in ordered}
    for item in existing_items:
        candidate_id = as_text(item.get("overlay_candidate_id"))
        if candidate_id in seen_ids:
            continue
        ordered.append(item)
        seen_ids.add(candidate_id)
    return ordered


def _cleaned_risk_flags(bundle: Mapping[str, Any]) -> list[str]:
    flags = [item for item in _normalize_string_list(bundle.get("risk_flags")) if item not in RISK_FLAGS_RESOLVED_BY_RESCUE]
    _append_unique(flags, "step6_7b_rescue_applied")
    return flags


def _cleaned_hold_reasons(bundle: Mapping[str, Any]) -> list[str]:
    reasons = _normalize_string_list(bundle.get("hold_reasons"))
    return [item for item in reasons if item not in READINESS_REASONS_RESOLVED_BY_RESCUE]


def _cleaned_field_hold_reasons(bundle: Mapping[str, Any]) -> dict[str, list[str]]:
    field_hold_reasons = dict(bundle.get("field_hold_reasons") or {})
    out: dict[str, list[str]] = {}
    for field_name, values in field_hold_reasons.items():
        cleaned = [item for item in _normalize_string_list(values) if item not in READINESS_REASONS_RESOLVED_BY_RESCUE]
        if cleaned:
            out[str(field_name)] = cleaned
    return out


def _cleaned_review_readiness(bundle: Mapping[str, Any]) -> dict[str, Any]:
    original = dict(bundle.get("review_readiness") or {})
    reasons = [item for item in _normalize_string_list(original.get("reasons")) if item not in READINESS_REASONS_RESOLVED_BY_RESCUE]
    _append_unique(reasons, "step6_7b_rescue_applied")
    return {
        "label": REVIEW_READINESS_NEEDS_ATTENTION,
        "survives_review_lane": True,
        "needs_attention": True,
        "draft_status_compatibility": "draft_ready_with_holds",
        "reasons": reasons,
    }


def _rescued_trust_state(bundle: Mapping[str, Any], *, scope_grounded: bool) -> dict[str, Any]:
    trust_label = TRUST_STATE_GROUNDED if scope_grounded else TRUST_STATE_GROUNDED_WITH_GAPS
    return {
        "label": trust_label,
        "definition_grounded": True,
        "scope_grounded": scope_grounded,
        "context_status": as_text(((bundle.get("context_layer") or {}).get("status"))) or CONTEXT_LAYER_STATUS_GROUNDED,
        "low_trust": False,
    }


def _source_set_ids(bundle: Mapping[str, Any], field_name: str) -> list[str]:
    provenance = dict((bundle.get("field_provenance_map") or {}).get(field_name) or {})
    out = _normalize_string_list(provenance.get("source_set_ids"))
    if not out and as_text(bundle.get("source_set_id")):
        out.append(as_text(bundle.get("source_set_id")))
    return out


def _source_run_ids(bundle: Mapping[str, Any], field_name: str) -> list[str]:
    provenance = dict((bundle.get("field_provenance_map") or {}).get(field_name) or {})
    out = _normalize_string_list(provenance.get("source_run_ids"))
    if not out and as_text(bundle.get("source_run_id")):
        out.append(as_text(bundle.get("source_run_id")))
    return out


def _original_raw_snapshot(bundle: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "authoritative_definition_status": as_text(bundle.get("authoritative_definition_status")),
        "definition_full_candidate": copy.deepcopy(dict(bundle.get("definition_full_candidate") or {})),
        "definition_short_candidate": copy.deepcopy(dict(bundle.get("definition_short_candidate") or {})),
        "enrichment_layer": copy.deepcopy(dict(bundle.get("enrichment_layer") or {})),
        "field_provenance_map": copy.deepcopy(dict(bundle.get("field_provenance_map") or {})),
        "review_readiness": copy.deepcopy(dict(bundle.get("review_readiness") or {})),
        "trust_state": copy.deepcopy(dict(bundle.get("trust_state") or {})),
        "risk_flags": _normalize_string_list(bundle.get("risk_flags")),
        "hold_reasons": _normalize_string_list(bundle.get("hold_reasons")),
        "evidence_bundle_overlay_candidate_ids": [
            as_text(item.get("overlay_candidate_id"))
            for item in bundle.get("evidence_bundle") or []
            if as_text(item.get("overlay_candidate_id"))
        ],
    }


def _model_runtime(
    model_rescue_cfg: Mapping[str, Any],
    *,
    model_invoker: Any = None,
) -> Step67ModelRuntime:
    model_profile = normalize_step67_model_profile(model_rescue_cfg)
    validate_supported_step67_model_profile(model_profile, field_prefix="model_rescue")
    return Step67ModelRuntime(
        base_url=as_text(model_rescue_cfg.get("generation_base_url")),
        model=as_text(model_profile.get("generation_model") or model_rescue_cfg.get("generation_model_alias")),
        max_retries=int(model_rescue_cfg.get("max_retries", 2)),
        num_ctx=int(model_rescue_cfg.get("num_ctx", 8192)),
        timeout_seconds=float(model_rescue_cfg.get("timeout_seconds", 120.0)),
        temperature=float(model_rescue_cfg.get("temperature", 0.0)),
        top_p=float(model_rescue_cfg.get("top_p", 1.0)),
        repeat_penalty=float(model_rescue_cfg.get("repeat_penalty", 1.0)),
        think=model_rescue_cfg.get("think"),
        model_profile=model_profile,
        draft_invoker=model_invoker,
    )


def _call_model_rescue(
    *,
    runtime: Step67ModelRuntime,
    request_payload: Mapping[str, Any],
) -> dict[str, Any]:
    model_profile = normalize_step67_model_profile(
        runtime.model_profile
        or {
            "generation_model": runtime.model,
            "thinking_enabled": runtime.think,
        }
    )
    messages = apply_step67_model_profile_to_messages(
        [
        {
            "role": "system",
            "content": (
                "You are performing bounded focused evidence rescue for a seed-floor fallback KC. "
                "Use only the provided target-evidence items. "
                "Sibling-success regions were used only to prioritize retrieval neighborhoods, not as final evidence. "
                "Do not use outside knowledge. "
                "If the evidence is insufficient, abstain. "
                "Return only schema-valid JSON."
            ),
        },
        {
            "role": "user",
            "content": (
                "Return direct_grounded only for a standalone supported definition. "
                "Return normalized_grounded only for a source-faithful conservative normalization. "
                "Return abstain when evidence is thin, structurally unsafe, or concept alignment is doubtful.\n\n"
                f"{request_payload}"
            ),
        },
        ],
        model_profile,
    )

    attempts = max(1, int(runtime.max_retries or 1))
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            if runtime.draft_invoker is not None:
                payload = runtime.draft_invoker(
                    {
                        "phase": "step6_7b_model_rescue",
                        "request_payload": dict(request_payload),
                        "schema": MODEL_RESCUE_SCHEMA,
                        "messages": messages,
                        "model": runtime.model,
                        "model_profile": dict(model_profile),
                        "attempt": attempt,
                        "attempts_total": attempts,
                    }
                )
                if isinstance(payload, tuple):
                    payload = payload[0]
                if not isinstance(payload, Mapping):
                    raise RuntimeError("step6_7b model invoker returned non-mapping payload")
                return dict(payload)

            payload, _, _ = ollama_chat_json(
                base_url=runtime.base_url,
                model=runtime.model,
                messages=messages,
                format_schema=MODEL_RESCUE_SCHEMA,
                temperature=float(runtime.temperature),
                top_p=float(runtime.top_p),
                num_ctx=int(runtime.num_ctx),
                repeat_penalty=float(runtime.repeat_penalty),
                think=step67_model_profile_think_flag(model_profile),
                response_parse_mode=str(model_profile.get("response_parse_mode") or ""),
                strip_thought_block_before_parse=bool(model_profile.get("strip_thought_block_before_parse")),
                timeout_s=float(runtime.timeout_seconds),
            )
            if not isinstance(payload, Mapping):
                raise RuntimeError("step6_7b model rescue returned non-object payload")
            return dict(payload)
        except Exception as exc:
            last_error = exc
            if attempt >= attempts:
                break

    assert last_error is not None
    raise RuntimeError(
        f"step6_7b model rescue failed after {attempts} attempt(s): "
        f"{last_error.__class__.__name__}: {last_error}"
    ) from last_error


def _model_rescue_error_outcome(exc: Exception) -> str:
    message = as_text(exc).lower()
    if "ollama chat response content was empty" in message:
        return "error_empty_content"
    if "could not parse ollama content as a json object" in message:
        return "error_json_parse"
    if "json object" in message or "jsondecodeerror" in message:
        return "error_json_parse"
    if "timed out" in message or "timeout" in message:
        return "error_timeout"
    return f"error_{exc.__class__.__name__.lower()}"


def _contains_any_phrase(text: str, phrases: Sequence[str]) -> bool:
    lowered = as_text(text).lower()
    return any(phrase in lowered for phrase in phrases if phrase)


def _model_direct_output_rejection_reason(*, text: str) -> str:
    value = as_text(text)
    lowered = value.lower()

    meta_evaluator_phrases = (
        "evidence item",
        "evidence items",
        "seed definition",
        "seed_definition",
        "page ",
        "directly matches",
        "corresponds exactly",
        "aligning with",
        "aligns with",
        "matching the seed definition",
        "provides a direct algorithmic implementation",
        "the evidence also states",
        "the evidence item from",
        "violating standalone definition requirement",
    )
    if _contains_any_phrase(lowered, meta_evaluator_phrases):
        return "meta_evaluator_language"

    worked_example_phrases = (
        "for example",
        "noting that",
        "consider the following",
        "suppose that",
        "suppose we",
        "f00=",
        "f01=",
        "f10=",
        "f11=",
    )
    if _contains_any_phrase(lowered, worked_example_phrases):
        return "worked_example_surface"

    return ""

def _model_evidence_items(
    *,
    local_rows: Sequence[Mapping[str, Any]],
    assessments_by_id: Mapping[str, Mapping[str, Any]],
    max_items: int,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in list(local_rows)[: max(1, max_items)]:
        candidate_id = as_text(row.get("overlay_candidate_id"))
        if not candidate_id:
            continue
        assessment = dict(assessments_by_id.get(candidate_id) or assess_overlay_candidate(row))
        items.append(
            {
                "overlay_candidate_id": candidate_id,
                "candidate_text": as_text(assessment.get("candidate_text") or row.get("quote_surface") or row.get("source_block_text")),
                "quote_surface": as_text(row.get("quote_surface")),
                "source_block_text": as_text(row.get("source_block_text")),
                "classification": as_text(assessment.get("classification")),
                "definition_signal": bool(assessment.get("definition_signal")),
                "scope_signal": bool(assessment.get("scope_signal")),
                "doc_id": as_text(row.get("doc_id")),
                "page_index": row.get("page_index"),
                "selection_focus_score": float(row.get("step6_7b_focus_score") or row.get("selection_score") or 0.0),
                "selection_focus_reasons": _normalize_string_list(row.get("step6_7b_focus_reasons")),
            }
        )
    return items


def _bounded_model_rescue(
    *,
    bundle: Mapping[str, Any],
    local_rows: Sequence[Mapping[str, Any]],
    sibling_anchors: Sequence[Mapping[str, Any]],
    assessments_by_id: Mapping[str, Mapping[str, Any]],
    model_rescue_cfg: Mapping[str, Any],
    model_invoker: Any = None,
) -> tuple[dict[str, Any] | None, str]:
    execution_mode = as_text(model_rescue_cfg.get("execution_mode") or MODEL_RESCUE_DISABLED).lower()
    if execution_mode != MODEL_RESCUE_LLM:
        return None, "disabled"

    if model_invoker is None:
        ensure_llm_runtime_available(model_rescue_cfg)

    runtime = _model_runtime(model_rescue_cfg, model_invoker=model_invoker)
    max_items = max(1, int(model_rescue_cfg.get("max_evidence_items", 8)))
    evidence_items = _model_evidence_items(
        local_rows=local_rows,
        assessments_by_id=assessments_by_id,
        max_items=max_items,
    )
    if not evidence_items:
        return None, "abstained_no_target_evidence"

    allowed_support_ids = {item["overlay_candidate_id"] for item in evidence_items}
    request_payload = {
        "kc_id": as_text(bundle.get("kc_id")),
        "canonical_name": as_text(bundle.get("canonical_name")),
        "aliases": _normalize_string_list(bundle.get("aliases")),
        "seed_definition": as_text(bundle.get("seed_definition")),
        "topic_path_ids": _normalize_string_list(bundle.get("topic_path_ids")),
        "topic_path_labels": _normalize_string_list(bundle.get("topic_path_labels")),
        "current_authoritative_definition_status": as_text(bundle.get("authoritative_definition_status")),
        "allowed_statuses": [
            AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED,
            AUTHORITATIVE_DEFINITION_STATUS_NORMALIZED_GROUNDED,
            "abstain",
        ],
        "evidence_strategy": "same_kc_target_evidence_prioritized_by_sibling_success_neighborhoods",
        "sibling_anchor_summary": [
            {
                "doc_id": as_text(item.get("doc_id")),
                "page_index": item.get("page_index"),
            }
            for item in list(sibling_anchors)[:8]
        ],
        "evidence_items": evidence_items,
    }

    try:
        payload = _call_model_rescue(runtime=runtime, request_payload=request_payload)
    except Exception as exc:
        return None, _model_rescue_error_outcome(exc)

    decision = dict(payload.get("decision") or {})
    status = as_text(decision.get("status"))

    if status == "abstain":
        return None, as_text(decision.get("abstention_reason")) or "abstained"

    if status not in {
        AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED,
        AUTHORITATIVE_DEFINITION_STATUS_NORMALIZED_GROUNDED,
    }:
        return None, "invalid_status"

    text = as_text(decision.get("text"))
    support_ids = _normalize_string_list(decision.get("supporting_overlay_candidate_ids"))
    if not text or not support_ids or any(item not in allowed_support_ids for item in support_ids):
        return None, "invalid_support_contract"

    if status == AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED:
        rejection_reason = _model_direct_output_rejection_reason(text=text)
        if rejection_reason:
            return None, f"rejected_direct_{rejection_reason}"

    return (
        {
            "candidate_value": {
                "status": "grounded",
                "text": text,
                "supporting_overlay_candidate_ids": support_ids,
                "selection_reason": "definition_full_candidate_step6_7b_bounded_model_rescue",
                "source_text_field": "step6_7b_focused_model_rescue",
            },
            "final_status": status,
            "supporting_evidence_ids": support_ids,
            "rescue_mode": BOUNDED_MODEL_RESCUE_MODE,
        },
        "rescued",
    )


def _apply_rescue(
    *,
    bundle: Mapping[str, Any],
    rescue_payload: Mapping[str, Any],
    triage_row: Mapping[str, Any],
    rows_by_id: Mapping[str, Mapping[str, Any]],
    assessments_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    output = copy.deepcopy(dict(bundle))
    candidate_value = dict(rescue_payload.get("candidate_value") or {})
    final_status = as_text(rescue_payload.get("final_status"))
    supporting_ids = _normalize_string_list(rescue_payload.get("supporting_evidence_ids"))
    scope_grounded = as_text(((bundle.get("scope_layer") or {}).get("status"))) == SCOPE_LAYER_STATUS_GROUNDED

    output["authoritative_definition_status"] = final_status
    output["draft_status"] = "draft_ready_with_holds"
    output["definition_full_candidate"] = copy.deepcopy(candidate_value)
    output["definition_short_candidate"] = _short_text_from_rescue(as_text(candidate_value.get("text")))
    output["enrichment_layer"] = {
        "status": "grounded",
        "text": as_text(candidate_value.get("text")),
        "short_text": as_text(output["definition_short_candidate"].get("text")) or as_text(candidate_value.get("text")),
        "supporting_overlay_candidate_ids": supporting_ids,
        "source_field": "step6_7b.definition_full_candidate",
    }
    output["trust_state"] = _rescued_trust_state(bundle, scope_grounded=scope_grounded)
    output["review_readiness"] = _cleaned_review_readiness(bundle)
    output["risk_flags"] = _cleaned_risk_flags(bundle)
    output["hold_reasons"] = _cleaned_hold_reasons(bundle)
    output["field_hold_reasons"] = _cleaned_field_hold_reasons(bundle)

    field_provenance_map = copy.deepcopy(dict(bundle.get("field_provenance_map") or {}))
    field_provenance_map["definition_full_candidate"] = {
        "status": "grounded",
        "overlay_candidate_ids": supporting_ids,
        "source_set_ids": _source_set_ids(bundle, "definition_full_candidate"),
        "source_run_ids": _source_run_ids(bundle, "definition_full_candidate"),
    }
    field_provenance_map["definition_short_candidate"] = {
        "status": as_text(output["definition_short_candidate"].get("status")) or "abstained",
        "overlay_candidate_ids": [],
        "source_set_ids": _source_set_ids(bundle, "definition_short_candidate") or _source_set_ids(bundle, "definition_full_candidate"),
        "source_run_ids": _source_run_ids(bundle, "definition_short_candidate") or _source_run_ids(bundle, "definition_full_candidate"),
    }
    evidence_bundle_provenance = dict(field_provenance_map.get("evidence_bundle") or {})
    field_provenance_map["evidence_bundle"] = {
        "status": evidence_bundle_provenance.get("status") or "grounded",
        "overlay_candidate_ids": _normalize_string_list(
            list(evidence_bundle_provenance.get("overlay_candidate_ids") or []) + supporting_ids
        ),
        "source_set_ids": _normalize_string_list(evidence_bundle_provenance.get("source_set_ids")) or _source_set_ids(bundle, "definition_full_candidate"),
        "source_run_ids": _normalize_string_list(evidence_bundle_provenance.get("source_run_ids")) or _source_run_ids(bundle, "definition_full_candidate"),
    }
    output["field_provenance_map"] = field_provenance_map
    output["evidence_bundle"] = _updated_evidence_bundle(
        bundle=bundle,
        supporting_ids=supporting_ids,
        rows_by_id=rows_by_id,
        assessments_by_id=assessments_by_id,
    )
    output["step6_7b_contract_version"] = STEP67B_CONTRACT_VERSION
    output["seed_floor_triage"] = copy.deepcopy(dict(triage_row))
    return output


def triage_seed_floor_bundle_row(
    *,
    bundle: Mapping[str, Any],
    overlay_rows_by_kc: Mapping[str, Sequence[Mapping[str, Any]]],
    sibling_anchor_index: Mapping[tuple[str, ...], Sequence[Mapping[str, Any]]],
    model_rescue_cfg: Mapping[str, Any] | None = None,
    model_invoker: Any = None,
) -> SeedFloorBundleTriageResult:
    output = copy.deepcopy(dict(bundle))
    output["step6_7b_contract_version"] = STEP67B_CONTRACT_VERSION
    if as_text(bundle.get("authoritative_definition_status")) != AUTHORITATIVE_DEFINITION_STATUS_SEED_FLOOR_FALLBACK:
        return SeedFloorBundleTriageResult(bundle=output, triage_row=None)

    kc_id = as_text(bundle.get("kc_id"))
    local_rows, sibling_anchors = _focused_local_rows(
        bundle=bundle,
        overlay_rows_by_kc=overlay_rows_by_kc,
        sibling_anchor_index=sibling_anchor_index,
    )
    deterministic_probe, candidates, rows_by_id, assessments_by_id = _deterministic_probe(
        bundle=bundle,
        local_rows=local_rows,
    )
    primary_bucket = _primary_bucket(
        bundle=bundle,
        local_rows=local_rows,
        sibling_anchors=sibling_anchors,
        assessments_by_id=assessments_by_id,
        deterministic_probe=deterministic_probe,
    )
    rescue_eligible = primary_bucket in RESCUE_ELIGIBLE_BUCKETS

    deterministic_rescue_attempted = False
    deterministic_rescue_outcome = "not_eligible"
    bounded_model_rescue_attempted = False
    bounded_model_rescue_outcome = "not_eligible"
    final_status = AUTHORITATIVE_DEFINITION_STATUS_SEED_FLOOR_FALLBACK
    rescue_mode = ""
    supporting_evidence_ids: list[str] = []
    rescue_payload: dict[str, Any] | None = None

    model_cfg = dict(model_rescue_cfg or {})
    force_model_validation = bool(model_cfg.get("validation_force_model_for_all_rescue_eligible", False))

    if rescue_eligible:
        deterministic_rescue_attempted = True
        if deterministic_probe is None:
            deterministic_rescue_outcome = "no_rescue"
            bounded_model_rescue_outcome = "not_attempted_yet"
        else:
            deterministic_candidate = dict(deterministic_probe)
            deterministic_candidate_status = (
                as_text(deterministic_candidate.get("final_status"))
                or AUTHORITATIVE_DEFINITION_STATUS_SEED_FLOOR_FALLBACK
            )
            deterministic_rescue_outcome = (
                "rescued_direct"
                if deterministic_candidate_status == AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED
                else "rescued_normalized"
            )

            if force_model_validation:
                bounded_model_rescue_outcome = "validation_forced_model_pending"
            else:
                rescue_payload = deterministic_candidate
                final_status = deterministic_candidate_status
                rescue_mode = as_text(rescue_payload.get("rescue_mode"))
                supporting_evidence_ids = _normalize_string_list(rescue_payload.get("supporting_evidence_ids"))
                bounded_model_rescue_outcome = "skipped_after_deterministic_rescue"

    if rescue_eligible and rescue_payload is None:
        execution_mode = as_text(model_cfg.get("execution_mode") or MODEL_RESCUE_DISABLED).lower()
        if execution_mode == MODEL_RESCUE_LLM:
            bounded_model_rescue_attempted = True
            model_probe, bounded_model_rescue_outcome = _bounded_model_rescue(
                bundle=bundle,
                local_rows=local_rows,
                sibling_anchors=sibling_anchors,
                assessments_by_id=assessments_by_id,
                model_rescue_cfg=model_cfg,
                model_invoker=model_invoker,
            )
            if model_probe is not None:
                rescue_payload = dict(model_probe)
                final_status = as_text(rescue_payload.get("final_status")) or AUTHORITATIVE_DEFINITION_STATUS_SEED_FLOOR_FALLBACK
                rescue_mode = as_text(rescue_payload.get("rescue_mode"))
                supporting_evidence_ids = _normalize_string_list(rescue_payload.get("supporting_evidence_ids"))
                bounded_model_rescue_outcome = (
                    "rescued_direct"
                    if final_status == AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED
                    else "rescued_normalized"
                )
        else:
            bounded_model_rescue_outcome = "disabled"

    triage_row = {
        "kc_id": kc_id,
        "original_status": AUTHORITATIVE_DEFINITION_STATUS_SEED_FLOOR_FALLBACK,
        "primary_bucket": primary_bucket,
        "secondary_reasons": _bucket_secondary_reasons(
            bundle,
            local_rows=local_rows,
            sibling_anchors=sibling_anchors,
        ),
        "sibling_success_anchor_count": len(sibling_anchors),
        "rescue_eligible": rescue_eligible,
        "validation_force_model_for_all_rescue_eligible": force_model_validation,
        "deterministic_rescue_attempted": deterministic_rescue_attempted,
        "deterministic_rescue_outcome": deterministic_rescue_outcome,
        "bounded_model_rescue_attempted": bounded_model_rescue_attempted,
        "bounded_model_rescue_outcome": bounded_model_rescue_outcome,
        "final_status": final_status,
        "evidence_summary": _evidence_summary(
            local_rows=local_rows,
            sibling_anchors=sibling_anchors,
            deterministic_probe=deterministic_probe,
        ),
        "rescue_mode": rescue_mode or "retained_seed_floor",
        "supporting_evidence_ids": supporting_evidence_ids,
        "step6_7b_contract_version": STEP67B_CONTRACT_VERSION,
        "original_step6_7_raw": _original_raw_snapshot(bundle),
    }

    if rescue_payload is not None:
        output = _apply_rescue(
            bundle=bundle,
            rescue_payload=rescue_payload,
            triage_row=triage_row,
            rows_by_id=rows_by_id,
            assessments_by_id=assessments_by_id,
        )
    else:
        output["seed_floor_triage"] = copy.deepcopy(dict(triage_row))
    return SeedFloorBundleTriageResult(bundle=output, triage_row=triage_row)


def emit_seed_floor_triaged_bundles(
    *,
    output_dir: Path,
    draft_rows: Sequence[Mapping[str, Any]],
    overlay_rows: Sequence[Mapping[str, Any]],
    model_rescue_cfg: Mapping[str, Any] | None = None,
    model_invoker: Any = None,
) -> SeedFloorTriageEmissionResult:
    overlay_rows_by_kc: dict[str, list[Mapping[str, Any]]] = {}
    for row in overlay_rows:
        kc_id = as_text(row.get("kc_id"))
        if not kc_id:
            continue
        overlay_rows_by_kc.setdefault(kc_id, []).append(row)

    sibling_anchor_index = _build_sibling_success_anchor_index(draft_rows=draft_rows)

    bundles: list[dict[str, Any]] = []
    triage_rows: list[dict[str, Any]] = []
    bucket_counts: Counter[str] = Counter()
    deterministic_outcomes: Counter[str] = Counter()
    bounded_model_outcomes: Counter[str] = Counter()
    final_status_counts: Counter[str] = Counter()

    for row in draft_rows:
        result = triage_seed_floor_bundle_row(
            bundle=row,
            overlay_rows_by_kc=overlay_rows_by_kc,
            sibling_anchor_index=sibling_anchor_index,
            model_rescue_cfg=model_rescue_cfg,
            model_invoker=model_invoker,
        )
        bundles.append(result.bundle)
        if result.triage_row is None:
            continue
        triage_rows.append(result.triage_row)
        bucket_counts[as_text(result.triage_row.get("primary_bucket"))] += 1
        deterministic_outcomes[as_text(result.triage_row.get("deterministic_rescue_outcome"))] += 1
        bounded_model_outcomes[as_text(result.triage_row.get("bounded_model_rescue_outcome"))] += 1
        final_status_counts[as_text(result.triage_row.get("final_status"))] += 1

    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = output_dir / "kc_draft_bundles_rescued.jsonl"
    triage_path = output_dir / "triage_rows.jsonl"
    stats_path = output_dir / "triage_stats.json"
    write_jsonl(bundle_path, bundles)
    write_jsonl(triage_path, triage_rows)

    stats = {
        "schema_version": "1.0",
        "stage": STEP67B_STAGE_NAME,
        "contract_version": STEP67B_CONTRACT_VERSION,
        "input_bundle_count": len(draft_rows),
        "output_bundle_count": len(bundles),
        "triaged_fallback_count": len(triage_rows),
        "primary_bucket_counts": dict(bucket_counts),
        "rescue_eligible_count": sum(1 for row in triage_rows if bool(row.get("rescue_eligible"))),
        "deterministic_rescue_outcome_counts": dict(deterministic_outcomes),
        "bounded_model_rescue_outcome_counts": dict(bounded_model_outcomes),
        "final_status_counts": dict(final_status_counts),
        "rescued_direct_count": final_status_counts[AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED],
        "rescued_normalized_count": final_status_counts[AUTHORITATIVE_DEFINITION_STATUS_NORMALIZED_GROUNDED],
        "unresolved_fallback_count": final_status_counts[AUTHORITATIVE_DEFINITION_STATUS_SEED_FLOOR_FALLBACK],
    }
    write_json(stats_path, stats)
    return SeedFloorTriageEmissionResult(
        bundle_path=bundle_path,
        triage_path=triage_path,
        stats_path=stats_path,
        bundle_count=len(bundles),
        triaged_count=len(triage_rows),
        stats=stats,
    )
