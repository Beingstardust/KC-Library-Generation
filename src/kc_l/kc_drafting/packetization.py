from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kc_l.kc_drafting.contracts import (
    AUTHORITATIVE_DEFINITION_STATUS_INSUFFICIENT_SUPPORT,
    AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED,
    AUTHORITATIVE_DEFINITION_STATUS_NORMALIZED_GROUNDED,
    COVERAGE_STATE_STATUS_REPRESENTED,
    CONTEXT_LAYER_STATUS_FALLBACK,
    CONTEXT_LAYER_STATUS_GROUNDED,
    CONTEXT_LAYER_STATUS_MISSING,
    ENRICHMENT_LAYER_STATUS_GROUNDED,
    REVIEW_READINESS_COVERAGE_ONLY,
    REVIEW_READINESS_NEEDS_ATTENTION,
    REVIEW_READINESS_READY,
    SCOPE_LAYER_STATUS_ABSTAINED,
    SCOPE_LAYER_STATUS_GROUNDED,
    STEP67_SEMANTIC_CONTRACT_VERSION,
    TRUST_STATE_COVERAGE_ONLY,
    TRUST_STATE_COVERAGE_ONLY_WITH_RISKS,
    TRUST_STATE_GROUNDED,
    TRUST_STATE_GROUNDED_WITH_GAPS,
)
from kc_l.kc_drafting.hierarchy_refs import typed_topic_hierarchy_fields
from kc_l.kc.review_packets import (
    CONTENT_SOURCE_MODE_DRAFT_PRIMARY,
    REVIEW_PACKET_STATE,
    validate_review_packet,
)
from kc_l.kc.supervision import compute_review_priority, derive_system_recommendation
from kc_l.utils.json_io import write_json, write_jsonl


RESTARTED_GENERATION_STAGE = "step6_8_restarted_review_packet_emission"
RESTARTED_PACKET_RULE_VERSION = "step6.8.review_packet_restart.v1"
RESTARTED_EVIDENCE_EXTRACTION_METHOD = "step6_8_restarted_review_packet_evidence"
SCOPE_GAP_FLAG = "scope_gap_reviewer_editable"
SCOPE_CANDIDATE_ABSTAINED_FLAG = "scope_candidate_abstained"
DRAFT_READY_WITH_HOLDS_FLAG = "draft_ready_with_holds"
REVIEW_QUEUE_WEAK_COVERAGE_FLAG = "review_queue_weak_coverage"
EXCLUDED_HELD_REASON = "excluded_held_draft_bundle"
MIXED_FOREIGN_DEFINITION_SUPPORT_FLAG = "definition_decisive_support_mixed_foreign"
HELD_REVIEW_SALVAGE_FLAG = "held_bundle_review_salvage"
DEFINITION_REVIEW_SALVAGE_UNVERIFIED_FLAG = "definition_review_salvage_unverified"
COVERAGE_ONLY_ACTIVE_FLAG = "coverage_only_active"
DEFINITION_ENRICHMENT_MISSING_FLAG = "definition_enrichment_missing"
CONTEXT_FALLBACK_ACTIVE_FLAG = "context_fallback_active"
CONTEXT_BUNDLE_MISSING_FLAG = "context_bundle_missing"
LOW_TRUST_SURVIVOR_FLAG = "coverage_only_survivor"
REVIEW_NEEDS_ATTENTION_FLAG = "review_needs_attention"
LOW_TRUST_REVIEW_FLAG = "coverage_only_review"
INVALID_PAGE_INDEX_DROPPED_FLAG = "invalid_page_index_dropped"
HIGH_CONTAMINATION_CANDIDATES_PRESENT_FLAG = "high_contamination_candidates_present"
PROVENANCE_REPAIRS_PRESENT_FLAG = "provenance_repairs_present"
NEIGHBORING_CONCEPT_BLEED_FLAG = "neighboring_concept_bleed"
DEFINITION_VERIFICATION_RUNTIME_FAILED_FLAG = "definition_verification_runtime_failed"
SCOPE_VERIFICATION_RUNTIME_FAILED_FLAG = "scope_verification_runtime_failed"
PROCEDURE_CONTEXT_ONLY_FLAG = "procedure_context_only"
COVERAGE_ONLY_KEEP_AND_EDIT_REASON = "coverage_only_keep_and_edit"
SUSPICIOUS_COVERAGE_ONLY_PACKET_REASON = "suspicious_coverage_only_packet"
REVIEW_EDIT_REQUIRED_REASON = "review_edit_required"
STRUCTURAL_COMPAT_OR_HIERARCHY_ISSUE_BUCKET = "structural_seed_or_hierarchy_issue"
APPROVE_READY_BLOCKED_BY_STRONG_RISK_REASON = "approve_ready_blocked_by_strong_risk"
APPROVE_READY_BLOCKED_BY_INCOMPLETE_REVIEW_STATE_REASON = "approve_ready_blocked_by_incomplete_review_state"
COVERAGE_ONLY_RECOMMENDATION_ALLOWED_REASON_CODES = {
    "definition_short_contract_fail",
    "support_contract_downgraded",
    "priority_bucket:low_support",
}
APPROVE_READY_BLOCKING_FLAGS = {
    HIGH_CONTAMINATION_CANDIDATES_PRESENT_FLAG,
    PROVENANCE_REPAIRS_PRESENT_FLAG,
    INVALID_PAGE_INDEX_DROPPED_FLAG,
    NEIGHBORING_CONCEPT_BLEED_FLAG,
    DEFINITION_VERIFICATION_RUNTIME_FAILED_FLAG,
    SCOPE_VERIFICATION_RUNTIME_FAILED_FLAG,
    PROCEDURE_CONTEXT_ONLY_FLAG,
}
COVERAGE_ONLY_RECOMMENDATION_BLOCKING_FLAGS = {
    MIXED_FOREIGN_DEFINITION_SUPPORT_FLAG,
    CONTEXT_BUNDLE_MISSING_FLAG,
    HELD_REVIEW_SALVAGE_FLAG,
    DEFINITION_REVIEW_SALVAGE_UNVERIFIED_FLAG,
    HIGH_CONTAMINATION_CANDIDATES_PRESENT_FLAG,
    NEIGHBORING_CONCEPT_BLEED_FLAG,
    DEFINITION_VERIFICATION_RUNTIME_FAILED_FLAG,
    SCOPE_VERIFICATION_RUNTIME_FAILED_FLAG,
    PROCEDURE_CONTEXT_ONLY_FLAG,
}


@dataclass(frozen=True)
class PacketExclusion:
    kc_candidate_id: str
    draft_status: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RestartedReviewPacketEmissionResult:
    output_dir: Path
    packet_path: Path
    summary_path: Path
    preview_path: Path
    packet_count: int
    excluded_candidate_count: int


@dataclass(frozen=True)
class EvidenceSpanBuildResult:
    spans: tuple[dict[str, Any], ...]
    dropped_invalid_page_index_span_count: int


@dataclass(frozen=True)
class RestartedReviewPacketBuildResult:
    packet: dict[str, Any]
    dropped_invalid_page_index_span_count: int


def _append_unique(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return None


def _quote_verified(value: Any) -> bool:
    direct = _as_bool(value)
    if direct is not None:
        return direct
    text = _as_text(value).lower()
    return text.startswith("verified")


def _coerce_non_negative_page_index(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            coerced = int(text)
        except ValueError:
            return None
        return coerced if coerced >= 0 else None
    return None


def _normalize_bbox(value: Any) -> list[float] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 4:
        return None
    out: list[float] = []
    for item in value:
        if not isinstance(item, (int, float)):
            return None
        out.append(float(item))
    return out


def _normalize_string_list(values: Any) -> list[str]:
    out: list[str] = []
    for value in values or []:
        text = _as_text(value)
        if text:
            _append_unique(out, text)
    return out


def _normalize_field_hold_reasons(payload: Mapping[str, Any]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for key in ("definition_full_candidate", "definition_short_candidate", "scope_candidate"):
        values = _normalize_string_list(payload.get(key))
        if values:
            out[key] = values
    return out


def _normalize_field_provenance_entry(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    obj = dict(payload or {})
    return {
        "status": _as_text(obj.get("status")) or "unknown",
        "overlay_candidate_ids": _normalize_string_list(obj.get("overlay_candidate_ids")),
        "source_set_ids": _normalize_string_list(obj.get("source_set_ids")),
        "source_run_ids": _normalize_string_list(obj.get("source_run_ids")),
    }


def _normalize_field_provenance_map(payload: Mapping[str, Any]) -> dict[str, Any]:
    obj = dict(payload or {})
    return {
        "definition_full_candidate": _normalize_field_provenance_entry(obj.get("definition_full_candidate")),
        "definition_short_candidate": _normalize_field_provenance_entry(obj.get("definition_short_candidate")),
        "scope_candidate": _normalize_field_provenance_entry(obj.get("scope_candidate")),
        "evidence_bundle": _normalize_field_provenance_entry(obj.get("evidence_bundle")),
    }


def _candidate_payload(bundle: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = bundle.get(key)
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _canonicalized_candidate_payload(bundle: Mapping[str, Any], key: str) -> dict[str, Any]:
    return _candidate_payload(bundle, f"{key}_canonicalized")


def _semantic_payload(bundle: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = bundle.get(key)
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _semantic_contract_present(bundle: Mapping[str, Any]) -> bool:
    return _as_text(bundle.get("semantic_contract_version")) == STEP67_SEMANTIC_CONTRACT_VERSION


def _bundle_risk_flags(bundle: Mapping[str, Any]) -> list[str]:
    risk_flags = _normalize_string_list(bundle.get("risk_flags"))
    if risk_flags:
        return risk_flags
    return _normalize_string_list(bundle.get("contamination_flags"))


def _bundle_review_readiness(bundle: Mapping[str, Any]) -> dict[str, Any]:
    return _semantic_payload(bundle, "review_readiness")


def _bundle_trust_state(bundle: Mapping[str, Any]) -> dict[str, Any]:
    return _semantic_payload(bundle, "trust_state")


def _normalize_coverage_state_payload(payload: Mapping[str, Any] | None, *, canonical_name: str = "") -> dict[str, Any]:
    obj = dict(payload or {})
    resolved_canonical_name = _as_text(obj.get("canonical_name")) or canonical_name
    return {
        "status": _as_text(obj.get("status")) or COVERAGE_STATE_STATUS_REPRESENTED,
        "canonical_name": resolved_canonical_name,
        "representation_basis": _as_text(obj.get("representation_basis")) or "hierarchy_identity",
        "source_field": _as_text(obj.get("source_field")) or "hierarchy.canonical_name",
        "review_lane_survival": obj.get("review_lane_survival") is not False,
        "evidence_support_required": obj.get("evidence_support_required") is not False,
    }


def _bundle_coverage_state(bundle: Mapping[str, Any]) -> dict[str, Any]:
    coverage_state = bundle.get("coverage_state")
    canonical_name = _as_text(bundle.get("canonical_name"))
    return _normalize_coverage_state_payload(coverage_state if isinstance(coverage_state, Mapping) else {}, canonical_name=canonical_name)


def _bundle_legacy_triage(bundle: Mapping[str, Any]) -> dict[str, Any]:
    # Historical Step 6.7B compatibility only. Fresh seedless Step 6.7 bundles
    # should not rely on this payload, but Step 6.8 can still read it when
    # older bundles are replayed for audit purposes.
    return dict(bundle.get("seed_floor_triage") or {})


def _bundle_authoritative_definition_status(bundle: Mapping[str, Any]) -> str:
    status = _as_text(bundle.get("authoritative_definition_status"))
    if status in {
        AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED,
        AUTHORITATIVE_DEFINITION_STATUS_NORMALIZED_GROUNDED,
        AUTHORITATIVE_DEFINITION_STATUS_INSUFFICIENT_SUPPORT,
    }:
        return status
    enrichment_layer = _semantic_payload(bundle, "enrichment_layer")
    if _as_text(enrichment_layer.get("status")) == ENRICHMENT_LAYER_STATUS_GROUNDED and _as_text(enrichment_layer.get("text")):
        return AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED
    full_payload = _candidate_payload(bundle, "definition_full_candidate")
    if _as_text(full_payload.get("status")) == "grounded" and _as_text(full_payload.get("text")):
        return AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED
    return AUTHORITATIVE_DEFINITION_STATUS_INSUFFICIENT_SUPPORT


def _bundle_topic_hierarchy_fields(bundle: Mapping[str, Any]) -> dict[str, Any]:
    hierarchy_fields = typed_topic_hierarchy_fields(bundle)
    return {
        "topic_path_ids": _normalize_string_list(hierarchy_fields.get("topic_path_ids")),
        "topic_path_labels": _normalize_string_list(hierarchy_fields.get("topic_path_labels")),
        "parent_topic_id": hierarchy_fields.get("parent_topic_id") if hierarchy_fields.get("parent_topic_id") is not None else None,
        "parent_topic_label": hierarchy_fields.get("parent_topic_label") if hierarchy_fields.get("parent_topic_label") is not None else None,
        "ancestor_topic_ids": _normalize_string_list(hierarchy_fields.get("ancestor_topic_ids")),
        "ancestor_topic_labels": _normalize_string_list(hierarchy_fields.get("ancestor_topic_labels")),
        "hierarchy_ancestry": dict(hierarchy_fields.get("hierarchy_ancestry") or {}),
    }


def _normalize_trust_state_payload(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    obj = dict(payload or {})
    return {
        "label": _as_text(obj.get("label")),
        "definition_grounded": bool(obj.get("definition_grounded")),
        "scope_grounded": bool(obj.get("scope_grounded")),
        "context_status": _as_text(obj.get("context_status")),
        "low_trust": bool(obj.get("low_trust")),
    }


def _normalize_review_readiness_payload(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    obj = dict(payload or {})
    return {
        "label": _as_text(obj.get("label")),
        "survives_review_lane": bool(obj.get("survives_review_lane")),
        "needs_attention": bool(obj.get("needs_attention")),
        "draft_status_compatibility": _as_text(obj.get("draft_status_compatibility")),
        "reasons": _normalize_string_list(obj.get("reasons")),
    }


def _review_definition_payload(
    bundle: Mapping[str, Any],
    *,
    prefer_canonicalized: bool = True,
) -> tuple[dict[str, Any], str]:
    enrichment_layer = _semantic_payload(bundle, "enrichment_layer")
    if (
        _as_text(enrichment_layer.get("status")) == ENRICHMENT_LAYER_STATUS_GROUNDED
        and _as_text(enrichment_layer.get("text"))
    ):
        return {
            "status": "grounded",
            "text": _as_text(enrichment_layer.get("text")),
            "supporting_overlay_candidate_ids": _normalize_string_list(enrichment_layer.get("supporting_overlay_candidate_ids")),
        }, "step6_7.kc_draft_bundles.enrichment_layer"

    legacy_payload, legacy_source = _choose_definition_payload(
        bundle,
        prefer_canonicalized=prefer_canonicalized,
    )
    if _as_text(legacy_payload.get("status")) == "grounded" and _as_text(legacy_payload.get("text")):
        return legacy_payload, legacy_source

    return {
        "status": "abstained",
        "text": "",
        "supporting_overlay_candidate_ids": [],
    }, "step6_7.kc_draft_bundles.coverage_state"


def _review_scope_layer(bundle: Mapping[str, Any], *, prefer_canonicalized: bool = True) -> dict[str, Any]:
    scope_layer = _semantic_payload(bundle, "scope_layer")
    if _as_text(scope_layer.get("status")):
        return scope_layer
    scope_payload = _scope_payload(bundle, prefer_canonicalized=prefer_canonicalized)
    if _as_text(scope_payload.get("status")) == SCOPE_LAYER_STATUS_GROUNDED:
        return {
            "status": SCOPE_LAYER_STATUS_GROUNDED,
            "text": _as_text(scope_payload.get("text")),
            "supporting_overlay_candidate_ids": _normalize_string_list(scope_payload.get("supporting_overlay_candidate_ids")),
        }
    return {
        "status": SCOPE_LAYER_STATUS_ABSTAINED,
        "text": "",
        "supporting_overlay_candidate_ids": [],
    }


def _grounded_llm_field_payload(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    obj = dict(payload or {})
    text = _as_text(obj.get("text"))
    supporting_ids = _normalize_string_list(obj.get("supporting_overlay_candidate_ids"))
    if _as_text(obj.get("status")) != "grounded" or not text or not supporting_ids:
        return {}
    return {
        "status": "grounded",
        "text": text,
        "supporting_overlay_candidate_ids": supporting_ids,
    }


def _looks_review_salvageable_definition_text(text: str) -> bool:
    normalized = _as_text(text)
    if len(normalized) < 30:
        return False
    if normalized.endswith(":"):
        return False
    alpha_chars = sum(1 for ch in normalized if ch.isalpha())
    digit_chars = sum(1 for ch in normalized if ch.isdigit())
    if alpha_chars < 20:
        return False
    if "=" in normalized and alpha_chars <= digit_chars + 5:
        return False
    return True


def _all_support_ids_local_to_kc(supporting_ids: Sequence[str], kc_id: str) -> bool:
    ids = _normalize_string_list(supporting_ids)
    return bool(ids) and all(_overlay_candidate_owner_kc_id(item) == kc_id for item in ids)


def _held_review_salvage_definition(
    bundle: Mapping[str, Any],
    *,
    kc_id: str,
) -> tuple[dict[str, Any], str, list[str]]:
    if _as_text(bundle.get("draft_status")) != "held":
        return {}, "", []
    hold_reasons = _normalize_string_list(bundle.get("hold_reasons"))
    if "sibling_boundary_mismatch" in hold_reasons:
        return {}, "", []

    llm = dict(((bundle.get("selection_diagnostics") or {}).get("llm_drafting")) or {})
    candidates = [
        (
            "step6_7.selection_diagnostics.llm_drafting.definition_redraft_verify_response.definition",
            _grounded_llm_field_payload(dict((llm.get("definition_redraft_verify_response") or {}).get("definition") or {})),
        ),
        (
            "step6_7.selection_diagnostics.llm_drafting.definition_redraft_response.definition",
            _grounded_llm_field_payload(dict((llm.get("definition_redraft_response") or {}).get("definition") or {})),
        ),
        (
            "step6_7.selection_diagnostics.llm_drafting.verify_response.definition",
            _grounded_llm_field_payload(dict((llm.get("verify_response") or {}).get("definition") or {})),
        ),
        (
            "step6_7.selection_diagnostics.llm_drafting.draft_response.definition",
            _grounded_llm_field_payload(dict((llm.get("draft_response") or {}).get("definition") or {})),
        ),
    ]

    for source, payload in candidates:
        if not payload:
            continue
        text = _as_text(payload.get("text"))
        supporting_ids = _normalize_string_list(payload.get("supporting_overlay_candidate_ids"))
        if not _all_support_ids_local_to_kc(supporting_ids, kc_id):
            continue
        if not _looks_review_salvageable_definition_text(text):
            continue
        notes = [
            "Held Step 6.7 bundle exposed to review via a persisted local-only LLM definition proposal.",
            "This proposal was not accepted as grounded by the Step 6.7 verifier and must be treated as reviewer-salvageable, not verifier-approved.",
        ]
        return payload, source, notes

    return {}, "", []


def _choose_definition_payload(
    bundle: Mapping[str, Any],
    *,
    prefer_canonicalized: bool = True,
) -> tuple[dict[str, Any], str]:
    if prefer_canonicalized:
        full_payload_canonicalized = _canonicalized_candidate_payload(bundle, "definition_full_candidate")
        if _as_text(full_payload_canonicalized.get("status")) == "grounded" and _as_text(full_payload_canonicalized.get("text")):
            return full_payload_canonicalized, "step6_75.kc_draft_bundles_canonicalized.definition_full_candidate"

    full_payload = _candidate_payload(bundle, "definition_full_candidate")
    short_payload = _candidate_payload(bundle, "definition_short_candidate")
    if _as_text(full_payload.get("status")) == "grounded" and _as_text(full_payload.get("text")):
        return full_payload, "step6_7.kc_draft_bundles.definition_full_candidate"
    return short_payload, "step6_7.kc_draft_bundles.definition_short_candidate"


def _scope_payload(bundle: Mapping[str, Any], *, prefer_canonicalized: bool = True) -> dict[str, Any]:
    if prefer_canonicalized:
        canonicalized_payload = _canonicalized_candidate_payload(bundle, "scope_candidate")
        if _as_text(canonicalized_payload.get("status")) == SCOPE_LAYER_STATUS_GROUNDED and _as_text(canonicalized_payload.get("text")):
            return canonicalized_payload
    return _candidate_payload(bundle, "scope_candidate")


def _definition_provenance_key(definition_source: str) -> str:
    if definition_source.endswith("definition_full_candidate"):
        return "definition_full_candidate"
    return "definition_short_candidate"


def _overlay_candidate_owner_kc_id(overlay_candidate_id: str) -> str:
    text = _as_text(overlay_candidate_id)
    if ":overlay:" not in text:
        return ""
    return text.split(":overlay:", 1)[0].strip()


def _mixed_foreign_definition_support(
    *,
    kc_id: str,
    field_provenance_map: Mapping[str, Any],
    definition_source: str,
) -> bool:
    provenance_key = _definition_provenance_key(definition_source)
    definition_provenance = _normalize_field_provenance_entry(field_provenance_map.get(provenance_key))
    local_ids = [
        overlay_candidate_id
        for overlay_candidate_id in definition_provenance.get("overlay_candidate_ids") or []
        if _overlay_candidate_owner_kc_id(str(overlay_candidate_id)) == kc_id
    ]
    foreign_ids = [
        overlay_candidate_id
        for overlay_candidate_id in definition_provenance.get("overlay_candidate_ids") or []
        if _overlay_candidate_owner_kc_id(str(overlay_candidate_id))
        and _overlay_candidate_owner_kc_id(str(overlay_candidate_id)) != kc_id
    ]
    return bool(local_ids and foreign_ids)


def _evidence_role(item: Mapping[str, Any], scope_support_ids: set[str]) -> str:
    overlay_candidate_id = _as_text(item.get("overlay_candidate_id"))
    bundle_role = _as_text(item.get("bundle_role"))
    assessment = dict(item.get("assessment") or {})
    if overlay_candidate_id in scope_support_ids:
        return "scope"
    if bundle_role == "definition_support":
        return "definition"
    if bundle_role == "equation_support":
        return "equation"
    if bundle_role == "context_support" and bool(assessment.get("scope_signal")):
        return "scope"
    return "other"


def _build_evidence_spans(bundle: Mapping[str, Any], scope_support_ids: set[str]) -> EvidenceSpanBuildResult:
    spans: list[dict[str, Any]] = []
    dropped_invalid_page_index_span_count = 0
    for item in bundle.get("evidence_bundle") or []:
        if not isinstance(item, Mapping):
            continue
        overlay_candidate_id = _as_text(item.get("overlay_candidate_id"))
        doc_id = _as_text(item.get("doc_id"))
        block_id = _as_text(item.get("block_id"))
        layer = _as_text(item.get("layer"))
        quote = _as_text(item.get("quote_surface")) or _as_text(item.get("source_block_text"))
        raw_page_index = item.get("page_index")
        page_index = _coerce_non_negative_page_index(raw_page_index)
        if (
            overlay_candidate_id
            and doc_id
            and block_id
            and layer
            and quote
            and raw_page_index is not None
            and page_index is None
        ):
            dropped_invalid_page_index_span_count += 1
        if not overlay_candidate_id or not doc_id or not block_id or not layer or not quote or page_index is None:
            continue
        provenance_flags = [
            f"OverlayCandidateId:{overlay_candidate_id}",
            f"BundleRole:{_as_text(item.get('bundle_role')) or 'other'}",
            f"ProvenanceStatus:{_as_text(item.get('provenance_normalization_status')) or 'unknown'}",
            f"ContaminationRisk:{_as_text(item.get('contamination_risk')) or 'unknown'}",
        ]
        spans.append(
            {
                "evidence_id": overlay_candidate_id,
                "doc_id": doc_id,
                "block_id": block_id,
                "page_index": page_index,
                "layer": layer,
                "bbox": _normalize_bbox(item.get("bbox")),
                "quote": quote,
                "role": _evidence_role(item, scope_support_ids),
                "extraction_method": RESTARTED_EVIDENCE_EXTRACTION_METHOD,
                "quote_verified": _quote_verified(item.get("quote_verification_status")),
                "provenance_quality_flags": provenance_flags,
            }
        )
    return EvidenceSpanBuildResult(
        spans=tuple(spans),
        dropped_invalid_page_index_span_count=dropped_invalid_page_index_span_count,
    )


def _coverage_labels(evidence_spans: Sequence[Mapping[str, Any]]) -> list[str]:
    roles = {str(span.get("role") or "") for span in evidence_spans}
    labels: list[str] = []
    if "definition" in roles or "equation" in roles:
        labels.append("definition")
    if "procedure" in roles:
        labels.append("procedural_step")
    return labels


def _build_coverage_note(bundle: Mapping[str, Any], risk_flags: Sequence[str]) -> str:
    parts: list[str] = []
    scope_layer = _review_scope_layer(bundle)
    review_readiness = _bundle_review_readiness(bundle)
    if _as_text(scope_layer.get("status")) != SCOPE_LAYER_STATUS_GROUNDED:
        parts.append("Scope field is intentionally blank and remains reviewer-editable.")
    if _as_text(review_readiness.get("label")) == REVIEW_READINESS_COVERAGE_ONLY:
        parts.append("This KC remains represented in the coverage lane, but definition support is still insufficient for grounded reviewer-facing wording.")
    caution_flags = [flag for flag in risk_flags if flag not in {SCOPE_GAP_FLAG, SCOPE_CANDIDATE_ABSTAINED_FLAG, DRAFT_READY_WITH_HOLDS_FLAG}]
    if caution_flags:
        parts.append(f"Caution flags: {', '.join(caution_flags)}.")
    return " ".join(parts).strip()


def _source_document_ids(evidence_spans: Sequence[Mapping[str, Any]]) -> list[str]:
    out: list[str] = []
    for span in evidence_spans:
        doc_id = _as_text(span.get("doc_id"))
        if doc_id:
            _append_unique(out, doc_id)
    return out


def _priority_features(
    bundle: Mapping[str, Any],
    evidence_spans: Sequence[Mapping[str, Any]],
    risk_flags: Sequence[str],
    *,
    mixed_foreign_definition_support: bool = False,
) -> dict[str, Any]:
    review_readiness = _bundle_review_readiness(bundle)
    trust_state = _bundle_trust_state(bundle)
    support_summary = dict(bundle.get("support_summary") or {})
    scope_layer = _review_scope_layer(bundle)
    readiness_label = _as_text(review_readiness.get("label"))
    trust_label = _as_text(trust_state.get("label"))
    semantic_tier = 2
    if readiness_label == REVIEW_READINESS_COVERAGE_ONLY:
        semantic_tier = 0
    elif readiness_label in {REVIEW_READINESS_NEEDS_ATTENTION, ""} or REVIEW_QUEUE_WEAK_COVERAGE_FLAG in risk_flags:
        semantic_tier = 1

    if trust_label in {TRUST_STATE_COVERAGE_ONLY, TRUST_STATE_COVERAGE_ONLY_WITH_RISKS}:
        definition_status = "unsupported_in_source"
    elif _as_text(support_summary.get("support_state")) == "strict_leaf_support":
        definition_status = "coherent_supported"
    else:
        definition_status = "fragmentary_supported"
    if mixed_foreign_definition_support and definition_status == "coherent_supported":
        definition_status = "fragmentary_supported"

    contamination_category = "clean"
    if any(flag in {CONTEXT_BUNDLE_MISSING_FLAG, MIXED_FOREIGN_DEFINITION_SUPPORT_FLAG} for flag in risk_flags):
        contamination_category = "hard_contamination"
    return {
        "semantic_tier": semantic_tier,
        "definition_status": definition_status,
        "accepted_quote_count": sum(1 for span in evidence_spans if bool(span.get("quote_verified"))),
        "evidence_span_count": len(evidence_spans),
        "definition_short_contract_ok": _as_text(_candidate_payload(bundle, "definition_short_candidate").get("status")) == "grounded",
        "support_contract_downgraded": readiness_label == REVIEW_READINESS_COVERAGE_ONLY,
        "contamination_category": contamination_category,
        "sibling_ambiguity": mixed_foreign_definition_support,
        "operational_support_present": _as_text(scope_layer.get("status")) == SCOPE_LAYER_STATUS_GROUNDED,
    }



def _build_notes_for_reviewer(bundle: Mapping[str, Any], risk_flags: Sequence[str]) -> str:
    notes: list[str] = []
    review_readiness = _bundle_review_readiness(bundle)
    trust_state = _bundle_trust_state(bundle)
    legacy_triage = _bundle_legacy_triage(bundle)
    compat_primary_bucket = _as_text(legacy_triage.get("primary_bucket"))
    compat_rescue_mode = _as_text(legacy_triage.get("rescue_mode"))
    if _as_text(_review_scope_layer(bundle).get("status")) != SCOPE_LAYER_STATUS_GROUNDED:
        notes.append("Scope is intentionally blank from the Step 6.7 draft and should be treated as a reviewer-editable gap.")
    if _as_text(review_readiness.get("label")) == REVIEW_READINESS_COVERAGE_ONLY:
        notes.append("This KC survived Step 6.7 as coverage-only. Keep it in review, but draft or edit the definition from evidence instead of treating the packet as grounded.")
        if compat_primary_bucket and compat_primary_bucket != STRUCTURAL_COMPAT_OR_HIERARCHY_ISSUE_BUCKET:
            notes.append("Legacy compatibility triage kept this packet on the edit path rather than the reject path.")
        elif not any(flag in COVERAGE_ONLY_RECOMMENDATION_BLOCKING_FLAGS for flag in risk_flags):
            notes.append("Coverage-only status alone is not a reject signal here: keep the KC in the review lane and edit the definition or scope if the concept itself is valid.")
    elif _as_text(trust_state.get("label")) == TRUST_STATE_GROUNDED_WITH_GAPS:
        notes.append("Grounded support exists, but the bundle still carries explicit attention markers and should be reviewed conservatively.")
    if compat_rescue_mode:
        notes.append(f"Legacy compatibility rescue mode: {compat_rescue_mode}.")
    if REVIEW_QUEUE_WEAK_COVERAGE_FLAG in risk_flags:
        notes.append("Upstream Step 5.3 weak-coverage caution is preserved on this packet.")
    if "held_bundle_review_salvage" in risk_flags:
        notes.append("Held Step 6.7 bundle exposed to review via a persisted local-only LLM definition proposal. This proposal was not accepted as grounded by the Step 6.7 verifier and must be treated as reviewer-salvageable, not verifier-approved.")
    return " ".join(notes).strip()


def _soften_coverage_only_recommendation(
    *,
    system_recommendation: Mapping[str, Any],
    authoritative_definition_status: str,
    review_readiness: Mapping[str, Any],
    risk_flags: Sequence[str],
    compat_primary_bucket: str = "",
) -> dict[str, Any]:
    recommendation = dict(system_recommendation or {})
    if authoritative_definition_status != AUTHORITATIVE_DEFINITION_STATUS_INSUFFICIENT_SUPPORT:
        return recommendation
    if _as_text(review_readiness.get("label")) != REVIEW_READINESS_COVERAGE_ONLY:
        return recommendation
    if review_readiness.get("survives_review_lane") is not True:
        return recommendation
    reason_codes = _normalize_string_list(recommendation.get("reason_codes"))
    if compat_primary_bucket and compat_primary_bucket != STRUCTURAL_COMPAT_OR_HIERARCHY_ISSUE_BUCKET:
        _append_unique(reason_codes, "priority_bucket:low_support")
        _append_unique(reason_codes, COVERAGE_ONLY_KEEP_AND_EDIT_REASON)
        _append_unique(reason_codes, REVIEW_EDIT_REQUIRED_REASON)
        recommendation["label"] = "review_needed"
        recommendation["reason_codes"] = reason_codes
        return recommendation
    if _as_text(recommendation.get("label")) != "reject_recommended":
        return recommendation
    blocking_flags = [flag for flag in _normalize_string_list(risk_flags) if flag in COVERAGE_ONLY_RECOMMENDATION_BLOCKING_FLAGS]
    if blocking_flags:
        _append_unique(reason_codes, SUSPICIOUS_COVERAGE_ONLY_PACKET_REASON)
        for flag in blocking_flags:
            _append_unique(reason_codes, f"suspicious_risk_flag:{flag}")
        recommendation["reason_codes"] = reason_codes
        return recommendation
    if any(code not in COVERAGE_ONLY_RECOMMENDATION_ALLOWED_REASON_CODES for code in reason_codes):
        return recommendation
    _append_unique(reason_codes, "priority_bucket:low_support")
    _append_unique(reason_codes, COVERAGE_ONLY_KEEP_AND_EDIT_REASON)
    recommendation["label"] = "review_needed"
    recommendation["reason_codes"] = reason_codes
    return recommendation


def _downgrade_approve_ready_recommendation(
    *,
    system_recommendation: Mapping[str, Any],
    trust_state: Mapping[str, Any],
    review_readiness: Mapping[str, Any],
    risk_flags: Sequence[str],
) -> dict[str, Any]:
    recommendation = dict(system_recommendation or {})
    if _as_text(recommendation.get("label")) != "approve_ready":
        return recommendation

    reason_codes = _normalize_string_list(recommendation.get("reason_codes"))
    readiness_label = _as_text(review_readiness.get("label"))
    trust_label = _as_text(trust_state.get("label"))
    strong_flags = [flag for flag in _normalize_string_list(risk_flags) if flag in APPROVE_READY_BLOCKING_FLAGS]

    if readiness_label == REVIEW_READINESS_READY and trust_label == TRUST_STATE_GROUNDED and not strong_flags:
        recommendation["reason_codes"] = reason_codes
        return recommendation

    recommendation["label"] = "review_needed"
    if readiness_label != REVIEW_READINESS_READY or trust_label != TRUST_STATE_GROUNDED:
        _append_unique(reason_codes, APPROVE_READY_BLOCKED_BY_INCOMPLETE_REVIEW_STATE_REASON)
    if strong_flags:
        _append_unique(reason_codes, APPROVE_READY_BLOCKED_BY_STRONG_RISK_REASON)
        for flag in strong_flags:
            _append_unique(reason_codes, f"strong_risk_flag:{flag}")
    recommendation["reason_codes"] = reason_codes
    return recommendation


def _looks_discourse_leadin_definition(text: str) -> bool:
    lowered = _as_text(text).lower()
    if not lowered:
        return False
    leadins = (
        "in this section",
        "in this chapter",
        "consider ",
        "suppose ",
        "note that",
        "as described above",
        "as indicated by",
        "the preceding example",
        "the following example",
        "this example",
        "thus,",
        "although ",
        "a high-level summary of",
    )
    return any(lowered.startswith(prefix) for prefix in leadins)


def _looks_example_or_exposition_definition(text: str) -> bool:
    lowered = _as_text(text).lower()
    if not lowered:
        return False
    markers = (
        "for example",
        "illustrates",
        "is summarized in",
        "shown as",
        "the example",
        "the preceding example",
        "the following example",
        "as described above",
        "as indicated by",
    )
    return any(marker in lowered for marker in markers)


def _looks_fragmentary_definition_surface(text: str) -> bool:
    stripped = _as_text(text)
    if not stripped:
        return False
    lowered = stripped.lower()
    if lowered.startswith(("and ", "or ", "but ", "that ", "which ")):
        return True
    if stripped.endswith((",", ";", ":")):
        return True
    formula_markers = ("=", "∑", "sum_", "chi^2", "avg(", "max(", "min(")
    if any(marker in stripped for marker in formula_markers) and len(stripped) < 140:
        return True
    return False



def _quarantine_reasons(packet: Mapping[str, Any]) -> list[str]:
    definition_draft = _as_text(packet.get("definition_draft"))
    risk_flags = set(_normalize_string_list(packet.get("risk_flags")))

    reasons: list[str] = []

    if _looks_fragmentary_definition_surface(definition_draft):
        _append_unique(reasons, "definition_fragmentary_surface")

    if MIXED_FOREIGN_DEFINITION_SUPPORT_FLAG in risk_flags:
        _append_unique(reasons, "definition_decisive_support_mixed_foreign")

    return reasons


def _build_restarted_review_packet_with_metadata(
    *,
    draft_bundle: Mapping[str, Any],
    step4_set_id: str,
    step4_5_set_id: str,
    step5_set_id: str,
    step6_6_set_id: str,
    step6_7_set_id: str,
    step6_7b_set_id: str,
    step6_75_set_id: str,
    step6_8_run_id: str,
) -> dict[str, Any]:
    draft_status = _as_text(draft_bundle.get("draft_status"))
    kc_id = _as_text(draft_bundle.get("kc_id"))
    canonical_name = _as_text(draft_bundle.get("canonical_name"))
    field_provenance_map = _normalize_field_provenance_map(draft_bundle.get("field_provenance_map") or {})
    semantic_contract_present = _semantic_contract_present(draft_bundle)
    raw_definition_payload, raw_definition_source = _review_definition_payload(
        draft_bundle,
        prefer_canonicalized=False,
    )
    definition_payload, definition_source = _review_definition_payload(
        draft_bundle,
        prefer_canonicalized=True,
    )
    raw_definition_draft = _as_text(raw_definition_payload.get("text"))
    definition_draft = _as_text(definition_payload.get("text"))
    held_salvage_notes: list[str] = []
    held_salvaged = False
    authoritative_definition_status = _bundle_authoritative_definition_status(draft_bundle)
    coverage_state = _bundle_coverage_state(draft_bundle)
    hierarchy_fields = _bundle_topic_hierarchy_fields(draft_bundle)
    trust_state = _normalize_trust_state_payload(_bundle_trust_state(draft_bundle))
    review_readiness = _normalize_review_readiness_payload(_bundle_review_readiness(draft_bundle))
    canonicalization_metadata = dict(draft_bundle.get("canonicalization_metadata") or {})
    canonicalization_risk_flags = _normalize_string_list(draft_bundle.get("canonicalization_risk_flags"))
    canonicalization_review_burden_estimate = _as_text(draft_bundle.get("review_burden_estimate"))
    legacy_triage = _bundle_legacy_triage(draft_bundle)
    compat_primary_bucket = _as_text(legacy_triage.get("primary_bucket"))

    if not semantic_contract_present and draft_status not in {"draft_ready", "draft_ready_with_holds"}:
        if draft_status != "held":
            raise ValueError(f"non-ready draft cannot become a ready packet: {draft_status}")
        salvaged_payload, salvaged_source, held_salvage_notes = _held_review_salvage_definition(
            draft_bundle,
            kc_id=kc_id,
        )
        if not salvaged_payload:
            raise ValueError("held_bundle_not_review_salvageable")
        definition_payload = salvaged_payload
        definition_source = salvaged_source
        raw_definition_payload = salvaged_payload
        raw_definition_source = salvaged_source
        definition_draft = _as_text(definition_payload.get("text"))
        raw_definition_draft = definition_draft
        draft_status = "draft_ready_with_holds"
        held_salvaged = True

        evidence_provenance = _normalize_field_provenance_entry(field_provenance_map.get("evidence_bundle"))
        field_provenance_map["definition_full_candidate"] = {
            "status": "grounded",
            "overlay_candidate_ids": _normalize_string_list(definition_payload.get("supporting_overlay_candidate_ids")),
            "source_set_ids": _normalize_string_list(evidence_provenance.get("source_set_ids")),
            "source_run_ids": _normalize_string_list(evidence_provenance.get("source_run_ids")),
        }
        authoritative_definition_status = AUTHORITATIVE_DEFINITION_STATUS_INSUFFICIENT_SUPPORT

    if not kc_id or not canonical_name:
        raise ValueError("missing required packet identity content")
    if authoritative_definition_status != AUTHORITATIVE_DEFINITION_STATUS_INSUFFICIENT_SUPPORT and not definition_draft:
        raise ValueError("missing required grounded draft content")
    mixed_foreign_definition_support = _mixed_foreign_definition_support(
        kc_id=kc_id,
        field_provenance_map=field_provenance_map,
        definition_source=definition_source,
    )
    raw_scope_layer = _review_scope_layer(draft_bundle, prefer_canonicalized=False)
    raw_scope_status = _as_text(raw_scope_layer.get("status")) or SCOPE_LAYER_STATUS_ABSTAINED
    raw_scope_draft = _as_text(raw_scope_layer.get("text")) if raw_scope_status == SCOPE_LAYER_STATUS_GROUNDED else ""

    scope_layer = _review_scope_layer(draft_bundle, prefer_canonicalized=True)
    scope_status = _as_text(scope_layer.get("status")) or SCOPE_LAYER_STATUS_ABSTAINED
    scope_draft = _as_text(scope_layer.get("text")) if scope_status == SCOPE_LAYER_STATUS_GROUNDED else ""
    scope_support_ids = set(_normalize_string_list(scope_layer.get("supporting_overlay_candidate_ids")))
    evidence_build = _build_evidence_spans(draft_bundle, scope_support_ids)
    evidence_spans = list(evidence_build.spans)
    if not evidence_spans:
        raise ValueError("no_grounded_step6_7_evidence_bundle")

    risk_flags = _bundle_risk_flags(draft_bundle)
    if draft_status == "draft_ready_with_holds":
        _append_unique(risk_flags, DRAFT_READY_WITH_HOLDS_FLAG)
    if held_salvaged:
        _append_unique(risk_flags, HELD_REVIEW_SALVAGE_FLAG)
        _append_unique(risk_flags, DEFINITION_REVIEW_SALVAGE_UNVERIFIED_FLAG)
    if scope_status != SCOPE_LAYER_STATUS_GROUNDED:
        _append_unique(risk_flags, SCOPE_GAP_FLAG)
        _append_unique(risk_flags, SCOPE_CANDIDATE_ABSTAINED_FLAG)
    if mixed_foreign_definition_support:
        _append_unique(risk_flags, MIXED_FOREIGN_DEFINITION_SUPPORT_FLAG)
    if _as_text(review_readiness.get("label")) == REVIEW_READINESS_COVERAGE_ONLY:
        _append_unique(risk_flags, LOW_TRUST_REVIEW_FLAG)
    if bool(review_readiness.get("needs_attention")):
        _append_unique(risk_flags, REVIEW_NEEDS_ATTENTION_FLAG)
    if evidence_build.dropped_invalid_page_index_span_count:
        _append_unique(risk_flags, INVALID_PAGE_INDEX_DROPPED_FLAG)

    priority_features = _priority_features(
        draft_bundle,
        evidence_spans,
        risk_flags,
        mixed_foreign_definition_support=mixed_foreign_definition_support,
    )
    review_priority = compute_review_priority(priority_features)
    system_recommendation = derive_system_recommendation(priority_features, review_priority)
    system_recommendation = _soften_coverage_only_recommendation(
        system_recommendation=system_recommendation,
        authoritative_definition_status=authoritative_definition_status,
        review_readiness=review_readiness,
        risk_flags=risk_flags,
        compat_primary_bucket=compat_primary_bucket,
    )
    system_recommendation = _downgrade_approve_ready_recommendation(
        system_recommendation=system_recommendation,
        trust_state=trust_state,
        review_readiness=review_readiness,
        risk_flags=risk_flags,
    )

    packet = {
        "review_packet_id": f"step6_8:{step6_8_run_id}:{kc_id}",
        "packet_state": REVIEW_PACKET_STATE,
        "kc_candidate_id": kc_id,
        "title_draft": canonical_name,
        "level_draft": "atomic",
        "definition_draft": definition_draft,
        "raw_definition_draft": raw_definition_draft,
        "authoritative_definition_status": authoritative_definition_status,
        "coverage_state": coverage_state,
        "scope_draft": scope_draft,
        "raw_scope_draft": raw_scope_draft,
        "scope_status": scope_status,
        **hierarchy_fields,
        "kc_specific_criteria": "",
        "draft_status": draft_status,
        "trust_state": trust_state,
        "review_readiness": review_readiness,
        "canonicalization_metadata": canonicalization_metadata,
        "canonicalization_risk_flags": canonicalization_risk_flags,
        "canonicalization_review_burden_estimate": canonicalization_review_burden_estimate,
        "draft_hold_reasons": _normalize_string_list(draft_bundle.get("hold_reasons")),
        "draft_field_hold_reasons": _normalize_field_hold_reasons(draft_bundle.get("field_hold_reasons") or {}),
        "field_provenance_map": field_provenance_map,
        "evidence_spans": evidence_spans,
        "evidence_coverage_summary": {
            "evidence_span_count": len(evidence_spans),
            "definition_support_state": priority_features["definition_status"],
            "operational_support_present": priority_features["operational_support_present"],
            "coverage_labels": _coverage_labels(evidence_spans),
            "provenance_complete": True,
            "coverage_note": _build_coverage_note(draft_bundle, risk_flags),
        },
        "source_provenance": {
            "generation_stage": RESTARTED_GENERATION_STAGE,
            "generation_run_id": step6_8_run_id,
            "source_set_ids": {
                "step4_set_id": step4_set_id,
                "step4_5_set_id": step4_5_set_id,
                "step5_set_id": step5_set_id,
                "step6_6_set_id": step6_6_set_id,
                "step6_7_set_id": step6_7_set_id,
                "step6_7b_set_id": step6_7b_set_id,
                "step6_75_set_id": step6_75_set_id,
            },
            "source_document_ids": _source_document_ids(evidence_spans),
        },
        "content_source_mode": CONTENT_SOURCE_MODE_DRAFT_PRIMARY,
        "content_repair_applied": False,
        "content_repair_reason": "",
        "original_content_source": {
            "definition_source": raw_definition_source,
            "evidence_source": "step6_7.kc_draft_bundles.evidence_bundle",
        },
        "review_content_source": {
            "definition_source": definition_source,
            "evidence_source": "step6_7.kc_draft_bundles.evidence_bundle",
        },
        "integrity_repair_notes": [],
        "risk_flags": risk_flags,
        "review_priority": review_priority,
        "system_recommendation": system_recommendation,
        "notes_for_reviewer": " ".join(
            item
            for item in [
                _build_notes_for_reviewer(draft_bundle, risk_flags),
                *held_salvage_notes,
            ]
            if item
        ).strip(),
    }
    return RestartedReviewPacketBuildResult(
        packet=packet,
        dropped_invalid_page_index_span_count=evidence_build.dropped_invalid_page_index_span_count,
    )


def build_restarted_review_packet(
    *,
    draft_bundle: Mapping[str, Any],
    step4_set_id: str,
    step4_5_set_id: str,
    step5_set_id: str,
    step6_6_set_id: str,
    step6_7_set_id: str,
    step6_8_run_id: str,
    step6_7b_set_id: str = "",
    step6_75_set_id: str = "",
) -> dict[str, Any]:
    return _build_restarted_review_packet_with_metadata(
        draft_bundle=draft_bundle,
        step4_set_id=step4_set_id,
        step4_5_set_id=step4_5_set_id,
        step5_set_id=step5_set_id,
        step6_6_set_id=step6_6_set_id,
        step6_7_set_id=step6_7_set_id,
        step6_7b_set_id=step6_7b_set_id,
        step6_75_set_id=step6_75_set_id,
        step6_8_run_id=step6_8_run_id,
    ).packet


def validate_restarted_review_packet(packet: Mapping[str, Any]) -> None:
    validate_review_packet(packet)
    if _as_text(packet.get("content_source_mode")) != CONTENT_SOURCE_MODE_DRAFT_PRIMARY:
        raise ValueError("restarted packet must use step6_7_draft_primary content source mode")
    if _as_text(packet.get("authoritative_definition_status")) not in {
        AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED,
        AUTHORITATIVE_DEFINITION_STATUS_NORMALIZED_GROUNDED,
        AUTHORITATIVE_DEFINITION_STATUS_INSUFFICIENT_SUPPORT,
    }:
        raise ValueError("authoritative_definition_status invalid")
    if _as_text(packet.get("draft_status")) not in {"draft_ready", "draft_ready_with_holds"}:
        raise ValueError("draft_status invalid for restarted packet")
    if "kc_specific_criteria" not in packet:
        raise ValueError("kc_specific_criteria must be present and empty in this phase")
    if _as_text(packet.get("kc_specific_criteria")):
        raise ValueError("kc_specific_criteria must remain empty in this phase")
    coverage_state = packet.get("coverage_state")
    if not isinstance(coverage_state, Mapping):
        raise ValueError("coverage_state must be an object")
    for required_key in ("status", "canonical_name", "representation_basis", "source_field", "review_lane_survival", "evidence_support_required"):
        if required_key not in coverage_state:
            raise ValueError(f"coverage_state.{required_key} missing")
    for key in ("topic_path_ids", "topic_path_labels", "ancestor_topic_ids", "ancestor_topic_labels"):
        if not isinstance(packet.get(key), list):
            raise ValueError(f"{key} must be a list")
    for key in ("parent_topic_id", "parent_topic_label"):
        if packet.get(key) is not None and not isinstance(packet.get(key), str):
            raise ValueError(f"{key} must be a string or null")
    hierarchy_ancestry = packet.get("hierarchy_ancestry")
    if not isinstance(hierarchy_ancestry, Mapping):
        raise ValueError("hierarchy_ancestry must be an object")
    for key in (
        "ancestor_hier_node_ids",
        "ancestor_labels",
        "leaf_hier_node_id",
        "parent_hier_node_id",
        "source_hierarchy_path",
    ):
        if key not in hierarchy_ancestry:
            raise ValueError(f"hierarchy_ancestry.{key} missing")
    if _as_text(packet.get("scope_status")) not in {"grounded", "abstained"}:
        raise ValueError("scope_status invalid")
    if _as_text(packet.get("scope_status")) == "abstained" and _as_text(packet.get("scope_draft")):
        raise ValueError("abstained scope packet must not emit scope_draft text")
    provenance_map = packet.get("field_provenance_map")
    if not isinstance(provenance_map, Mapping):
        raise ValueError("field_provenance_map must be an object")
    for key in ("definition_full_candidate", "definition_short_candidate", "scope_candidate", "evidence_bundle"):
        value = provenance_map.get(key)
        if not isinstance(value, Mapping):
            raise ValueError(f"field_provenance_map.{key} must be an object")
        for required_key in ("status", "overlay_candidate_ids", "source_set_ids", "source_run_ids"):
            if required_key not in value:
                raise ValueError(f"field_provenance_map.{key}.{required_key} missing")
    trust_state = packet.get("trust_state")
    if not isinstance(trust_state, Mapping):
        raise ValueError("trust_state must be an object")
    if _as_text(trust_state.get("label")) not in {
        TRUST_STATE_GROUNDED,
        TRUST_STATE_GROUNDED_WITH_GAPS,
        TRUST_STATE_COVERAGE_ONLY,
        TRUST_STATE_COVERAGE_ONLY_WITH_RISKS,
    }:
        raise ValueError("trust_state.label invalid")
    if _as_text(trust_state.get("context_status")) not in {
        CONTEXT_LAYER_STATUS_GROUNDED,
        CONTEXT_LAYER_STATUS_FALLBACK,
        CONTEXT_LAYER_STATUS_MISSING,
    }:
        raise ValueError("trust_state.context_status invalid")
    for key in ("definition_grounded", "scope_grounded", "low_trust"):
        if not isinstance(trust_state.get(key), bool):
            raise ValueError(f"trust_state.{key} must be boolean")
    review_readiness = packet.get("review_readiness")
    if not isinstance(review_readiness, Mapping):
        raise ValueError("review_readiness must be an object")
    if _as_text(review_readiness.get("label")) not in {
        REVIEW_READINESS_READY,
        REVIEW_READINESS_NEEDS_ATTENTION,
        REVIEW_READINESS_COVERAGE_ONLY,
    }:
        raise ValueError("review_readiness.label invalid")
    if review_readiness.get("survives_review_lane") is not True:
        raise ValueError("review_readiness.survives_review_lane must remain true")
    if not isinstance(review_readiness.get("needs_attention"), bool):
        raise ValueError("review_readiness.needs_attention must be boolean")
    if _as_text(review_readiness.get("draft_status_compatibility")) not in {"draft_ready", "draft_ready_with_holds"}:
        raise ValueError("review_readiness.draft_status_compatibility invalid")
    if _as_text(review_readiness.get("draft_status_compatibility")) != _as_text(packet.get("draft_status")):
        raise ValueError("review_readiness.draft_status_compatibility must match draft_status")
    if not isinstance(review_readiness.get("reasons"), list):
        raise ValueError("review_readiness.reasons must be a list")


def build_summary(
    *,
    source_processed_dir: Path,
    packets: Sequence[Mapping[str, Any]],
    draft_rows: Sequence[Mapping[str, Any]] | None = None,
    quarantine: Sequence[Mapping[str, Any]],
    exclusions: Sequence[PacketExclusion],
    step6_7_drafting_runtime: Mapping[str, Any] | None = None,
    dropped_invalid_page_index_span_count: int = 0,
) -> dict[str, Any]:
    priority_counts = Counter(packet["review_priority"]["bucket"] for packet in packets)
    recommendation_counts = Counter(packet["system_recommendation"]["label"] for packet in packets)
    review_edit_required_kcs = [
        packet["kc_candidate_id"]
        for packet in packets
        if REVIEW_EDIT_REQUIRED_REASON in _normalize_string_list((packet.get("system_recommendation") or {}).get("reason_codes"))
    ]
    risk_flag_counts = Counter(flag for packet in packets for flag in packet.get("risk_flags") or [])
    authoritative_definition_status_counts = Counter(
        _as_text(packet.get("authoritative_definition_status"))
        for packet in packets
        if _as_text(packet.get("authoritative_definition_status"))
    )
    scope_gap_ids = [packet["kc_candidate_id"] for packet in packets if packet.get("scope_status") == "abstained"]
    caution_ids = [
        packet["kc_candidate_id"]
        for packet in packets
        if any(
            flag not in {SCOPE_GAP_FLAG, SCOPE_CANDIDATE_ABSTAINED_FLAG, DRAFT_READY_WITH_HOLDS_FLAG}
            for flag in packet.get("risk_flags") or []
        )
    ]
    draft_status_counts = Counter(packet.get("draft_status") for packet in packets)
    trust_state_counts = Counter(
        _as_text((_bundle_trust_state(row) or {}).get("label"))
        for row in draft_rows or []
        if _as_text((_bundle_trust_state(row) or {}).get("label"))
    )
    review_readiness_counts = Counter(
        _as_text((_bundle_review_readiness(row) or {}).get("label"))
        for row in draft_rows or []
        if _as_text((_bundle_review_readiness(row) or {}).get("label"))
    )
    fallback_kcs = [
        packet["kc_candidate_id"]
        for packet in packets
        if _as_text(packet.get("authoritative_definition_status")) == AUTHORITATIVE_DEFINITION_STATUS_INSUFFICIENT_SUPPORT
    ]
    normalized_grounded_kcs = [
        packet["kc_candidate_id"]
        for packet in packets
        if _as_text(packet.get("authoritative_definition_status")) == AUTHORITATIVE_DEFINITION_STATUS_NORMALIZED_GROUNDED
    ]
    low_trust_kcs = [
        _as_text(row.get("kc_id"))
        for row in draft_rows or []
        if _as_text((_bundle_review_readiness(row) or {}).get("label")) == REVIEW_READINESS_COVERAGE_ONLY
    ]
    invalid_page_index_drop_packet_ids = [
        packet["kc_candidate_id"]
        for packet in packets
        if INVALID_PAGE_INDEX_DROPPED_FLAG in (_normalize_string_list(packet.get("risk_flags")))
    ]
    return {
        "schema_version": "1.0",
        "stage": RESTARTED_GENERATION_STAGE,
        "rule_version": RESTARTED_PACKET_RULE_VERSION,
        "source_processed_dir": str(source_processed_dir),
        "packet_count": len(packets),
        "excluded_candidate_count": len(exclusions),
        "included_kcs": [packet["kc_candidate_id"] for packet in packets],
        "quarantine_count": len(quarantine),
        "quarantined_kcs": [_as_text(item.get("kc_candidate_id")) for item in quarantine if _as_text(item.get("kc_candidate_id"))],
        "excluded_kcs": [item.kc_candidate_id for item in exclusions if item.kc_candidate_id],
        "dropped_invalid_page_index_span_count": dropped_invalid_page_index_span_count,
        "packets_with_invalid_page_index_drops": invalid_page_index_drop_packet_ids,
        "packets_with_scope_gaps": scope_gap_ids,
        "packets_with_caution_flags": caution_ids,
        "held_salvage_ready_count": 0,
        "held_salvage_ready_kcs": [],
        "held_salvage_quarantine_count": 0,
        "held_salvage_quarantined_kcs": [],
        "insufficient_support_definition_count": len([item for item in fallback_kcs if item]),
        "insufficient_support_definition_kcs": [item for item in fallback_kcs if item],
        "normalized_grounded_definition_count": len([item for item in normalized_grounded_kcs if item]),
        "normalized_grounded_kcs": [item for item in normalized_grounded_kcs if item],
        "coverage_only_packet_count": len([item for item in low_trust_kcs if item]),
        "coverage_only_kcs": [item for item in low_trust_kcs if item],
        "review_edit_required_count": len([item for item in review_edit_required_kcs if item]),
        "review_edit_required_kcs": [item for item in review_edit_required_kcs if item],
        "recommendation_counts": dict(recommendation_counts),
        "priority_counts": dict(priority_counts),
        "draft_status_counts": dict(draft_status_counts),
        "quarantine_draft_status_counts": {},
        "trust_state_counts": dict(trust_state_counts),
        "review_readiness_counts": dict(review_readiness_counts),
        "authoritative_definition_status_counts": dict(authoritative_definition_status_counts),
        "risk_flag_counts": dict(risk_flag_counts),
        "step6_7_drafting_runtime": dict(step6_7_drafting_runtime or {}),
        "field_source_map": {
            "definition_draft": "Reviewer-facing definition prefers step6_75 canonicalized definition candidates when present; otherwise it uses step6_7 enrichment_layer when grounded and stays blank when support remains insufficient.",
            "authoritative_definition_status": "step6_7.kc_draft_bundles.authoritative_definition_status with legacy fallback inference when absent",
            "coverage_state": "step6_7.kc_draft_bundles.coverage_state describing hierarchy-based representation survival without definition fallback",
            "topic_path_ids": "step6_7.kc_draft_bundles topic hierarchy refs derived from hierarchy overlay ancestry",
            "topic_path_labels": "step6_7.kc_draft_bundles topic hierarchy refs derived from hierarchy overlay ancestry",
            "scope_draft": "Reviewer-facing scope prefers step6_75 canonicalized scope_candidate when present; otherwise it uses step6_7 scope_layer when grounded and stays blank when the reviewer-editable gap is preserved.",
            "field_provenance_map": "Step 6.7 field provenance map is preserved into the packet, while historical Step 6.7B triage metadata and Step 6.75 canonicalization metadata are carried alongside it when present.",
            "evidence_spans": "step6_7.kc_draft_bundles.evidence_bundle sanitized to drop spans whose page_index cannot be safely coerced to a non-negative integer",
            "trust_state": "step6_7.kc_draft_bundles.trust_state carried forward into the reviewer packet without semantic repair",
            "review_readiness": "step6_7.kc_draft_bundles.review_readiness carried forward into the reviewer packet without semantic repair",
            "risk_flags": "step6_7 semantic risk flags plus explicit scope-gap packet metadata",
            "review_priority": "src/kc_l/kc/supervision.py computed from conservative features derived from the Step 6.7 draft bundle",
            "system_recommendation": "src/kc_l/kc/supervision.py recommendation output, then Step 6.8 narrows it so structurally valid coverage-only packets remain review_needed with review_edit_required, only clean ready-grounded packets stay approve_ready, and only structurally suspicious packets remain reject_recommended.",
            "step6_7_drafting_runtime": "Step 6.7 run summary or draft stats proof of execution mode, resolved model alias, config field, and llm call count",
        },
        "grounding_rules": {
            "one_packet_per_kc_rule": "Every Step 6.7 KC bundle emits exactly one Step 6.8 review packet.",
            "survival_rule": "Weak Step 6.7 bundles remain in the review lane as explicit coverage-only packets and are not silently excluded.",
            "coverage_rule": "Coverage survival comes from hierarchy-based representation in coverage_state and never from injected definition fallback text.",
            "authoritative_definition_status_rule": "Authoritative definition status is explicit: direct_grounded, normalized_grounded, or insufficient_support.",
            "reviewer_decision_bundle_rule": "Packets preserve coverage_state, trust_state, and review_readiness so the reviewer does not need to reconstruct hidden Step 6.7 state.",
            "review_recommendation_rule": "Step 6.8 keeps benign coverage-only packets and grounded-but-incomplete packets at review_needed, adds review_edit_required reason codes to structurally valid coverage-only survivors, allows approve_ready only for clean ready-grounded packets, and reserves reject_recommended for the narrow structurally suspicious subset.",
            "hierarchy_ref_rule": "Packets preserve typed topic hierarchy refs plus a denormalized hierarchy ancestry snapshot.",
            "context_preservation_rule": "Contextual evidence is preserved from the Step 6.7 evidence bundle even when the definition surface stays unresolved.",
            "scope_gap_rule": "Missing scope is preserved as an explicit reviewer-editable gap and never invented.",
            "content_repair_rule": "No new semantic repair is applied in the restarted packet stage.",
            "evidence_span_sanitation_rule": "Packetization drops any evidence span whose page_index cannot be safely coerced to a non-negative integer and marks the packet with invalid_page_index_dropped.",
        },
    }


def build_preview_markdown(
    *,
    source_processed_dir: Path,
    packets: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
) -> str:
    lines = [
        "# Restarted Review Packet Preview",
        "",
        f"- Source processed dir: `{source_processed_dir}`",
        f"- Packet count: `{summary['packet_count']}`",
        f"- Included KCs: `{summary['included_kcs']}`",
        f"- Coverage-only KCs: `{summary.get('coverage_only_kcs', [])}`",
        f"- Insufficient-support KCs: `{summary.get('insufficient_support_definition_kcs', [])}`",
        f"- Dropped invalid page-index spans: `{summary.get('dropped_invalid_page_index_span_count', 0)}`",
        f"- Scope-gap packets: `{summary['packets_with_scope_gaps']}`",
        f"- Caution-flag packets: `{summary['packets_with_caution_flags']}`",
        f"- Recommendation counts: `{summary['recommendation_counts']}`",
        f"- Priority counts: `{summary['priority_counts']}`",
        "",
        "## Packets",
        "",
    ]
    for packet in packets:
        lines.extend(
            [
                f"### {packet['kc_candidate_id']} - {packet['title_draft']}",
                "",
                f"- Draft status: `{packet['draft_status']}`",
                f"- Authoritative definition status: `{packet.get('authoritative_definition_status', '')}`",
                f"- Priority: `{packet['review_priority']['bucket']}`",
                f"- Recommendation: `{packet['system_recommendation']['label']}`",
                f"- Scope status: `{packet['scope_status']}`",
                f"- Risk flags: `{packet['risk_flags']}`",
                f"- Definition draft: `{packet['definition_draft']}`",
                f"- Scope draft: `{packet['scope_draft']}`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def emit_restarted_review_packets_from_draft_bundles(
    *,
    source_processed_dir: Path,
    output_dir: Path,
    draft_rows: Sequence[Mapping[str, Any]],
    step4_set_id: str,
    step4_5_set_id: str,
    step5_set_id: str,
    step6_6_set_id: str,
    step6_7_set_id: str,
    step6_8_run_id: str,
    step6_7b_set_id: str = "",
    step6_75_set_id: str = "",
    step6_7_drafting_runtime: Mapping[str, Any] | None = None,
) -> RestartedReviewPacketEmissionResult:
    packets: list[dict[str, Any]] = []
    dropped_invalid_page_index_span_count = 0

    for row in draft_rows:
        build_result = _build_restarted_review_packet_with_metadata(
            draft_bundle=row,
            step4_set_id=step4_set_id,
            step4_5_set_id=step4_5_set_id,
            step5_set_id=step5_set_id,
            step6_6_set_id=step6_6_set_id,
            step6_7_set_id=step6_7_set_id,
            step6_7b_set_id=step6_7b_set_id,
            step6_75_set_id=step6_75_set_id,
            step6_8_run_id=step6_8_run_id,
        )
        packet = build_result.packet
        dropped_invalid_page_index_span_count += build_result.dropped_invalid_page_index_span_count
        validate_restarted_review_packet(packet)
        packets.append(packet)

    summary = build_summary(
        source_processed_dir=source_processed_dir,
        packets=packets,
        draft_rows=draft_rows,
        quarantine=[],
        exclusions=[],
        step6_7_drafting_runtime=step6_7_drafting_runtime,
        dropped_invalid_page_index_span_count=dropped_invalid_page_index_span_count,
    )
    preview = build_preview_markdown(
        source_processed_dir=source_processed_dir,
        packets=packets,
        summary=summary,
    )

    output_dir.mkdir(parents=True, exist_ok=True)

    packet_path = output_dir / "review_packets.jsonl"
    summary_path = output_dir / "review_packet_summary.json"
    preview_path = output_dir / "review_packet_preview.md"

    write_jsonl(packet_path, packets)
    write_json(summary_path, summary)
    preview_path.write_text(preview, encoding="utf-8")

    return RestartedReviewPacketEmissionResult(
        output_dir=output_dir,
        packet_path=packet_path,
        summary_path=summary_path,
        preview_path=preview_path,
        packet_count=len(packets),
        excluded_candidate_count=0,
    )
