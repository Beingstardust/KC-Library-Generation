from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from kc_l.kc_drafting.contracts import (
    AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED,
    AUTHORITATIVE_DEFINITION_STATUS_INSUFFICIENT_SUPPORT,
    COVERAGE_STATE_STATUS_REPRESENTED,
    DRAFT_CONTRACT_VERSION,
    HEURISTIC_DRAFTING_MODE,
    STEP67_SEMANTIC_CONTRACT_VERSION,
)
from kc_l.kc_drafting.hierarchy_refs import typed_topic_hierarchy_fields
from kc_l.kc_drafting.policy_domain import (
    classify_background_drift,
    is_domain_family_member,
    tolerated_background_drift_classes,
)
from kc_l.retrieval_gate.semantic import match_normalize, unique_preserve_order
from kc_l.retrieval_gate.evidence_stage_v3_lane_semantics import has_automatic_drafting_support

DEFINITION_LINK_CUES = [
    " is ",
    " are ",
    " defined as ",
    " means ",
    " refers to ",
    " we call ",
    " denote",
    " denotes",
    " assumed that ",
    " assumption ",
    " where ",
    " within ",
]

SCOPE_CUES = [
    "within ",
    "for ",
    "where ",
    "when ",
    "belongs",
    "class ",
    "cluster ",
    "attribute ",
]

STRONG_SCOPE_CONTEXT_CUES = [
    " in classification ",
    " used for ",
    " for training ",
    " feature space ",
    " given evidence ",
    " representative of the population ",
]

QUESTION_CUES = [
    "justify your answer",
    "justify your answers",
    " can we ",
    "if you answered",
]

SHORTENABLE_METRIC_SUFFIXES = {"index", "rate", "ratio"}
DIRECT_EXPLANATORY_CUES = [
    " is ",
    " are ",
    " i.e. ",
    " i.e ",
    " means ",
    " refers to ",
    " defined as ",
    " called ",
    " known as ",
    " difference between ",
]
DESCRIPTIVE_SEPARATOR_PATTERN = re.compile(r"\s[:;\-]\s")
LABELED_CLAUSE_PATTERN = re.compile(r"(?P<label>[A-Za-z][A-Za-z0-9() /\-]{1,80}?)(?P<delimiter>\s*[:=])")
CLAUSE_SEPARATOR_PATTERN = re.compile(r"[,;•▶]\s*")
CLAUSE_CAPITALIZED_BOUNDARY_PATTERN = re.compile(r"\s+(?=[A-Z][a-z])")
FOCUS_TOKEN_STOPWORDS = {
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
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "these",
    "this",
    "those",
    "to",
    "was",
    "we",
    "where",
    "which",
    "with",
}
DEFINITION_FRAGMENT_PREFIXES = (
    "where ",
    "for a training set ",
    "for an attribute ",
    "for the training set ",
    "if ",
    "let ",
    "given is ",
    "this results in ",
)
GENERIC_BACKGROUND_PREFIXES = (
    "how to ",
    "we have seen",
    "different types of ",
    "there are many ways ",
)
PROCEDURAL_FRAGMENT_PREFIXES = (
    "choose ",
    "remove ",
    "invoke ",
    "sample ",
    "pick ",
    "compute ",
    "build ",
)
GENERIC_CONTEXT_LEAD_INS = (
    "given is ",
    "given are ",
    "let ",
    "slideset from ",
    "your turn",
)
SAME_KC_CONTEXT_LEAD_INS = (
    "although ",
    "furthermore ",
    "furthermore,",
    "for example",
    "for instance",
    "however",
    "hence",
    "in the following",
    "note that",
    "notice that",
    "there are ",
    "there is ",
    "to illustrate",
    "suppose ",
    "consider ",
)
REVIEWER_SURFACE_NOISE_MARKERS = ("\u0001", "\ufffd", "\u25b6")
REVIEWER_BUNDLE_BLOCK_REASONS = {
    "citation_or_slide_context",
    "formula_dense_fragment",
    "ocr_noise",
    "traceback_noise",
}
STRUCTURAL_PREFIX_PATTERN = re.compile(r"^(?:table|figure|algorithm)\s+\d+(?:\.\d+)*\.?\s*", flags=re.IGNORECASE)
PRONOUN_LED_SENTENCE_PATTERN = re.compile(r"^(?:It|They|This|These)\b", flags=re.IGNORECASE)


def normalize_ws(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def tokenize(text: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9]+", str(text or "").lower())


def _normalized_text(text: Any) -> str:
    return match_normalize(normalize_ws(text or ""))


def _alnum_key(text: Any) -> str:
    return "".join(re.findall(r"[a-z0-9]+", normalize_ws(text).lower()))


def _candidate_text(row: Mapping[str, Any]) -> str:
    source_block_text = normalize_ws(row.get("source_block_text") or "")
    if source_block_text:
        return source_block_text
    return normalize_ws(row.get("quote_surface") or "")


def _candidate_source_text_field(row: Mapping[str, Any]) -> str:
    source_block_text = normalize_ws(row.get("source_block_text") or "")
    return "source_block_text" if source_block_text else "quote_surface"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _text_has_any_cue(text_norm: str, cues: Sequence[str]) -> bool:
    return any(cue in text_norm for cue in cues)


def _question_like(text: str) -> bool:
    text_norm = f" {_normalized_text(text)} "
    return "?" in text or _text_has_any_cue(text_norm, QUESTION_CUES)



def _role_hint_mapping(value):
    """Normalize role_hint into a mapping.

    Older KC overlay rows may carry a mapping. Topic-pack bridge rows may carry
    a plain string role. Keep this generic and domain-agnostic.
    """
    if isinstance(value, dict):
        return dict(value)
    if value in (None, ""):
        return {}
    if isinstance(value, str):
        return {
            "role": value,
            "slot_role": value,
            "raw_role_hint": value,
        }
    try:
        return dict(value)
    except Exception:
        return {
            "raw_role_hint": str(value),
        }


def _definition_signal(row: Mapping[str, Any], text_norm: str) -> bool:
    role_hint = _role_hint_mapping(row.get("role_hint"))
    support_profile = dict(row.get("support_profile") or (row.get("alignment_breakdown") or {}).get("support_profile") or {})
    safe_role = str(role_hint.get("safe_role_hint") or "")
    top_role = str(role_hint.get("top_role") or "")
    context_keyword_hits = _context_keyword_hits(row, text_norm)
    return bool(
        bool(row.get("is_definition_like"))
        or (
            str(support_profile.get("preferred_support_role") or "") == "definitional_anchor"
            and str(support_profile.get("anchor_quality") or "") in {"strong", "usable"}
            and not bool(support_profile.get("formula_auxiliary_only", False))
        )
        or safe_role == "definition"
        or top_role == "definition"
        or _text_has_any_cue(text_norm, DEFINITION_LINK_CUES)
        or context_keyword_hits >= 2
    )


def _scope_signal(text_norm: str) -> bool:
    return _text_has_any_cue(text_norm, SCOPE_CUES)


def _support_profile(row: Mapping[str, Any]) -> Dict[str, Any]:
    alignment_breakdown = dict(row.get("alignment_breakdown") or {})
    return dict(row.get("support_profile") or alignment_breakdown.get("support_profile") or {})


def _selected_grounded_scope_support(
    row: Mapping[str, Any],
    assessment: Mapping[str, Any],
) -> bool:
    text = str(assessment.get("candidate_text") or _candidate_text(row))
    text_norm = f" {_normalized_text(text)} "
    token_count = len(tokenize(text_norm))
    title_overlap, context_overlap, has_name_anchor = _definition_alignment_features(row, text)
    rerank_margin = _retrieval_metric(row, "rerank_margin")
    return bool(
        assessment.get("usable_evidence")
        and not assessment.get("contamination_block")
        and not assessment.get("question_like")
        and not assessment.get("title_like_heading")
        and not assessment.get("bare_heading")
        and not assessment.get("formula_lead_in")
        and assessment.get("scope_signal")
        and 8 <= token_count <= 40
        and (
            assessment.get("definition_candidate")
            or assessment.get("context_candidate")
            or assessment.get("equation_support")
        )
        and _text_has_any_cue(text_norm, STRONG_SCOPE_CONTEXT_CUES)
        and (has_name_anchor or title_overlap > 0 or context_overlap >= 2)
        and (has_name_anchor or title_overlap > 0 or rerank_margin > 0.0)
    )


def _dedupe_key(row: Mapping[str, Any]) -> str:
    text_key = _normalized_text(_candidate_text(row))
    if text_key:
        return text_key
    return str(row.get("overlay_candidate_id") or "")


def _candidate_name_variants(row: Mapping[str, Any]) -> List[str]:
    canonical = normalize_ws(row.get("canonical_name") or "")
    aliases = [normalize_ws(item) for item in row.get("aliases") or []]
    variants: List[str] = []
    for raw in [canonical, *aliases]:
        if not raw:
            continue
        variants.append(raw)
        stripped = normalize_ws(re.sub(r"\([^)]*\)", " ", raw))
        if stripped and stripped != raw:
            variants.append(stripped)
        for match in re.findall(r"\(([^)]+)\)", raw):
            variant = normalize_ws(match)
            if variant:
                variants.append(variant)
        for part in re.split(r"/", raw):
            variant = normalize_ws(part)
            if variant and variant != raw:
                variants.append(variant)
    return [variant for variant in unique_preserve_order(variants) if variant]


def _candidate_full_name_keys(row: Mapping[str, Any]) -> List[str]:
    keys = [_alnum_key(raw) for raw in _candidate_name_variants(row)]
    return [key for key in unique_preserve_order(keys) if key]


def _candidate_formula_name_keys(row: Mapping[str, Any]) -> List[str]:
    keys: List[str] = []
    for raw in _candidate_name_variants(row):
        compact = _alnum_key(raw)
        if compact:
            keys.append(compact)
        parts = [part for part in tokenize(raw) if len(part) >= 4]
        if len(parts) >= 2 and parts[-1] in SHORTENABLE_METRIC_SUFFIXES:
            keys.append(parts[0])
    return unique_preserve_order(keys)


def _focus_tokens(text: Any) -> set[str]:
    return {
        token
        for token in tokenize(_normalized_text(text))
        if len(token) >= 3 and token not in FOCUS_TOKEN_STOPWORDS
    }


def _strip_leading_markers(text: str) -> str:
    stripped = re.sub(r"^[^A-Za-z0-9]+", "", normalize_ws(text))
    return normalize_ws(stripped)


def _strip_structural_prefix(text: str) -> str:
    stripped = STRUCTURAL_PREFIX_PATTERN.sub("", normalize_ws(text))
    stripped = re.sub(r"^[•▶\-]+\s*", "", stripped)
    return normalize_ws(stripped)


def _looks_labeled_definition_clause(text: str) -> bool:
    return LABELED_CLAUSE_PATTERN.match(_strip_leading_markers(text)) is not None


def _starts_with_any(text: str, prefixes: Sequence[str]) -> bool:
    return any(text.startswith(prefix) for prefix in prefixes)


def _sentence_segments(text: str, *, limit: int = 6) -> List[str]:
    cleaned = _strip_structural_prefix(text)
    if not cleaned:
        return []
    segments = [normalize_ws(part) for part in re.split(r"(?<=[.!?])\s+", cleaned) if normalize_ws(part)]
    return segments[: max(1, int(limit))] if segments else [cleaned]


def _has_name_anchor(text: str, row: Mapping[str, Any]) -> bool:
    compact_text = _alnum_key(text)
    if not compact_text:
        return False
    for name_key in _candidate_full_name_keys(row):
        if name_key and name_key in compact_text:
            return True
    return False


def _label_matches_target(label: str, row: Mapping[str, Any]) -> bool:
    label_key = _alnum_key(label)
    if not label_key:
        return False
    return any(label_key == name_key for name_key in _candidate_full_name_keys(row))


def _labeled_clause_matches(text: str) -> List[re.Match[str]]:
    starts = {0}
    for match in CLAUSE_SEPARATOR_PATTERN.finditer(text):
        starts.add(match.end())
    for match in CLAUSE_CAPITALIZED_BOUNDARY_PATTERN.finditer(text):
        starts.add(match.end())

    matches_by_start: Dict[int, re.Match[str]] = {}
    for start in sorted(starts):
        match = LABELED_CLAUSE_PATTERN.match(text, start)
        if match is not None:
            matches_by_start[int(match.start())] = match
    return [matches_by_start[idx] for idx in sorted(matches_by_start)]


def _extract_target_support_segment(
    *,
    row: Mapping[str, Any],
    text: str,
    contamination_risk: str,
    question_like: bool,
    bare_heading: bool,
) -> Dict[str, str]:
    if not text or contamination_risk == "high" or question_like or bare_heading:
        return {}
    matches = _labeled_clause_matches(text)
    if len(matches) < 2:
        return _extract_same_kc_sentence_segment(row=row)
    target_indexes = [
        idx for idx, match in enumerate(matches)
        if _label_matches_target(str(match.group("label") or ""), row)
    ]
    if len(target_indexes) != 1:
        return _extract_same_kc_sentence_segment(row=row)
    target_idx = target_indexes[0]
    target_match = matches[target_idx]
    clause_end = matches[target_idx + 1].start() if target_idx + 1 < len(matches) else len(text)
    clause = normalize_ws(text[target_match.start():clause_end].strip(" ,;•▶-"))
    clause = normalize_ws(re.sub(r"^[•▶\-\s]+", "", clause))
    clause = normalize_ws(re.sub(r"[ ,;•▶\-]+$", "", clause))
    if not clause or clause == normalize_ws(text):
        return _extract_same_kc_sentence_segment(row=row)
    if len(tokenize(_normalized_text(clause))) < 3:
        return _extract_same_kc_sentence_segment(row=row)
    delimiter = str(target_match.group("delimiter") or "").strip()
    kind = "paired_metric_formula" if delimiter == "=" else "labeled_concept_clause"
    return {"text": clause, "kind": kind}


def _same_kc_heading_prefix(row: Mapping[str, Any], text: str) -> str:
    cleaned = _strip_structural_prefix(text)
    if not cleaned:
        return ""
    prefix = re.split(r"(?<=[.:!?])\s+", cleaned, maxsplit=1)[0].strip()
    prefix = normalize_ws(re.sub(r"[:.]$", "", prefix))
    if not prefix or len(tokenize(_normalized_text(prefix))) > 10:
        return ""
    return prefix if _has_name_anchor(prefix, row) else ""


def _anchored_same_kc_relation_score(text: str, row: Mapping[str, Any]) -> float:
    lowered = normalize_ws(text).lower()
    if not lowered:
        return 0.0
    prefix_stripped = re.sub(r"^(?:for|given)\b[^,.!?]{0,96},\s*", "", lowered, flags=re.IGNORECASE)
    canonical_core = normalize_ws(re.sub(r"\([^)]*\)", " ", row.get("canonical_name") or ""))
    canonical_core_token_count = max(1, len(tokenize(canonical_core)))
    relation_patterns = (
        "is",
        "are",
        "was",
        "were",
        "means",
        "refers to",
        "denotes",
        "called",
        "known as",
        "captures",
        "represents",
        "characterizes",
        "measures",
        "quantifies",
    )
    concept_lead_patterns = (
        "is",
        "are",
        "was",
        "were",
        "means",
        "refers to",
        "denotes",
        "captures",
        "represents",
        "characterizes",
        "measures",
        "quantifies",
        "starts with",
        "begins with",
        "operates by",
        "operates independently of",
        "operates independently",
        "uses only",
    )
    for variant in _candidate_name_variants(row):
        escaped = re.escape(variant.lower())
        anchor_suffix = r"(?=\s|[.?!,:;]|$)"
        relation_object_allowed = len(tokenize(variant)) >= canonical_core_token_count
        if re.search(
            rf"^(?:the|a|an)\s+{escaped}{anchor_suffix}\s*(?:=|\b(?:{'|'.join(re.escape(item) for item in concept_lead_patterns)})\b)",
            prefix_stripped,
            flags=re.IGNORECASE,
        ) or re.search(
            rf"^{escaped}{anchor_suffix}\s*(?:=|\b(?:{'|'.join(re.escape(item) for item in concept_lead_patterns)})\b)",
            prefix_stripped,
            flags=re.IGNORECASE,
        ):
            return 3.0
        if relation_object_allowed and (
            re.search(
            rf"^[a-z0-9][^.?!]{{0,200}}\b(?:{'|'.join(re.escape(item) for item in relation_patterns)})\b\s+(?:the|a|an)\s+{escaped}{anchor_suffix}",
            lowered,
            flags=re.IGNORECASE,
        ) or re.search(
            rf"^[a-z0-9][^.?!]{{0,200}}\b(?:{'|'.join(re.escape(item) for item in relation_patterns)})\b\s+{escaped}{anchor_suffix}",
            lowered,
            flags=re.IGNORECASE,
        )):
            return 2.0
    return 0.0


def _same_kc_sentence_variants(row: Mapping[str, Any], text: str, *, source_kind: str) -> List[Tuple[str, str]]:
    cleaned = _strip_structural_prefix(text)
    if not cleaned:
        return []
    segments = _sentence_segments(cleaned, limit=6)
    heading = _same_kc_heading_prefix(row, cleaned)
    variants: List[Tuple[str, str]] = []
    for index, segment in enumerate(segments):
        variants.append((segment, f"anchored_same_kc_{source_kind}_sentence"))
        if heading and index == 1 and PRONOUN_LED_SENTENCE_PATTERN.match(segment):
            variants.append(
                (
                    normalize_ws(PRONOUN_LED_SENTENCE_PATTERN.sub(lambda _: heading, segment, count=1)),
                    f"anchored_same_kc_{source_kind}_heading_continuation",
                )
            )
    if ":" in cleaned and heading:
        _, tail = cleaned.split(":", 1)
        tail_segments = _sentence_segments(tail, limit=2)
        if tail_segments:
            variants.append((tail_segments[0], f"anchored_same_kc_{source_kind}_tail_sentence"))
            if PRONOUN_LED_SENTENCE_PATTERN.match(tail_segments[0]):
                variants.append(
                    (
                        normalize_ws(PRONOUN_LED_SENTENCE_PATTERN.sub(lambda _: heading, tail_segments[0], count=1)),
                        f"anchored_same_kc_{source_kind}_tail_heading_continuation",
                    )
                )
    deduped: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for candidate_text, kind in variants:
        normalized = normalize_ws(candidate_text)
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        seen.add(key)
        deduped.append((normalized, kind))
    return deduped


def _looks_same_kc_sentence_fragment(text: str) -> bool:
    normalized = normalize_ws(text)
    lowered = normalized.lower()
    if not lowered:
        return True
    if not normalized[:1].isupper():
        return True
    if lowered.endswith((":", "=", " where", " which", " that")):
        return True
    if _starts_with_any(lowered, DEFINITION_FRAGMENT_PREFIXES):
        return True
    if not re.search(r"[.!?]$", normalized) and lowered.endswith((" given", " with", " of", " to", " for")):
        return True
    return False


def _extract_same_kc_sentence_segment(*, row: Mapping[str, Any]) -> Dict[str, str]:
    raw_quote_surface = normalize_ws(row.get("quote_surface") or "")
    raw_source_block_text = normalize_ws(row.get("source_block_text") or "")
    raw_text = _candidate_text(row)
    raw_text_norm = normalize_ws(raw_text)
    candidates: List[Tuple[float, str, str]] = []
    for source_kind, raw_source in (
        ("quote", raw_quote_surface),
        ("source_block", raw_source_block_text),
    ):
        if not raw_source:
            continue
        for candidate_text, kind in _same_kc_sentence_variants(row, raw_source, source_kind=source_kind):
            if not candidate_text or candidate_text == raw_text_norm:
                continue
            lowered = candidate_text.lower()
            if _question_like(candidate_text):
                continue
            if _starts_with_any(lowered, SAME_KC_CONTEXT_LEAD_INS):
                continue
            if _starts_with_any(lowered, GENERIC_BACKGROUND_PREFIXES):
                continue
            if _starts_with_any(lowered, GENERIC_CONTEXT_LEAD_INS):
                continue
            if _looks_same_kc_sentence_fragment(candidate_text):
                continue
            relation_score = _anchored_same_kc_relation_score(candidate_text, row)
            if relation_score <= 0.0:
                continue
            candidate_norm = f" {_normalized_text(candidate_text)} "
            if not (
                _text_has_any_cue(candidate_norm, DIRECT_EXPLANATORY_CUES)
                or _text_has_any_cue(candidate_norm, (" called ", " known as "))
                or (
                    _has_name_anchor(candidate_text, row)
                    and _text_has_any_cue(
                        candidate_norm,
                        (
                            " starts with ",
                            " begins with ",
                            " operates by ",
                            " operates independently ",
                            " operates independently of ",
                            " uses only ",
                        ),
                    )
                )
            ):
                continue
            score = relation_score
            if source_kind == "quote" and len(candidate_text) < len(raw_source_block_text or candidate_text):
                score += 1.5
            if _has_name_anchor(candidate_text, row):
                score += 1.0
            score -= max(0.0, float(len(candidate_text) - 180) / 120.0)
            candidates.append((score, candidate_text, kind))
    if not candidates:
        return {}
    candidates.sort(key=lambda item: (-float(item[0]), len(item[1]), item[2]))
    _, candidate_text, kind = candidates[0]
    return {"text": candidate_text, "kind": kind}


def _exact_named_equality_formula(
    *,
    row: Mapping[str, Any],
    text: str,
    quote_surface: str,
    formula_like: bool,
    special_definition_evidence: bool,
) -> bool:
    if not (formula_like and special_definition_evidence):
        return False
    formula_text = quote_surface or text
    if "=" not in formula_text:
        return False
    lhs = formula_text.split("=", 1)[0]
    lhs_key = _alnum_key(lhs)
    if not lhs_key:
        return False
    for name_key in _candidate_formula_name_keys(row):
        if name_key and lhs_key.startswith(name_key):
            return True
    return False


def _theorem_statement_or_equation(
    *,
    row: Mapping[str, Any],
    source_block_text: str,
    heading_like: bool,
    formula_like: bool,
    special_definition_evidence: bool,
    long_enough_prose: bool,
) -> bool:
    canonical_norm = f" {_normalized_text(row.get('canonical_name') or '')} "
    source_norm = f" {_normalized_text(source_block_text)} "
    theorem_semantic_cue = bool(
        _text_has_any_cue(source_norm, DIRECT_EXPLANATORY_CUES)
        or " probability " in source_norm
        or " given evidence " in source_norm
    )
    return bool(
        formula_like
        and special_definition_evidence
        and not heading_like
        and long_enough_prose
        and source_block_text
        and " theorem " in canonical_norm
        and "=" in source_block_text
        and ":" in source_block_text
        and theorem_semantic_cue
    )


def _formula_backed_explanatory_clause(
    *,
    row: Mapping[str, Any],
    source_block_text: str,
    heading_like: bool,
    formula_like: bool,
    special_definition_evidence: bool,
    long_enough_prose: bool,
) -> bool:
    source_norm = f" {_normalized_text(source_block_text)} "
    context_keyword_hits = _context_keyword_hits(row, source_block_text)
    semantic_anchor = bool(
        _has_name_anchor(source_block_text, row)
        or context_keyword_hits >= 2
    )
    direct_explanatory = bool(
        source_block_text
        and (_text_has_any_cue(source_norm, DIRECT_EXPLANATORY_CUES) or ":" in source_block_text)
    )
    return bool(
        formula_like
        and source_block_text
        and special_definition_evidence
        and not heading_like
        and long_enough_prose
        and semantic_anchor
        and direct_explanatory
    )


def _anchored_descriptive_clause(
    *,
    row: Mapping[str, Any],
    text: str,
    source_block_text: str,
    text_norm: str,
    usable_evidence: bool,
    contamination_block: bool,
    question_like: bool,
    bare_heading: bool,
    heading_like: bool,
    supportive_context: bool,
    long_enough_prose: bool,
    anchor_strength: str,
    target_segment_extracted: bool,
) -> bool:
    source_norm = f" {_normalized_text(source_block_text)} "
    descriptive_separator = bool(
        ":" in source_block_text
        or DESCRIPTIVE_SEPARATOR_PATTERN.search(source_block_text)
        or DESCRIPTIVE_SEPARATOR_PATTERN.search(text)
    )
    sufficient_descriptive_length = bool(
        long_enough_prose or (target_segment_extracted and len(tokenize(text_norm)) >= 4)
    )
    if not (
        source_block_text
        and usable_evidence
        and not contamination_block
        and not question_like
        and not bare_heading
        and not heading_like
        and sufficient_descriptive_length
        and (supportive_context or anchor_strength == "strong")
        and _has_name_anchor(source_block_text, row)
    ):
        return False
    return bool(
        _text_has_any_cue(text_norm, DEFINITION_LINK_CUES)
        or _text_has_any_cue(source_norm, DEFINITION_LINK_CUES)
        or descriptive_separator
    )


def _row_labels(row: Mapping[str, Any]) -> List[str]:
    labels = [normalize_ws(item).lower() for item in row.get("ancestor_labels") or []]
    if labels:
        return [label for label in labels if label]
    return [normalize_ws(item).lower() for item in row.get("source_hierarchy_path") or [] if normalize_ws(item)]


def _domain_policy_family_match(row: Mapping[str, Any]) -> bool:
    return is_domain_family_member(row)


def _formula_lhs_anchor(
    *,
    row: Mapping[str, Any],
    text: str,
    quote_surface: str,
) -> bool:
    formula_text = quote_surface or text
    if "=" not in formula_text:
        return False
    lhs_key = _alnum_key(formula_text.split("=", 1)[0])
    if not lhs_key:
        return False
    for name_key in _candidate_formula_name_keys(row):
        if name_key and lhs_key.startswith(name_key):
            return True
    return False


def _source_block_anchor(
    *,
    source_block_text: str,
    supportive_context: bool,
    context_keyword_hits: int,
) -> bool:
    return bool(source_block_text and supportive_context and context_keyword_hits >= 3)


def _anchor_strength(
    *,
    row: Mapping[str, Any],
    text: str,
    quote_surface: str,
    source_block_text: str,
    exact_name_phrase: bool,
    exact_alias_phrase: bool,
    name_or_alias_hit: bool,
    supportive_context: bool,
    context_keyword_hits: int,
) -> str:
    direct_anchor = bool(
        exact_name_phrase
        or exact_alias_phrase
        or _has_name_anchor(text, row)
        or _has_name_anchor(quote_surface, row)
        or _has_name_anchor(source_block_text, row)
        or _formula_lhs_anchor(row=row, text=text, quote_surface=quote_surface)
        or _source_block_anchor(
            source_block_text=source_block_text,
            supportive_context=supportive_context,
            context_keyword_hits=context_keyword_hits,
        )
    )
    if direct_anchor:
        return "strong"
    if name_or_alias_hit or context_keyword_hits >= 2:
        return "moderate"
    return "weak"


def _concept_mix_risk(
    *,
    quote_surface: str,
    source_block_text: str,
    alignment_breakdown: Mapping[str, Any],
    target_segment_extracted: bool,
) -> str:
    if target_segment_extracted:
        return "single_concept"
    competitor_token_hits = int(alignment_breakdown.get("competitor_token_hits") or 0)
    heading_name_hits = int(alignment_breakdown.get("heading_name_hits") or 0)
    quote_stripped = normalize_ws(quote_surface)
    source_lower = normalize_ws(source_block_text).lower()
    colon_count = source_lower.count(":")
    if quote_stripped.endswith(":") and colon_count >= 2:
        return "mixed_concept_list"
    if competitor_token_hits > 0 and heading_name_hits > 0 and colon_count >= 1:
        return "mixed_concept_list"
    if competitor_token_hits > 0 or heading_name_hits > 0:
        return "neighboring_concept_bleed"
    return "single_concept"


def _background_drift_class(
    *,
    row: Mapping[str, Any],
    text: str,
    quote_surface: str,
    source_block_text: str,
    anchor_strength: str,
    concept_mix_risk: str,
) -> str:
    if not _domain_policy_family_match(row):
        return "none"
    return classify_background_drift(
        row=row,
        text=text,
        quote_surface=quote_surface,
        source_block_text=source_block_text,
        anchor_strength=anchor_strength,
        concept_mix_risk=concept_mix_risk,
    )


def _generic_drafting_policy_features(
    *,
    row: Mapping[str, Any],
    text: str,
    quote_surface: str,
    source_block_text: str,
    alignment_breakdown: Mapping[str, Any],
    exact_name_phrase: bool,
    exact_alias_phrase: bool,
    name_or_alias_hit: bool,
    supportive_context: bool,
    context_keyword_hits: int,
    target_segment_extracted: bool,
) -> Dict[str, Any]:
    anchor_strength = _anchor_strength(
        row=row,
        text=text,
        quote_surface=quote_surface,
        source_block_text=source_block_text,
        exact_name_phrase=exact_name_phrase,
        exact_alias_phrase=exact_alias_phrase,
        name_or_alias_hit=name_or_alias_hit,
        supportive_context=supportive_context,
        context_keyword_hits=context_keyword_hits,
    )
    concept_mix_risk = _concept_mix_risk(
        quote_surface=quote_surface,
        source_block_text=source_block_text,
        alignment_breakdown=alignment_breakdown,
        target_segment_extracted=target_segment_extracted,
    )
    background_drift_class = _background_drift_class(
        row=row,
        text=text,
        quote_surface=quote_surface,
        source_block_text=source_block_text,
        anchor_strength=anchor_strength,
        concept_mix_risk=concept_mix_risk,
    )
    background_drift_block = background_drift_class != "none" and anchor_strength != "strong"
    concept_mix_block = concept_mix_risk == "mixed_concept_list" or (
        concept_mix_risk == "neighboring_concept_bleed" and anchor_strength == "weak"
    )
    return {
        "anchor_strength": anchor_strength,
        "background_drift_class": background_drift_class,
        "concept_mix_risk": concept_mix_risk,
        "background_drift_block": background_drift_block,
        "concept_mix_block": concept_mix_block,
    }


def select_overlay_kc_subset(
    overlay_rows: Sequence[Mapping[str, Any]],
    limit_kcs: int | None,
    *,
    exact_kc_ids: Sequence[str] | None = None,
) -> List[Dict[str, Any]]:
    rows_by_kc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in overlay_rows:
        kc_id = str(row.get("kc_id") or "")
        if not kc_id:
            continue
        rows_by_kc[kc_id].append(dict(row))

    ordered_ids = sorted(rows_by_kc.keys())
    if exact_kc_ids:
        missing = [str(kc_id) for kc_id in exact_kc_ids if str(kc_id) not in rows_by_kc]
        if missing:
            raise RuntimeError(f"Configured exact_kc_ids contains unknown kc_id values: {missing}")
        chosen_ids = [str(kc_id) for kc_id in exact_kc_ids]
        if limit_kcs is not None and len(chosen_ids) != int(limit_kcs):
            raise RuntimeError(
                f"Configured exact_kc_ids length {len(chosen_ids)} does not match limit_kcs {int(limit_kcs)}"
            )
    else:
        chosen_ids = list(ordered_ids if limit_kcs is None else ordered_ids[: int(limit_kcs)])

    selected_rows: List[Dict[str, Any]] = []
    for kc_id in chosen_ids:
        selected_rows.extend(rows_by_kc[kc_id])
    return selected_rows


def assess_overlay_candidate(row: Mapping[str, Any]) -> Dict[str, Any]:
    raw_text = _candidate_text(row)
    raw_quote_surface = normalize_ws(row.get("quote_surface") or "")
    raw_source_block_text = normalize_ws(row.get("source_block_text") or "")
    raw_text_norm = f" {_normalized_text(raw_text)} "
    raw_token_count = len(tokenize(raw_text_norm))
    provenance_status = str(row.get("provenance_normalization_status") or "")
    contamination_risk = str(row.get("contamination_risk") or "")
    alignment_breakdown = dict(row.get("alignment_breakdown") or {})
    support_profile = _support_profile(row)
    upstream_support_role = str(support_profile.get("preferred_support_role") or "other")
    upstream_anchor_quality = str(support_profile.get("anchor_quality") or "weak")
    upstream_formula_auxiliary_only = bool(support_profile.get("formula_auxiliary_only", False))
    upstream_context_completion_available = bool(
        support_profile.get("has_context_completion_source", False)
    )
    raw_text_definition_link = _text_has_any_cue(raw_text_norm, DEFINITION_LINK_CUES)
    raw_question_like = _question_like(raw_text)
    formula_like = bool(row.get("is_formula_like"))
    raw_heading_like = bool(row.get("is_heading_like"))
    procedure_like = bool(row.get("is_procedure_like"))
    exact_name_phrase = bool(alignment_breakdown.get("exact_name_phrase"))
    exact_alias_phrase = bool(alignment_breakdown.get("exact_alias_phrase"))
    name_or_alias_hit = bool(alignment_breakdown.get("name_or_alias_hit"))
    context_keyword_hits = _context_keyword_hits(row, raw_text)
    name_support = bool(exact_name_phrase or exact_alias_phrase or name_or_alias_hit or context_keyword_hits >= 1)
    supportive_context = bool(
        bool(row.get("strong_structured_candidate"))
        or bool(row.get("strong_same_topic"))
        or (
            upstream_support_role in {"definitional_anchor", "explanatory_anchor", "context_completion_anchor"}
            and upstream_anchor_quality in {"strong", "usable"}
        )
    )
    raw_title_like_heading = raw_heading_like and not raw_text_definition_link and not procedure_like
    raw_bare_heading = raw_title_like_heading and raw_token_count <= 12 and not formula_like
    target_segment = _extract_target_support_segment(
        row=row,
        text=raw_text,
        contamination_risk=contamination_risk,
        question_like=raw_question_like,
        bare_heading=raw_bare_heading,
    )
    target_segment_text = normalize_ws(target_segment.get("text") or "")
    target_segment_kind = str(target_segment.get("kind") or "")
    target_segment_extracted = bool(target_segment_text)

    text = target_segment_text or raw_text
    quote_surface = target_segment_text or raw_quote_surface
    source_block_text = target_segment_text or raw_source_block_text
    text_norm = f" {_normalized_text(text)} "
    token_count = len(tokenize(text_norm))
    definition_signal = _definition_signal(row, text_norm)
    question_like = _question_like(text)
    heading_like = bool(raw_heading_like and not target_segment_extracted)
    text_definition_link = _text_has_any_cue(text_norm, DEFINITION_LINK_CUES)
    policy_features = _generic_drafting_policy_features(
        row=row,
        text=text,
        quote_surface=quote_surface,
        source_block_text=source_block_text,
        alignment_breakdown=alignment_breakdown,
        exact_name_phrase=exact_name_phrase,
        exact_alias_phrase=exact_alias_phrase,
        name_or_alias_hit=name_or_alias_hit,
        supportive_context=supportive_context,
        context_keyword_hits=context_keyword_hits,
        target_segment_extracted=target_segment_extracted,
    )
    anchor_strength = str(policy_features["anchor_strength"])
    background_drift_class = str(policy_features["background_drift_class"])
    concept_mix_risk = str(policy_features["concept_mix_risk"])
    background_drift_block = bool(policy_features["background_drift_block"])
    concept_mix_block = bool(policy_features["concept_mix_block"])
    title_like_heading = heading_like and not text_definition_link and not procedure_like
    bare_heading = title_like_heading and token_count <= 12 and not formula_like
    formula_lead_in = bool(
        formula_like
        and target_segment_kind != "paired_metric_formula"
        and (
            text.endswith("=")
            or text.endswith(":")
            or quote_surface.endswith("=")
            or quote_surface.endswith(":")
            or (token_count <= 10 and "=" in text)
        )
    )
    contamination_block = contamination_risk == "high"
    usable_evidence = bool(
        bool(row.get("quote_verified"))
        and provenance_status != "dropped"
        and not bool(row.get("doc_mismatch"))
    )
    special_definition_evidence = bool(
        bool(row.get("quote_verified"))
        and provenance_status != "dropped"
        and not contamination_block
        and not question_like
        and not bare_heading
    )
    long_enough_prose = len(text) >= 80 or text.count(".") >= 1
    exact_named_equality_formula = _exact_named_equality_formula(
        row=row,
        text=text,
        quote_surface=quote_surface,
        formula_like=formula_like,
        special_definition_evidence=special_definition_evidence,
    )
    theorem_statement_or_equation = _theorem_statement_or_equation(
        row=row,
        source_block_text=source_block_text,
        heading_like=heading_like,
        formula_like=formula_like,
        special_definition_evidence=special_definition_evidence,
        long_enough_prose=long_enough_prose,
    )
    formula_backed_explanatory_clause = _formula_backed_explanatory_clause(
        row=row,
        source_block_text=source_block_text,
        heading_like=heading_like,
        formula_like=formula_like,
        special_definition_evidence=special_definition_evidence,
        long_enough_prose=long_enough_prose,
    )
    anchored_descriptive_clause = _anchored_descriptive_clause(
        row=row,
        text=text,
        source_block_text=source_block_text,
        text_norm=text_norm,
        usable_evidence=usable_evidence,
        contamination_block=contamination_block,
        question_like=question_like,
        bare_heading=bare_heading,
        heading_like=heading_like,
        supportive_context=supportive_context,
        long_enough_prose=long_enough_prose,
        anchor_strength=anchor_strength,
        target_segment_extracted=target_segment_extracted,
    )
    prose_definition_surface = bool(
        usable_evidence
        and not contamination_block
        and not bare_heading
        and not title_like_heading
        and not formula_lead_in
        and not question_like
        and not formula_like
        and token_count >= 8
        and (definition_signal or long_enough_prose)
        and (supportive_context or anchor_strength == "strong")
        and not upstream_formula_auxiliary_only
    )
    positive_surface_type = ""
    if exact_named_equality_formula:
        positive_surface_type = "named_formula"
    elif theorem_statement_or_equation:
        positive_surface_type = "theorem_statement"
    elif formula_backed_explanatory_clause:
        positive_surface_type = "formula_backed_explanatory_clause"
    elif anchored_descriptive_clause:
        positive_surface_type = "anchored_descriptive_clause"
    elif prose_definition_surface:
        positive_surface_type = "prose_definition"

    background_drift_tolerated = bool(
        background_drift_class in tolerated_background_drift_classes()
        and anchor_strength == "strong"
        and positive_surface_type
        and not concept_mix_block
    )
    background_drift_block = bool(
        background_drift_class != "none" and not background_drift_tolerated
    )
    special_definition_support = bool(
        positive_surface_type
        and not background_drift_block
        and not concept_mix_block
    )
    explanatory_candidate = bool(
        prose_definition_surface
        and not background_drift_block
        and not concept_mix_block
    )
    definition_candidate = bool(
        special_definition_support
        and not (
            upstream_formula_auxiliary_only
            and positive_surface_type not in {"named_formula", "theorem_statement"}
        )
        and (
            positive_surface_type != "prose_definition"
            or not procedure_like
        )
    )
    context_candidate = bool(
        explanatory_candidate
        or (
            usable_evidence
            and upstream_support_role in {"explanatory_anchor", "context_completion_anchor"}
            and upstream_anchor_quality in {"strong", "usable"}
        )
    )
    formula_candidate = bool(
        usable_evidence
        and not background_drift_block
        and not concept_mix_block
        and formula_like
        and token_count >= 4
    )
    equation_support = bool(
        formula_candidate
        and not title_like_heading
        and not formula_lead_in
        and not question_like
        and not contamination_block
    )
    scope_signal = _scope_signal(text_norm)

    selection_score = _safe_float(row.get("alignment_score"))
    if usable_evidence:
        selection_score += 2.0
    if supportive_context:
        selection_score += 1.0
    if name_support:
        selection_score += 0.75
    if upstream_support_role == "definitional_anchor":
        selection_score += 3.0 if upstream_anchor_quality == "strong" else 1.5
    elif upstream_support_role in {"explanatory_anchor", "context_completion_anchor"}:
        selection_score += 1.5
    if upstream_context_completion_available:
        selection_score += 0.75
    if definition_candidate:
        selection_score += 3.0
    elif context_candidate:
        selection_score += 1.5
    if formula_backed_explanatory_clause:
        selection_score -= 3.0
    if equation_support:
        selection_score += 1.0
    if upstream_formula_auxiliary_only:
        selection_score -= 4.0
    if provenance_status == "substituted":
        selection_score -= 0.5
    if provenance_status == "recovered":
        selection_score -= 0.25
    if bare_heading:
        selection_score -= 6.0
    if formula_lead_in:
        selection_score -= 5.0
    if question_like:
        selection_score -= 3.0
    if heading_like and not definition_candidate:
        selection_score -= 2.0
    if contamination_block:
        selection_score -= 3.5
    if background_drift_tolerated:
        selection_score -= 4.0
    elif background_drift_block:
        selection_score -= 8.0
    if concept_mix_block:
        selection_score -= 8.0
    if provenance_status == "dropped":
        selection_score -= 100.0

    exclusion_reasons: List[str] = []
    if not usable_evidence:
        exclusion_reasons.append("unusable_evidence")
    if title_like_heading:
        exclusion_reasons.append("heading_like")
    if bare_heading:
        exclusion_reasons.append("bare_heading")
    if formula_lead_in:
        exclusion_reasons.append("formula_lead_in")
    if question_like:
        exclusion_reasons.append("question_like")
    if contamination_block:
        exclusion_reasons.append("high_contamination")
    if background_drift_block:
        exclusion_reasons.append(f"background_drift_{background_drift_class}")
    if concept_mix_block:
        exclusion_reasons.append(concept_mix_risk)
    if procedure_like and not definition_signal:
        exclusion_reasons.append("procedure_context_only")

    classification = "weak_support"
    if definition_candidate:
        classification = "definition_support"
    elif context_candidate:
        classification = "context_support"
    elif equation_support:
        classification = "equation_support"
    elif formula_candidate:
        classification = "formula_only_support"
    elif title_like_heading:
        classification = "heading_only"

    return {
        "overlay_candidate_id": str(row.get("overlay_candidate_id") or ""),
        "candidate_text": text,
        "candidate_text_norm": text_norm.strip(),
        "token_count": token_count,
        "target_segment_extracted": target_segment_extracted,
        "target_segment_kind": target_segment_kind,
        "usable_evidence": usable_evidence,
        "definition_signal": definition_signal,
        "scope_signal": scope_signal,
        "title_like_heading": title_like_heading,
        "bare_heading": bare_heading,
        "formula_lead_in": formula_lead_in,
        "question_like": question_like,
        "contamination_block": contamination_block,
        "anchor_strength": anchor_strength,
        "background_drift_class": background_drift_class,
        "concept_mix_risk": concept_mix_risk,
        "background_drift_block": background_drift_block,
        "background_drift_tolerated": background_drift_tolerated,
        "concept_mix_block": concept_mix_block,
        "positive_surface_type": positive_surface_type,
        "exact_named_equality_formula": exact_named_equality_formula,
        "theorem_statement_or_equation": theorem_statement_or_equation,
        "formula_backed_explanatory_clause": formula_backed_explanatory_clause,
        "anchored_descriptive_clause": anchored_descriptive_clause,
        "definition_candidate": definition_candidate,
        "context_candidate": context_candidate,
        "equation_support": equation_support,
        "formula_candidate": formula_candidate,
        "upstream_support_role": upstream_support_role,
        "upstream_anchor_quality": upstream_anchor_quality,
        "upstream_formula_auxiliary_only": upstream_formula_auxiliary_only,
        "upstream_context_completion_available": upstream_context_completion_available,
        "classification": classification,
        "selection_score": round(selection_score, 6),
        "exclusion_reasons": unique_preserve_order(exclusion_reasons),
    }


def _support_pack_row_distance(
    left_row: Mapping[str, Any],
    right_row: Mapping[str, Any],
) -> int | None:
    if str(left_row.get("doc_id") or "") != str(right_row.get("doc_id") or ""):
        return None
    left_page = left_row.get("page_index")
    right_page = right_row.get("page_index")
    if isinstance(left_page, int) and isinstance(right_page, int) and int(left_page) != int(right_page):
        return None
    left_block_match = re.search(r"(\d+)(?!.*\d)", str(left_row.get("block_id") or ""))
    right_block_match = re.search(r"(\d+)(?!.*\d)", str(right_row.get("block_id") or ""))
    if left_block_match is None or right_block_match is None:
        return 0 if str(left_row.get("block_id") or "") == str(right_row.get("block_id") or "") else None
    return abs(int(left_block_match.group(1)) - int(right_block_match.group(1)))


def _definition_support_pack_variants(
    row: Mapping[str, Any],
    assessment: Mapping[str, Any],
) -> List[Tuple[str, str]]:
    candidate_text = normalize_ws(assessment.get("candidate_text") or _candidate_text(row))
    variants: List[Tuple[str, str]] = []
    if candidate_text:
        variants.append((candidate_text, "candidate_text"))

    target_segment = _extract_same_kc_sentence_segment(row=row)
    target_segment_text = normalize_ws(target_segment.get("text") or "")
    target_segment_kind = str(target_segment.get("kind") or "")
    if target_segment_text:
        variants.append((target_segment_text, target_segment_kind or "same_kc_segment"))

    for source_kind, raw_source in (
        ("quote", normalize_ws(row.get("quote_surface") or "")),
        ("source_block", normalize_ws(row.get("source_block_text") or "")),
    ):
        if not raw_source:
            continue
        variants.extend(_same_kc_sentence_variants(row, raw_source, source_kind=source_kind))

    deduped: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for text, kind in variants:
        normalized = normalize_ws(text)
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        seen.add(key)
        deduped.append((normalized, kind))
    return deduped


def _definition_support_pack_variant_allowed(
    *,
    row: Mapping[str, Any],
    assessment: Mapping[str, Any],
    text: str,
) -> Tuple[bool, float]:
    normalized = normalize_ws(text)
    lowered = normalized.lower()
    if not normalized:
        return False, 0.0
    if not bool(assessment.get("usable_evidence")):
        return False, 0.0
    if (
        bool(assessment.get("question_like"))
        or bool(assessment.get("bare_heading"))
        or bool(assessment.get("contamination_block"))
        or bool(assessment.get("background_drift_block"))
        or bool(assessment.get("concept_mix_block"))
    ):
        return False, 0.0
    if _question_like(normalized):
        return False, 0.0
    if _starts_with_any(lowered, SAME_KC_CONTEXT_LEAD_INS):
        return False, 0.0
    if _starts_with_any(lowered, GENERIC_BACKGROUND_PREFIXES):
        return False, 0.0
    if _starts_with_any(lowered, GENERIC_CONTEXT_LEAD_INS):
        return False, 0.0
    if _looks_same_kc_sentence_fragment(normalized):
        return False, 0.0
    token_count = len(tokenize(_normalized_text(normalized)))
    if token_count < 5 or token_count > 46:
        return False, 0.0
    extended_issues = set(_definition_extended_issue_codes(row, assessment, normalized))
    if extended_issues.intersection(
        {
            "citation_or_slide_context",
            "ocr_noise",
            "traceback_noise",
            "generic_background",
            "procedural_fragment",
            "question_like",
        }
    ):
        return False, 0.0
    relation_score = _anchored_same_kc_relation_score(normalized, row)
    text_norm = f" {_normalized_text(normalized)} "
    has_relation_cue = bool(
        _text_has_any_cue(text_norm, DIRECT_EXPLANATORY_CUES)
        or _text_has_any_cue(text_norm, (" called ", " known as ", " defined as ", " refers to ", " denotes "))
    )
    title_overlap, _, has_name_anchor = _definition_alignment_features(row, normalized)
    formulaish = bool(
        assessment.get("exact_named_equality_formula")
        or assessment.get("theorem_statement_or_equation")
        or assessment.get("formula_backed_explanatory_clause")
        or (assessment.get("equation_support") and "=" in normalized)
    )
    strong_target_alignment = bool(has_name_anchor or title_overlap >= 2)
    if not (
        relation_score > 0.0
        or formulaish
        or (bool(assessment.get("definition_candidate")) and has_relation_cue)
        or (bool(assessment.get("context_candidate")) and has_relation_cue)
    ):
        return False, 0.0
    if not (relation_score > 0.0 or strong_target_alignment or formulaish):
        return False, 0.0
    return True, relation_score


def _definition_support_pack_variant_score(
    *,
    row: Mapping[str, Any],
    assessment: Mapping[str, Any],
    text: str,
    kind: str,
    relation_score: float,
) -> Tuple[float, bool]:
    normalized = normalize_ws(text)
    support_profile = _support_profile(row)
    upstream_support_role = str(support_profile.get("preferred_support_role") or "other")
    upstream_anchor_quality = str(support_profile.get("anchor_quality") or "weak")
    upstream_formula_auxiliary_only = bool(support_profile.get("formula_auxiliary_only", False))
    raw_candidate_text = normalize_ws(assessment.get("candidate_text") or "")
    token_count = len(tokenize(_normalized_text(normalized)))
    shortened = bool(raw_candidate_text and normalized != raw_candidate_text and len(normalized) + 12 <= len(raw_candidate_text))
    positive_surface_type = str(assessment.get("positive_surface_type") or "")
    formulaish = bool(
        assessment.get("exact_named_equality_formula")
        or assessment.get("theorem_statement_or_equation")
        or assessment.get("formula_backed_explanatory_clause")
        or (assessment.get("equation_support") and "=" in normalized)
    )

    score = float(assessment.get("selection_score") or 0.0)
    score += 4.0 * relation_score
    if bool(assessment.get("definition_candidate")):
        score += 3.0
    elif bool(assessment.get("context_candidate")):
        score += 1.5
    elif bool(assessment.get("equation_support")):
        score += 0.5

    if upstream_support_role == "definitional_anchor":
        score += 4.0 if upstream_anchor_quality == "strong" else 2.0
    elif upstream_support_role in {"explanatory_anchor", "context_completion_anchor"}:
        score += 1.5
    if bool(support_profile.get("has_context_completion_source", False)):
        score += 1.0

    if positive_surface_type == "prose_definition":
        score += 3.5
    elif positive_surface_type == "anchored_descriptive_clause":
        score += 3.0
    elif positive_surface_type == "formula_backed_explanatory_clause":
        score += 2.0
    elif positive_surface_type in {"named_formula", "theorem_statement"}:
        score += 1.0

    if "heading_continuation" in kind or "tail_sentence" in kind:
        score += 2.0
    elif "same_kc_segment" in kind:
        score += 1.5

    if shortened:
        score += 2.5
    if bool(assessment.get("target_segment_extracted")) and normalized == raw_candidate_text:
        score += 1.0

    if 8 <= token_count <= 28:
        score += 2.5
    elif token_count <= 36:
        score += 1.0
    else:
        score -= 1.0

    if upstream_formula_auxiliary_only:
        score -= 2.0 if relation_score <= 0.0 else 0.75
    if formulaish and relation_score <= 0.0:
        score -= 0.5

    return round(score, 6), formulaish


def select_definition_support_pack(
    rows_by_id: Mapping[str, Mapping[str, Any]],
    assessments_by_id: Mapping[str, Mapping[str, Any]],
    *,
    target_kc_id: str,
    max_pack_size: int = 3,
) -> List[Dict[str, Any]]:
    if max_pack_size <= 0:
        return []

    best_by_id: Dict[str, Dict[str, Any]] = {}
    for candidate_id, row in rows_by_id.items():
        if str(row.get("kc_id") or "") != str(target_kc_id):
            continue
        assessment = dict(assessments_by_id.get(candidate_id) or {})
        if not assessment:
            continue
        if not (
            bool(assessment.get("definition_candidate"))
            or bool(assessment.get("context_candidate"))
            or bool(assessment.get("equation_support"))
            or bool(assessment.get("formula_candidate"))
        ):
            continue

        best_item: Dict[str, Any] = {}
        for text, kind in _definition_support_pack_variants(row, assessment):
            allowed, relation_score = _definition_support_pack_variant_allowed(
                row=row,
                assessment=assessment,
                text=text,
            )
            if not allowed:
                continue
            score, formulaish = _definition_support_pack_variant_score(
                row=row,
                assessment=assessment,
                text=text,
                kind=kind,
                relation_score=relation_score,
            )
            current = {
                "overlay_candidate_id": str(candidate_id),
                "candidate_text": normalize_ws(text),
                "support_pack_kind": str(kind),
                "support_pack_score": score,
                "relation_score": round(float(relation_score), 6),
                "formulaish": bool(formulaish),
                "source_text_field": _candidate_source_text_field(row),
                "text_changed": normalize_ws(text) != normalize_ws(assessment.get("candidate_text") or ""),
                "row": dict(row),
            }
            if not best_item or float(current["support_pack_score"]) > float(best_item["support_pack_score"]):
                best_item = current
        if best_item:
            best_by_id[str(candidate_id)] = best_item

    ranked = list(best_by_id.values())
    for item in ranked:
        row = dict(item.get("row") or {})
        relation_score = float(item.get("relation_score") or 0.0)
        formulaish = bool(item.get("formulaish"))
        nearby_formula_gloss_bonus = 0.0
        for other in ranked:
            if str(other.get("overlay_candidate_id") or "") == str(item.get("overlay_candidate_id") or ""):
                continue
            distance = _support_pack_row_distance(row, dict(other.get("row") or {}))
            if distance is None or distance > 2:
                continue
            other_relation = float(other.get("relation_score") or 0.0)
            other_formulaish = bool(other.get("formulaish"))
            if formulaish and other_relation > 0.0:
                nearby_formula_gloss_bonus = max(nearby_formula_gloss_bonus, 1.5 if distance <= 1 else 0.75)
            elif relation_score > 0.0 and other_formulaish:
                nearby_formula_gloss_bonus = max(nearby_formula_gloss_bonus, 1.0 if distance <= 1 else 0.5)
        item["support_pack_score"] = round(float(item.get("support_pack_score") or 0.0) + nearby_formula_gloss_bonus, 6)

    ranked.sort(
        key=lambda item: (
            -float(item.get("support_pack_score") or 0.0),
            -float(item.get("relation_score") or 0.0),
            str(item.get("overlay_candidate_id") or ""),
        )
    )
    return [
        {
            key: value
            for key, value in item.items()
            if key != "row"
        }
        for item in ranked[: max(1, int(max_pack_size))]
    ]


def _candidate_value(
    *,
    text: str,
    supporting_ids: Sequence[str],
    selection_reason: str,
    source_text_field: str,
) -> Dict[str, Any]:
    return {
        "status": "grounded",
        "text": text,
        "supporting_overlay_candidate_ids": [str(item) for item in supporting_ids],
        "selection_reason": selection_reason,
        "source_text_field": source_text_field,
    }


def _abstained_value(*, field_name: str, reasons: Sequence[str]) -> Dict[str, Any]:
    return {
        "status": "abstained",
        "text": "",
        "supporting_overlay_candidate_ids": [],
        "selection_reason": f"{field_name}_abstained",
        "hold_reasons": [str(item) for item in reasons],
        "source_text_field": "",
    }


def select_evidence_bundle(
    rows: Sequence[Mapping[str, Any]],
    *,
    max_bundle_size: int,
    max_explanatory_candidates: int,
    assessments_by_id: Mapping[str, Mapping[str, Any]] | None = None,
    prioritized_candidate_ids: Sequence[str] | None = None,
    blocked_candidate_ids: Sequence[str] | None = None,
) -> Dict[str, Any]:
    if assessments_by_id is None:
        assessed_rows: List[Tuple[Mapping[str, Any], Dict[str, Any]]] = [
            (row, assess_overlay_candidate(row))
            for row in rows
        ]
    else:
        assessed_rows = [
            (
                row,
                dict(
                    assessments_by_id.get(str(row.get("overlay_candidate_id") or ""))
                    or assess_overlay_candidate(row)
                ),
            )
            for row in rows
        ]
    assessed_rows.sort(
        key=lambda item: (
            -float(item[1].get("selection_score") or 0.0),
            str(item[0].get("overlay_candidate_id") or ""),
        )
    )

    selected: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    seen_text_keys: set[str] = set()
    explanatory_count = 0
    equation_count = 0
    by_id = {
        str(row.get("overlay_candidate_id") or ""): (row, assessment)
        for row, assessment in assessed_rows
    }
    ordered_priorities = [
        str(item)
        for item in unique_preserve_order(prioritized_candidate_ids or [])
        if str(item)
    ]
    blocked_ids = {
        str(item)
        for item in unique_preserve_order(blocked_candidate_ids or [])
        if str(item)
    }

    def _append_selected(row: Mapping[str, Any], assessment: Mapping[str, Any], bundle_role: str) -> None:
        selected.append(
            {
                "bundle_role": bundle_role,
                "overlay_candidate_id": str(row.get("overlay_candidate_id") or ""),
                "selection_score": float(assessment["selection_score"]),
                "candidate_text": assessment["candidate_text"],
                "quote_surface": normalize_ws(row.get("quote_surface") or ""),
                "source_block_text": normalize_ws(row.get("source_block_text") or ""),
                "doc_id": str(row.get("doc_id") or ""),
                "block_id": str(row.get("block_id") or ""),
                "page_index": row.get("page_index"),
                "sentence_id": str(row.get("sentence_id") or ""),
                "layer": str(row.get("layer") or ""),
                "alignment_score": _safe_float(row.get("alignment_score")),
                "contamination_risk": str(row.get("contamination_risk") or ""),
                "provenance_normalization_status": str(row.get("provenance_normalization_status") or ""),
                "quote_verification_status": str(row.get("quote_verification_status") or ""),
                "assessment": {
                    "classification": str(assessment["classification"]),
                    "definition_signal": bool(assessment["definition_signal"]),
                    "scope_signal": bool(assessment["scope_signal"]),
                    "bare_heading": bool(assessment["bare_heading"]),
                    "formula_lead_in": bool(assessment["formula_lead_in"]),
                    "question_like": bool(assessment["question_like"]),
                },
            }
        )

    def _try_select(row: Mapping[str, Any], assessment: Mapping[str, Any], *, prioritize: bool) -> None:
        nonlocal explanatory_count, equation_count
        reasons: List[str] = []
        candidate_id = str(row.get("overlay_candidate_id") or "")
        dedupe_key = _dedupe_key(row)
        if candidate_id in blocked_ids:
            reasons.append("definition_verifier_bundle_block")
        if dedupe_key in seen_text_keys:
            reasons.append("duplicate_text")
        if len(selected) >= max_bundle_size:
            reasons.append("bundle_capacity_reached")

        bundle_role = ""
        if not reasons and assessment["definition_candidate"] and explanatory_count < max_explanatory_candidates:
            bundle_role = "definition_support" if explanatory_count == 0 else "context_support"
            explanatory_count += 1
        elif not reasons and assessment["context_candidate"] and explanatory_count < max_explanatory_candidates:
            bundle_role = "context_support"
            explanatory_count += 1
        elif not reasons and assessment["equation_support"] and equation_count < 1:
            bundle_role = "equation_support"
            equation_count += 1
        elif not reasons and prioritize and bool(assessment.get("usable_evidence")):
            bundle_role = "context_support"
        else:
            if explanatory_count >= max_explanatory_candidates and (
                assessment["definition_candidate"] or assessment["context_candidate"]
            ):
                reasons.append("explanatory_capacity_reached")
            reasons.extend(list(assessment["exclusion_reasons"]))
            if not (
                assessment["definition_candidate"]
                or assessment["context_candidate"]
                or assessment["equation_support"]
            ):
                reasons.append("not_selected_for_bundle")

        if bundle_role:
            seen_text_keys.add(dedupe_key)
            _append_selected(row, assessment, bundle_role)
            return

        excluded.append(
            {
                "overlay_candidate_id": str(row.get("overlay_candidate_id") or ""),
                "selection_score": float(assessment["selection_score"]),
                "classification": str(assessment["classification"]),
                "exclusion_reasons": unique_preserve_order([reason for reason in reasons if reason]),
            }
        )

    priority_seen: set[str] = set()
    for candidate_id in ordered_priorities:
        pair = by_id.get(candidate_id)
        if pair is None or candidate_id in priority_seen:
            continue
        priority_seen.add(candidate_id)
        row, assessment = pair
        _try_select(row, assessment, prioritize=True)

    for row, assessment in assessed_rows:
        candidate_id = str(row.get("overlay_candidate_id") or "")
        if candidate_id in priority_seen:
            continue
        _try_select(row, assessment, prioritize=False)

    excluded_by_reason: Counter[str] = Counter()
    for item in excluded:
        for reason in item["exclusion_reasons"]:
            excluded_by_reason[str(reason)] += 1

    return {
        "selected": selected,
        "excluded": excluded,
        "excluded_by_reason": dict(sorted(excluded_by_reason.items())),
        "assessments_by_id": {
            str(assessment["overlay_candidate_id"]): assessment
            for _, assessment in assessed_rows
        },
    }



STAGE3_V3_EVIDENCE_PACK_VERSION = "step5x_v3_evidence_packs_v1"
STAGE3_V3_DEFINITION_ROLES = {"definition_kernel", "explanatory_gloss"}


def _stage3_v3_pack_active(exemplar: Mapping[str, Any]) -> bool:
    return (
        bool(exemplar.get("evidence_pack_available", False))
        and str(exemplar.get("evidence_pack_version") or "") == STAGE3_V3_EVIDENCE_PACK_VERSION
    )


def _stage3_v3_pack_has_drafting_core(exemplar: Mapping[str, Any]) -> bool:
    return bool(has_automatic_drafting_support(exemplar))


def _stage3_v3_pack_route(exemplar: Mapping[str, Any]) -> str:
    quality = dict(exemplar.get("evidence_pack_quality") or {})
    route = str(quality.get("route") or "")
    if _stage3_v3_pack_active(exemplar) and not _stage3_v3_pack_has_drafting_core(exemplar):
        return "insufficient_support_packet"
    return route


def _stage3_v3_ordered_definition_row(row: Mapping[str, Any]) -> bool:
    membership = dict(row.get("evidence_pack_membership") or {})
    lane_semantics = dict(row.get("evidence_lane_semantics") or {})
    if lane_semantics and not bool(lane_semantics.get("automatic_drafting_supported", False)):
        return False
    if membership.get("selected_for_drafting_core") is False and lane_semantics:
        # Keep compatibility with older packs where lane membership cannot be
        # mapped to a specific overlay row, but fail closed when the whole pack
        # has no drafting core.
        if not bool(lane_semantics.get("automatic_drafting_supported", False)):
            return False
    if not bool(membership.get("selected_for_pack", False)):
        return False

    ordered_positions = membership.get("ordered_pack_positions") or []
    if not ordered_positions:
        return False

    slot_roles = {str(role) for role in membership.get("slot_roles") or [] if str(role)}
    if not slot_roles.intersection(STAGE3_V3_DEFINITION_ROLES):
        return False

    return True


def _stage3_v3_definition_entry_allowed(
    entry: Mapping[str, Any],
    *,
    rows_by_id: Mapping[str, Mapping[str, Any]],
    exemplar: Mapping[str, Any],
) -> bool:
    """Fail-closed definition-field gate for Step 5x v3 evidence packs.

    Stage 5x v3 already decided which evidence is safe for drafting. Step 6.7
    must not promote context_completion, sibling_contrast, or non-pack rows into
    definition_full_candidate / definition_short_candidate.
    """
    if not _stage3_v3_pack_active(exemplar):
        return True

    if _stage3_v3_pack_route(exemplar) == "insufficient_support_packet":
        return False

    candidate_id = str(
        entry.get("candidate_id")
        or entry.get("overlay_candidate_id")
        or ""
    )
    if not candidate_id:
        return False

    row = dict(rows_by_id.get(candidate_id) or {})
    if not row:
        return False

    return _stage3_v3_ordered_definition_row(row)


def _filter_stage3_v3_definition_entries(
    definition_entries: Sequence[Mapping[str, Any]],
    *,
    rows_by_id: Mapping[str, Mapping[str, Any]],
    exemplar: Mapping[str, Any],
) -> List[Mapping[str, Any]]:
    if not _stage3_v3_pack_active(exemplar):
        return list(definition_entries)

    return [
        entry
        for entry in definition_entries
        if _stage3_v3_definition_entry_allowed(
            entry,
            rows_by_id=rows_by_id,
            exemplar=exemplar,
        )
    ]



def _stage3_v3_allowed_definition_slot_lookup(
    exemplar: Mapping[str, Any],
) -> Dict[str, Dict[str, str]]:
    """Map Stage 3 pack candidate IDs to the exact text approved for definition drafting."""
    lookup: Dict[str, Dict[str, str]] = {}

    slots = dict(exemplar.get("evidence_pack_slots") or {})
    for role in STAGE3_V3_DEFINITION_ROLES:
        for item in slots.get(role) or []:
            if not isinstance(item, Mapping):
                continue
            candidate_id = str(
                item.get("candidate_id")
                or item.get("source_candidate_id")
                or ""
            )
            text = normalize_ws(item.get("text") or item.get("quote") or "")
            if candidate_id and text:
                lookup[candidate_id] = {
                    "text": text,
                    "role": str(role),
                    "source": f"evidence_pack_slots.{role}.text",
                }

    for item in exemplar.get("ordered_pack_for_drafting") or []:
        if not isinstance(item, Mapping):
            continue
        role = str(item.get("role") or "")
        if role not in STAGE3_V3_DEFINITION_ROLES:
            continue
        candidate_id = str(
            item.get("candidate_id")
            or item.get("source_candidate_id")
            or ""
        )
        text = normalize_ws(item.get("text") or item.get("quote") or "")
        if candidate_id and text:
            lookup[candidate_id] = {
                "text": text,
                "role": role,
                "source": "ordered_pack_for_drafting.text",
            }

    return lookup


def _stage3_v3_definition_slot_surface_for_overlay_candidate(
    overlay_candidate_id: str,
    *,
    rows_by_id: Mapping[str, Mapping[str, Any]],
    exemplar: Mapping[str, Any],
) -> Dict[str, str]:
    row = dict(rows_by_id.get(str(overlay_candidate_id) or "") or {})
    if not row:
        return {}

    membership = dict(row.get("evidence_pack_membership") or {})
    pack_candidate_id = str(membership.get("pack_candidate_id") or "")
    if not pack_candidate_id:
        return {}

    lookup = _stage3_v3_allowed_definition_slot_lookup(exemplar)
    return dict(lookup.get(pack_candidate_id) or {})


def _clamp_stage3_v3_definition_candidate_text(
    candidate: Mapping[str, Any],
    *,
    rows_by_id: Mapping[str, Mapping[str, Any]],
    exemplar: Mapping[str, Any],
    field_name: str,
) -> Dict[str, Any]:
    """For v3 packs, keep definition text at the exact Stage 3 slot surface.

    The boundary filter decides which overlay row may support a definition.
    This clamp decides which text surface is allowed to be emitted. Without this,
    Step 6.7 can still select a correct v3 row but expand it to source_block_text,
    which is too broad for reviewer-facing definition fields.
    """
    out = dict(candidate or {})

    if not _stage3_v3_pack_active(exemplar):
        return out

    if str(out.get("status") or "") != "grounded":
        return out

    supporting_ids = [
        str(item)
        for item in out.get("supporting_overlay_candidate_ids") or []
        if str(item)
    ]

    for overlay_candidate_id in supporting_ids:
        slot_surface = _stage3_v3_definition_slot_surface_for_overlay_candidate(
            overlay_candidate_id,
            rows_by_id=rows_by_id,
            exemplar=exemplar,
        )
        slot_text = normalize_ws(slot_surface.get("text") or "")
        if slot_text:
            original_text = normalize_ws(out.get("text") or "")
            out["text"] = slot_text
            out["source_text_field"] = str(slot_surface.get("source") or "evidence_pack_slots.definition.text")
            out["selection_reason"] = f"stage3_v3_exact_pack_surface_for_{field_name}"
            out["stage3_v3_surface_clamp"] = {
                "applied": True,
                "role": str(slot_surface.get("role") or ""),
                "source": str(slot_surface.get("source") or ""),
                "original_text_changed": original_text != slot_text,
                "original_text_length": len(original_text),
                "clamped_text_length": len(slot_text),
            }
            return out

    return out


def _choose_definition_full_candidate(
    definition_entries: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    if not definition_entries:
        return {}
    best = dict(definition_entries[0])
    candidate_id = str(best.get("candidate_id") or "")
    row = dict(best.get("row") or {})
    text = str(best.get("text") or "")
    return _candidate_value(
        text=text,
        supporting_ids=[candidate_id],
        selection_reason="best_surface_from_all_assessed_rows",
        source_text_field=_candidate_source_text_field(row),
    )


def _choose_definition_short_candidate(
    definition_full_candidate: Mapping[str, Any],
    definition_entries: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    if str(definition_full_candidate.get("status") or "") != "grounded":
        return {}

    full_text = str(definition_full_candidate.get("text") or "")
    full_ids = [str(item) for item in definition_full_candidate.get("supporting_overlay_candidate_ids") or []]
    if full_text and len(tokenize(_normalized_text(full_text))) <= 32:
        source_row = {}
        if full_ids:
            for entry in definition_entries:
                if str(entry.get("candidate_id") or "") == full_ids[0]:
                    source_row = dict(entry.get("row") or {})
                    break
        return _candidate_value(
            text=full_text,
            supporting_ids=full_ids,
            selection_reason="same_as_definition_full_candidate",
            source_text_field=_candidate_source_text_field(source_row),
        )

    for entry in definition_entries:
        candidate_id = str(entry.get("candidate_id") or "")
        if candidate_id in full_ids:
            continue
        text = str(entry.get("text") or "")
        token_count = len(tokenize(_normalized_text(text)))
        if text and 8 <= token_count <= 24 and len(text) <= 180:
            row = dict(entry.get("row") or {})
            return _candidate_value(
                text=text,
                supporting_ids=[candidate_id],
                selection_reason="short_extractive_definition_support_from_all_assessed_rows",
                source_text_field=_candidate_source_text_field(row),
            )
    return {}


def _choose_scope_candidate(

    definition_full_candidate: Mapping[str, Any],
    rows_by_id: Mapping[str, Mapping[str, Any]],
    assessments_by_id: Mapping[str, Mapping[str, Any]],
    selected_bundle: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    seen_candidate_ids: set[str] = set()
    for item in selected_bundle:
        candidate_id = str(item.get("overlay_candidate_id") or "")
        seen_candidate_ids.add(candidate_id)
        assessment = dict(assessments_by_id.get(candidate_id) or {})
        row = dict(rows_by_id.get(candidate_id) or {})
        if not _selected_grounded_scope_support(row, assessment):
            continue
        text = str(assessment.get("candidate_text") or "")
        if not text:
            continue
        return _candidate_value(
            text=text,
            supporting_ids=[candidate_id],
            selection_reason="scope_use_context_from_selected_grounded_support",
            source_text_field=_candidate_source_text_field(row),
        )

    assessed_rows = sorted(
        rows_by_id.items(),
        key=lambda item: (
            -float((assessments_by_id.get(item[0]) or {}).get("selection_score") or 0.0),
            str(item[0]),
        ),
    )
    for candidate_id, row in assessed_rows:
        if candidate_id in seen_candidate_ids:
            continue
        assessment = dict(assessments_by_id.get(candidate_id) or {})
        if not _selected_grounded_scope_support(row, assessment):
            continue
        text = str(assessment.get("candidate_text") or "")
        if not text:
            continue
        return _candidate_value(
            text=text,
            supporting_ids=[candidate_id],
            selection_reason="scope_use_context_from_all_assessed_rows",
            source_text_field=_candidate_source_text_field(row),
        )
    return {}


def _support_summary(
    rows: Sequence[Mapping[str, Any]],
    selection: Mapping[str, Any],
    definition_full_candidate: Mapping[str, Any],
) -> Dict[str, Any]:
    assessments_by_id = dict(selection.get("assessments_by_id") or {})
    selected_bundle = list(selection.get("selected") or [])
    review_queue_hit = any(bool((row.get("step5_3_review_queue_aux") or {}).get("in_review_queue")) for row in rows)

    counts = Counter()
    selected_bundle_high_contamination = 0
    selected_bundle_provenance_repairs = 0
    for item in selected_bundle:
        if str(item.get("contamination_risk") or "") == "high":
            selected_bundle_high_contamination += 1
        if str(item.get("provenance_normalization_status") or "") not in {"", "original"}:
            selected_bundle_provenance_repairs += 1

    for row in rows:
        candidate_id = str(row.get("overlay_candidate_id") or "")
        assessment = dict(assessments_by_id.get(candidate_id) or {})
        if assessment.get("usable_evidence"):
            counts["usable_evidence_candidates"] += 1
        if assessment.get("definition_candidate"):
            counts["definition_support_candidates"] += 1
        if assessment.get("context_candidate"):
            counts["context_support_candidates"] += 1
        if assessment.get("equation_support"):
            counts["equation_support_candidates"] += 1
        if assessment.get("formula_candidate"):
            counts["formula_candidates"] += 1
        if assessment.get("title_like_heading"):
            counts["bare_heading_candidates"] += 1
        if assessment.get("contamination_block"):
            counts["high_contamination_candidates"] += 1
        if str(row.get("provenance_normalization_status") or "") == "dropped":
            counts["dropped_provenance_candidates"] += 1

    selection_reason = str(definition_full_candidate.get("selection_reason") or "")
    strict_leaf_eligible = bool(
        definition_full_candidate.get("status") == "grounded"
        and selection_reason not in {
            "definition_full_candidate_single_span_fallback",
            "definition_full_candidate_completed_from_context",
        }
    )

    support_state = "insufficient_support"
    if definition_full_candidate.get("status") == "grounded":
        support_state = (
            "strict_leaf_support"
            if strict_leaf_eligible and counts["definition_support_candidates"] >= 1 and len(selected_bundle) >= 2
            else "grounded_single_quote"
        )
    elif counts["formula_candidates"] >= 1 and counts["definition_support_candidates"] == 0:
        support_state = "formula_only_support"
    elif counts["bare_heading_candidates"] >= 1 and counts["definition_support_candidates"] == 0:
        support_state = "heading_contaminated_support"

    return {
        "support_state": support_state,
        "total_overlay_candidates": len(rows),
        "selected_bundle_size": len(selected_bundle),
        "selected_bundle_high_contamination_candidates": selected_bundle_high_contamination,
        "selected_bundle_provenance_repair_candidates": selected_bundle_provenance_repairs,
        "review_queue_hit": review_queue_hit,
        **dict(sorted(counts.items())),
    }


def _field_provenance(
    *,
    field_value: Mapping[str, Any],
    source_set_ids: Sequence[str],
    source_run_ids: Sequence[str],
) -> Dict[str, Any]:
    return {
        "status": str(field_value.get("status") or "abstained"),
        "overlay_candidate_ids": [str(item) for item in field_value.get("supporting_overlay_candidate_ids") or []],
        "source_set_ids": [str(item) for item in source_set_ids],
        "source_run_ids": [str(item) for item in source_run_ids],
    }


def _definition_title_tokens(row: Mapping[str, Any]) -> set[str]:
    variants = " ".join(_candidate_name_variants(row))
    return _focus_tokens(variants)


def _hierarchy_context_surface(row: Mapping[str, Any]) -> str:
    canonical_name = normalize_ws(row.get("canonical_name") or "")
    alias_keys = {
        normalize_ws(item).lower()
        for item in row.get("aliases") or []
        if normalize_ws(item)
    }
    blocked_keys = {canonical_name.lower(), *alias_keys} if canonical_name else set(alias_keys)
    hierarchy_items = [
        normalize_ws(item)
        for item in row.get("source_hierarchy_path") or row.get("ancestor_labels") or []
        if normalize_ws(item)
    ]
    filtered_items = [item for item in hierarchy_items if item.lower() not in blocked_keys]
    return " ".join(filtered_items)


def _definition_context_tokens(row: Mapping[str, Any]) -> set[str]:
    # Active drafting uses typed hierarchy context rather than injected definition text.
    return _focus_tokens(_hierarchy_context_surface(row))


def _context_keyword_hits(row: Mapping[str, Any], text: str) -> int:
    return len(_focus_tokens(text) & _definition_context_tokens(row))


def _retrieval_metric(row: Mapping[str, Any], key: str) -> float:
    scores = dict(row.get("retrieval_scores") or {})
    return _safe_float(scores.get(key))


def _definition_alignment_features(row: Mapping[str, Any], text: str) -> tuple[int, int, bool]:
    text_tokens = _focus_tokens(text)
    title_overlap = len(text_tokens & _definition_title_tokens(row))
    context_overlap = len(text_tokens & _definition_context_tokens(row))
    has_name_anchor = _has_name_anchor(text, row)
    return title_overlap, context_overlap, has_name_anchor


def _natural_language_word_count(text: str) -> int:
    latex_stripped = re.sub(r"\[A-Za-z]+", " ", text)
    latex_stripped = re.sub(r"[_{}^$|]", " ", latex_stripped)
    return len(re.findall(r"[A-Za-z]{3,}", latex_stripped))


def _definition_surface_issue_codes(
    row: Mapping[str, Any],
    assessment: Mapping[str, Any],
    text: str,
) -> List[str]:
    lowered = _strip_leading_markers(text).lower()
    if not lowered:
        return ["empty_surface"]

    issues: List[str] = []
    exact_named_formula = bool(assessment.get("exact_named_equality_formula"))
    if not exact_named_formula and _starts_with_any(lowered, DEFINITION_FRAGMENT_PREFIXES):
        issues.append("fragment_lead_in")
    if _starts_with_any(lowered, GENERIC_BACKGROUND_PREFIXES) or " different types of " in f" {lowered} ":
        issues.append("generic_background")
    if not exact_named_formula and _starts_with_any(lowered, PROCEDURAL_FRAGMENT_PREFIXES):
        issues.append("procedural_fragment")
    if bool(row.get("is_procedure_like")) and " then do " in f" {lowered} ":
        issues.append("procedural_fragment")
    if not exact_named_formula and (
        bool(assessment.get("formula_lead_in"))
        or lowered.endswith(":")
        or lowered.endswith("=")
    ):
        issues.append("formula_lead_in")
    if (
        not exact_named_formula
        and not _looks_labeled_definition_clause(text)
        and not _text_has_any_cue(f" {_normalized_text(text)} ", DEFINITION_LINK_CUES)
        and "." not in text
        and "=" not in text
        and (bool(assessment.get("title_like_heading")) or bool(assessment.get("bare_heading")) or " - " in text or " – " in text or text.count(":") >= 2)
    ):
        issues.append("heading_like")
    if bool(assessment.get("question_like")):
        issues.append("question_like")
    if len(tokenize(_normalized_text(text))) > 48 and not exact_named_formula:
        issues.append("overlong_surface")
    return unique_preserve_order(issues)


def _definition_extended_issue_codes(
    row: Mapping[str, Any],
    assessment: Mapping[str, Any],
    text: str,
) -> List[str]:
    issues = list(_definition_surface_issue_codes(row, assessment, text))
    lowered = _strip_leading_markers(text).lower()
    title_overlap, context_overlap, has_name_anchor = _definition_alignment_features(row, text)
    rerank_margin = _retrieval_metric(row, "rerank_margin")
    natural_word_count = _natural_language_word_count(text)

    if "traceback" in lowered:
        issues.append("traceback_noise")
    if _starts_with_any(lowered, GENERIC_CONTEXT_LEAD_INS):
        issues.append("generic_context_lead_in")
    if " from section " in f" {lowered} " or " slideset from " in f" {lowered} ":
        issues.append("citation_or_slide_context")
    if any(marker in text for marker in REVIEWER_SURFACE_NOISE_MARKERS) or re.match(r"^[a-z][A-Z]", text):
        issues.append("ocr_noise")
    if (
        bool(assessment.get("equation_support"))
        and len(tokenize(_normalized_text(text))) > 20
        and len(re.findall(r"[$=\\{}_^|]", text)) >= 6
        and natural_word_count >= 8
        and not has_name_anchor
    ):
        issues.append("formula_dense_fragment")
    if not has_name_anchor and title_overlap <= 1 and context_overlap < 2:
        issues.append("weak_target_alignment")
    if (
        not has_name_anchor
        and title_overlap <= 1
        and context_overlap < 3
        and rerank_margin <= 0.0
        and not bool(assessment.get("exact_named_equality_formula"))
    ):
        issues.append("ambiguous_retrieval")
    return unique_preserve_order(issues)


def _definition_candidate_pool_eligible(
    row: Mapping[str, Any],
    assessment: Mapping[str, Any],
    text: str,
) -> bool:
    if not text:
        return False
    if not bool(assessment.get("usable_evidence")):
        return False
    if bool(assessment.get("contamination_block")) or bool(assessment.get("question_like")) or bool(assessment.get("bare_heading")):
        return False
    if bool(assessment.get("background_drift_block")) or bool(assessment.get("concept_mix_block")):
        return False
    if not (
        bool(assessment.get("definition_candidate"))
        or bool(assessment.get("context_candidate"))
        or bool(assessment.get("exact_named_equality_formula"))
        or bool(assessment.get("equation_support"))
    ):
        return False
    return True


def _definition_candidate_verdict(
    row: Mapping[str, Any],
    assessment: Mapping[str, Any],
    text: str,
) -> Dict[str, Any]:
    title_overlap, context_overlap, has_name_anchor = _definition_alignment_features(row, text)
    positive_surface_type = str(assessment.get("positive_surface_type") or "")
    reasons: List[str] = []
    if not _definition_candidate_pool_eligible(row, assessment, text):
        reasons.append("not_definition_candidate_pool")

    if not _definition_surface_passes_gate(row, assessment, text):
        reasons.append("surface_gate_rejected")

    extended_issues = _definition_extended_issue_codes(row, assessment, text)
    hard_blocking_codes = {
        "empty_surface",
        "generic_background",
        "procedural_fragment",
        "question_like",
        "generic_context_lead_in",
        "traceback_noise",
        "weak_target_alignment",
        "ambiguous_retrieval",
    }
    reasons.extend(code for code in extended_issues if code in hard_blocking_codes)

    if (
        "citation_or_slide_context" in extended_issues
        and not bool(assessment.get("exact_named_equality_formula"))
        and not bool(assessment.get("theorem_statement_or_equation"))
    ):
        reasons.append("citation_or_slide_context")

    if (
        "ocr_noise" in extended_issues
        and not bool(assessment.get("exact_named_equality_formula"))
        and (
            "citation_or_slide_context" in extended_issues
            or not has_name_anchor
            or title_overlap <= 1
        )
    ):
        reasons.append("ocr_noise")

    if (
        "formula_dense_fragment" in extended_issues
        and not bool(assessment.get("exact_named_equality_formula"))
        and positive_surface_type not in {
            "named_formula",
            "theorem_statement",
            "formula_backed_explanatory_clause",
        }
    ):
        reasons.append("formula_dense_fragment")

    return {
        "accepted": not reasons,
        "reasons": unique_preserve_order(reasons),
        "extended_issue_codes": extended_issues,
        "title_overlap": title_overlap,
        "context_overlap": context_overlap,
        "context_overlap": context_overlap,
        "has_name_anchor": has_name_anchor,
    }


def _definition_candidate_choice_score(
    row: Mapping[str, Any],
    assessment: Mapping[str, Any],
    text: str,
    verdict: Mapping[str, Any],
) -> float:
    score = _definition_surface_choice_score(row, assessment, text)
    title_overlap = int(verdict.get("title_overlap") or 0)
    context_overlap = int(verdict.get("context_overlap") or 0)
    has_name_anchor = bool(verdict.get("has_name_anchor"))
    rerank_margin = _retrieval_metric(row, "rerank_margin")

    score += 3.0 * float(min(title_overlap, 2))
    score += 1.5 * float(min(context_overlap, 3))
    if has_name_anchor:
        score += 2.0
    if rerank_margin > 0.0:
        score += 18.0 * min(rerank_margin, 0.2)
    else:
        score += 12.0 * max(rerank_margin, -0.2)
    if bool(assessment.get("equation_support")):
        score += 1.5
    if bool(assessment.get("exact_named_equality_formula")):
        score += 2.5

    for code in verdict.get("extended_issue_codes") or []:
        if code in {"citation_or_slide_context", "ocr_noise"}:
            score -= 2.0
    return round(score, 6)


def _definition_candidate_entries(
    rows_by_id: Mapping[str, Mapping[str, Any]],
    assessments_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, int]]:
    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    rejected_by_reason: Counter[str] = Counter()

    for candidate_id, row in rows_by_id.items():
        assessment = dict(assessments_by_id.get(candidate_id) or {})
        text = str(assessment.get("candidate_text") or "")
        if not text:
            continue
        verdict = _definition_candidate_verdict(row, assessment, text)
        choice_score = _definition_candidate_choice_score(row, assessment, text, verdict)
        entry = {
            "candidate_id": candidate_id,
            "row": row,
            "assessment": assessment,
            "text": text,
            "choice_score": choice_score,
            "selection_score": float(assessment.get("selection_score") or 0.0),
            "verdict": verdict,
        }
        if verdict.get("accepted"):
            accepted.append(entry)
        else:
            reasons = [str(item) for item in verdict.get("reasons") or []]
            for reason in reasons:
                rejected_by_reason[reason] += 1
            rejected.append(
                {
                    "overlay_candidate_id": candidate_id,
                    "selection_score": float(assessment.get("selection_score") or 0.0),
                    "choice_score": choice_score,
                    "reasons": reasons,
                }
            )

    accepted.sort(
        key=lambda item: (
            -float(item.get("choice_score") or 0.0),
            -float(item.get("selection_score") or 0.0),
            str(item.get("candidate_id") or ""),
        )
    )
    rejected.sort(
        key=lambda item: (
            -float(item.get("choice_score") or 0.0),
            -float(item.get("selection_score") or 0.0),
            str(item.get("overlay_candidate_id") or ""),
        )
    )
    return accepted, rejected, dict(sorted(rejected_by_reason.items()))


def _definition_surface_passes_gate(
    row: Mapping[str, Any],
    assessment: Mapping[str, Any],
    text: str,
) -> bool:
    if not text:
        return False

    if not _definition_candidate_pool_eligible(row, assessment, text):
        return False

    if bool(assessment.get("exact_named_equality_formula")):
        return True

    issue_codes = set(_definition_surface_issue_codes(row, assessment, text))

    text_tokens = _focus_tokens(text)
    title_overlap = len(text_tokens & _definition_title_tokens(row))
    context_overlap = len(text_tokens & _definition_context_tokens(row))
    has_name_anchor = _has_name_anchor(text, row)
    has_target_alignment = bool(title_overlap > 0 or context_overlap > 0 or has_name_anchor)

    if not has_target_alignment:
        return False

    positive_surface_type = str(assessment.get("positive_surface_type") or "")
    definition_signal = bool(assessment.get("definition_signal"))
    formula_candidate = bool(assessment.get("formula_candidate"))

    hard_blocking_codes = {
        "empty_surface",
        "generic_background",
        "procedural_fragment",
        "question_like",
    }
    if any(code in hard_blocking_codes for code in issue_codes):
        return False

    if "fragment_lead_in" in issue_codes:
        fragment_rescue = bool(
            has_name_anchor
            and positive_surface_type in {
                "named_formula",
                "theorem_statement",
                "formula_backed_explanatory_clause",
                "anchored_descriptive_clause",
            }
        )
        if not fragment_rescue:
            return False

    if "heading_like" in issue_codes:
        heading_rescue = bool(
            has_target_alignment
            and positive_surface_type in {
                "anchored_descriptive_clause",
                "formula_backed_explanatory_clause",
                "named_formula",
                "theorem_statement",
            }
        )
        if not heading_rescue:
            return False

    if "formula_lead_in" in issue_codes:
        formula_rescue = bool(
            has_target_alignment
            and (
                positive_surface_type in {
                    "named_formula",
                    "theorem_statement",
                    "formula_backed_explanatory_clause",
                }
                or (formula_candidate and definition_signal)
            )
        )
        if not formula_rescue:
            return False

    return True


def _definition_surface_choice_score(
    row: Mapping[str, Any],
    assessment: Mapping[str, Any],
    text: str,
) -> float:
    text_tokens = _focus_tokens(text)
    title_overlap = len(text_tokens & _definition_title_tokens(row))
    context_overlap = len(text_tokens & _definition_context_tokens(row))
    alignment_breakdown = dict(row.get("alignment_breakdown") or {})
    positive_surface_type = str(assessment.get("positive_surface_type") or "")
    labeled_clause = _looks_labeled_definition_clause(text)

    score = 0.0
    score += 4.0 * float(title_overlap)
    score += 2.0 * float(min(context_overlap, 4))
    if _has_name_anchor(text, row):
        score += 4.0
    if labeled_clause:
        score += 2.5
    if bool(assessment.get("exact_named_equality_formula")):
        score += 4.0
    if positive_surface_type == "prose_definition":
        score += 4.0
    elif positive_surface_type == "anchored_descriptive_clause":
        score += 3.0
    elif positive_surface_type in {"named_formula", "theorem_statement", "formula_backed_explanatory_clause"}:
        score += 2.5
    if bool(assessment.get("definition_candidate")):
        score += 2.0
    elif bool(assessment.get("context_candidate")):
        score += 0.75

    token_count = len(tokenize(_normalized_text(text)))
    if 6 <= token_count <= 28:
        score += 2.0
    elif token_count > 36:
        score -= 2.0

    competitor_hits = int(alignment_breakdown.get("competitor_token_hits") or 0)
    score -= float(min(4, competitor_hits))

    if (
        bool(row.get("is_procedure_like"))
        and not bool(assessment.get("exact_named_equality_formula"))
        and not labeled_clause
    ):
        score -= 2.0

    issue_codes = _definition_surface_issue_codes(row, assessment, text)
    for code in issue_codes:
        if code in {"fragment_lead_in", "formula_lead_in", "heading_like"}:
            score -= 2.0
        elif code == "overlong_surface":
            score -= 1.0
        else:
            score -= 6.0

    return round(score, 6)


DEFINITION_EVIDENCE_PACKET_CONTRACT_VERSION = "step6_7_definition_evidence_packet_v1"
DEFINITION_EVIDENCE_PACKET_ROLES = (
    "target_witness",
    "definition_gloss",
    "formula_or_notation",
    "mechanism_or_scope",
    "contrastive_sibling",
    "example_or_context",
)


def _definition_packet_role(
    *,
    row: Mapping[str, Any],
    assessment: Mapping[str, Any],
    text: str,
    target_kc_id: str,
) -> str:
    support_profile = _support_profile(row)
    upstream_support_role = str(support_profile.get("preferred_support_role") or "other")
    if str(row.get("kc_id") or "") != str(target_kc_id):
        return "contrastive_sibling"
    if upstream_support_role == "definitional_anchor":
        return "definition_gloss"
    if upstream_support_role == "context_completion_anchor":
        return "mechanism_or_scope"
    if upstream_support_role == "formula_or_parameter_anchor":
        return "formula_or_notation"
    if bool(row.get("is_example_like")):
        return "example_or_context"
    if (
        bool(assessment.get("equation_support"))
        or bool(assessment.get("formula_candidate"))
        or bool(row.get("is_formula_like"))
    ):
        return "formula_or_notation"
    if bool(assessment.get("definition_candidate")) or bool(assessment.get("definition_signal")):
        return "definition_gloss"
    if bool(assessment.get("context_candidate")) or bool(assessment.get("scope_signal")):
        return "mechanism_or_scope"

    title_overlap, context_overlap, has_name_anchor = _definition_alignment_features(row, text)
    if bool(has_name_anchor or title_overlap > 0 or context_overlap > 0):
        return "target_witness"
    return "example_or_context"


def _definition_packet_formula_anchor_allowed(
    *,
    row: Mapping[str, Any],
    assessment: Mapping[str, Any],
    text: str,
) -> bool:
    title_overlap, _, has_name_anchor = _definition_alignment_features(row, text)
    formula_defined_signal = bool(
        assessment.get("exact_named_equality_formula")
        or assessment.get("theorem_statement_or_equation")
        or assessment.get("formula_backed_explanatory_clause")
    )
    return bool(
        formula_defined_signal
        and (has_name_anchor or title_overlap > 0 or bool(assessment.get("definition_signal")))
    )


_PROCEDURE_SEQUENCE_MARKER_RE = re.compile(
    r"^\s*(?:step\s*\d+|stage\s*\d+|phase\s*\d+|\d+\s*[.)]|"
    r"first|second|third|fourth|fifth|next|then|finally|initially|afterwards?|subsequently)\b",
    re.IGNORECASE,
)


def _definition_packet_procedure_anchor_allowed(
    *,
    row: Mapping[str, Any],
    text: str,
) -> bool:
    """Structural, vocabulary-free escape for is_procedure_like rows, mirroring
    _definition_packet_formula_anchor_allowed's shape (content-class flag AND an
    independent anchor/binding signal). Uses the same category of signal as the sibling
    Step 5x-level escape in evidence_admission.py::_procedure_structural_anchor_allowed,
    adapted to this module's row shape: this overlay row has no role_eligibility /
    candidate_quality fields (those live only on the raw Step 5x pack record), but its own
    support_profile already carries an equivalent procedure-role signal and target-binding
    basis, computed at Step 5x/5p and passed through unchanged by the Step 6.6 overlay.
    """
    support_profile = dict(row.get("support_profile") or {})
    support_roles = {str(item) for item in (support_profile.get("support_roles") or [])}
    shape_tags = {str(item) for item in (support_profile.get("structural_shape_tags") or [])}
    if "process_or_procedure" not in support_roles and "procedure" not in shape_tags:
        return False
    if not str(support_profile.get("target_binding_basis") or "").strip():
        return False
    tokens = set(t for t in re.findall(r"[a-z0-9]+", text.lower()) if t)
    if len(tokens) < 6:
        return False
    return bool(_PROCEDURE_SEQUENCE_MARKER_RE.match(text.strip()))


def _definition_packet_anchor_state(
    *,
    role: str,
    row: Mapping[str, Any],
    assessment: Mapping[str, Any],
    text: str,
    verdict: Mapping[str, Any],
) -> Tuple[bool, str]:
    if role == "contrastive_sibling":
        return False, "sibling_disambiguation_only"
    if role == "example_or_context":
        return False, "example_or_context_not_definitional_anchor"
    if role == "formula_or_notation":
        if _definition_packet_formula_anchor_allowed(row=row, assessment=assessment, text=text):
            return True, ""
        return False, "formula_or_notation_without_definitional_gloss"
    if bool(row.get("is_procedure_like")):
        if _definition_packet_procedure_anchor_allowed(row=row, text=text):
            return True, ""
        return False, "procedure_like_not_definitional_anchor"
    if role == "definition_gloss":
        return bool(verdict.get("accepted")), "" if bool(verdict.get("accepted")) else "definition_verdict_rejected"
    if role in {"target_witness", "mechanism_or_scope"}:
        relation_score = _anchored_same_kc_relation_score(text, row)
        if relation_score > 0.0 and not bool(row.get("is_example_like")):
            return True, ""
        return False, "relation_bearing_definition_missing"
    return False, "role_not_anchor_eligible"


def build_definition_evidence_packet(
    rows_by_id: Mapping[str, Mapping[str, Any]],
    assessments_by_id: Mapping[str, Mapping[str, Any]],
    *,
    target_kc_id: str,
    max_items_per_role: int = 2,
) -> Dict[str, Any]:
    role_items: Dict[str, List[Dict[str, Any]]] = {role: [] for role in DEFINITION_EVIDENCE_PACKET_ROLES}

    for candidate_id, row in rows_by_id.items():
        assessment = dict(assessments_by_id.get(candidate_id) or {})
        text = normalize_ws(assessment.get("candidate_text") or _candidate_text(row))
        if not text:
            continue
        if not bool(assessment.get("usable_evidence")):
            continue

        role = _definition_packet_role(
            row=row,
            assessment=assessment,
            text=text,
            target_kc_id=target_kc_id,
        )
        verdict = _definition_candidate_verdict(row, assessment, text)
        anchor_eligible, anchor_blocked_reason = _definition_packet_anchor_state(
            role=role,
            row=row,
            assessment=assessment,
            text=text,
            verdict=verdict,
        )
        title_overlap, context_overlap, has_name_anchor = _definition_alignment_features(row, text)
        relation_score = _anchored_same_kc_relation_score(text, row)
        role_score = float(assessment.get("selection_score") or 0.0)
        role_score += 8.0 if anchor_eligible else 0.0
        role_score += 4.0 if bool(verdict.get("accepted")) else 0.0
        role_score += 3.0 * float(min(title_overlap, 2))
        role_score += 2.0 * float(min(context_overlap, 3))
        role_score += 4.0 * float(relation_score)
        if role == "contrastive_sibling":
            role_score += 1.0

        role_items[role].append(
            {
                "role": role,
                "overlay_candidate_id": str(candidate_id),
                "source_kc_id": str(row.get("kc_id") or ""),
                "candidate_text": text,
                "source_text_field": _candidate_source_text_field(row),
                "doc_id": str(row.get("doc_id") or ""),
                "block_id": str(row.get("block_id") or ""),
                "page_index": row.get("page_index"),
                "anchor_eligible": bool(anchor_eligible),
                "anchor_blocked_reason": str(anchor_blocked_reason),
                "disambiguation_only": role == "contrastive_sibling",
                "role_score": round(role_score, 6),
                "relation_score": round(float(relation_score), 6),
                "title_overlap": int(title_overlap),
                "context_overlap": int(context_overlap),
                "has_name_anchor": bool(has_name_anchor),
                "definition_verdict_accepted": bool(verdict.get("accepted")),
                "definition_verdict_reasons": [str(item) for item in verdict.get("reasons") or []],
                "assessment": {
                    "classification": str(assessment.get("classification") or ""),
                    "positive_surface_type": str(assessment.get("positive_surface_type") or ""),
                    "definition_signal": bool(assessment.get("definition_signal")),
                    "definition_candidate": bool(assessment.get("definition_candidate")),
                    "context_candidate": bool(assessment.get("context_candidate")),
                    "equation_support": bool(assessment.get("equation_support")),
                    "formula_candidate": bool(assessment.get("formula_candidate")),
                    "scope_signal": bool(assessment.get("scope_signal")),
                    "formula_defined_anchor_allowed": bool(
                        role == "formula_or_notation"
                        and anchor_eligible
                    ),
                },
            }
        )

    normalized_role_items: Dict[str, List[Dict[str, Any]]] = {}
    anchor_role_counts: Counter[str] = Counter()
    candidate_anchor_ids: List[str] = []
    contrastive_sibling_ids: List[str] = []
    for role in DEFINITION_EVIDENCE_PACKET_ROLES:
        ranked = sorted(
            role_items.get(role) or [],
            key=lambda item: (
                -float(item.get("role_score") or 0.0),
                str(item.get("overlay_candidate_id") or ""),
            ),
        )[: max(1, int(max_items_per_role))]
        normalized_role_items[role] = ranked
        for item in ranked:
            candidate_id = str(item.get("overlay_candidate_id") or "")
            if bool(item.get("anchor_eligible")):
                anchor_role_counts[role] += 1
                candidate_anchor_ids.append(candidate_id)
            if role == "contrastive_sibling" and candidate_id:
                contrastive_sibling_ids.append(candidate_id)

    formula_anchor_allowed = bool(anchor_role_counts.get("formula_or_notation"))
    non_formula_anchor_present = any(
        count > 0
        for role, count in anchor_role_counts.items()
        if role != "formula_or_notation"
    )
    definitional_anchor_present = bool(non_formula_anchor_present or formula_anchor_allowed)
    sole_anchor_blocked_reason = ""
    if not definitional_anchor_present:
        non_anchor_reasons = [
            str(item.get("anchor_blocked_reason") or "")
            for role in DEFINITION_EVIDENCE_PACKET_ROLES
            if role != "contrastive_sibling"
            for item in normalized_role_items.get(role, [])
            if str(item.get("anchor_blocked_reason") or "")
        ]
        sole_anchor_blocked_reason = ";".join(unique_preserve_order(non_anchor_reasons))

    return {
        "contract_version": DEFINITION_EVIDENCE_PACKET_CONTRACT_VERSION,
        "target_kc_id": str(target_kc_id),
        "roles": normalized_role_items,
        "anchor_role_counts": dict(sorted(anchor_role_counts.items())),
        "candidate_anchor_ids": unique_preserve_order(candidate_anchor_ids),
        "contrastive_sibling_ids": unique_preserve_order(contrastive_sibling_ids),
        "definitional_anchor_present": definitional_anchor_present,
        "formula_anchor_allowed": formula_anchor_allowed,
        "non_formula_anchor_present": non_formula_anchor_present,
        "sole_anchor_blocked_reason": sole_anchor_blocked_reason,
        "hard_rules": {
            "example_or_context_anchor_allowed": False,
            "formula_or_notation_requires_formula_defined_signal": True,
            "contrastive_sibling_disambiguation_only": True,
        },
    }


SELECTED_DEFINITION_REVIEW_QUALITY_CONTRACT_VERSION = "step6_7_selected_definition_review_quality_v1"
_SELECTED_DEFINITION_SURFACE_FAMILY_FLAGS = {
    "formula_only_anchor": "selected_definition_formula_only_anchor",
    "broken_fragment": "selected_definition_broken_fragment",
    "procedure_instruction_surface": "selected_definition_procedure_instruction_surface",
    "example_update_surface": "selected_definition_example_update_surface",
    "context_only_label_surface": "selected_definition_context_only_label_surface",
    "severe_ocr_or_broken_math_surface": "selected_definition_severe_ocr_or_broken_math_surface",
}
_REVIEW_PROCEDURE_PREFIXES = (
    *PROCEDURAL_FRAGMENT_PREFIXES,
    "apply ",
    "calculate ",
    "determine ",
    "estimate ",
    "evaluate ",
    "repeat ",
    "select ",
    "set ",
    "split ",
    "train ",
    "update ",
    "use ",
)
_REVIEW_EXAMPLE_UPDATE_PREFIXES = (
    "after each example",
    "after the example",
    "as an example",
    "consider ",
    "example ",
    "for example",
    "for instance",
    "given ",
    "if ",
    "in this example",
    "suppose ",
    "when ",
)
_REVIEW_CONTEXT_UPDATE_PREFIXES = (
    "although ",
    "alternatively",
    "as previously mentioned",
    "furthermore",
    "for the purpose",
    "hence",
    "however",
    "in other words",
    "in this case",
    "in the following",
    "notice that",
    "on the other hand",
    "one simple way",
    "otherwise",
    "this avoids",
    "there are ",
    "there is ",
    "to illustrate",
    "to demonstrate",
    "using ",
)


def _selected_definition_support_pairs(
    definition_full_candidate: Mapping[str, Any],
    rows_by_id: Mapping[str, Mapping[str, Any]],
    assessments_by_id: Mapping[str, Mapping[str, Any]],
) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for support_id in definition_full_candidate.get("supporting_overlay_candidate_ids") or []:
        candidate_id = str(support_id or "")
        if not candidate_id:
            continue
        row = dict(rows_by_id.get(candidate_id) or {})
        assessment = dict(assessments_by_id.get(candidate_id) or {})
        if row and not assessment:
            assessment = assess_overlay_candidate(row)
        pairs.append((row, assessment))
    return pairs


def _selected_definition_has_gloss_signal(
    text: str,
    support_pairs: Sequence[Tuple[Mapping[str, Any], Mapping[str, Any]]],
) -> bool:
    text_norm = f" {_normalized_text(text)} "
    natural_word_count = _natural_language_word_count(text)
    if natural_word_count >= 7 and _text_has_any_cue(text_norm, DEFINITION_LINK_CUES):
        return True
    for _, assessment in support_pairs:
        positive_surface_type = str(assessment.get("positive_surface_type") or "")
        if positive_surface_type in {
            "prose_definition",
            "anchored_descriptive_clause",
            "formula_backed_explanatory_clause",
        } and natural_word_count >= 6:
            return True
    return False


def _selected_definition_formula_only(
    text: str,
    support_pairs: Sequence[Tuple[Mapping[str, Any], Mapping[str, Any]]],
) -> bool:
    formula_symbol_count = len(re.findall(r"[=<>+\-*/^_{}$\\|]", text))
    latex_like = bool(re.search(r"\\[A-Za-z]+", text))
    support_formulaish = any(
        bool(assessment.get("exact_named_equality_formula"))
        or bool(assessment.get("formula_candidate"))
        or bool(assessment.get("equation_support"))
        or bool(row.get("is_formula_like"))
        for row, assessment in support_pairs
    )
    if not (formula_symbol_count >= 1 or latex_like or support_formulaish):
        return False
    if _selected_definition_has_gloss_signal(text, support_pairs):
        return False
    natural_word_count = _natural_language_word_count(text)
    if natural_word_count <= 5:
        return True
    formula_heavy = formula_symbol_count >= 3 or latex_like
    return bool(formula_heavy and natural_word_count <= 8)


def _selected_definition_procedure_instruction(
    text: str,
    support_pairs: Sequence[Tuple[Mapping[str, Any], Mapping[str, Any]]],
    issue_codes: Sequence[str],
) -> bool:
    lowered = _strip_leading_markers(text).lower()
    if "procedural_fragment" in issue_codes:
        return True
    if _starts_with_any(lowered, _REVIEW_PROCEDURE_PREFIXES):
        return not _text_has_any_cue(f" {_normalized_text(text)} ", DEFINITION_LINK_CUES)
    procedure_phrases = (
        " can be propagated ",
        " is assigned ",
        " are assigned ",
        " must also ",
        " will be classified ",
    )
    if any(phrase in f" {lowered} " for phrase in procedure_phrases):
        return True
    return any(bool(row.get("is_procedure_like")) for row, _ in support_pairs) and not _selected_definition_has_gloss_signal(
        text,
        support_pairs,
    )


def _selected_definition_example_update(text: str, issue_codes: Sequence[str]) -> bool:
    lowered = _strip_leading_markers(text).lower()
    if _starts_with_any(lowered, _REVIEW_EXAMPLE_UPDATE_PREFIXES):
        return True
    if _starts_with_any(lowered, _REVIEW_CONTEXT_UPDATE_PREFIXES):
        return True
    if "generic_context_lead_in" in issue_codes:
        return True
    update_phrases = (
        " is updated ",
        " are updated ",
        " was updated ",
        " were updated ",
        " gets updated ",
        " get updated ",
    )
    return any(phrase in f" {lowered} " for phrase in update_phrases)


def _selected_definition_context_only_label(
    text: str,
    row: Mapping[str, Any],
    assessment: Mapping[str, Any],
    issue_codes: Sequence[str],
) -> bool:
    lowered = _strip_leading_markers(text).lower()
    if "=" in text:
        return False
    token_count = len(tokenize(_normalized_text(text)))
    has_definition_cue = _text_has_any_cue(f" {_normalized_text(text)} ", DEFINITION_LINK_CUES)
    heading_like = bool(assessment.get("bare_heading")) or bool(assessment.get("title_like_heading")) or "heading_like" in issue_codes
    label_like = ":" in text or " - " in text or " -- " in text or bool(re.match(r"^[A-Z][A-Za-z0-9 /()-]{2,80}$", text))
    equation_reference_only = any(
        phrase in f" {lowered} "
        for phrase in (
            " is given in equation ",
            " are given in equation ",
            " shown in equation ",
            " given in equations ",
        )
    )
    if equation_reference_only:
        return True
    return bool((heading_like or label_like) and token_count <= 12 and not has_definition_cue)


def _selected_definition_surface_assessment(
    row: Mapping[str, Any],
    assessment: Mapping[str, Any],
    text: str,
) -> Dict[str, Any]:
    surface_assessment = dict(assessment)
    assessed_text = normalize_ws(
        assessment.get("candidate_text")
        or row.get("source_block_text")
        or row.get("quote_surface")
        or ""
    )
    if assessed_text == normalize_ws(text):
        return surface_assessment
    lowered = _strip_leading_markers(text).lower()
    token_count = len(tokenize(_normalized_text(text)))
    has_definition_cue = _text_has_any_cue(f" {_normalized_text(text)} ", DEFINITION_LINK_CUES)
    surface_assessment["candidate_text"] = normalize_ws(text)
    surface_assessment["formula_lead_in"] = bool(lowered.endswith(":") or lowered.endswith("="))
    surface_assessment["question_like"] = _question_like(text)
    surface_assessment["bare_heading"] = bool(
        token_count <= 8
        and not has_definition_cue
        and "." not in text
        and "=" not in text
    )
    surface_assessment["title_like_heading"] = surface_assessment["bare_heading"]
    return surface_assessment


def _selected_definition_severe_ocr_or_math(text: str, issue_codes: Sequence[str]) -> bool:
    if any(code in issue_codes for code in {"ocr_noise", "traceback_noise", "formula_dense_fragment"}):
        return True
    natural_word_count = _natural_language_word_count(text)
    symbol_count = len(re.findall(r"[=<>+\-*/^_{}$\\|]", text))
    fused_ocr = bool(re.search(r"[a-z][A-Z][a-z]|[A-Za-z][0-9][A-Za-z0-9]*|[0-9][A-Za-z]", text))
    if fused_ocr and (symbol_count >= 1 or "ambiguous_retrieval" in issue_codes):
        return True
    if "?" in text and symbol_count >= 1:
        return True
    return bool(symbol_count >= 8 and natural_word_count <= 4)


def selected_definition_review_quality(
    definition_full_candidate: Mapping[str, Any],
    rows_by_id: Mapping[str, Mapping[str, Any]],
    assessments_by_id: Mapping[str, Mapping[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Classify selected definition surfaces that should not be plain review-ready."""

    text = normalize_ws(definition_full_candidate.get("text") or "")
    supporting_ids = [
        str(item)
        for item in definition_full_candidate.get("supporting_overlay_candidate_ids") or []
        if str(item)
    ]
    if str(definition_full_candidate.get("status") or "") != "grounded" or not text:
        return {
            "contract_version": SELECTED_DEFINITION_REVIEW_QUALITY_CONTRACT_VERSION,
            "evaluated": False,
            "suppressed": False,
            "surface_family": "",
            "surface_families": [],
            "risk_flags": [],
            "issue_codes": [],
            "supporting_overlay_candidate_ids": supporting_ids,
        }

    assessment_lookup = assessments_by_id or {}
    support_pairs = _selected_definition_support_pairs(
        definition_full_candidate,
        rows_by_id,
        assessment_lookup,
    )
    primary_row = dict(support_pairs[0][0]) if support_pairs else {}
    primary_assessment = dict(support_pairs[0][1]) if support_pairs else {}
    primary_surface_assessment = _selected_definition_surface_assessment(
        primary_row,
        primary_assessment,
        text,
    )
    issue_codes = unique_preserve_order(
        [
            *_definition_surface_issue_codes(primary_row, primary_surface_assessment, text),
            *_definition_extended_issue_codes(primary_row, primary_surface_assessment, text),
        ]
    )

    families: List[str] = []
    if _selected_definition_formula_only(text, support_pairs):
        families.append("formula_only_anchor")
    if any(code in issue_codes for code in {"empty_surface", "fragment_lead_in", "formula_lead_in"}) or _strip_leading_markers(text).rstrip(" .").endswith((
        ":",
        "=",
    )):
        families.append("broken_fragment")
    if _selected_definition_procedure_instruction(text, support_pairs, issue_codes):
        families.append("procedure_instruction_surface")
    if _selected_definition_example_update(text, issue_codes):
        families.append("example_update_surface")
    if _selected_definition_context_only_label(text, primary_row, primary_surface_assessment, issue_codes):
        families.append("context_only_label_surface")
    if _selected_definition_severe_ocr_or_math(text, issue_codes):
        families.append("severe_ocr_or_broken_math_surface")

    families = unique_preserve_order(families)
    risk_flags = [
        _SELECTED_DEFINITION_SURFACE_FAMILY_FLAGS[family]
        for family in families
        if family in _SELECTED_DEFINITION_SURFACE_FAMILY_FLAGS
    ]
    return {
        "contract_version": SELECTED_DEFINITION_REVIEW_QUALITY_CONTRACT_VERSION,
        "evaluated": True,
        "suppressed": bool(families),
        "surface_family": families[0] if families else "definition_grade_surface",
        "surface_families": families,
        "risk_flags": risk_flags,
        "issue_codes": issue_codes,
        "supporting_overlay_candidate_ids": supporting_ids,
        "source_text_field": str(definition_full_candidate.get("source_text_field") or ""),
        "selection_reason": str(definition_full_candidate.get("selection_reason") or ""),
    }



def _heuristic_route_policy_text(value: Any) -> str:
    return str(value or "").strip()


def _heuristic_route_policy_norm(value: Any) -> str:
    return " ".join(_heuristic_route_policy_text(value).lower().split())


def _heuristic_route_policy_tokens(value: Any) -> set[str]:
    import re as _route_policy_re

    stop = {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
        "in", "into", "is", "it", "its", "of", "on", "or", "the", "to",
        "with", "without", "that", "this", "these", "those",
    }
    return {
        token
        for token in _route_policy_re.findall(r"[a-z0-9]+", _heuristic_route_policy_text(value).lower())
        if len(token) >= 2 and token not in stop
    }


def _heuristic_route_policy_token_jaccard(left: Any, right: Any) -> float:
    left_tokens = _heuristic_route_policy_tokens(left)
    right_tokens = _heuristic_route_policy_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _heuristic_route_policy_text_match(left: Any, right: Any, *, threshold: float = 0.55) -> bool:
    left_norm = _heuristic_route_policy_norm(left)
    right_norm = _heuristic_route_policy_norm(right)
    if not left_norm or not right_norm:
        return False
    if left_norm in right_norm or right_norm in left_norm:
        return True
    return _heuristic_route_policy_token_jaccard(left_norm, right_norm) >= threshold


def _heuristic_route_policy_ordered_pack_items(exemplar: Mapping[str, Any]) -> List[Dict[str, Any]]:
    if _stage3_v3_pack_active(exemplar) and not _stage3_v3_pack_has_drafting_core(exemplar):
        return []
    items = exemplar.get("ordered_pack_for_drafting") or []
    if not isinstance(items, list):
        return []
    return [dict(item) for item in items if isinstance(item, Mapping)]


def _heuristic_route_policy_ordered_item_role(item: Mapping[str, Any]) -> str:
    return _heuristic_route_policy_text(item.get("role") or item.get("slot_role"))


def _heuristic_route_policy_ordered_item_text(item: Mapping[str, Any]) -> str:
    for key in ("text", "candidate_text", "quote_surface", "source_block_text"):
        value = _heuristic_route_policy_text(item.get(key))
        if value:
            return value
    return ""


def _heuristic_route_policy_row_texts(row: Mapping[str, Any]) -> List[str]:
    values: List[str] = []
    for key in (
        "text",
        "candidate_text",
        "quote_surface",
        "source_block_text",
        "original_quote_surface",
        "original_source_block_text",
        "source_block_text_raw",
    ):
        value = _heuristic_route_policy_text(row.get(key))
        if value:
            values.append(value)
    return values


def _heuristic_route_policy_find_row_for_text(
    text_value: str,
    rows: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    best_row: Mapping[str, Any] = {}
    best_score = 0.0

    for row in rows:
        if not isinstance(row, Mapping):
            continue

        for candidate_text in _heuristic_route_policy_row_texts(row):
            if _heuristic_route_policy_text_match(text_value, candidate_text):
                return row

            score = _heuristic_route_policy_token_jaccard(text_value, candidate_text)
            if score > best_score:
                best_score = score
                best_row = row

    if best_score >= 0.45:
        return best_row

    return {}


def _heuristic_route_policy_ordered_definition_score(
    item: Mapping[str, Any],
    canonical_name: str,
) -> float:
    text_value = _heuristic_route_policy_ordered_item_text(item)
    text_norm = _heuristic_route_policy_norm(text_value)
    canonical_tokens = _heuristic_route_policy_tokens(canonical_name)

    score = 0.0

    if _heuristic_route_policy_ordered_item_role(item) == "definition_kernel":
        score += 10.0

    score += min(len(_heuristic_route_policy_tokens(text_value)), 28) / 10.0

    if canonical_tokens and canonical_tokens & _heuristic_route_policy_tokens(text_value):
        score += 3.0

    definitional_markers = [
        " is ",
        " are ",
        " refers to ",
        " defined ",
        " known as ",
        " called ",
        " consists of ",
        " measures ",
        " represents ",
        " grown ",
    ]
    if any(marker in f" {text_norm} " for marker in definitional_markers):
        score += 4.0

    meta_prefixes = (
        "this section presents",
        "this subsection presents",
        "this chapter presents",
        "this section describes",
        "this subsection describes",
        "we present",
        "we describe",
    )
    if text_norm.startswith(meta_prefixes):
        score -= 8.0

    return score


def _heuristic_route_policy_candidate_matches_ordered_role(
    candidate: Mapping[str, Any],
    exemplar: Mapping[str, Any],
    role: str,
) -> bool:
    if not isinstance(candidate, Mapping):
        return False

    text_value = _heuristic_route_policy_text(candidate.get("text"))
    if not text_value:
        return False

    for item in _heuristic_route_policy_ordered_pack_items(exemplar):
        if _heuristic_route_policy_ordered_item_role(item) != role:
            continue
        if _heuristic_route_policy_text_match(
            text_value,
            _heuristic_route_policy_ordered_item_text(item),
        ):
            return True

    return False


def _heuristic_route_policy_preferred_definition_kernel_candidate(
    exemplar: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    items = [
        item
        for item in _heuristic_route_policy_ordered_pack_items(exemplar)
        if _heuristic_route_policy_ordered_item_role(item) == "definition_kernel"
        and _heuristic_route_policy_ordered_item_text(item)
    ]

    if not items:
        return {}

    canonical_name = _heuristic_route_policy_text(exemplar.get("canonical_name"))
    ranked = sorted(
        items,
        key=lambda item: _heuristic_route_policy_ordered_definition_score(item, canonical_name),
        reverse=True,
    )

    for item in ranked:
        text_value = _heuristic_route_policy_ordered_item_text(item)
        matched_row = _heuristic_route_policy_find_row_for_text(text_value, rows)
        overlay_id = _heuristic_route_policy_text(matched_row.get("overlay_candidate_id"))
        ordered_pack_candidate_id = _heuristic_route_policy_text(item.get("candidate_id"))
        support_id = overlay_id or ordered_pack_candidate_id

        if not support_id:
            continue

        return {
            "status": "grounded",
            "text": text_value,
            "supporting_overlay_candidate_ids": [support_id],
            "supporting_ordered_pack_candidate_ids": [
                ordered_pack_candidate_id
            ],
            "supporting_overlay_candidate_ids_origin": (
                "overlay_candidate_id"
                if overlay_id
                else "ordered_pack_candidate_id_fallback"
            ),
            "selection_reason": "definition_full_candidate_ordered_pack_definition_kernel_policy",
            "source_text_field": "ordered_pack_for_drafting.text",
            "stage3_v3_role_policy": {
                "applied": True,
                "policy": "prefer_definition_kernel_over_explanatory_gloss",
                "selected_role": _heuristic_route_policy_ordered_item_role(item),
                "selected_ordered_pack_candidate_id": ordered_pack_candidate_id,
                "matched_overlay_candidate_id": overlay_id,
            },
        }

    return {}


def _heuristic_route_policy_evidence_pack_trace(exemplar: Mapping[str, Any]) -> Dict[str, Any]:
    quality = dict(exemplar.get("evidence_pack_quality") or {})
    ordered_items = _heuristic_route_policy_ordered_pack_items(exemplar)

    role_counts: Dict[str, int] = {}
    for item in ordered_items:
        role = _heuristic_route_policy_ordered_item_role(item)
        if role:
            role_counts[role] = role_counts.get(role, 0) + 1

    insufficient_reasons = quality.get("insufficient_reasons") or []
    if not isinstance(insufficient_reasons, list):
        insufficient_reasons = [str(insufficient_reasons)]

    return {
        "available": bool(exemplar.get("evidence_pack_available")),
        "version": _heuristic_route_policy_text(exemplar.get("evidence_pack_version")),
        "route": _heuristic_route_policy_text(quality.get("route")),
        "ordered_pack_count": len(ordered_items),
        "ordered_pack_roles": role_counts,
        "evidence_lane_semantics": dict(exemplar.get("evidence_lane_semantics") or {}),
        "automatic_drafting_supported": bool((exemplar.get("evidence_lane_semantics") or {}).get("automatic_drafting_supported", _stage3_v3_pack_has_drafting_core(exemplar))),
        "definition_anchor_present": bool(quality.get("definition_anchor_present", False)),
        "definition_anchor_natural_language": bool(quality.get("definition_anchor_natural_language", False)),
        "positive_support_count": int(quality.get("positive_support_count") or 0),
        "auxiliary_support_count": int(quality.get("auxiliary_support_count") or 0),
        "guardrail_support_count": int(quality.get("guardrail_support_count") or 0),
        "context_completion_used": bool(quality.get("context_completion_used", False)),
        "formula_dominance_risk": _heuristic_route_policy_text(quality.get("formula_dominance_risk")),
        "sibling_contamination_risk": _heuristic_route_policy_text(quality.get("sibling_contamination_risk")),
        "insufficient_reasons": [str(item) for item in insufficient_reasons],
    }


def _heuristic_route_policy_bundle_role_for_ordered_item(item: Mapping[str, Any]) -> str:
    role = _heuristic_route_policy_ordered_item_role(item)
    if role == "definition_kernel":
        return "definition_support"
    if role == "explanatory_gloss":
        return "context_support"
    if "equation" in role or "formula" in role:
        return "equation_support"
    return "context_support"


def _heuristic_route_policy_bundle_item_from_ordered_item(
    item: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    text_value = _heuristic_route_policy_ordered_item_text(item)
    matched_row = _heuristic_route_policy_find_row_for_text(text_value, rows)

    bundle_role = _heuristic_route_policy_bundle_role_for_ordered_item(item)
    overlay_id = _heuristic_route_policy_text(matched_row.get("overlay_candidate_id"))

    if not overlay_id:
        overlay_id = _heuristic_route_policy_text(item.get("candidate_id"))

    assessment = {
        "classification": bundle_role,
        "definition_signal": bundle_role == "definition_support",
        "scope_signal": bundle_role in {"definition_support", "context_support"},
        "bare_heading": False,
        "formula_lead_in": bundle_role == "equation_support",
        "question_like": False,
        "equation_support": bundle_role == "equation_support",
    }

    return {
        "overlay_candidate_id": overlay_id,
        "ordered_pack_candidate_id": _heuristic_route_policy_text(item.get("candidate_id")),
        "bundle_role": bundle_role,
        "candidate_text": _heuristic_route_policy_text(matched_row.get("candidate_text")) or text_value,
        "quote_surface": _heuristic_route_policy_text(matched_row.get("quote_surface")) or text_value,
        "source_block_text": _heuristic_route_policy_text(matched_row.get("source_block_text")) or text_value,
        "doc_id": matched_row.get("doc_id"),
        "page_index": matched_row.get("page_index"),
        "sentence_id": matched_row.get("sentence_id"),
        "block_id": matched_row.get("block_id"),
        "layer": matched_row.get("layer"),
        "selection_score": matched_row.get("selection_score"),
        "alignment_score": matched_row.get("alignment_score"),
        "contamination_risk": matched_row.get("contamination_risk"),
        "quote_verification_status": matched_row.get("quote_verification_status"),
        "provenance_normalization_status": matched_row.get("provenance_normalization_status"),
        "assessment": assessment,
        "evidence_pack_route_policy": {
            "source": "ordered_pack_for_drafting",
            "ordered_pack_role": _heuristic_route_policy_ordered_item_role(item),
            "text_matched_to_overlay": bool(matched_row),
        },
    }


def _heuristic_route_policy_selected_bundle(
    *,
    original_bundle: Sequence[Mapping[str, Any]],
    exemplar: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    route: str,
    max_bundle_size: int,
) -> List[Dict[str, Any]]:
    if route == "insufficient_support_packet":
        return []

    ordered_items = _heuristic_route_policy_ordered_pack_items(exemplar)

    if ordered_items:
        out: List[Dict[str, Any]] = []
        seen: set[str] = set()

        for item in ordered_items:
            if len(out) >= max_bundle_size:
                break

            bundle_item = _heuristic_route_policy_bundle_item_from_ordered_item(item, rows)
            key = _heuristic_route_policy_text(bundle_item.get("overlay_candidate_id")) or _heuristic_route_policy_text(bundle_item.get("quote_surface"))
            if not key or key in seen:
                continue

            seen.add(key)
            out.append(bundle_item)

        return out

    return [dict(item) for item in original_bundle if isinstance(item, Mapping)]


def build_kc_draft_bundles(
    overlay_rows: Sequence[Mapping[str, Any]],
    *,
    max_bundle_size: int = 4,
    max_explanatory_candidates: int = 3,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    rows_by_kc: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for row in overlay_rows:
        kc_id = str(row.get("kc_id") or "")
        if not kc_id:
            continue
        rows_by_kc[kc_id].append(row)

    bundles: List[Dict[str, Any]] = []
    draft_status_counter: Counter[str] = Counter()
    support_state_counter: Counter[str] = Counter()
    evidence_bundle_size_distribution: Counter[str] = Counter()
    contamination_flag_counter: Counter[str] = Counter()
    definition_verifier_rejection_counter: Counter[str] = Counter()
    kcs_with_definition_candidates = 0
    kcs_with_abstained_definitions = 0
    kcs_with_contamination_flags = 0
    kcs_held_for_insufficient_support = 0
    definition_verifier_rejected_kcs = 0

    for kc_id in sorted(rows_by_kc.keys()):
        rows = sorted(rows_by_kc[kc_id], key=lambda row: str(row.get("overlay_candidate_id") or ""))
        exemplar = dict(rows[0])
        rows_by_id = {str(row.get("overlay_candidate_id") or ""): row for row in rows}
        assessments_by_id = {
            str(row.get("overlay_candidate_id") or ""): assess_overlay_candidate(row)
            for row in rows
        }
        definition_entries, definition_rejected_candidates, definition_rejected_by_reason = _definition_candidate_entries(
            rows_by_id,
            assessments_by_id,
        )
        for reason, count in definition_rejected_by_reason.items():
            definition_verifier_rejection_counter[str(reason)] += int(count)

        raw_definition_entry_count = len(definition_entries)
        definition_entries = _filter_stage3_v3_definition_entries(
            definition_entries,
            rows_by_id=rows_by_id,
            exemplar=exemplar,
        )
        stage3_v3_definition_entries_filtered = raw_definition_entry_count - len(definition_entries)

        definition_full_candidate = _choose_definition_full_candidate(definition_entries)
        definition_full_candidate = _clamp_stage3_v3_definition_candidate_text(
            definition_full_candidate,
            rows_by_id=rows_by_id,
            exemplar=exemplar,
            field_name="definition_full_candidate",
        )
        evidence_pack_trace = _heuristic_route_policy_evidence_pack_trace(exemplar)
        evidence_pack_route = str(evidence_pack_trace.get("route") or "")

        if evidence_pack_route in {"insufficient_support_packet", "partial_grounded_packet"}:
            definition_full_candidate = {}
        elif (
            evidence_pack_route == "standard_drafting"
            and not _heuristic_route_policy_candidate_matches_ordered_role(
                definition_full_candidate,
                exemplar,
                "definition_kernel",
            )
        ):
            role_policy_candidate = _heuristic_route_policy_preferred_definition_kernel_candidate(
                exemplar,
                rows,
            )
            if role_policy_candidate:
                definition_full_candidate = role_policy_candidate

        definition_short_candidate = _choose_definition_short_candidate(
            definition_full_candidate,
            definition_entries,
        )
        definition_short_candidate = _clamp_stage3_v3_definition_candidate_text(
            definition_short_candidate,
            rows_by_id=rows_by_id,
            exemplar=exemplar,
            field_name="definition_short_candidate",
        )
        prioritized_candidate_ids = unique_preserve_order(
            [
                *[str(item) for item in definition_full_candidate.get("supporting_overlay_candidate_ids") or []],
                *[str(item) for item in definition_short_candidate.get("supporting_overlay_candidate_ids") or []],
            ]
        )
        blocked_bundle_candidate_ids = unique_preserve_order(
            [
                str(item.get("overlay_candidate_id") or "")
                for item in definition_rejected_candidates
                if any(
                    str(reason) in REVIEWER_BUNDLE_BLOCK_REASONS
                    for reason in item.get("reasons") or []
                )
            ]
        )
        selection = select_evidence_bundle(
            rows,
            max_bundle_size=max_bundle_size,
            max_explanatory_candidates=max_explanatory_candidates,
            assessments_by_id=assessments_by_id,
            prioritized_candidate_ids=prioritized_candidate_ids,
            blocked_candidate_ids=blocked_bundle_candidate_ids,
        )
        selected_bundle = list(selection["selected"])

        selected_bundle = _heuristic_route_policy_selected_bundle(
            original_bundle=selected_bundle,
            exemplar=exemplar,
            rows=rows,
            route=evidence_pack_route,
            max_bundle_size=max_bundle_size,
        )
        selection = dict(selection)
        selection["bundle"] = selected_bundle

        support_summary = _support_summary(rows, selection, definition_full_candidate)
        contamination_flags: List[str] = []
        if bool((exemplar.get("step5_3_review_queue_aux") or {}).get("in_review_queue")):
            contamination_flags.append("review_queue_weak_coverage")
        if int(support_summary.get("selected_bundle_high_contamination_candidates") or 0) > 0:
            contamination_flags.append("high_contamination_candidates_present")
        if definition_full_candidate.get("status") != "grounded" and int(support_summary.get("bare_heading_candidates") or 0) > 0:
            contamination_flags.append("heading_only_definition_risk")
        if definition_full_candidate.get("status") != "grounded" and int(support_summary.get("formula_candidates") or 0) > 0:
            contamination_flags.append("formula_only_definition_risk")
        if int(support_summary.get("selected_bundle_provenance_repair_candidates") or 0) > 0:
            contamination_flags.append("provenance_repairs_present")
        contamination_flags = unique_preserve_order(contamination_flags)

        field_hold_reasons: Dict[str, List[str]] = {}
        if definition_full_candidate.get("status") != "grounded":
            reasons = ["definition_support_insufficient"]
            if definition_rejected_by_reason:
                reasons.append("definition_candidate_verifier_rejected")
                definition_verifier_rejected_kcs += 1
            if "heading_only_definition_risk" in contamination_flags:
                reasons.append("heading_only_definition_risk")
            if "formula_only_definition_risk" in contamination_flags:
                reasons.append("formula_only_definition_risk")
            if "review_queue_weak_coverage" in contamination_flags:
                reasons.append("review_queue_weak_coverage")
            definition_full_candidate = _abstained_value(field_name="definition_full_candidate", reasons=reasons)
            field_hold_reasons["definition_full_candidate"] = reasons

        if definition_short_candidate.get("status") != "grounded":
            reasons = ["no_safe_short_extract"]
            definition_short_candidate = _abstained_value(field_name="definition_short_candidate", reasons=reasons)
            field_hold_reasons["definition_short_candidate"] = reasons

        if (
            evidence_pack_route == "standard_drafting"
            and definition_full_candidate.get("status") == "grounded"
            and definition_short_candidate.get("status") != "grounded"
        ):
            definition_short_candidate = {
                "status": "grounded",
                "text": str(definition_full_candidate.get("text") or "").strip(),
                "supporting_overlay_candidate_ids": list(
                    definition_full_candidate.get("supporting_overlay_candidate_ids") or []
                ),
                "supporting_ordered_pack_candidate_ids": list(
                    definition_full_candidate.get("supporting_ordered_pack_candidate_ids") or []
                ),
                "supporting_overlay_candidate_ids_origin": definition_full_candidate.get(
                    "supporting_overlay_candidate_ids_origin"
                ),
                "selection_reason": "same_as_route_policy_definition_full_candidate",
                "source_text_field": str(definition_full_candidate.get("source_text_field") or ""),
                "stage3_v3_role_policy": definition_full_candidate.get("stage3_v3_role_policy"),
            }

        scope_candidate = _choose_scope_candidate(
            definition_full_candidate,
            rows_by_id,
            assessments_by_id,
            selected_bundle,
        )
        if scope_candidate.get("status") != "grounded":
            reasons = ["no_safe_scope_extract"]
            scope_candidate = _abstained_value(field_name="scope_candidate", reasons=reasons)
            field_hold_reasons["scope_candidate"] = reasons

        hold_reasons = unique_preserve_order(
            reason
            for reasons in field_hold_reasons.values()
            for reason in reasons
        )
        if definition_full_candidate.get("status") != "grounded":
            draft_status = "held"
            kcs_held_for_insufficient_support += 1
            kcs_with_abstained_definitions += 1
        elif hold_reasons:
            draft_status = "draft_ready_with_holds"
        else:
            draft_status = "draft_ready"
        draft_status_counter[draft_status] += 1

        if definition_full_candidate.get("status") == "grounded":
            kcs_with_definition_candidates += 1
        if contamination_flags:
            kcs_with_contamination_flags += 1
            for flag in contamination_flags:
                contamination_flag_counter[str(flag)] += 1

        support_state = str(support_summary.get("support_state") or "insufficient_support")
        support_state_counter[support_state] += 1
        evidence_bundle_size_distribution[str(len(selected_bundle))] += 1

        source_set_ids = unique_preserve_order(
            str(row.get("source_set_id") or "")
            for row in rows
            if str(row.get("source_set_id") or "")
        )
        source_run_ids = unique_preserve_order(
            str(row.get("source_run_id") or "")
            for row in rows
            if str(row.get("source_run_id") or "")
        )
        field_provenance_map = {
            "definition_full_candidate": _field_provenance(
                field_value=definition_full_candidate,
                source_set_ids=source_set_ids,
                source_run_ids=source_run_ids,
            ),
            "definition_short_candidate": _field_provenance(
                field_value=definition_short_candidate,
                source_set_ids=source_set_ids,
                source_run_ids=source_run_ids,
            ),
            "scope_candidate": _field_provenance(
                field_value=scope_candidate,
                source_set_ids=source_set_ids,
                source_run_ids=source_run_ids,
            ),
            "evidence_bundle": {
                "status": "grounded" if selected_bundle else "abstained",
                "overlay_candidate_ids": [str(item.get("overlay_candidate_id") or "") for item in selected_bundle],
                "source_set_ids": source_set_ids,
                "source_run_ids": source_run_ids,
            },
        }
        hierarchy_fields = typed_topic_hierarchy_fields(exemplar)
        authoritative_definition_status = (
            AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED
            if definition_full_candidate.get("status") == "grounded"
            else AUTHORITATIVE_DEFINITION_STATUS_INSUFFICIENT_SUPPORT
        )
        coverage_state = {
            "status": COVERAGE_STATE_STATUS_REPRESENTED,
            "canonical_name": str(exemplar.get("canonical_name") or ""),
            "representation_basis": "hierarchy_identity",
            "source_field": "hierarchy.canonical_name",
            "review_lane_survival": True,
            "evidence_support_required": True,
        }
        evidence_pack_quality = dict(exemplar.get("evidence_pack_quality") or {})

        bundle = {
            "draft_contract_version": DRAFT_CONTRACT_VERSION,
            "semantic_contract_version": STEP67_SEMANTIC_CONTRACT_VERSION,
            "drafting_mode": HEURISTIC_DRAFTING_MODE,
            "kc_id": kc_id,
            "canonical_name": str(exemplar.get("canonical_name") or ""),
            "aliases": [str(item) for item in exemplar.get("aliases") or []],
            "authoritative_definition_status": authoritative_definition_status,
            "coverage_state": coverage_state,
            **hierarchy_fields,
            "draft_input_overlay_set_id": str(exemplar.get("draft_input_overlay_set_id") or ""),
            "draft_status": draft_status,
            "definition_full_candidate": definition_full_candidate,
            "definition_short_candidate": definition_short_candidate,
            "scope_candidate": scope_candidate,
            "evidence_bundle": selected_bundle,
            "support_summary": support_summary,
            "evidence_pack_trace": evidence_pack_trace,
            "contamination_flags": contamination_flags,
            "hold_reasons": hold_reasons,
            "field_hold_reasons": field_hold_reasons,
            "field_provenance_map": field_provenance_map,
            "selection_diagnostics": {
                "evidence_pack": {
                    "available": bool(exemplar.get("evidence_pack_available", False)),
                    "version": str(exemplar.get("evidence_pack_version") or ""),
                    "route": str(evidence_pack_quality.get("route") or ""),
                    "definition_anchor_present": bool(evidence_pack_quality.get("definition_anchor_present", False)),
                    "definition_anchor_natural_language": bool(
                        evidence_pack_quality.get("definition_anchor_natural_language", False)
                    ),
                    "formula_dominance_risk": str(evidence_pack_quality.get("formula_dominance_risk") or ""),
                    "sibling_contamination_risk": str(
                        evidence_pack_quality.get("sibling_contamination_risk") or ""
                    ),
                    "context_completion_used": bool(evidence_pack_quality.get("context_completion_used", False)),
                    "ordered_pack_count": len(exemplar.get("ordered_pack_for_drafting") or []),
                    "stage3_v3_definition_entries_filtered": stage3_v3_definition_entries_filtered,
                    "stage3_v3_definition_entry_count_after_filter": len(definition_entries),
                },
                "prioritized_candidate_ids": prioritized_candidate_ids,
                "blocked_bundle_candidate_ids": blocked_bundle_candidate_ids,
                "selected_candidate_ids": [str(item.get("overlay_candidate_id") or "") for item in selected_bundle],
                "excluded_by_reason": dict(selection.get("excluded_by_reason") or {}),
                "excluded_candidates": list(selection.get("excluded") or []),
                "definition_candidate_diagnostics": {
                    "selected_candidate_id": (
                        str((definition_full_candidate.get("supporting_overlay_candidate_ids") or [""])[0])
                        if definition_full_candidate.get("supporting_overlay_candidate_ids")
                        else ""
                    ),
                    "accepted_candidate_ids": [str(item.get("candidate_id") or "") for item in definition_entries[:5]],
                    "rejected_by_reason": definition_rejected_by_reason,
                    "rejected_candidates": definition_rejected_candidates[:10],
                },
            },
            "step5_3_review_queue_aux": dict(exemplar.get("step5_3_review_queue_aux") or {}),
            "source_run_id": source_run_ids[0] if source_run_ids else "",
            "source_set_id": source_set_ids[0] if source_set_ids else "",
        }
        bundles.append(bundle)

    stats = {
        "draft_contract_version": DRAFT_CONTRACT_VERSION,
        "drafting_mode": HEURISTIC_DRAFTING_MODE,
        "total_kcs": len(bundles),
        "kcs_with_definition_candidates": kcs_with_definition_candidates,
        "kcs_with_abstained_definitions": kcs_with_abstained_definitions,
        "kcs_with_contamination_flags": kcs_with_contamination_flags,
        "kcs_held_for_insufficient_support": kcs_held_for_insufficient_support,
        "definition_verifier_rejected_kcs": definition_verifier_rejected_kcs,
        "definition_verifier_rejection_breakdown": dict(sorted(definition_verifier_rejection_counter.items())),
        "draft_status_breakdown": dict(sorted(draft_status_counter.items())),
        "support_state_breakdown": dict(sorted(support_state_counter.items())),
        "evidence_bundle_size_distribution": dict(sorted(evidence_bundle_size_distribution.items())),
        "contamination_flag_breakdown": dict(sorted(contamination_flag_counter.items())),
    }
    return bundles, stats
