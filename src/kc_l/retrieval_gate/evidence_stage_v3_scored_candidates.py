from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from kc_l.audit.manifests import build_output_manifest, env_snapshot, try_cmd_version
from kc_l.retrieval_gate.evidence_stage_v3_candidate_bank import (
    InputSpec,
    input_spec_exists,
    parse_input_spec,
    read_json_from_spec,
    read_jsonl_from_spec,
    resolve_related_input_spec,
    resolve_repo_path,
)
from kc_l.retrieval_gate.shapeaware_shadow import classify_shapeaware_candidate
from kc_l.retrieval_gate.evidence_admission import decide_evidence_admission
from kc_l.retrieval_gate.structural_role_anchor import apply_structural_role_anchoring
from kc_l.retrieval_windowing.semantic import match_normalize, normalize_ws, tokenize, unique_preserve_order
from kc_l.utils.json_io import write_json, write_jsonl


REPO_ROOT = Path(__file__).resolve().parents[3]
SCORED_CANDIDATE_CONTRACT_VERSION = "step5x_v3_scored_candidates_v1"
SOURCE_SURFACE_STAGE2 = "step5x_v3_candidate_bank"
DEFAULT_OUTPUT_ROOT = "data/processed/evidence_stage_v3_scored_candidates"
DEFAULT_SET_MANIFEST_ROOT = "data/processed/evidence_stage_v3_scored_candidates/_sets"
FORBIDDEN_SEED_FIELDS = {"seed_definition", "seed_keywords"}
FORBIDDEN_PACK_FIELDS = {"pack_quality", "ordered_pack_for_drafting", "slots", "eligibility"}
HYBRID_BINDING_MIN_PROB = 0.5

STANDALONE_POSITIVE_ROLES = (
    "definition_kernel",
    "explanatory_gloss",
    "scope_condition",
    "formula_notation",
    "example_or_procedure",
)
AUXILIARY_ROLES = ("context_completion_candidate",)
GUARDRAIL_ROLES = ("sibling_contrast",)
POSITIVE_ROLES = STANDALONE_POSITIVE_ROLES
ALL_ROLES = (*STANDALONE_POSITIVE_ROLES, *AUXILIARY_ROLES, *GUARDRAIL_ROLES)
SCORABLE_ROLES = (
    *STANDALONE_POSITIVE_ROLES,
    "context_completion_candidate",
    "example_or_procedure",
    "sibling_contrast",
)

# Positive-support guard is deliberately separate from role_eligibility.
# A row can be valid as formula/context/review evidence while still being
# blocked from drafting-pack positive support.
STRICT_POSITIVE_SUPPORT_BLOCKER_FLAGS = (
    "definition_subject_mismatch",
    "no_target_binding",
    "candidate_pool_membership_only",
    "bibliography_like",
    "reference_like",
    "context_only_support",
    "source_kc_mismatch",
    "sibling_competitor_dominant",
    "profile_route_positive_support_blocked",
)

CONDITIONAL_POSITIVE_SUPPORT_BLOCKER_FLAGS = (
    "needs_stronger_anchor_context",
    "formula_without_target_binding",
)


def _positive_support_guard(
    *,
    risk_flags: Sequence[Any],
    role_eligibility: Mapping[str, Any],
    lexical_target_binding: Mapping[str, Any],
    definition_framing: Mapping[str, Any],
    direct_target_statement: Mapping[str, Any],
    candidate_quality: Mapping[str, Any],
    unit_type: str = "kc",
) -> Dict[str, Any]:
    """Return pack-authority guard metadata without mutating role eligibility."""
    normalized_unit_type = str(unit_type or "kc").strip().lower()
    observed = {str(flag) for flag in risk_flags or [] if str(flag).strip()}
    strict_basis_reasons: List[str] = []

    if normalized_unit_type != "kc":
        return {
            "guard_version": "step5x_positive_support_guard_v1",
            "applies_to_unit_type": normalized_unit_type,
            "blocked_from_positive_support": False,
            "blocker_flags": [],
            "strict_blocker_flags": [],
            "conditional_blocker_flags": [],
            "strict_target_basis": True,
            "strict_target_basis_reasons": ["topic_unit_not_forced_through_kc_positive_support_guard"],
            "pack_action": "allow_pack_composer_to_apply_topic_policy",
        }

    basis = _as_dict(candidate_quality.get("target_bound_positive_support_basis"))

    if bool(role_eligibility.get("strict_fallback_definition_kernel_override")) or bool(basis.get("strict_fallback_definition_kernel_override")):
        strict_basis_reasons.append("strict_fallback_definition_kernel_override")

    formula_without_target_binding = "formula_without_target_binding" in observed
    formula_target_basis_override = bool(
        role_eligibility.get("formula_target_basis_override")
        or basis.get("formula_target_basis_override")
        or bool(direct_target_statement.get("is_direct_target_statement"))
        or bool(basis.get("direct_target_statement"))
        or (
            bool(lexical_target_binding.get("is_target_bound"))
            and str(lexical_target_binding.get("binding_strength") or "") in {"strong", "usable"}
        )
        or bool(basis.get("lexical_target_bound"))
        or bool(role_eligibility.get("strict_fallback_definition_kernel_override"))
        or bool(basis.get("strict_fallback_definition_kernel_override"))
    )

    structural_formula_basis = bool(
        role_eligibility.get("structural_anchor_formula_support")
        or basis.get("structural_anchor_formula_support")
    )
    if structural_formula_basis and not (formula_without_target_binding and not formula_target_basis_override):
        strict_basis_reasons.append("structural_anchor_formula_support")

    if bool(direct_target_statement.get("is_direct_target_statement")) or bool(basis.get("direct_target_statement")):
        strict_basis_reasons.append("direct_target_statement")

    if bool(lexical_target_binding.get("is_target_bound")) and str(lexical_target_binding.get("binding_strength") or "") in {"strong", "usable"}:
        strict_basis_reasons.append("target_bound_lexical_binding")

    if str(definition_framing.get("subject_alignment") or "") in {"aligned", "compatible"}:
        strict_basis_reasons.append("definition_subject_aligned_or_compatible")

    strict_target_basis = bool(strict_basis_reasons)

    strict_blockers = [flag for flag in STRICT_POSITIVE_SUPPORT_BLOCKER_FLAGS if flag in observed]
    conditional_blockers = [
        flag for flag in CONDITIONAL_POSITIVE_SUPPORT_BLOCKER_FLAGS
        if flag in observed
        and flag != "formula_without_target_binding"
        and not strict_target_basis
    ]
    if formula_without_target_binding and not formula_target_basis_override:
        conditional_blockers.append("formula_without_target_binding")
    blockers = unique_preserve_order([*strict_blockers, *conditional_blockers])

    return {
        "guard_version": "step5x_positive_support_guard_v1",
        "applies_to_unit_type": normalized_unit_type,
        "blocked_from_positive_support": bool(blockers),
        "blocker_flags": blockers,
        "strict_blocker_flags": strict_blockers,
        "conditional_blocker_flags": conditional_blockers,
        "strict_target_basis": strict_target_basis,
        "strict_target_basis_reasons": unique_preserve_order(strict_basis_reasons),
        "pack_action": "near_miss_review_only" if blockers else "allow_positive_support_candidate",
    }


GLUE_TOKENS = {
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
    "in",
    "into",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}
BROAD_HEAD_TOKENS = {
    "analysis",
    "approach",
    "approaches",
    "basic",
    "basics",
    "coefficient",
    "coefficients",
    "concept",
    "concepts",
    "distance",
    "distances",
    "data",
    "handling",
    "index",
    "indices",
    "information",
    "introduction",
    "measure",
    "measures",
    "method",
    "methods",
    "metric",
    "metrics",
    "model",
    "models",
    "overview",
    "point",
    "points",
    "procedure",
    "procedures",
    "process",
    "processes",
    "score",
    "scores",
    "system",
    "systems",
    "technique",
    "techniques",
    "theory",
    "type",
    "types",
    "validation",
    "value",
    "values",
}
GENERIC_TARGET_SUFFIX_TOKENS = BROAD_HEAD_TOKENS | {
    "definition",
    "definitions",
    "formula",
    "formulas",
    "ratio",
    "ratios",
    "relation",
    "relations",
}
FRAGMENT_PREFIX_RE = re.compile(r"^(?:and|or|but|because|while|where|when|if|then|thus|therefore|however|for|to)\b")
TRAILING_FRAGMENT_RE = re.compile(r"(?:[,;:]|(?:\b(?:and|or|but|because|while|where|when|if|then)\s*))$")
DEFINITION_LINK_RE = re.compile(
    r"\b(?:is|are|was|were|refers to|defined as|known as|called|means|denotes|describes|represents|measures)\b"
)
FORMULA_NOTATION_RE = re.compile(
    r"(?:\\(?:sum|frac|sqrt|log|begin|end|mathbb|mathbf|operatorname)\b|"
    r"\b(?:argmax|argmin)\b|"
    r"(?:^|[\s\(\[])"
    r"(?:P|p|f|g|h|O|x|y|z|t|n|m|k|d|w|b|mu|sigma|theta|lambda)"
    r"\s*[\(\[]|"
    r"[=<>≤≥≈∑Σ]|"
    r"\b(?:equation|eq\.|table|figure|fig\.)\s*\d+)"
)
MATHISH_RE = re.compile(
    r"(?:[$\\{}_^]|(?:\b[a-zA-Z]\s*[\*\^_]\s*[a-zA-Z0-9])|(?:\b[a-zA-Z]\s*[\(\[]))"
)
CAPTION_RE = re.compile(r"^(?:figure|fig\.|table|algorithm|listing|chart)\b")
PROMPT_RE = re.compile(r"^(?:describe|explain|compare|discuss|consider|identify|list|state|suppose|show)\b")
# 2026-07-27 fix: the single flat word-list version of this regex had an 80-90% real false-
# trigger rate (confirmed against this week's real hard-rejects) - "avoid", "must not", "should
# not" fire equally on genuine meta-instructional asides ("a common mistake is...") and on
# ordinary technical description ("avoid computing many similarities", "must not exceed",
# "should not only X but also Y"), which share none of the former's warn-the-reader framing.
# Split into two categories instead of one flat list: MISTAKE_NOUN_RE covers nouns that are
# inherently about error/confusion and can stand alone; WARNING_MODAL_RE covers generic
# modal/caution words that are too common in plain technical prose to trust alone and now
# require co-occurrence with a mistake noun (see _meta_guidance_signal). This reorganizes the
# same existing word set into two co-occurrence-gated categories - it adds no new vocabulary and
# references no specific domain's terms, so it stays domain-agnostic.
# "confus(e/ing/ion)" was dropped from this set after A/B verification against real data caught
# it matching "confusion matrix" - a standard classifier-evaluation term with no relation to
# reader confusion, not a domain-specific term being special-cased, just too collision-prone to
# trust as a bare substring anywhere general prose might discuss confusion matrices.
META_GUIDANCE_MISTAKE_NOUN_RE = re.compile(r"\b(?:common\s+mistakes?|mistakes?|pitfalls?)\b")
META_GUIDANCE_WARNING_MODAL_RE = re.compile(r"\b(?:caution|warning|avoid|be\s+careful|should\s+not|must\s+not)\b")
REFERENCE_LIKE_RE = re.compile(
    r"\b(?:reference|references|bibliography|cited|citation|article|paper|journal|proceedings|et\s+al\.?|doi|isbn)\b"
)
BIBLIOGRAPHY_HEADING_RE = re.compile(r"\b(?:references|bibliography|works\s+cited|further\s+reading)\b")
# 2026-07-27 fix: patch_heading is document-chunking-derived metadata, not a judgment about the
# candidate's OWN text - confirmed real incident, 8/8 real bibliography_like hard-rejects this
# week were substantive, on-topic technical prose (e.g. "the remaining redundant attributes
# would show little to no FOIL's information gain") sitting under a "Bibliography" heading
# purely because of where the source PDF's chunk boundary fell, not because the text itself is
# a reference-list entry. This is a purely structural/syntactic pattern (bracketed numeric
# citation clusters, or a capitalized-name-plus-parenthesized-year author-citation shape) - no
# Data Mining or any other domain vocabulary is referenced, so it generalizes to any corpus.
CITATION_ENTRY_RE = re.compile(
    r"(?:\[\d+\][,;]?\s*){2,}|\b[A-Z][a-zA-Z'\-]+,?\s+(?:and\s+|&\s+)?[A-Z][a-zA-Z'\-]+\.?\s*\(\d{4}\)"
)
NUMBERED_STEP_RE = re.compile(r"^\s*(?:\d+[\.\)]|[-*])\s+")
IF_THEN_RE = re.compile(r"\bif\b.*\bthen\b")
EXAMPLE_RE = re.compile(r"\b(?:example|for example|for instance|e\.g\.)\b")
PROCEDURE_RE = re.compile(
    r"(?:\b(?:procedure|step|steps|repeat|compute|calculate|return|iterate|first|second|third|finally)\b|as follows)"
)
SCOPE_RE = re.compile(
    r"\b(?:if|when|unless|under|assuming|provided that|subject to|in the case of|for a given|whenever|only if)\b"
)
CONTRAST_RE = re.compile(r"\b(?:not|but|whereas|rather than|instead of|neither|versus|vs\.)\b")
GENERIC_SUBJECT_RE = re.compile(r"^(?:a|an|the)?\s*(?:concept|measure|metric|method|procedure|approach|process)\b")
NEGATIVE_TARGET_RELATION_TEMPLATES = (
    r"\b[^\.]{{0,80}}\b(?:is|are|was|were)\s+not\s+(?:a|an|the)?\s*{target}\b",
    r"\b[^\.]{{0,80}}\b(?:is|are|was|were)\s+neither\s+(?:a|an|the)?\s*{target}\b",
    r"\b[^\.]{{0,80}}\b(?:within|close to|near|belongs to|falls within)[^\.]{{0,80}}\b{target}\b",
)
REQUIRED_STAGE1_FIELDS = (
    "candidate_id",
    "candidate_bank_version",
    "kc_id",
    "canonical_name",
    "aliases",
    "topic_path_ids",
    "topic_path_labels",
    "parent_topic_id",
    "parent_topic_label",
    "source_kc_id",
    "source_canonical_name",
    "granularity",
    "text",
    "source_block_text",
    "context_text",
    "doc_id",
    "page_index",
    "block_id",
    "sentence_id",
    "sent_idx",
    "patch_id",
    "patch_heading",
    "reveal_group_id",
    "layer",
    "bbox",
    "char_start",
    "char_end",
    "retrieval_scores",
    "alignment_score",
    "alignment_breakdown",
    "support_profile",
    "structural_flags",
    "raw_text_hash",
    "provenance",
    "source_row_index",
    "source_evidence_index",
)


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _stringify_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _as_text(value: Any) -> str:
    return normalize_ws(str(value or ""))


def _as_int(value: Any, *, default: int | None = None) -> Optional[int]:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except Exception:
        return default


def _as_float(value: Any, *, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {}


def _as_str_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        text = _as_text(item)
        if text:
            out.append(text)
    return out


def _content_tokens(
    text: str,
    *,
    min_len: int = 2,
    remove_broad_heads: bool = False,
) -> List[str]:
    tokens = [token for token in tokenize(match_normalize(text), min_len=min_len) if token not in GLUE_TOKENS]
    if remove_broad_heads:
        tokens = [token for token in tokens if token not in BROAD_HEAD_TOKENS]
    return tokens


def _target_phrase_pattern(target_phrases: Sequence[str]) -> re.Pattern[str] | None:
    phrases = [phrase for phrase in unique_preserve_order([match_normalize(item) for item in target_phrases if _as_text(item)]) if phrase]
    if not phrases:
        return None
    phrases.sort(key=len, reverse=True)
    escaped = [re.escape(phrase).replace(r"\ ", r"[-\s]+") for phrase in phrases]
    return re.compile(r"\b(?:" + "|".join(escaped) + r")\b")


def _best_target_overlap(
    text_tokens: Sequence[str],
    phrase_token_sets: Sequence[Sequence[str]],
) -> Tuple[int, float, List[str], int]:
    token_set = set(text_tokens)
    best_matches = 0
    best_ratio = 0.0
    best_phrase: List[str] = []
    best_decisive_matches = 0
    for token_list in phrase_token_sets:
        deduped = unique_preserve_order(list(token_list))
        if not deduped:
            continue
        phrase_set = set(deduped)
        matches = len(token_set & phrase_set)
        ratio = float(matches) / float(len(phrase_set))
        decisive_tokens = [token for token in deduped if token not in BROAD_HEAD_TOKENS]
        decisive_matches = len(token_set & set(decisive_tokens)) if decisive_tokens else 0
        if (
            matches > best_matches
            or (matches == best_matches and ratio > best_ratio)
            or (matches == best_matches and abs(ratio - best_ratio) < 1e-9 and decisive_matches > best_decisive_matches)
        ):
            best_matches = matches
            best_ratio = ratio
            best_phrase = deduped
            best_decisive_matches = decisive_matches
    return best_matches, round(best_ratio, 6), best_phrase, best_decisive_matches


def _binding_strength_value(strength: str) -> int:
    return {"none": 0, "weak": 1, "usable": 2, "strong": 3}.get(str(strength or "none"), 0)


def _strength_at_least(strength: str, threshold: str) -> bool:
    return _binding_strength_value(strength) >= _binding_strength_value(threshold)


def _natural_language_like(text: str, *, formula_like: bool = False) -> bool:
    tokens = _content_tokens(text, min_len=2)
    if not tokens:
        return False
    if formula_like and len(tokens) <= 6 and DEFINITION_LINK_RE.search(match_normalize(text)) is None:
        return False
    return len(tokens) >= 4


def _actual_formula_notation(candidate_row: Mapping[str, Any]) -> bool:
    text = _as_text(candidate_row.get("text") or candidate_row.get("candidate_text"))
    source_block_text = _as_text(candidate_row.get("source_block_text"))
    if FORMULA_NOTATION_RE.search(text):
        return True
    if source_block_text and FORMULA_NOTATION_RE.search(source_block_text):
        return True
    return False


def _mathish_prose(candidate_row: Mapping[str, Any], *, actual_formula: bool) -> bool:
    if actual_formula:
        return False
    text = _as_text(candidate_row.get("text") or candidate_row.get("candidate_text"))
    structural_flags = _as_dict(candidate_row.get("structural_flags"))
    return bool(structural_flags.get("looks_formula_like") or MATHISH_RE.search(text))


def _topic_tokens(candidate_row: Mapping[str, Any]) -> Tuple[List[str], List[str]]:
    parent_topic_tokens = _content_tokens(_as_text(candidate_row.get("parent_topic_label")), min_len=2, remove_broad_heads=True)
    topic_tokens: List[str] = []
    for label in _as_str_list(candidate_row.get("topic_path_labels")):
        topic_tokens.extend(_content_tokens(label, min_len=2, remove_broad_heads=True))
    return unique_preserve_order(parent_topic_tokens), unique_preserve_order(topic_tokens)


def _target_binding_profile(candidate_row: Mapping[str, Any]) -> Dict[str, Any]:
    canonical_name = _as_text(candidate_row.get("canonical_name"))
    aliases = _as_str_list(candidate_row.get("aliases"))
    target_phrases = unique_preserve_order([canonical_name, *aliases])
    canonical_tokens = unique_preserve_order(_content_tokens(canonical_name, min_len=2))
    alias_token_lists = [unique_preserve_order(_content_tokens(alias, min_len=2)) for alias in aliases if _as_text(alias)]
    alias_tokens = unique_preserve_order(token for token_list in alias_token_lists for token in token_list)
    phrase_token_sets = [canonical_tokens, *alias_token_lists]
    qualifier_tokens = unique_preserve_order(
        token for token in canonical_tokens if token not in BROAD_HEAD_TOKENS and token not in GLUE_TOKENS
    )
    parent_topic_tokens, topic_path_tokens = _topic_tokens(candidate_row)
    family_tokens = unique_preserve_order(
        [
            *parent_topic_tokens,
            *(
                token
                for token in alias_tokens
                if token not in BROAD_HEAD_TOKENS and (token not in canonical_tokens or token in parent_topic_tokens)
            ),
            *(token for token in qualifier_tokens if len(token) <= 3),
        ]
    )
    ambiguous_target = bool(
        len(canonical_tokens) <= 2
        or (len(qualifier_tokens) <= 1 and any(token in BROAD_HEAD_TOKENS for token in canonical_tokens))
    )
    return {
        "canonical_tokens": canonical_tokens,
        "alias_token_lists": alias_token_lists,
        "phrase_token_sets": [tokens for tokens in phrase_token_sets if tokens],
        "target_phrases": target_phrases,
        "qualifier_tokens": qualifier_tokens,
        "parent_topic_tokens": parent_topic_tokens,
        "topic_path_tokens": topic_path_tokens,
        "family_tokens": family_tokens,
        "ambiguous_target": ambiguous_target,
    }


def _candidate_text_context(candidate_row: Mapping[str, Any]) -> Dict[str, Any]:
    text = _as_text(candidate_row.get("text") or candidate_row.get("candidate_text"))
    source_block_text = _as_text(candidate_row.get("source_block_text"))
    heading_text = _as_text(candidate_row.get("patch_heading"))
    text_tokens = _content_tokens(text, min_len=2)
    source_block_tokens = _content_tokens(source_block_text, min_len=2)
    heading_tokens = _content_tokens(heading_text, min_len=2)
    combined_tokens = unique_preserve_order([*text_tokens, *source_block_tokens, *heading_tokens])
    return {
        "text": text,
        "source_block_text": source_block_text,
        "heading_text": heading_text,
        "text_norm": match_normalize(text),
        "source_block_norm": match_normalize(source_block_text),
        "heading_norm": match_normalize(heading_text),
        "text_tokens": text_tokens,
        "source_block_tokens": source_block_tokens,
        "heading_tokens": heading_tokens,
        "combined_tokens": combined_tokens,
    }


def _profile_route_evaluation(candidate_row: Mapping[str, Any]) -> Dict[str, Any]:
    route_eval = _as_dict(candidate_row.get("step5p_route_evaluation"))
    if not route_eval:
        return {
            "route_contract_present": False,
            "matched_route_count": 0,
            "positive_route_match_count": 0,
            "context_only_route_match_count": 0,
            "route_positive_blocked_by_missing_support_count": 0,
            "context_only_match_without_positive_route": False,
            "missing_support_blocks_profile_route_positive": False,
            "route_contract_positive_match_required": False,
            "positive_support_block_reason": "",
        }
    context_only_without_positive = bool(route_eval.get("context_only_match_without_positive_route"))
    missing_support_without_positive = bool(
        int(route_eval.get("route_positive_blocked_by_missing_support_count") or 0) > 0
        and int(route_eval.get("positive_route_match_count") or 0) == 0
    )
    alignment = _as_dict(candidate_row.get("alignment_breakdown"))
    direct_surface_named = bool(
        alignment.get("exact_name_phrase") or alignment.get("exact_alias_phrase")
    )
    route_contract_present = bool(route_eval.get("route_contract_present"))
    positive_route_count = int(route_eval.get("positive_route_match_count") or 0)
    # If Step 5p supplied a route contract, non-surface-named positive evidence
    # must be supported by at least one positive route match. Otherwise broad
    # rows found near a context locator can leak into the leaf-KC evidence pack.
    route_contract_positive_required = bool(
        route_contract_present
        and positive_route_count == 0
        and not direct_surface_named
    )
    # Route-level missing support blocks positive support only when the route is
    # the apparent source of the target binding. Direct exact-surface evidence,
    # whether canonical or alias-based, remains eligible through normal Step 5x
    # gates.
    block_missing_support = bool(
        missing_support_without_positive and not direct_surface_named
    )
    reason = ""
    if context_only_without_positive:
        reason = "context_only_profile_route_without_positive_route"
    elif block_missing_support:
        reason = "profile_route_required_support_missing"
    elif route_contract_positive_required:
        reason = "profile_route_contract_without_positive_route_match"
    return {
        "route_contract_present": route_contract_present,
        "matched_route_count": int(route_eval.get("matched_route_count") or 0),
        "positive_route_match_count": positive_route_count,
        "context_only_route_match_count": int(route_eval.get("context_only_route_match_count") or 0),
        "route_positive_blocked_by_missing_support_count": int(route_eval.get("route_positive_blocked_by_missing_support_count") or 0),
        "context_only_match_without_positive_route": context_only_without_positive,
        "missing_support_blocks_profile_route_positive": block_missing_support,
        "route_contract_positive_match_required": route_contract_positive_required,
        "positive_support_block_reason": reason,
        "matched_routes": route_eval.get("matched_routes") or [],
        "route_control_role": route_eval.get("route_control_role") or "step5p_retrieval_control_metadata_not_evidence",
    }


def _parent_topic_alignment(
    candidate_row: Mapping[str, Any],
    profile: Mapping[str, Any],
    context: Mapping[str, Any],
) -> Dict[str, Any]:
    combined_tokens = set(context.get("combined_tokens") or [])
    parent_topic_hits = sorted(combined_tokens & set(profile.get("parent_topic_tokens") or []))
    topic_path_hits = sorted(combined_tokens & set(profile.get("topic_path_tokens") or []))
    source_kc_match = bool(
        _as_text(candidate_row.get("source_kc_id")) and _as_text(candidate_row.get("source_kc_id")) == _as_text(candidate_row.get("kc_id"))
    )
    reasons: List[str] = []
    strength = "none"
    if source_kc_match:
        reasons.append("source_kc_match")
    if parent_topic_hits:
        reasons.append("parent_topic_tokens_present")
    if topic_path_hits:
        reasons.append("topic_path_tokens_present")
    if source_kc_match and (parent_topic_hits or topic_path_hits):
        strength = "strong"
    elif len(parent_topic_hits) >= 2 or len(topic_path_hits) >= 2:
        strength = "strong"
    elif source_kc_match or parent_topic_hits or topic_path_hits:
        strength = "usable"
    elif _as_text(candidate_row.get("source_kc_id")) and _as_text(candidate_row.get("source_kc_id")) != _as_text(candidate_row.get("kc_id")):
        strength = "conflicting"
        reasons.append("source_kc_mismatch")
    return {
        "alignment_strength": strength,
        "parent_topic_hits": parent_topic_hits,
        "topic_path_hits": topic_path_hits,
        "source_kc_match": source_kc_match,
        "reasons": unique_preserve_order(reasons),
    }


def _candidate_target_binding(
    candidate_row: Mapping[str, Any],
    *,
    profile: Mapping[str, Any],
    context: Mapping[str, Any],
    parent_alignment: Mapping[str, Any],
    global_candidate_usage: Mapping[str, Any] | None,
    cfg: Mapping[str, Any],
) -> Dict[str, Any]:
    thresholds = default_scoring_cfg(cfg)
    structural_flags = _as_dict(candidate_row.get("structural_flags"))
    alignment_breakdown = _as_dict(candidate_row.get("alignment_breakdown"))
    support_profile = _as_dict(candidate_row.get("support_profile"))
    text_tokens = list(context.get("text_tokens") or [])
    source_block_tokens = list(context.get("source_block_tokens") or [])
    heading_tokens = list(context.get("heading_tokens") or [])
    target_phrases = list(profile.get("target_phrases") or [])
    phrase_token_sets = list(profile.get("phrase_token_sets") or [])
    qualifier_tokens = set(profile.get("qualifier_tokens") or [])
    family_tokens = set(profile.get("family_tokens") or [])
    exact_pattern = _target_phrase_pattern(target_phrases)
    text_norm = str(context.get("text_norm") or "")
    source_block_norm = str(context.get("source_block_norm") or "")
    heading_norm = str(context.get("heading_norm") or "")
    text_exact = bool(exact_pattern.search(text_norm)) if exact_pattern is not None else False
    source_block_exact = bool(exact_pattern.search(source_block_norm)) if exact_pattern is not None else False
    heading_exact = bool(exact_pattern.search(heading_norm)) if exact_pattern is not None else False
    text_matches, text_ratio, matched_text_phrase, decisive_text_matches = _best_target_overlap(text_tokens, phrase_token_sets)
    source_matches, source_ratio, matched_source_phrase, decisive_source_matches = _best_target_overlap(source_block_tokens, phrase_token_sets)
    heading_matches, heading_ratio, matched_heading_phrase, decisive_heading_matches = _best_target_overlap(heading_tokens, phrase_token_sets)
    combined_tokens = set(context.get("combined_tokens") or [])
    qualifier_hits = sorted(combined_tokens & qualifier_tokens)
    parent_topic_hits = list(parent_alignment.get("parent_topic_hits") or [])
    family_hits = sorted(combined_tokens & family_tokens)
    source_kc_match = bool(parent_alignment.get("source_kc_match", False))
    competitor_hits = _as_int(alignment_breakdown.get("competitor_token_hits"), default=0) or 0
    broad_only_match = bool(
        text_matches > 0
        and decisive_text_matches == 0
        and source_matches <= 1
        and heading_matches <= 1
    )

    usage = _usage_for_candidate(candidate_row, global_candidate_usage)
    # Sibling-aware (2026-07-26 fix): use the *_foreign_topic_kc_count fields, not the raw
    # *_kc_count ones - see _usage_for_candidate's own docstring for the confirmed false-positive
    # this fixes (KC_CLU_EVAL_002 "SSE" content wrongly flagged purely for recurring across
    # sibling clustering-evaluation KCs). Always <= the raw count, so this can only relax
    # over-triggering, never newly trigger a case the raw count wouldn't already have caught.
    recurring_without_target = bool(
        usage["raw_text_hash_foreign_topic_kc_count"] >= int(thresholds["global_recurring_text_kc_threshold"])
        or usage["normalized_text_foreign_topic_kc_count"] >= int(thresholds["global_recurring_text_kc_threshold"])
        or (
            usage["patch_foreign_topic_kc_count"] >= int(thresholds["global_recurring_patch_kc_threshold"])
            and usage["patch_foreign_topic_kc_count"] > 0
        )
    )

    # Target-binding strength ladder (Phase 3.5 rank #2 / audit codebase-audit-20260805 item 3):
    # the match-count/ratio cutoffs below (text_matches>=3, ratio>=0.95 for "strong";
    # text_matches>=2 + decisive_text_matches>=1 + ratio>=0.5 for "usable"; analogous
    # source-block/heading variants) are literal constants, not config-overridable like the
    # thresholds dict entries elsewhere in this function - unlike the six role-score thresholds
    # (see default_scoring_cfg's min_definition_score et al., empirically calibrated 2026-07-27
    # from 360 hand-judged examples, commit ab1b7d2), no dedicated per-parameter calibration study
    # exists for this specific family, and the repo's git history (13 total commits) has no earlier
    # record of one either.
    #
    # Investigated as part of this audit and left unchanged, documented as an accepted, reasoned
    # default per the audit's own explicit fallback (real calibration wasn't feasible to redo for
    # every constant in this session): the ladder is internally coherent (exact phrase match beats
    # near-total multi-token overlap beats majority overlap-with-a-decisive-token beats any single
    # token), and - more than merely "never checked" - this exact, unmodified ladder is what ran
    # across the full 5-config, step_05x-through-step_06_8 corpus regeneration this session
    # (research_notes/step5p_5x_audits/FINAL_window_capture_fix_and_regeneration_20260805.md):
    # 0 ordered_evidence_admission_violation_count / 0 ordered_sibling_violation_count / 0 new
    # regressions across all 5 configs. Real, if not isolated-per-constant, evidence of correctness
    # at the scale that matters (whole-pipeline output), not a silently unexamined magic-number set.
    binding_reasons: List[str] = []
    offtarget_reasons: List[str] = []
    binding_strength = "none"

    if text_exact:
        binding_strength = "strong"
        binding_reasons.append("exact_target_phrase_in_text")
    elif text_matches >= 3 or (text_matches >= 2 and text_ratio >= 0.95):
        binding_strength = "strong"
        binding_reasons.append("multi_token_target_match_in_text")
    elif text_matches >= 2 and decisive_text_matches >= 1 and text_ratio >= 0.5:
        binding_strength = "usable"
        binding_reasons.append("partial_target_phrase_overlap_in_text")
    elif (
        bool(thresholds["count_source_block_target_hits"])
        and source_block_exact
        and bool(structural_flags.get("looks_fragmentary") or structural_flags.get("looks_formula_like"))
    ):
        binding_strength = "usable"
        binding_reasons.append("target_phrase_recovered_from_source_block")
    elif (
        bool(thresholds["count_source_block_target_hits"])
        and source_matches >= 2
        and decisive_source_matches >= 1
        and source_ratio >= 0.5
        and bool(structural_flags.get("looks_fragmentary") or structural_flags.get("looks_formula_like"))
    ):
        binding_strength = "usable"
        binding_reasons.append("partial_target_phrase_overlap_in_source_block")
    elif (
        bool(thresholds["allow_heading_only_target_recovery"])
        and heading_exact
        and (text_matches >= 1 or source_matches >= 1 or bool(structural_flags.get("looks_fragmentary")))
    ):
        binding_strength = "usable"
        binding_reasons.append("exact_target_phrase_in_heading")
    elif heading_matches >= 2 and decisive_heading_matches >= 1:
        binding_strength = "usable"
        binding_reasons.append("heading_plus_local_target_overlap")
    elif text_matches >= 1 or source_matches >= 1 or heading_matches >= 1:
        binding_strength = "weak"
        binding_reasons.append("single_target_token_or_metadata_overlap")

    if qualifier_hits:
        binding_reasons.append("qualifier_or_parent_topic_alignment")
    elif parent_topic_hits:
        binding_reasons.append("parent_topic_alignment")
    if family_hits:
        binding_reasons.append("family_alignment")

    if broad_only_match:
        offtarget_reasons.append("broad_phrase_overlap_only")
    if competitor_hits >= max(2, text_matches + source_matches + heading_matches):
        offtarget_reasons.append("sibling_or_competitor_stronger_than_target")
        if binding_strength != "strong":
            binding_strength = "weak"
    if _as_text(candidate_row.get("source_kc_id")) and _as_text(candidate_row.get("source_kc_id")) != _as_text(candidate_row.get("kc_id")):
        if not source_kc_match and not _strength_at_least(binding_strength, "usable"):
            offtarget_reasons.append("source_kc_mismatch_without_target_cue")
            binding_strength = "weak"
    if bool(alignment_breakdown.get("doc_mismatch", False)):
        offtarget_reasons.append("doc_mismatch")
    if bool(support_profile.get("generic_context_only", False)):
        offtarget_reasons.append("generic_context_only")
    if qualifier_tokens and _strength_at_least(binding_strength, "usable") and not (qualifier_hits or parent_topic_hits or source_kc_match):
        offtarget_reasons.append("qualifier_or_parent_topic_missing")
        binding_strength = "weak"
    if (
        bool(thresholds.get("require_family_alignment_when_available", True))
        and family_tokens
        and _strength_at_least(binding_strength, "usable")
        and not text_exact
        and not family_hits
        and not parent_topic_hits
    ):
        offtarget_reasons.append("family_alignment_missing_for_broad_target")
        binding_strength = "weak"
    if (
        bool(profile.get("ambiguous_target", False))
        and _strength_at_least(binding_strength, "usable")
        and not (parent_topic_hits or source_kc_match)
        and not text_exact
    ):
        offtarget_reasons.append("parent_topic_alignment_missing_for_ambiguous_target")
        binding_strength = "weak"
    if recurring_without_target and not _strength_at_least(binding_strength, "usable"):
        offtarget_reasons.append("recurring_global_candidate_without_target_binding")
        binding_strength = "none"

    if _binding_strength_value(binding_strength) == 0:
        offtarget_reasons.append("candidate_pool_membership_only")
        offtarget_reasons.append("no_target_binding")

    # Score constants (same accepted-default status as the ladder above, same evidence basis):
    # per-tier base scores 0.0/0.9/2.4/4.0 give each binding_strength tier clear separation without
    # overlap once combined with the +/-0.2/0.1/0.45 adjustments below, and decisive-match/qualifier
    # bonuses are capped (min(2, ...)) so no single signal can push a weak/usable row past the next
    # tier's own base score by stacking alone.
    score = {"none": 0.0, "weak": 0.9, "usable": 2.4, "strong": 4.0}[binding_strength]
    score += 0.2 * min(2, decisive_text_matches)
    score += 0.1 * min(2, len(qualifier_hits) + len(parent_topic_hits))
    score -= 0.45 if broad_only_match else 0.0
    score = round(max(0.0, score), 6)

    return {
        "is_target_bound": _strength_at_least(binding_strength, str(thresholds["min_target_binding_for_positive_roles"])),
        "binding_strength": binding_strength,
        "binding_reasons": unique_preserve_order(binding_reasons),
        "offtarget_reasons": unique_preserve_order(offtarget_reasons),
        "exact_target_phrase_in_text": text_exact,
        "text_target_match_count": int(text_matches),
        "heading_target_match_count": int(heading_matches),
        "source_block_target_match_count": int(source_matches),
        "qualifier_token_hits": len(qualifier_hits),
        "parent_topic_token_hits": len(parent_topic_hits),
        "family_token_hits": len(family_hits),
        "score": score,
    }


def _definition_subject_alignment(candidate_row: Mapping[str, Any], profile: Mapping[str, Any]) -> Tuple[str, List[str]]:
    text = _as_text(candidate_row.get("text") or candidate_row.get("candidate_text"))
    if not text:
        return "missing", ["definition_subject_missing"]
    target_pattern = _target_phrase_pattern(profile.get("target_phrases") or [])
    if target_pattern is None:
        return "missing", ["definition_subject_missing"]
    text_norm = match_normalize(text)
    link_match = DEFINITION_LINK_RE.search(text_norm)
    if link_match is None:
        return "missing", ["definition_linker_absent"]
    subject_text = text_norm[: link_match.start()].strip(" ,;:-")
    subject_focus = re.split(r"[,:;]\s*", subject_text)[-1].strip(" ,;:-") or subject_text
    subject_tokens = _content_tokens(subject_text, min_len=2)
    subject_focus_tokens = _content_tokens(subject_focus, min_len=2)
    subject_matches, subject_ratio, _, decisive_matches = _best_target_overlap(
        subject_tokens,
        profile.get("phrase_token_sets") or [],
    )
    focus_matches, focus_ratio, _, focus_decisive_matches = _best_target_overlap(
        subject_focus_tokens,
        profile.get("phrase_token_sets") or [],
    )
    canonical_tokens = set(profile.get("canonical_tokens") or [])
    core_target_tokens = {token for token in canonical_tokens if token not in GENERIC_TARGET_SUFFIX_TOKENS}
    if not core_target_tokens:
        core_target_tokens = set(canonical_tokens)
    family_tokens = set(profile.get("family_tokens") or [])
    alias_family_tokens = {
        token
        for token_list in profile.get("alias_token_lists") or []
        for token in token_list
        if token not in canonical_tokens and token not in BROAD_HEAD_TOKENS
    }
    family_sensitive_target = bool(alias_family_tokens)
    full_family_hits = family_tokens & set(subject_tokens)
    focus_family_hits = family_tokens & set(subject_focus_tokens)
    alias_family_hits = alias_family_tokens & set(subject_tokens)
    focus_alias_family_hits = alias_family_tokens & set(subject_focus_tokens)
    core_subject_hits = core_target_tokens & set(subject_tokens)
    core_focus_hits = core_target_tokens & set(subject_focus_tokens)
    target_starts_subject = False
    target_starts_focus = False
    for phrase in profile.get("target_phrases") or []:
        escaped = re.escape(match_normalize(phrase))
        if re.search(rf"^(?:a|an|the)\s+{escaped}\b|^{escaped}\b", subject_text) is not None:
            target_starts_subject = True
        if re.search(rf"^(?:a|an|the)\s+{escaped}\b|^{escaped}\b", subject_focus) is not None:
            target_starts_focus = True
    if target_pattern.search(subject_focus) is not None and (
        target_starts_focus or not family_sensitive_target or alias_family_hits or focus_alias_family_hits
    ):
        return "aligned", ["definition_subject_target_named"]
    if target_pattern.search(subject_text) is not None and target_starts_subject:
        return "aligned", ["definition_subject_target_named"]
    if focus_matches >= 2 and focus_ratio >= 0.5 and (
        not family_sensitive_target or alias_family_hits or focus_alias_family_hits
    ):
        return "aligned", ["definition_subject_target_overlap"]
    if focus_decisive_matches >= 1 and focus_ratio >= 0.8 and (
        not family_sensitive_target or alias_family_hits or focus_alias_family_hits
    ):
        return "aligned", ["definition_subject_target_overlap"]
    if subject_matches >= 2 and subject_ratio >= 0.5 and full_family_hits and not family_sensitive_target:
        return "aligned", ["definition_subject_target_overlap"]
    if decisive_matches >= 1 and subject_ratio >= 0.8 and full_family_hits and not family_sensitive_target:
        return "aligned", ["definition_subject_target_overlap"]
    if core_focus_hits and (
        target_starts_focus
        or (
            len(subject_focus_tokens) <= max(3, len(core_target_tokens) + 1)
            and (focus_ratio >= 0.5 or focus_decisive_matches >= 1)
        )
    ):
        return "compatible", ["definition_subject_core_target_overlap"]
    if core_subject_hits and target_starts_subject and (subject_ratio >= 0.5 or decisive_matches >= 1):
        return "compatible", ["definition_subject_core_target_overlap"]
    for phrase in profile.get("target_phrases") or []:
        escaped = re.escape(match_normalize(phrase))
        if re.search(
            rf"\b(?:called|known as|termed|named|defined as|referred to as)\b[^\.]{{0,80}}\b{escaped}\b",
            text_norm,
        ) is not None:
            return "aligned", ["definition_target_named_in_complement"]
    for phrase in profile.get("target_phrases") or []:
        escaped = re.escape(match_normalize(phrase))
        for template in NEGATIVE_TARGET_RELATION_TEMPLATES:
            if re.search(template.format(target=escaped), text_norm) is not None:
                return "contrastive", ["definition_subject_negative_or_contrastive_target"]
    complement_text = text_norm[link_match.end() :].strip(" ,;:-")
    if target_pattern.search(complement_text) is not None and GENERIC_SUBJECT_RE.search(subject_text) is not None:
        return "aligned", ["definition_generic_subject_named_target"]
    target_match_in_text = target_pattern.search(text_norm)
    if target_match_in_text is not None:
        if (
            target_match_in_text.start() <= 40
            and ("," in subject_text or re.match(r"^(?:in|for|under|within|during|across)\b", subject_text) is not None)
        ):
            return "missing", ["definition_subject_preposed_target_context"]
        mismatch_reasons = ["definition_subject_mismatch"]
        # 2026-07-26 fix: tag whether the ONLY thing that matched is a single generic word/token
        # (plain-whitespace word count on the actual matched text, hyphens counted as part of
        # the word - "trade-off" is one word for collision purposes, same as "binary") versus a
        # genuine multi-word phrase. Confirmed real, dangerous homonym-collision risk: single-
        # word aliases match completely unrelated text purely by coincidence -
        # KC_CLF_UND_007 "Attribute/Variable Types" has alias "binary", which matched
        # "...binary classification..." (a different concept entirely, nothing to do with
        # attribute types); KC_FSEL_FW_004 "Filter vs. Wrapper Trade-off" has alias "trade-off",
        # which matched an unrelated neural-network hyperparameter sentence. A multi-word match
        # (the KC's own canonical name, or a distinctive multi-word alias phrase) does not share
        # this risk - downstream consumers can safely treat that case differently from a bare
        # single generic token match, without needing any hardcoded list of "risky" words.
        matched_phrase = target_match_in_text.group().strip()
        if len(matched_phrase.split()) <= 1:
            mismatch_reasons.append("definition_subject_mismatch_single_token_match")
        return "mismatch", mismatch_reasons
    return "missing", ["definition_subject_missing"]


def _definition_statement_style(candidate_row: Mapping[str, Any], *, lexical_target_binding: Mapping[str, Any]) -> Tuple[str, List[str]]:
    text = _as_text(candidate_row.get("text") or candidate_row.get("candidate_text"))
    structural_flags = _as_dict(candidate_row.get("structural_flags"))
    support_profile = _as_dict(candidate_row.get("support_profile"))
    reasons: List[str] = []
    if not text:
        return "none", ["text_missing"]
    lower = match_normalize(text)
    if DEFINITION_LINK_RE.search(lower):
        reasons.append("definition_linker_present")
    if str(support_profile.get("preferred_support_role") or "") == "definitional_anchor":
        reasons.append("support_profile_definitional_hint")
    if structural_flags.get("looks_prompt_like"):
        reasons.append("prompt_like_surface")
    if structural_flags.get("looks_caption_like"):
        reasons.append("caption_like_surface")
    if structural_flags.get("looks_fragmentary"):
        reasons.append("fragmentary_surface")
    if DEFINITION_LINK_RE.search(lower) is not None and not structural_flags.get("looks_prompt_like") and not structural_flags.get("looks_caption_like"):
        return "explicit", reasons
    if bool(lexical_target_binding.get("is_target_bound")) and _natural_language_like(text) and not structural_flags.get("looks_prompt_like"):
        return "implicit", reasons
    return "none", reasons


def _explicit_negative_target_relation(text: str, target_phrases: Sequence[str]) -> bool:
    text_norm = match_normalize(text)
    for phrase in target_phrases:
        escaped = re.escape(match_normalize(phrase))
        for template in NEGATIVE_TARGET_RELATION_TEMPLATES:
            if re.search(template.format(target=escaped), text_norm) is not None:
                return True
    return False


def _target_statement_signal(
    candidate_row: Mapping[str, Any],
    *,
    profile: Mapping[str, Any],
    lexical_target_binding: Mapping[str, Any],
    definition_framing: Mapping[str, Any],
) -> Dict[str, Any]:
    text = _as_text(candidate_row.get("text") or candidate_row.get("candidate_text"))
    text_norm = match_normalize(text)
    structural_flags = _as_dict(candidate_row.get("structural_flags"))
    target_phrases = [match_normalize(item) for item in profile.get("target_phrases") or [] if _as_text(item)]
    text_tokens = _content_tokens(text, min_len=2)
    early_tokens = text_tokens[:8]
    early_token_set = set(early_tokens)
    qualifier_tokens = set(profile.get("qualifier_tokens") or [])
    family_tokens = set(profile.get("family_tokens") or [])
    early_qualifier_hits = sorted(early_token_set & qualifier_tokens)
    early_family_hits = sorted(early_token_set & family_tokens)
    text_target_match_count = int(lexical_target_binding.get("text_target_match_count") or 0)
    competitor_hits = _as_int(_as_dict(candidate_row.get("alignment_breakdown")).get("competitor_token_hits"), default=0) or 0
    subject_alignment = str(definition_framing.get("subject_alignment") or "")
    reasons: List[str] = []
    direct = False

    if subject_alignment in {"aligned", "compatible"}:
        direct = True
        reasons.append("definition_subject_aligned" if subject_alignment == "aligned" else "definition_subject_compatible")

    if not structural_flags.get("looks_fragmentary") and not structural_flags.get("looks_caption_like") and not structural_flags.get("looks_prompt_like"):
        if not direct:
            for phrase in target_phrases:
                idx = text_norm.find(phrase)
                if idx != -1 and idx <= 40 and subject_alignment == "missing":
                    direct = True
                    reasons.append("target_phrase_near_sentence_start")
                    break
        if not direct:
            for phrase in target_phrases:
                escaped = re.escape(phrase)
                if re.search(
                    rf"\b(?:called|known as|termed|named|defined as|referred to as)\b[^\.]{{0,80}}\b{escaped}\b",
                    text_norm,
                ) is not None:
                    direct = True
                    reasons.append("target_named_in_definition_complement")
                    break
        if (
            not direct
            and subject_alignment == "missing"
            and competitor_hits == 0
            and text_target_match_count >= 2
            and (early_qualifier_hits or early_family_hits)
        ):
            direct = True
            reasons.append("early_target_and_family_token_alignment")

    return {
        "is_direct_target_statement": direct,
        "reasons": unique_preserve_order(reasons),
    }


def _definition_framing_score(
    candidate_row: Mapping[str, Any],
    *,
    lexical_target_binding: Mapping[str, Any],
    profile: Mapping[str, Any],
) -> Dict[str, Any]:
    subject_alignment, subject_reasons = _definition_subject_alignment(candidate_row, profile)
    definition_style, style_reasons = _definition_statement_style(candidate_row, lexical_target_binding=lexical_target_binding)
    support_profile = _as_dict(candidate_row.get("support_profile"))
    structural_flags = _as_dict(candidate_row.get("structural_flags"))
    score = 0.0
    if subject_alignment == "aligned":
        score += 2.5
    elif subject_alignment == "compatible":
        score += 1.7
    elif subject_alignment == "contrastive":
        score -= 2.5
    elif subject_alignment == "mismatch":
        score -= 1.75
    if definition_style == "explicit":
        score += 2.0
    elif definition_style == "implicit":
        score += 0.8
    if str(support_profile.get("preferred_support_role") or "") == "definitional_anchor":
        score += 0.6
    if structural_flags.get("looks_prompt_like"):
        score -= 1.5
    if structural_flags.get("looks_caption_like"):
        score -= 1.25
    if structural_flags.get("looks_fragmentary"):
        score -= 0.9
    return {
        "score": round(score, 6),
        "subject_alignment": subject_alignment,
        "definition_style": definition_style,
        "reasons": unique_preserve_order([*subject_reasons, *style_reasons]),
    }


def _formula_signal(candidate_row: Mapping[str, Any], *, lexical_target_binding: Mapping[str, Any]) -> Dict[str, Any]:
    actual_formula = _actual_formula_notation(candidate_row)
    mathish = _mathish_prose(candidate_row, actual_formula=actual_formula)
    support_profile = _as_dict(candidate_row.get("support_profile"))
    reasons: List[str] = []
    score = 0.0
    if actual_formula:
        reasons.append("actual_formula_notation")
        score += 2.5
    if mathish and not actual_formula:
        reasons.append("mathish_prose_without_notation")
        score -= 1.5
    if _as_float(support_profile.get("formula_support_score")) > 0:
        reasons.append("formula_support_profile_hint")
        score += 0.25 if actual_formula else -0.1
    if actual_formula and bool(support_profile.get("structural_anchor_support")):
        reasons.append("structural_anchor_formula_support")
        score += 0.95
    if actual_formula and bool(support_profile.get("shape_hint_formula_or_metric")):
        reasons.append("shape_hint_formula_metric_support")
        score += 0.75
    if not bool(lexical_target_binding.get("is_target_bound", False)) and actual_formula:
        reasons.append("formula_without_target_binding")
        score -= 0.75
    return {
        "score": round(score, 6),
        "is_actual_formula_notation": actual_formula,
        "looks_mathish_prose": bool(mathish and not actual_formula),
        "reasons": unique_preserve_order(reasons),
    }


def _procedure_or_example_signal(candidate_row: Mapping[str, Any]) -> Dict[str, Any]:
    text = _as_text(candidate_row.get("text") or candidate_row.get("candidate_text"))
    lower = match_normalize(text)
    structural_flags = _as_dict(candidate_row.get("structural_flags"))
    procedure_score = 0.0
    example_score = 0.0
    prompt_score = 0.0
    reasons: List[str] = []
    if NUMBERED_STEP_RE.search(text) or IF_THEN_RE.search(lower) or PROCEDURE_RE.search(lower):
        procedure_score += 1.8
        reasons.append("procedure_cue_present")
    if EXAMPLE_RE.search(lower):
        example_score += 1.4
        reasons.append("example_cue_present")
    if structural_flags.get("looks_prompt_like") or PROMPT_RE.search(lower):
        prompt_score += 2.0
        reasons.append("prompt_cue_present")
    return {
        "procedure_score": round(procedure_score, 6),
        "example_score": round(example_score, 6),
        "prompt_score": round(prompt_score, 6),
        "reasons": unique_preserve_order(reasons),
    }


def _meta_guidance_signal(candidate_row: Mapping[str, Any]) -> Dict[str, Any]:
    text = _as_text(candidate_row.get("text") or candidate_row.get("candidate_text"))
    lower = match_normalize(text)
    structural_flags = _as_dict(candidate_row.get("structural_flags"))
    score = 0.0
    reasons: List[str] = []
    has_mistake_noun = bool(META_GUIDANCE_MISTAKE_NOUN_RE.search(lower))
    has_warning_modal = bool(META_GUIDANCE_WARNING_MODAL_RE.search(lower))
    if has_mistake_noun:
        score += 2.0
        reasons.append("meta_guidance_mistake_noun_present")
        if has_warning_modal:
            reasons.append("meta_guidance_warning_modal_co_present")
    if structural_flags.get("looks_prompt_like") and any(
        token in lower for token in ("avoid", "mistake", "pitfall", "warning", "caution")
    ):
        score += 0.75
        reasons.append("prompt_like_meta_guidance_surface")
    return {
        "score": round(score, 6),
        "is_meta_guidance": bool(score > 0.0),
        "reasons": unique_preserve_order(reasons),
    }


def _reference_like_signal(candidate_row: Mapping[str, Any]) -> Dict[str, Any]:
    text = _as_text(candidate_row.get("text") or candidate_row.get("candidate_text"))
    lower = match_normalize(text)
    heading = match_normalize(_as_text(candidate_row.get("patch_heading") or candidate_row.get("source_heading_text")))
    reasons: List[str] = []
    reference_score = 0.0
    bibliography_score = 0.0
    if REFERENCE_LIKE_RE.search(lower):
        reference_score += 1.4
        reasons.append("reference_like_surface")
    # 2026-07-27 fix: patch_heading alone is not trustworthy - require citation-entry structure
    # somewhere in the candidate's own text OR its surrounding source_block_text before trusting
    # a "Bibliography"-labeled heading. See CITATION_ENTRY_RE's own comment for the confirmed
    # real incident this closes. Checking source_block_text too (not just the narrow candidate
    # sentence) was added after a second real incident found during A/B verification: a lone
    # paper-title fragment ("Learning with many irrelevant features.") carries no citation
    # markers itself, but its own source_block_text is an unambiguous 20+ entry numbered
    # reference list - the corroborating structure exists, just one field over.
    source_block_text = _as_text(candidate_row.get("source_block_text"))
    if BIBLIOGRAPHY_HEADING_RE.search(heading) and (
        CITATION_ENTRY_RE.search(text) or CITATION_ENTRY_RE.search(source_block_text)
    ):
        bibliography_score += 2.0
        reasons.append("bibliography_heading_corroborated_by_text_structure")
    if BIBLIOGRAPHY_HEADING_RE.search(lower):
        bibliography_score += 1.2
        reasons.append("bibliography_surface")
    return {
        "reference_like_penalty": round(reference_score, 6),
        "bibliography_penalty": round(bibliography_score, 6),
        "is_reference_like": bool(reference_score > 0.0),
        "is_bibliography_like": bool(bibliography_score > 0.0),
        "reasons": unique_preserve_order(reasons),
    }


def _fragment_or_caption_signal(candidate_row: Mapping[str, Any]) -> Dict[str, Any]:
    text = _as_text(candidate_row.get("text") or candidate_row.get("candidate_text"))
    lower = match_normalize(text)
    structural_flags = _as_dict(candidate_row.get("structural_flags"))
    fragment_score = 0.0
    caption_score = 0.0
    reasons: List[str] = []
    if structural_flags.get("looks_fragmentary") or len(text) < 40 or FRAGMENT_PREFIX_RE.search(lower) or TRAILING_FRAGMENT_RE.search(lower):
        fragment_score += 1.5
        reasons.append("fragmentary_surface")
    if structural_flags.get("looks_caption_like") or CAPTION_RE.search(lower):
        caption_score += 1.5
        reasons.append("caption_like_surface")
    heading_like = bool((_as_dict(candidate_row.get("alignment_breakdown")).get("flags") or {}).get("is_heading_like", False))
    if heading_like:
        reasons.append("heading_like_surface")
    return {
        "fragment_score": round(fragment_score, 6),
        "caption_score": round(caption_score, 6),
        "heading_like": heading_like,
        "reasons": unique_preserve_order(reasons),
    }


def _scope_condition_score(candidate_row: Mapping[str, Any]) -> Tuple[float, List[str]]:
    text = _as_text(candidate_row.get("text") or candidate_row.get("candidate_text"))
    lower = match_normalize(text)
    reasons: List[str] = []
    score = 0.0
    if SCOPE_RE.search(lower):
        score += 1.4
        reasons.append("scope_cue_present")
    return round(score, 6), reasons


def _usage_for_candidate(candidate_row: Mapping[str, Any], global_candidate_usage: Mapping[str, Any] | None) -> Dict[str, int]:
    """*_foreign_topic_kc_count fields (2026-07-26 fix) are the sibling-aware companions to the
    original raw *_kc_count fields: the count of recurring KCs whose own parent_topic_id
    differs from THIS candidate's target KC's parent_topic_id, rather than every recurring KC
    regardless of topic. Confirmed real over-triggering (KC_CLU_EVAL_002 "SSE (Cluster
    Quality)": two genuinely on-topic, specific SSE sentences - "of the squared error (SSE),
    which is also known as scatter", "total SSE is the total cohesion... Equation 7.3" - were
    both flagged recurring_global_candidate purely because SSE-related text is a shared,
    legitimate candidate across several SIBLING clustering-evaluation KCs under the same parent
    topic, at raw_text_hash_kc_count/normalized_text_kc_count >= the threshold-of-3 default -
    the original check could not distinguish that from genuinely generic/boilerplate text
    recurring across topically UNRELATED KCs (also confirmed real and worth keeping flagged:
    KC_CLU_DBS_005's flagged sentence was actually about the different, related "density-
    reachable" concept, not "directly density-reachable" specifically). *_foreign_topic_kc_count
    is always <= the corresponding raw *_kc_count (a strict subset), so using it instead can
    only relax over-triggering, never newly trigger a case the raw count wouldn't already have
    caught - a one-directional, safe-by-construction change. Falls back to the raw count
    (unchanged prior behavior) whenever this candidate's own parent_topic_id is unknown, since
    there is nothing to safely distinguish "foreign" from "sibling" without it.
    """
    if not global_candidate_usage:
        return {
            "raw_text_hash_kc_count": 1,
            "normalized_text_kc_count": 1,
            "patch_kc_count": 1 if _as_text(candidate_row.get("patch_id")) else 0,
            "raw_text_hash_foreign_topic_kc_count": 1,
            "normalized_text_foreign_topic_kc_count": 1,
            "patch_foreign_topic_kc_count": 1 if _as_text(candidate_row.get("patch_id")) else 0,
        }
    raw_hash = _as_text(candidate_row.get("raw_text_hash"))
    norm_text = match_normalize(_as_text(candidate_row.get("text") or candidate_row.get("candidate_text")))
    patch_id = _as_text(candidate_row.get("patch_id"))
    raw_map = global_candidate_usage.get("raw_text_hash_to_kcs") or {}
    text_map = global_candidate_usage.get("normalized_text_to_kcs") or {}
    patch_map = global_candidate_usage.get("patch_id_to_kcs") or {}
    kc_to_parent = global_candidate_usage.get("kc_id_to_parent_topic_id") or {}
    own_kc_id = _as_text(candidate_row.get("kc_id"))
    own_parent = _as_text(candidate_row.get("parent_topic_id")) or kc_to_parent.get(own_kc_id)

    def _foreign_topic_count(kc_ids: list[str]) -> int:
        if not own_parent:
            return len(kc_ids)
        return sum(1 for kid in kc_ids if kc_to_parent.get(kid) and kc_to_parent.get(kid) != own_parent)

    raw_kc_ids = raw_map.get(raw_hash, []) if raw_hash else []
    text_kc_ids = text_map.get(norm_text, []) if norm_text else []
    patch_kc_ids = patch_map.get(patch_id, []) if patch_id else []
    return {
        "raw_text_hash_kc_count": len(raw_kc_ids),
        "normalized_text_kc_count": len(text_kc_ids),
        "patch_kc_count": len(patch_kc_ids),
        "raw_text_hash_foreign_topic_kc_count": _foreign_topic_count(raw_kc_ids),
        "normalized_text_foreign_topic_kc_count": _foreign_topic_count(text_kc_ids),
        "patch_foreign_topic_kc_count": _foreign_topic_count(patch_kc_ids),
    }


def _contamination_signals(
    candidate_row: Mapping[str, Any],
    *,
    lexical_target_binding: Mapping[str, Any],
    parent_alignment: Mapping[str, Any],
    global_candidate_usage: Mapping[str, Any] | None,
    cfg: Mapping[str, Any],
) -> Dict[str, Any]:
    # Contamination score ladder (Phase 3.5 rank #3 / audit codebase-audit-20260805 item 4):
    # broad_topic_only/doc_mismatch/source_kc_mismatch/competitor/contamination_exclusion_hint
    # weights below are literal constants, not config-overridable (unlike the six role-score
    # thresholds - see default_scoring_cfg's min_definition_score et al., empirically calibrated
    # 2026-07-27, commit ab1b7d2). No dedicated per-parameter calibration study exists for this
    # specific family; the repo's git history (13 total commits) has no earlier record of one
    # either.
    #
    # Investigated as part of this audit and left unchanged, documented as an accepted, reasoned
    # default per the audit's own explicit fallback (real per-constant calibration wasn't
    # feasible to redo for every literal in this session): each reason fires independently and
    # additively (a candidate can be flagged broad+mismatch+competitor at once, correctly
    # compounding suspicion rather than the strongest single flag winning), and this exact,
    # unmodified ladder - combined with the sibling-aware recurring-candidate check just below,
    # already fixed once this session (2026-07-26) - is what fed max_contamination_score_for_
    # positive_roles (2.5) and manual_review_contamination_threshold (3.2) across the full
    # 5-config, step_05x-through-step_06_8 corpus regeneration this session
    # (research_notes/step5p_5x_audits/FINAL_window_capture_fix_and_regeneration_20260805.md):
    # 0 ordered_evidence_admission_violation_count / 0 ordered_sibling_violation_count / 0 new
    # regressions across all 5 configs. Real, whole-pipeline validation evidence, not a silently
    # unexamined magic-number set.
    alignment_breakdown = _as_dict(candidate_row.get("alignment_breakdown"))
    support_profile = _as_dict(candidate_row.get("support_profile"))
    reasons: List[str] = []
    score = 0.0
    broad_topic_only = bool(
        support_profile.get("generic_context_only")
        or "broad_phrase_overlap_only" in _as_str_list(lexical_target_binding.get("offtarget_reasons"))
        or "qualifier_or_parent_topic_missing" in _as_str_list(lexical_target_binding.get("offtarget_reasons"))
    )
    if broad_topic_only:
        score += 1.6
        reasons.append("broad_topic_only")
    doc_mismatch = bool(alignment_breakdown.get("doc_mismatch", False))
    if doc_mismatch:
        score += 1.3
        reasons.append("doc_mismatch")
    source_kc_mismatch = bool(
        _as_text(candidate_row.get("source_kc_id"))
        and _as_text(candidate_row.get("source_kc_id")) != _as_text(candidate_row.get("kc_id"))
    )
    if source_kc_mismatch and not _strength_at_least(str(lexical_target_binding.get("binding_strength") or "none"), "usable"):
        score += 1.5
        reasons.append("source_kc_mismatch_without_target_cue")
    competitor_hits = _as_int(alignment_breakdown.get("competitor_token_hits"), default=0) or 0
    if competitor_hits:
        score += min(1.5, 0.45 * competitor_hits)
        reasons.append("competitor_token_hits")
    if bool(support_profile.get("contamination_exclusion_hint", False)) and (
        broad_topic_only or source_kc_mismatch or competitor_hits >= 2
    ):
        score += 0.45
        reasons.append("contamination_exclusion_hint")
    usage = _usage_for_candidate(candidate_row, global_candidate_usage)
    # Sibling-aware (2026-07-26 fix) - see _usage_for_candidate's own docstring.
    if (
        usage["raw_text_hash_foreign_topic_kc_count"] >= int(default_scoring_cfg(cfg)["global_recurring_text_kc_threshold"])
        and not _strength_at_least(str(lexical_target_binding.get("binding_strength") or "none"), "strong")
    ):
        score += 1.2
        reasons.append("recurring_global_candidate_without_target_binding")
    if str(parent_alignment.get("alignment_strength") or "none") == "conflicting":
        score += 1.0
        reasons.append("parent_topic_alignment_conflicting")
    return {
        "score": round(score, 6),
        "broad_topic_only": broad_topic_only,
        "doc_mismatch": doc_mismatch,
        "source_kc_mismatch": source_kc_mismatch,
        "competitor_token_hits": competitor_hits,
        "reasons": unique_preserve_order(reasons),
    }


def _sibling_or_competitor_signals(
    candidate_row: Mapping[str, Any],
    *,
    profile: Mapping[str, Any],
    lexical_target_binding: Mapping[str, Any],
    definition_framing: Mapping[str, Any],
    contamination: Mapping[str, Any],
    force_dominant: bool = False,
) -> Dict[str, Any]:
    text = _as_text(candidate_row.get("text") or candidate_row.get("candidate_text"))
    alignment_breakdown = _as_dict(candidate_row.get("alignment_breakdown"))
    support_profile = _as_dict(candidate_row.get("support_profile"))
    competitor_hits = _as_int(alignment_breakdown.get("competitor_token_hits"), default=0) or 0
    subject_alignment = str(definition_framing.get("subject_alignment") or "")
    contrastive_target_mention = bool(
        subject_alignment == "contrastive"
        or (subject_alignment not in {"aligned", "compatible"} and _explicit_negative_target_relation(text, profile.get("target_phrases") or []))
    )
    strong_target_definition = bool(subject_alignment in {"aligned", "compatible"})
    genuine_sibling_signal = bool(
        (competitor_hits >= 1 and not strong_target_definition)
        or str(support_profile.get("preferred_support_role") or "") == "contamination_or_sibling_exclusion"
        or contrastive_target_mention
        or (
            _as_text(candidate_row.get("source_kc_id"))
            and _as_text(candidate_row.get("source_kc_id")) != _as_text(candidate_row.get("kc_id"))
        )
    )
    # Sibling/competitor penalty family (Phase 3.5 rank #4 / audit codebase-audit-20260805 item 5):
    # the +1.2/+1.4/+0.6/-0.7 weights and the competitor cap (min(2.0, 0.7*competitor_hits), up to
    # +2.0) below are literal constants, not config-overridable. No dedicated per-parameter
    # calibration study exists for this specific score family - but unlike several of this
    # session's other accepted-default items, the surrounding LOGIC in this exact function has
    # already had a real, hand-investigated fix pass (the 2026-07-28 cross-instance
    # reconciliation fix immediately below, confirmed against the real KC_FSEL_GEN_002/SBG
    # incident), so this isn't an unexamined function - just a family of weights within it that
    # were not themselves the subject of that fix.
    #
    # Investigated as part of this audit and left unchanged, documented as an accepted, reasoned
    # default per the audit's own explicit fallback: this exact, unmodified family fed the
    # sibling_contrast role score across the full 5-config corpus regeneration this session
    # (research_notes/step5p_5x_audits/FINAL_window_capture_fix_and_regeneration_20260805.md),
    # which showed 0 ordered_sibling_violation_count and 0 new regressions across all 5 configs.
    score = 0.0
    reasons: List[str] = []
    # 2026-07-28 fix: cross-instance reconciliation. The same raw sentence can enter
    # candidate_bank as multiple separate rows under the same kc_id via different retrieval
    # routes/context windows - confirmed real (KC_FSEL_GEN_002/SBG: 6/7 instances of an
    # SFG-owned "stopping criteria" sentence correctly computed genuine_sibling_signal=True
    # and got rejected, but a 7th instance of the byte-identical text, retrieved via a route
    # that didn't carry the same surrounding-context signal, scored genuine_sibling_signal=
    # False and reached ordered_evidence). force_dominant is set by score_candidate_rows'
    # third pass when ANY other row sharing this (kc_id, raw_text_hash) pair already computed
    # genuine_sibling_signal=True - every instance of the identical text should inherit the
    # block, not just the ones whose specific retrieval context happened to compute it.
    if force_dominant and not genuine_sibling_signal:
        genuine_sibling_signal = True
        reasons.append("propagated_from_identical_text_instance")
    if genuine_sibling_signal:
        reasons.append("genuine_sibling_or_competitor_signal")
        score += 1.2
    if competitor_hits:
        reasons.append("competitor_token_hits")
        score += min(2.0, 0.7 * competitor_hits)
    if contrastive_target_mention:
        reasons.append("contrastive_target_mention")
        score += 1.4
    if contamination.get("source_kc_mismatch"):
        reasons.append("source_kc_mismatch")
        score += 0.6
    if _strength_at_least(str(lexical_target_binding.get("binding_strength") or "none"), "strong") and str(definition_framing.get("subject_alignment") or "") in {"aligned", "compatible"}:
        score -= 0.7
    return {
        "score": round(max(0.0, score), 6),
        "genuine_sibling_signal": genuine_sibling_signal,
        "contrastive_target_mention": bool(contrastive_target_mention),
        "reasons": unique_preserve_order(reasons),
    }


def _same_region_bonus(
    candidate_row: Mapping[str, Any],
    *,
    stronger_anchor_index: Mapping[str, Any] | None,
) -> Tuple[float, List[str]]:
    if not stronger_anchor_index:
        return 0.0, []
    kc_id = _as_text(candidate_row.get("kc_id"))
    anchors = _as_dict(stronger_anchor_index.get(kc_id))
    if not anchors:
        return 0.0, []
    reasons: List[str] = []
    bonus = 0.0
    patch_id = _as_text(candidate_row.get("patch_id"))
    block_id = _as_text(candidate_row.get("block_id"))
    doc_id = _as_text(candidate_row.get("doc_id"))
    reveal_group_id = _as_text(candidate_row.get("reveal_group_id"))
    page_index = _as_int(candidate_row.get("page_index"))
    if patch_id and patch_id in set(anchors.get("patch_ids") or []):
        bonus += 1.0
        reasons.append("same_patch_as_stronger_anchor")
    if block_id and block_id in set(anchors.get("block_ids") or []):
        bonus += 0.8
        reasons.append("same_block_as_stronger_anchor")
    if reveal_group_id and reveal_group_id in set(anchors.get("reveal_group_ids") or []):
        bonus += 0.6
        reasons.append("same_reveal_group_as_stronger_anchor")
    doc_page_key = f"{doc_id}::{page_index}" if doc_id and page_index is not None else ""
    if doc_page_key and doc_page_key in set(anchors.get("doc_page_keys") or []):
        bonus += 0.4
        reasons.append("same_page_as_stronger_anchor")
    return round(bonus, 6), unique_preserve_order(reasons)


def _risk_flags(
    *,
    lexical_target_binding: Mapping[str, Any],
    parent_alignment: Mapping[str, Any],
    definition_framing: Mapping[str, Any],
    formula_signal: Mapping[str, Any],
    procedure_signal: Mapping[str, Any],
    meta_guidance: Mapping[str, Any],
    reference_signal: Mapping[str, Any],
    fragment_signal: Mapping[str, Any],
    contamination: Mapping[str, Any],
    sibling_signal: Mapping[str, Any],
    same_region_reasons: Sequence[str],
    global_candidate_usage: Mapping[str, Any] | None,
    candidate_row: Mapping[str, Any],
    cfg: Mapping[str, Any],
) -> List[str]:
    flags: List[str] = []
    binding_strength = str(lexical_target_binding.get("binding_strength") or "none")
    if binding_strength == "none":
        flags.append("no_target_binding")
    if "candidate_pool_membership_only" in _as_str_list(lexical_target_binding.get("offtarget_reasons")):
        flags.append("candidate_pool_membership_only")
    if "qualifier_or_parent_topic_missing" in _as_str_list(lexical_target_binding.get("offtarget_reasons")):
        flags.append("qualifier_or_parent_topic_missing")
    if "parent_topic_alignment_missing_for_ambiguous_target" in _as_str_list(lexical_target_binding.get("offtarget_reasons")):
        flags.append("ambiguous_target_without_parent_alignment")
    if str(definition_framing.get("subject_alignment") or "") in {"contrastive", "mismatch"}:
        flags.append("definition_subject_mismatch")
        # 2026-07-26 fix: surface the single-token-match granularity all the way to the row's
        # own risk_flags, not just definition_framing's internal reasons - see
        # _definition_subject_alignment's own docstring/comment for the confirmed real
        # homonym-collision cases this distinguishes.
        if "definition_subject_mismatch_single_token_match" in _as_str_list(definition_framing.get("reasons")):
            flags.append("definition_subject_mismatch_single_token_match")
    if bool(formula_signal.get("looks_mathish_prose", False)):
        flags.append("fake_formula_prose")
    if not bool(lexical_target_binding.get("is_target_bound", False)) and bool(formula_signal.get("is_actual_formula_notation", False)):
        flags.append("formula_without_target_binding")
    if _as_float(procedure_signal.get("prompt_score")) > 0:
        flags.append("prompt_like")
    if _as_float(procedure_signal.get("procedure_score")) > 0:
        flags.append("procedure_like")
    if _as_float(procedure_signal.get("example_score")) > 0:
        flags.append("example_like")
    if bool(meta_guidance.get("is_meta_guidance", False)):
        flags.append("meta_guidance")
    if bool(reference_signal.get("is_reference_like", False)):
        flags.append("reference_like")
    if bool(reference_signal.get("is_bibliography_like", False)):
        flags.append("bibliography_like")
    route_reason = str(profile_route_eval.get("positive_support_block_reason") or "") if "profile_route_eval" in locals() else ""
    if route_reason:
        flags.append(route_reason)
    if _as_float(fragment_signal.get("fragment_score")) > 0:
        flags.append("fragmentary")
    if _as_float(fragment_signal.get("caption_score")) > 0:
        flags.append("caption_like")
    if bool(fragment_signal.get("heading_like", False)):
        flags.append("heading_like")
    if bool(contamination.get("broad_topic_only", False)):
        flags.append("broad_topic_only")
    if bool(contamination.get("doc_mismatch", False)):
        flags.append("doc_mismatch")
    if bool(contamination.get("source_kc_mismatch", False)):
        flags.append("source_kc_mismatch")
    if bool(sibling_signal.get("genuine_sibling_signal", False)):
        flags.append("sibling_competitor_dominant")
    usage = _usage_for_candidate(candidate_row, global_candidate_usage)
    # Sibling-aware (2026-07-26 fix) - see _usage_for_candidate's own docstring. This is the
    # site that produces the "recurring_global_candidate" flag surfaced downstream.
    if (
        usage["raw_text_hash_foreign_topic_kc_count"] >= int(default_scoring_cfg(cfg)["global_recurring_text_kc_threshold"])
        or usage["patch_foreign_topic_kc_count"] >= int(default_scoring_cfg(cfg)["global_recurring_patch_kc_threshold"])
    ):
        flags.append("recurring_global_candidate")
    if same_region_reasons:
        flags.append("needs_stronger_anchor_context")
    if str(parent_alignment.get("alignment_strength") or "none") == "conflicting":
        flags.append("parent_topic_alignment_conflicting")
    return unique_preserve_order(flags)


def _candidate_quality_and_routing(
    *,
    lexical_target_binding: Mapping[str, Any],
    definition_framing: Mapping[str, Any],
    direct_target_statement: Mapping[str, Any],
    contamination: Mapping[str, Any],
    sibling_signal: Mapping[str, Any],
    role_scores: Mapping[str, float],
    role_eligibility: Mapping[str, bool],
    same_region_bonus: float,
    cfg: Mapping[str, Any],
    hybrid_retrieval: Optional[Mapping[str, Any]] = None,
) -> Tuple[Dict[str, Any], str, Dict[str, List[str]]]:
    thresholds = default_scoring_cfg(cfg)
    positive_support_eligible = bool(role_eligibility.get("positive_support_eligible", False))
    auxiliary_support_eligible = bool(role_eligibility.get("auxiliary_support_eligible", False))
    guardrail_support_eligible = bool(role_eligibility.get("guardrail_support_eligible", False))
    direct_target = bool(direct_target_statement.get("is_direct_target_statement", False))
    guardrail_dominates = bool(
        guardrail_support_eligible
        and not (
            str(definition_framing.get("subject_alignment") or "") in {"aligned", "compatible"}
            or (positive_support_eligible and direct_target)
        )
    )
    guardrail_only = bool(guardrail_support_eligible and not positive_support_eligible and not auxiliary_support_eligible)
    same_region_auxiliary_only = bool(
        auxiliary_support_eligible
        and not positive_support_eligible
    )
    top_positive_score = max(float(role_scores.get(role, 0.0)) for role in STANDALONE_POSITIVE_ROLES)
    top_auxiliary_score = max(float(role_scores.get(role, 0.0)) for role in AUXILIARY_ROLES)
    overall_score = max(top_positive_score, top_auxiliary_score, float(role_scores.get("sibling_contrast", 0.0)))
    overall_score -= 0.35 * float(contamination.get("score", 0.0))
    if guardrail_only:
        overall_score -= 0.4
    overall_score = round(overall_score, 6)
    # A hybrid-retrieved candidate was ranked by a cross-encoder relevance model, which judges
    # aboutness directly. That is a stronger and more honest binding claim than "the sentence
    # restates the unit's name" - the lexical test that formulas and procedure steps structurally
    # cannot pass. Gated on a calibrated probability so weakly-ranked hits do not qualify.
    hybrid = _as_dict(hybrid_retrieval)
    cross_encoder_bound = bool(
        float(hybrid.get("cross_encoder_prob") or 0.0) >= HYBRID_BINDING_MIN_PROB
    )
    target_bound_positive = bool(
        positive_support_eligible
        and (
            lexical_target_binding.get("is_target_bound", False)
            or direct_target
            or role_eligibility.get("strict_fallback_definition_kernel_override", False)
            or role_eligibility.get("structural_anchor_formula_support", False)
            or cross_encoder_bound
        )
    )
    quality = {
        "overall_score": overall_score,
        "target_bound_positive_support": target_bound_positive,
        "target_bound_positive_support_basis": {
            "lexical_target_bound": bool(lexical_target_binding.get("is_target_bound", False)),
            "direct_target_statement": bool(direct_target),
            "strict_fallback_definition_kernel_override": bool(role_eligibility.get("strict_fallback_definition_kernel_override", False)),
            "structural_anchor_formula_support": bool(role_eligibility.get("structural_anchor_formula_support", False)),
            "cross_encoder_relevance": cross_encoder_bound,
        },
        "auxiliary_support": auxiliary_support_eligible,
        "same_region_auxiliary_only": same_region_auxiliary_only,
        "guardrail_only": guardrail_only,
    }

    debug_positive: List[str] = []
    debug_negative: List[str] = []
    debug_gates: List[str] = []
    if quality["target_bound_positive_support"]:
        debug_positive.append("target_bound_positive_role_eligible")
    if same_region_auxiliary_only:
        debug_positive.append("same_region_auxiliary_candidate")
    if guardrail_only:
        debug_positive.append("guardrail_only_candidate")
    if guardrail_dominates:
        debug_negative.append("guardrail_signal_dominates_standalone_positive")
        debug_gates.append("standalone_positive_blocked_by_guardrail")
    if float(contamination.get("score", 0.0)) > float(thresholds["max_contamination_score_for_positive_roles"]):
        debug_negative.append("contamination_above_positive_threshold")
        debug_gates.append("positive_roles_blocked_by_contamination")
    if str(definition_framing.get("subject_alignment") or "") in {"contrastive", "mismatch"}:
        debug_negative.append("definition_subject_not_aligned")
    if not bool(lexical_target_binding.get("is_target_bound", False)):
        debug_negative.append("target_binding_below_positive_threshold")

    routing = "drop_from_positive_roles"
    if (
        positive_support_eligible
        and not guardrail_dominates
        and float(contamination.get("score", 0.0)) <= float(thresholds["manual_review_contamination_threshold"])
    ):
        routing = "positive_role_candidate"
    elif auxiliary_support_eligible and not positive_support_eligible:
        routing = "auxiliary_only_candidate"
    elif guardrail_only:
        routing = "guardrail_only_candidate"
    elif positive_support_eligible and guardrail_dominates:
        routing = "manual_review_candidate"
    elif bool(lexical_target_binding.get("is_target_bound", False)) and (
        float(contamination.get("score", 0.0)) >= float(thresholds["manual_review_contamination_threshold"])
        or str(definition_framing.get("subject_alignment") or "") in {"contrastive", "mismatch"}
    ):
        routing = "manual_review_candidate"
    return quality, routing, {
        "positive_signals": unique_preserve_order(debug_positive),
        "negative_signals": unique_preserve_order(debug_negative),
        "gates_triggered": unique_preserve_order(debug_gates),
    }


def default_scoring_cfg(cfg: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    source = dict(cfg or {})
    thresholds = dict(source.get("thresholds") or {})
    return {
        "min_target_binding_for_positive_roles": str(
            thresholds.get("min_target_binding_for_positive_roles", "usable")
        ),
        # min_definition_score/min_explanatory_score/min_scope_score/min_formula_score/
        # min_context_completion_score/min_example_or_procedure_score: empirically calibrated
        # 2026-07-27 (commit ab1b7d2) from 360 hand-judged stratified examples (60/role across 10
        # score deciles), re-verified live against the real role_eligibility field on
        # scored_candidates.jsonl before deploy. min_formula_score and min_context_completion_score
        # were deliberately left at their pre-calibration values (formula's best empirical cut
        # relied on too thin a sample, n=6, to trust; context_completion was already sitting at its
        # empirically-optimal point) - not an oversight. These six fallbacks previously still held
        # the disproven pre-calibration numbers (3.9/3.1/3.0/.../3.0) even though the real
        # production config (steps/step_05_x_evidence_stage_v3/resources/
        # step5x_v3_scored_candidates.default.yaml) has carried the calibrated values since that
        # commit - harmless while every real run config supplies these keys, but a silent trap for
        # any future config that omits one. Now kept in sync with the calibrated config values.
        "min_definition_score": float(thresholds.get("min_definition_score", 6.0)),
        "min_explanatory_score": float(thresholds.get("min_explanatory_score", 6.0)),
        "min_scope_score": float(thresholds.get("min_scope_score", 4.3)),
        "min_formula_score": float(thresholds.get("min_formula_score", 3.6)),
        "min_context_completion_score": float(thresholds.get("min_context_completion_score", 3.2)),
        "min_example_or_procedure_score": float(thresholds.get("min_example_or_procedure_score", 4.5)),
        # min_sibling_contrast_score: NOT part of the 2026-07-27 calibration round above (that
        # round covered exactly six roles - definition/explanatory/scope/formula/
        # context_completion/example_or_procedure, 360 = 60x6 hand-judged examples - sibling
        # contrast was not one of them). Still an open, uncalibrated single threshold; deliberately
        # not force-calibrated here since it is one value, not a family, and no confirmed bug is
        # tied to it the way the other six had real evidence behind their recalibration.
        "min_sibling_contrast_score": float(thresholds.get("min_sibling_contrast_score", 2.8)),
        "max_contamination_score_for_positive_roles": float(
            thresholds.get("max_contamination_score_for_positive_roles", 2.5)
        ),
        "manual_review_contamination_threshold": float(
            thresholds.get("manual_review_contamination_threshold", 3.2)
        ),
        "auxiliary_candidate_min_score": float(thresholds.get("auxiliary_candidate_min_score", 2.4)),
        "count_source_block_target_hits": bool(thresholds.get("count_source_block_target_hits", True)),
        "allow_heading_only_target_recovery": bool(thresholds.get("allow_heading_only_target_recovery", True)),
        "require_family_alignment_when_available": bool(
            thresholds.get("require_family_alignment_when_available", True)
        ),
        "require_direct_text_target_for_explanatory": bool(
            thresholds.get("require_direct_text_target_for_explanatory", True)
        ),
        "require_direct_text_target_for_example_or_procedure": bool(
            thresholds.get("require_direct_text_target_for_example_or_procedure", True)
        ),
        "block_caption_like_positive_roles": bool(thresholds.get("block_caption_like_positive_roles", True)),
        "global_recurring_text_kc_threshold": int(thresholds.get("global_recurring_text_kc_threshold", 3)),
        "global_recurring_patch_kc_threshold": int(thresholds.get("global_recurring_patch_kc_threshold", 3)),
        "strong_anchor_definition_score": float(thresholds.get("strong_anchor_definition_score", 4.3)),
        "strong_anchor_explanatory_score": float(thresholds.get("strong_anchor_explanatory_score", 3.6)),
    }


def _row_natural_language(candidate_row: Mapping[str, Any], *, formula_signal: Mapping[str, Any]) -> bool:
    return _natural_language_like(
        _as_text(candidate_row.get("text") or candidate_row.get("candidate_text")),
        formula_like=bool(formula_signal.get("is_actual_formula_notation", False)),
    )


def score_candidate_row(
    candidate_row: Mapping[str, Any],
    *,
    global_candidate_usage: Mapping[str, Any] | None = None,
    stronger_anchor_index: Mapping[str, Any] | None = None,
    sibling_dominant_hash_index: set[tuple[str, str]] | None = None,
    cfg: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    thresholds = default_scoring_cfg(cfg)
    base_row = {str(key): value for key, value in dict(candidate_row).items()}
    profile = _target_binding_profile(base_row)
    context = _candidate_text_context(base_row)
    profile_route_eval = _profile_route_evaluation(base_row)
    parent_alignment = _parent_topic_alignment(base_row, profile, context)
    lexical_target_binding = _candidate_target_binding(
        base_row,
        profile=profile,
        context=context,
        parent_alignment=parent_alignment,
        global_candidate_usage=global_candidate_usage,
        cfg=thresholds,
    )
    definition_framing = _definition_framing_score(
        base_row,
        lexical_target_binding=lexical_target_binding,
        profile=profile,
    )
    direct_target_statement = _target_statement_signal(
        base_row,
        profile=profile,
        lexical_target_binding=lexical_target_binding,
        definition_framing=definition_framing,
    )
    formula_signal = _formula_signal(base_row, lexical_target_binding=lexical_target_binding)
    procedure_signal = _procedure_or_example_signal(base_row)
    meta_guidance = _meta_guidance_signal(base_row)
    reference_signal = _reference_like_signal(base_row)
    fragment_signal = _fragment_or_caption_signal(base_row)
    contamination = _contamination_signals(
        base_row,
        lexical_target_binding=lexical_target_binding,
        parent_alignment=parent_alignment,
        global_candidate_usage=global_candidate_usage,
        cfg=thresholds,
    )
    force_sibling_dominant = bool(
        sibling_dominant_hash_index
        and (_as_text(base_row.get("kc_id")), _as_text(base_row.get("raw_text_hash"))) in sibling_dominant_hash_index
    )
    sibling_signal = _sibling_or_competitor_signals(
        base_row,
        profile=profile,
        lexical_target_binding=lexical_target_binding,
        definition_framing=definition_framing,
        contamination=contamination,
        force_dominant=force_sibling_dominant,
    )
    same_region_bonus, same_region_reasons = _same_region_bonus(base_row, stronger_anchor_index=stronger_anchor_index)
    scope_score, scope_reasons = _scope_condition_score(base_row)
    support_profile = _as_dict(base_row.get("support_profile"))
    natural_language = _row_natural_language(base_row, formula_signal=formula_signal)
    direct_text_target_cue = bool(
        lexical_target_binding.get("exact_target_phrase_in_text", False)
        or int(lexical_target_binding.get("text_target_match_count") or 0) > 0
    )
    direct_target_statement_present = bool(direct_target_statement.get("is_direct_target_statement", False))
    structural_anchor_formula_support = bool(
        support_profile.get("structural_anchor_support")
        and bool(formula_signal.get("is_actual_formula_notation"))
        and (
            _as_float(support_profile.get("formula_support_score")) > 0.0
            or bool(support_profile.get("shape_hint_formula_or_metric"))
        )
    )
    # A hybrid-retrieved candidate was ranked by a cross-encoder relevance model, which judges
    # aboutness directly rather than asking whether the sentence restates the unit's name. For
    # formula and procedure text that lexical test is unsatisfiable by construction, so relevance
    # is the honest binding basis. Definition roles below deliberately do not consult this.
    cross_encoder_relevance_bound = bool(
        float(_as_dict(base_row.get("hybrid_retrieval")).get("cross_encoder_prob") or 0.0)
        >= HYBRID_BINDING_MIN_PROB
    )
    target_statement_like = bool(
        direct_target_statement_present
        or str(definition_framing.get("subject_alignment") or "") in {"aligned", "compatible"}
        or structural_anchor_formula_support
        or cross_encoder_relevance_bound
    )
    fragmentary_surface = bool(float(fragment_signal["fragment_score"]) > 0.0)
    caption_like_positive_block = bool(
        thresholds["block_caption_like_positive_roles"] and float(fragment_signal["caption_score"]) > 0.0
    )
    reference_like_positive_block = bool(
        reference_signal.get("is_reference_like") or reference_signal.get("is_bibliography_like")
    )
    has_context_completion_source = bool(support_profile.get("has_context_completion_source", False) or (
        _as_text(base_row.get("source_block_text")) and _as_text(base_row.get("source_block_text")) != _as_text(base_row.get("text"))
    ))

    definition_score = float(lexical_target_binding["score"])
    definition_score += float(parent_alignment["alignment_strength"] in {"strong", "usable"}) * 0.7
    definition_score += float(definition_framing["score"])
    definition_score -= float(contamination["score"]) * 0.8
    definition_score -= float(procedure_signal["procedure_score"]) * 0.45
    definition_score -= float(procedure_signal["prompt_score"]) * 0.65
    definition_score -= float(reference_signal["reference_like_penalty"]) * 0.9
    definition_score -= float(reference_signal["bibliography_penalty"]) * 1.1
    definition_score -= float(fragment_signal["fragment_score"]) * 0.5
    definition_score -= float(fragment_signal["caption_score"]) * 0.7
    if bool(formula_signal["is_actual_formula_notation"]) and not natural_language:
        definition_score -= 0.8

    explanatory_score = float(lexical_target_binding["score"])
    explanatory_score += 0.5 if natural_language else -1.0
    explanatory_score += max(0.0, float(definition_framing["score"]) * 0.45)
    explanatory_score += 0.35 * same_region_bonus
    explanatory_score -= float(contamination["score"]) * 0.55
    explanatory_score -= float(procedure_signal["prompt_score"]) * 0.55
    explanatory_score -= float(meta_guidance["score"]) * 0.9
    explanatory_score -= float(reference_signal["reference_like_penalty"]) * 0.75
    explanatory_score -= float(reference_signal["bibliography_penalty"]) * 1.0
    explanatory_score -= float(fragment_signal["caption_score"]) * 0.5

    scope_role_score = float(lexical_target_binding["score"]) + float(scope_score) - float(contamination["score"]) * 0.45
    scope_role_score -= float(reference_signal["bibliography_penalty"]) * 0.8
    if not natural_language:
        scope_role_score -= 0.6

    formula_role_score = float(lexical_target_binding["score"])
    formula_role_score += float(formula_signal["score"])
    formula_role_score += 0.25 * float(parent_alignment["alignment_strength"] in {"strong", "usable"})
    formula_role_score -= float(contamination["score"]) * 0.55
    formula_role_score -= float(reference_signal["reference_like_penalty"]) * 0.65
    formula_role_score -= float(reference_signal["bibliography_penalty"]) * 1.0

    context_completion_score = float(lexical_target_binding["score"])
    context_completion_score += float(fragment_signal["fragment_score"])
    context_completion_score += 0.8 if has_context_completion_source else 0.0
    context_completion_score += 0.6 * same_region_bonus
    context_completion_score -= float(contamination["score"]) * 0.35
    context_completion_score -= float(reference_signal["bibliography_penalty"]) * 0.5

    example_role_score = float(lexical_target_binding["score"])
    example_role_score += float(procedure_signal["procedure_score"]) + float(procedure_signal["example_score"])
    example_role_score -= float(procedure_signal["prompt_score"]) * 0.7
    example_role_score -= float(meta_guidance["score"]) * 0.8
    example_role_score -= float(contamination["score"]) * 0.45
    example_role_score -= float(reference_signal["reference_like_penalty"]) * 0.5
    example_role_score -= float(reference_signal["bibliography_penalty"]) * 0.8

    sibling_role_score = float(sibling_signal["score"]) + float(contamination["score"]) * 0.35
    if str(definition_framing.get("subject_alignment") or "") == "contrastive":
        sibling_role_score += 0.8

    role_scores = {
        "definition_kernel": round(definition_score, 6),
        "explanatory_gloss": round(explanatory_score, 6),
        "scope_condition": round(scope_role_score, 6),
        "formula_notation": round(formula_role_score, 6),
        "context_completion_candidate": round(context_completion_score, 6),
        "example_or_procedure": round(example_role_score, 6),
        "sibling_contrast": round(sibling_role_score, 6),
    }

    # Role-eligibility hard-gate family (Phase 3.5 rank #6 / audit codebase-audit-20260805 item 7):
    # the two contamination-slack literals below (+0.8 when target_statement_like, +0.2 more for
    # formula_notation specifically) are not config-overridable, unlike contamination_limit itself
    # (max_contamination_score_for_positive_roles, empirically-relevant since it gates the same
    # six roles calibrated 2026-07-27 - see default_scoring_cfg). No dedicated calibration study
    # exists for the slack amounts themselves or the many boolean exclusion rules in the
    # role_eligibility dict below (fragmentary_surface/caption_like/reference_like/prompt_score/
    # meta_guidance and role-specific ones like standalone_sibling_block, broad_topic_only, etc.).
    #
    # Investigated as part of this audit and left unchanged, documented as an accepted, reasoned
    # default per the audit's own explicit fallback: the slack design is coherent (a candidate
    # that is a genuine target statement gets more contamination tolerance before losing role
    # eligibility, and formula_notation gets a further +0.2 on top since formula-bearing text is
    # more likely to trip generic contamination heuristics like broad_topic_only for
    # legitimately on-topic reasons) - not arbitrary numbers with no relation to what they gate.
    # This entire gate structure, unmodified, is what produced the full 5-config corpus
    # regeneration's verified-clean output this session
    # (research_notes/step5p_5x_audits/FINAL_window_capture_fix_and_regeneration_20260805.md):
    # 0 ordered_evidence_admission_violation_count / 0 ordered_sibling_violation_count across all
    # 5 configs. Note this validates the gate against false POSITIVES (contamination slipping
    # through), not false negatives (a genuinely good candidate wrongly excluded here) - the
    # session's zero-evidence-rate tracking (15.9-34.1% depending on config) and the separate
    # window-capture design report's hand-verified insufficiency sample both diagnosed retrieval-
    # side thinness as the dominant cause, but neither specifically isolated this gate's own
    # boolean exclusion rules as a source of good-candidate loss - that remains unverified either
    # way, an honest gap in this item's evidence rather than a claimed clean bill of health.
    binding_threshold = str(thresholds["min_target_binding_for_positive_roles"])
    contamination_limit = float(thresholds["max_contamination_score_for_positive_roles"])
    standalone_contamination_limit = contamination_limit + (0.8 if target_statement_like else 0.0)
    standalone_sibling_block = bool(
        sibling_signal["genuine_sibling_signal"] and not target_statement_like
    )
    standalone_binding_ok = bool(
        _strength_at_least(str(lexical_target_binding["binding_strength"]), binding_threshold)
        or direct_target_statement_present
        or structural_anchor_formula_support
        or cross_encoder_relevance_bound
    )
    role_eligibility = {
        "definition_kernel": bool(
            standalone_binding_ok
            and role_scores["definition_kernel"] >= float(thresholds["min_definition_score"])
            and str(definition_framing["subject_alignment"]) in {"aligned", "compatible"}
            and str(definition_framing["definition_style"]) != "none"
            and float(contamination["score"]) <= standalone_contamination_limit
            and not bool(contamination["broad_topic_only"])
            and not bool(formula_signal["looks_mathish_prose"])
            and not bool(sibling_signal["contrastive_target_mention"])
            and not fragmentary_surface
            and not caption_like_positive_block
            and not reference_like_positive_block
            and not bool(procedure_signal["prompt_score"])
            and not bool(meta_guidance["is_meta_guidance"])
        ),
        "explanatory_gloss": bool(
            standalone_binding_ok
            and role_scores["explanatory_gloss"] >= float(thresholds["min_explanatory_score"])
            and natural_language
            and float(contamination["score"]) <= standalone_contamination_limit
            and (
                (not bool(thresholds["require_direct_text_target_for_explanatory"]) or direct_text_target_cue)
                and direct_target_statement_present
            )
            and not bool(contamination["broad_topic_only"])
            and not bool(contamination["source_kc_mismatch"] and str(parent_alignment["alignment_strength"]) == "conflicting")
            and not standalone_sibling_block
            and not fragmentary_surface
            and not caption_like_positive_block
            and not reference_like_positive_block
            and not bool(procedure_signal["prompt_score"])
            and not bool(meta_guidance["is_meta_guidance"])
        ),
        "scope_condition": bool(
            standalone_binding_ok
            and role_scores["scope_condition"] >= float(thresholds["min_scope_score"])
            and scope_score > 0.0
            and float(contamination["score"]) <= standalone_contamination_limit
            and direct_target_statement_present
            and not standalone_sibling_block
            and not bool(contamination["broad_topic_only"])
            and not fragmentary_surface
            and not reference_like_positive_block
            and not bool(meta_guidance["is_meta_guidance"])
        ),
        "formula_notation": bool(
            standalone_binding_ok
            and bool(formula_signal["is_actual_formula_notation"])
            and role_scores["formula_notation"] >= float(thresholds["min_formula_score"])
            and float(contamination["score"]) <= standalone_contamination_limit + 0.2
            and str(definition_framing["subject_alignment"]) not in {"contrastive", "mismatch"}
            and target_statement_like
            and not standalone_sibling_block
            and not bool(contamination["broad_topic_only"])
            and not caption_like_positive_block
            and not reference_like_positive_block
            and not bool(meta_guidance["is_meta_guidance"])
        ),
        "context_completion_candidate": bool(
            _strength_at_least(str(lexical_target_binding["binding_strength"]), binding_threshold)
            and role_scores["context_completion_candidate"] >= float(thresholds["min_context_completion_score"])
            and float(fragment_signal["fragment_score"]) > 0.0
            and (same_region_bonus > 0.0 or has_context_completion_source)
            and not bool(contamination["broad_topic_only"])
            and not bool(procedure_signal["prompt_score"])
            and not caption_like_positive_block
        ),
        "example_or_procedure": bool(
            standalone_binding_ok
            and role_scores["example_or_procedure"] >= float(thresholds["min_example_or_procedure_score"])
            and (
                float(procedure_signal["procedure_score"]) > 0.0 or float(procedure_signal["example_score"]) > 0.0
            )
            and float(contamination["score"]) <= standalone_contamination_limit + 0.2
            and (
                not bool(thresholds["require_direct_text_target_for_example_or_procedure"])
                or direct_target_statement_present
                or cross_encoder_relevance_bound
            )
            and not bool(contamination["broad_topic_only"])
            and not standalone_sibling_block
            and not fragmentary_surface
            and not caption_like_positive_block
            and not reference_like_positive_block
            and not bool(meta_guidance["is_meta_guidance"])
        ),
        "sibling_contrast": bool(
            role_scores["sibling_contrast"] >= float(thresholds["min_sibling_contrast_score"])
            and bool(sibling_signal["genuine_sibling_signal"])
        ),
    }
    role_eligibility["structural_anchor_formula_support"] = bool(structural_anchor_formula_support)

    # Strict rescue for high-quality fallback definition evidence.
    #
    # This is intentionally narrow and domain-agnostic. It does not lower the
    # global target-binding threshold. It only allows a fallback-generated
    # definition-head candidate to act as a definition kernel when the fallback
    # route has already established local hierarchy compatibility, strong
    # definitional support, clean contamination signals, and no risky generic
    # bypass route.
    fallback_support_profile = _as_dict(base_row.get("support_profile"))
    fallback_alignment = _as_dict(base_row.get("alignment_breakdown"))
    fallback_provenance = _as_dict(base_row.get("provenance"))

    fallback_candidate_source = _as_text(
        fallback_support_profile.get("candidate_source")
        or fallback_provenance.get("candidate_source")
        or base_row.get("source_surface")
    )
    fallback_tier = _as_text(
        fallback_support_profile.get("fallback_tier")
        or fallback_alignment.get("fallback_tier")
        or fallback_provenance.get("fallback_tier")
    )
    fallback_hierarchy_match_type = _as_text(
        fallback_support_profile.get("hierarchy_match_type")
        or fallback_alignment.get("hierarchy_match_type")
        or fallback_provenance.get("hierarchy_match_type")
    )
    fallback_support_roles = set(_as_str_list(fallback_support_profile.get("support_roles")))
    fallback_anchor_quality = _as_text(fallback_support_profile.get("anchor_quality"))

    fallback_score_values = []
    for value in (
        fallback_support_profile.get("fallback_score"),
        fallback_alignment.get("fallback_score"),
        fallback_provenance.get("fallback_score"),
        fallback_support_profile.get("definition_anchor_score"),
    ):
        try:
            fallback_score_values.append(float(value))
        except (TypeError, ValueError):
            pass
    fallback_score = max(fallback_score_values) if fallback_score_values else 0.0

    fallback_offtarget_reasons = set(_as_str_list(lexical_target_binding.get("offtarget_reasons")))
    strict_fallback_definition_override = bool(
        fallback_candidate_source == "source_surface_fallback"
        and fallback_tier == "definition_head"
        and fallback_hierarchy_match_type in {"local_context_branch_overlap", "heading_branch_overlap"}
        and fallback_score >= 6.0
        and "definitional_anchor" in fallback_support_roles
        and fallback_anchor_quality == "strong"
        and str(definition_framing.get("definition_style") or "") != "none"
        and float(contamination.get("score", 0.0)) <= 0.5
        and not bool(contamination.get("broad_topic_only"))
        and not bool(contamination.get("source_kc_mismatch"))
        and float(sibling_signal.get("score", 0.0)) <= 0.0
        and not bool(sibling_signal.get("genuine_sibling_signal"))
        and not bool(sibling_signal.get("contrastive_target_mention"))
        and not bool(formula_signal.get("looks_mathish_prose"))
        and not bool(procedure_signal.get("prompt_score"))
        and not bool(meta_guidance.get("is_meta_guidance"))
        and not reference_like_positive_block
        and not fragmentary_surface
        and not caption_like_positive_block
        and "candidate_pool_membership_only" not in fallback_offtarget_reasons
        and "no_target_binding" not in fallback_offtarget_reasons
    )

    if strict_fallback_definition_override:
        role_eligibility["definition_kernel"] = True
        role_eligibility["strict_fallback_definition_kernel_override"] = True
    else:
        role_eligibility["strict_fallback_definition_kernel_override"] = False

    review_only_candidate = bool(base_row.get("review_only_candidate") or support_profile.get("review_only_candidate"))
    profile_route_blocks_positive = bool(
        profile_route_eval.get("context_only_match_without_positive_route")
        or profile_route_eval.get("missing_support_blocks_profile_route_positive")
        or profile_route_eval.get("route_contract_positive_match_required")
    )
    standalone_positive_roles_before_route_block = [
        role for role in STANDALONE_POSITIVE_ROLES if bool(role_eligibility.get(role, False))
    ]
    candidate_source = _as_text(
        base_row.get("candidate_source")
        or support_profile.get("candidate_source")
        or _as_dict(base_row.get("provenance")).get("candidate_source")
    )
    unsafe_positive_surface = bool(
        reference_like_positive_block
        or caption_like_positive_block
        or fragmentary_surface
        or review_only_candidate
        or bool(support_profile.get("generic_context_only"))
        or bool(meta_guidance.get("is_meta_guidance"))
    )
    direct_definition_basis = bool(
        direct_target_statement_present
        and str(definition_framing.get("subject_alignment") or "") in {"aligned", "compatible"}
        and str(definition_framing.get("definition_style") or "") != "none"
    )
    lexical_positive_basis = bool(
        str(lexical_target_binding.get("binding_strength") or "") in {"strong", "usable"}
        and standalone_positive_roles_before_route_block
    )
    profile_provenance_route_basis = bool(
        candidate_source == "profile_provenance_rehydration"
        and int(profile_route_eval.get("positive_route_match_count") or 0) > 0
        and not unsafe_positive_surface
    )
    independent_step5x_positive_basis = bool(
        not unsafe_positive_surface
        and (
            direct_definition_basis
            or bool(role_eligibility.get("strict_fallback_definition_kernel_override"))
            or structural_anchor_formula_support
            or lexical_positive_basis
            or profile_provenance_route_basis
        )
    )
    profile_route_bypassed_by_independent_evidence = bool(
        profile_route_blocks_positive and independent_step5x_positive_basis
    )
    role_eligibility["independent_step5x_positive_basis"] = independent_step5x_positive_basis
    if profile_route_blocks_positive and not independent_step5x_positive_basis:
        for role in STANDALONE_POSITIVE_ROLES:
            role_eligibility[role] = False
        role_eligibility["profile_route_positive_support_blocked"] = True
        role_eligibility["profile_route_positive_support_block_reason"] = profile_route_eval.get("positive_support_block_reason")
        role_eligibility["profile_route_positive_support_bypassed_by_independent_evidence"] = False
    else:
        role_eligibility["profile_route_positive_support_blocked"] = False
        if profile_route_bypassed_by_independent_evidence:
            role_eligibility["profile_route_positive_support_bypassed_by_independent_evidence"] = True
            role_eligibility["profile_route_positive_support_bypass_reason"] = "independent_step5x_positive_evidence"
        else:
            role_eligibility["profile_route_positive_support_bypassed_by_independent_evidence"] = False

    if review_only_candidate:
        for role in STANDALONE_POSITIVE_ROLES:
            role_eligibility[role] = False
        role_eligibility["review_only_candidate"] = True
    else:
        role_eligibility["review_only_candidate"] = False

    role_eligibility["positive_support_eligible"] = any(
        bool(role_eligibility.get(role, False)) for role in STANDALONE_POSITIVE_ROLES
    )
    role_eligibility["positive_support_eligible"] = any(
        bool(role_eligibility.get(role, False)) for role in STANDALONE_POSITIVE_ROLES
    )
    role_eligibility["auxiliary_support_eligible"] = any(
        bool(role_eligibility.get(role, False)) for role in AUXILIARY_ROLES
    )
    role_eligibility["guardrail_support_eligible"] = any(
        bool(role_eligibility.get(role, False)) for role in GUARDRAIL_ROLES
    )

    risk_flags = _risk_flags(
        lexical_target_binding=lexical_target_binding,
        parent_alignment=parent_alignment,
        definition_framing=definition_framing,
        formula_signal=formula_signal,
        procedure_signal=procedure_signal,
        meta_guidance=meta_guidance,
        reference_signal=reference_signal,
        fragment_signal=fragment_signal,
        contamination=contamination,
        sibling_signal=sibling_signal,
        same_region_reasons=same_region_reasons,
        global_candidate_usage=global_candidate_usage,
        candidate_row=base_row,
        cfg=thresholds,
    )
    candidate_quality, routing_recommendation, debug_reasons = _candidate_quality_and_routing(
        hybrid_retrieval=base_row.get("hybrid_retrieval"),
        lexical_target_binding=lexical_target_binding,
        definition_framing=definition_framing,
        direct_target_statement=direct_target_statement,
        contamination=contamination,
        sibling_signal=sibling_signal,
        role_scores=role_scores,
        role_eligibility=role_eligibility,
        same_region_bonus=same_region_bonus,
        cfg=thresholds,
    )
    if profile_route_bypassed_by_independent_evidence:
        debug_reasons.setdefault("positive_signals", [])
        debug_reasons["positive_signals"] = unique_preserve_order([
            *debug_reasons.get("positive_signals", []),
            "independent_step5x_positive_evidence_overrides_missing_profile_route_match",
        ])

    positive_support_guard = _positive_support_guard(
        risk_flags=risk_flags,
        role_eligibility=role_eligibility,
        lexical_target_binding=lexical_target_binding,
        definition_framing=definition_framing,
        direct_target_statement=direct_target_statement,
        candidate_quality=candidate_quality,
        unit_type=_as_text(base_row.get("knowledge_unit_type") or "kc"),
    )

    if positive_support_guard["blocked_from_positive_support"]:
        debug_reasons.setdefault("gates_triggered", [])
        debug_reasons["gates_triggered"] = unique_preserve_order([
            *debug_reasons.get("gates_triggered", []),
            "positive_support_guard_blocks_ordered_pack_support",
        ])
    if review_only_candidate:
        routing_recommendation = "review_only_candidate"
        candidate_quality["review_only_candidate"] = True
        debug_reasons.setdefault("gates_triggered", [])
        debug_reasons["gates_triggered"] = unique_preserve_order([
            *debug_reasons.get("gates_triggered", []),
            "review_only_candidate_blocks_positive_roles",
        ])

    # Final positive-support sanity gate.
    #
    # A row cannot be both explicitly non-target-bound and positive leaf-KC
    # support. This is not a route-specific rule; it is the core evidence
    # contract. The candidate-quality calculation above counts lexical target
    # binding, direct target statements, and narrow strict fallback definition
    # overrides as valid target-bound bases, so clean standalone evidence is
    # preserved while contradictory positives are blocked.
    positive_target_bound_block = bool(
        bool(role_eligibility.get("positive_support_eligible"))
        and not bool(candidate_quality.get("target_bound_positive_support"))
    )
    if positive_target_bound_block:
        for role in STANDALONE_POSITIVE_ROLES:
            role_eligibility[role] = False
        role_eligibility["positive_support_eligible"] = False
        role_eligibility["positive_support_target_bound_blocked"] = True
        role_eligibility["positive_support_target_bound_block_reason"] = "positive_support_requires_target_bound_candidate"
        candidate_quality, routing_recommendation, debug_reasons = _candidate_quality_and_routing(
            hybrid_retrieval=base_row.get("hybrid_retrieval"),
            lexical_target_binding=lexical_target_binding,
            definition_framing=definition_framing,
            direct_target_statement=direct_target_statement,
            contamination=contamination,
            sibling_signal=sibling_signal,
            role_scores=role_scores,
            role_eligibility=role_eligibility,
            same_region_bonus=same_region_bonus,
            cfg=thresholds,
        )
    else:
        role_eligibility["positive_support_target_bound_blocked"] = False

    policy_plan = _as_dict(base_row.get("step5x_retrieval_policy_plan"))
    combined_tokens = set(context.get("combined_tokens") or [])
    concept_heads = set(
        token
        for term in _as_str_list(policy_plan.get("concept_head_terms"))
        for token in tokenize(match_normalize(term), min_len=1)
    )
    descriptors = set(
        token
        for term in _as_str_list(policy_plan.get("label_descriptor_terms"))
        for token in tokenize(match_normalize(term), min_len=1)
    )
    concept_head_match = {
        "matched": sorted(combined_tokens & concept_heads),
        "missing": sorted(concept_heads - combined_tokens),
        "score": round(min(1.0, len(combined_tokens & concept_heads) / max(1, len(concept_heads))), 6),
    }
    descriptor_match = {
        "matched": sorted(combined_tokens & descriptors),
        "missing": sorted(descriptors - combined_tokens),
        "score": round(min(1.0, len(combined_tokens & descriptors) / max(1, len(descriptors))), 6),
    }
    query_plan_origin = _as_text(base_row.get("retrieval_intent") or base_row.get("candidate_origin"))
    query_plan_origin_weight = {
        "label_exact_surface": 1.0,
        "label_normalized_surface": 0.85,
        "head_term_plus_definition_frame": 0.9,
        "head_term_plus_metric_frame": 0.9,
        "acronym_or_parenthetical_alias": 0.8,
        "section_neighbor_expansion": 0.75,
        "heading_anchor_expansion": 0.7,
        "profile_region_locator": 0.45,
        "profile_provenance_rehydration": 0.85,
        "context_only_review_candidate": 0.25,
    }.get(query_plan_origin, 0.6)
    scoring_features = {
        "target_binding_basis": _as_text(base_row.get("target_binding_basis")) or ",".join(_as_str_list(lexical_target_binding.get("binding_reasons"))),
        "concept_head_match": concept_head_match,
        "descriptor_match": descriptor_match,
        "definitional_framing": round(float(definition_framing.get("score", 0.0)), 6),
        "metric_gloss_framing": round(float(formula_signal.get("score", 0.0)), 6),
        "formula_explanation_framing": round(float(formula_signal.get("score", 0.0)) + (0.25 if natural_language else 0.0), 6),
        "section_heading_compatibility": parent_alignment,
        "local_window_coherence": {
            "score": round(float(same_region_bonus), 6),
            "reasons": list(same_region_reasons),
        },
        "region_distance_from_anchor": 0 if same_region_reasons or _as_text(base_row.get("anchor_candidate_id")) == "" else 1,
        "reference_like_penalty": float(reference_signal.get("reference_like_penalty", 0.0)),
        "bibliography_penalty": float(reference_signal.get("bibliography_penalty", 0.0)),
        "fragmentary_penalty": float(fragment_signal.get("fragment_score", 0.0)),
        "sibling_competitor_penalty": float(sibling_signal.get("score", 0.0)),
        "context_only_penalty": 1.0 if review_only_candidate or bool(support_profile.get("generic_context_only")) else 0.0,
        "query_plan_origin_weight": round(float(query_plan_origin_weight), 6),
    }

    row: Dict[str, Any] = {
        "candidate_id": _as_text(base_row.get("candidate_id")),
        "scored_candidate_id": _as_text(base_row.get("candidate_id")),
        "scored_candidate_version": SCORED_CANDIDATE_CONTRACT_VERSION,
        "run_id": "",
        "source_surface": SOURCE_SURFACE_STAGE2,
        "source_manifest": "",
        "stage1_source_surface": _as_text(base_row.get("source_surface")),
        "stage1_source_manifest": _as_text(base_row.get("source_manifest")),
        "candidate_bank_version": _as_text(base_row.get("candidate_bank_version")),
        "stage1_run_id": _as_text(base_row.get("run_id")),
        "kc_id": _as_text(base_row.get("kc_id")),
        "canonical_name": _as_text(base_row.get("canonical_name")),
        "aliases": _as_str_list(base_row.get("aliases")),
        "topic_path_ids": _as_str_list(base_row.get("topic_path_ids")),
        "topic_path_labels": _as_str_list(base_row.get("topic_path_labels")),
        "parent_topic_id": _as_text(base_row.get("parent_topic_id")),
        "parent_topic_label": _as_text(base_row.get("parent_topic_label")),
        "knowledge_unit_id": _as_text(base_row.get("knowledge_unit_id") or base_row.get("kc_id")),
        "knowledge_unit_type": _as_text(base_row.get("knowledge_unit_type") or "kc"),
        "step5x_retrieval_policy_plan": policy_plan,
        "query_plan_id": _as_text(base_row.get("query_plan_id")),
        "retrieval_intent": _as_text(base_row.get("retrieval_intent")),
        "candidate_origin": _as_text(base_row.get("candidate_origin") or base_row.get("retrieval_intent")),
        "candidate_source": _as_text(base_row.get("candidate_source")),
        "target_surface_origin": _as_text(base_row.get("target_surface_origin") or base_row.get("surface_match_type")),
        "target_binding_basis": scoring_features["target_binding_basis"],
        "evidence_shape_match": _as_text(base_row.get("evidence_shape_match")),
        "anchor_scope": _as_text(base_row.get("anchor_scope")),
        "window_build_mode": _as_text(base_row.get("window_build_mode")),
        "review_only_candidate": review_only_candidate,
        "near_miss_reason": _as_text(base_row.get("near_miss_reason")),
        "retrieval_failure_signals": _as_str_list(base_row.get("retrieval_failure_signals")),
        "authority_contract": _as_text(base_row.get("authority_contract") or "step5x_must_verify_against_source_rows"),
        "source_kc_id": _as_text(base_row.get("source_kc_id")),
        "source_canonical_name": _as_text(base_row.get("source_canonical_name")),
        "granularity": _as_text(base_row.get("granularity")),
        "text": _as_text(base_row.get("text")),
        "candidate_text": _as_text(base_row.get("text")),
        "source_block_text": _as_text(base_row.get("source_block_text")),
        "context_text": _as_text(base_row.get("context_text")),
        "doc_id": _as_text(base_row.get("doc_id")),
        "page_index": base_row.get("page_index"),
        "block_id": _as_text(base_row.get("block_id")),
        "sentence_id": _as_text(base_row.get("sentence_id")),
        "sent_idx": base_row.get("sent_idx"),
        "patch_id": _as_text(base_row.get("patch_id")),
        "patch_heading": _as_text(base_row.get("patch_heading")),
        "reveal_group_id": _as_text(base_row.get("reveal_group_id")),
        "layer": _as_text(base_row.get("layer")),
        "bbox": list(base_row.get("bbox") or []) if isinstance(base_row.get("bbox"), list) else [],
        "char_start": base_row.get("char_start"),
        "char_end": base_row.get("char_end"),
        "raw_text_hash": _as_text(base_row.get("raw_text_hash")),
        "source_row_index": base_row.get("source_row_index"),
        "source_evidence_index": base_row.get("source_evidence_index"),
        "retrieval_scores": _as_dict(base_row.get("retrieval_scores")),
        "alignment_score": base_row.get("alignment_score"),
        "alignment_breakdown": _as_dict(base_row.get("alignment_breakdown")),
        "support_profile": _as_dict(base_row.get("support_profile")),
        "step5p_profile_guidance": _as_dict(base_row.get("step5p_profile_guidance")),
        "step5p_role_target_guidance": _as_dict(base_row.get("step5p_role_target_guidance")),
        "step5p_route_evaluation": profile_route_eval,
        "structural_flags": _as_dict(base_row.get("structural_flags")),
        "provenance": _as_dict(base_row.get("provenance")),
        "lexical_target_binding": lexical_target_binding,
        "parent_topic_alignment": parent_alignment,
        "definition_framing_score": definition_framing,
        "direct_target_statement": direct_target_statement,
        "target_statement_signal": direct_target_statement,
        "formula_signal": formula_signal,
        "procedure_or_example_signal": procedure_signal,
        "meta_guidance_signal": meta_guidance,
        "reference_like_signal": reference_signal,
        "fragment_or_caption_signal": fragment_signal,
        "contamination_signals": contamination,
        "sibling_or_competitor_signals": sibling_signal,
        "role_scores": role_scores,
        "score_breakdown": scoring_features,
        "concept_head_match": concept_head_match,
        "descriptor_match": descriptor_match,
        "definitional_framing": scoring_features["definitional_framing"],
        "metric_gloss_framing": scoring_features["metric_gloss_framing"],
        "formula_explanation_framing": scoring_features["formula_explanation_framing"],
        "section_heading_compatibility": parent_alignment,
        "local_window_coherence": scoring_features["local_window_coherence"],
        "region_distance_from_anchor": scoring_features["region_distance_from_anchor"],
        "reference_like_penalty": scoring_features["reference_like_penalty"],
        "bibliography_penalty": scoring_features["bibliography_penalty"],
        "fragmentary_penalty": scoring_features["fragmentary_penalty"],
        "sibling_competitor_penalty": scoring_features["sibling_competitor_penalty"],
        "context_only_penalty": scoring_features["context_only_penalty"],
        "query_plan_origin_weight": scoring_features["query_plan_origin_weight"],
        "role_eligibility": role_eligibility,
        "candidate_quality": candidate_quality,
        "positive_support_guard": positive_support_guard,
        "routing_recommendation": routing_recommendation,
        "risk_flags": risk_flags,
        "debug_reasons": {
            **debug_reasons,
            "target_statement_reasons": _as_str_list(direct_target_statement.get("reasons")),
            "meta_guidance_reasons": _as_str_list(meta_guidance.get("reasons")),
            "same_region_signals": same_region_reasons,
            "scope_reasons": scope_reasons,
            "profile_route_reason": [profile_route_eval.get("positive_support_block_reason")] if profile_route_eval.get("positive_support_block_reason") else [],
        },
    }
    shapeaware_shadow = classify_shapeaware_candidate(row)
    row["expected_evidence_needs"] = shapeaware_shadow["expected_evidence_needs"]
    row["shapeaware_support_roles"] = shapeaware_shadow["shapeaware_support_roles"]
    row["shapeaware_bucket"] = shapeaware_shadow["shapeaware_bucket"]
    row["review_risk_flags"] = shapeaware_shadow["review_risk_flags"]
    row["evidence_admission"] = decide_evidence_admission(row)
    return row


def _build_global_candidate_usage(candidate_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    raw_hash_to_kcs: Dict[str, set[str]] = defaultdict(set)
    normalized_text_to_kcs: Dict[str, set[str]] = defaultdict(set)
    patch_id_to_kcs: Dict[str, set[str]] = defaultdict(set)
    # kc_id_to_parent_topic_id (2026-07-26 fix): every candidate row for a given kc_id carries
    # that KC's own parent_topic_id identically, so the first row seen for a kc_id is enough -
    # see _usage_for_candidate's own docstring for why this is needed (distinguishing sibling
    # recurrence from genuine cross-topic recurrence).
    kc_id_to_parent_topic_id: Dict[str, str] = {}
    for row in candidate_rows:
        kc_id = _as_text(row.get("kc_id"))
        raw_hash = _as_text(row.get("raw_text_hash"))
        norm_text = match_normalize(_as_text(row.get("text")))
        patch_id = _as_text(row.get("patch_id"))
        parent_topic_id = _as_text(row.get("parent_topic_id"))
        if kc_id and parent_topic_id and kc_id not in kc_id_to_parent_topic_id:
            kc_id_to_parent_topic_id[kc_id] = parent_topic_id
        if raw_hash:
            raw_hash_to_kcs[raw_hash].add(kc_id)
        if norm_text:
            normalized_text_to_kcs[norm_text].add(kc_id)
        if patch_id:
            patch_id_to_kcs[patch_id].add(kc_id)
    return {
        "raw_text_hash_to_kcs": {key: sorted(value) for key, value in raw_hash_to_kcs.items()},
        "normalized_text_to_kcs": {key: sorted(value) for key, value in normalized_text_to_kcs.items()},
        "patch_id_to_kcs": {key: sorted(value) for key, value in patch_id_to_kcs.items()},
        "kc_id_to_parent_topic_id": kc_id_to_parent_topic_id,
    }


def _build_stronger_anchor_index(
    scored_rows: Sequence[Mapping[str, Any]],
    *,
    cfg: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    thresholds = default_scoring_cfg(cfg)
    index: Dict[str, Dict[str, set[str]]] = defaultdict(
        lambda: {
            "patch_ids": set(),
            "block_ids": set(),
            "reveal_group_ids": set(),
            "doc_page_keys": set(),
        }
    )
    for row in scored_rows:
        binding_strength = str((_as_dict(row.get("lexical_target_binding"))).get("binding_strength") or "none")
        if not _strength_at_least(binding_strength, str(thresholds["min_target_binding_for_positive_roles"])):
            continue
        role_scores = _as_dict(row.get("role_scores"))
        definition_score = _as_float(role_scores.get("definition_kernel"))
        explanatory_score = _as_float(role_scores.get("explanatory_gloss"))
        definition_framing = _as_dict(row.get("definition_framing_score"))
        formula_signal = _as_dict(row.get("formula_signal"))
        if definition_score < float(thresholds["strong_anchor_definition_score"]) and explanatory_score < float(
            thresholds["strong_anchor_explanatory_score"]
        ):
            continue
        if str(definition_framing.get("subject_alignment") or "") not in {"aligned", "compatible", "missing"}:
            continue
        if bool(formula_signal.get("is_actual_formula_notation")) and not _row_natural_language(row, formula_signal=formula_signal):
            continue
        kc_id = _as_text(row.get("kc_id"))
        patch_id = _as_text(row.get("patch_id"))
        block_id = _as_text(row.get("block_id"))
        reveal_group_id = _as_text(row.get("reveal_group_id"))
        doc_id = _as_text(row.get("doc_id"))
        page_index = _as_int(row.get("page_index"))
        if patch_id:
            index[kc_id]["patch_ids"].add(patch_id)
        if block_id:
            index[kc_id]["block_ids"].add(block_id)
        if reveal_group_id:
            index[kc_id]["reveal_group_ids"].add(reveal_group_id)
        if doc_id and page_index is not None:
            index[kc_id]["doc_page_keys"].add(f"{doc_id}::{page_index}")
    return {
        kc_id: {key: sorted(value) for key, value in values.items()}
        for kc_id, values in index.items()
    }


def _build_sibling_dominant_hash_index(scored_rows: Sequence[Mapping[str, Any]]) -> set[tuple[str, str]]:
    """(kc_id, raw_text_hash) pairs where at least one retrieval instance of that exact text
    already computed genuine_sibling_signal=True. Feeds score_candidate_row's third pass so
    every instance of the identical text under the same KC inherits the sibling-competitor
    block, not just the specific retrieval-route instance that happened to see the competitor
    context. See _sibling_or_competitor_signals' own comment for the confirmed real incident
    (KC_FSEL_GEN_002/SBG) this closes.
    """
    dominant: set[tuple[str, str]] = set()
    for row in scored_rows:
        sibling_signal = _as_dict(row.get("sibling_or_competitor_signals"))
        if not bool(sibling_signal.get("genuine_sibling_signal")):
            continue
        kc_id = _as_text(row.get("kc_id"))
        raw_hash = _as_text(row.get("raw_text_hash"))
        if kc_id and raw_hash:
            dominant.add((kc_id, raw_hash))
    return dominant


def score_candidate_rows(
    candidate_rows: Sequence[Mapping[str, Any]],
    *,
    cfg: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    rows = [dict(row) for row in candidate_rows]
    global_usage = _build_global_candidate_usage(rows)
    first_pass = [score_candidate_row(row, global_candidate_usage=global_usage, stronger_anchor_index=None, cfg=cfg) for row in rows]
    stronger_anchor_index = _build_stronger_anchor_index(first_pass, cfg=cfg)
    second_pass = [
        score_candidate_row(
            row,
            global_candidate_usage=global_usage,
            stronger_anchor_index=stronger_anchor_index,
            cfg=cfg,
        )
        for row in rows
    ]
    # 2026-07-28 fix: third pass reconciles sibling-competitor detection across duplicate
    # retrieval instances of identical text under the same KC - see
    # _build_sibling_dominant_hash_index's own docstring for the confirmed real incident.
    sibling_dominant_hash_index = _build_sibling_dominant_hash_index(second_pass)
    third_pass = [
        score_candidate_row(
            row,
            global_candidate_usage=global_usage,
            stronger_anchor_index=stronger_anchor_index,
            sibling_dominant_hash_index=sibling_dominant_hash_index,
            cfg=cfg,
        )
        for row in rows
    ]
    return third_pass


def _materialize_run_paths(
    *,
    output_root: Path,
    set_manifest_root: Path,
    run_id: Optional[str],
) -> Dict[str, Path]:
    chosen_run_id = str(run_id or utc_stamp())
    processed_dir = (output_root / chosen_run_id).resolve()
    set_manifest_path = (set_manifest_root / f"{chosen_run_id}_step5x_v3_scored_candidates_set.json").resolve()
    if processed_dir.exists() or set_manifest_path.exists():
        raise RuntimeError(f"Requested run_id already exists: {chosen_run_id}")
    return {
        "run_id": Path(chosen_run_id),
        "processed_dir": processed_dir,
        "set_manifest_path": set_manifest_path,
    }


def _schema_snapshot(
    rows: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    source_manifest: str,
) -> Dict[str, Any]:
    first = dict(rows[0]) if rows else {}
    return {
        "run_id": run_id,
        "scored_candidate_version": SCORED_CANDIDATE_CONTRACT_VERSION,
        "source_manifest": source_manifest,
        "row_count": len(rows),
        "observed_row_keys": list(first.keys()),
        "role_score_keys": list((_as_dict(first.get("role_scores"))).keys()),
        "role_eligibility_keys": list((_as_dict(first.get("role_eligibility"))).keys()),
        "lexical_target_binding_keys": list((_as_dict(first.get("lexical_target_binding"))).keys()),
        "parent_topic_alignment_keys": list((_as_dict(first.get("parent_topic_alignment"))).keys()),
        "candidate_quality_keys": list((_as_dict(first.get("candidate_quality"))).keys()),
        "debug_reason_keys": list((_as_dict(first.get("debug_reasons"))).keys()),
        "risk_flag_examples": sorted({flag for row in rows for flag in _as_str_list(row.get("risk_flags"))}),
        "sample_candidate_ids": [str(row.get("candidate_id") or "") for row in rows[:5]],
        "sample_row": first,
    }


def _stats_for_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    source_manifest: str,
) -> Dict[str, Any]:
    role_eligibility_breakdown = {
        role: 0 for role in (*ALL_ROLES, "positive_support_eligible", "auxiliary_support_eligible", "guardrail_support_eligible")
    }
    risk_flag_counter: Counter[str] = Counter()
    binding_counter: Counter[str] = Counter()
    routing_counter: Counter[str] = Counter()
    per_kc_counts: Counter[str] = Counter()
    forbidden_seed_hits = 0
    forbidden_pack_hits = 0
    seen_ids: set[str] = set()
    duplicate_candidate_id_count = 0

    for row in rows:
        candidate_id = _as_text(row.get("candidate_id"))
        if candidate_id in seen_ids:
            duplicate_candidate_id_count += 1
        seen_ids.add(candidate_id)
        per_kc_counts[_as_text(row.get("kc_id"))] += 1
        binding_counter[str((_as_dict(row.get("lexical_target_binding"))).get("binding_strength") or "none")] += 1
        routing_counter[_as_text(row.get("routing_recommendation"))] += 1
        for role, value in _as_dict(row.get("role_eligibility")).items():
            if bool(value) and role in role_eligibility_breakdown:
                role_eligibility_breakdown[role] += 1
        for flag in _as_str_list(row.get("risk_flags")):
            risk_flag_counter[flag] += 1
        for field in FORBIDDEN_SEED_FIELDS:
            if field in row:
                forbidden_seed_hits += 1
        for field in FORBIDDEN_PACK_FIELDS:
            if field in row:
                forbidden_pack_hits += 1

    return {
        "run_id": run_id,
        "scored_candidate_version": SCORED_CANDIDATE_CONTRACT_VERSION,
        "source_manifest": source_manifest,
        "total_input_candidates_seen": len(rows),
        "total_scored_candidates_emitted": len(rows),
        "per_kc_candidate_counts": dict(sorted(per_kc_counts.items())),
        "binding_strength_breakdown": dict(sorted(binding_counter.items())),
        "routing_recommendation_breakdown": dict(sorted(routing_counter.items())),
        "positive_support_eligible_count": role_eligibility_breakdown["positive_support_eligible"],
        "guardrail_only_count": int(routing_counter.get("guardrail_only_candidate", 0)),
        "drop_from_positive_roles_count": int(routing_counter.get("drop_from_positive_roles", 0)),
        "role_eligibility_breakdown": role_eligibility_breakdown,
        "risk_flag_breakdown": dict(sorted(risk_flag_counter.items())),
        "forbidden_seed_field_hits": forbidden_seed_hits,
        "forbidden_pack_field_hits": forbidden_pack_hits,
        "duplicate_candidate_id_count": duplicate_candidate_id_count,
    }


def load_candidate_bank_rows(
    *,
    stage1_set_manifest: str | None = None,
    candidate_bank_jsonl: str | None = None,
    exact_kc_ids: Sequence[str] | None = None,
    limit_kcs: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    manifest_spec: Optional[InputSpec] = None
    manifest_obj: Dict[str, Any] = {}
    if stage1_set_manifest:
        manifest_spec = parse_input_spec(stage1_set_manifest, repo_root=REPO_ROOT)
        if not input_spec_exists(manifest_spec):
            raise FileNotFoundError(f"Stage 1 set manifest not found: {manifest_spec.display()}")
        manifest_obj = read_json_from_spec(manifest_spec)

    candidate_spec: Optional[InputSpec] = None
    if candidate_bank_jsonl:
        candidate_spec = resolve_related_input_spec(candidate_bank_jsonl, repo_root=REPO_ROOT, base_spec=manifest_spec)
    elif manifest_spec is not None:
        artifacts = manifest_obj.get("artifacts") or {}
        raw_jsonl = artifacts.get("candidate_bank_jsonl")
        if not raw_jsonl:
            raise RuntimeError(f"Stage 1 set manifest missing candidate_bank_jsonl: {manifest_spec.display()}")
        candidate_spec = resolve_related_input_spec(raw_jsonl, repo_root=REPO_ROOT, base_spec=manifest_spec)
    else:
        raise RuntimeError("Either stage1_set_manifest or candidate_bank_jsonl must be provided.")

    if candidate_spec is None or not input_spec_exists(candidate_spec):
        raise FileNotFoundError("Resolved Stage 1 candidate bank JSONL does not exist.")

    rows = read_jsonl_from_spec(candidate_spec)
    kc_filter = [str(kc_id) for kc_id in exact_kc_ids or [] if str(kc_id).strip()]
    if kc_filter:
        by_kc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_kc[_as_text(row.get("kc_id"))].append(dict(row))
        missing = [kc_id for kc_id in kc_filter if kc_id not in by_kc]
        if missing:
            # Zero-candidate KCs are valid in clean-slate evidence retrieval.
            # A requested KC may have no Stage 1 candidates because retrieval failed,
            # not because the KC is unknown or corpus-insufficient.
            # Keep available rows and let downstream pack composition represent
            # missing KCs as insufficient-support / zero-candidate cases.
            pass
        filtered: List[Dict[str, Any]] = []
        for kc_id in kc_filter:
            filtered.extend(by_kc[kc_id])
        rows = filtered
    elif limit_kcs is not None:
        seen_order = unique_preserve_order([_as_text(row.get("kc_id")) for row in rows])
        allowed = set(seen_order[: int(limit_kcs)])
        rows = [dict(row) for row in rows if _as_text(row.get("kc_id")) in allowed]
    else:
        rows = [dict(row) for row in rows]

    info = {
        "stage1_set_manifest": manifest_spec.display() if manifest_spec is not None else "",
        "candidate_bank_jsonl": candidate_spec.display(),
        "stage1_manifest_obj": manifest_obj,
        "source_manifest": manifest_spec.display() if manifest_spec is not None else candidate_spec.display(),
        "exact_kc_ids": kc_filter,
        "limit_kcs": limit_kcs,
    }
    return rows, info


def build_scored_candidate_artifacts(
    candidate_rows: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    source_manifest: str,
    candidate_bank_jsonl_path: str,
    config_path: str | None = None,
    exact_kc_ids: Sequence[str] | None = None,
    limit_kcs: int | None = None,
    cfg: Mapping[str, Any] | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    set_manifest_root: str | Path | None = None,
) -> dict[str, Any]:
    rows = score_candidate_rows(candidate_rows, cfg=cfg)
    paths = _materialize_run_paths(
        output_root=resolve_repo_path(output_root, repo_root=REPO_ROOT),
        set_manifest_root=resolve_repo_path(set_manifest_root or DEFAULT_SET_MANIFEST_ROOT, repo_root=REPO_ROOT),
        run_id=run_id,
    )
    chosen_run_id = str(paths["run_id"])
    processed_dir = paths["processed_dir"]
    set_manifest_path = paths["set_manifest_path"]
    processed_dir.mkdir(parents=True, exist_ok=False)
    set_manifest_path.parent.mkdir(parents=True, exist_ok=True)

    scored_rows: List[Dict[str, Any]] = []
    for row in rows:
        updated = dict(row)
        updated["run_id"] = chosen_run_id
        updated["source_manifest"] = source_manifest
        updated["source_surface"] = SOURCE_SURFACE_STAGE2
        scored_rows.append(updated)

    # Formula and procedure evidence characteristically does not restate the unit name, so the
    # lexical target-binding contract zeroed those roles wholesale (measured: 0 procedure and 18
    # formula items admitted library-wide, against 1183 and 1759 candidates clearing their role
    # score thresholds). Bind them structurally instead - co-location in the same source patch as
    # an already-validated target-bound positive for the SAME unit. Runs as a second pass because
    # it needs a cross-candidate view that per-row scoring does not have.
    structural_role_anchor_stats = apply_structural_role_anchoring(
        scored_rows,
        thresholds=default_scoring_cfg(cfg).get("role_score_thresholds") if isinstance(cfg, dict) else None,
        readmit=decide_evidence_admission,
    )

    scored_candidates_jsonl = processed_dir / "scored_candidates.jsonl"
    scored_candidate_stats_json = processed_dir / "scored_candidate_stats.json"
    scored_candidate_schema_snapshot_json = processed_dir / "scored_candidate_schema_snapshot.json"
    scored_candidate_manifest_json = processed_dir / "scored_candidate_manifest.json"

    stats = _stats_for_rows(scored_rows, run_id=chosen_run_id, source_manifest=source_manifest)
    schema_snapshot = _schema_snapshot(scored_rows, run_id=chosen_run_id, source_manifest=source_manifest)

    write_jsonl(scored_candidates_jsonl, scored_rows)
    write_json(scored_candidate_stats_json, stats)
    write_json(scored_candidate_schema_snapshot_json, schema_snapshot)

    scored_candidate_manifest = {
        "run_id": chosen_run_id,
        "stage": "step5x_v3_scored_candidates",
        "created_at": now_utc_iso(),
        "inputs": {
            "candidate_bank_set_manifest": source_manifest,
            "candidate_bank_jsonl": candidate_bank_jsonl_path,
            "config_path": str(config_path or ""),
            "exact_kc_ids": [str(kc_id) for kc_id in exact_kc_ids or []],
            "limit_kcs": limit_kcs,
        },
        "artifacts": {
            "scored_candidates_jsonl": _stringify_path(scored_candidates_jsonl),
            "scored_candidate_stats_json": _stringify_path(scored_candidate_stats_json),
            "scored_candidate_schema_snapshot_json": _stringify_path(scored_candidate_schema_snapshot_json),
            "scored_candidate_manifest_json": _stringify_path(scored_candidate_manifest_json),
        },
        "compatibility": {
            "step6_6_ready": False,
            "step6_7_contract_changed": False,
        },
        "environment": {
            "env_snapshot": env_snapshot(),
            "python_version": try_cmd_version(["python", "--version"]),
        },
    }
    write_json(scored_candidate_manifest_json, scored_candidate_manifest)

    set_manifest = {
        "run_id": chosen_run_id,
        "stage": "step5x_v3_scored_candidates",
        "created_at": now_utc_iso(),
        "inputs": {
            "candidate_bank_set_manifest": source_manifest,
            "candidate_bank_jsonl": candidate_bank_jsonl_path,
            "config_path": str(config_path or ""),
            "exact_kc_ids": [str(kc_id) for kc_id in exact_kc_ids or []],
            "limit_kcs": limit_kcs,
        },
        "artifacts": {
            "scored_candidates_jsonl": _stringify_path(scored_candidates_jsonl),
            "scored_candidate_stats_json": _stringify_path(scored_candidate_stats_json),
            "scored_candidate_schema_snapshot_json": _stringify_path(scored_candidate_schema_snapshot_json),
            "scored_candidate_manifest_json": _stringify_path(scored_candidate_manifest_json),
        },
        "compatibility": {
            "step6_6_ready": False,
            "step6_7_contract_changed": False,
        },
    }
    write_json(set_manifest_path, set_manifest)

    output_manifest_path = processed_dir / "output_manifest.json"
    write_json(output_manifest_path, build_output_manifest(processed_dir))

    return {
        "run_id": chosen_run_id,
        "processed_dir": _stringify_path(processed_dir),
        "set_manifest": _stringify_path(set_manifest_path),
        "scored_candidates_jsonl": _stringify_path(scored_candidates_jsonl),
        "scored_candidate_stats_json": _stringify_path(scored_candidate_stats_json),
        "scored_candidate_schema_snapshot_json": _stringify_path(scored_candidate_schema_snapshot_json),
        "scored_candidate_manifest_json": _stringify_path(scored_candidate_manifest_json),
        "total_scored_candidates_emitted": len(scored_rows),
    }


__all__ = [
    "ALL_ROLES",
    "DEFAULT_OUTPUT_ROOT",
    "DEFAULT_SET_MANIFEST_ROOT",
    "FORBIDDEN_PACK_FIELDS",
    "FORBIDDEN_SEED_FIELDS",
    "POSITIVE_ROLES",
    "SCORED_CANDIDATE_CONTRACT_VERSION",
    "SOURCE_SURFACE_STAGE2",
    "build_scored_candidate_artifacts",
    "default_scoring_cfg",
    "load_candidate_bank_rows",
    "score_candidate_row",
    "score_candidate_rows",
]
