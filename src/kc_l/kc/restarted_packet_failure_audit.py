from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from kc_l.retrieval_gate.text_normalize import match_normalize
from kc_l.utils.json_io import read_json, read_jsonl, write_json, write_jsonl


PACKET_FAILURE_AUDIT_STAGE = "step6_14_packet_failure_audit_restarted"
PACKET_FAILURE_AUDIT_RULE_VERSION = "step6.14.packet_failure_audit.v1"
COHORT_REGISTRY_SCHEMA_VERSION = "step6.packet_cohort_registry.restarted.v1"
FAILURE_MATRIX_SCHEMA_VERSION = "step6.packet_failure_matrix.restarted.v1"
DOSSIER_SCHEMA_VERSION = "step6.packet_failure_dossiers.restarted.v1"

NORM_TOKEN_RE = re.compile(r"[^a-z0-9]+")
BACKGROUND_CUE_PHRASES = [
    "how to build",
    "different types",
    "quality measurement",
    "training set",
    "test set",
    "candidate split",
    "choose the best",
    "for each",
    "invoke",
    "learning ",
    "split criteria",
    "very old, simple",
    "majority class label",
]

DOSSIER_SELECTION = {
    "approved": ["KC_CLF_NB_001", "KC_CLF_UND_002"],
    "edited_approved": ["KC_CLF_DT_004", "KC_EVAL_BASIC_004", "KC_EVAL_ENS_003"],
    "rejected": ["KC_CLF_DT_011", "KC_CLF_DT_002", "KC_CLF_NB_010"],
    "excluded-held": ["KC_EVAL_BASIC_001", "KC_CLU_EVAL_005"],
}


@dataclass(frozen=True)
class RestartedPacketFailureAuditResult:
    output_dir: Path
    registry_path: Path
    registry_summary_path: Path
    registry_preview_path: Path
    matrix_path: Path
    matrix_summary_path: Path
    matrix_preview_path: Path
    dossiers_json_path: Path
    dossiers_md_path: Path
    aggregate_summary_json_path: Path
    aggregate_report_md_path: Path


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _norm_list(values: Any) -> list[str]:
    out: list[str] = []
    for value in values or []:
        text = _as_text(value)
        if text and text not in out:
            out.append(text)
    return out


def _norm_text(value: Any) -> str:
    return NORM_TOKEN_RE.sub(" ", _as_text(value).lower()).strip()


def _unique_preserve(values: Sequence[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _as_text(value)
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _preview(value: Any, *, limit: int = 220) -> str:
    text = " ".join(_as_text(value).split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _title_from_row(row: Mapping[str, Any] | None) -> str:
    row = row or {}
    return _as_text(row.get("title") or row.get("title_draft") or row.get("canonical_name") or row.get("kc_id") or row.get("kc_candidate_id"))


def _canonical_name_from_row(row: Mapping[str, Any] | None) -> str:
    row = row or {}
    return _as_text(row.get("canonical_name") or row.get("title") or row.get("title_draft"))


def _aliases_from_row(row: Mapping[str, Any] | None) -> list[str]:
    row = row or {}
    return _norm_list(row.get("aliases"))


def _hierarchy_ancestry(row: Mapping[str, Any] | None) -> Mapping[str, Any]:
    row = row or {}
    return dict(row.get("hierarchy_ancestry") or {})


def _source_hierarchy_path(row: Mapping[str, Any] | None) -> list[str]:
    return _norm_list(_hierarchy_ancestry(row).get("source_hierarchy_path"))


def _parent_label(row: Mapping[str, Any] | None) -> str:
    source_path = _source_hierarchy_path(row)
    if len(source_path) >= 2:
        return source_path[-2]
    ancestor_labels = _norm_list(_hierarchy_ancestry(row).get("ancestor_labels"))
    if ancestor_labels:
        return ancestor_labels[-1]
    return ""


def _field_overlay_ids_from_provenance(field_provenance_map: Mapping[str, Any] | None) -> list[str]:
    field_provenance_map = field_provenance_map or {}
    out: list[str] = []
    for payload in field_provenance_map.values():
        if isinstance(payload, Mapping):
            out.extend(_norm_list(payload.get("overlay_candidate_ids")))
    return _unique_preserve(out)


def _overlay_ids_from_evidence_bundle(bundle: Sequence[Mapping[str, Any]] | None) -> list[str]:
    out: list[str] = []
    for row in bundle or []:
        if isinstance(row, Mapping):
            out.append(_as_text(row.get("overlay_candidate_id")))
    return _unique_preserve(out)


def _evidence_ids_from_spans(spans: Sequence[Mapping[str, Any]] | None) -> list[str]:
    out: list[str] = []
    for span in spans or []:
        if isinstance(span, Mapping):
            out.append(_as_text(span.get("evidence_id")))
    return _unique_preserve(out)


def _field_linked_count(field_linked_evidence_ids: Mapping[str, Any] | None) -> int:
    field_linked_evidence_ids = field_linked_evidence_ids or {}
    ids: list[str] = []
    for value in field_linked_evidence_ids.values():
        ids.extend(_norm_list(value))
    return len(_unique_preserve(ids))

def _reviewed_surface_text(packet_row: Mapping[str, Any] | None, audit_row: Mapping[str, Any] | None, resolved_row: Mapping[str, Any] | None, runtime_row: Mapping[str, Any] | None) -> str:
    packet_row = packet_row or {}
    audit_row = audit_row or {}
    resolved_row = resolved_row or {}
    runtime_row = runtime_row or {}
    return " ".join(
        part for part in [
            _as_text(audit_row.get("current_packet_text")),
            _as_text(packet_row.get("definition_draft")),
            _as_text(packet_row.get("scope_draft")),
            _as_text((resolved_row.get("final_text") or {}).get("definition")),
            _as_text((resolved_row.get("final_text") or {}).get("scope")),
            _as_text(runtime_row.get("display_text")),
        ]
        if _as_text(part)
    )


def _draft_surface_text(draft_row: Mapping[str, Any] | None) -> str:
    draft_row = draft_row or {}
    return " ".join(
        part for part in [
            _as_text(((draft_row.get("definition_full_candidate") or {}).get("text"))),
            _as_text(((draft_row.get("scope_candidate") or {}).get("text"))),
            *[_as_text((item or {}).get("candidate_text")) for item in list(draft_row.get("evidence_bundle") or [])[:3]],
        ]
        if _as_text(part)
    )


def _generic_background_hits(text: str) -> list[str]:
    lowered = _as_text(text).lower()
    return [phrase for phrase in BACKGROUND_CUE_PHRASES if phrase in lowered]


def _build_kc_metadata(*, draft_rows: Sequence[Mapping[str, Any]], packet_rows: Sequence[Mapping[str, Any]], frozen_rows: Sequence[Mapping[str, Any]], sandbox_rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for row in [*draft_rows, *packet_rows, *frozen_rows, *sandbox_rows]:
        kc_id = _as_text(row.get("kc_id") or row.get("kc_candidate_id"))
        if not kc_id:
            continue
        existing = metadata.get(kc_id, {})
        title = _title_from_row(row) or _as_text(existing.get("title"))
        canonical_name = _canonical_name_from_row(row) or _as_text(existing.get("canonical_name"))
        aliases = _unique_preserve([*_norm_list(existing.get("aliases")), *_aliases_from_row(row)])
        hierarchy_path = _source_hierarchy_path(row) or list(existing.get("source_hierarchy_path") or [])
        metadata[kc_id] = {
            "kc_id": kc_id,
            "title": title,
            "canonical_name": canonical_name,
            "aliases": aliases,
            "parent_label": _parent_label(row) or _as_text(existing.get("parent_label")),
            "source_hierarchy_path": hierarchy_path,
        }
    return metadata


def _build_family_term_map(metadata_by_kc: Mapping[str, Mapping[str, Any]]) -> dict[str, list[str]]:
    by_parent: dict[str, list[str]] = defaultdict(list)
    for kc_id, meta in metadata_by_kc.items():
        parent = _as_text(meta.get("parent_label"))
        if parent:
            by_parent[parent].append(kc_id)
    out: dict[str, list[str]] = {}
    for kc_id, meta in metadata_by_kc.items():
        parent = _as_text(meta.get("parent_label"))
        sibling_terms: list[str] = []
        for sibling_kc in by_parent.get(parent, []):
            if sibling_kc == kc_id:
                continue
            sibling_meta = metadata_by_kc[sibling_kc]
            sibling_terms.extend([
                _as_text(sibling_meta.get("title")),
                _as_text(sibling_meta.get("canonical_name")),
                *_norm_list(sibling_meta.get("aliases")),
            ])
        out[kc_id] = _unique_preserve([term for term in sibling_terms if len(_norm_text(term)) >= 4])
    return out


def _sibling_overlap_hits(kc_id: str, text: str, sibling_term_map: Mapping[str, Sequence[str]]) -> list[str]:
    normalized_text = match_normalize(text)
    hits: list[str] = []
    for label in sibling_term_map.get(kc_id, []):
        norm_label = match_normalize(label)
        if norm_label and norm_label in normalized_text:
            hits.append(label)
    return _unique_preserve(hits)


def _build_retrieval_trace_map(validation_results: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, list[str]]]:
    trace_map: dict[str, dict[str, list[str]]] = defaultdict(lambda: {"appears_in_queries": [], "ambiguous_queries": [], "weak_queries": []})
    for result in validation_results:
        query_id = _as_text(result.get("query_id"))
        evaluation = dict(result.get("evaluation") or {})
        ambiguous = bool(evaluation.get("same_parent_confusion")) or not bool(evaluation.get("top1_hit"))
        weak = not bool(evaluation.get("top3_hit"))
        for top in list(result.get("top_results") or []):
            kc_id = _as_text(top.get("kc_id"))
            if not kc_id:
                continue
            trace_map[kc_id]["appears_in_queries"].append(query_id)
            if ambiguous:
                trace_map[kc_id]["ambiguous_queries"].append(query_id)
            if weak:
                trace_map[kc_id]["weak_queries"].append(query_id)
    for payload in trace_map.values():
        payload["appears_in_queries"] = _unique_preserve(payload["appears_in_queries"])
        payload["ambiguous_queries"] = _unique_preserve(payload["ambiguous_queries"])
        payload["weak_queries"] = _unique_preserve(payload["weak_queries"])
    return dict(trace_map)


def _filled_blank_field_counts(*, definition_text: str, scope_text: str) -> tuple[int, int]:
    filled = sum(1 for value in [definition_text, scope_text] if _as_text(value))
    return filled, 2 - filled


def _tentative_stage_candidate(*, outcome: str, packet_row: Mapping[str, Any] | None, sibling_hits: Sequence[str], background_hits: Sequence[str], evidence_sparsity_indicator: bool, packet_alone_sufficient: bool, content_repair_applied: bool) -> str:
    if outcome == "excluded-held":
        return "legitimate abstention / not enough evidence"
    if outcome in {"edited_approved", "rejected"}:
        if _as_text((packet_row or {}).get("content_source_mode")) == "step6_7_draft_primary" and not content_repair_applied:
            if sibling_hits or background_hits or evidence_sparsity_indicator or not packet_alone_sufficient or "draft_ready_with_holds" in list((packet_row or {}).get("risk_flags") or []):
                return "Step 6.7 drafting"
        return "unresolved / cannot determine"
    return "unresolved / cannot determine"


def _review_note(audit_row: Mapping[str, Any] | None, resolved_row: Mapping[str, Any] | None, excluded_assessment: Mapping[str, Any] | None) -> str:
    values = [
        _as_text((resolved_row or {}).get("review_notes")),
        _as_text((resolved_row or {}).get("rejection_reason")),
        _as_text((audit_row or {}).get("review_notes")),
        _as_text((audit_row or {}).get("rejection_reason")),
        _as_text((excluded_assessment or {}).get("verdict_rationale")),
    ]
    for value in values:
        if value:
            return value
    return ""


def _source_set_ids(packet_row: Mapping[str, Any] | None) -> Mapping[str, Any]:
    packet_row = packet_row or {}
    return dict(((packet_row.get("source_provenance") or {}).get("source_set_ids") or {}))

def build_packet_cohort_registry(*, review_packet_rows: Sequence[Mapping[str, Any]], review_audit_rows: Sequence[Mapping[str, Any]], resolved_rows: Sequence[Mapping[str, Any]], frozen_rows: Sequence[Mapping[str, Any]], sandbox_rows: Sequence[Mapping[str, Any]], runtime_rows: Sequence[Mapping[str, Any]], retrieval_rows: Sequence[Mapping[str, Any]], draft_rows: Sequence[Mapping[str, Any]], excluded_assessments: Sequence[Mapping[str, Any]], retrieval_validation_results: Sequence[Mapping[str, Any]], packet_path: Path, draft_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    packets_by_kc = {_as_text(row.get("kc_candidate_id")): row for row in review_packet_rows}
    audits_by_kc = {_as_text(row.get("kc_candidate_id")): row for row in review_audit_rows}
    resolved_by_kc = {_as_text(row.get("kc_candidate_id")): row for row in resolved_rows}
    frozen_by_kc = {_as_text(row.get("kc_id")): row for row in frozen_rows}
    sandbox_by_kc = {_as_text(row.get("kc_id")): row for row in sandbox_rows}
    runtime_by_kc = {_as_text(row.get("kc_id")): row for row in runtime_rows}
    retrieval_by_kc = {_as_text(row.get("kc_id")): row for row in retrieval_rows}
    draft_by_kc = {_as_text(row.get("kc_id")): row for row in draft_rows}
    excluded_by_kc = {_as_text(row.get("kc_candidate_id")): row for row in excluded_assessments}
    metadata_by_kc = _build_kc_metadata(draft_rows=draft_rows, packet_rows=review_packet_rows, frozen_rows=frozen_rows, sandbox_rows=sandbox_rows)
    sibling_term_map = _build_family_term_map(metadata_by_kc)
    retrieval_trace_map = _build_retrieval_trace_map(retrieval_validation_results)

    all_kc_ids = sorted({*draft_by_kc, *packets_by_kc, *resolved_by_kc, *frozen_by_kc, *sandbox_by_kc})
    registry_rows: list[dict[str, Any]] = []
    for kc_id in all_kc_ids:
        packet_row = packets_by_kc.get(kc_id)
        audit_row = audits_by_kc.get(kc_id)
        resolved_row = resolved_by_kc.get(kc_id)
        frozen_row = frozen_by_kc.get(kc_id)
        sandbox_row = sandbox_by_kc.get(kc_id)
        runtime_row = runtime_by_kc.get(kc_id)
        retrieval_row = retrieval_by_kc.get(kc_id)
        draft_row = draft_by_kc.get(kc_id)
        excluded_assessment = excluded_by_kc.get(kc_id)
        meta = metadata_by_kc.get(kc_id, {"kc_id": kc_id})

        packet_inclusion_status = "reviewed" if packet_row is not None else "excluded-held"
        final_outcome = _as_text((resolved_row or {}).get("final_status")) or "excluded-held"
        step6_7_overlay_ids = _field_overlay_ids_from_provenance((packet_row or {}).get("field_provenance_map")) or _field_overlay_ids_from_provenance((draft_row or {}).get("field_provenance_map"))
        step6_7_overlay_ids = _unique_preserve([*step6_7_overlay_ids, *_overlay_ids_from_evidence_bundle((draft_row or {}).get("evidence_bundle"))])
        review_event_id = _as_text((resolved_row or {}).get("review_event_id") or (audit_row or {}).get("review_event_id"))
        retrieval_trace = retrieval_trace_map.get(kc_id, {"appears_in_queries": [], "ambiguous_queries": [], "weak_queries": []})
        registry_rows.append({
            "schema_version": COHORT_REGISTRY_SCHEMA_VERSION,
            "kc_id": kc_id,
            "title": _as_text(meta.get("title")),
            "canonical_name": _as_text(meta.get("canonical_name")),
            "parent_label": _as_text(meta.get("parent_label")),
            "source_hierarchy_path": list(meta.get("source_hierarchy_path") or []),
            "packet_inclusion_status": packet_inclusion_status,
            "final_outcome": final_outcome,
            "packet_source_artifact": str(packet_path),
            "review_packet_id": _as_text((packet_row or {}).get("review_packet_id")),
            "review_event_id": review_event_id,
            "resolved_audit_event_id": review_event_id if resolved_row is not None else "",
            "reviewed_library_present": frozen_row is not None,
            "sandbox_present": sandbox_row is not None,
            "runtime_present": runtime_row is not None,
            "retrieval_pilot_present": retrieval_row is not None,
            "step6_7_draft_artifact": str(draft_path),
            "step6_7_draft_status": _as_text((draft_row or {}).get("draft_status")),
            "step6_6_overlay_set_id": _as_text(_source_set_ids(packet_row).get("step6_6_set_id") or (draft_row or {}).get("draft_input_overlay_set_id")),
            "step6_7_set_id": _as_text(_source_set_ids(packet_row).get("step6_7_set_id")),
            "linked_overlay_candidate_ids": step6_7_overlay_ids,
            "linked_evidence_ids": _norm_list((frozen_row or {}).get("linked_evidence_ids") or (audit_row or {}).get("linked_evidence_ids") or _evidence_ids_from_spans((packet_row or {}).get("evidence_spans"))),
            "retrieval_validation_queries": list(retrieval_trace.get("appears_in_queries") or []),
            "retrieval_ambiguity_queries": list(retrieval_trace.get("ambiguous_queries") or []),
            "is_kc_clf_dt_011": kc_id == "KC_CLF_DT_011",
        })
    return registry_rows, retrieval_trace_map


def build_packet_failure_matrix(*, registry_rows: Sequence[Mapping[str, Any]], review_packet_rows: Sequence[Mapping[str, Any]], review_audit_rows: Sequence[Mapping[str, Any]], resolved_rows: Sequence[Mapping[str, Any]], frozen_rows: Sequence[Mapping[str, Any]], sandbox_rows: Sequence[Mapping[str, Any]], retrieval_rows: Sequence[Mapping[str, Any]], draft_rows: Sequence[Mapping[str, Any]], excluded_assessments: Sequence[Mapping[str, Any]], retrieval_trace_map: Mapping[str, Mapping[str, list[str]]]) -> list[dict[str, Any]]:
    packets_by_kc = {_as_text(row.get("kc_candidate_id")): row for row in review_packet_rows}
    audits_by_kc = {_as_text(row.get("kc_candidate_id")): row for row in review_audit_rows}
    resolved_by_kc = {_as_text(row.get("kc_candidate_id")): row for row in resolved_rows}
    frozen_by_kc = {_as_text(row.get("kc_id")): row for row in frozen_rows}
    sandbox_by_kc = {_as_text(row.get("kc_id")): row for row in sandbox_rows}
    retrieval_by_kc = {_as_text(row.get("kc_id")): row for row in retrieval_rows}
    draft_by_kc = {_as_text(row.get("kc_id")): row for row in draft_rows}
    excluded_by_kc = {_as_text(row.get("kc_candidate_id")): row for row in excluded_assessments}
    metadata_by_kc = _build_kc_metadata(draft_rows=draft_rows, packet_rows=review_packet_rows, frozen_rows=frozen_rows, sandbox_rows=sandbox_rows)
    sibling_term_map = _build_family_term_map(metadata_by_kc)

    rows: list[dict[str, Any]] = []
    for registry in registry_rows:
        outcome = _as_text(registry.get("final_outcome"))
        if outcome == "approved":
            continue
        kc_id = _as_text(registry.get("kc_id"))
        packet_row = packets_by_kc.get(kc_id)
        audit_row = audits_by_kc.get(kc_id)
        resolved_row = resolved_by_kc.get(kc_id)
        frozen_row = frozen_by_kc.get(kc_id)
        draft_row = draft_by_kc.get(kc_id)
        excluded_assessment = excluded_by_kc.get(kc_id)
        retrieval_row = retrieval_by_kc.get(kc_id)
        reviewed_definition = _as_text((packet_row or {}).get("definition_draft")) or _as_text(((draft_row or {}).get("definition_full_candidate") or {}).get("text"))
        reviewed_scope = _as_text((packet_row or {}).get("scope_draft")) or _as_text(((draft_row or {}).get("scope_candidate") or {}).get("text"))
        filled_fields, blank_fields = _filled_blank_field_counts(definition_text=reviewed_definition, scope_text=reviewed_scope)
        evidence_ids = _norm_list((audit_row or {}).get("linked_evidence_ids") or (frozen_row or {}).get("linked_evidence_ids") or _evidence_ids_from_spans((packet_row or {}).get("evidence_spans")) or _overlay_ids_from_evidence_bundle((draft_row or {}).get("evidence_bundle")))
        field_linked_count = _field_linked_count((audit_row or {}).get("field_linked_evidence_ids") or (frozen_row or {}).get("field_linked_evidence_ids"))
        if field_linked_count == 0 and draft_row is not None:
            field_linked_count = len(_field_overlay_ids_from_provenance((draft_row or {}).get("field_provenance_map")))
        combined_text = _reviewed_surface_text(packet_row, audit_row, resolved_row, retrieval_row) if packet_row is not None else _draft_surface_text(draft_row)
        sibling_hits = _sibling_overlap_hits(kc_id, combined_text, sibling_term_map)
        background_hits = _generic_background_hits(combined_text)
        risk_flags = _norm_list((packet_row or {}).get("risk_flags") or (draft_row or {}).get("hold_reasons") or (excluded_assessment or {}).get("summary_exclusion_reasons"))
        intentionally_blank_scope = bool((frozen_row or {}).get("scope_blank_is_intentional")) or _as_text((frozen_row or {}).get("scope_status") or (resolved_row or {}).get("scope_status_at_review")) == "intentionally_blank"
        evidence_sparsity_indicator = len(evidence_ids) <= 2
        packet_alone_sufficient = bool((audit_row or {}).get("packet_alone_sufficient"))
        raw_internals_needed = bool((audit_row or {}).get("raw_internals_reopened")) if packet_row is not None else bool((excluded_assessment or {}).get("requires_raw_internals"))
        content_repair_applied = bool((packet_row or {}).get("content_repair_applied"))
        tentative_stage = _tentative_stage_candidate(outcome=outcome, packet_row=packet_row, sibling_hits=sibling_hits, background_hits=background_hits, evidence_sparsity_indicator=evidence_sparsity_indicator, packet_alone_sufficient=packet_alone_sufficient, content_repair_applied=content_repair_applied)
        rows.append({
            "schema_version": FAILURE_MATRIX_SCHEMA_VERSION,
            "kc_id": kc_id,
            "cohort_outcome": outcome,
            "packet_risk_flags": risk_flags,
            "intentionally_blank_scope": intentionally_blank_scope,
            "filled_reviewer_field_count": filled_fields,
            "blank_reviewer_field_count": blank_fields,
            "evidence_id_count": len(evidence_ids),
            "field_linked_evidence_count": field_linked_count,
            "evidence_sparsity_indicator": evidence_sparsity_indicator,
            "weak_coverage_indicator": "review_queue_weak_coverage" in risk_flags,
            "sibling_overlap_lexical_cue": bool(sibling_hits),
            "sibling_overlap_terms": sibling_hits,
            "generic_background_cue": bool(background_hits),
            "generic_background_terms": background_hits,
            "review_changed_field_count": len(list((resolved_row or {}).get("edited_fields") or [])),
            "reject_marker": outcome == "rejected",
            "reject_rationale_text": _review_note(audit_row, resolved_row, excluded_assessment),
            "packet_alone_sufficient": packet_alone_sufficient if packet_row is not None else False,
            "raw_internals_needed": raw_internals_needed,
            "retrieval_pilot_included": retrieval_row is not None,
            "retrieval_ambiguity_observed": bool((retrieval_trace_map.get(kc_id) or {}).get("ambiguous_queries")),
            "retrieval_ambiguity_queries": list((retrieval_trace_map.get(kc_id) or {}).get("ambiguous_queries") or []),
            "tentative_earliest_failing_stage_candidate": tentative_stage,
        })
    return rows

def build_representative_dossiers(*, registry_rows: Sequence[Mapping[str, Any]], failure_rows: Sequence[Mapping[str, Any]], review_packet_rows: Sequence[Mapping[str, Any]], review_audit_rows: Sequence[Mapping[str, Any]], resolved_rows: Sequence[Mapping[str, Any]], draft_rows: Sequence[Mapping[str, Any]], retrieval_trace_map: Mapping[str, Mapping[str, list[str]]]) -> list[dict[str, Any]]:
    registry_by_kc = {_as_text(row.get("kc_id")): row for row in registry_rows}
    matrix_by_kc = {_as_text(row.get("kc_id")): row for row in failure_rows}
    packets_by_kc = {_as_text(row.get("kc_candidate_id")): row for row in review_packet_rows}
    audits_by_kc = {_as_text(row.get("kc_candidate_id")): row for row in review_audit_rows}
    resolved_by_kc = {_as_text(row.get("kc_candidate_id")): row for row in resolved_rows}
    draft_by_kc = {_as_text(row.get("kc_id")): row for row in draft_rows}

    dossiers: list[dict[str, Any]] = []
    for outcome, kc_ids in DOSSIER_SELECTION.items():
        for kc_id in kc_ids:
            registry = registry_by_kc[kc_id]
            matrix = matrix_by_kc.get(kc_id, {})
            packet_row = packets_by_kc.get(kc_id)
            audit_row = audits_by_kc.get(kc_id)
            resolved_row = resolved_by_kc.get(kc_id)
            draft_row = draft_by_kc.get(kc_id)
            if packet_row is not None:
                packet_text_snapshot = _preview(_as_text((audit_row or {}).get("current_packet_text")) or _reviewed_surface_text(packet_row, audit_row, resolved_row, {}), limit=260)
                evidence_examples = [
                    {"evidence_id": _as_text(span.get("evidence_id")), "quote": _preview(span.get("quote"), limit=160)}
                    for span in list(packet_row.get("evidence_spans") or [])[:2]
                ]
            else:
                packet_text_snapshot = _preview(_draft_surface_text(draft_row), limit=260)
                evidence_examples = [
                    {"evidence_id": _as_text(item.get("overlay_candidate_id")), "quote": _preview(item.get("candidate_text"), limit=160)}
                    for item in list((draft_row or {}).get("evidence_bundle") or [])[:2]
                ]
            definition_text = _as_text((packet_row or {}).get("definition_draft")) or _as_text(((draft_row or {}).get("definition_full_candidate") or {}).get("text"))
            scope_text = _as_text((packet_row or {}).get("scope_draft")) or _as_text(((draft_row or {}).get("scope_candidate") or {}).get("text"))
            dossiers.append({
                "schema_version": DOSSIER_SCHEMA_VERSION,
                "kc_id": kc_id,
                "cohort_outcome": outcome,
                "title": _as_text(registry.get("title")),
                "packet_text_snapshot": packet_text_snapshot,
                "key_filled_fields": {"definition": _preview(definition_text, limit=180), "scope": _preview(scope_text, limit=180)} if scope_text else {"definition": _preview(definition_text, limit=180)},
                "key_blank_fields": [field for field, value in {"definition": definition_text, "scope": scope_text}.items() if not _as_text(value)],
                "evidence_examples": evidence_examples,
                "review_markers": {
                    "review_packet_id": _as_text((packet_row or {}).get("review_packet_id")),
                    "review_event_id": _as_text((resolved_row or {}).get("review_event_id") or (audit_row or {}).get("review_event_id")),
                    "action_taken": _as_text((resolved_row or {}).get("action_taken") or (audit_row or {}).get("action_taken")),
                    "edited_fields": list((resolved_row or {}).get("edited_fields") or []),
                    "review_note": _review_note(audit_row, resolved_row, None),
                },
                "lineage_refs": {
                    "step6_7_draft_status": _as_text(registry.get("step6_7_draft_status")),
                    "step6_6_overlay_set_id": _as_text(registry.get("step6_6_overlay_set_id")),
                    "linked_overlay_candidate_ids": list(registry.get("linked_overlay_candidate_ids") or [])[:4],
                },
                "retrieval_pilot_note": {
                    "included": bool(registry.get("retrieval_pilot_present")),
                    "ambiguity_queries": list((retrieval_trace_map.get(kc_id) or {}).get("ambiguous_queries") or []),
                    "weak_queries": list((retrieval_trace_map.get(kc_id) or {}).get("weak_queries") or []),
                },
                "extracted_anomalies": _unique_preserve([
                    *list(matrix.get("packet_risk_flags") or []),
                    *list(matrix.get("sibling_overlap_terms") or []),
                    *list(matrix.get("generic_background_terms") or []),
                    _as_text(matrix.get("tentative_earliest_failing_stage_candidate")),
                ]),
            })
    return dossiers


def build_registry_summary(registry_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "stage": PACKET_FAILURE_AUDIT_STAGE,
        "rule_version": PACKET_FAILURE_AUDIT_RULE_VERSION,
        "record_count": len(registry_rows),
        "packet_inclusion_counts": dict(Counter(_as_text(row.get("packet_inclusion_status")) for row in registry_rows)),
        "final_outcome_counts": dict(Counter(_as_text(row.get("final_outcome")) for row in registry_rows)),
        "reviewed_library_present_count": sum(1 for row in registry_rows if bool(row.get("reviewed_library_present"))),
        "sandbox_present_count": sum(1 for row in registry_rows if bool(row.get("sandbox_present"))),
        "runtime_present_count": sum(1 for row in registry_rows if bool(row.get("runtime_present"))),
        "retrieval_pilot_present_count": sum(1 for row in registry_rows if bool(row.get("retrieval_pilot_present"))),
        "kc_clf_dt_011": next((row for row in registry_rows if _as_text(row.get("kc_id")) == "KC_CLF_DT_011"), {}),
    }


def build_failure_matrix_summary(failure_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "stage": PACKET_FAILURE_AUDIT_STAGE,
        "rule_version": PACKET_FAILURE_AUDIT_RULE_VERSION,
        "row_count": len(failure_rows),
        "cohort_outcome_counts": dict(Counter(_as_text(row.get("cohort_outcome")) for row in failure_rows)),
        "intentionally_blank_scope_count": sum(1 for row in failure_rows if bool(row.get("intentionally_blank_scope"))),
        "evidence_sparsity_count": sum(1 for row in failure_rows if bool(row.get("evidence_sparsity_indicator"))),
        "weak_coverage_count": sum(1 for row in failure_rows if bool(row.get("weak_coverage_indicator"))),
        "sibling_overlap_count": sum(1 for row in failure_rows if bool(row.get("sibling_overlap_lexical_cue"))),
        "generic_background_cue_count": sum(1 for row in failure_rows if bool(row.get("generic_background_cue"))),
        "retrieval_ambiguity_count": sum(1 for row in failure_rows if bool(row.get("retrieval_ambiguity_observed"))),
        "edit_heavy_count": sum(1 for row in failure_rows if int(row.get("review_changed_field_count") or 0) >= 2),
        "edit_lighter_count": sum(1 for row in failure_rows if 0 < int(row.get("review_changed_field_count") or 0) < 2),
        "tentative_stage_counts": dict(Counter(_as_text(row.get("tentative_earliest_failing_stage_candidate")) for row in failure_rows)),
    }


def build_aggregate_summary(registry_summary: Mapping[str, Any], matrix_summary: Mapping[str, Any], dossiers: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "stage": PACKET_FAILURE_AUDIT_STAGE,
        "rule_version": PACKET_FAILURE_AUDIT_RULE_VERSION,
        "registry": dict(registry_summary),
        "failure_matrix": dict(matrix_summary),
        "dossier_count": len(dossiers),
        "dossier_kcs": [_as_text(item.get("kc_id")) for item in dossiers],
    }


def build_registry_preview(registry_rows: Sequence[Mapping[str, Any]], registry_summary: Mapping[str, Any]) -> str:
    lines = ["# Packet Cohort Registry Preview", "", f"- Record count: `{registry_summary['record_count']}`", f"- Final outcomes: `{registry_summary['final_outcome_counts']}`", "", "| KC | Inclusion | Outcome | Frozen | Sandbox | Runtime | Retrieval |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in registry_rows:
        lines.append(f"| {row['kc_id']} | {row['packet_inclusion_status']} | {row['final_outcome']} | {row['reviewed_library_present']} | {row['sandbox_present']} | {row['runtime_present']} | {row['retrieval_pilot_present']} |")
    return "\n".join(lines) + "\n"


def build_failure_preview(failure_rows: Sequence[Mapping[str, Any]], matrix_summary: Mapping[str, Any]) -> str:
    lines = ["# Packet Failure Matrix Preview", "", f"- Row count: `{matrix_summary['row_count']}`", f"- Outcome counts: `{matrix_summary['cohort_outcome_counts']}`", f"- Tentative stage counts: `{matrix_summary['tentative_stage_counts']}`", "", "| KC | Outcome | Sparse | SiblingCue | BackgroundCue | RetrievalAmbiguity | TentativeStage |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in failure_rows:
        lines.append(f"| {row['kc_id']} | {row['cohort_outcome']} | {row['evidence_sparsity_indicator']} | {row['sibling_overlap_lexical_cue']} | {row['generic_background_cue']} | {row['retrieval_ambiguity_observed']} | {row['tentative_earliest_failing_stage_candidate']} |")
    return "\n".join(lines) + "\n"

def build_dossiers_markdown(dossiers: Sequence[Mapping[str, Any]]) -> str:
    lines = ["# Representative Packet Dossiers", ""]
    for dossier in dossiers:
        lines.extend([
            f"## {dossier['kc_id']} - {dossier['cohort_outcome']}",
            "",
            f"- Title: `{dossier['title']}`",
            f"- Packet text snapshot: `{dossier['packet_text_snapshot']}`",
            f"- Key blank fields: `{dossier['key_blank_fields']}`",
            f"- Review markers: `{dossier['review_markers']}`",
            f"- Lineage refs: `{dossier['lineage_refs']}`",
            f"- Retrieval note: `{dossier['retrieval_pilot_note']}`",
            f"- Extracted anomalies: `{dossier['extracted_anomalies']}`",
            "",
        ])
    return "\n".join(lines)


def build_aggregate_report(*, registry_summary: Mapping[str, Any], matrix_summary: Mapping[str, Any], dossiers: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "# Packet Failure Audit Summary",
        "",
        f"- Registry record count: `{registry_summary['record_count']}`",
        f"- Final outcomes: `{registry_summary['final_outcome_counts']}`",
        f"- Failure matrix row count: `{matrix_summary['row_count']}`",
        f"- Intentionally blank scope count: `{matrix_summary['intentionally_blank_scope_count']}`",
        f"- Evidence sparsity count: `{matrix_summary['evidence_sparsity_count']}`",
        f"- Sibling-overlap cue count: `{matrix_summary['sibling_overlap_count']}`",
        f"- Generic-background cue count: `{matrix_summary['generic_background_cue_count']}`",
        f"- Retrieval ambiguity count: `{matrix_summary['retrieval_ambiguity_count']}`",
        f"- Tentative stage counts: `{matrix_summary['tentative_stage_counts']}`",
        f"- Representative dossier KCs: `{[_as_text(item.get('kc_id')) for item in dossiers]}`",
    ]
    return "\n".join(lines) + "\n"


def assemble_restarted_packet_failure_audit(*, review_packet_path: Path, review_packet_summary_path: Path, review_audit_path: Path, review_audit_summary_path: Path, resolved_audit_path: Path, resolved_audit_summary_path: Path, frozen_reviewed_library_path: Path, reviewed_library_summary_path: Path, sandbox_path: Path, sandbox_summary_path: Path, runtime_library_path: Path, retrieval_source_path: Path, retrieval_validation_results_path: Path, step6_7_draft_path: Path, output_dir: Path) -> RestartedPacketFailureAuditResult:
    review_packet_rows = read_jsonl(review_packet_path)
    review_packet_summary = read_json(review_packet_summary_path)
    review_audit_rows = read_jsonl(review_audit_path)
    review_audit_summary = read_json(review_audit_summary_path)
    resolved_rows = read_jsonl(resolved_audit_path)
    resolved_audit_summary = read_json(resolved_audit_summary_path)
    frozen_rows = read_jsonl(frozen_reviewed_library_path)
    reviewed_library_summary = read_json(reviewed_library_summary_path)
    sandbox_rows = read_jsonl(sandbox_path)
    sandbox_summary = read_json(sandbox_summary_path)
    runtime_rows = read_jsonl(runtime_library_path)
    retrieval_rows = read_jsonl(retrieval_source_path)
    retrieval_validation_results = read_json(retrieval_validation_results_path)
    draft_rows = read_jsonl(step6_7_draft_path)

    registry_rows, retrieval_trace_map = build_packet_cohort_registry(
        review_packet_rows=review_packet_rows,
        review_audit_rows=review_audit_rows,
        resolved_rows=resolved_rows,
        frozen_rows=frozen_rows,
        sandbox_rows=sandbox_rows,
        runtime_rows=runtime_rows,
        retrieval_rows=retrieval_rows,
        draft_rows=draft_rows,
        excluded_assessments=list(review_audit_summary.get("excluded_case_assessments") or []),
        retrieval_validation_results=list(retrieval_validation_results or []),
        packet_path=review_packet_path,
        draft_path=step6_7_draft_path,
    )
    failure_rows = build_packet_failure_matrix(
        registry_rows=registry_rows,
        review_packet_rows=review_packet_rows,
        review_audit_rows=review_audit_rows,
        resolved_rows=resolved_rows,
        frozen_rows=frozen_rows,
        sandbox_rows=sandbox_rows,
        retrieval_rows=retrieval_rows,
        draft_rows=draft_rows,
        excluded_assessments=list(review_audit_summary.get("excluded_case_assessments") or []),
        retrieval_trace_map=retrieval_trace_map,
    )
    dossiers = build_representative_dossiers(
        registry_rows=registry_rows,
        failure_rows=failure_rows,
        review_packet_rows=review_packet_rows,
        review_audit_rows=review_audit_rows,
        resolved_rows=resolved_rows,
        draft_rows=draft_rows,
        retrieval_trace_map=retrieval_trace_map,
    )

    registry_summary = build_registry_summary(registry_rows)
    matrix_summary = build_failure_matrix_summary(failure_rows)
    aggregate_summary = build_aggregate_summary(registry_summary, matrix_summary, dossiers)
    registry_preview = build_registry_preview(registry_rows, registry_summary)
    failure_preview = build_failure_preview(failure_rows, matrix_summary)
    dossiers_md = build_dossiers_markdown(dossiers)
    aggregate_report = build_aggregate_report(registry_summary=registry_summary, matrix_summary=matrix_summary, dossiers=dossiers)

    output_dir.mkdir(parents=True, exist_ok=True)
    registry_path = output_dir / "packet_cohort_registry.jsonl"
    registry_summary_path = output_dir / "packet_cohort_registry_summary.json"
    registry_preview_path = output_dir / "packet_cohort_registry_preview.md"
    matrix_path = output_dir / "packet_failure_matrix.jsonl"
    matrix_summary_path = output_dir / "packet_failure_matrix_summary.json"
    matrix_preview_path = output_dir / "packet_failure_matrix_preview.md"
    dossiers_json_path = output_dir / "representative_packet_dossiers.json"
    dossiers_md_path = output_dir / "representative_packet_dossiers.md"
    aggregate_summary_json_path = output_dir / "packet_failure_audit_summary.json"
    aggregate_report_md_path = output_dir / "packet_failure_audit_report.md"

    write_jsonl(registry_path, registry_rows)
    write_json(registry_summary_path, registry_summary)
    registry_preview_path.write_text(registry_preview, encoding="utf-8")
    write_jsonl(matrix_path, failure_rows)
    write_json(matrix_summary_path, matrix_summary)
    matrix_preview_path.write_text(failure_preview, encoding="utf-8")
    write_json(dossiers_json_path, list(dossiers))
    dossiers_md_path.write_text(dossiers_md, encoding="utf-8")
    write_json(aggregate_summary_json_path, aggregate_summary)
    aggregate_report_md_path.write_text(aggregate_report, encoding="utf-8")

    return RestartedPacketFailureAuditResult(
        output_dir=output_dir,
        registry_path=registry_path,
        registry_summary_path=registry_summary_path,
        registry_preview_path=registry_preview_path,
        matrix_path=matrix_path,
        matrix_summary_path=matrix_summary_path,
        matrix_preview_path=matrix_preview_path,
        dossiers_json_path=dossiers_json_path,
        dossiers_md_path=dossiers_md_path,
        aggregate_summary_json_path=aggregate_summary_json_path,
        aggregate_report_md_path=aggregate_report_md_path,
    )
