from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass
import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from kc_l.retrieval_windowing.semantic import match_normalize, normalize_ws, tokenize, unique_preserve_order


SOURCE_SURFACE_FALLBACK = "source_surface_fallback"
DEFAULT_DYNAMIC_BROAD_TOKEN_MIN_DOC_FREQUENCY = 12
PAREN_CONTENT_RE = re.compile(r"\(([^()]+)\)")
PROMPT_LIKE_RE = re.compile(
    r"^(?:describe|explain|compare|discuss|consider|identify|list|state|suppose|show|prove|find)\b|"
    r"^(?:exercise|question)\b|"
    r"^problem\s*(?:\d+|[ivxlcdm]+)?\s*[:.)-]"
)
FORMULA_RE = re.compile(
    r"(?:\\(?:sum|frac|sqrt|log|begin|end|mathbb|mathbf|operatorname)\b|"
    r"\b(?:argmax|argmin)\b|[∑Σ=<>≤≥≈]|"
    r"[A-Za-z][A-Za-z0-9_]*\s*=\s*[^=])"
)
CAPTION_RE = re.compile(r"^(?:figure|fig\.|table|algorithm|listing|chart)\b")
FRAGMENT_PREFIX_RE = re.compile(r"^(?:and|or|but|because|while|where|when|if|then|thus|therefore|however|for|to)\b")
TRAILING_FRAGMENT_RE = re.compile(r"(?:[,;:]|(?:\b(?:and|or|but|because|while|where|when|if|then)\s*))$")
RELATION_RE = re.compile(r"\b(?:is|are|was|were|refers to|defined as|known as|called|means|denotes|describes)\b")
SCOPE_RE = re.compile(
    r"\b(?:occurs when|arises when|happens when|during|within|stage of|phase of|part of|"
    r"used for|applies to|belongs to|consists of|contains|includes|comprises|"
    r"collection of|group of|set of|leads to|results in)\b"
)
GENERIC_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "if",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "this",
    "to",
    "with",
}
GENERIC_SUFFIX_TOKENS = {
    "algorithm",
    "approach",
    "concept",
    "definition",
    "measure",
    "method",
    "metric",
    "overview",
    "phase",
    "problem",
}
SURFACE_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("text", "text_norm"),
    ("source_block", "source_block_norm"),
    ("heading", "heading_norm"),
    ("context", "context_norm"),
)
SURFACE_PRIORITY_EXACT = {"text": 4.0, "source_block": 3.5, "heading": 2.75, "context": 2.5}
SURFACE_PRIORITY_TOKEN = {"text": 3.35, "source_block": 3.0}
SURFACE_PRIORITY_HEAD = {"text": 2.85, "source_block": 2.55, "heading": 2.2, "context": 1.9}
TERM_PRIORITY = {"canonical": 2.0, "alias": 1.75, "acronym": 1.5, "canonical_head": 1.4, "alias_head": 1.2}
TIER_PRIORITY = {"exact_surface": 0, "target_token": 1, "definition_head": 2, "branch_local_heading": 3}


@dataclass(frozen=True)
class SourceSurfaceFallbackConfig:
    enabled: bool = False
    max_fallback_per_kc: int = 8
    min_score: float = 4.0
    require_surface_match: bool = True
    require_hierarchy_compatibility: bool = True
    dynamic_broad_token_min_doc_frequency: int = DEFAULT_DYNAMIC_BROAD_TOKEN_MIN_DOC_FREQUENCY
    allow_acronym_surface_match: bool = True
    reject_prompt_like: bool = True
    reject_fragmentary: bool = True
    reject_formula_only_without_surface: bool = True


@dataclass(frozen=True)
class SurfaceTerm:
    raw: str
    normalized: str
    kind: str
    tokens: Tuple[str, ...]
    token_set: frozenset[str]
    is_short_form: bool


@dataclass(frozen=True)
class Profile:
    kc_id: str
    canonical_name: str
    knowledge_unit_type: str
    aliases: Tuple[str, ...]
    topic_path_ids: Tuple[str, ...]
    topic_path_labels: Tuple[str, ...]
    parent_topic_id: str
    parent_topic_label: str
    target_terms: Tuple[SurfaceTerm, ...]
    target_tokens: Tuple[str, ...]
    target_token_set: frozenset[str]
    filtered_target_tokens: Tuple[str, ...]
    filtered_target_token_set: frozenset[str]
    head_terms: Tuple[SurfaceTerm, ...]
    head_token_set: frozenset[str]
    branch_tokens: Tuple[str, ...]
    branch_token_set: frozenset[str]
    retrieval_policy_plan: Mapping[str, Any]


def fallback_config_from_mapping(raw: Mapping[str, Any] | SourceSurfaceFallbackConfig | None) -> SourceSurfaceFallbackConfig:
    if isinstance(raw, SourceSurfaceFallbackConfig):
        return raw
    cfg = dict(raw or {})
    return SourceSurfaceFallbackConfig(
        enabled=bool(cfg.get("enabled", False)),
        max_fallback_per_kc=max(0, int(cfg.get("max_fallback_per_kc", 8) or 0)),
        min_score=float(cfg.get("min_score", 4.0) or 0.0),
        require_surface_match=bool(cfg.get("require_surface_match", True)),
        require_hierarchy_compatibility=bool(cfg.get("require_hierarchy_compatibility", True)),
        dynamic_broad_token_min_doc_frequency=max(
            1,
            int(cfg.get("dynamic_broad_token_min_doc_frequency", DEFAULT_DYNAMIC_BROAD_TOKEN_MIN_DOC_FREQUENCY) or 1),
        ),
        allow_acronym_surface_match=bool(cfg.get("allow_acronym_surface_match", True)),
        reject_prompt_like=bool(cfg.get("reject_prompt_like", True)),
        reject_fragmentary=bool(cfg.get("reject_fragmentary", True)),
        reject_formula_only_without_surface=bool(cfg.get("reject_formula_only_without_surface", True)),
    )


def _as_text(value: Any) -> str:
    return normalize_ws(str(value or ""))


def _as_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except Exception:
        return None


def _as_str_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        text = _as_text(item)
        if text:
            out.append(text)
    return out


def _canonicalize_token(token: str) -> str:
    lowered = str(token or "").lower()
    if len(lowered) > 4 and lowered.endswith("ies"):
        return lowered[:-3] + "y"
    if len(lowered) > 4 and lowered.endswith("s") and not lowered.endswith(("ss", "us", "is", "es")):
        return lowered[:-1]
    return lowered


def _token_sequence(text: str, *, min_len: int) -> List[str]:
    return unique_preserve_order(_canonicalize_token(token) for token in tokenize(match_normalize(text), min_len=min_len))


def _content_tokens(text: str, *, min_len: int = 2) -> List[str]:
    return [token for token in _token_sequence(text, min_len=min_len) if token and token not in GENERIC_STOPWORDS]


def _unique_tokens(parts: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for part in parts:
        for token in _content_tokens(part, min_len=2):
            if token in seen:
                continue
            seen.add(token)
            out.append(token)
    return out


def _parenthetical_surface_terms(raw_text: str) -> List[str]:
    out: List[str] = []
    for match in PAREN_CONTENT_RE.finditer(str(raw_text or "")):
        text = normalize_ws(match.group(1))
        if not text:
            continue
        token_count = len(_token_sequence(text, min_len=1))
        if token_count == 0:
            continue
        if len(text) <= 24 or token_count <= 3:
            out.append(text)
    return unique_preserve_order(out)


def _surface_terms(canonical_name: str, aliases: Sequence[str], *, allow_acronym_surface_match: bool) -> List[SurfaceTerm]:
    raw_terms: List[Tuple[str, str]] = []
    canonical = _as_text(canonical_name)
    if canonical:
        raw_terms.append((canonical, "canonical"))
    for alias in aliases:
        text = _as_text(alias)
        if text:
            raw_terms.append((text, "alias"))
    if allow_acronym_surface_match:
        for text, origin_kind in list(raw_terms):
            for candidate in _parenthetical_surface_terms(text):
                raw_terms.append((candidate, "acronym" if len(candidate) <= 12 else origin_kind))
    terms: List[SurfaceTerm] = []
    seen: set[Tuple[str, str]] = set()
    for raw, kind in raw_terms:
        normalized = match_normalize(raw)
        tokens = tuple(_token_sequence(raw, min_len=1))
        if not normalized or not tokens:
            continue
        key = (normalized, kind)
        if key in seen:
            continue
        seen.add(key)
        is_short_form = len(tokens) == 1 and len(tokens[0]) <= 12
        terms.append(
            SurfaceTerm(
                raw=raw,
                normalized=normalized,
                kind=kind,
                tokens=tokens,
                token_set=frozenset(tokens),
                is_short_form=is_short_form,
            )
        )
    return terms


def _strip_generic_suffix_tokens(tokens: Sequence[str]) -> Tuple[str, ...]:
    trimmed = list(token for token in tokens if token)
    while len(trimmed) > 1 and trimmed[-1] in GENERIC_SUFFIX_TOKENS:
        trimmed.pop()
    return tuple(trimmed)


def _head_surface_terms(target_terms: Sequence[SurfaceTerm]) -> List[SurfaceTerm]:
    out: List[SurfaceTerm] = []
    seen: set[Tuple[str, str]] = set()
    for term in target_terms:
        stripped_tokens = _strip_generic_suffix_tokens(term.tokens)
        if not stripped_tokens or stripped_tokens == term.tokens:
            continue
        kind = "canonical_head" if term.kind == "canonical" else "alias_head"
        normalized = " ".join(stripped_tokens)
        key = (normalized, kind)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            SurfaceTerm(
                raw=normalized,
                normalized=normalized,
                kind=kind,
                tokens=stripped_tokens,
                token_set=frozenset(stripped_tokens),
                is_short_form=len(stripped_tokens) == 1 and len(stripped_tokens[0]) <= 12,
            )
        )
    return out


def _policy_head_terms(policy_plan: Mapping[str, Any]) -> List[SurfaceTerm]:
    out: List[SurfaceTerm] = []
    seen: set[str] = set()
    for raw in _as_str_list(policy_plan.get("concept_head_terms")):
        tokens = tuple(_token_sequence(raw, min_len=1))
        normalized = match_normalize(raw)
        if not tokens or not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(
            SurfaceTerm(
                raw=raw,
                normalized=normalized,
                kind="policy_concept_head",
                tokens=tokens,
                token_set=frozenset(tokens),
                is_short_form=len(tokens) == 1 and len(tokens[0]) <= 12,
            )
        )
    return out


def compute_dynamic_broad_tokens(
    kc_context_rows: Sequence[Mapping[str, Any]],
    *,
    min_doc_frequency: int,
) -> List[str]:
    token_doc_frequency: Counter[str] = Counter()
    token_parent_labels: Dict[str, set[str]] = defaultdict(set)
    for row in kc_context_rows:
        parent_topic_label = match_normalize(_as_text(row.get("parent_topic_label")) or _as_text(row.get("parent_topic")))
        pieces = [
            _as_text(row.get("canonical_name")),
            *_as_str_list(row.get("aliases")),
            *_as_str_list(row.get("topic_path_labels")),
        ]
        tokens = set(_unique_tokens(pieces))
        for token in tokens:
            token_doc_frequency[token] += 1
            if parent_topic_label:
                token_parent_labels[token].add(parent_topic_label)
    broad = [
        token
        for token, count in token_doc_frequency.items()
        if count >= int(min_doc_frequency) and len(token_parent_labels.get(token) or set()) >= 2
    ]
    return sorted(broad)


def _build_profile(
    row: Mapping[str, Any],
    *,
    broad_tokens: set[str],
    allow_acronym_surface_match: bool,
) -> Profile | None:
    kc_id = _as_text(row.get("kc_id"))
    canonical_name = _as_text(row.get("canonical_name"))
    if not kc_id or not canonical_name:
        return None
    aliases = tuple(_as_str_list(row.get("aliases")))
    knowledge_unit_type = _as_text(row.get("knowledge_unit_type") or row.get("node_type") or "kc").lower() or "kc"
    topic_path_ids = tuple(_as_str_list(row.get("topic_path_ids")))
    topic_path_labels = tuple(_as_str_list(row.get("topic_path_labels")))
    parent_topic_id = _as_text(row.get("parent_topic_id"))
    parent_topic_label = _as_text(row.get("parent_topic_label"))
    target_terms = tuple(_surface_terms(canonical_name, aliases, allow_acronym_surface_match=allow_acronym_surface_match))
    target_tokens = tuple(unique_preserve_order(token for term in target_terms for token in term.tokens if len(token) >= 2))
    target_token_set = frozenset(target_tokens)
    filtered_target_tokens = tuple(
        token
        for token in target_tokens
        if token not in broad_tokens and token not in GENERIC_SUFFIX_TOKENS
    )
    if not filtered_target_tokens and target_tokens:
        filtered_target_tokens = tuple(
            token for token in target_tokens if token not in GENERIC_SUFFIX_TOKENS
        ) or tuple(target_tokens[:1])
    policy_plan = row.get("step5x_retrieval_policy_plan") if isinstance(row.get("step5x_retrieval_policy_plan"), Mapping) else {}
    head_terms = tuple([*_head_surface_terms(target_terms), *_policy_head_terms(policy_plan)])
    head_token_set = frozenset(
        token
        for term in head_terms
        for token in term.tokens
        if token not in broad_tokens and token not in GENERIC_SUFFIX_TOKENS
    )
    if not head_token_set and head_terms:
        head_token_set = frozenset(token for term in head_terms for token in term.tokens if token not in GENERIC_SUFFIX_TOKENS)
    if not head_token_set and head_terms:
        head_token_set = frozenset(token for term in head_terms for token in term.tokens)
    raw_branch_tokens = _unique_tokens(topic_path_labels)
    branch_tokens = tuple(
        token
        for token in raw_branch_tokens
        if token not in broad_tokens and token not in target_token_set and token not in GENERIC_SUFFIX_TOKENS
    )
    return Profile(
        kc_id=kc_id,
        canonical_name=canonical_name,
        knowledge_unit_type=knowledge_unit_type,
        aliases=aliases,
        topic_path_ids=topic_path_ids,
        topic_path_labels=topic_path_labels,
        parent_topic_id=parent_topic_id,
        parent_topic_label=parent_topic_label,
        target_terms=target_terms,
        target_tokens=target_tokens,
        target_token_set=target_token_set,
        filtered_target_tokens=filtered_target_tokens,
        filtered_target_token_set=frozenset(filtered_target_tokens),
        head_terms=head_terms,
        head_token_set=head_token_set,
        branch_tokens=branch_tokens,
        branch_token_set=frozenset(branch_tokens),
        retrieval_policy_plan=policy_plan,
    )


def _boundary_phrase_hit(surface_norm: str, phrase_norm: str) -> bool:
    if not surface_norm or not phrase_norm:
        return False
    start = surface_norm.find(phrase_norm)
    while start >= 0:
        end = start + len(phrase_norm)
        before = surface_norm[start - 1] if start > 0 else " "
        after = surface_norm[end] if end < len(surface_norm) else " "
        if not before.isalnum() and not after.isalnum():
            return True
        start = surface_norm.find(phrase_norm, start + 1)
    return False


def _surface_views(sentence_row: Mapping[str, Any]) -> Dict[str, Any]:
    text = _as_text(sentence_row.get("sentence_text") or sentence_row.get("text") or sentence_row.get("snippet"))
    source_block_text = _as_text(sentence_row.get("source_block_text") or text)
    patch_heading = _as_text(sentence_row.get("patch_heading"))
    page_heading = _as_text(sentence_row.get("page_heading_norm"))
    heading_text = patch_heading or page_heading
    context_text = page_heading if page_heading and page_heading != patch_heading else ""
    return {
        "text": text,
        "source_block_text": source_block_text,
        "heading_text": heading_text,
        "context_text": context_text,
        "text_norm": match_normalize(text),
        "source_block_norm": match_normalize(source_block_text),
        "heading_norm": match_normalize(heading_text),
        "context_norm": match_normalize(context_text),
        "text_tokens": _content_tokens(text, min_len=2),
        "source_block_tokens": _content_tokens(source_block_text, min_len=2),
        "heading_tokens": _content_tokens(heading_text, min_len=2),
        "context_tokens": _content_tokens(context_text, min_len=2),
    }


def _collect_exact_candidates(profile: Profile, views: Mapping[str, Any]) -> List[Dict[str, Any]]:
    matches: List[Dict[str, Any]] = []
    for surface_name, norm_key in SURFACE_FIELDS:
        surface_norm = str(views.get(norm_key) or "")
        for term in profile.target_terms:
            if not _boundary_phrase_hit(surface_norm, term.normalized):
                continue
            matches.append(
                {
                    "tier": "exact_surface",
                    "surface_name": surface_name,
                    "surface_match_type": f"exact_{term.kind}_{surface_name}",
                    "matched_surface_terms": [term.raw],
                    "matched_target_tokens": list(term.tokens),
                    "term_kind": term.kind,
                    "base_score": SURFACE_PRIORITY_EXACT[surface_name] + TERM_PRIORITY.get(term.kind, 1.25),
                    "anchor_strength": "exact_phrase",
                    "allow_strong_surface_bypass": True,
                }
            )
    return matches


def _collect_token_candidates(profile: Profile, views: Mapping[str, Any]) -> List[Dict[str, Any]]:
    if len(profile.filtered_target_tokens) < 2:
        return []
    candidates: List[Dict[str, Any]] = []
    for surface_name in ("text", "source_block"):
        surface_tokens = set(views.get(f"{surface_name}_tokens") or [])
        matched_tokens = [token for token in profile.filtered_target_tokens if token in surface_tokens]
        if len(matched_tokens) < 2:
            continue
        full_cover = len(matched_tokens) == len(profile.filtered_target_tokens)
        candidates.append(
            {
                "tier": "target_token",
                "surface_name": surface_name,
                "surface_match_type": f"target_token_overlap_{surface_name}",
                "matched_surface_terms": [],
                "matched_target_tokens": matched_tokens,
                "term_kind": "target_token",
                "base_score": SURFACE_PRIORITY_TOKEN[surface_name] + (0.7 * len(matched_tokens)) + (0.35 if full_cover else 0.0),
                "anchor_strength": "multi_token",
                "allow_strong_surface_bypass": False,
            }
        )
    return candidates


def _collect_head_candidates(profile: Profile, views: Mapping[str, Any]) -> List[Dict[str, Any]]:
    if not profile.head_terms:
        return []
    candidates: List[Dict[str, Any]] = []
    for surface_name, norm_key in SURFACE_FIELDS:
        surface_norm = str(views.get(norm_key) or "")
        surface_tokens = set(views.get(f"{surface_name}_tokens") or [])
        for term in profile.head_terms:
            exact = _boundary_phrase_hit(surface_norm, term.normalized)
            matched_tokens = list(term.tokens) if exact else [token for token in term.tokens if token in surface_tokens]
            if not matched_tokens:
                continue
            tier = "branch_local_heading" if surface_name in {"heading", "context"} else "definition_head"
            match_kind = "head_exact" if exact else "head_token"
            candidates.append(
                {
                    "tier": tier,
                    "surface_name": surface_name,
                    "surface_match_type": f"{match_kind}_{surface_name}",
                    "matched_surface_terms": [term.raw] if exact else [],
                    "matched_target_tokens": matched_tokens,
                    "term_kind": term.kind,
                    "base_score": SURFACE_PRIORITY_HEAD[surface_name]
                    + (1.05 if exact else 0.7)
                    + (0.25 * max(len(matched_tokens) - 1, 0)),
                    "anchor_strength": "head_phrase" if exact else "head_token",
                    "allow_strong_surface_bypass": False,
                }
            )
    return candidates


def _hierarchy_compatibility(
    profile: Profile,
    views: Mapping[str, Any],
    *,
    surface_name: str,
    allow_strong_surface_bypass: bool,
) -> Dict[str, Any]:
    branch_tokens = set(profile.branch_token_set)
    heading_tokens = set(views.get("heading_tokens") or [])
    local_tokens = set(views.get("source_block_tokens") or []) | set(views.get("context_tokens") or [])
    heading_hits = sorted(branch_tokens & heading_tokens)
    local_hits = sorted(branch_tokens & local_tokens)
    heading_specific_tokens = heading_tokens - set(profile.target_token_set) - set(profile.head_token_set) - set(heading_hits)
    strong_surface_anchor = surface_name in {"text", "source_block"}
    contradictory_heading = bool(len(heading_specific_tokens) >= 2 and not heading_hits)

    if heading_hits:
        match_type = "heading_branch_overlap"
        compatible = True
    elif local_hits:
        match_type = "local_context_branch_overlap"
        compatible = True
    elif strong_surface_anchor and not branch_tokens and not contradictory_heading:
        match_type = "surface_anchor_no_branch_tokens"
        compatible = True
    elif allow_strong_surface_bypass and strong_surface_anchor and not contradictory_heading:
        match_type = "strong_surface_no_heading_contradiction"
        compatible = True
    else:
        match_type = "hierarchy_mismatch"
        compatible = False

    return {
        "compatible": compatible,
        "match_type": match_type,
        "heading_hits": heading_hits,
        "local_hits": local_hits,
        "heading_specific_tokens": sorted(heading_specific_tokens),
        "contradictory_heading": contradictory_heading,
        "usable_branch_tokens": bool(branch_tokens),
    }


def _looks_prompt_like(views: Mapping[str, Any]) -> bool:
    text = str(views.get("text") or "")
    heading_text = str(views.get("heading_text") or "")
    return bool(
        PROMPT_LIKE_RE.search(text.lower())
        or PROMPT_LIKE_RE.search(heading_text.lower())
        or ("?" in text and len(text) < 220)
    )


def _looks_fragmentary(sentence_row: Mapping[str, Any], views: Mapping[str, Any]) -> bool:
    text = str(views.get("text") or "")
    lower = text.lower()
    if not lower:
        return True
    if len(lower) < 28:
        return True
    if FRAGMENT_PREFIX_RE.search(lower):
        return True
    if TRAILING_FRAGMENT_RE.search(lower):
        return True
    if bool(sentence_row.get("is_heading_like")) and len(text) < 80:
        return True
    return False


def _structural_flags(sentence_row: Mapping[str, Any], views: Mapping[str, Any]) -> Dict[str, Any]:
    text = str(views.get("text") or "")
    source_block_text = str(views.get("source_block_text") or "")
    heading_text = str(views.get("heading_text") or "")
    looks_formula_like = bool(sentence_row.get("is_formula_like")) or bool(FORMULA_RE.search(text) or FORMULA_RE.search(source_block_text))
    looks_caption_like = bool(CAPTION_RE.search(text.lower()) or CAPTION_RE.search(heading_text.lower()))
    looks_prompt_like = _looks_prompt_like(views)
    looks_fragmentary = _looks_fragmentary(sentence_row, views)
    return {
        "has_text": bool(text),
        "has_source_block_text": bool(source_block_text),
        "has_sentence_id": bool(_as_text(sentence_row.get("sentence_id"))),
        "has_patch_id": bool(_as_text(sentence_row.get("patch_id"))),
        "has_page_index": _as_int(sentence_row.get("page_index")) is not None,
        "looks_formula_like": looks_formula_like,
        "looks_caption_like": looks_caption_like,
        "looks_prompt_like": looks_prompt_like,
        "looks_fragmentary": looks_fragmentary,
    }


def _cue_signals(sentence_row: Mapping[str, Any], views: Mapping[str, Any]) -> Dict[str, Any]:
    combined_text = normalize_ws(f"{views.get('text') or ''} {views.get('source_block_text') or ''}")
    lowered = combined_text.lower()
    has_definition_flag = bool(sentence_row.get("is_definition_like"))
    relation_like = bool(has_definition_flag or RELATION_RE.search(lowered))
    scope_like = bool(SCOPE_RE.search(lowered))
    return {
        "has_definition_flag": has_definition_flag,
        "relation_like": relation_like,
        "scope_like": scope_like,
        "has_relation_or_scope": bool(relation_like or scope_like),
        "has_strong_relation_or_definition": bool(has_definition_flag or relation_like),
    }


def _formula_only_without_binding(
    views: Mapping[str, Any],
    structural_flags: Mapping[str, Any],
    *,
    candidate: Mapping[str, Any],
) -> bool:
    if not bool(structural_flags.get("looks_formula_like")):
        return False
    text = str(views.get("text") or "")
    alpha_tokens = [token for token in _token_sequence(text, min_len=2) if any(ch.isalpha() for ch in token)]
    has_text_binding = bool(candidate.get("surface_name") == "text" and candidate.get("matched_target_tokens"))
    return bool(len(alpha_tokens) <= 4 and not has_text_binding and not RELATION_RE.search(text.lower()))


def _candidate_cue_failure(candidate: Mapping[str, Any], cues: Mapping[str, Any]) -> str | None:
    tier = str(candidate.get("tier") or "")
    matched_token_count = len(candidate.get("matched_target_tokens") or [])
    if tier == "exact_surface":
        return None
    if tier == "target_token":
        return None if bool(cues.get("has_relation_or_scope")) else "token_match_without_relation_or_scope"
    if tier == "definition_head":
        if matched_token_count <= 1:
            return None if bool(cues.get("has_strong_relation_or_definition")) else "head_match_without_strong_relation"
        return None if bool(cues.get("has_relation_or_scope")) else "head_match_without_relation_or_scope"
    if tier == "branch_local_heading":
        if matched_token_count <= 1:
            return None if bool(cues.get("has_strong_relation_or_definition")) else "heading_head_match_without_strong_relation"
        return None if bool(cues.get("has_relation_or_scope")) else "heading_head_match_without_relation_or_scope"
    return None


def _candidate_context_failure(candidate: Mapping[str, Any], hierarchy: Mapping[str, Any]) -> str | None:
    tier = str(candidate.get("tier") or "")
    if tier == "exact_surface":
        return None

    # A strict hierarchy bypass is only assigned after a conservative binding
    # check has already accepted the local passage. In that case, do not let a
    # stale generic-heading contradiction reject the candidate afterward.
    if bool(hierarchy.get("strict_hierarchy_bypass")):
        return None

    if bool(hierarchy.get("contradictory_heading")):
        return "context_mismatch"
    return None




def _target_suffix_token_set(profile: Profile) -> set[str]:
    suffixes: set[str] = set()
    for term in profile.target_terms:
        stripped = _strip_generic_suffix_tokens(term.tokens)
        if stripped and stripped != term.tokens and len(term.tokens) > len(stripped):
            suffixes.update(term.tokens[len(stripped):])
    return suffixes


def _text_has_matched_anchor(views: Mapping[str, Any], candidate: Mapping[str, Any]) -> bool:
    text_norm = str(views.get("text_norm") or "")
    text_tokens = set(views.get("text_tokens") or [])

    for term in candidate.get("matched_surface_terms") or []:
        normalized = match_normalize(str(term or ""))
        if normalized and _boundary_phrase_hit(text_norm, normalized):
            return True

    matched_tokens = [str(t) for t in candidate.get("matched_target_tokens") or [] if str(t).strip()]
    if not matched_tokens:
        return False

    tier = str(candidate.get("tier") or "")
    if tier == "target_token":
        return all(token in text_tokens for token in matched_tokens)

    return any(token in text_tokens for token in matched_tokens)


def _source_block_only_anchor_failure(
    views: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> str | None:
    if str(candidate.get("surface_name") or "") != "source_block":
        return None

    source_block_text = str(views.get("source_block_text") or "")
    text = str(views.get("text") or "")
    if not source_block_text or source_block_text == text:
        return None

    if _text_has_matched_anchor(views, candidate):
        return None

    return "source_block_only_anchor_without_emitted_text_anchor"


def _has_strict_definition_subject_binding(token: str, text_norm: str) -> bool:
    token_re = re.escape(token)
    subject = rf"(?:a|an|the)?\s*{token_re}s?"

    # Conservative definition binding. This deliberately does not treat every
    # "token is/are ..." sequence as definitional, because passive or procedural
    # uses such as "each token is given..." and "items in the token are taken..."
    # are not definitions of the token.
    definitional_predicate = (
        r"(?:a|an|the|one|type|kind|form|collection|group|set|subset|class|"
        r"category|concept|defined|well\s+defined|not\s+well\s+defined|"
        r"imprecise|ambiguous|undefined)"
    )

    if re.search(rf"\b{subject}\s+(?:is|are|was|were)\s+{definitional_predicate}\b", text_norm):
        return True

    if re.search(
        rf"\b(?:definition|notion|concept|meaning)\s+of\s+{subject}\s+"
        rf"(?:is|are|was|were)\s+{definitional_predicate}\b",
        text_norm,
    ):
        return True

    if re.search(
        rf"\b{subject}\s+"
        rf"(?:means|denotes|represents|refers\s+to|consists\s+of|contains|includes|comprises)\b",
        text_norm,
    ):
        return True

    if re.search(rf"\b(?:defined\s+as|called|known\s+as)\s+{subject}\b", text_norm):
        return True

    return False


def _has_windowed_token_cue(token: str, text_norm: str, cue_pattern: str, *, window_words: int = 16) -> bool:
    token_re = re.escape(token)
    after = rf"\b{token_re}\b(?:\s+\w+){{0,{window_words}}}\s+\b(?:{cue_pattern})\b"
    before = rf"\b(?:{cue_pattern})\b(?:\s+\w+){{0,{window_words}}}\s+\b{token_re}\b"
    return bool(re.search(after, text_norm) or re.search(before, text_norm))




def _profile_context_anchor_tokens(profile: Profile | None) -> set[str]:
    """Return non-generic profile/context tokens usable as same-sense guards.

    This deliberately avoids domain-specific vocabulary. The tokens come only
    from the profile object that was already built from the KC/context row and
    the broader run-level context.
    """
    if profile is None:
        return set()

    generic = {
        "phase", "process", "stage", "step", "task", "procedure", "method",
        "model", "algorithm", "data", "value", "values", "problem", "example",
        "concept", "definition", "type", "types", "approach", "system",
        "learning", "learn", "training", "testing", "test", "set", "sets",
    }

    tokens: set[str] = set()

    # Be permissive about attribute names because Profile can evolve.
    candidate_attrs = [
        "broad_tokens",
        "parent_topic_tokens",
        "topic_tokens",
        "branch_tokens",
        "target_branch_tokens",
        "heading_specific_tokens",
        "context_tokens",
    ]

    for attr in candidate_attrs:
        value = getattr(profile, attr, None)
        if not value:
            continue
        if isinstance(value, str):
            values = [value]
        else:
            values = list(value)
        for item in values:
            tok = str(item or "").strip().lower()
            if len(tok) < 4:
                continue
            if tok in generic:
                continue
            tokens.add(tok)

    # Also inspect raw topic labels. These are not domain-specific constants:
    # they come from the KC profile. This is deliberately separate from
    # profile.branch_tokens because branch_tokens may have removed broad tokens.
    # For generic labels such as "Learning Phase", a broad parent/topic token can
    # still be the only useful same-sense anchor.
    raw_context_labels = []
    raw_context_labels.extend(list(getattr(profile, "topic_path_labels", ()) or ()))
    parent_label = getattr(profile, "parent_topic_label", "")
    if parent_label:
        raw_context_labels.append(parent_label)

    for label in raw_context_labels:
        for tok in _content_tokens(str(label or ""), min_len=2):
            tok = str(tok or "").strip().lower()
            if len(tok) < 4:
                continue
            if tok in generic:
                continue
            tokens.add(tok)

    # Also inspect term-like fields if present. This remains generic because it
    # reads the profile, not a course-specific list.
    for attr in ["branch_terms", "topic_terms", "parent_terms"]:
        value = getattr(profile, attr, None)
        if not value:
            continue
        for term in list(value):
            for tok in getattr(term, "tokens", []) or []:
                tok = str(tok or "").strip().lower()
                if len(tok) >= 4 and tok not in generic:
                    tokens.add(tok)

    return tokens
def _has_process_phase_passage_binding(token: str, views: Mapping[str, Any], profile: Profile | None = None) -> bool:
    text_norm = str(views.get("text_norm") or "")
    source_block_norm = str(views.get("source_block_norm") or "")
    text_tokens = set(views.get("text_tokens") or [])

    if token not in text_tokens:
        return False

    local_norm = normalize_ws(f"{text_norm} {source_block_norm}")

    process_cue = bool(
        re.search(r"\b(?:process|stage|phase|step|task|procedure|sequence)\b", local_norm)
    )
    naming_cue = bool(
        re.search(r"\b(?:known\s+as|called|described\s+as|referred\s+to\s+as|defined\s+as)\b", local_norm)
    )
    construction_cue = bool(
        re.search(
            r"\b(?:build|building|built|construct|constructing|constructed|create|creating|"
            r"created|train|training|trained|learn|learning|learned|estimate|estimating|"
            r"estimated|fit|fitting|fitted|induce|inducing|induced|derive|deriving|derived)\b",
            local_norm,
        )
    )
    input_output_cue = bool(
        re.search(r"\b(?:from|using|given|to|into|before|after|then)\b", local_norm)
    )
    profile_context_tokens = _profile_context_anchor_tokens(profile)
    local_tokens = (
        set(views.get("text_tokens") or [])
        | set(views.get("source_block_tokens") or [])
        | set(views.get("heading_tokens") or [])
        | set(views.get("context_tokens") or [])
    )
    profile_context_hit = bool(profile_context_tokens and (local_tokens & profile_context_tokens))

    # This bypass is intentionally strict because it overrides missing branch
    # evidence for single-head phase labels. A bare phrase such as
    # "learning process" is not enough. In addition to generic process and
    # construction cues, require at least one non-generic profile/context token
    # from the KC itself so that a generic phase label does not attach to an
    # unrelated curriculum branch.
    if not process_cue:
        return False
    if not construction_cue:
        return False
    if not profile_context_hit:
        return False
    return naming_cue and input_output_cue


def _single_head_binding_failure(
    profile: Profile,
    views: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> str | None:
    tier = str(candidate.get("tier") or "")
    if tier not in {"definition_head", "branch_local_heading"}:
        return None

    matched_tokens = [str(t) for t in candidate.get("matched_target_tokens") or [] if str(t).strip()]
    if len(matched_tokens) != 1:
        return None

    token = matched_tokens[0]
    text_norm = str(views.get("text_norm") or "")
    text_tokens = set(views.get("text_tokens") or [])

    if token not in text_tokens:
        return "single_head_token_not_in_emitted_text"

    suffixes = _target_suffix_token_set(profile)

    if "definition" in suffixes:
        if _has_strict_definition_subject_binding(token, text_norm):
            return None
        return "single_head_definition_without_strict_text_binding"

    if "phase" in suffixes:
        if _has_process_phase_passage_binding(token, views, profile):
            return None
        return "single_head_phase_without_process_binding"

    if "problem" in suffixes:
        if _has_windowed_token_cue(
            token,
            text_norm,
            r"problem|issue|occur|occurs|arise|arises|happen|happens|result|results|resulting|lead|leads|cause|causes|when",
            window_words=18,
        ):
            return None
        return "single_head_problem_without_problem_binding"

    if suffixes & {"method", "approach", "algorithm"}:
        if _has_windowed_token_cue(
            token,
            text_norm,
            r"method|approach|algorithm|procedure|process|used|uses|applies|construct|build|learn",
            window_words=16,
        ):
            return None
        return "single_head_method_without_process_binding"

    if suffixes & {"measure", "metric"}:
        if _has_windowed_token_cue(
            token,
            text_norm,
            r"measure|metric|score|computed|calculated|evaluates|quantifies|value",
            window_words=16,
        ):
            return None
        return "single_head_measure_without_measure_binding"

    if suffixes & {"concept", "overview"}:
        return "single_head_generic_suffix_too_weak"

    if _has_strict_definition_subject_binding(token, text_norm):
        return None

    return "single_head_without_strict_text_binding"


def _strict_single_head_hierarchy_bypass(
    profile: Profile,
    views: Mapping[str, Any],
    candidate: Mapping[str, Any],
    hierarchy: Mapping[str, Any],
) -> str:
    surface_name = str(candidate.get("surface_name") or "")
    if surface_name not in {"text", "source_block"}:
        return ""

    tier = str(candidate.get("tier") or "")
    matched_tokens = [str(t) for t in candidate.get("matched_target_tokens") or [] if str(t).strip()]
    if tier not in {"definition_head", "branch_local_heading"} or len(matched_tokens) != 1:
        return ""

    if surface_name == "source_block":
        # Source-block matches are only allowed to bypass missing hierarchy when
        # the emitted sentence itself contains the matched head token. This keeps
        # valid block-completed passages alive while preventing inherited block
        # context from anchoring unrelated short sentences.
        text_tokens = {str(t) for t in views.get("text_tokens") or [] if str(t).strip()}
        if not all(token in text_tokens for token in matched_tokens):
            return ""

    if _single_head_binding_failure(profile, views, candidate) is not None:
        return ""

    suffixes = _target_suffix_token_set(profile)
    heading_norm = str(views.get("heading_norm") or "")
    if re.search(r"\b(?:references|bibliography|exercise|exercises|question|questions|index|appendix)\b", heading_norm):
        return ""

    if "phase" in suffixes and _has_process_phase_passage_binding(matched_tokens[0], views, profile):
        return "strict_process_phase_binding"

    return ""


def _candidate_caution_reason(
    candidate: Mapping[str, Any],
    *,
    hierarchy: Mapping[str, Any],
    source_block_completion_used: bool,
    cues: Mapping[str, Any],
) -> str:
    if str(candidate.get("tier") or "") in {"definition_head", "branch_local_heading"} and len(candidate.get("matched_target_tokens") or []) == 1:
        return "single_head_token_anchor"
    if source_block_completion_used and not bool(cues.get("has_strong_relation_or_definition")):
        return "source_block_completion_without_strong_relation"
    if bool(hierarchy.get("contradictory_heading")):
        return "contradictory_heading"
    return ""


def _retrieval_intent_for_candidate(
    *,
    fallback_tier: str,
    surface_match_type: str,
    structural_flags: Mapping[str, Any],
    cues: Mapping[str, Any],
) -> str:
    if fallback_tier == "exact_surface":
        if "acronym" in surface_match_type:
            return "acronym_or_parenthetical_alias"
        if "canonical" in surface_match_type and surface_match_type.endswith("_text"):
            return "label_exact_surface"
        return "label_normalized_surface"
    if bool(structural_flags.get("looks_formula_like")):
        return "head_term_plus_metric_frame"
    if bool(cues.get("has_strong_relation_or_definition")):
        return "head_term_plus_definition_frame"
    if fallback_tier == "definition_head":
        return "head_term_plus_definition_frame"
    if fallback_tier == "branch_local_heading":
        return "heading_anchor_expansion"
    return "label_normalized_surface"


def _evidence_shape_match(structural_flags: Mapping[str, Any], cues: Mapping[str, Any]) -> str:
    if bool(structural_flags.get("looks_formula_like")):
        return "formula_or_metric"
    if bool(cues.get("has_strong_relation_or_definition")):
        return "definition_or_gloss"
    if bool(cues.get("scope_like")):
        return "scope_condition"
    return "context"


def _score_candidate(
    *,
    candidate: Mapping[str, Any],
    hierarchy: Mapping[str, Any],
    structural_flags: Mapping[str, Any],
    cues: Mapping[str, Any],
    source_block_completion_used: bool,
) -> Tuple[float, List[str]]:
    reasons = [
        f"tier:{candidate['tier']}",
        f"surface:{candidate['surface_name']}",
        f"match:{candidate['surface_match_type']}",
    ]
    score = float(candidate["base_score"])
    hierarchy_type = str(hierarchy.get("match_type") or "")
    if hierarchy_type == "heading_branch_overlap":
        score += 1.9
        reasons.append("hierarchy:heading_branch_overlap")
    elif hierarchy_type == "local_context_branch_overlap":
        score += 1.7
        reasons.append("hierarchy:local_context_branch_overlap")
    elif hierarchy_type == "strong_surface_no_heading_contradiction":
        score += 1.2
        reasons.append("hierarchy:strong_surface_no_heading_contradiction")
    elif hierarchy_type == "surface_anchor_no_branch_tokens":
        score += 0.85
        reasons.append("hierarchy:surface_anchor_no_branch_tokens")
    elif hierarchy_type == "strict_process_phase_binding":
        score += 1.35
        reasons.append("hierarchy:strict_process_phase_binding")
    if bool(cues.get("has_strong_relation_or_definition")):
        score += 0.8
        reasons.append("strong_relation_or_definition")
    elif bool(cues.get("has_relation_or_scope")):
        score += 0.45
        reasons.append("relation_or_scope")
    if source_block_completion_used:
        score += 0.25
        reasons.append("source_block_completion_used")
    if bool(structural_flags.get("looks_formula_like")):
        score -= 0.75
        reasons.append("formula_like_penalty")
    return score, reasons


def _raw_text_hash(text: str) -> str:
    return hashlib.sha256(match_normalize(text).encode("utf-8")).hexdigest()


def _dedupe_key(
    kc_id: str,
    *,
    sentence_id: str,
    block_id: str,
    doc_id: str,
    raw_text_hash: str,
) -> Tuple[str, str, str, str, str]:
    return (kc_id, sentence_id, block_id, doc_id, raw_text_hash)


def _candidate_sort_key(candidate: Mapping[str, Any]) -> Tuple[int, float, int, int, str]:
    tier = str(candidate.get("tier") or "")
    surface_name = str(candidate.get("surface_name") or "")
    return (
        TIER_PRIORITY.get(tier, 99),
        -float(candidate.get("base_score") or 0.0),
        0 if surface_name == "text" else 1,
        -len(candidate.get("matched_target_tokens") or []),
        str(candidate.get("surface_match_type") or ""),
    )


def build_source_surface_fallback_candidates(
    sentence_rows: Sequence[Mapping[str, Any]],
    *,
    selected_kc_contexts: Sequence[Mapping[str, Any]],
    registry_kc_contexts: Sequence[Mapping[str, Any]] | None = None,
    existing_candidate_rows: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any] | SourceSurfaceFallbackConfig | None = None,
    sentence_source_manifest: str,
    sentence_source_jsonl: str,
) -> Dict[str, Any]:
    cfg = fallback_config_from_mapping(config)
    if not cfg.enabled:
        return {
            "rows": [],
            "stats": {
                "enabled": False,
                "source_surface": SOURCE_SURFACE_FALLBACK,
                "sentence_source_manifest": sentence_source_manifest,
                "sentence_source_jsonl": sentence_source_jsonl,
                "candidate_rows_added": 0,
            },
        }

    broad_tokens = set(
        compute_dynamic_broad_tokens(
            list(registry_kc_contexts or selected_kc_contexts),
            min_doc_frequency=cfg.dynamic_broad_token_min_doc_frequency,
        )
    )
    profiles: List[Profile] = []
    for context_row in selected_kc_contexts:
        profile = _build_profile(
            context_row,
            broad_tokens=broad_tokens,
            allow_acronym_surface_match=cfg.allow_acronym_surface_match,
        )
        if profile is not None:
            profiles.append(profile)

    seen_keys: set[Tuple[str, str, str, str, str]] = set()
    for row in existing_candidate_rows:
        kc_id = _as_text(row.get("kc_id"))
        raw_text_hash = _as_text(row.get("raw_text_hash")) or _raw_text_hash(_as_text(row.get("text")))
        seen_keys.add(
            _dedupe_key(
                kc_id,
                sentence_id=_as_text(row.get("sentence_id")),
                block_id=_as_text(row.get("block_id")),
                doc_id=_as_text(row.get("doc_id")),
                raw_text_hash=raw_text_hash,
            )
        )

    candidates_by_kc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    rejected_counts: Counter[str] = Counter()
    surface_match_counter: Counter[str] = Counter()
    hierarchy_match_counter: Counter[str] = Counter()
    fallback_tier_counter: Counter[str] = Counter()
    dropped_duplicate_count = 0

    for source_row_index, sentence_row in enumerate(sentence_rows):
        views = _surface_views(sentence_row)
        structural_flags = _structural_flags(sentence_row, views)
        cues = _cue_signals(sentence_row, views)
        for profile in profiles:
            possible_candidates = [
                *_collect_exact_candidates(profile, views),
                *_collect_token_candidates(profile, views),
                *_collect_head_candidates(profile, views),
            ]
            if not possible_candidates:
                rejected_counts["no_surface_match"] += 1
                continue

            if cfg.reject_prompt_like and bool(structural_flags.get("looks_prompt_like")):
                rejected_counts["prompt_like"] += 1
                continue
            if cfg.reject_fragmentary and bool(structural_flags.get("looks_fragmentary")):
                rejected_counts["fragmentary"] += 1
                continue
            if bool(structural_flags.get("looks_caption_like")):
                rejected_counts["caption_like"] += 1
                continue

            accepted: Dict[str, Any] | None = None
            accepted_hierarchy: Dict[str, Any] | None = None
            accepted_score = 0.0
            accepted_score_reasons: List[str] = []
            accepted_caution_reason = ""

            for candidate in sorted(possible_candidates, key=_candidate_sort_key):
                hierarchy = _hierarchy_compatibility(
                    profile,
                    views,
                    surface_name=str(candidate.get("surface_name") or ""),
                    allow_strong_surface_bypass=bool(candidate.get("allow_strong_surface_bypass")),
                )
                hierarchy_bypass = _strict_single_head_hierarchy_bypass(profile, views, candidate, hierarchy)
                if cfg.require_hierarchy_compatibility and not bool(hierarchy.get("compatible")):
                    if hierarchy_bypass:
                        hierarchy = dict(hierarchy)
                        original_contradictory_heading = bool(hierarchy.get("contradictory_heading"))
                        hierarchy["compatible"] = True
                        hierarchy["match_type"] = hierarchy_bypass
                        hierarchy["strict_hierarchy_bypass"] = True
                        hierarchy["original_contradictory_heading"] = original_contradictory_heading
                        hierarchy["contradictory_heading_overridden"] = original_contradictory_heading
                        hierarchy["contradictory_heading"] = False
                    else:
                        rejected_counts["hierarchy_mismatch"] += 1
                        continue

                cue_failure = _candidate_cue_failure(candidate, cues)
                if cue_failure:
                    rejected_counts[cue_failure] += 1
                    continue

                context_failure = _candidate_context_failure(candidate, hierarchy)
                if context_failure:
                    rejected_counts[context_failure] += 1
                    continue

                if cfg.reject_formula_only_without_surface and _formula_only_without_binding(
                    views,
                    structural_flags,
                    candidate=candidate,
                ):
                    rejected_counts["formula_only_without_surface"] += 1
                    continue

                source_block_anchor_failure = _source_block_only_anchor_failure(views, candidate)
                if source_block_anchor_failure:
                    rejected_counts[source_block_anchor_failure] += 1
                    continue

                single_head_failure = _single_head_binding_failure(profile, views, candidate)
                if single_head_failure:
                    rejected_counts[single_head_failure] += 1
                    continue

                source_block_completion_used = bool(
                    views["source_block_text"]
                    and views["source_block_text"] != views["text"]
                    and str(candidate.get("surface_name")) == "source_block"
                )
                score, score_reasons = _score_candidate(
                    candidate=candidate,
                    hierarchy=hierarchy,
                    structural_flags=structural_flags,
                    cues=cues,
                    source_block_completion_used=source_block_completion_used,
                )
                if score < cfg.min_score:
                    rejected_counts["below_min_score"] += 1
                    continue

                accepted = dict(candidate)
                accepted_hierarchy = dict(hierarchy)
                accepted_score = score
                accepted_score_reasons = list(score_reasons)
                accepted_caution_reason = _candidate_caution_reason(
                    candidate,
                    hierarchy=hierarchy,
                    source_block_completion_used=source_block_completion_used,
                    cues=cues,
                )
                break

            if accepted is None or accepted_hierarchy is None:
                continue

            text = str(views["text"] or views["source_block_text"])
            raw_text_hash = _raw_text_hash(text)
            sentence_id = _as_text(sentence_row.get("sentence_id"))
            block_id = _as_text(sentence_row.get("block_id"))
            doc_id = _as_text(sentence_row.get("doc_id"))
            dedupe_key = _dedupe_key(
                profile.kc_id,
                sentence_id=sentence_id,
                block_id=block_id,
                doc_id=doc_id,
                raw_text_hash=raw_text_hash,
            )
            if dedupe_key in seen_keys:
                dropped_duplicate_count += 1
                rejected_counts["duplicate_of_existing_candidate"] += 1
                continue
            seen_keys.add(dedupe_key)

            surface_match_type = str(accepted["surface_match_type"])
            fallback_tier = str(accepted["tier"])
            matched_surface_terms = list(accepted.get("matched_surface_terms") or [])
            matched_target_tokens = list(accepted.get("matched_target_tokens") or [])
            surface_match_counter[surface_match_type] += 1
            hierarchy_match_counter[str(accepted_hierarchy["match_type"])] += 1
            fallback_tier_counter[fallback_tier] += 1

            patch_heading = _as_text(sentence_row.get("patch_heading"))
            page_heading = _as_text(sentence_row.get("page_heading_norm"))
            source_heading_text = patch_heading or page_heading
            source_block_completion_used = bool(
                views["source_block_text"]
                and views["source_block_text"] != views["text"]
                and str(accepted.get("surface_name")) == "source_block"
            )
            support_roles = ["fallback_surface_match"]
            if bool(cues.get("has_strong_relation_or_definition")):
                support_roles.append("definitional_anchor")
            elif bool(structural_flags.get("looks_formula_like")):
                support_roles.append("formula_or_parameter_anchor")
            else:
                support_roles.append("context_completion_anchor")
            fallback_reason = f"{fallback_tier}:{surface_match_type}+{accepted_hierarchy['match_type']}"
            hierarchy_signal = str(accepted_hierarchy["match_type"])
            policy_plan = dict(profile.retrieval_policy_plan or {})
            query_plan_id = _as_text(policy_plan.get("query_plan_id"))
            retrieval_intent = _retrieval_intent_for_candidate(
                fallback_tier=fallback_tier,
                surface_match_type=surface_match_type,
                structural_flags=structural_flags,
                cues=cues,
            )
            evidence_shape_match = _evidence_shape_match(structural_flags, cues)
            anchor_scope = "source_block" if source_block_completion_used else "same_sentence"
            authority_contract = "step5x_must_verify_against_source_rows"
            support_profile = {
                "support_roles": unique_preserve_order(support_roles),
                "preferred_support_role": "definitional_anchor" if bool(cues.get("has_strong_relation_or_definition")) else "other",
                "definition_anchor_score": round(
                    accepted_score if bool(cues.get("has_strong_relation_or_definition")) else max(accepted_score - 1.5, 0.0),
                    3,
                ),
                "explanatory_anchor_score": round(max(accepted_score - 0.75, 0.0), 3),
                "formula_support_score": round(1.0 if bool(structural_flags.get("looks_formula_like")) else 0.0, 3),
                "context_completion_score": round(0.5 if source_block_completion_used else 0.0, 3),
                "contamination_penalty": 0.0,
                "anchor_quality": "strong" if accepted_score >= cfg.min_score + 1.75 else "usable",
                "needs_context_completion": bool(source_block_completion_used and not bool(cues.get("has_strong_relation_or_definition"))),
                "has_context_completion_source": bool(source_block_completion_used),
                "formula_auxiliary_only": bool(structural_flags.get("looks_formula_like") and not bool(cues.get("has_strong_relation_or_definition"))),
                "contamination_exclusion_hint": False,
                "relation_like": bool(cues.get("has_strong_relation_or_definition")),
                "generic_context_only": False,
                "fragmentary_surface": bool(structural_flags.get("looks_fragmentary")),
                "source_block_completion_used": source_block_completion_used,
                "candidate_source": SOURCE_SURFACE_FALLBACK,
                "fallback_tier": fallback_tier,
                "fallback_reason": fallback_reason,
                "fallback_score": round(accepted_score, 6),
                "fallback_score_reasons": list(accepted_score_reasons),
                "matched_surface_terms": matched_surface_terms,
                "matched_target_tokens": matched_target_tokens,
                "surface_match_type": surface_match_type,
                "hierarchy_match_type": hierarchy_signal,
                "hierarchy_compatibility_signal": hierarchy_signal,
                "target_branch_tokens": list(profile.branch_tokens),
                "fallback_caution_reason": accepted_caution_reason,
                "query_plan_id": query_plan_id,
                "retrieval_intent": retrieval_intent,
                "candidate_origin": retrieval_intent,
                "target_surface_origin": surface_match_type,
                "target_binding_basis": f"{surface_match_type}+{hierarchy_signal}",
                "evidence_shape_match": evidence_shape_match,
                "anchor_scope": anchor_scope,
                "window_build_mode": "source_sentence",
                "review_only_candidate": False,
                "near_miss_reason": "",
                "retrieval_failure_signals": [],
                "authority_contract": authority_contract,
            }
            alignment_breakdown = {
                "name_or_alias_hit": fallback_tier == "exact_surface",
                "exact_name_phrase": surface_match_type.startswith("exact_canonical"),
                "exact_alias_phrase": surface_match_type.startswith("exact_alias") or surface_match_type.startswith("exact_acronym"),
                "canonical_name_token_hits": len(set(profile.target_tokens) & set(views["text_tokens"])),
                "alias_token_hits": len(set(profile.target_tokens) & (set(views["source_block_tokens"]) - set(views["text_tokens"]))),
                "name_or_alias_token_hits": len(set(profile.target_tokens) & (set(views["text_tokens"]) | set(views["source_block_tokens"]))),
                "context_keyword_hits": len(accepted_hierarchy["local_hits"]),
                "heading_name_hits": 1 if str(accepted.get("surface_name")) == "heading" else 0,
                "competitor_token_hits": len(accepted_hierarchy["heading_specific_tokens"]) if bool(accepted_hierarchy.get("contradictory_heading")) else 0,
                "doc_group": "",
                "kc_group": "",
                "doc_mismatch": False,
                "hard_suppressed": False,
                "strong_same_topic": bool(accepted_hierarchy["compatible"]),
                "strong_structured_candidate": bool(accepted_hierarchy["compatible"] and fallback_tier == "exact_surface"),
                "contamination_risk": "low" if not accepted_hierarchy["contradictory_heading"] else "medium",
                "contamination_signals": ["contradictory_heading"] if accepted_hierarchy["contradictory_heading"] else [],
                "fallback_candidate": True,
                "fallback_tier": fallback_tier,
                "matched_surface_terms": matched_surface_terms,
                "matched_target_tokens": matched_target_tokens,
                "surface_match_type": surface_match_type,
                "hierarchy_match_type": hierarchy_signal,
                "hierarchy_compatibility_signal": hierarchy_signal,
                "target_branch_tokens": list(profile.branch_tokens),
                "fallback_score": round(accepted_score, 6),
                "fallback_score_reasons": list(accepted_score_reasons),
                "fallback_caution_reason": accepted_caution_reason,
                "query_plan_id": query_plan_id,
                "retrieval_intent": retrieval_intent,
                "candidate_origin": retrieval_intent,
                "target_surface_origin": surface_match_type,
                "target_binding_basis": f"{surface_match_type}+{hierarchy_signal}",
                "evidence_shape_match": evidence_shape_match,
                "anchor_scope": anchor_scope,
                "window_build_mode": "source_sentence",
                "authority_contract": authority_contract,
                "flags": {
                    "is_meta": bool(sentence_row.get("is_meta")),
                    "is_nav_boilerplate": bool(sentence_row.get("is_nav_boilerplate")),
                    "is_author_affiliation": bool(sentence_row.get("is_author_affiliation")),
                    "is_transition_text": bool(sentence_row.get("is_transition_text")),
                    "is_heading_like": bool(sentence_row.get("is_heading_like")),
                    "is_formula_like": bool(sentence_row.get("is_formula_like")),
                    "is_definition_like": bool(sentence_row.get("is_definition_like")),
                    "is_procedure_like": bool(sentence_row.get("is_procedure_like")),
                    "is_example_like": bool(sentence_row.get("is_example_like")),
                },
            }
            provenance = {
                "from_step": "step4_5_sentence_overlay",
                "source_manifest": sentence_source_manifest,
                "source_jsonl": sentence_source_jsonl,
                "source_row_index": int(source_row_index),
                "source_evidence_index": 0,
                "candidate_source": SOURCE_SURFACE_FALLBACK,
                "fallback_tier": fallback_tier,
                "fallback_reason": fallback_reason,
                "fallback_score": round(accepted_score, 6),
                "fallback_score_reasons": list(accepted_score_reasons),
                "matched_surface_terms": matched_surface_terms,
                "matched_target_tokens": matched_target_tokens,
                "surface_match_type": surface_match_type,
                "hierarchy_match_type": hierarchy_signal,
                "hierarchy_compatibility_signal": hierarchy_signal,
                "source_heading_text": source_heading_text,
                "fallback_caution_reason": accepted_caution_reason,
                "query_plan_id": query_plan_id,
                "retrieval_intent": retrieval_intent,
                "candidate_origin": retrieval_intent,
                "target_surface_origin": surface_match_type,
                "target_binding_basis": f"{surface_match_type}+{hierarchy_signal}",
                "evidence_shape_match": evidence_shape_match,
                "anchor_scope": anchor_scope,
                "window_build_mode": "source_sentence",
                "review_only_candidate": False,
                "near_miss_reason": "",
                "retrieval_failure_signals": [],
                "authority_contract": authority_contract,
            }
            candidates_by_kc[profile.kc_id].append(
                {
                    "source_row_index": int(source_row_index),
                    "source_evidence_index": 0,
                    "kc_id": profile.kc_id,
                    "canonical_name": profile.canonical_name,
                    "aliases": list(profile.aliases),
                    "topic_path_ids": list(profile.topic_path_ids),
                    "topic_path_labels": list(profile.topic_path_labels),
                    "parent_topic_id": profile.parent_topic_id,
                    "parent_topic_label": profile.parent_topic_label,
                    "knowledge_unit_id": _as_text(policy_plan.get("knowledge_unit_id") or profile.kc_id),
                    "knowledge_unit_type": _as_text(policy_plan.get("knowledge_unit_type") or profile.knowledge_unit_type or "kc"),
                    "step5x_retrieval_policy_plan": policy_plan,
                    "query_plan_id": query_plan_id,
                    "retrieval_intent": retrieval_intent,
                    "candidate_origin": retrieval_intent,
                    "target_surface_origin": surface_match_type,
                    "target_binding_basis": f"{surface_match_type}+{hierarchy_signal}",
                    "evidence_shape_match": evidence_shape_match,
                    "anchor_scope": anchor_scope,
                    "window_build_mode": "source_sentence",
                    "review_only_candidate": False,
                    "near_miss_reason": "",
                    "retrieval_failure_signals": [],
                    "authority_contract": authority_contract,
                    "source_kc_id": profile.kc_id,
                    "source_canonical_name": profile.canonical_name,
                    "granularity": "sentence" if sentence_id or sentence_row.get("sent_idx") is not None or text else "block",
                    "text": text,
                    "source_block_text": str(views["source_block_text"] or text),
                    "context_text": str(views["context_text"] or ""),
                    "doc_id": doc_id,
                    "page_index": _as_int(sentence_row.get("page_index")),
                    "block_id": block_id,
                    "sentence_id": sentence_id,
                    "sent_idx": _as_int(sentence_row.get("sent_idx")),
                    "patch_id": _as_text(sentence_row.get("patch_id")),
                    "patch_heading": patch_heading,
                    "reveal_group_id": _as_text(sentence_row.get("reveal_group_id")),
                    "layer": _as_text(sentence_row.get("layer")),
                    "bbox": list(sentence_row.get("bbox") or []) if isinstance(sentence_row.get("bbox"), list) else [],
                    "char_start": _as_int(sentence_row.get("char_start")),
                    "char_end": _as_int(sentence_row.get("char_end")),
                    "retrieval_scores": {
                        "combined": round(accepted_score / 10.0, 6),
                        "heuristic": round(accepted_score, 6),
                        "source_type": "step4_5_sentence_overlay",
                        "fallback_candidate": True,
                        "fallback_tier": fallback_tier,
                    },
                    "alignment_score": round(accepted_score, 6),
                    "alignment_breakdown": alignment_breakdown,
                    "support_profile": support_profile,
                    "structural_flags": structural_flags,
                    "raw_text_hash": raw_text_hash,
                    "provenance": provenance,
                    "candidate_source": SOURCE_SURFACE_FALLBACK,
                    "fallback_tier": fallback_tier,
                    "fallback_reason": fallback_reason,
                    "fallback_score": round(accepted_score, 6),
                    "fallback_score_reasons": list(accepted_score_reasons),
                    "matched_surface_terms": matched_surface_terms,
                    "matched_target_tokens": matched_target_tokens,
                    "surface_match_type": surface_match_type,
                    "hierarchy_match_type": hierarchy_signal,
                    "hierarchy_compatibility_signal": hierarchy_signal,
                    "target_branch_tokens": list(profile.branch_tokens),
                    "source_heading_text": source_heading_text,
                    "fallback_caution_reason": accepted_caution_reason,
                }
            )

    output_rows: List[Dict[str, Any]] = []
    candidate_count_by_kc: Dict[str, int] = {}
    for profile in profiles:
        ordered = sorted(
            candidates_by_kc.get(profile.kc_id, []),
            key=lambda row: (
                -float(row.get("alignment_score") or 0.0),
                TIER_PRIORITY.get(str(row.get("fallback_tier") or ""), 99),
                0 if str(row.get("surface_match_type") or "").startswith("exact_canonical_text") else 1,
                int(row.get("source_row_index") or 0),
            ),
        )
        capped = ordered[: cfg.max_fallback_per_kc]
        output_rows.extend(capped)
        candidate_count_by_kc[profile.kc_id] = len(capped)
        if len(ordered) > len(capped):
            rejected_counts["per_kc_cap"] += len(ordered) - len(capped)

    stats = {
        "enabled": True,
        "source_surface": SOURCE_SURFACE_FALLBACK,
        "sentence_source_manifest": sentence_source_manifest,
        "sentence_source_jsonl": sentence_source_jsonl,
        "total_kcs_considered": len(profiles),
        "total_sentence_rows_scanned": len(sentence_rows),
        "candidate_rows_added": len(output_rows),
        "candidate_count_by_kc": dict(sorted(candidate_count_by_kc.items())),
        "broad_tokens": sorted(broad_tokens),
        "fallback_tier_counter": dict(sorted(fallback_tier_counter.items())),
        "surface_match_type_counter": dict(sorted(surface_match_counter.items())),
        "hierarchy_match_type_counter": dict(sorted(hierarchy_match_counter.items())),
        "rejected_counts": dict(sorted(rejected_counts.items())),
        "dropped_duplicate_count": int(dropped_duplicate_count),
    }
    return {"rows": output_rows, "stats": stats}


__all__ = [
    "DEFAULT_DYNAMIC_BROAD_TOKEN_MIN_DOC_FREQUENCY",
    "SOURCE_SURFACE_FALLBACK",
    "SourceSurfaceFallbackConfig",
    "build_source_surface_fallback_candidates",
    "compute_dynamic_broad_tokens",
    "fallback_config_from_mapping",
]
