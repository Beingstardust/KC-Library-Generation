from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Sequence

from .semantic import match_normalize, normalize_ws, tokenize

ROLE_LABEL_VALUES = ("definition", "equation", "procedure", "example", "warning", "other")
ROLE_PRIORITY = {"definition": 0, "equation": 1, "procedure": 2, "example": 3, "warning": 4, "other": 5}
FORMULA_RE = re.compile(r"(?:=|\\sum|\\log|\\sqrt|∑|Σ|sqrt|log\s*\(|p\s*\(|P\s*\()")
NUMBERED_STEP_RE = re.compile(r"^\s*(?:\d+[\.\)]|[-*])\s+")
IF_THEN_RE = re.compile(r"\bif\b.*\bthen\b")
DEFINITION_LINK_RE = re.compile(r"\b(?:is|are|defined as|refers to|means|called|denote|denotes)\b\s*[:=]?")


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
