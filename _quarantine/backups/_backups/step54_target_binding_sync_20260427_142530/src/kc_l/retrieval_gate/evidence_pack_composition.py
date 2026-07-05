from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .semantic import match_normalize, normalize_ws, tokenize, unique_preserve_order


EVIDENCE_PACK_CONTRACT_VERSION = "step5_4_role_aware_pack_v1"
EVIDENCE_PACK_ROLES = (
    "definition_kernel",
    "explanatory_gloss",
    "formula_notation",
    "scope_condition",
    "context_completion",
    "example_or_procedure",
    "sibling_contrast",
)
REQUIRED_INSUFFICIENT_REASONS = (
    "definition_anchor_missing",
    "natural_language_anchor_missing",
    "formula_only_support_pack",
    "weak_coverage",
    "sibling_contamination_risk",
    "fragmentary_without_completion",
    "source_provenance_missing",
    "broad_topic_only",
    "example_or_procedure_only",
)
ROLE_PRIORITY = {
    "definition_kernel": 100,
    "explanatory_gloss": 90,
    "formula_notation": 70,
    "scope_condition": 65,
    "context_completion": 60,
    "example_or_procedure": 30,
    "sibling_contrast": 10,
}
DEFINITION_LINK_RE = re.compile(
    r"\b(?:is|are|defined as|refers to|means|called|denote|denotes|represents|corresponds to)\b\s*[:=]?"
)
FORMULA_RE = re.compile(r"(?:=|\\sum|\\log|\\sqrt|∑|Σ|sqrt|log\s*\(|p\s*\(|P\s*\(|argmax|argmin)")
SCOPE_CUE_RE = re.compile(
    r"\b(?:if|when|under|assuming|assume|provided|subject to|only if|unless|where|given|for a fixed)\b"
)
EXAMPLE_CUE_RE = re.compile(r"\b(?:example|for example|for instance|e\.g\.)\b")
PROCEDURE_CUE_RE = re.compile(r"\b(?:algorithm|procedure|step|repeat|compute|return|iterate|input|output)\b")
CONTRAST_CUE_RE = re.compile(r"\b(?:unlike|in contrast|whereas|different from|as opposed to|rather than)\b")
FRAGMENT_PREFIXES = (
    "where ",
    "for ",
    "given ",
    "if ",
    "let ",
    "when ",
    "then ",
    "thus ",
    "therefore ",
    "it ",
    "this ",
    "these ",
    "those ",
)
GENERIC_CONTEXT_PREFIXES = ("for example", "for instance", "example", "note that", "consider ")


def _composition_cfg(cfg: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    source = dict((cfg or {}).get("composition") or cfg or {})
    return {
        "max_slots_total": int(source.get("max_slots_total", 10)),
        "max_definition_kernel": int(source.get("max_definition_kernel", 2)),
        "max_explanatory_gloss": int(source.get("max_explanatory_gloss", 3)),
        "max_formula_notation": int(source.get("max_formula_notation", 2)),
        "max_scope_condition": int(source.get("max_scope_condition", 2)),
        "max_context_completion": int(source.get("max_context_completion", 2)),
        "max_example_or_procedure": int(source.get("max_example_or_procedure", 1)),
        "max_sibling_contrast": int(source.get("max_sibling_contrast", 2)),
        "max_context_completion_items": int(source.get("max_context_completion_items", 2)),
        "max_context_completion_chars": int(source.get("max_context_completion_chars", 420)),
        "max_chars_for_drafting": int(source.get("max_chars_for_drafting", 1800)),
        "max_candidates_considered_per_kc": int(source.get("max_candidates_considered_per_kc", 18)),
        "context_window_sentences": int(source.get("context_window_sentences", 1)),
        "min_definition_score": float(source.get("min_definition_score", 3.0)),
        "min_explanatory_score": float(source.get("min_explanatory_score", 2.0)),
        "min_formula_score": float(source.get("min_formula_score", 2.5)),
        "min_scope_score": float(source.get("min_scope_score", 2.0)),
        "min_example_score": float(source.get("min_example_score", 2.0)),
        "min_sibling_score": float(source.get("min_sibling_score", 1.5)),
    }


def _routing_cfg(cfg: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    source = dict((cfg or {}).get("routing") or {})
    return {
        "standard_min_coverage_score": float(source.get("standard_min_coverage_score", 0.58)),
        "standard_min_density_score": float(source.get("standard_min_density_score", 0.32)),
        "partial_min_coverage_score": float(source.get("partial_min_coverage_score", 0.2)),
    }


def _as_text(value: Any) -> str:
    return normalize_ws(str(value or ""))


def _as_int(value: Any, default: int = -1) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _string_list(value: Any) -> List[str]:
    return [str(item) for item in value or [] if str(item).strip()]


def _topic_path_labels(kc_row: Mapping[str, Any]) -> List[str]:
    raw = _string_list(kc_row.get("source_hierarchy_path") or kc_row.get("kc_path") or [])
    canonical_name = _as_text(kc_row.get("canonical_name"))
    if raw and canonical_name and match_normalize(raw[-1]) == match_normalize(canonical_name):
        return raw[:-1]
    return raw


def _topic_path_ids(kc_row: Mapping[str, Any], topic_path_labels: Sequence[str]) -> List[str]:
    ancestor_ids = _string_list(kc_row.get("ancestor_hier_node_ids") or [])
    if ancestor_ids:
        return ancestor_ids[: len(topic_path_labels)]
    return []


def _parent_topic_id(kc_row: Mapping[str, Any], topic_path_ids: Sequence[str]) -> str:
    if kc_row.get("parent_hier_node_id"):
        return str(kc_row.get("parent_hier_node_id") or "")
    return str(topic_path_ids[-1]) if topic_path_ids else ""


def _parent_topic_label(topic_path_labels: Sequence[str]) -> str:
    return str(topic_path_labels[-1]) if topic_path_labels else ""


def build_pack_candidate_id(kc_id: str, source_candidate_index: int, candidate_row: Mapping[str, Any]) -> str:
    payload = {
        "kc_id": str(kc_id),
        "source_candidate_index": int(source_candidate_index),
        "doc_id": str(candidate_row.get("doc_id") or ""),
        "block_id": str(candidate_row.get("block_id") or ""),
        "page_index": candidate_row.get("page_index"),
        "sentence_id": str(candidate_row.get("sentence_id") or ""),
        "snippet": _as_text(
            candidate_row.get("snippet") or candidate_row.get("quote_surface") or candidate_row.get("text") or ""
        ),
    }
    digest = hashlib.sha1(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return f"{kc_id}:step5_4:{digest}"


def _source_order_key(item: Mapping[str, Any]) -> Tuple[int, int, str, int, int, int, str]:
    return (
        _as_int(item.get("doc_rank"), default=9999),
        _as_int(item.get("page_index"), default=9999),
        str(item.get("block_id") or item.get("patch_id") or item.get("sentence_id") or ""),
        _as_int(item.get("sent_idx"), default=9999),
        _as_int(item.get("char_start"), default=9999),
        _as_int(item.get("source_candidate_index"), default=9999),
        str(item.get("candidate_id") or ""),
    )


def _natural_language_like(text: str, *, formula_like: bool) -> bool:
    if not text:
        return False
    alpha_chars = sum(1 for char in text if char.isalpha())
    if alpha_chars == 0:
        return False
    if formula_like and alpha_chars < max(6, len(text) // 6):
        return False
    return True


def _fragmentary_surface(text: str, *, formula_like: bool, relation_like: bool) -> bool:
    lower = match_normalize(text)
    token_count = len(tokenize(lower, min_len=2))
    if not text:
        return True
    if any(lower.startswith(prefix) for prefix in FRAGMENT_PREFIXES):
        return True
    if any(lower.startswith(prefix) for prefix in GENERIC_CONTEXT_PREFIXES):
        return True
    if lower.endswith((":", "=", " where", " which", " that", " such that")):
        return True
    if formula_like and token_count <= 10 and not relation_like:
        return True
    if token_count < 7 and not relation_like:
        return True
    return False


def _relation_like(text: str, support_profile: Mapping[str, Any]) -> bool:
    if bool(support_profile.get("relation_like", False)):
        return True
    return DEFINITION_LINK_RE.search(match_normalize(text)) is not None


def _scope_like(text: str) -> bool:
    return SCOPE_CUE_RE.search(match_normalize(text)) is not None


def _context_completion_source_available(text: str, source_block_text: str, support_profile: Mapping[str, Any]) -> bool:
    if bool(support_profile.get("has_context_completion_source", False)):
        return True
    return bool(source_block_text and source_block_text != text and len(source_block_text) >= len(text) + 20)


def _candidate_flags(candidate_row: Mapping[str, Any]) -> Dict[str, bool]:
    flags = dict(candidate_row.get("sentence_flags") or (candidate_row.get("alignment_breakdown") or {}).get("flags") or {})
    return {
        "is_formula_like": bool(candidate_row.get("is_formula_like", flags.get("is_formula_like", False))),
        "is_definition_like": bool(candidate_row.get("is_definition_like", flags.get("is_definition_like", False))),
        "is_procedure_like": bool(candidate_row.get("is_procedure_like", flags.get("is_procedure_like", False))),
        "is_example_like": bool(candidate_row.get("is_example_like", flags.get("is_example_like", False))),
        "is_heading_like": bool(candidate_row.get("is_heading_like", flags.get("is_heading_like", False))),
    }


def _candidate_target_binding_score(candidate_row: Mapping[str, Any], support_profile: Mapping[str, Any]) -> float:
    alignment_breakdown = dict(candidate_row.get("alignment_breakdown") or {})
    score = 0.0
    if bool(alignment_breakdown.get("exact_name_phrase", False)):
        score += 3.0
    if bool(alignment_breakdown.get("exact_alias_phrase", False)):
        score += 2.5
    if bool(alignment_breakdown.get("name_or_alias_hit", False)):
        score += 1.5
    score += 0.75 * min(2, _as_int(alignment_breakdown.get("context_keyword_hits"), default=0))
    score += 0.35 * min(2, _as_int(alignment_breakdown.get("heading_name_hits"), default=0))
    score -= 1.0 * min(3, _as_int(alignment_breakdown.get("competitor_token_hits"), default=0))
    if bool(candidate_row.get("doc_mismatch", False)):
        score -= 1.5
    if bool(support_profile.get("contamination_exclusion_hint", False)):
        score -= 1.0
    return score


def _candidate_view(
    kc_row: Mapping[str, Any],
    candidate_row: Mapping[str, Any],
    source_candidate_index: int,
    doc_rank: int,
) -> Dict[str, Any]:
    support_profile = dict(candidate_row.get("support_profile") or (candidate_row.get("alignment_breakdown") or {}).get("support_profile") or {})
    flags = _candidate_flags(candidate_row)
    text = _as_text(candidate_row.get("snippet") or candidate_row.get("quote_surface") or candidate_row.get("text"))
    source_block_text = _as_text(candidate_row.get("source_block_text") or candidate_row.get("source_block_text_raw") or text)
    relation_like = _relation_like(text, support_profile)
    formula_like = bool(flags["is_formula_like"] or FORMULA_RE.search(text))
    procedure_like = bool(flags["is_procedure_like"] or PROCEDURE_CUE_RE.search(match_normalize(text)))
    example_like = bool(flags["is_example_like"] or EXAMPLE_CUE_RE.search(match_normalize(text)))
    scope_like = bool(_scope_like(text))
    fragmentary = bool(
        support_profile.get("fragmentary_surface", False) or _fragmentary_surface(text, formula_like=formula_like, relation_like=relation_like)
    )
    natural_language_like = _natural_language_like(text, formula_like=formula_like)
    contamination_risk = str(
        candidate_row.get("contamination_risk")
        or (candidate_row.get("alignment_breakdown") or {}).get("contamination_risk")
        or "low"
    )
    candidate_id = build_pack_candidate_id(str(kc_row.get("kc_id") or ""), source_candidate_index, candidate_row)
    target_binding_score = _candidate_target_binding_score(candidate_row, support_profile)
    exact_name_phrase = bool((candidate_row.get("alignment_breakdown") or {}).get("exact_name_phrase", False))
    exact_alias_phrase = bool((candidate_row.get("alignment_breakdown") or {}).get("exact_alias_phrase", False))
    sibling_bias = bool(
        support_profile.get("contamination_exclusion_hint", False)
        or contamination_risk == "high"
        or (
            _as_int((candidate_row.get("alignment_breakdown") or {}).get("competitor_token_hits"), default=0) >= 1
            and not exact_name_phrase
            and not exact_alias_phrase
            and target_binding_score < 2.0
        )
    )
    return {
        "candidate_id": candidate_id,
        "source_row_id": candidate_id,
        "source_candidate_index": int(source_candidate_index),
        "kc_id": str(kc_row.get("kc_id") or ""),
        "canonical_name": _as_text(kc_row.get("canonical_name") or candidate_row.get("canonical_name")),
        "doc_rank": int(doc_rank),
        "doc_id": str(candidate_row.get("doc_id") or ""),
        "block_id": str(candidate_row.get("block_id") or ""),
        "page_index": _as_int(candidate_row.get("page_index"), default=-1),
        "sentence_id": str(candidate_row.get("sentence_id") or ""),
        "sent_idx": _as_int(candidate_row.get("sent_idx"), default=-1),
        "char_start": _as_int(candidate_row.get("char_start"), default=-1),
        "char_end": _as_int(candidate_row.get("char_end"), default=-1),
        "patch_id": str(candidate_row.get("patch_id") or ""),
        "patch_heading": _as_text(candidate_row.get("patch_heading")),
        "page_heading_norm": _as_text(candidate_row.get("page_heading_norm")),
        "reveal_group_id": str(candidate_row.get("reveal_group_id") or ""),
        "text": text,
        "quote": text,
        "source_block_text": source_block_text,
        "alignment_score": float(candidate_row.get("alignment_score") or 0.0),
        "retrieval_scores": dict(candidate_row.get("retrieval_scores") or {}),
        "alignment_breakdown": dict(candidate_row.get("alignment_breakdown") or {}),
        "support_profile": support_profile,
        "formula_like": formula_like,
        "definition_like": bool(flags["is_definition_like"]),
        "procedure_like": procedure_like,
        "example_like": example_like,
        "heading_like": bool(flags["is_heading_like"]),
        "scope_like": scope_like,
        "relation_like": relation_like,
        "fragmentary": fragmentary,
        "natural_language_like": natural_language_like,
        "target_binding_score": float(target_binding_score),
        "contamination_risk": contamination_risk,
        "sibling_bias": sibling_bias,
        "context_completion_available": _context_completion_source_available(text, source_block_text, support_profile),
        "quote_verified": bool(candidate_row.get("quote_verified", False)),
        "source_provenance_available": bool(
            str(candidate_row.get("doc_id") or "")
            or str(candidate_row.get("block_id") or "")
            or str(candidate_row.get("sentence_id") or "")
        ),
    }


def _definition_score(candidate: Mapping[str, Any]) -> float:
    score = float(candidate.get("alignment_score") or 0.0)
    support_profile = dict(candidate.get("support_profile") or {})
    preferred_role = str(support_profile.get("preferred_support_role") or "other")
    anchor_quality = str(support_profile.get("anchor_quality") or "weak")
    if preferred_role == "definitional_anchor":
        score += 4.0
    if anchor_quality == "strong":
        score += 2.0
    elif anchor_quality == "usable":
        score += 1.0
    if bool(candidate.get("relation_like", False)):
        score += 2.5
    if bool(candidate.get("natural_language_like", False)):
        score += 1.5
    if bool(candidate.get("definition_like", False)):
        score += 1.0
    score += float(candidate.get("target_binding_score") or 0.0)
    if bool(candidate.get("fragmentary", False)):
        score -= 1.0
    if bool(candidate.get("formula_like", False)):
        score -= 2.0 if bool(support_profile.get("formula_auxiliary_only", False)) else 0.5
    if bool(candidate.get("procedure_like", False)):
        score -= 2.0
    if bool(candidate.get("example_like", False)):
        score -= 1.5
    if bool(candidate.get("heading_like", False)):
        score -= 2.0
    if bool(candidate.get("sibling_bias", False)):
        score -= 3.0
    return score


def _explanatory_score(candidate: Mapping[str, Any]) -> float:
    score = float(candidate.get("alignment_score") or 0.0) * 0.7
    support_profile = dict(candidate.get("support_profile") or {})
    preferred_role = str(support_profile.get("preferred_support_role") or "other")
    if preferred_role in {"definitional_anchor", "explanatory_anchor", "context_completion_anchor"}:
        score += 2.0
    if bool(candidate.get("natural_language_like", False)):
        score += 2.0
    if bool(candidate.get("context_completion_available", False)):
        score += 1.5
    if bool(candidate.get("relation_like", False)):
        score += 1.0
    score += 0.6 * float(candidate.get("target_binding_score") or 0.0)
    if bool(candidate.get("formula_like", False)) and not bool(candidate.get("natural_language_like", False)):
        score -= 2.0
    if bool(candidate.get("example_like", False)):
        score -= 1.0
    if bool(candidate.get("procedure_like", False)):
        score -= 0.75
    if bool(candidate.get("sibling_bias", False)):
        score -= 1.5
    return score


def _formula_score(candidate: Mapping[str, Any]) -> float:
    score = float(candidate.get("alignment_score") or 0.0)
    support_profile = dict(candidate.get("support_profile") or {})
    if bool(candidate.get("formula_like", False)):
        score += 3.0
    if str(support_profile.get("preferred_support_role") or "") == "formula_or_parameter_anchor":
        score += 2.0
    if bool(candidate.get("relation_like", False)):
        score += 0.75
    if bool(candidate.get("sibling_bias", False)):
        score -= 1.0
    return score


def _scope_score(candidate: Mapping[str, Any]) -> float:
    score = float(candidate.get("alignment_score") or 0.0) * 0.75
    if bool(candidate.get("scope_like", False)):
        score += 2.5
    if bool(candidate.get("natural_language_like", False)):
        score += 0.5
    score += 0.4 * float(candidate.get("target_binding_score") or 0.0)
    if bool(candidate.get("sibling_bias", False)):
        score -= 1.0
    return score


def _example_score(candidate: Mapping[str, Any]) -> float:
    score = float(candidate.get("alignment_score") or 0.0) * 0.7
    if bool(candidate.get("example_like", False)):
        score += 2.0
    if bool(candidate.get("procedure_like", False)):
        score += 2.0
    if bool(candidate.get("scope_like", False)):
        score += 0.5
    if bool(candidate.get("sibling_bias", False)):
        score -= 0.5
    return score


def _sibling_score(candidate: Mapping[str, Any]) -> float:
    score = 0.0
    if bool(candidate.get("sibling_bias", False)):
        score += 3.0
    if str(candidate.get("contamination_risk") or "") == "high":
        score += 2.0
    elif str(candidate.get("contamination_risk") or "") == "medium":
        score += 1.0
    score += max(0.0, 1.5 - float(candidate.get("target_binding_score") or 0.0))
    if CONTRAST_CUE_RE.search(match_normalize(str(candidate.get("text") or ""))) is not None:
        score += 0.5
    return score


def _completion_text_from_source_block(candidate: Mapping[str, Any], max_chars: int) -> Tuple[str, str]:
    text = _as_text(candidate.get("text"))
    source_block_text = _as_text(candidate.get("source_block_text"))
    if not source_block_text or source_block_text == text or len(source_block_text) <= len(text) + 12:
        return "", ""
    if len(source_block_text) > max_chars:
        source_block_text = source_block_text[: max_chars - 3].rstrip() + "..."
    return source_block_text, "same_block_source_block"


def _normalize_sentence_context_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "doc_id": str(row.get("doc_id") or ""),
        "block_id": str(row.get("block_id") or ""),
        "page_index": _as_int(row.get("page_index"), default=-1),
        "sentence_id": str(row.get("sentence_id") or ""),
        "sent_idx": _as_int(row.get("sent_idx"), default=-1),
        "char_start": _as_int(row.get("char_start"), default=-1),
        "patch_id": str(row.get("patch_id") or ""),
        "patch_heading": _as_text(row.get("patch_heading")),
        "page_heading_norm": _as_text(row.get("page_heading_norm") or row.get("patch_heading")),
        "reveal_group_id": str(row.get("reveal_group_id") or ""),
        "text": _as_text(
            row.get("sentence_text") or row.get("quote_surface") or row.get("snippet") or row.get("text") or ""
        ),
    }


def build_sentence_context_index(sentence_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    by_block: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    by_patch: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    by_reveal: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    by_heading: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    by_page: Dict[Tuple[str, int], List[Dict[str, Any]]] = defaultdict(list)
    by_sentence_id: Dict[str, Dict[str, Any]] = {}
    for row in sentence_rows:
        normalized = _normalize_sentence_context_row(row)
        text = str(normalized.get("text") or "")
        if not text:
            continue
        rows.append(normalized)
        if normalized["sentence_id"]:
            by_sentence_id[normalized["sentence_id"]] = normalized
        if normalized["doc_id"] and normalized["block_id"]:
            by_block[(normalized["doc_id"], normalized["block_id"])].append(normalized)
        if normalized["doc_id"] and normalized["patch_id"]:
            by_patch[(normalized["doc_id"], normalized["patch_id"])].append(normalized)
        if normalized["doc_id"] and normalized["reveal_group_id"]:
            by_reveal[(normalized["doc_id"], normalized["reveal_group_id"])].append(normalized)
        if normalized["doc_id"] and normalized["page_heading_norm"]:
            by_heading[(normalized["doc_id"], normalized["page_heading_norm"])].append(normalized)
        if normalized["doc_id"] and normalized["page_index"] >= 0:
            by_page[(normalized["doc_id"], normalized["page_index"])].append(normalized)
    for grouped in list(by_block.values()) + list(by_patch.values()) + list(by_reveal.values()) + list(by_heading.values()) + list(by_page.values()):
        grouped.sort(key=lambda item: (_as_int(item.get("sent_idx"), default=9999), _as_int(item.get("char_start"), default=9999), str(item.get("sentence_id") or "")))
    return {
        "rows": rows,
        "by_sentence_id": by_sentence_id,
        "by_block": by_block,
        "by_patch": by_patch,
        "by_reveal": by_reveal,
        "by_heading": by_heading,
        "by_page": by_page,
    }


def _candidate_context_position(
    candidate: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
) -> int:
    sentence_id = str(candidate.get("sentence_id") or "")
    if sentence_id:
        for index, row in enumerate(rows):
            if str(row.get("sentence_id") or "") == sentence_id:
                return index
    candidate_text = match_normalize(str(candidate.get("text") or ""))
    for index, row in enumerate(rows):
        if candidate_text and match_normalize(str(row.get("text") or "")) == candidate_text:
            return index
    sent_idx = _as_int(candidate.get("sent_idx"), default=-1)
    if sent_idx >= 0:
        for index, row in enumerate(rows):
            if _as_int(row.get("sent_idx"), default=-1) == sent_idx:
                return index
    return -1


def _completion_text_from_rows(
    candidate: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    window: int,
    max_chars: int,
) -> str:
    if not rows:
        return ""
    position = _candidate_context_position(candidate, rows)
    if position < 0:
        return ""
    start = max(0, position - max(1, window))
    end = min(len(rows), position + max(1, window) + 1)
    parts: List[str] = []
    candidate_text_norm = match_normalize(str(candidate.get("text") or ""))
    for row in rows[start:end]:
        text = _as_text(row.get("text"))
        if not text:
            continue
        if candidate_text_norm and match_normalize(text) == candidate_text_norm:
            continue
        parts.append(text)
    if not parts:
        return ""
    merged = normalize_ws(" ".join(parts))
    if len(merged) > max_chars:
        merged = merged[: max_chars - 3].rstrip() + "..."
    return merged


def _completion_from_sentence_index(
    candidate: Mapping[str, Any],
    sentence_context_index: Mapping[str, Any] | None,
    cfg: Mapping[str, Any],
) -> Tuple[str, str]:
    if not sentence_context_index:
        return "", ""
    composition_cfg = _composition_cfg(cfg)
    max_chars = int(composition_cfg["max_context_completion_chars"])
    window = int(composition_cfg["context_window_sentences"])
    doc_id = str(candidate.get("doc_id") or "")
    block_id = str(candidate.get("block_id") or "")
    if doc_id and block_id:
        text = _completion_text_from_rows(
            candidate,
            list((sentence_context_index.get("by_block") or {}).get((doc_id, block_id), [])),
            window=window,
            max_chars=max_chars,
        )
        if text:
            return text, "same_block_neighbors"
    patch_id = str(candidate.get("patch_id") or "")
    if doc_id and patch_id:
        text = _completion_text_from_rows(
            candidate,
            list((sentence_context_index.get("by_patch") or {}).get((doc_id, patch_id), [])),
            window=window,
            max_chars=max_chars,
        )
        if text:
            return text, "same_patch_neighbors"
    reveal_group_id = str(candidate.get("reveal_group_id") or "")
    if doc_id and reveal_group_id:
        text = _completion_text_from_rows(
            candidate,
            list((sentence_context_index.get("by_reveal") or {}).get((doc_id, reveal_group_id), [])),
            window=window,
            max_chars=max_chars,
        )
        if text:
            return text, "same_reveal_group_neighbors"
    heading_norm = _as_text(candidate.get("page_heading_norm") or candidate.get("patch_heading"))
    if doc_id and heading_norm:
        text = _completion_text_from_rows(
            candidate,
            list((sentence_context_index.get("by_heading") or {}).get((doc_id, heading_norm), [])),
            window=window,
            max_chars=max_chars,
        )
        if text:
            return text, "same_heading_neighbors"
    page_index = _as_int(candidate.get("page_index"), default=-1)
    if doc_id and page_index >= 0 and str(candidate.get("contamination_risk") or "") != "high":
        text = _completion_text_from_rows(
            candidate,
            list((sentence_context_index.get("by_page") or {}).get((doc_id, page_index), [])),
            window=window,
            max_chars=max_chars,
        )
        if text:
            return text, "same_page_neighbors"
    return "", ""


def _build_slot_item(
    candidate: Mapping[str, Any],
    *,
    role: str,
    reason_selected: str,
    risk_flags: Sequence[str],
    text: Optional[str] = None,
    candidate_id: Optional[str] = None,
    source_row_id: Optional[str] = None,
    generated: bool = False,
) -> Dict[str, Any]:
    item_text = _as_text(text if text is not None else candidate.get("text"))
    source_candidate_id = str(candidate.get("candidate_id") or "")
    return {
        "candidate_id": str(candidate_id or source_candidate_id),
        "source_candidate_id": source_candidate_id,
        "source_row_id": str(source_row_id or candidate.get("source_row_id") or source_candidate_id),
        "source_candidate_index": _as_int(candidate.get("source_candidate_index"), default=-1),
        "role": role,
        "text": item_text,
        "quote": item_text,
        "doc_id": str(candidate.get("doc_id") or ""),
        "page_index": _as_int(candidate.get("page_index"), default=-1),
        "sentence_id": str(candidate.get("sentence_id") or ""),
        "patch_id": str(candidate.get("patch_id") or ""),
        "block_id": str(candidate.get("block_id") or ""),
        "heading_path": [value for value in [_as_text(candidate.get("patch_heading")), _as_text(candidate.get("page_heading_norm"))] if value],
        "retrieval_scores": dict(candidate.get("retrieval_scores") or {}),
        "alignment_score": float(candidate.get("alignment_score") or 0.0),
        "support_profile": dict(candidate.get("support_profile") or {}),
        "reason_selected": reason_selected,
        "risk_flags": unique_preserve_order([str(flag) for flag in risk_flags if str(flag).strip()]),
        "contamination_risk": str(candidate.get("contamination_risk") or ""),
        "formula_like": bool(candidate.get("formula_like", False)),
        "definition_like": bool(candidate.get("definition_like", False)),
        "procedure_like": bool(candidate.get("procedure_like", False)),
        "example_like": bool(candidate.get("example_like", False)),
        "natural_language_like": bool(candidate.get("natural_language_like", False)),
        "generated": bool(generated),
        "doc_rank": _as_int(candidate.get("doc_rank"), default=9999),
        "sent_idx": _as_int(candidate.get("sent_idx"), default=9999),
        "char_start": _as_int(candidate.get("char_start"), default=9999),
    }


def _candidate_risk_flags(candidate: Mapping[str, Any]) -> List[str]:
    flags: List[str] = []
    if bool(candidate.get("formula_like", False)):
        flags.append("formula_like")
    if bool(candidate.get("fragmentary", False)):
        flags.append("fragmentary_surface")
    if bool(candidate.get("procedure_like", False)):
        flags.append("procedure_like")
    if bool(candidate.get("example_like", False)):
        flags.append("example_like")
    if str(candidate.get("contamination_risk") or "") in {"medium", "high"}:
        flags.append(f"contamination_{str(candidate.get('contamination_risk') or '').lower()}")
    if not bool(candidate.get("source_provenance_available", False)):
        flags.append("source_provenance_missing")
    return flags


def _merge_ordered_pack_items(
    slots: Mapping[str, Sequence[Mapping[str, Any]]],
    cfg: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    composition_cfg = _composition_cfg(cfg)
    merged: Dict[str, Dict[str, Any]] = {}
    for role in EVIDENCE_PACK_ROLES:
        for item in slots.get(role) or []:
            candidate_id = str(item.get("candidate_id") or "")
            if not candidate_id:
                continue
            current = merged.get(candidate_id)
            if current is None:
                current = dict(item)
                current["roles"] = [role]
                merged[candidate_id] = current
                continue
            current["roles"] = unique_preserve_order([*current.get("roles", []), role])
            current["risk_flags"] = unique_preserve_order([*(current.get("risk_flags") or []), *(_string_list(item.get("risk_flags")))])
    ranked = sorted(
        merged.values(),
        key=lambda item: (
            -max(ROLE_PRIORITY.get(role, 0) for role in item.get("roles") or ["sibling_contrast"]),
            -float(item.get("alignment_score") or 0.0),
            _source_order_key(item),
        ),
    )
    chosen: List[Dict[str, Any]] = []
    total_chars = 0
    max_slots_total = int(composition_cfg["max_slots_total"])
    max_chars_for_drafting = int(composition_cfg["max_chars_for_drafting"])
    for item in ranked:
        text = _as_text(item.get("text"))
        if not text:
            continue
        if len(chosen) >= max_slots_total:
            break
        if chosen and total_chars + len(text) > max_chars_for_drafting:
            continue
        chosen.append(item)
        total_chars += len(text)
    chosen.sort(key=_source_order_key)
    return chosen


def _slot_membership(items: Sequence[Mapping[str, Any]], candidate_id: str) -> bool:
    for item in items:
        if str(item.get("candidate_id") or "") == candidate_id:
            return True
        if str(item.get("source_candidate_id") or "") == candidate_id:
            return True
    return False


def build_evidence_pack_membership_index(pack_row: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    slots = dict(pack_row.get("slots") or {})
    ordered_pack = list(pack_row.get("ordered_pack_for_drafting") or [])
    membership: Dict[str, Dict[str, Any]] = {}
    for role in EVIDENCE_PACK_ROLES:
        for slot_index, item in enumerate(slots.get(role) or []):
            for candidate_id in (
                str(item.get("candidate_id") or ""),
                str(item.get("source_candidate_id") or ""),
            ):
                if not candidate_id:
                    continue
                payload = membership.setdefault(
                    candidate_id,
                    {"slot_roles": [], "slot_positions": {}, "ordered_pack_positions": []},
                )
                payload["slot_roles"] = unique_preserve_order([*payload["slot_roles"], role])
                payload["slot_positions"][role] = int(slot_index)
    for ordered_index, item in enumerate(ordered_pack):
        for candidate_id in (
            str(item.get("candidate_id") or ""),
            str(item.get("source_candidate_id") or ""),
        ):
            if not candidate_id:
                continue
            payload = membership.setdefault(
                candidate_id,
                {"slot_roles": [], "slot_positions": {}, "ordered_pack_positions": []},
            )
            payload["ordered_pack_positions"] = unique_preserve_order(
                [*payload["ordered_pack_positions"], int(ordered_index)]
            )
    return membership


def _select_slot(
    slot_name: str,
    candidates: Sequence[Mapping[str, Any]],
    *,
    limit: int,
    min_score: float,
    score_fn,
    allow_formula_primary: bool = False,
    exclude_ids: Optional[set[str]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, float]]:
    selected: List[Dict[str, Any]] = []
    scores: Dict[str, float] = {}
    excluded = exclude_ids if exclude_ids is not None else set()
    ranked = sorted(
        candidates,
        key=lambda candidate: (-float(score_fn(candidate)), _source_order_key(candidate)),
    )
    for candidate in ranked:
        candidate_id = str(candidate.get("candidate_id") or "")
        if candidate_id in excluded:
            continue
        score = float(score_fn(candidate))
        scores[candidate_id] = score
        if score < min_score:
            continue
        if slot_name == "definition_kernel":
            preferred_role = str(dict(candidate.get("support_profile") or {}).get("preferred_support_role") or "other")
            if bool(candidate.get("formula_like", False)) and not allow_formula_primary:
                continue
            if bool(candidate.get("procedure_like", False)) or bool(candidate.get("example_like", False)):
                continue
            if (
                float(candidate.get("target_binding_score") or 0.0) < 1.0
                and preferred_role != "definitional_anchor"
                and not bool(candidate.get("definition_like", False))
            ):
                continue
            if (
                preferred_role not in {"definitional_anchor", "explanatory_anchor", "context_completion_anchor"}
                and not bool(candidate.get("definition_like", False))
                and not bool(candidate.get("relation_like", False))
            ):
                continue
            if bool(candidate.get("sibling_bias", False)) and float(candidate.get("target_binding_score") or 0.0) < 2.5:
                continue
        if slot_name == "explanatory_gloss":
            if bool(candidate.get("formula_like", False)) and bool(
                dict(candidate.get("support_profile") or {}).get("formula_auxiliary_only", False)
            ):
                continue
            preferred_role = str(dict(candidate.get("support_profile") or {}).get("preferred_support_role") or "other")
            if (
                float(candidate.get("target_binding_score") or 0.0) < 0.75
                and preferred_role not in {"definitional_anchor", "explanatory_anchor", "context_completion_anchor"}
            ):
                continue
            if bool(candidate.get("sibling_bias", False)) and float(candidate.get("target_binding_score") or 0.0) < 1.5:
                continue
        if slot_name == "formula_notation" and not bool(candidate.get("formula_like", False)):
            continue
        if slot_name == "scope_condition" and not bool(candidate.get("scope_like", False)):
            continue
        if slot_name == "example_or_procedure" and not (bool(candidate.get("example_like", False)) or bool(candidate.get("procedure_like", False))):
            continue
        if slot_name == "sibling_contrast" and not bool(candidate.get("sibling_bias", False)):
            continue
        risk_flags = _candidate_risk_flags(candidate)
        item = _build_slot_item(
            candidate,
            role=slot_name,
            reason_selected=f"selected_as_{slot_name}",
            risk_flags=risk_flags,
        )
        selected.append(item)
        excluded.add(candidate_id)
        if len(selected) >= max(0, int(limit)):
            break
    return selected, scores


def _context_completion_item(
    candidate: Mapping[str, Any],
    *,
    sentence_context_index: Mapping[str, Any] | None,
    cfg: Mapping[str, Any],
) -> Tuple[Optional[Dict[str, Any]], str]:
    composition_cfg = _composition_cfg(cfg)
    max_chars = int(composition_cfg["max_context_completion_chars"])
    completion_text, completion_mode = _completion_text_from_source_block(candidate, max_chars)
    if not completion_text:
        completion_text, completion_mode = _completion_from_sentence_index(candidate, sentence_context_index, cfg)
    if not completion_text:
        return None, ""
    generated_id = f"{str(candidate.get('candidate_id') or '')}:context"
    item = _build_slot_item(
        candidate,
        role="context_completion",
        candidate_id=generated_id,
        source_row_id=str(candidate.get("candidate_id") or ""),
        reason_selected=f"fragmentary_anchor_{completion_mode}",
        risk_flags=[*_candidate_risk_flags(candidate), f"completion_mode:{completion_mode}"],
        text=completion_text,
        generated=True,
    )
    return item, completion_mode


def _selected_candidate_ids(slots: Mapping[str, Sequence[Mapping[str, Any]]]) -> List[str]:
    selected: List[str] = []
    for role in EVIDENCE_PACK_ROLES:
        for item in slots.get(role) or []:
            candidate_id = str(item.get("source_candidate_id") or item.get("candidate_id") or "")
            if candidate_id:
                selected.append(candidate_id)
    return unique_preserve_order(selected)


def _all_span_ids(slots: Mapping[str, Sequence[Mapping[str, Any]]]) -> List[str]:
    values: List[str] = []
    for role in EVIDENCE_PACK_ROLES:
        for item in slots.get(role) or []:
            for candidate_id in (
                str(item.get("candidate_id") or ""),
                str(item.get("source_candidate_id") or ""),
            ):
                if candidate_id:
                    values.append(candidate_id)
    return unique_preserve_order(values)


def _all_source_refs(slots: Mapping[str, Sequence[Mapping[str, Any]]]) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    seen: set[Tuple[str, int, str, str]] = set()
    for role in EVIDENCE_PACK_ROLES:
        for item in slots.get(role) or []:
            key = (
                str(item.get("doc_id") or ""),
                _as_int(item.get("page_index"), default=-1),
                str(item.get("block_id") or ""),
                str(item.get("sentence_id") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            refs.append(
                {
                    "doc_id": key[0],
                    "page_index": key[1],
                    "block_id": key[2],
                    "sentence_id": key[3],
                }
            )
    return refs


def _pack_quality(
    *,
    candidates: Sequence[Mapping[str, Any]],
    slots: Mapping[str, Sequence[Mapping[str, Any]]],
    ordered_pack: Sequence[Mapping[str, Any]],
    cfg: Mapping[str, Any],
) -> Dict[str, Any]:
    routing_cfg = _routing_cfg(cfg)
    definition_items = list(slots.get("definition_kernel") or [])
    explanatory_items = list(slots.get("explanatory_gloss") or [])
    formula_items = list(slots.get("formula_notation") or [])
    scope_items = list(slots.get("scope_condition") or [])
    context_items = list(slots.get("context_completion") or [])
    example_items = list(slots.get("example_or_procedure") or [])
    sibling_items = list(slots.get("sibling_contrast") or [])
    definition_anchor_present = bool(definition_items)
    natural_language_definition_items = [
        item
        for item in definition_items
        if bool(item.get("natural_language_like", False)) and not bool(item.get("formula_like", False))
    ]
    definition_anchor_natural_language = bool(natural_language_definition_items)
    formula_primary = bool(definition_items and all(bool(item.get("formula_like", False)) for item in definition_items))
    formula_auxiliary_only = bool(formula_items) and not formula_primary
    context_completion_used = bool(context_items)
    formula_dominance_risk = "low"
    if formula_primary and not definition_anchor_natural_language:
        formula_dominance_risk = "high"
    elif formula_items and (not definition_anchor_natural_language or len(formula_items) >= len(explanatory_items) + 1):
        formula_dominance_risk = "medium"
    sibling_contamination_risk = "low"
    if any("contamination_high" in _string_list(item.get("risk_flags")) for item in definition_items):
        sibling_contamination_risk = "high"
    elif sibling_items or any("contamination_medium" in _string_list(item.get("risk_flags")) for item in ordered_pack):
        sibling_contamination_risk = "medium"
    coverage_components = 0.0
    coverage_components += 1.0 if definition_items else 0.0
    coverage_components += 1.0 if explanatory_items else 0.0
    coverage_components += 0.5 if scope_items else 0.0
    coverage_components += 0.5 if context_items else 0.0
    coverage_components += 0.35 if formula_items else 0.0
    coverage_components += 0.15 if example_items else 0.0
    coverage_score = min(1.0, coverage_components / 3.0)
    max_chars_for_drafting = float(_composition_cfg(cfg)["max_chars_for_drafting"])
    selected_chars = float(sum(len(_as_text(item.get("text"))) for item in ordered_pack))
    density_score = 0.0
    if max_chars_for_drafting > 0:
        density_score = min(1.0, selected_chars / max_chars_for_drafting)
    has_any_grounded_support = bool(definition_items or explanatory_items or formula_items or scope_items)
    insufficient_reasons: List[str] = []
    if not definition_anchor_present:
        insufficient_reasons.append("definition_anchor_missing")
    if not definition_anchor_natural_language:
        insufficient_reasons.append("natural_language_anchor_missing")
    if formula_primary and not definition_anchor_natural_language:
        insufficient_reasons.append("formula_only_support_pack")
    if coverage_score < float(routing_cfg["partial_min_coverage_score"]):
        insufficient_reasons.append("weak_coverage")
    if sibling_contamination_risk == "high":
        insufficient_reasons.append("sibling_contamination_risk")
    if any(bool(candidate.get("fragmentary", False)) for candidate in candidates) and not context_completion_used:
        insufficient_reasons.append("fragmentary_without_completion")
    if not any(bool(candidate.get("source_provenance_available", False)) for candidate in candidates):
        insufficient_reasons.append("source_provenance_missing")
    if has_any_grounded_support and not any(float(candidate.get("target_binding_score") or 0.0) >= 2.0 for candidate in candidates):
        insufficient_reasons.append("broad_topic_only")
    if not has_any_grounded_support and example_items:
        insufficient_reasons.append("example_or_procedure_only")

    if (
        definition_anchor_natural_language
        and coverage_score >= float(routing_cfg["standard_min_coverage_score"])
        and density_score >= float(routing_cfg["standard_min_density_score"])
        and sibling_contamination_risk == "low"
        and formula_dominance_risk != "high"
    ):
        route = "standard_drafting"
    elif definition_anchor_present and has_any_grounded_support:
        route = "escalated_evidence_rescue"
    elif has_any_grounded_support and (definition_items or explanatory_items or formula_items or scope_items):
        route = "partial_grounded_packet"
    else:
        route = "insufficient_support_packet"

    return {
        "definition_anchor_present": definition_anchor_present,
        "definition_anchor_natural_language": definition_anchor_natural_language,
        "context_completion_used": context_completion_used,
        "formula_primary": formula_primary,
        "formula_auxiliary_only": formula_auxiliary_only,
        "formula_dominance_risk": formula_dominance_risk,
        "sibling_contamination_risk": sibling_contamination_risk,
        "coverage_score": round(float(coverage_score), 6),
        "density_score": round(float(density_score), 6),
        "source_order_preserved": True,
        "route": route,
        "insufficient_reasons": [reason for reason in REQUIRED_INSUFFICIENT_REASONS if reason in set(insufficient_reasons)],
    }


def compose_evidence_pack(
    *,
    kc_row: Mapping[str, Any],
    step5_row: Optional[Mapping[str, Any]],
    sentence_context_index: Mapping[str, Any] | None,
    cfg: Mapping[str, Any] | None = None,
    source_manifests: Mapping[str, str] | None = None,
) -> Dict[str, Any]:
    composition_cfg = _composition_cfg(cfg)
    evidence_rows = list((step5_row or {}).get("evidence") or [])
    doc_rank_by_doc_id: Dict[str, int] = {}
    normalized_candidates: List[Dict[str, Any]] = []
    max_candidates_considered = int(composition_cfg["max_candidates_considered_per_kc"])
    for source_candidate_index, evidence_row in enumerate(evidence_rows[:max_candidates_considered]):
        if not isinstance(evidence_row, Mapping):
            continue
        doc_id = str(evidence_row.get("doc_id") or "")
        if doc_id not in doc_rank_by_doc_id:
            doc_rank_by_doc_id[doc_id] = len(doc_rank_by_doc_id)
        normalized_candidates.append(
            _candidate_view(
                kc_row,
                evidence_row,
                source_candidate_index=source_candidate_index,
                doc_rank=doc_rank_by_doc_id[doc_id],
            )
        )
    deduped: Dict[Tuple[str, str], Dict[str, Any]] = {}
    duplicates: Dict[str, str] = {}
    for candidate in normalized_candidates:
        key = (str(candidate.get("doc_id") or ""), match_normalize(str(candidate.get("text") or "")))
        current = deduped.get(key)
        if current is None or float(candidate.get("alignment_score") or 0.0) > float(current.get("alignment_score") or 0.0):
            if current is not None:
                duplicates[str(current.get("candidate_id") or "")] = "duplicate_text_superseded"
            deduped[key] = candidate
        else:
            duplicates[str(candidate.get("candidate_id") or "")] = "duplicate_text"
    candidates = list(deduped.values())

    selected_ids: set[str] = set()
    slots: Dict[str, List[Dict[str, Any]]] = {role: [] for role in EVIDENCE_PACK_ROLES}
    definition_items, definition_scores = _select_slot(
        "definition_kernel",
        candidates,
        limit=int(composition_cfg["max_definition_kernel"]),
        min_score=float(composition_cfg["min_definition_score"]),
        score_fn=_definition_score,
        allow_formula_primary=False,
        exclude_ids=selected_ids,
    )
    slots["definition_kernel"] = definition_items

    explanatory_items, explanatory_scores = _select_slot(
        "explanatory_gloss",
        candidates,
        limit=int(composition_cfg["max_explanatory_gloss"]),
        min_score=float(composition_cfg["min_explanatory_score"]),
        score_fn=_explanatory_score,
        exclude_ids=selected_ids,
    )
    slots["explanatory_gloss"] = explanatory_items

    formula_items, formula_scores = _select_slot(
        "formula_notation",
        candidates,
        limit=int(composition_cfg["max_formula_notation"]),
        min_score=float(composition_cfg["min_formula_score"]),
        score_fn=_formula_score,
        exclude_ids=selected_ids,
    )
    slots["formula_notation"] = formula_items

    scope_items, scope_scores = _select_slot(
        "scope_condition",
        candidates,
        limit=int(composition_cfg["max_scope_condition"]),
        min_score=float(composition_cfg["min_scope_score"]),
        score_fn=_scope_score,
        exclude_ids=selected_ids,
    )
    slots["scope_condition"] = scope_items

    example_items, example_scores = _select_slot(
        "example_or_procedure",
        candidates,
        limit=int(composition_cfg["max_example_or_procedure"]),
        min_score=float(composition_cfg["min_example_score"]),
        score_fn=_example_score,
        exclude_ids=selected_ids,
    )
    slots["example_or_procedure"] = example_items

    sibling_items, sibling_scores = _select_slot(
        "sibling_contrast",
        candidates,
        limit=int(composition_cfg["max_sibling_contrast"]),
        min_score=float(composition_cfg["min_sibling_score"]),
        score_fn=_sibling_score,
        exclude_ids=selected_ids,
    )
    slots["sibling_contrast"] = sibling_items

    if not slots["definition_kernel"]:
        formula_candidates = sorted(
            candidates,
            key=lambda candidate: (-float(_formula_score(candidate)), _source_order_key(candidate)),
        )
        for candidate in formula_candidates:
            candidate_id = str(candidate.get("candidate_id") or "")
            if not candidate_id:
                continue
            if not bool(candidate.get("formula_like", False)):
                continue
            if float(_formula_score(candidate)) < float(composition_cfg["min_formula_score"]):
                continue
            promoted = _build_slot_item(
                candidate,
                role="definition_kernel",
                reason_selected="promoted_formula_primary_without_natural_language_anchor",
                risk_flags=[*_candidate_risk_flags(candidate), "formula_primary_candidate"],
            )
            slots["definition_kernel"] = [promoted]
            if not _slot_membership(slots["formula_notation"], candidate_id):
                slots["formula_notation"].append(
                    _build_slot_item(
                        candidate,
                        role="formula_notation",
                        reason_selected="selected_as_formula_notation",
                        risk_flags=_candidate_risk_flags(candidate),
                    )
                )
            selected_ids.add(candidate_id)
            break

    context_items: List[Dict[str, Any]] = []
    for slot_name in ("definition_kernel", "explanatory_gloss"):
        for slot_item in slots.get(slot_name) or []:
            source_candidate_id = str(slot_item.get("source_candidate_id") or "")
            source_candidate = next(
                (candidate for candidate in candidates if str(candidate.get("candidate_id") or "") == source_candidate_id),
                None,
            )
            if source_candidate is None:
                continue
            if not (
                bool(source_candidate.get("fragmentary", False))
                or bool(source_candidate.get("context_completion_available", False))
            ):
                continue
            completion_item, _ = _context_completion_item(
                source_candidate,
                sentence_context_index=sentence_context_index,
                cfg=cfg or {},
            )
            if completion_item is None:
                continue
            context_items.append(completion_item)
            if len(context_items) >= int(composition_cfg["max_context_completion_items"]):
                break
        if len(context_items) >= int(composition_cfg["max_context_completion_items"]):
            break
    slots["context_completion"] = context_items[: int(composition_cfg["max_context_completion"])]

    for role in EVIDENCE_PACK_ROLES:
        slots[role].sort(key=_source_order_key)

    ordered_pack = _merge_ordered_pack_items(slots, cfg or {})
    pack_quality = _pack_quality(
        candidates=candidates,
        slots=slots,
        ordered_pack=ordered_pack,
        cfg=cfg or {},
    )

    dropped_candidate_ids: List[str] = []
    drop_reasons: Dict[str, str] = dict(duplicates)
    selected_source_candidate_ids = set(_selected_candidate_ids(slots))
    for candidate in candidates:
        candidate_id = str(candidate.get("candidate_id") or "")
        if not candidate_id:
            continue
        if candidate_id in selected_source_candidate_ids:
            continue
        dropped_candidate_ids.append(candidate_id)
        if candidate_id in drop_reasons:
            continue
        if bool(candidate.get("sibling_bias", False)):
            drop_reasons[candidate_id] = "sibling_contamination_risk"
        elif bool(candidate.get("formula_like", False)):
            drop_reasons[candidate_id] = "formula_auxiliary_not_selected"
        elif bool(candidate.get("procedure_like", False)) or bool(candidate.get("example_like", False)):
            drop_reasons[candidate_id] = "example_or_procedure_only"
        elif not bool(candidate.get("source_provenance_available", False)):
            drop_reasons[candidate_id] = "source_provenance_missing"
        else:
            drop_reasons[candidate_id] = "lower_priority_support"

    topic_path_labels = _topic_path_labels(kc_row)
    topic_path_ids = _topic_path_ids(kc_row, topic_path_labels)
    parent_topic_id = _parent_topic_id(kc_row, topic_path_ids)
    parent_topic_label = _parent_topic_label(topic_path_labels)

    return {
        "kc_id": str(kc_row.get("kc_id") or (step5_row or {}).get("kc_id") or ""),
        "canonical_name": _as_text(kc_row.get("canonical_name") or (step5_row or {}).get("canonical_name")),
        "topic_path_ids": topic_path_ids,
        "topic_path_labels": topic_path_labels,
        "parent_topic_id": parent_topic_id,
        "parent_topic_label": parent_topic_label,
        "pack_version": EVIDENCE_PACK_CONTRACT_VERSION,
        "source_manifests": {
            "step5_3_set_manifest": str((source_manifests or {}).get("step5_3_set_manifest") or ""),
            "step4_5_sentence_overlay_manifest": str((source_manifests or {}).get("step4_5_sentence_overlay_manifest") or ""),
        },
        "slots": slots,
        "ordered_pack_for_drafting": ordered_pack,
        "pack_quality": pack_quality,
        "provenance_sidecar": {
            "selected_candidate_ids": _selected_candidate_ids(slots),
            "dropped_candidate_ids": unique_preserve_order(dropped_candidate_ids),
            "drop_reasons": dict(sorted(drop_reasons.items())),
            "all_span_ids": _all_span_ids(slots),
            "all_source_refs": _all_source_refs(slots),
        },
        "step5_3_support_pack_summary": dict((step5_row or {}).get("support_pack_summary") or {}),
        "step5_3_review_queue_aux": dict((step5_row or {}).get("review_queue_aux") or {}),
    }


def compose_evidence_packs(
    *,
    kc_rows: Sequence[Mapping[str, Any]],
    step5_rows_by_kc: Mapping[str, Mapping[str, Any]],
    sentence_context_index: Mapping[str, Any] | None = None,
    cfg: Mapping[str, Any] | None = None,
    source_manifests: Mapping[str, str] | None = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    packs: List[Dict[str, Any]] = []
    route_counter: Counter[str] = Counter()
    formula_risk_counter: Counter[str] = Counter()
    contamination_risk_counter: Counter[str] = Counter()
    insufficient_reason_counter: Counter[str] = Counter()
    definition_anchor_present_count = 0
    definition_anchor_natural_language_count = 0
    context_completion_used_count = 0
    coverage_scores: List[float] = []
    density_scores: List[float] = []

    for kc_row in kc_rows:
        kc_id = str(kc_row.get("kc_id") or "")
        pack = compose_evidence_pack(
            kc_row=kc_row,
            step5_row=step5_rows_by_kc.get(kc_id),
            sentence_context_index=sentence_context_index,
            cfg=cfg,
            source_manifests=source_manifests,
        )
        packs.append(pack)
        quality = dict(pack.get("pack_quality") or {})
        route_counter[str(quality.get("route") or "")] += 1
        formula_risk_counter[str(quality.get("formula_dominance_risk") or "")] += 1
        contamination_risk_counter[str(quality.get("sibling_contamination_risk") or "")] += 1
        if bool(quality.get("definition_anchor_present", False)):
            definition_anchor_present_count += 1
        if bool(quality.get("definition_anchor_natural_language", False)):
            definition_anchor_natural_language_count += 1
        if bool(quality.get("context_completion_used", False)):
            context_completion_used_count += 1
        coverage_scores.append(float(quality.get("coverage_score") or 0.0))
        density_scores.append(float(quality.get("density_score") or 0.0))
        for reason in quality.get("insufficient_reasons") or []:
            insufficient_reason_counter[str(reason)] += 1

    packs.sort(key=lambda item: str(item.get("kc_id") or ""))
    total_kcs = len(packs)
    stats = {
        "pack_version": EVIDENCE_PACK_CONTRACT_VERSION,
        "total_kcs": total_kcs,
        "route_breakdown": dict(sorted(route_counter.items())),
        "formula_dominance_risk_breakdown": dict(sorted(formula_risk_counter.items())),
        "sibling_contamination_risk_breakdown": dict(sorted(contamination_risk_counter.items())),
        "definition_anchor_present_count": definition_anchor_present_count,
        "definition_anchor_natural_language_count": definition_anchor_natural_language_count,
        "context_completion_used_count": context_completion_used_count,
        "insufficient_reason_breakdown": dict(sorted(insufficient_reason_counter.items())),
        "average_coverage_score": round(sum(coverage_scores) / total_kcs, 6) if total_kcs else 0.0,
        "average_density_score": round(sum(density_scores) / total_kcs, 6) if total_kcs else 0.0,
    }
    return packs, stats
