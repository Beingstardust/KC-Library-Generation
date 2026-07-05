from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Sequence

from .semantic import match_normalize, normalize_ws, tokenize

ROLE_LABEL_VALUES = ("definition", "equation", "procedure", "example", "warning", "other")
ROLE_PRIORITY = {"definition": 0, "equation": 1, "procedure": 2, "example": 3, "warning": 4, "other": 5}
SUPPORT_ROLE_VALUES = (
    "definitional_anchor",
    "explanatory_anchor",
    "formula_or_parameter_anchor",
    "context_completion_anchor",
    "contamination_or_sibling_exclusion",
    "other",
)
FORMULA_RE = re.compile(r"(?:=|\\sum|\\log|\\sqrt|∑|Σ|sqrt|log\s*\(|p\s*\(|P\s*\()")
NUMBERED_STEP_RE = re.compile(r"^\s*(?:\d+[\.\)]|[-*])\s+")
IF_THEN_RE = re.compile(r"\bif\b.*\bthen\b")
DEFINITION_LINK_RE = re.compile(r"\b(?:is|are|defined as|refers to|means|called|denote|denotes)\b\s*[:=]?")
FRAGMENT_PREFIXES = ("where ", "for ", "given ", "if ", "let ", "when ")
GENERIC_CONTEXT_PREFIXES = ("for example", "for instance", "example", "note that", "consider ")


def default_role_cfg(cfg: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    source = dict(cfg or {})
    return {
        "definition_cues": [
            str(item)
            for item in source.get("definition_cues")
            or [" is ", " defined as ", " we call ", " denote", " denotes", " means ", " called ", " refers to "]
        ],
        "procedure_cues": [str(item) for item in source.get("procedure_cues") or ["algorithm", "procedure", "step", "repeat", "compute", "for each", "first", "second", "third"]],
        "example_cues": [str(item) for item in source.get("example_cues") or ["example", "for example", "e.g."]],
        "warning_cues": [str(item) for item in source.get("warning_cues") or ["warning", "pitfall", "note", "incorrect", "wrong", "avoid"]],
        "weak_score_threshold": float(source.get("weak_score_threshold", 1.75)),
        "ambiguity_gap_threshold": float(source.get("ambiguity_gap_threshold", 0.9)),
        "dominant_score_threshold": float(source.get("dominant_score_threshold", 3.0)),
        "dominant_gap_threshold": float(source.get("dominant_gap_threshold", 1.25)),
        "strong_definition_score": float(source.get("strong_definition_score", 2.5)),
    }


def _candidate_bool(candidate: Any, field_name: str) -> bool:
    return bool(getattr(candidate, field_name, False))


def _candidate_int(candidate: Any, field_name: str) -> int:
    try:
        return int(getattr(candidate, field_name, 0) or 0)
    except Exception:
        return 0


def _candidate_flags(candidate: Any) -> Mapping[str, bool]:
    flags = getattr(candidate, "sentence_flags", {})
    return flags if isinstance(flags, Mapping) else {}


def score_quote_roles(
    *,
    quote: str,
    canonical_name: str,
    aliases: Sequence[str],
    candidate: Any,
    cfg: Mapping[str, Any] | None = None,
) -> Dict[str, float]:
    role_cfg = default_role_cfg(cfg)
    text = normalize_ws(quote)
    lower = match_normalize(text)
    tokens = set(tokenize(lower, min_len=2))
    canonical_tokens = set(tokenize(match_normalize(canonical_name), min_len=2))
    alias_tokens = {token for alias in aliases for token in tokenize(match_normalize(alias), min_len=2)}
    overlap = len(tokens & (canonical_tokens | alias_tokens))
    flags = _candidate_flags(candidate)

    scores = {role: 0.0 for role in ROLE_LABEL_VALUES}
    scores["other"] = 0.25

    if overlap:
        scores["definition"] += min(3.0, 0.75 * overlap)
    if _candidate_bool(candidate, "exact_name_phrase") or _candidate_bool(candidate, "exact_alias_phrase"):
        scores["definition"] += 2.5
    for cue in role_cfg["definition_cues"]:
        if cue and cue in lower:
            scores["definition"] += 1.5
    if DEFINITION_LINK_RE.search(lower):
        scores["definition"] += 1.25
    if flags.get("is_definition_like"):
        scores["definition"] += 1.25
    if flags.get("is_heading_like") and overlap:
        scores["definition"] += 0.5

    if FORMULA_RE.search(text):
        scores["equation"] += 4.0
    if any(token in text for token in ["$", "{", "}", "<=", ">=", "->"]):
        scores["equation"] += 1.5
    if flags.get("is_formula_like"):
        scores["equation"] += 1.25

    if NUMBERED_STEP_RE.search(text):
        scores["procedure"] += 2.5
    if IF_THEN_RE.search(lower):
        scores["procedure"] += 2.0
    if any(cue in lower for cue in role_cfg["procedure_cues"]):
        scores["procedure"] += 1.5
    if any(token in lower for token in ["input:", "output:", "invoke", "return", "else", "repeat", "until"]):
        scores["procedure"] += 1.5
    if flags.get("is_procedure_like"):
        scores["procedure"] += 1.25

    if any(cue in lower for cue in role_cfg["example_cues"]):
        scores["example"] += 2.5
    if flags.get("is_example_like"):
        scores["example"] += 1.25

    if any(cue in lower for cue in role_cfg["warning_cues"]):
        scores["warning"] += 2.5

    if max(scores.values()) <= scores["other"]:
        scores["other"] += 0.5
    return scores


def analyze_quote_role(
    *,
    quote: str,
    canonical_name: str,
    aliases: Sequence[str],
    candidate: Any,
    cfg: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    role_cfg = default_role_cfg(cfg)
    scores = score_quote_roles(quote=quote, canonical_name=canonical_name, aliases=aliases, candidate=candidate, cfg=role_cfg)
    ordered = sorted(scores.items(), key=lambda item: (-float(item[1]), ROLE_PRIORITY.get(str(item[0]), 99), str(item[0])))
    top_role, top_score = ordered[0]
    second_role, second_score = ordered[1]
    gap = float(top_score) - float(second_score)
    dominant = (
        str(top_role) != "other"
        and float(top_score) >= float(role_cfg["dominant_score_threshold"])
        and gap >= float(role_cfg["dominant_gap_threshold"])
    )
    ambiguous = (not dominant) and (
        str(top_role) == "other"
        or float(top_score) < float(role_cfg["weak_score_threshold"])
        or gap <= float(role_cfg["ambiguity_gap_threshold"])
    )
    ambiguity_reason = ""
    if dominant:
        ambiguity_reason = ""
    elif str(top_role) == "other":
        ambiguity_reason = "top_role_other"
    elif float(top_score) < float(role_cfg["weak_score_threshold"]):
        ambiguity_reason = "weak_top_score"
    elif gap <= float(role_cfg["ambiguity_gap_threshold"]):
        ambiguity_reason = "top_two_close"
    return {
        "scores": {str(key): float(value) for key, value in scores.items()},
        "top_role": str(top_role),
        "top_score": float(top_score),
        "second_role": str(second_role),
        "second_score": float(second_score),
        "dominant": dominant,
        "ambiguous": ambiguous,
        "ambiguity_reason": ambiguity_reason,
        "strong_definition_or_equation": max(float(scores["definition"]), float(scores["equation"])) >= float(role_cfg["strong_definition_score"]),
    }


def analyze_support_readiness(
    *,
    quote: str,
    source_block_text: str,
    canonical_name: str,
    aliases: Sequence[str],
    candidate: Any,
    cfg: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    role_cfg = default_role_cfg(cfg)
    role_analysis = analyze_quote_role(
        quote=quote,
        canonical_name=canonical_name,
        aliases=aliases,
        candidate=candidate,
        cfg=role_cfg,
    )
    text = normalize_ws(quote)
    source_text = normalize_ws(source_block_text or quote)
    lower = match_normalize(text)
    source_lower = match_normalize(source_text)
    token_count = len(tokenize(lower, min_len=2))
    flags = _candidate_flags(candidate)
    exact_name_phrase = _candidate_bool(candidate, "exact_name_phrase")
    exact_alias_phrase = _candidate_bool(candidate, "exact_alias_phrase")
    context_keyword_hits = _candidate_int(candidate, "context_keyword_hits")
    heading_name_hits = _candidate_int(candidate, "heading_name_hits")
    competitor_token_hits = _candidate_int(candidate, "competitor_token_hits")
    doc_mismatch = _candidate_bool(candidate, "doc_mismatch")
    hard_suppressed = _candidate_bool(candidate, "hard_suppressed")
    formula_like = bool(flags.get("is_formula_like")) or FORMULA_RE.search(text) is not None
    procedure_like = bool(flags.get("is_procedure_like"))
    example_like = bool(flags.get("is_example_like"))
    relation_like = bool(DEFINITION_LINK_RE.search(lower))
    compact_equation_surface = bool(formula_like and "=" in text and token_count <= 10)
    starts_fragment = any(lower.startswith(prefix) for prefix in FRAGMENT_PREFIXES)
    generic_context_only = any(lower.startswith(prefix) for prefix in GENERIC_CONTEXT_PREFIXES)
    trailing_fragment = lower.endswith((":", "=", " where", " which", " that", " such that"))
    fragmentary = bool(
        starts_fragment
        or trailing_fragment
        or (token_count < 8 and not relation_like)
        or (formula_like and token_count <= 10 and not relation_like)
    )
    source_has_completion = bool(
        source_text
        and source_text != text
        and len(source_text) >= len(text) + 20
        and (
            DEFINITION_LINK_RE.search(source_lower) is not None
            or role_analysis["scores"]["definition"] >= float(role_cfg["strong_definition_score"])
            or (exact_name_phrase or exact_alias_phrase)
        )
    )

    definition_anchor_score = float(role_analysis["scores"]["definition"])
    definition_anchor_score += 1.25 if relation_like else 0.0
    definition_anchor_score += 1.0 if exact_name_phrase or exact_alias_phrase else 0.0
    definition_anchor_score += 0.5 * min(2, context_keyword_hits)
    definition_anchor_score += 0.35 * min(2, heading_name_hits)
    definition_anchor_score -= 1.5 if example_like and not relation_like else 0.0
    definition_anchor_score -= 1.25 if procedure_like and not relation_like else 0.0
    definition_anchor_score -= 1.0 if formula_like and not relation_like else 0.0

    explanatory_anchor_score = float(role_analysis["scores"]["definition"]) * 0.55
    explanatory_anchor_score += 1.5 if source_has_completion else 0.0
    explanatory_anchor_score += 1.0 if token_count >= 10 and not formula_like else 0.0
    explanatory_anchor_score += 0.5 * min(2, context_keyword_hits)
    explanatory_anchor_score -= 1.0 if generic_context_only else 0.0
    explanatory_anchor_score -= 1.0 if example_like and not relation_like else 0.0

    formula_support_score = float(role_analysis["scores"]["equation"])
    formula_support_score += 0.75 if relation_like else 0.0
    formula_support_score += 0.5 if source_has_completion else 0.0

    context_completion_score = 0.0
    context_completion_score += 3.0 if fragmentary and source_has_completion else 0.0
    context_completion_score += 1.0 if fragmentary and relation_like else 0.0
    context_completion_score += 0.5 if fragmentary and formula_like and source_has_completion else 0.0

    contamination_penalty = 0.0
    contamination_penalty += 2.0 if competitor_token_hits >= 2 else 0.0
    contamination_penalty += 1.5 if doc_mismatch else 0.0
    contamination_penalty += 2.5 if hard_suppressed else 0.0
    contamination_penalty += 0.75 if generic_context_only else 0.0

    formula_auxiliary_only = bool(
        formula_like
        and (
            compact_equation_surface
            or not relation_like
            or definition_anchor_score < max(4.0, float(role_cfg["strong_definition_score"]))
        )
        and not source_has_completion
    )
    contamination_exclusion_hint = bool(
        contamination_penalty >= 2.0
        or (competitor_token_hits >= 1 and not (exact_name_phrase or exact_alias_phrase))
    )

    preferred_support_role = "other"
    if definition_anchor_score >= max(explanatory_anchor_score, 4.5) and not formula_auxiliary_only:
        preferred_support_role = "definitional_anchor"
    elif context_completion_score >= 2.5:
        preferred_support_role = "context_completion_anchor"
    elif explanatory_anchor_score >= 3.0 and not formula_auxiliary_only:
        preferred_support_role = "explanatory_anchor"
    elif formula_support_score >= 4.0:
        preferred_support_role = "formula_or_parameter_anchor"
    elif contamination_exclusion_hint:
        preferred_support_role = "contamination_or_sibling_exclusion"

    anchor_quality = "weak"
    if preferred_support_role == "definitional_anchor" and definition_anchor_score >= 6.0 and contamination_penalty < 2.0:
        anchor_quality = "strong"
    elif preferred_support_role in {"definitional_anchor", "explanatory_anchor", "context_completion_anchor"} and max(
        definition_anchor_score,
        explanatory_anchor_score,
        context_completion_score,
    ) >= 4.0:
        anchor_quality = "usable"

    support_roles = [preferred_support_role]
    if source_has_completion and "context_completion_anchor" not in support_roles:
        support_roles.append("context_completion_anchor")
    if formula_support_score >= 4.0 and "formula_or_parameter_anchor" not in support_roles:
        support_roles.append("formula_or_parameter_anchor")
    if contamination_exclusion_hint and "contamination_or_sibling_exclusion" not in support_roles:
        support_roles.append("contamination_or_sibling_exclusion")

    return {
        "support_roles": [role for role in SUPPORT_ROLE_VALUES if role in support_roles],
        "preferred_support_role": preferred_support_role,
        "definition_anchor_score": round(definition_anchor_score, 6),
        "explanatory_anchor_score": round(explanatory_anchor_score, 6),
        "formula_support_score": round(formula_support_score, 6),
        "context_completion_score": round(context_completion_score, 6),
        "contamination_penalty": round(contamination_penalty, 6),
        "anchor_quality": anchor_quality,
        "needs_context_completion": bool(fragmentary and source_has_completion),
        "has_context_completion_source": bool(source_has_completion),
        "formula_auxiliary_only": formula_auxiliary_only,
        "contamination_exclusion_hint": contamination_exclusion_hint,
        "relation_like": relation_like,
        "generic_context_only": generic_context_only,
        "fragmentary_surface": fragmentary,
        "source_block_completion_used": bool(source_has_completion and source_text != text),
    }
