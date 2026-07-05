from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from kc_l.retrieval_gate.provenance_normalize import normalize_candidate_provenance
from kc_l.retrieval_gate.role_scoring import analyze_quote_role
from kc_l.retrieval_gate.semantic import (
    build_name_context_terms,
    build_query_text,
    exact_phrase_hits,
    match_normalize,
    unique_preserve_order,
)
from kc_l.retrieval_gate.text_normalize import verify_quote_in_raw_source
from kc_l.utils.json_io import read_jsonl


OVERLAY_CONTRACT_VERSION = "1.0"
SOURCE_STEP_KIND = "step5_3_kc_evidence_recalibrated"


def attach_hierarchy_context_to_registry_rows(
    registry_rows: Sequence[Mapping[str, Any]],
    hierarchy_context_by_kc: Mapping[str, Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    attached_rows: List[Dict[str, Any]] = []
    for row in registry_rows:
        merged = dict(row)
        context = dict(hierarchy_context_by_kc.get(str(row.get("kc_id") or "")) or {})
        if context:
            merged.update(context)
        attached_rows.append(merged)
    return attached_rows


def select_kc_subset(
    registry_rows: Sequence[Mapping[str, Any]],
    limit_kcs: Optional[int],
    *,
    exact_kc_ids: Optional[Sequence[str]] = None,
) -> List[Mapping[str, Any]]:
    ordered = sorted(registry_rows, key=lambda row: str(row.get("kc_id") or ""))
    if exact_kc_ids:
        by_id = {str(row.get("kc_id") or ""): row for row in ordered}
        missing = [str(kc_id) for kc_id in exact_kc_ids if str(kc_id) not in by_id]
        if missing:
            raise RuntimeError(f"Configured exact_kc_ids contains unknown kc_id values: {missing}")
        chosen = [by_id[str(kc_id)] for kc_id in exact_kc_ids]
        if limit_kcs is not None and len(chosen) != int(limit_kcs):
            raise RuntimeError(
                f"Configured exact_kc_ids length {len(chosen)} does not match limit_kcs {int(limit_kcs)}"
            )
        return chosen if limit_kcs is None else chosen[: int(limit_kcs)]
    if limit_kcs is None:
        return list(ordered)
    return list(ordered[: int(limit_kcs)])


def load_source_corpus(step4_set_obj: Mapping[str, Any], repo_root: Path) -> Dict[str, Any]:
    source_lookup: Dict[str, Dict[str, Any]] = {}
    doc_blocks: Dict[str, List[Dict[str, Any]]] = {}
    corpus_paths: List[Path] = []
    docs_obj = step4_set_obj.get("docs")
    if not isinstance(docs_obj, Mapping):
        raise RuntimeError("Step 4 set manifest is missing docs")
    for doc_key in sorted(docs_obj.keys()):
        info = docs_obj[doc_key]
        if not isinstance(info, Mapping):
            continue
        artifacts = info.get("artifacts")
        if not isinstance(artifacts, Mapping):
            continue
        corpus_meta = artifacts.get("block_text_corpus.jsonl")
        if not isinstance(corpus_meta, Mapping):
            continue
        raw_path = corpus_meta.get("path")
        if not raw_path:
            continue
        corpus_path = (repo_root / str(raw_path)).resolve()
        corpus_paths.append(corpus_path)
        rows = list(read_jsonl(corpus_path))
        if not rows:
            continue
        doc_id = str(rows[0].get("doc_id") or doc_key)
        doc_blocks[doc_id] = rows
        for row in rows:
            block_id = str(row.get("block_id") or "")
            if block_id:
                source_lookup[block_id] = dict(row)
    return {"source_lookup": source_lookup, "doc_blocks": doc_blocks, "corpus_paths": corpus_paths}


def build_review_queue_lookup(review_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}
    for row in review_rows:
        kc_id = str(row.get("kc_id") or "")
        if not kc_id:
            continue
        lookup[kc_id] = dict(row)
    return lookup


def build_overlay_candidate_id(kc_id: str, evidence_item: Mapping[str, Any], source_candidate_index: int) -> str:
    payload = {
        "kc_id": str(kc_id),
        "source_candidate_index": int(source_candidate_index),
        "evidence_item": evidence_item,
    }
    digest = hashlib.sha1(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return f"{kc_id}:overlay:{digest}"


def _safe_int(value: Any, default: int = -1) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _quote_match_norm(text: str) -> str:
    return match_normalize(str(text or ""))


def _candidate_view_from_evidence(evidence_item: Mapping[str, Any]) -> SimpleNamespace:
    snippet = str(evidence_item.get("snippet") or "")
    source_block_text = str(evidence_item.get("source_block_text") or "")
    return SimpleNamespace(
        doc_id=str(evidence_item.get("doc_id") or ""),
        block_id=str(evidence_item.get("block_id") or ""),
        page_index=_safe_int(evidence_item.get("page_index"), default=-1),
        layer=str(evidence_item.get("layer") or ""),
        bbox=evidence_item.get("bbox"),
        sentence_id=str(evidence_item.get("sentence_id") or ""),
        sent_idx=_safe_int(evidence_item.get("sent_idx"), default=-1),
        char_start=_safe_int(evidence_item.get("char_start"), default=-1),
        char_end=_safe_int(evidence_item.get("char_end"), default=-1),
        reveal_group_id=evidence_item.get("reveal_group_id"),
        reveal_canonical_page_index=evidence_item.get("reveal_canonical_page_index"),
        patch_id=str(evidence_item.get("patch_id") or ""),
        patch_heading=str(evidence_item.get("patch_heading") or ""),
        patch_type=str(evidence_item.get("patch_type") or ""),
        patch_span_source=str(evidence_item.get("patch_span_source") or ""),
        page_heading_norm=str(evidence_item.get("page_heading_norm") or evidence_item.get("patch_heading") or ""),
        text_source=str(evidence_item.get("text_source") or ""),
        source_text=source_block_text,
        text_raw=source_block_text,
        source_block_text=source_block_text,
        source_block_text_raw=source_block_text,
        quote=snippet,
        quote_raw=snippet,
        quote_match_norm=_quote_match_norm(snippet),
    )


def _provenance_quality_flags(
    *,
    provenance_status: str,
    provenance_reason: str,
    quote_rebound: bool,
) -> List[str]:
    flags: List[str] = []
    if provenance_status == "original":
        flags.append("ProvenanceSource:page_index_valid")
    elif provenance_status == "recovered":
        flags.extend(["PageIndexRecovered", f"ProvenanceSource:{provenance_reason}"])
    elif provenance_status == "substituted":
        flags.extend(["PageIndexSubstituted", f"ProvenanceSource:{provenance_reason}"])
    elif provenance_status == "dropped":
        flags.extend(["PageIndexDropped", f"ProvenanceSource:{provenance_reason}"])
    if quote_rebound:
        flags.append("QuoteRebound")
    return unique_preserve_order([flag for flag in flags if str(flag).strip()])


def _quote_verification_status(
    *,
    provenance_status: str,
    quote_verified: bool,
    original_quote_verified: bool,
    quote_rebound: bool,
) -> str:
    if quote_verified:
        parts = ["verified", provenance_status or "unknown"]
        if quote_rebound:
            parts.append("rebound")
        return "_".join(parts)
    if original_quote_verified:
        return "verified_original_only"
    return "unverified"


def _bool_flag(flags: Mapping[str, Any], name: str) -> bool:
    return bool(flags.get(name, False))


def _review_queue_aux(review_row: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    row = dict(review_row or {})
    return {
        "in_review_queue": bool(row),
        "reasons": [str(item) for item in row.get("reasons") or []],
        "selected_candidate_count": _safe_int(row.get("selected_candidate_count"), default=0),
        "strong_same_topic_count": _safe_int(row.get("strong_same_topic_count"), default=0),
        "structured_candidate_count": _safe_int(row.get("structured_candidate_count"), default=0),
    }


def _record_from_evidence(
    *,
    kc_row: Mapping[str, Any],
    step5_row: Mapping[str, Any],
    evidence_item: Mapping[str, Any],
    source_candidate_index: int,
    review_queue_row: Optional[Mapping[str, Any]],
    provenance_index: Mapping[str, Any],
    source_set_id: str,
    source_run_id: str,
    layer_preference: Sequence[str],
    role_hints_enabled: bool,
) -> Dict[str, Any]:
    canonical_name = str(kc_row.get("canonical_name") or step5_row.get("canonical_name") or "")
    aliases = [str(item) for item in kc_row.get("aliases") or step5_row.get("aliases") or []]
    hierarchy_context = [
        str(item)
        for item in kc_row.get("source_hierarchy_path") or kc_row.get("kc_path") or []
        if str(item).strip()
    ]
    query_text = build_query_text(canonical_name, aliases, hierarchy_context[:-1])
    name_terms = build_name_context_terms(canonical_name, aliases, hierarchy_context[:-1])
    original_quote_surface = str(evidence_item.get("snippet") or "")
    original_source_block_text = str(evidence_item.get("source_block_text") or "")
    original_quote_verified = verify_quote_in_raw_source(original_quote_surface, original_source_block_text)

    candidate_view = _candidate_view_from_evidence(evidence_item)
    provenance_result = normalize_candidate_provenance(
        candidate_view,
        provenance_index,
        layer_order=[str(item) for item in layer_preference],
    )
    updates = dict(provenance_result.get("updates") or {})
    provenance_status = str(provenance_result.get("status") or "")
    provenance_reason = str(provenance_result.get("reason") or "")

    current_doc_id = str(updates.get("doc_id") or candidate_view.doc_id)
    current_block_id = str(updates.get("block_id") or candidate_view.block_id)
    current_page_index = _safe_int(updates.get("page_index"), default=_safe_int(candidate_view.page_index, default=-1))
    current_layer = str(updates.get("layer") or candidate_view.layer)
    current_bbox = updates.get("bbox", candidate_view.bbox)
    current_sentence_id = str(updates.get("sentence_id") or candidate_view.sentence_id)
    current_sent_idx = _safe_int(updates.get("sent_idx"), default=_safe_int(candidate_view.sent_idx, default=-1))
    current_char_start = _safe_int(updates.get("char_start"), default=_safe_int(candidate_view.char_start, default=-1))
    current_char_end = _safe_int(updates.get("char_end"), default=_safe_int(candidate_view.char_end, default=-1))
    current_reveal_group_id = updates.get("reveal_group_id", candidate_view.reveal_group_id)
    current_reveal_canonical_page_index = updates.get(
        "reveal_canonical_page_index",
        candidate_view.reveal_canonical_page_index,
    )
    current_patch_id = str(updates.get("patch_id") or candidate_view.patch_id)
    current_patch_heading = str(updates.get("patch_heading") or candidate_view.patch_heading)
    current_patch_type = str(updates.get("patch_type") or candidate_view.patch_type)
    current_patch_span_source = str(updates.get("patch_span_source") or candidate_view.patch_span_source)
    current_page_heading_norm = str(updates.get("page_heading_norm") or candidate_view.page_heading_norm)
    current_text_source = str(updates.get("text_source") or candidate_view.text_source)
    current_quote_surface = str(updates.get("quote") or candidate_view.quote_raw)
    current_source_block_text = str(updates.get("source_block_text") or candidate_view.source_block_text_raw)
    quote_verified = bool(
        updates.get("quote_verified", False)
        or verify_quote_in_raw_source(current_quote_surface, current_source_block_text)
    )
    quote_rebound = bool(updates.get("quote_rebound", False))
    quote_rebind_reason = str(updates.get("quote_rebind_reason") or "")
    quote_match_norm = str(updates.get("quote_match_norm") or _quote_match_norm(current_quote_surface))

    alignment_breakdown = dict(evidence_item.get("alignment_breakdown") or {})
    alignment_breakdown.pop("seed_keyword_hits", None)
    sentence_flags = dict(alignment_breakdown.get("flags") or {})
    support_profile = dict(evidence_item.get("support_profile") or alignment_breakdown.get("support_profile") or {})
    exact_name_phrase, exact_alias_phrase = exact_phrase_hits(
        quote_match_norm,
        str(name_terms.get("canonical_norm") or ""),
        list(name_terms.get("alias_norms") or []),
    )
    role_hint = {
        "role_hint_source": "disabled",
        "top_role": "",
        "top_score": 0.0,
        "second_role": "",
        "second_score": 0.0,
        "dominant": False,
        "ambiguous": False,
        "ambiguity_reason": "",
        "strong_definition_or_equation": False,
        "safe_role_hint": "",
    }
    if role_hints_enabled:
        role_proxy = SimpleNamespace(
            exact_name_phrase=exact_name_phrase,
            exact_alias_phrase=exact_alias_phrase,
            sentence_flags=sentence_flags,
        )
        role_analysis = analyze_quote_role(
            quote=current_quote_surface,
            canonical_name=canonical_name,
            aliases=aliases,
            candidate=role_proxy,
        )
        safe_role_hint = ""
        if bool(role_analysis.get("dominant")):
            safe_role_hint = str(role_analysis.get("top_role") or "")
        role_hint = {
            "role_hint_source": "heuristic",
            "top_role": str(role_analysis.get("top_role") or ""),
            "top_score": float(role_analysis.get("top_score") or 0.0),
            "second_role": str(role_analysis.get("second_role") or ""),
            "second_score": float(role_analysis.get("second_score") or 0.0),
            "dominant": bool(role_analysis.get("dominant", False)),
            "ambiguous": bool(role_analysis.get("ambiguous", False)),
            "ambiguity_reason": str(role_analysis.get("ambiguity_reason") or ""),
            "strong_definition_or_equation": bool(role_analysis.get("strong_definition_or_equation", False)),
            "safe_role_hint": safe_role_hint,
        }

    return {
        "overlay_contract_version": OVERLAY_CONTRACT_VERSION,
        "overlay_candidate_id": build_overlay_candidate_id(
            str(kc_row.get("kc_id") or ""),
            evidence_item,
            source_candidate_index,
        ),
        "source_candidate_index": int(source_candidate_index),
        "source_set_id": source_set_id,
        "source_run_id": source_run_id,
        "source_step_kind": SOURCE_STEP_KIND,
        "kc_id": str(kc_row.get("kc_id") or ""),
        "canonical_name": canonical_name,
        "aliases": aliases,
        "query_text": query_text,
        "query_used": query_text,
        "ancestor_hier_node_ids": [str(item) for item in kc_row.get("ancestor_hier_node_ids") or []],
        "ancestor_labels": [str(item) for item in kc_row.get("ancestor_labels") or []],
        "leaf_hier_node_id": str(kc_row.get("leaf_hier_node_id") or ""),
        "parent_hier_node_id": str(kc_row.get("parent_hier_node_id") or ""),
        "source_hierarchy_path": [str(item) for item in kc_row.get("source_hierarchy_path") or kc_row.get("kc_path") or []],
        "step5_3_review_queue_aux": _review_queue_aux(review_queue_row),
        "step5_3_support_pack_summary": dict(step5_row.get("support_pack_summary") or {}),
        "doc_id": current_doc_id,
        "block_id": current_block_id,
        "page_index": int(current_page_index),
        "bbox": current_bbox,
        "layer": current_layer,
        "sentence_id": current_sentence_id,
        "sent_idx": int(current_sent_idx),
        "char_start": int(current_char_start),
        "char_end": int(current_char_end),
        "reveal_group_id": current_reveal_group_id,
        "reveal_canonical_page_index": current_reveal_canonical_page_index,
        "patch_id": current_patch_id,
        "patch_heading": current_patch_heading,
        "patch_type": current_patch_type,
        "patch_span_source": current_patch_span_source,
        "page_heading_norm": current_page_heading_norm,
        "text_source": current_text_source,
        "original_doc_id": candidate_view.doc_id,
        "original_block_id": candidate_view.block_id,
        "original_page_index": int(candidate_view.page_index),
        "original_bbox": candidate_view.bbox,
        "original_layer": candidate_view.layer,
        "original_sentence_id": candidate_view.sentence_id,
        "original_sent_idx": int(candidate_view.sent_idx),
        "original_char_start": int(candidate_view.char_start),
        "original_char_end": int(candidate_view.char_end),
        "original_reveal_group_id": candidate_view.reveal_group_id,
        "original_reveal_canonical_page_index": candidate_view.reveal_canonical_page_index,
        "original_patch_id": candidate_view.patch_id,
        "original_patch_heading": candidate_view.patch_heading,
        "original_patch_type": candidate_view.patch_type,
        "original_patch_span_source": candidate_view.patch_span_source,
        "original_page_heading_norm": candidate_view.page_heading_norm,
        "original_text_source": candidate_view.text_source,
        "quote_surface": current_quote_surface,
        "original_quote_surface": original_quote_surface,
        "quote_match_norm": quote_match_norm,
        "quote_verification_status": _quote_verification_status(
            provenance_status=provenance_status,
            quote_verified=quote_verified,
            original_quote_verified=original_quote_verified,
            quote_rebound=quote_rebound,
        ),
        "quote_verified": quote_verified,
        "quote_rebound": quote_rebound,
        "quote_rebind_reason": quote_rebind_reason,
        "source_block_text": current_source_block_text,
        "source_block_text_raw": current_source_block_text,
        "original_source_block_text": original_source_block_text,
        "retrieval_scores": dict(evidence_item.get("retrieval_scores") or {}),
        "alignment_score": float(evidence_item.get("alignment_score") or 0.0),
        "alignment_breakdown": alignment_breakdown,
        "is_heading_like": _bool_flag(sentence_flags, "is_heading_like"),
        "is_formula_like": _bool_flag(sentence_flags, "is_formula_like"),
        "is_definition_like": _bool_flag(sentence_flags, "is_definition_like"),
        "is_procedure_like": _bool_flag(sentence_flags, "is_procedure_like"),
        "sentence_flags": sentence_flags,
        "support_profile": support_profile,
        "contamination_risk": str(alignment_breakdown.get("contamination_risk") or ""),
        "contamination_signals": [str(item) for item in alignment_breakdown.get("contamination_signals") or []],
        "strong_same_topic": bool(alignment_breakdown.get("strong_same_topic", False)),
        "strong_structured_candidate": bool(alignment_breakdown.get("strong_structured_candidate", False)),
        "doc_mismatch": bool(alignment_breakdown.get("doc_mismatch", False)),
        "provenance_normalization_status": provenance_status,
        "provenance_normalization_reason": provenance_reason,
        "provenance_normalization_note": str(updates.get("provenance_note") or ""),
        "provenance_quality_flags": _provenance_quality_flags(
            provenance_status=provenance_status,
            provenance_reason=provenance_reason,
            quote_rebound=quote_rebound,
        ),
        "role_hint": role_hint,
    }


def build_overlay_records(
    *,
    kc_rows: Sequence[Mapping[str, Any]],
    step5_rows_by_kc: Mapping[str, Mapping[str, Any]],
    review_queue_by_kc: Mapping[str, Mapping[str, Any]],
    provenance_index: Mapping[str, Any],
    source_set_id: str,
    source_run_id: str,
    layer_preference: Sequence[str],
    role_hints_enabled: bool = True,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    provenance_counter: Dict[str, int] = {}
    quote_verification_counter: Dict[str, int] = {}
    role_counter: Dict[str, int] = {}
    safe_role_counter: Dict[str, int] = {}
    records_by_kc: Dict[str, int] = {}

    for kc_row in kc_rows:
        kc_id = str(kc_row.get("kc_id") or "")
        step5_row = step5_rows_by_kc.get(kc_id)
        if step5_row is None:
            raise RuntimeError(f"Selected kc_id missing from Step 5.3 candidates: {kc_id}")
        evidence_rows = list(step5_row.get("evidence") or [])
        review_queue_row = review_queue_by_kc.get(kc_id)
        records_by_kc[kc_id] = len(evidence_rows)
        for idx, evidence_item in enumerate(evidence_rows):
            if not isinstance(evidence_item, Mapping):
                continue
            record = _record_from_evidence(
                kc_row=kc_row,
                step5_row=step5_row,
                evidence_item=evidence_item,
                source_candidate_index=idx,
                review_queue_row=review_queue_row,
                provenance_index=provenance_index,
                source_set_id=source_set_id,
                source_run_id=source_run_id,
                layer_preference=layer_preference,
                role_hints_enabled=role_hints_enabled,
            )
            records.append(record)
            provenance_status = str(record.get("provenance_normalization_status") or "")
            provenance_counter[provenance_status] = provenance_counter.get(provenance_status, 0) + 1
            quote_status = str(record.get("quote_verification_status") or "")
            quote_verification_counter[quote_status] = quote_verification_counter.get(quote_status, 0) + 1
            top_role = str(((record.get("role_hint") or {}).get("top_role")) or "")
            role_counter[top_role] = role_counter.get(top_role, 0) + 1
            safe_role = str(((record.get("role_hint") or {}).get("safe_role_hint")) or "")
            safe_role_counter[safe_role] = safe_role_counter.get(safe_role, 0) + 1

    stats = {
        "overlay_contract_version": OVERLAY_CONTRACT_VERSION,
        "source_step_kind": SOURCE_STEP_KIND,
        "total_kcs": len(kc_rows),
        "total_overlay_records": len(records),
        "records_by_kc": dict(sorted(records_by_kc.items())),
        "provenance_normalization_breakdown": dict(sorted(provenance_counter.items())),
        "quote_verification_breakdown": dict(sorted(quote_verification_counter.items())),
        "role_hint_top_role_breakdown": dict(sorted(role_counter.items())),
        "safe_role_hint_breakdown": dict(sorted(safe_role_counter.items())),
        "step5_3_review_queue_hit_count": sum(
            1 for kc_row in kc_rows if str(kc_row.get("kc_id") or "") in review_queue_by_kc
        ),
    }
    return records, stats
