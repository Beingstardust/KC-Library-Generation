from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from kc_l.kc_drafting.contracts import (
    AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED,
    AUTHORITATIVE_DEFINITION_STATUS_NORMALIZED_GROUNDED,
    AUTHORITATIVE_DEFINITION_STATUS_SEED_FLOOR_FALLBACK,
    as_text,
)
from kc_l.kc_drafting.heuristic_core import assess_overlay_candidate
from kc_l.utils.json_io import write_json, write_jsonl

STEP67C_CONTRACT_VERSION = "step6_7c_seed_floor_recoverability_audit_v1"
STEP67C_STAGE_NAME = "step6_7c_seed_floor_recoverability_audit"

RECOVERABILITY_A_DIRECT = "A_direct"
RECOVERABILITY_B_NORMALIZED = "B_normalized"
RECOVERABILITY_C_NOT_RECOVERABLE = "C_not_recoverable"

FAILURE_FAMILIES = (
    "missing_target_witness",
    "missing_definition",
    "missing_formula",
    "missing_condition",
    "missing_consequence",
    "competitor_bleed",
    "genuine_sparsity",
)

TARGET_TERM_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "into", "using", "used", "use",
    "are", "was", "were", "can", "may", "not", "but", "does", "each", "such", "than", "then",
    "when", "where", "which", "what", "how", "why", "via", "per", "over", "under", "between",
    "within", "without", "only", "all", "any", "its", "their", "there", "have", "has", "had",
}


@dataclass(frozen=True)
class Step67CAuditResult:
    row: dict[str, Any]
    packet: dict[str, Any] | None
    failure: dict[str, Any] | None


@dataclass(frozen=True)
class Step67CEmissionResult:
    run_id: str
    processed_dir: Path
    run_dir: Path
    recoverability_rows_path: Path
    recoverability_packets_path: Path
    recoverability_failures_path: Path
    recoverability_stats_path: Path
    set_manifest_path: Path
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


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _utc_run_id() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")


def _parent_topic_key_from_bundle(bundle: Mapping[str, Any]) -> tuple[str, ...]:
    topic_path_ids = _normalize_string_list(bundle.get("topic_path_ids"))
    if len(topic_path_ids) >= 2:
        return tuple(topic_path_ids[:-1])
    topic_path_labels = _normalize_string_list(bundle.get("topic_path_labels"))
    if len(topic_path_labels) >= 2:
        return tuple(topic_path_labels[:-1])
    return tuple()


def _status_is_grounded(status: str) -> bool:
    return status in {
        AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED,
        AUTHORITATIVE_DEFINITION_STATUS_NORMALIZED_GROUNDED,
    }


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
        for item in bundle.get("evidence_bundle") or []:
            if not isinstance(item, Mapping):
                continue
            doc_id = as_text(item.get("doc_id"))
            page_index = _page_index(item.get("page_index"))
            if not doc_id or page_index is None:
                continue
            anchor_index.setdefault(parent_key, []).append(
                {
                    "doc_id": doc_id,
                    "page_index": page_index,
                    "selection_score": float(item.get("selection_score") or item.get("alignment_score") or 0.0),
                    "overlay_candidate_id": as_text(item.get("overlay_candidate_id")),
                    "block_id": as_text(item.get("block_id")),
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
            ),
        )
        compact_index[parent_key] = compact[:48]
    return compact_index


def _tokenize_target_terms(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9_]+", as_text(text).lower())
        if len(token) >= 3 and token not in TARGET_TERM_STOPWORDS
    ]


def _target_phrases(bundle: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for value in [bundle.get("canonical_name"), *(bundle.get("aliases") or [])]:
        phrase = as_text(value).lower().strip()
        if len(phrase) >= 3:
            _append_unique(out, phrase)
    return out[:16]


def _target_terms(bundle: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for value in [bundle.get("canonical_name"), *(bundle.get("aliases") or []), bundle.get("seed_definition")]:
        for token in _tokenize_target_terms(as_text(value)):
            _append_unique(out, token)
    return out[:64]


def _candidate_text(row: Mapping[str, Any], assessment: Mapping[str, Any]) -> str:
    return as_text(assessment.get("candidate_text") or row.get("quote_surface") or row.get("source_block_text"))


def _exact_target_witness(text: str, target_phrases: Sequence[str]) -> bool:
    lowered = as_text(text).lower()
    return any(phrase and phrase in lowered for phrase in target_phrases)


def _term_overlap_count(text: str, target_terms: Sequence[str]) -> int:
    lowered = as_text(text).lower()
    return sum(1 for term in target_terms if term and term in lowered)


def _seed_shape(bundle: Mapping[str, Any]) -> dict[str, bool]:
    seed = as_text(bundle.get("seed_definition")).lower()
    name = as_text(bundle.get("canonical_name")).lower()
    formula_required = any(
        marker in seed or marker in name
        for marker in ["=", "sum", "sqrt", "o(", "complexity", "entropy", "jaccard", "rand index", "mcnemar", "nemenyi", "friedman"]
    )
    condition_required = bool(re.search(r"\b(if|when|only if|provided that|whenever)\b", seed))
    consequence_required = bool(re.search(r"\b(therefore|thus|results in|leads to|means that|causes|so that|collapse)\b", seed))
    procedural_definition = any(
        marker in seed or marker in name
        for marker in ["algorithm", "strategy", "workflow", "leave-one-out", "cross validation", "procedure"]
    )
    return {
        "formula_required": formula_required,
        "condition_required": condition_required,
        "consequence_required": consequence_required,
        "procedural_definition": procedural_definition,
    }


def _make_evidence_item(
    *,
    row: Mapping[str, Any],
    assessment: Mapping[str, Any],
    origin: str,
    admission_basis: str,
) -> dict[str, Any]:
    return {
        "overlay_candidate_id": as_text(row.get("overlay_candidate_id")),
        "kc_id": as_text(row.get("kc_id")),
        "doc_id": as_text(row.get("doc_id")),
        "page_index": row.get("page_index"),
        "block_id": as_text(row.get("block_id")),
        "candidate_text": _candidate_text(row, assessment),
        "quote_surface": as_text(row.get("quote_surface")),
        "classification": as_text(assessment.get("classification")),
        "definition_signal": bool(assessment.get("definition_signal")),
        "scope_signal": bool(assessment.get("scope_signal")),
        "origin": origin,
        "admission_basis": admission_basis,
        "selection_score": float(row.get("selection_score") or assessment.get("selection_score") or 0.0),
    }


def _assign_roles(
    *,
    bundle: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    origin: str,
    target_terms: Sequence[str],
    target_phrases: Sequence[str],
    max_per_role: int,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    accepted = {
        "target_witness_spans": [],
        "definition_spans": [],
        "formula_spans": [],
        "condition_spans": [],
        "consequence_spans": [],
        "competitor_spans": [],
    }
    discarded: list[dict[str, Any]] = []
    target_kc_id = as_text(bundle.get("kc_id"))

    for row in rows:
        assessment = dict(assess_overlay_candidate(row))
        text = _candidate_text(row, assessment)
        text_lower = text.lower()
        row_kc_id = as_text(row.get("kc_id"))
        witness = _exact_target_witness(text, target_phrases)
        overlap = _term_overlap_count(text, target_terms)
        foreign = row_kc_id and row_kc_id != target_kc_id

        if foreign and not witness:
            discarded.append(
                {
                    "overlay_candidate_id": as_text(row.get("overlay_candidate_id")),
                    "discard_reason": "foreign_without_target_witness",
                }
            )
            continue

        classification = as_text(assessment.get("classification"))

        if witness and len(accepted["target_witness_spans"]) < max_per_role:
            accepted["target_witness_spans"].append(
                _make_evidence_item(
                    row=row,
                    assessment=assessment,
                    origin=origin,
                    admission_basis="exact_target_phrase",
                )
            )

        if (bool(assessment.get("definition_signal")) or (row_kc_id == target_kc_id and overlap >= 1)) and len(accepted["definition_spans"]) < max_per_role:
            accepted["definition_spans"].append(
                _make_evidence_item(
                    row=row,
                    assessment=assessment,
                    origin=origin,
                    admission_basis="same_kc_local" if row_kc_id == target_kc_id else "exact_target_phrase",
                )
            )

        if (classification in {"formula_only_support", "equation_support"} or re.search(r"(?:=|\bsum\b|\bsqrt\b|\bO\()", text)) and len(accepted["formula_spans"]) < max_per_role:
            accepted["formula_spans"].append(
                _make_evidence_item(
                    row=row,
                    assessment=assessment,
                    origin=origin,
                    admission_basis="formula_pair",
                )
            )

        if re.search(r"\b(if|when|only if|provided that|whenever)\b", text_lower) and len(accepted["condition_spans"]) < max_per_role:
            accepted["condition_spans"].append(
                _make_evidence_item(
                    row=row,
                    assessment=assessment,
                    origin=origin,
                    admission_basis="condition_clause",
                )
            )

        if re.search(r"\b(therefore|thus|results in|leads to|means that|causes|collapse)\b", text_lower) and len(accepted["consequence_spans"]) < max_per_role:
            accepted["consequence_spans"].append(
                _make_evidence_item(
                    row=row,
                    assessment=assessment,
                    origin=origin,
                    admission_basis="consequence_clause",
                )
            )

        if foreign and overlap >= 1 and len(accepted["competitor_spans"]) < max_per_role:
            accepted["competitor_spans"].append(
                _make_evidence_item(
                    row=row,
                    assessment=assessment,
                    origin=origin,
                    admission_basis="competitor_check",
                )
            )

        admitted_ids = {
            as_text(item.get("overlay_candidate_id"))
            for role_items in accepted.values()
            for item in role_items
        }
        if as_text(row.get("overlay_candidate_id")) not in admitted_ids:
            discarded.append(
                {
                    "overlay_candidate_id": as_text(row.get("overlay_candidate_id")),
                    "discard_reason": "weak_alignment",
                }
            )

    return accepted, discarded


def _sibling_window_rows(
    *,
    bundle: Mapping[str, Any],
    sibling_anchor_index: Mapping[tuple[str, ...], Sequence[Mapping[str, Any]]],
    overlay_rows_by_doc: Mapping[str, Sequence[Mapping[str, Any]]],
    existing_ids: set[str],
    max_window_pages: int,
    max_anchors: int,
) -> list[dict[str, Any]]:
    parent_key = _parent_topic_key_from_bundle(bundle)
    anchors = list(sibling_anchor_index.get(parent_key, []))[:max_anchors]
    out: list[dict[str, Any]] = []
    seen = set(existing_ids)

    for anchor in anchors:
        doc_id = as_text(anchor.get("doc_id"))
        anchor_page = _page_index(anchor.get("page_index"))
        if not doc_id or anchor_page is None:
            continue
        for row in overlay_rows_by_doc.get(doc_id) or []:
            oid = as_text(row.get("overlay_candidate_id"))
            if not oid or oid in seen:
                continue
            row_page = _page_index(row.get("page_index"))
            if row_page is None or abs(row_page - anchor_page) > max_window_pages:
                continue
            out.append(dict(row))
            seen.add(oid)

    out.sort(key=lambda r: (-float(r.get("selection_score") or 0.0), as_text(r.get("overlay_candidate_id"))))
    return out


def _competitor_conflict(packet: Mapping[str, Sequence[Mapping[str, Any]]]) -> bool:
    competitor = max((float(item.get("selection_score") or 0.0) for item in packet.get("competitor_spans") or []), default=0.0)
    target = max((float(item.get("selection_score") or 0.0) for item in packet.get("definition_spans") or []), default=0.0)
    return competitor > target and competitor > 0.0


def _recoverability_class(
    *,
    bundle: Mapping[str, Any],
    packet: Mapping[str, Sequence[Mapping[str, Any]]],
    seed_shape: Mapping[str, bool],
    same_kc_rows: Sequence[Mapping[str, Any]],
) -> tuple[str, list[str], str, str]:
    reason_codes: list[str] = []
    target_witness = bool(packet.get("target_witness_spans"))
    definition_span = bool(packet.get("definition_spans"))
    formula_span = bool(packet.get("formula_spans"))
    condition_span = bool(packet.get("condition_spans"))
    consequence_span = bool(packet.get("consequence_spans"))
    competitor_conflict = _competitor_conflict(packet)

    if not target_witness:
        _append_unique(reason_codes, "missing_target_witness")
    if not definition_span:
        _append_unique(reason_codes, "missing_definition")
    if seed_shape.get("formula_required") and not formula_span:
        _append_unique(reason_codes, "missing_formula")
    if seed_shape.get("condition_required") and not condition_span:
        _append_unique(reason_codes, "missing_condition")
    if seed_shape.get("consequence_required") and not consequence_span:
        _append_unique(reason_codes, "missing_consequence")
    if competitor_conflict:
        _append_unique(reason_codes, "competitor_bleed")
    if not same_kc_rows:
        _append_unique(reason_codes, "genuine_sparsity")

    required_ok = (
        target_witness
        and definition_span
        and (not seed_shape.get("formula_required") or formula_span)
        and (not seed_shape.get("condition_required") or condition_span)
        and (not seed_shape.get("consequence_required") or consequence_span)
        and not competitor_conflict
    )
    if required_ok:
        return RECOVERABILITY_A_DIRECT, reason_codes, "draft_direct", ""

    missing_core = 0
    for code in reason_codes:
        if code in {"missing_target_witness", "missing_definition", "missing_formula", "missing_condition", "missing_consequence"}:
            missing_core += 1

    if target_witness and not competitor_conflict and missing_core <= 1 and same_kc_rows:
        return RECOVERABILITY_B_NORMALIZED, reason_codes, "draft_normalized", ""

    if "genuine_sparsity" in reason_codes:
        failure_family = "genuine_sparsity"
    elif "competitor_bleed" in reason_codes:
        failure_family = "competitor_bleed"
    elif "missing_target_witness" in reason_codes:
        failure_family = "missing_target_witness"
    elif "missing_definition" in reason_codes:
        failure_family = "missing_definition"
    elif "missing_formula" in reason_codes:
        failure_family = "missing_formula"
    elif "missing_condition" in reason_codes:
        failure_family = "missing_condition"
    elif "missing_consequence" in reason_codes:
        failure_family = "missing_consequence"
    else:
        failure_family = "genuine_sparsity"

    return RECOVERABILITY_C_NOT_RECOVERABLE, reason_codes, "hold_upstream", failure_family


def audit_single_fallback(
    *,
    bundle: Mapping[str, Any],
    triage_row: Mapping[str, Any],
    overlay_rows_by_kc: Mapping[str, Sequence[Mapping[str, Any]]],
    overlay_rows_by_doc: Mapping[str, Sequence[Mapping[str, Any]]],
    sibling_anchor_index: Mapping[tuple[str, ...], Sequence[Mapping[str, Any]]],
    max_window_pages: int,
    max_sibling_anchors_per_kc: int,
    max_packet_items_per_role: int,
) -> Step67CAuditResult:
    kc_id = as_text(bundle.get("kc_id"))
    same_kc_rows = [dict(item) for item in overlay_rows_by_kc.get(kc_id) or []]
    existing_ids = {as_text(row.get("overlay_candidate_id")) for row in same_kc_rows if as_text(row.get("overlay_candidate_id"))}

    sibling_rows = _sibling_window_rows(
        bundle=bundle,
        sibling_anchor_index=sibling_anchor_index,
        overlay_rows_by_doc=overlay_rows_by_doc,
        existing_ids=existing_ids,
        max_window_pages=max_window_pages,
        max_anchors=max_sibling_anchors_per_kc,
    )

    target_terms = _target_terms(bundle)
    target_phrases = _target_phrases(bundle)

    same_packet, same_discarded = _assign_roles(
        bundle=bundle,
        rows=same_kc_rows,
        origin="same_kc_local",
        target_terms=target_terms,
        target_phrases=target_phrases,
        max_per_role=max_packet_items_per_role,
    )
    sibling_packet, sibling_discarded = _assign_roles(
        bundle=bundle,
        rows=sibling_rows,
        origin="sibling_window",
        target_terms=target_terms,
        target_phrases=target_phrases,
        max_per_role=max_packet_items_per_role,
    )

    packet: dict[str, list[dict[str, Any]]] = {}
    for key in same_packet.keys():
        merged = list(same_packet.get(key, []))
        merged_ids = {as_text(item.get("overlay_candidate_id")) for item in merged}
        for item in sibling_packet.get(key, []):
            if len(merged) >= max_packet_items_per_role:
                break
            if as_text(item.get("overlay_candidate_id")) not in merged_ids:
                merged.append(item)
                merged_ids.add(as_text(item.get("overlay_candidate_id")))
        packet[key] = merged

    seed_shape = _seed_shape(bundle)
    recoverability_class, reason_codes, recommended_next_action, failure_family = _recoverability_class(
        bundle=bundle,
        packet=packet,
        seed_shape=seed_shape,
        same_kc_rows=same_kc_rows,
    )

    row = {
        "kc_id": kc_id,
        "canonical_name": as_text(bundle.get("canonical_name")),
        "aliases": _normalize_string_list(bundle.get("aliases")),
        "seed_definition": as_text(bundle.get("seed_definition")),
        "topic_path_ids": _normalize_string_list(bundle.get("topic_path_ids")),
        "topic_path_labels": _normalize_string_list(bundle.get("topic_path_labels")),
        "baseline_step6_7_status": as_text(((bundle.get("seed_floor_triage") or {}).get("original_step6_7_raw") or {}).get("authoritative_definition_status")),
        "baseline_step6_7b_status": as_text(bundle.get("authoritative_definition_status")),
        "baseline_step6_7b_outcome": as_text(triage_row.get("bounded_model_rescue_outcome") or triage_row.get("deterministic_rescue_outcome")),
        "seed_shape": seed_shape,
        "role_coverage": {
            "target_witness": bool(packet.get("target_witness_spans")),
            "definition_span": bool(packet.get("definition_spans")),
            "formula_span": bool(packet.get("formula_spans")),
            "condition_span": bool(packet.get("condition_spans")),
            "consequence_span": bool(packet.get("consequence_spans")),
            "competitor_span": bool(packet.get("competitor_spans")),
        },
        "recoverability_class": recoverability_class,
        "recoverability_reason_codes": reason_codes,
        "recommended_next_action": recommended_next_action,
        "packet_counts": {
            "same_kc_rows": len(same_kc_rows),
            "sibling_anchor_pages": len(sibling_anchor_index.get(_parent_topic_key_from_bundle(bundle), [])[:max_sibling_anchors_per_kc]),
            "candidate_rows_examined": len(same_kc_rows) + len(sibling_rows),
            "accepted_packet_items": sum(len(v) for v in packet.values()),
        },
        "packet_quality": {
            "foreign_kc_admitted_count": sum(
                1
                for role_items in packet.values()
                for item in role_items
                if as_text(item.get("kc_id")) and as_text(item.get("kc_id")) != kc_id
            ),
            "explicit_target_witness_count": len(packet.get("target_witness_spans") or []),
            "competitor_conflict": _competitor_conflict(packet),
        },
    }

    packet_row = None
    failure_row = None
    if recoverability_class in {RECOVERABILITY_A_DIRECT, RECOVERABILITY_B_NORMALIZED}:
        packet_row = {
            "kc_id": kc_id,
            "recoverability_class": recoverability_class,
            **packet,
            "discarded_candidates": same_discarded + sibling_discarded,
        }
    else:
        failure_row = {
            "kc_id": kc_id,
            "failure_family": failure_family,
            "details": reason_codes,
        }

    return Step67CAuditResult(row=row, packet=packet_row, failure=failure_row)


def emit_step67c_recoverability_audit(
    *,
    config_path: Path,
) -> Step67CEmissionResult:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    baseline_manifest_path = Path(config["inputs"]["step6_7b_set_manifest"])
    baseline_manifest = _load_json(baseline_manifest_path)

    bundles_path = Path(baseline_manifest["artifacts"]["kc_draft_bundles_rescued_jsonl"])
    triage_rows_path = Path(baseline_manifest["artifacts"]["triage_rows_jsonl"])
    step67_bundles_path = Path(baseline_manifest["upstream"]["kc_draft_bundles_jsonl"])
    overlay_rows_path = Path(baseline_manifest["upstream"]["candidate_sentence_overlay_jsonl"])

    processed_root = Path(config["outputs"]["processed_root"])
    sets_root = Path(config["outputs"]["sets_root"])
    runs_root = Path(config["outputs"]["runs_root"])
    processed_root.mkdir(parents=True, exist_ok=True)
    sets_root.mkdir(parents=True, exist_ok=True)
    runs_root.mkdir(parents=True, exist_ok=True)

    run_id = _utc_run_id()
    processed_dir = processed_root / run_id
    run_dir = runs_root / f"{run_id}_step6_7c"
    processed_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    bundles = _load_jsonl(bundles_path)
    triage_rows = _load_jsonl(triage_rows_path)
    step67_bundles = _load_jsonl(step67_bundles_path)
    overlay_rows = _load_jsonl(overlay_rows_path)

    triage_by_kc = {as_text(row.get("kc_id")): row for row in triage_rows}
    fallback_kc_ids = [
        as_text(row.get("kc_id"))
        for row in triage_rows
        if as_text(row.get("final_status")) == AUTHORITATIVE_DEFINITION_STATUS_SEED_FLOOR_FALLBACK
    ]
    bundles_by_kc = {as_text(row.get("kc_id")): row for row in bundles}

    overlay_rows_by_kc: dict[str, list[Mapping[str, Any]]] = {}
    overlay_rows_by_doc: dict[str, list[Mapping[str, Any]]] = {}
    for row in overlay_rows:
        kc_id = as_text(row.get("kc_id"))
        doc_id = as_text(row.get("doc_id"))
        if kc_id:
            overlay_rows_by_kc.setdefault(kc_id, []).append(row)
        if doc_id:
            overlay_rows_by_doc.setdefault(doc_id, []).append(row)

    sibling_anchor_index = _build_sibling_success_anchor_index(draft_rows=step67_bundles)

    audit_cfg = dict(config.get("audit") or {})
    max_window_pages = int(audit_cfg.get("sibling_page_window", 2))
    max_sibling_anchors_per_kc = int(audit_cfg.get("max_sibling_anchors_per_kc", 16))
    max_packet_items_per_role = int(audit_cfg.get("max_packet_items_per_role", 3))

    rows_out: list[dict[str, Any]] = []
    packets_out: list[dict[str, Any]] = []
    failures_out: list[dict[str, Any]] = []

    class_counts: Counter[str] = Counter()
    failure_counts: Counter[str] = Counter()

    for kc_id in fallback_kc_ids:
        bundle = bundles_by_kc.get(kc_id)
        triage_row = triage_by_kc.get(kc_id)
        if bundle is None or triage_row is None:
            continue

        result = audit_single_fallback(
            bundle=bundle,
            triage_row=triage_row,
            overlay_rows_by_kc=overlay_rows_by_kc,
            overlay_rows_by_doc=overlay_rows_by_doc,
            sibling_anchor_index=sibling_anchor_index,
            max_window_pages=max_window_pages,
            max_sibling_anchors_per_kc=max_sibling_anchors_per_kc,
            max_packet_items_per_role=max_packet_items_per_role,
        )
        rows_out.append(result.row)
        class_counts[as_text(result.row.get("recoverability_class"))] += 1

        if result.packet is not None:
            packets_out.append(result.packet)
        if result.failure is not None:
            failures_out.append(result.failure)
            failure_counts[as_text(result.failure.get("failure_family"))] += 1

    rows_path = processed_dir / "recoverability_rows.jsonl"
    packets_path = processed_dir / "recoverability_packets.jsonl"
    failures_path = processed_dir / "recoverability_failures.jsonl"
    stats_path = processed_dir / "recoverability_stats.json"

    write_jsonl(rows_path, rows_out)
    write_jsonl(packets_path, packets_out)
    write_jsonl(failures_path, failures_out)

    stats = {
        "schema_version": "1.0",
        "stage": STEP67C_STAGE_NAME,
        "contract_version": STEP67C_CONTRACT_VERSION,
        "input_fallback_count": len(fallback_kc_ids),
        "recoverability_class_counts": {
            RECOVERABILITY_A_DIRECT: class_counts[RECOVERABILITY_A_DIRECT],
            RECOVERABILITY_B_NORMALIZED: class_counts[RECOVERABILITY_B_NORMALIZED],
            RECOVERABILITY_C_NOT_RECOVERABLE: class_counts[RECOVERABILITY_C_NOT_RECOVERABLE],
        },
        "failure_family_counts": {family: failure_counts[family] for family in FAILURE_FAMILIES},
        "packet_quality_summary": {
            "rows_with_explicit_target_witness": sum(
                1
                for row in rows_out
                if int(((row.get("packet_quality") or {}).get("explicit_target_witness_count") or 0)) > 0
            ),
            "rows_with_formula_support": sum(
                1
                for row in rows_out
                if bool(((row.get("role_coverage") or {}).get("formula_span")))
            ),
            "rows_with_competitor_conflict": sum(
                1
                for row in rows_out
                if bool(((row.get("packet_quality") or {}).get("competitor_conflict")))
            ),
            "foreign_kc_rows_admitted": sum(
                int(((row.get("packet_quality") or {}).get("foreign_kc_admitted_count") or 0))
                for row in rows_out
            ),
        },
    }
    write_json(stats_path, stats)

    config_snapshot = run_dir / "config_snapshot.yaml"
    input_manifest = run_dir / "input_manifest.json"
    output_manifest = run_dir / "output_manifest.json"
    summary_path = run_dir / "summary.json"

    config_snapshot.write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")
    write_json(
        input_manifest,
        {
            "step6_7b_set_manifest": baseline_manifest_path.as_posix(),
            "baseline_bundles_jsonl": bundles_path.as_posix(),
            "baseline_triage_rows_jsonl": triage_rows_path.as_posix(),
            "upstream_step6_7_bundles_jsonl": step67_bundles_path.as_posix(),
            "upstream_overlay_jsonl": overlay_rows_path.as_posix(),
            "input_fallback_kc_ids": fallback_kc_ids,
        },
    )
    write_json(
        output_manifest,
        {
            "recoverability_rows_jsonl": rows_path.as_posix(),
            "recoverability_packets_jsonl": packets_path.as_posix(),
            "recoverability_failures_jsonl": failures_path.as_posix(),
            "recoverability_stats_json": stats_path.as_posix(),
        },
    )
    write_json(
        summary_path,
        {
            "run_id": run_id,
            "processed_dir": processed_dir.as_posix(),
            "audit_dir": run_dir.as_posix(),
            **stats,
        },
    )

    set_manifest_path = sets_root / f"{run_id}_step6_7c_seed_floor_recoverability_audit_set.json"
    write_json(
        set_manifest_path,
        {
            "schema_version": "1.0",
            "kind": "step6_7c_seed_floor_recoverability_audit_set",
            "set_id": f"{run_id}_step6_7c_seed_floor_recoverability_audit_set",
            "created_utc": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            "run_id_step6_7c": run_id,
            "artifacts": {
                "recoverability_rows_jsonl": rows_path.as_posix(),
                "recoverability_packets_jsonl": packets_path.as_posix(),
                "recoverability_failures_jsonl": failures_path.as_posix(),
                "recoverability_stats_json": stats_path.as_posix(),
            },
            "audit": {
                "run_dir": run_dir.as_posix(),
                "config_snapshot": config_snapshot.as_posix(),
                "input_manifest": input_manifest.as_posix(),
                "output_manifest": output_manifest.as_posix(),
                "summary": summary_path.as_posix(),
            },
            "upstream": {
                "step6_7b_set_manifest": baseline_manifest_path.as_posix(),
                "kc_draft_bundles_rescued_jsonl": bundles_path.as_posix(),
                "triage_rows_jsonl": triage_rows_path.as_posix(),
                "kc_draft_bundles_jsonl": step67_bundles_path.as_posix(),
                "candidate_sentence_overlay_jsonl": overlay_rows_path.as_posix(),
            },
            "step6_7c_runtime": {
                "config_path": config_path.as_posix(),
                "contract_version": STEP67C_CONTRACT_VERSION,
                "sibling_page_window": max_window_pages,
                "max_sibling_anchors_per_kc": max_sibling_anchors_per_kc,
                "max_packet_items_per_role": max_packet_items_per_role,
            },
        },
    )

    return Step67CEmissionResult(
        run_id=run_id,
        processed_dir=processed_dir,
        run_dir=run_dir,
        recoverability_rows_path=rows_path,
        recoverability_packets_path=packets_path,
        recoverability_failures_path=failures_path,
        recoverability_stats_path=stats_path,
        set_manifest_path=set_manifest_path,
        stats=stats,
    )
