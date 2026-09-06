from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence

from .text_normalize import build_text_views, match_normalize, normalize_ws, rebind_quote_to_raw_source, verify_quote_in_raw_source


def safe_int(value: Any, default: int = -1) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def has_valid_page_index(value: Any) -> bool:
    return safe_int(value, default=-1) >= 0


def _layer_rank(layer: str, layer_order: Sequence[str]) -> int:
    try:
        return list(layer_order).index(str(layer or ""))
    except ValueError:
        return len(list(layer_order)) + 1


def _candidate_value(candidate: Any, field_name: str, default: Any = "") -> Any:
    return getattr(candidate, field_name, default)


def build_sentence_provenance_index(
    sentence_rows: Iterable[Mapping[str, Any]],
    source_lookup: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    by_block: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    by_doc_quote: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    by_doc_quote_norm: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    valid_block_rows_by_doc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in sentence_rows:
        doc_id = str(row.get("doc_id") or "")
        block_id = str(row.get("block_id") or "")
        quote_raw = str(row.get("sentence_text") or "")
        quote_views = build_text_views(quote_raw)
        source_block_text_raw = str(row.get("source_block_text") or "")
        source_block_views = build_text_views(source_block_text_raw)
        prepared = {
            "doc_id": doc_id,
            "block_id": block_id,
            "quote": quote_raw,
            "quote_raw": quote_raw,
            "quote_norm": quote_views["match_norm"],
            "quote_match_norm": quote_views["match_norm"],
            "sentence_id": str(row.get("sentence_id") or ""),
            "sent_idx": safe_int(row.get("sent_idx"), default=-1),
            "char_start": safe_int(row.get("char_start"), default=-1),
            "char_end": safe_int(row.get("char_end"), default=-1),
            "page_index": safe_int(row.get("page_index"), default=-1),
            "layer": str(row.get("layer") or ""),
            "bbox": row.get("bbox"),
            "reveal_group_id": row.get("reveal_group_id"),
            "reveal_canonical_page_index": row.get("reveal_canonical_page_index"),
            "patch_id": str(row.get("patch_id") or ""),
            "patch_heading": str(row.get("patch_heading") or ""),
            "patch_type": str(row.get("patch_type") or ""),
            "patch_span_source": str(row.get("patch_span_source") or ""),
            "page_heading_norm": str(row.get("page_heading_norm") or ""),
            "text_source": str(row.get("text_source") or ""),
            "source_block_text": source_block_text_raw,
            "source_block_text_raw": source_block_text_raw,
            "source_block_text_match_norm": source_block_views["match_norm"],
        }
        by_block[block_id].append(prepared)
        if quote_raw:
            by_doc_quote[doc_id][quote_raw].append(prepared)
            by_doc_quote_norm[doc_id][prepared["quote_norm"]].append(prepared)
    for row in source_lookup.values():
        if not has_valid_page_index(row.get("page_index")):
            continue
        doc_id = str(row.get("doc_id") or "")
        text_raw = str(row.get("text") or "")
        text_views = build_text_views(text_raw)
        valid_block_rows_by_doc[doc_id].append(
            {
                "doc_id": doc_id,
                "block_id": str(row.get("block_id") or ""),
                "page_index": safe_int(row.get("page_index"), default=-1),
                "layer": str(row.get("layer") or ""),
                "bbox": row.get("bbox"),
                "page_heading_norm": str(row.get("page_heading_norm") or ""),
                "text": text_raw,
                "text_raw": text_raw,
                "text_match_norm": text_views["match_norm"],
            }
        )
    return {
        "sentences_by_block": by_block,
        "sentences_by_doc_quote": by_doc_quote,
        "sentences_by_doc_quote_norm": by_doc_quote_norm,
        "valid_block_rows_by_doc": valid_block_rows_by_doc,
    }


def _row_match_score(candidate: Any, row: Mapping[str, Any], *, layer_order: Sequence[str]) -> tuple[Any, ...]:
    patch_match = int(bool(row.get("patch_id")) and str(row.get("patch_id")) == str(_candidate_value(candidate, "patch_id", "")))
    reveal_match = int(
        row.get("reveal_group_id") is not None
        and _candidate_value(candidate, "reveal_group_id", None) is not None
        and row.get("reveal_group_id") == _candidate_value(candidate, "reveal_group_id", None)
    )
    block_match = int(str(row.get("block_id") or "") == str(_candidate_value(candidate, "block_id", "")))
    sentence_match = int(str(row.get("sentence_id") or "") == str(_candidate_value(candidate, "sentence_id", "")))
    heading_match = int(
        bool(str(row.get("page_heading_norm") or ""))
        and match_normalize(str(row.get("page_heading_norm") or ""))
        == match_normalize(str(_candidate_value(candidate, "page_heading_norm", "")))
    )
    source_match = int(
        bool(str(row.get("source_block_text") or ""))
        and normalize_ws(str(row.get("source_block_text") or "")) == normalize_ws(str(_candidate_value(candidate, "source_block_text", "")))
    )
    return (
        sentence_match,
        block_match,
        patch_match,
        reveal_match,
        source_match,
        heading_match,
        -_layer_rank(str(row.get("layer") or ""), layer_order),
        -safe_int(row.get("page_index"), default=-1),
        str(row.get("block_id") or ""),
    )


def _block_match_score(candidate: Any, row: Mapping[str, Any], *, layer_order: Sequence[str]) -> tuple[Any, ...]:
    quote_raw = str(_candidate_value(candidate, "quote_raw", "") or _candidate_value(candidate, "quote", ""))
    quote_norm = str(_candidate_value(candidate, "quote_match_norm", "") or match_normalize(quote_raw))
    text_raw = str(row.get("text_raw") or row.get("text") or "")
    text_norm = str(row.get("text_match_norm") or match_normalize(text_raw))
    exact_quote = int(bool(quote_raw) and quote_raw in text_raw)
    norm_quote = int(bool(quote_norm) and quote_norm in text_norm)
    heading_match = int(
        bool(str(row.get("page_heading_norm") or ""))
        and match_normalize(str(row.get("page_heading_norm") or ""))
        == match_normalize(str(_candidate_value(candidate, "page_heading_norm", "")))
    )
    return (
        exact_quote,
        norm_quote,
        heading_match,
        -_layer_rank(str(row.get("layer") or ""), layer_order),
        -safe_int(row.get("page_index"), default=-1),
        str(row.get("block_id") or ""),
    )


def _sentence_updates(candidate: Any, row: Mapping[str, Any], *, status: str, reason: str) -> Dict[str, Any]:
    source_block_text = str(row.get("source_block_text_raw") or row.get("source_block_text") or "")
    return {
        "block_id": str(row.get("block_id") or _candidate_value(candidate, "block_id", "")),
        "page_index": safe_int(row.get("page_index"), default=safe_int(_candidate_value(candidate, "page_index", -1), default=-1)),
        "layer": str(row.get("layer") or _candidate_value(candidate, "layer", "")),
        "bbox": row.get("bbox"),
        "sentence_id": str(row.get("sentence_id") or _candidate_value(candidate, "sentence_id", "")),
        "sent_idx": safe_int(row.get("sent_idx"), default=safe_int(_candidate_value(candidate, "sent_idx", -1), default=-1)),
        "char_start": safe_int(row.get("char_start"), default=safe_int(_candidate_value(candidate, "char_start", -1), default=-1)),
        "char_end": safe_int(row.get("char_end"), default=safe_int(_candidate_value(candidate, "char_end", -1), default=-1)),
        "reveal_group_id": row.get("reveal_group_id", _candidate_value(candidate, "reveal_group_id", None)),
        "reveal_canonical_page_index": row.get(
            "reveal_canonical_page_index",
            _candidate_value(candidate, "reveal_canonical_page_index", None),
        ),
        "patch_id": str(row.get("patch_id") or _candidate_value(candidate, "patch_id", "")),
        "patch_heading": str(row.get("patch_heading") or _candidate_value(candidate, "patch_heading", "")),
        "patch_type": str(row.get("patch_type") or _candidate_value(candidate, "patch_type", "")),
        "patch_span_source": str(row.get("patch_span_source") or _candidate_value(candidate, "patch_span_source", "")),
        "page_heading_norm": str(row.get("page_heading_norm") or _candidate_value(candidate, "page_heading_norm", "")),
        "text_source": str(row.get("text_source") or _candidate_value(candidate, "text_source", "")),
        "source_text": source_block_text or str(_candidate_value(candidate, "source_text", "")),
        "text_raw": source_block_text or str(_candidate_value(candidate, "text_raw", "")),
        "text_match_norm": str(row.get("source_block_text_match_norm") or match_normalize(source_block_text or _candidate_value(candidate, "source_text", ""))),
        "source_block_text": source_block_text or str(_candidate_value(candidate, "source_block_text", "")),
        "source_block_text_raw": source_block_text or str(_candidate_value(candidate, "source_block_text_raw", "")),
        "source_block_text_match_norm": str(
            row.get("source_block_text_match_norm") or match_normalize(source_block_text or _candidate_value(candidate, "source_block_text", ""))
        ),
        "provenance_status": status,
        "provenance_source": reason,
        "provenance_note": f"{_candidate_value(candidate, 'block_id', '')}->{row.get('block_id')}",
    }


def _block_updates(candidate: Any, row: Mapping[str, Any], *, reason: str) -> Dict[str, Any]:
    source_text = str(row.get("text_raw") or row.get("text") or "")
    return {
        "block_id": str(row.get("block_id") or _candidate_value(candidate, "block_id", "")),
        "page_index": safe_int(row.get("page_index"), default=safe_int(_candidate_value(candidate, "page_index", -1), default=-1)),
        "layer": str(row.get("layer") or _candidate_value(candidate, "layer", "")),
        "bbox": row.get("bbox"),
        "page_heading_norm": str(row.get("page_heading_norm") or _candidate_value(candidate, "page_heading_norm", "")),
        "source_text": source_text or str(_candidate_value(candidate, "source_text", "")),
        "text_raw": source_text or str(_candidate_value(candidate, "text_raw", "")),
        "text_match_norm": str(row.get("text_match_norm") or match_normalize(source_text or _candidate_value(candidate, "source_text", ""))),
        "source_block_text": source_text or str(_candidate_value(candidate, "source_block_text", "")),
        "source_block_text_raw": source_text or str(_candidate_value(candidate, "source_block_text_raw", "")),
        "source_block_text_match_norm": str(
            row.get("text_match_norm") or match_normalize(source_text or _candidate_value(candidate, "source_block_text", ""))
        ),
        "provenance_status": "substituted",
        "provenance_source": reason,
        "provenance_note": f"{_candidate_value(candidate, 'block_id', '')}->{row.get('block_id')}",
    }


def _candidate_quote_raw(candidate: Any) -> str:
    return str(_candidate_value(candidate, "quote_raw", "") or _candidate_value(candidate, "quote", ""))


def _candidate_quote_match_norm(candidate: Any) -> str:
    quote_raw = _candidate_quote_raw(candidate)
    return str(_candidate_value(candidate, "quote_match_norm", "") or match_normalize(quote_raw))


def _candidate_source_text(candidate: Any) -> str:
    return str(_candidate_value(candidate, "text_raw", "") or _candidate_value(candidate, "source_text", ""))


def _candidate_source_block_text(candidate: Any) -> str:
    return str(
        _candidate_value(candidate, "source_block_text_raw", "")
        or _candidate_value(candidate, "source_block_text", "")
        or _candidate_source_text(candidate)
    )


def _quote_updates(
    candidate: Any,
    *,
    source_text: str,
    source_block_text: str,
    reason: str,
    preferred_quote: str = "",
) -> Optional[Dict[str, Any]]:
    quote_raw = _candidate_quote_raw(candidate)
    quote_match_norm = _candidate_quote_match_norm(candidate)
    rebound_quote = ""
    if preferred_quote and verify_quote_in_raw_source(preferred_quote, source_text):
        rebound_quote = preferred_quote
    else:
        rebound_quote = rebind_quote_to_raw_source(
            quote_raw=quote_raw,
            quote_match_norm=quote_match_norm,
            source_text=source_text,
        ) or ""
    if not rebound_quote or not verify_quote_in_raw_source(rebound_quote, source_text):
        return None
    quote_rebound = rebound_quote != quote_raw
    return {
        "quote": rebound_quote,
        "quote_raw": rebound_quote,
        "quote_match_norm": match_normalize(rebound_quote),
        "source_text": source_text,
        "text_raw": source_text,
        "text_match_norm": match_normalize(source_text),
        "source_block_text": source_block_text,
        "source_block_text_raw": source_block_text,
        "source_block_text_match_norm": match_normalize(source_block_text),
        "quote_verified": True,
        "quote_rebound": quote_rebound,
        "quote_rebind_reason": reason if quote_rebound else "",
    }


def _original_candidate_updates(candidate: Any) -> Dict[str, Any]:
    source_text = _candidate_source_text(candidate)
    source_block_text = _candidate_source_block_text(candidate)
    quote_raw = _candidate_quote_raw(candidate)
    if verify_quote_in_raw_source(quote_raw, source_text):
        return {
            "status": "original",
            "reason": "page_index_valid",
            "updates": {
                "quote": quote_raw,
                "quote_raw": quote_raw,
                "quote_match_norm": _candidate_quote_match_norm(candidate),
                "source_text": source_text,
                "text_raw": source_text,
                "text_match_norm": match_normalize(source_text),
                "source_block_text": source_block_text,
                "source_block_text_raw": source_block_text,
                "source_block_text_match_norm": match_normalize(source_block_text),
                "quote_verified": True,
                "quote_rebound": False,
                "quote_rebind_reason": "",
            },
            "quote_rebound": False,
            "quote_rebind_failed": False,
        }
    quote_updates = _quote_updates(
        candidate,
        source_text=source_text,
        source_block_text=source_block_text,
        reason="original_quote_rebound",
    )
    if quote_updates is None:
        return {"status": "dropped", "reason": "original_quote_unverifiable", "updates": {}, "quote_rebound": False, "quote_rebind_failed": True}
    return {
        "status": "original",
        "reason": "original_quote_rebound",
        "updates": quote_updates,
        "quote_rebound": bool(quote_updates.get("quote_rebound")),
        "quote_rebind_failed": False,
    }


def normalize_candidate_provenance(
    candidate: Any,
    provenance_index: Mapping[str, Any],
    *,
    layer_order: Sequence[str],
) -> Dict[str, Any]:
    page_index = safe_int(_candidate_value(candidate, "page_index", -1), default=-1)
    if page_index >= 0:
        return _original_candidate_updates(candidate)
    quote_raw = _candidate_quote_raw(candidate)
    quote_norm = _candidate_quote_match_norm(candidate)
    doc_id = str(_candidate_value(candidate, "doc_id", "") or "")
    block_id = str(_candidate_value(candidate, "block_id", "") or "")
    if not quote_raw or not quote_norm or not doc_id:
        return {"status": "dropped", "reason": "missing_quote_or_doc_id", "updates": {}, "quote_rebound": False, "quote_rebind_failed": False}

    same_block_rows = [
        row
        for row in list((provenance_index.get("sentences_by_block") or {}).get(block_id, []))
        if has_valid_page_index(row.get("page_index"))
        and (
            str(row.get("quote_raw") or row.get("quote") or "") == quote_raw
            or str(row.get("quote_match_norm") or row.get("quote_norm") or "") == quote_norm
        )
    ]
    if same_block_rows:
        best = max(same_block_rows, key=lambda row: _row_match_score(candidate, row, layer_order=layer_order))
        updates = _sentence_updates(candidate, best, status="recovered", reason="overlay_same_block")
        quote_updates = _quote_updates(
            candidate,
            source_text=str(best.get("source_block_text_raw") or best.get("source_block_text") or ""),
            source_block_text=str(best.get("source_block_text_raw") or best.get("source_block_text") or ""),
            preferred_quote=str(best.get("quote_raw") or best.get("quote") or ""),
            reason="overlay_same_block",
        )
        if quote_updates is None:
            return {"status": "dropped", "reason": "overlay_same_block_quote_rebind_failed", "updates": {}, "quote_rebound": False, "quote_rebind_failed": True}
        return {
            "status": "recovered",
            "reason": "overlay_same_block",
            "updates": {**updates, **quote_updates},
            "quote_rebound": bool(quote_updates.get("quote_rebound")),
            "quote_rebind_failed": False,
        }

    same_doc_rows = list(((provenance_index.get("sentences_by_doc_quote") or {}).get(doc_id, {})).get(quote_raw, []))
    same_doc_rows.extend(
        row
        for row in list(((provenance_index.get("sentences_by_doc_quote_norm") or {}).get(doc_id, {})).get(quote_norm, []))
        if row not in same_doc_rows
    )
    valid_same_doc_rows = [row for row in same_doc_rows if has_valid_page_index(row.get("page_index"))]
    if valid_same_doc_rows:
        best = max(valid_same_doc_rows, key=lambda row: _row_match_score(candidate, row, layer_order=layer_order))
        status = "recovered" if str(best.get("block_id") or "") == block_id else "substituted"
        reason = "overlay_exact_sentence" if status == "recovered" else "overlay_layer_substitution"
        updates = _sentence_updates(candidate, best, status=status, reason=reason)
        quote_updates = _quote_updates(
            candidate,
            source_text=str(best.get("source_block_text_raw") or best.get("source_block_text") or ""),
            source_block_text=str(best.get("source_block_text_raw") or best.get("source_block_text") or ""),
            preferred_quote=str(best.get("quote_raw") or best.get("quote") or ""),
            reason=reason,
        )
        if quote_updates is None:
            return {"status": "dropped", "reason": f"{reason}_quote_rebind_failed", "updates": {}, "quote_rebound": False, "quote_rebind_failed": True}
        return {
            "status": status,
            "reason": reason,
            "updates": {**updates, **quote_updates},
            "quote_rebound": bool(quote_updates.get("quote_rebound")),
            "quote_rebind_failed": False,
        }

    valid_block_rows = [
        row
        for row in list((provenance_index.get("valid_block_rows_by_doc") or {}).get(doc_id, []))
        if quote_norm and quote_norm in str(row.get("text_match_norm") or match_normalize(str(row.get("text_raw") or row.get("text") or "")))
    ]
    if valid_block_rows:
        best = max(valid_block_rows, key=lambda row: _block_match_score(candidate, row, layer_order=layer_order))
        updates = _block_updates(candidate, best, reason="block_text_substitution")
        quote_updates = _quote_updates(
            candidate,
            source_text=str(best.get("text_raw") or best.get("text") or ""),
            source_block_text=str(best.get("text_raw") or best.get("text") or ""),
            reason="block_text_substitution",
        )
        if quote_updates is None:
            return {"status": "dropped", "reason": "block_text_substitution_quote_rebind_failed", "updates": {}, "quote_rebound": False, "quote_rebind_failed": True}
        return {
            "status": "substituted",
            "reason": "block_text_substitution",
            "updates": {**updates, **quote_updates},
            "quote_rebound": bool(quote_updates.get("quote_rebound")),
            "quote_rebind_failed": False,
        }

    return {"status": "dropped", "reason": "page_index_unresolved", "updates": {}, "quote_rebound": False, "quote_rebind_failed": False}
