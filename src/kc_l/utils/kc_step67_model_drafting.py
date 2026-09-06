from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from kc_l.kc_drafting.model_profile import (
    apply_step67_model_profile_to_messages,
    normalize_step67_model_profile,
    step67_model_profile_think_flag,
)
from kc_l.kc_drafting.contracts import (
    AUTHORITATIVE_DEFINITION_STATUS_INSUFFICIENT_SUPPORT,
    AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED,
    AUTHORITATIVE_DEFINITION_STATUS_NORMALIZED_GROUNDED,
    COVERAGE_STATE_STATUS_REPRESENTED,
    CONTEXT_LAYER_STATUS_FALLBACK,
    CONTEXT_LAYER_STATUS_GROUNDED,
    CONTEXT_LAYER_STATUS_MISSING,
    ENRICHMENT_LAYER_STATUS_GROUNDED,
    ENRICHMENT_LAYER_STATUS_MISSING,
    REVIEW_READINESS_COVERAGE_ONLY,
    REVIEW_READINESS_NEEDS_ATTENTION,
    REVIEW_READINESS_READY,
    SCOPE_LAYER_STATUS_ABSTAINED,
    SCOPE_LAYER_STATUS_GROUNDED,
    STEP67_SEMANTIC_CONTRACT_VERSION,
    TRUST_STATE_COVERAGE_ONLY,
    TRUST_STATE_COVERAGE_ONLY_WITH_RISKS,
    TRUST_STATE_GROUNDED,
    TRUST_STATE_GROUNDED_WITH_GAPS,
    compatibility_draft_status,
    attach_kc_specific_criteria_placeholder,
)
from kc_l.kc_drafting.hierarchy_refs import typed_topic_hierarchy_fields
from kc_l.kc_drafting.heuristic_core import (
    DEFINITION_EVIDENCE_PACKET_ROLES,
    DRAFT_CONTRACT_VERSION,
    REVIEWER_BUNDLE_BLOCK_REASONS,
    _abstained_value,
    _candidate_source_text_field,
    _candidate_value,
    _definition_alignment_features,
    _definition_candidate_choice_score,
    _definition_candidate_entries,
    _definition_candidate_verdict,
    _definition_extended_issue_codes,
    _field_provenance,
    _selected_grounded_scope_support,
    _support_summary,
    assess_overlay_candidate,
    build_definition_evidence_packet,
    select_evidence_bundle,
    select_definition_support_pack,
    selected_definition_review_quality,
)
from kc_l.retrieval_gate.semantic import unique_preserve_order
from kc_l.retrieval_gate.evidence_stage_v3_lane_semantics import has_automatic_drafting_support
from kc_l.utils.ollama_json import ollama_chat_json


MODEL_DRAFTING_MODE = "llm_multispan_grounded_v1"
DEFINITION_GENERATION_MODE_LEGACY = "legacy_joint_draft_v1"
DEFINITION_GENERATION_MODE_PACKET_MULTICANDIDATE = "packet_multicandidate_v1"
COVERAGE_ONLY_ACTIVE_FLAG = "coverage_only_active"
DEFINITION_ENRICHMENT_MISSING_FLAG = "definition_enrichment_missing"
CONTEXT_FALLBACK_ACTIVE_FLAG = "context_fallback_active"
CONTEXT_BUNDLE_MISSING_FLAG = "context_bundle_missing"
LOW_TRUST_SURVIVOR_FLAG = "coverage_only_survivor"
REVIEW_NEEDS_ATTENTION_FLAG = "review_needs_attention"
LOW_TRUST_REVIEW_FLAG = "coverage_only_review"
SELECTED_DEFINITION_SURFACE_REVIEW_SUPPRESSED_FLAG = "selected_definition_surface_review_suppressed"


@dataclass(frozen=True)
class Step67ModelRuntime:
    base_url: str
    model: str
    max_retries: int = 3
    num_ctx: int = 8192
    timeout_seconds: float = 180.0
    temperature: float = 0.0
    top_p: float = 1.0
    repeat_penalty: float = 1.0
    think: Optional[bool] = False
    model_profile: Mapping[str, Any] = field(default_factory=dict)
    draft_invoker: Optional[Callable[[Dict[str, Any]], Any]] = None
    verify_invoker: Optional[Callable[[Dict[str, Any]], Any]] = None


@dataclass(frozen=True)
class Step67DraftingPolicy:
    definition_candidate_limit: int = 5
    scope_candidate_limit: int = 5
    family_context_limit: int = 4
    completion_context_limit: int = 4
    evidence_text_max_chars: int = 320
    max_bundle_size: int = 6
    max_explanatory_candidates: int = 5
    short_definition_max_chars: int = 220
    short_definition_max_tokens: int = 32
    max_definition_binding_support_rows: int = 2
    max_llm_calls_per_kc: int = 8
    definition_generation_mode: str = DEFINITION_GENERATION_MODE_LEGACY


@dataclass(frozen=True)
class FieldCandidate:
    overlay_candidate_id: str
    score: float
    text: str
    source_text_field: str
    candidate_kind: str
    row: Dict[str, Any]
    assessment: Dict[str, Any]
    issues: Tuple[str, ...]
    has_name_anchor: bool
    title_overlap: int
    context_overlap: int
    single_span_accepted: bool


class LLMCallBudgetExceededError(RuntimeError):
    """Raised when a single KC exceeds the explicit Step 6.7 LLM call budget."""


def _normalize_ws(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _new_kc_llm_budget_state(max_calls: int) -> Dict[str, Any]:
    bounded_max_calls = max(1, int(max_calls))
    return {
        "max_calls": bounded_max_calls,
        "calls_used": 0,
        "remaining_calls": bounded_max_calls,
        "phase_call_order": [],
        "phase_call_counts": {},
        "blocked_phases": [],
        "budget_exhausted": False,
    }


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9]+", str(text or "").lower())


def _clip_text(text: str, max_chars: int) -> str:
    cleaned = _normalize_ws(text)
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max(0, max_chars - 3)].rstrip() + "..."


def _text_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _normalize_ws(text).lower())


def _candidate_tokens(text: str) -> int:
    return len(_tokenize(text))


CONTENT_STOPWORDS: set[str] = {
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
    "given",
    "if",
    "iff",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "such",
    "that",
    "the",
    "there",
    "to",
    "with",
}


def _content_tokens(text: Any) -> List[str]:
    return [token for token in _tokenize(str(text or "")) if len(token) > 1 and token not in CONTENT_STOPWORDS]


def _content_token_set(text: Any) -> set[str]:
    return set(_content_tokens(text))


def _family_group_key(exemplar: Mapping[str, Any]) -> str:
    parent_hier_node_id = str(exemplar.get("parent_hier_node_id") or "").strip()
    if parent_hier_node_id:
        return f"parent::{parent_hier_node_id}"
    source_hierarchy_path = [str(item).strip() for item in exemplar.get("source_hierarchy_path") or [] if str(item).strip()]
    if len(source_hierarchy_path) > 1:
        return f"path::{' > '.join(source_hierarchy_path[:-1]).lower()}"
    return ""


def _descriptor_context_items(exemplar: Mapping[str, Any]) -> List[str]:
    canonical_name = _normalize_ws(exemplar.get("canonical_name") or "")
    aliases = [_normalize_ws(item) for item in exemplar.get("aliases") or [] if _normalize_ws(item)]
    blocked = {item.lower() for item in [canonical_name, *aliases] if item}
    hierarchy_items = [
        _normalize_ws(item)
        for item in exemplar.get("source_hierarchy_path") or exemplar.get("ancestor_labels") or []
        if _normalize_ws(item)
    ]
    return [item for item in hierarchy_items if item.lower() not in blocked]


def _descriptor_context_text(exemplar: Mapping[str, Any]) -> str:
    return " ; ".join(_descriptor_context_items(exemplar))


def _kc_descriptor(exemplar: Mapping[str, Any]) -> Dict[str, Any]:
    canonical_name = _normalize_ws(exemplar.get("canonical_name") or "")
    aliases = [_normalize_ws(item) for item in exemplar.get("aliases") or [] if _normalize_ws(item)]
    descriptor_context = _descriptor_context_text(exemplar)
    phrases = [phrase.lower() for phrase in [canonical_name, *aliases] if phrase]
    return {
        "kc_id": str(exemplar.get("kc_id") or ""),
        "canonical_name": canonical_name,
        "aliases": aliases,
        "hierarchy_context": _descriptor_context_items(exemplar),
        "family_group_key": _family_group_key(exemplar),
        "name_tokens": _content_token_set(" ".join([canonical_name, *aliases])),
        "context_tokens": _content_token_set(descriptor_context),
        "name_phrases": phrases,
    }


def _descriptor_alignment(text: str, descriptor: Mapping[str, Any]) -> Dict[str, Any]:
    normalized = _normalize_ws(text).lower()
    candidate_tokens = _content_token_set(text)
    name_tokens = set(descriptor.get("name_tokens") or set())
    context_tokens = set(descriptor.get("context_tokens") or set())
    name_overlap = len(candidate_tokens & name_tokens)
    context_overlap = len(candidate_tokens & context_tokens)
    exact_name_phrase = any(str(phrase) and str(phrase) in normalized for phrase in descriptor.get("name_phrases") or [])
    score = (4.0 if exact_name_phrase else 0.0) + (3.0 * float(name_overlap)) + (1.5 * float(context_overlap))
    return {
        "score": round(score, 6),
        "name_overlap": int(name_overlap),
        "context_overlap": int(context_overlap),
        "context_overlap": int(context_overlap),
        "exact_name_phrase": bool(exact_name_phrase),
    }


def _contrastive_alignment(
    text: str,
    *,
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    target_profile = _descriptor_alignment(text, target_descriptor)
    best_sibling_profile: Dict[str, Any] = {"score": 0.0, "name_overlap": 0, "context_overlap": 0, "exact_name_phrase": False}
    best_sibling_descriptor: Dict[str, Any] = {}
    for sibling_descriptor in sibling_descriptors:
        profile = _descriptor_alignment(text, sibling_descriptor)
        if float(profile.get("score") or 0.0) > float(best_sibling_profile.get("score") or 0.0):
            best_sibling_profile = profile
            best_sibling_descriptor = dict(sibling_descriptor)
    sibling_margin = float(best_sibling_profile.get("score") or 0.0) - float(target_profile.get("score") or 0.0)
    return {
        "target": target_profile,
        "best_sibling": best_sibling_profile,
        "best_sibling_descriptor": best_sibling_descriptor,
        "sibling_margin": round(sibling_margin, 6),
    }


def _sibling_boundary_risk(
    text: str,
    *,
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
) -> bool:
    if not text or not sibling_descriptors:
        return False
    alignment = _contrastive_alignment(
        text,
        target_descriptor=target_descriptor,
        sibling_descriptors=sibling_descriptors,
    )
    target_profile = dict(alignment.get("target") or {})
    best_sibling_profile = dict(alignment.get("best_sibling") or {})
    sibling_margin = float(alignment.get("sibling_margin") or 0.0)
    if float(best_sibling_profile.get("score") or 0.0) <= 0.0:
        return False
    if sibling_margin >= 4.0:
        return True
    if (
        bool(best_sibling_profile.get("exact_name_phrase"))
        and not bool(target_profile.get("exact_name_phrase"))
        and sibling_margin >= 1.5
    ):
        return True
    lowered = f" {_normalize_ws(text).lower()} "
    if " for each " in lowered and " iff " not in lowered and " if and only if " not in lowered and sibling_margin >= 1.0:
        return True
    return False


def _sibling_descriptor_payloads(
    sibling_descriptors: Sequence[Mapping[str, Any]],
    *,
    limit: int = 4,
) -> List[Dict[str, str]]:
    payloads: List[Dict[str, str]] = []
    for descriptor in sibling_descriptors[: max(0, int(limit))]:
        payloads.append(
            {
                "kc_id": str(descriptor.get("kc_id") or ""),
                "canonical_name": str(descriptor.get("canonical_name") or ""),
                "hierarchy_context": [str(item) for item in descriptor.get("hierarchy_context") or [] if str(item)],
            }
        )
    return payloads


def _descriptor_payload(descriptor: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "kc_id": str(descriptor.get("kc_id") or ""),
        "canonical_name": str(descriptor.get("canonical_name") or ""),
        "aliases": [str(item) for item in descriptor.get("aliases") or []],
        "hierarchy_context": [str(item) for item in descriptor.get("hierarchy_context") or [] if str(item)],
        "family_group_key": str(descriptor.get("family_group_key") or ""),
    }


def _kc_prompt_payload(exemplar: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "kc_id": str(exemplar.get("kc_id") or ""),
        "canonical_name": str(exemplar.get("canonical_name") or ""),
        "aliases": [str(item) for item in exemplar.get("aliases") or []],
        "ancestor_labels": [str(item) for item in exemplar.get("ancestor_labels") or []],
        "source_hierarchy_path": [str(item) for item in exemplar.get("source_hierarchy_path") or []],
        "hierarchy_context": _descriptor_context_items(exemplar),
    }


def _row_source_relation(row: Mapping[str, Any], *, target_kc_id: str) -> str:
    return "local" if str(row.get("kc_id") or "") == str(target_kc_id or "") else "family_context"


def _clean_completion_segment(text: str) -> str:
    cleaned = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]+", " ", str(text or ""))
    cleaned = _normalize_ws(cleaned)
    cleaned = re.sub(r"^[\u2022\u00b7:;,\-]+\s*", "", cleaned)
    return cleaned


SCOPE_EXPLANATION_CUES: Tuple[str, ...] = (
    " can be used ",
    " used for ",
    " used when ",
    " useful for ",
    " applies to ",
    " applicable ",
    " interpreted ",
    " interpretation ",
    " indicates ",
    " means ",
    " describes ",
    " captures ",
    " measures ",
    " tests whether ",
    " compares ",
    " computed on ",
    " based on ",
    " provided that ",
    " requires ",
    " split ",
    " training ",
    " testing ",
    " aggregate ",
    " within ",
    " around ",
)

SCOPE_GENERIC_LEAD_IN_PATTERNS: Tuple[re.Pattern[str], ...] = (
    re.compile(r"^given\s+(?:is|are)\b", flags=re.IGNORECASE),
    re.compile(r"^let\b", flags=re.IGNORECASE),
)

DEFINITION_FALLBACK_START_PATTERNS: Tuple[re.Pattern[str], ...] = (
    re.compile(r"^(?:figure|table|algorithm|input)\b", flags=re.IGNORECASE),
    re.compile(r"^[0-9]+[.)]\s"),
    re.compile(r"^for each\b", flags=re.IGNORECASE),
    re.compile(r"^(?:then|where|when)\b", flags=re.IGNORECASE),
)

DEFINITION_CONTEXTUAL_SCAFFOLD_START_PATTERNS: Tuple[re.Pattern[str], ...] = (
    re.compile(r"^(?:for|given|let)\b", flags=re.IGNORECASE),
)

DEFINITION_RELATION_CUES: Tuple[str, ...] = (
    " iff ",
    " if and only if ",
    " defined as ",
    " refers to ",
    " means ",
    " we call ",
    " denotes ",
)

DEFINITION_FRAGMENT_TAIL_PATTERNS: Tuple[re.Pattern[str], ...] = (
    re.compile(r":\s*$"),
    re.compile(r"\b(?:iff|if and only if)\s*$", flags=re.IGNORECASE),
    re.compile(r"\bi\.e\.\s*$", flags=re.IGNORECASE),
    re.compile(r"\bsuch that\s*:?\s*$", flags=re.IGNORECASE),
    re.compile(r"\bthen(?: it holds that)?\s*:?\s*$", flags=re.IGNORECASE),
    re.compile(r"\b(?:and|or)\s*$", flags=re.IGNORECASE),
)


def _looks_bibliography_entry(text: str) -> bool:
    stripped = _normalize_ws(text)
    lowered = stripped.lower()
    year_hits = re.findall(r"\(\d{4}[a-z]?\)", stripped)
    author_hits = re.findall(r"(?:^|\s)\d*[A-Z][A-Za-z'`-]+,\s*(?:[A-Z]\.\s*)+", stripped)
    return bool(
        re.match(r"^[A-Z][A-Za-z'`-]+,\s*[A-Z]\.", stripped)
        or re.match(r"^[A-Z][A-Za-z'`-]+,\s*[A-Z].*\(\d{4}\)", stripped)
        or (len(author_hits) >= 2 and year_hits)
        or (
            author_hits
            and year_hits
            and re.search(r"\b(?:proc\.?|proceedings|journal|vol\.?|pp\.?|press|springer|ieee|acm|morgan kaufmann)\b", lowered)
        )
        or re.match(r"^\d+\s*[A-Z][A-Za-z'`-]+,\s*(?:[A-Z]\.\s*)+.*\(\d{4}\)", stripped)
    )


def _has_scope_explanation_cue(text: str, assessment: Mapping[str, Any]) -> bool:
    lowered = f" {_normalize_ws(text).lower()} "
    return bool(assessment.get("scope_signal")) or any(cue in lowered for cue in SCOPE_EXPLANATION_CUES)


def _looks_generic_scope_lead_in(text: str) -> bool:
    stripped = _normalize_ws(text)
    return any(pattern.match(stripped) for pattern in SCOPE_GENERIC_LEAD_IN_PATTERNS)


def _looks_definition_fragment_tail(text: str) -> bool:
    stripped = _normalize_ws(text)
    if not stripped:
        return True
    return any(pattern.search(stripped) for pattern in DEFINITION_FRAGMENT_TAIL_PATTERNS)


def _looks_definition_fragment_start(text: str) -> bool:
    stripped = _normalize_ws(text)
    if not stripped:
        return True
    if any(pattern.match(stripped) for pattern in DEFINITION_FALLBACK_START_PATTERNS):
        return True
    lowered = stripped.lower()
    return lowered.startswith(("is ", "are "))


def _looks_relation_tail_fragment(text: str) -> bool:
    stripped = _normalize_ws(text)
    if not stripped:
        return True
    return bool(
        re.search(
            r"\b(?:is|are|means|refers to|denotes|captures|represents|characterizes|measures|quantifies)\s*[.!?]?$",
            stripped,
            flags=re.IGNORECASE,
        )
    )


def _looks_multi_proposition_surface(text: str) -> bool:
    stripped = _normalize_ws(text)
    if not stripped:
        return False
    sentence_like_parts = [part for part in re.split(r"(?<=[.!?])\s+", stripped) if _normalize_ws(part)]
    if len(sentence_like_parts) >= 2 and _candidate_tokens(stripped) >= 20:
        return True
    if stripped.count(";") >= 1 and _candidate_tokens(stripped) >= 20:
        return True
    return False


def _looks_heading_like_definition(text: str) -> bool:
    stripped = _normalize_ws(text)
    if not stripped:
        return False
    lowered = stripped.lower()
    token_count = _candidate_tokens(stripped)
    if token_count > 10:
        return False
    if any(ch in stripped for ch in ".;!?="):
        return False
    if " iff " in f" {lowered} " or " if and only if " in f" {lowered} ":
        return False
    if re.search(r"\b(?:is|are|means|refers|denotes|describes|measures|captures|tests|uses|when|where|with|that|which)\b", lowered):
        return False
    if re.match(r"^(?:chapter|section|figure|table|algorithm)\b", lowered):
        return True
    return token_count <= 8


def _looks_clause_continuation_fragment(text: str) -> bool:
    stripped = _normalize_ws(text)
    lowered = f" {stripped.lower()} "
    return bool(
        re.match(r"^(?:and|or|where|until|for each|if|then)\b", stripped, flags=re.IGNORECASE)
        or re.match(
            r"^(?:[$\\A-Za-z0-9_()\[\]{}.,+-]+(?:\s+[$\\A-Za-z0-9_()\[\]{}.,+-]+){0,4})\s+(?:is|are)\b",
            stripped,
            flags=re.IGNORECASE,
        )
        or " it holds that " in lowered
        or " and " in lowered
        or bool(re.search(r"\b[A-Za-z]\s*=", stripped))
        or "≤" in stripped
        or ">=" in stripped
        or "<=" in stripped
    )


def _definition_assignment_segments(text: str) -> List[Tuple[str, str]]:
    stripped = _normalize_ws(text)
    if "=" not in stripped:
        return []
    matches = list(
        re.finditer(
            r"(?P<label>[A-Za-z][A-Za-z0-9()/% _\-]{0,48})\s*=\s*(?P<rhs>[^=]+?)(?=(?:\s+[A-Za-z][A-Za-z0-9()/% _\-]{0,48}\s*=)|$)",
            stripped,
        )
    )
    return [
        (str(_normalize_ws(match.group("label") or "")), str(_normalize_ws(match.group("rhs") or "")))
        for match in matches
        if _normalize_ws(match.group("label") or "") and _normalize_ws(match.group("rhs") or "")
    ]


def _rhs_looks_scalar_output(rhs: str) -> bool:
    stripped = _normalize_ws(rhs)
    if not stripped or not re.search(r"\d", stripped):
        return False
    residual = re.sub(r"[0-9\s%.,:;(){}\[\]+\-/*^<>=_]", "", stripped)
    return not residual


def _looks_metric_output_surface(text: str) -> bool:
    stripped = _normalize_ws(text)
    assignments = _definition_assignment_segments(stripped)
    if not assignments:
        return False
    numeric_assignments = sum(1 for _, rhs in assignments if _rhs_looks_scalar_output(rhs))
    lowered = f" {stripped.lower()} "
    explicit_definition_relation = any(cue in lowered for cue in DEFINITION_RELATION_CUES)
    if numeric_assignments >= 2:
        return True
    return numeric_assignments == 1 and len(assignments) == 1 and not explicit_definition_relation


def _looks_procedural_definition_header(text: str) -> bool:
    stripped = _normalize_ws(text)
    lowered = f" {stripped.lower()} "
    if "=" not in stripped and ":" not in stripped:
        return False
    if " iff " in lowered or " if and only if " in lowered:
        return False
    cue_hits = sum(
        1
        for cue in (" function ", " initialize ", " repeat ", " return ", " until ", " while ", " input ", " output ", " algorithm ")
        if cue in lowered
    )
    return cue_hits >= 2 or (
        " function " in lowered and (" initialize " in lowered or " repeat " in lowered or " return " in lowered)
    )


def _looks_contextual_definition_scaffold(
    text: str,
    *,
    supporting_rows: Sequence[Mapping[str, Any]],
    target_descriptor: Mapping[str, Any],
) -> bool:
    stripped = _normalize_ws(text)
    if not stripped or not any(pattern.match(stripped) for pattern in DEFINITION_CONTEXTUAL_SCAFFOLD_START_PATTERNS):
        return False
    lowered = f" {stripped.lower()} "
    if any(cue in lowered for cue in DEFINITION_RELATION_CUES):
        return False
    if not supporting_rows:
        return False
    target_profile = _descriptor_alignment(stripped, target_descriptor)
    if bool(target_profile.get("exact_name_phrase")):
        return False
    target_kc_id = str(target_descriptor.get("kc_id") or "")
    foreign_support = any(_row_source_relation(row, target_kc_id=target_kc_id) != "local" for row in supporting_rows)
    procedure_or_formula_support = 0
    for row in supporting_rows:
        assessment = dict(assess_overlay_candidate(row))
        if bool(row.get("is_procedure_like")) or bool(row.get("is_formula_like")) or bool(assessment.get("equation_support")):
            procedure_or_formula_support += 1
    if procedure_or_formula_support <= 0:
        return False
    return foreign_support or ":" in stripped or "=" in stripped


def _page_key(row: Mapping[str, Any]) -> Tuple[str, int] | None:
    doc_id = str(row.get("doc_id") or "")
    page_index = row.get("page_index")
    if not doc_id or not isinstance(page_index, int):
        return None
    return doc_id, int(page_index)


def _block_suffix_index(block_id: str) -> int | None:
    match = re.search(r":(\d+)$", str(block_id or ""))
    if not match:
        return None
    return int(match.group(1))


def _definition_rescue_score(candidate: FieldCandidate) -> float:
    score = float(candidate.score)
    text = _normalize_ws(candidate.text)
    lowered = f" {text.lower()} "
    assessment = dict(candidate.assessment)
    if candidate.single_span_accepted:
        score += 3.0
    if bool(assessment.get("definition_signal")):
        score += 1.5
    if bool(assessment.get("context_candidate")) and not bool(assessment.get("definition_candidate")):
        score -= 1.0
    if _has_scope_explanation_cue(text, assessment):
        score -= 3.5
    if re.search(r"\[[^\]]+\]", text):
        score -= 3.0
    if _looks_definition_fragment_tail(text):
        score -= 3.5
    if _looks_definition_fragment_start(text):
        if candidate.has_name_anchor or candidate.title_overlap > 0 or candidate.context_overlap > 0:
            score += 1.0
        else:
            score -= 2.0
    if _looks_bibliography_entry(text):
        score -= 6.0
    if " iff " in lowered or " if and only if " in lowered or "=" in text:
        score += 1.0
    return round(score, 6)


def _definition_candidate_rerank_adjustment(
    candidate: FieldCandidate,
    *,
    target_descriptor: Mapping[str, Any],
) -> float:
    text = _normalize_ws(candidate.text)
    if not text:
        return 0.0
    lowered = f" {text.lower()} "
    issues = {str(item) for item in candidate.issues}
    assessment = dict(candidate.assessment)
    target_kc_id = str(target_descriptor.get("kc_id") or "")
    local_candidate = _row_source_relation(candidate.row, target_kc_id=target_kc_id) == "local"
    name_variants = _definition_name_variants(
        str(target_descriptor.get("canonical_name") or ""),
        [str(item) for item in target_descriptor.get("aliases") or []],
    )
    relation_score = _quote_surface_relation_score(text, name_variants=name_variants)
    token_count = _candidate_tokens(text)
    surface_type = str(assessment.get("positive_surface_type") or "")
    classification = str(assessment.get("classification") or "")
    target_profile = _descriptor_alignment(text, target_descriptor)
    fragmentary_surface = bool(
        "fragment_lead_in" in issues
        or _looks_definition_fragment_start(text)
        or _looks_definition_fragment_tail(text)
    )
    score = 0.0

    if local_candidate:
        score += 5.0
    else:
        score -= 4.0

    if relation_score > 0.0 and not fragmentary_surface:
        score += 4.0 + relation_score
    elif bool(target_profile.get("exact_name_phrase")) and any(
        cue in lowered
        for cue in (
            " starts with ",
            " begins with ",
            " operates ",
            " uses ",
            " consists of ",
            " assigns ",
            " groups ",
            " partitions ",
            " merges ",
        )
    ):
        score += 2.0

    if classification == "definition_support":
        score += 2.0
    elif classification == "context_support":
        score -= 2.0
    elif classification == "equation_support":
        score -= 3.0

    if surface_type == "anchored_descriptive_clause" and local_candidate:
        score += 1.0
    elif surface_type == "formula_backed_explanatory_clause" and relation_score <= 0.0:
        score -= 1.5

    if candidate.has_name_anchor:
        score += 1.0

    if "overlong_surface" in issues:
        score -= 7.0
    elif 8 <= token_count <= 36:
        score += 1.5
    elif token_count >= 48:
        score -= min(4.0, 1.0 + float(token_count - 48) / 8.0)

    if "fragment_lead_in" in issues:
        score -= 4.0
    if _looks_definition_fragment_start(text) or _looks_definition_fragment_tail(text):
        score -= 5.0
    if text[:1].isalpha() and text[:1].islower():
        score -= 3.5
    if "formula_dense_fragment" in issues:
        score -= 4.0
    if _looks_bibliography_entry(text):
        score -= 6.0
    if _looks_heading_like_definition(text):
        score -= 5.0
    if _looks_multi_proposition_surface(text):
        score -= 4.0
    if (
        relation_score <= 0.0
        and " called " not in lowered
        and " known as " not in lowered
        and " defined as " not in lowered
        and " refers to " not in lowered
        and " denotes " not in lowered
        and (_looks_generic_scope_lead_in(text) or _has_scope_explanation_cue(text, assessment))
    ):
        score -= 2.5
    if not fragmentary_surface and any(
        cue in lowered
        for cue in (
            " called ",
            " known as ",
            " defined as ",
            " refers to ",
            " denotes ",
        )
    ):
        score += 2.5

    return round(score, 6)


def _rerank_definition_candidates(
    definition_candidates: Sequence[FieldCandidate],
    *,
    target_descriptor: Mapping[str, Any],
) -> List[FieldCandidate]:
    reranked = [
        replace(
            candidate,
            score=round(
                float(candidate.score)
                + _definition_candidate_rerank_adjustment(
                    candidate,
                    target_descriptor=target_descriptor,
                ),
                6,
            ),
        )
        for candidate in definition_candidates
    ]
    reranked.sort(key=lambda item: (-float(item.score), item.overlay_candidate_id))
    return reranked


def _definition_rescue_candidates(
    definition_candidates: Sequence[FieldCandidate],
    *,
    limit: int,
) -> List[FieldCandidate]:
    rescored = sorted(
        definition_candidates,
        key=lambda item: (-_definition_rescue_score(item), -float(item.score), item.overlay_candidate_id),
    )
    return list(rescored[: max(1, int(limit))])


def _definition_single_span_fallback_candidate(
    definition_candidates: Sequence[FieldCandidate],
    *,
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
) -> Optional[FieldCandidate]:
    safe_candidates: List[Tuple[float, FieldCandidate]] = []
    for candidate in definition_candidates:
        if not candidate.single_span_accepted:
            continue
        text = _normalize_ws(candidate.text)
        if not text:
            continue
        if (
            _looks_metric_output_surface(text)
            or _looks_procedural_definition_header(text)
            or _looks_bibliography_entry(text)
            or _looks_generic_scope_lead_in(text)
            or _looks_heading_like_definition(text)
        ):
            continue
        if _looks_definition_fragment_start(text) or _looks_definition_fragment_tail(text):
            continue
        if any(
            code in {"citation_or_slide_context", "ocr_noise", "traceback_noise", "generic_background", "procedural_fragment"}
            for code in candidate.issues
        ):
            continue
        target_kc_id = str(target_descriptor.get("kc_id") or "")
        if _row_source_relation(candidate.row, target_kc_id=target_kc_id) != "local":
            continue
        target_profile = _descriptor_alignment(text, target_descriptor)
        lowered = f" {text.lower()} "
        if not (
            candidate.has_name_anchor
            or bool(target_profile.get("exact_name_phrase"))
            or int(target_profile.get("name_overlap") or 0) >= 2
        ):
            continue
        if not (
            any(cue in lowered for cue in DEFINITION_RELATION_CUES)
            or "=" in text
            or " iff " in lowered
            or " if and only if " in lowered
        ):
            continue
        if _looks_multi_proposition_surface(text):
            continue
        if _sibling_boundary_risk(
            text,
            target_descriptor=target_descriptor,
            sibling_descriptors=sibling_descriptors,
        ):
            continue
        if _has_scope_explanation_cue(text, candidate.assessment) and " =" not in text and " iff " not in f" {text.lower()} ":
            continue
        safe_candidates.append((_definition_rescue_score(candidate), candidate))
    if not safe_candidates:
        return None
    safe_candidates.sort(key=lambda item: (-float(item[0]), -float(item[1].score), item[1].overlay_candidate_id))
    return safe_candidates[0][1]


def _definition_draft_supported_single_span_fallback_candidate(
    *,
    definition_candidates: Sequence[FieldCandidate],
    preservation_draft_response: Mapping[str, Any],
    rescue_draft_response: Mapping[str, Any],
    definition_redraft_response: Mapping[str, Any],
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
) -> Tuple[Optional[FieldCandidate], str]:
    pool_by_id = {
        str(candidate.overlay_candidate_id): candidate
        for candidate in definition_candidates
        if str(candidate.overlay_candidate_id)
    }
    target_kc_id = str(target_descriptor.get("kc_id") or "")
    for source_name, response in (
        ("preservation_draft_response", preservation_draft_response),
        ("rescue_draft_response", rescue_draft_response),
        ("definition_redraft_response", definition_redraft_response),
    ):
        payload = dict(response.get("definition") or {})
        if str(payload.get("status") or "") != ENRICHMENT_LAYER_STATUS_GROUNDED:
            continue
        supporting_ids = [str(item) for item in payload.get("supporting_overlay_candidate_ids") or [] if str(item)]
        if len(supporting_ids) != 1:
            continue
        candidate = pool_by_id.get(supporting_ids[0])
        if candidate is None or not candidate.single_span_accepted:
            continue
        text = _normalize_ws(candidate.text)
        if not text:
            continue
        if _row_source_relation(candidate.row, target_kc_id=target_kc_id) != "local":
            continue
        if _looks_bibliography_entry(text) or _looks_heading_like_definition(text):
            continue
        if any(
            code in {"citation_or_slide_context", "ocr_noise", "traceback_noise", "generic_background", "procedural_fragment"}
            for code in candidate.issues
        ):
            continue
        if _sibling_boundary_risk(
            text,
            target_descriptor=target_descriptor,
            sibling_descriptors=sibling_descriptors,
        ):
            continue
        return candidate, source_name
    return None, ""


def _prefer_definition_duplicate_candidate(
    current: FieldCandidate,
    candidate: FieldCandidate,
    *,
    target_descriptor: Mapping[str, Any],
) -> FieldCandidate:
    target_kc_id = str(target_descriptor.get("kc_id") or "")
    current_local = _row_source_relation(current.row, target_kc_id=target_kc_id) == "local"
    candidate_local = _row_source_relation(candidate.row, target_kc_id=target_kc_id) == "local"
    if candidate_local != current_local:
        return candidate if candidate_local else current

    current_fragmentary = _looks_definition_fragment_start(current.text) or _looks_definition_fragment_tail(current.text)
    candidate_fragmentary = _looks_definition_fragment_start(candidate.text) or _looks_definition_fragment_tail(candidate.text)
    if candidate_fragmentary != current_fragmentary:
        return candidate if not candidate_fragmentary else current

    current_issue_count = len(current.issues)
    candidate_issue_count = len(candidate.issues)
    if candidate_issue_count != current_issue_count:
        return candidate if candidate_issue_count < current_issue_count else current

    return candidate if float(candidate.score) > float(current.score) else current


def _definition_context_completion_candidate(
    definition_candidates: Sequence[FieldCandidate],
    *,
    completion_context_rows: Sequence[Mapping[str, Any]],
    rows_by_page: Mapping[Tuple[str, int], Sequence[Mapping[str, Any]]],
    rows_by_id: Mapping[str, Mapping[str, Any]],
    assessments_by_id: Mapping[str, Mapping[str, Any]],
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    completion_rows_by_id = {
        str(row.get("overlay_candidate_id") or ""): dict(row)
        for row in completion_context_rows
        if str(row.get("overlay_candidate_id") or "")
    }

    rescue_candidates = _definition_rescue_candidates(definition_candidates, limit=max(1, min(4, len(definition_candidates))))
    for fragment_candidate in rescue_candidates:
        fragment_text = _normalize_ws(fragment_candidate.text)
        if not _looks_definition_fragment_tail(fragment_text):
            continue
        if _row_source_relation(
            fragment_candidate.row,
            target_kc_id=str(target_descriptor.get("kc_id") or ""),
        ) != "local":
            continue
        fragment_page_key = _page_key(fragment_candidate.row)
        fragment_block_index = _block_suffix_index(str(fragment_candidate.row.get("block_id") or ""))
        if fragment_page_key is None or fragment_block_index is None:
            continue

        ordered_rows: List[Tuple[int, Mapping[str, Any], str]] = []
        fragment_page_rows = rows_by_page.get(fragment_page_key, [])
        for row in fragment_page_rows:
            if str(row.get("overlay_candidate_id") or "") == str(fragment_candidate.row.get("overlay_candidate_id") or ""):
                continue
            if _page_key(row) != fragment_page_key:
                continue
            if str(row.get("kc_id") or "") != str(target_descriptor.get("kc_id") or ""):
                continue
            if str(row.get("kc_id") or "") != str(target_descriptor.get("kc_id") or ""):
                continue
            row_block_index = _block_suffix_index(str(row.get("block_id") or ""))
            if row_block_index is None or row_block_index <= fragment_block_index or row_block_index > fragment_block_index + 3:
                continue
            assessment = dict(assess_overlay_candidate(row))
            text = _clean_completion_segment(str(assessment.get("candidate_text") or ""))
            if not text or not _allowed_candidate_base(assessment):
                continue
            if _looks_bibliography_entry(text) or _looks_heading_like_definition(text):
                continue
            issues = _definition_extended_issue_codes(row, assessment, text)
            if any(issue in {"citation_or_slide_context", "ocr_noise", "traceback_noise"} for issue in issues):
                continue
            if not (_looks_clause_continuation_fragment(text) or _has_scope_explanation_cue(text, assessment)):
                continue
            same_layer = str(row.get("layer") or "") == str(fragment_candidate.row.get("layer") or "")
            distance = row_block_index - fragment_block_index
            ordering_score = 0.0
            ordering_score += 7.0 if distance == 1 else (4.0 if distance == 2 else 2.5)
            if same_layer:
                ordering_score += 4.0
            if _looks_clause_continuation_fragment(text):
                ordering_score += 2.5
            if not _looks_definition_fragment_tail(text):
                ordering_score += 1.0
            if str(row.get("kc_id") or "") == str(target_descriptor.get("kc_id") or ""):
                ordering_score += 1.5
            if bool(assessment.get("definition_candidate")):
                ordering_score += 1.0
            if bool(assessment.get("context_candidate")) or bool(assessment.get("scope_signal")):
                ordering_score += 0.5
            ordered_rows.append((int(round(-ordering_score * 1000)), dict(row), text))

        if not ordered_rows:
            for row in completion_rows_by_id.values():
                if _page_key(row) != fragment_page_key:
                    continue
                if str(row.get("kc_id") or "") != str(target_descriptor.get("kc_id") or ""):
                    continue
                if str(row.get("kc_id") or "") != str(target_descriptor.get("kc_id") or ""):
                    continue
                if str(row.get("kc_id") or "") != str(target_descriptor.get("kc_id") or ""):
                    continue
                if str(row.get("kc_id") or "") != str(target_descriptor.get("kc_id") or ""):
                    continue
                row_block_index = _block_suffix_index(str(row.get("block_id") or ""))
                if row_block_index is None or row_block_index <= fragment_block_index or row_block_index > fragment_block_index + 4:
                    continue
                assessment = dict(assessments_by_id.get(str(row.get("overlay_candidate_id") or "")) or assess_overlay_candidate(row))
                text = _clean_completion_segment(str(assessment.get("candidate_text") or ""))
                if not text or _looks_bibliography_entry(text) or _looks_heading_like_definition(text):
                    continue
                if not (_looks_clause_continuation_fragment(text) or _has_scope_explanation_cue(text, assessment)):
                    continue
                ordered_rows.append((row_block_index, row, text))

        if not ordered_rows:
            continue

        merged_segments = [_clean_completion_segment(fragment_text)]
        supporting_ids = [fragment_candidate.overlay_candidate_id]
        supporting_rows = [dict(fragment_candidate.row)]
        for _, row, text in sorted(ordered_rows, key=lambda item: (item[0], str(item[1].get("overlay_candidate_id") or ""))):
            candidate_id = str(row.get("overlay_candidate_id") or "")
            if not candidate_id or candidate_id in supporting_ids:
                continue
            merged_segments.append(text)
            supporting_ids.append(candidate_id)
            supporting_rows.append(dict(row))
            merged_text = _normalize_ws(" ".join(segment for segment in merged_segments if segment))
            if not merged_text:
                continue
            candidate_value = _candidate_value(
                text=merged_text,
                supporting_ids=supporting_ids,
                selection_reason="definition_full_candidate_completed_from_context",
                source_text_field=fragment_candidate.source_text_field,
            )
            if _looks_definition_fragment_start(merged_text) or _looks_definition_fragment_tail(merged_text):
                continue
            visible_rows_by_id = dict(rows_by_id)
            visible_assessments_by_id = dict(assessments_by_id)
            _materialize_support_rows(
                rows_by_id=visible_rows_by_id,
                assessments_by_id=visible_assessments_by_id,
                support_rows=supporting_rows,
            )
            if _field_definition_sibling_risk(
                candidate_value,
                rows_by_id=visible_rows_by_id,
                target_descriptor=target_descriptor,
                sibling_descriptors=sibling_descriptors,
            ):
                continue
            _materialize_support_rows(
                rows_by_id=rows_by_id,
                assessments_by_id=assessments_by_id,
                support_rows=supporting_rows,
            )
            return candidate_value
    return {}


def _candidate_diag_payload(candidate: FieldCandidate, *, max_chars: int) -> Dict[str, Any]:
    assessment = dict(candidate.assessment)
    return {
        "overlay_candidate_id": candidate.overlay_candidate_id,
        "source_kc_id": str(candidate.row.get("kc_id") or ""),
        "score": round(float(candidate.score), 6),
        "candidate_kind": candidate.candidate_kind,
        "text": _clip_text(candidate.text, max_chars),
        "token_count": _candidate_tokens(candidate.text),
        "source_text_field": candidate.source_text_field,
        "doc_id": str(candidate.row.get("doc_id") or ""),
        "block_id": str(candidate.row.get("block_id") or ""),
        "page_index": candidate.row.get("page_index"),
        "layer": str(candidate.row.get("layer") or ""),
        "has_name_anchor": bool(candidate.has_name_anchor),
        "title_overlap": int(candidate.title_overlap),
        "context_overlap": int(candidate.context_overlap),
        "single_span_accepted": bool(candidate.single_span_accepted),
        "issues": list(candidate.issues),
        "assessment": {
            "classification": str(assessment.get("classification") or ""),
            "positive_surface_type": str(assessment.get("positive_surface_type") or ""),
            "definition_signal": bool(assessment.get("definition_signal")),
            "scope_signal": bool(assessment.get("scope_signal")),
            "equation_support": bool(assessment.get("equation_support")),
            "context_candidate": bool(assessment.get("context_candidate")),
            "definition_candidate": bool(assessment.get("definition_candidate")),
        },
    }


def _candidate_diag_payload_with_context(
    candidate: FieldCandidate,
    *,
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
    max_chars: int,
) -> Dict[str, Any]:
    payload = _candidate_diag_payload(candidate, max_chars=max_chars)
    payload["candidate_source_relation"] = _row_source_relation(
        candidate.row,
        target_kc_id=str(target_descriptor.get("kc_id") or ""),
    )
    payload["source_canonical_name"] = str(candidate.row.get("canonical_name") or "")
    alignment = _contrastive_alignment(
        candidate.text,
        target_descriptor=target_descriptor,
        sibling_descriptors=sibling_descriptors,
    )
    payload["contrastive_alignment"] = {
        "target_score": float((alignment.get("target") or {}).get("score") or 0.0),
        "best_sibling_score": float((alignment.get("best_sibling") or {}).get("score") or 0.0),
        "sibling_margin": float(alignment.get("sibling_margin") or 0.0),
        "best_sibling_kc_id": str((alignment.get("best_sibling_descriptor") or {}).get("kc_id") or ""),
    }
    return payload


def _materialize_support_rows(
    *,
    rows_by_id: Dict[str, Mapping[str, Any]],
    assessments_by_id: Dict[str, Mapping[str, Any]],
    support_rows: Sequence[Mapping[str, Any]],
) -> None:
    for row in support_rows:
        candidate_id = str(row.get("overlay_candidate_id") or "")
        if not candidate_id:
            continue
        if candidate_id not in rows_by_id:
            rows_by_id[candidate_id] = dict(row)
        if candidate_id not in assessments_by_id:
            assessments_by_id[candidate_id] = assess_overlay_candidate(row)


def _supporting_lookup_candidate_from_row(
    row: Mapping[str, Any],
    *,
    assessments_by_id: Mapping[str, Mapping[str, Any]],
) -> Optional[FieldCandidate]:
    candidate_id = str(row.get("overlay_candidate_id") or "")
    if not candidate_id:
        return None
    assessment = dict(assessments_by_id.get(candidate_id) or assess_overlay_candidate(row))
    text = _normalize_ws(assessment.get("candidate_text") or "")
    if not text:
        return None
    title_overlap, context_overlap, has_name_anchor = _definition_alignment_features(row, text)
    issues = tuple(str(item) for item in unique_preserve_order(_definition_extended_issue_codes(row, assessment, text)))
    return FieldCandidate(
        overlay_candidate_id=candidate_id,
        score=round(float(assessment.get("selection_score") or 0.0), 6),
        text=text,
        source_text_field=_candidate_source_text_field(row),
        candidate_kind="definition",
        row=dict(row),
        assessment=assessment,
        issues=issues,
        has_name_anchor=bool(has_name_anchor),
        title_overlap=int(title_overlap),
        context_overlap=int(context_overlap),
        single_span_accepted=False,
    )


def _augment_supporting_lookup_from_value(
    value: Mapping[str, Any],
    *,
    supporting_lookup: Dict[str, FieldCandidate],
    rows_by_id: Mapping[str, Mapping[str, Any]],
    assessments_by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    if str(value.get("status") or "") != "grounded":
        return
    for candidate_id in [str(item) for item in value.get("supporting_overlay_candidate_ids") or [] if str(item)]:
        if candidate_id in supporting_lookup:
            continue
        row = rows_by_id.get(candidate_id)
        if not row:
            continue
        candidate = _supporting_lookup_candidate_from_row(
            row,
            assessments_by_id=assessments_by_id,
        )
        if candidate is not None:
            supporting_lookup[candidate_id] = candidate


def _labeled_candidate_payloads(
    definition_candidates: Sequence[FieldCandidate],
    scope_candidates: Sequence[FieldCandidate],
    *,
    max_chars: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, str]]:
    overlay_to_label: Dict[str, str] = {}
    label_counter = 1

    def ensure_label(candidate: FieldCandidate) -> str:
        nonlocal label_counter
        overlay_id = candidate.overlay_candidate_id
        label = overlay_to_label.get(overlay_id)
        if label:
            return label
        label = f"E{label_counter}"
        overlay_to_label[overlay_id] = label
        label_counter += 1
        return label

    def enrich(candidates: Sequence[FieldCandidate]) -> List[Dict[str, Any]]:
        enriched: List[Dict[str, Any]] = []
        for candidate in candidates:
            payload = _candidate_diag_payload(candidate, max_chars=max_chars)
            payload["evidence_label"] = ensure_label(candidate)
            enriched.append(payload)
        return enriched

    return enrich(definition_candidates), enrich(scope_candidates), overlay_to_label


def _reference_candidate_value(
    reference_value: Mapping[str, Any],
    *,
    selection_reason: str,
    rows_by_id: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    supporting_ids = [str(item) for item in reference_value.get("supporting_overlay_candidate_ids") or [] if str(item)]
    if not supporting_ids:
        return {}
    first_row = rows_by_id.get(supporting_ids[0]) or {}
    return _candidate_value(
        text=str(reference_value.get("text") or ""),
        supporting_ids=supporting_ids,
        selection_reason=selection_reason,
        source_text_field=str(reference_value.get("source_text_field") or _candidate_source_text_field(first_row)),
    )


def _grounded_candidate_available(
    value: Mapping[str, Any],
    *,
    rows_by_id: Mapping[str, Mapping[str, Any]],
) -> bool:
    if str(value.get("status") or "") != "grounded":
        return False
    supporting_ids = [str(item) for item in value.get("supporting_overlay_candidate_ids") or [] if str(item)]
    return bool(supporting_ids) and all(candidate_id in rows_by_id for candidate_id in supporting_ids)


def _field_definition_sibling_risk(
    value: Mapping[str, Any],
    *,
    rows_by_id: Mapping[str, Mapping[str, Any]],
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
) -> bool:
    if str(value.get("status") or "") != "grounded":
        return False
    text = _normalize_ws(value.get("text") or "")
    if not text:
        return True
    source_text_field = str(value.get("source_text_field") or "")
    supporting_ids = [str(item) for item in value.get("supporting_overlay_candidate_ids") or [] if str(item)]
    supporting_rows = [dict(rows_by_id.get(candidate_id) or {}) for candidate_id in supporting_ids if candidate_id in rows_by_id]
    if (
        _looks_metric_output_surface(text)
        or _looks_procedural_definition_header(text)
        or _looks_contextual_definition_scaffold(
            text,
            supporting_rows=supporting_rows,
            target_descriptor=target_descriptor,
        )
        or _looks_bibliography_entry(text)
        or _looks_heading_like_definition(text)
        or _looks_definition_fragment_tail(text)
    ):
        return True
    if supporting_ids:
        target_kc_id = str(target_descriptor.get("kc_id") or "")
        local_support_present = any(
            str((rows_by_id.get(candidate_id) or {}).get("kc_id") or "") == target_kc_id
            for candidate_id in supporting_ids
        )
        supporting_quote_texts = [
            _normalize_ws(row.get("quote_surface") or row.get("candidate_text") or "")
            for row in supporting_rows
        ]
        supporting_texts = [
            _normalize_ws(
                assess_overlay_candidate(row).get("candidate_text")
                or row.get("quote_surface")
                or row.get("source_block_text")
                or ""
            )
            for row in supporting_rows
        ]
        if len(supporting_texts) == 1:
            support_text = supporting_texts[0]
            safe_local_quote_override = False
            if source_text_field == "source_faithful_normalization" and len(supporting_quote_texts) == 1:
                safe_local_quote_override = bool(
                    _anchored_local_definition_sentence(
                        str(target_descriptor.get("canonical_name") or ""),
                        supporting_quote_texts[0],
                    )
                )
            if support_text and (
                not safe_local_quote_override
                and (
                    _looks_bibliography_entry(support_text)
                    or _looks_heading_like_definition(support_text)
                    or _looks_definition_fragment_tail(support_text)
                    or _looks_definition_fragment_start(support_text)
                )
            ):
                return True
        if len(supporting_quote_texts) == 1:
            quote_text = supporting_quote_texts[0]
            lowered_final = f" {text.lower()} "
            if quote_text and (
                _looks_bibliography_entry(quote_text)
                or _looks_heading_like_definition(quote_text)
                or (
                    (_looks_definition_fragment_tail(quote_text) or _looks_definition_fragment_start(quote_text))
                    and (
                        " then it holds that " in lowered_final
                        or _looks_definition_fragment_tail(text)
                        or _looks_definition_fragment_start(text)
                    )
                )
            ):
                return True
        if not local_support_present:
            target_profile = _descriptor_alignment(text, target_descriptor)
            if not (
                bool(target_profile.get("exact_name_phrase"))
                or int(target_profile.get("name_overlap") or 0) > 0
            ):
                return True
            if any(_looks_multi_proposition_surface(support_text) for support_text in supporting_texts):
                return True
    return _sibling_boundary_risk(
        text,
        target_descriptor=target_descriptor,
        sibling_descriptors=sibling_descriptors,
    )


def _family_context_rows(
    *,
    rows_by_kc: Mapping[str, Sequence[Mapping[str, Any]]],
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
    limit: int,
) -> List[Mapping[str, Any]]:
    if not sibling_descriptors or int(limit) <= 0:
        return []
    scored_rows: List[Tuple[float, Mapping[str, Any]]] = []
    seen_ids: set[str] = set()
    for sibling_descriptor in sibling_descriptors:
        sibling_kc_id = str(sibling_descriptor.get("kc_id") or "")
        for row in rows_by_kc.get(sibling_kc_id, []):
            candidate_id = str(row.get("overlay_candidate_id") or "")
            if not candidate_id or candidate_id in seen_ids:
                continue
            assessment = assess_overlay_candidate(row)
            text = _normalize_ws(assessment.get("candidate_text") or "")
            if not text or not _allowed_candidate_base(assessment) or _looks_bibliography_entry(text) or _looks_heading_like_definition(text):
                continue
            alignment = _contrastive_alignment(
                text,
                target_descriptor=target_descriptor,
                sibling_descriptors=sibling_descriptors,
            )
            target_profile = dict(alignment.get("target") or {})
            sibling_margin = float(alignment.get("sibling_margin") or 0.0)
            if float(target_profile.get("score") or 0.0) <= 0.0 or sibling_margin > 0.0:
                continue
            if not (
                bool(target_profile.get("exact_name_phrase"))
                or int(target_profile.get("name_overlap") or 0) > 0
                or int(target_profile.get("context_overlap") or 0) > 0
            ):
                continue
            score = (
                float(target_profile.get("score") or 0.0)
                + float(assessment.get("selection_score") or 0.0)
                + (1.5 if bool(assessment.get("definition_candidate")) else 0.0)
                + (1.0 if bool(assessment.get("context_candidate")) else 0.0)
                + (1.0 if bool(assessment.get("scope_signal")) else 0.0)
            )
            scored_rows.append((score, dict(row)))
            seen_ids.add(candidate_id)
    scored_rows.sort(key=lambda item: (-float(item[0]), str(item[1].get("overlay_candidate_id") or "")))
    harvested_rows: List[Mapping[str, Any]] = []
    seen_text_keys: set[str] = set()
    for _, row in scored_rows:
        text_key = _text_key(str(assess_overlay_candidate(row).get("candidate_text") or ""))
        if text_key and text_key in seen_text_keys:
            continue
        if text_key:
            seen_text_keys.add(text_key)
        harvested_rows.append(row)
        if len(harvested_rows) >= int(limit):
            break
    return harvested_rows


def _completion_context_rows(
    *,
    rows_by_page: Mapping[Tuple[str, int], Sequence[Mapping[str, Any]]],
    fragment_rows: Sequence[Mapping[str, Any]],
    target_kc_id: str,
    limit: int,
) -> List[Mapping[str, Any]]:
    if int(limit) <= 0:
        return []
    scored_rows: List[Tuple[float, Mapping[str, Any]]] = []
    seen_ids: set[str] = set()
    for fragment_row in fragment_rows:
        fragment_assessment = assess_overlay_candidate(fragment_row)
        fragment_text = _normalize_ws(fragment_assessment.get("candidate_text") or "")
        if not _looks_definition_fragment_tail(fragment_text):
            continue
        page_key = _page_key(fragment_row)
        if page_key is None:
            continue
        fragment_block_index = _block_suffix_index(str(fragment_row.get("block_id") or ""))
        for row in rows_by_page.get(page_key, []):
            candidate_id = str(row.get("overlay_candidate_id") or "")
            if not candidate_id or candidate_id in seen_ids or candidate_id == str(fragment_row.get("overlay_candidate_id") or ""):
                continue
            assessment = assess_overlay_candidate(row)
            text = _clean_completion_segment(assessment.get("candidate_text") or "")
            if not text or not _allowed_candidate_base(assessment):
                continue
            if _looks_bibliography_entry(text) or _looks_heading_like_definition(text):
                continue
            issues = _definition_extended_issue_codes(row, assessment, text)
            if any(issue in {"citation_or_slide_context", "ocr_noise", "traceback_noise"} for issue in issues):
                continue
            row_block_index = _block_suffix_index(str(row.get("block_id") or ""))
            if fragment_block_index is None or row_block_index is None:
                continue
            distance = row_block_index - fragment_block_index
            if distance <= 0 or distance > 3:
                continue
            score = 0.0
            same_layer = str(row.get("layer") or "") == str(fragment_row.get("layer") or "")
            score += 7.0 if distance == 1 else (4.0 if distance == 2 else 2.5)
            if same_layer:
                score += 4.0
            if _looks_clause_continuation_fragment(text):
                score += 2.5
            if not _looks_definition_fragment_tail(text):
                score += 1.0
            if str(row.get("kc_id") or "") == str(target_kc_id or ""):
                score += 1.5
            if bool(assessment.get("definition_candidate")):
                score += 1.0
            if bool(assessment.get("context_candidate")) or bool(assessment.get("scope_signal")):
                score += 0.5
            row_copy = dict(row)
            row_copy["step67_completion_context"] = True
            scored_rows.append((score, row_copy))
            seen_ids.add(candidate_id)
    scored_rows.sort(key=lambda item: (-float(item[0]), str(item[1].get("overlay_candidate_id") or "")))
    harvested_rows: List[Mapping[str, Any]] = []
    for _, row in scored_rows[: max(0, int(limit))]:
        harvested_rows.append(row)
    return harvested_rows


def _reason_penalty(reason: str) -> float:
    penalties = {
        "weak_target_alignment": 8.0,
        "ambiguous_retrieval": 7.0,
        "citation_or_slide_context": 5.0,
        "ocr_noise": 5.0,
        "generic_context_lead_in": 4.0,
        "generic_background": 5.0,
        "procedural_fragment": 4.0,
        "formula_dense_fragment": 2.5,
        "surface_gate_rejected": 2.5,
        "not_definition_candidate_pool": 1.5,
    }
    return float(penalties.get(str(reason), 0.0))


def _bundle_item_from_row(
    row: Mapping[str, Any],
    assessment: Mapping[str, Any],
    *,
    bundle_role: str,
) -> Dict[str, Any]:
    return {
        "bundle_role": str(bundle_role or "context_support"),
        "overlay_candidate_id": str(row.get("overlay_candidate_id") or ""),
        "selection_score": float(assessment.get("selection_score") or 0.0),
        "candidate_text": str(assessment.get("candidate_text") or ""),
        "quote_surface": _normalize_ws(row.get("quote_surface") or ""),
        "source_block_text": _normalize_ws(row.get("source_block_text") or ""),
        "doc_id": str(row.get("doc_id") or ""),
        "block_id": str(row.get("block_id") or ""),
        "page_index": row.get("page_index"),
        "sentence_id": str(row.get("sentence_id") or ""),
        "layer": str(row.get("layer") or ""),
        "alignment_score": float(row.get("alignment_score") or 0.0),
        "contamination_risk": str(row.get("contamination_risk") or ""),
        "provenance_normalization_status": str(row.get("provenance_normalization_status") or ""),
        "quote_verification_status": str(row.get("quote_verification_status") or ""),
        "assessment": {
            "classification": str(assessment.get("classification") or ""),
            "definition_signal": bool(assessment.get("definition_signal")),
            "scope_signal": bool(assessment.get("scope_signal")),
            "bare_heading": bool(assessment.get("bare_heading")),
            "formula_lead_in": bool(assessment.get("formula_lead_in")),
            "question_like": bool(assessment.get("question_like")),
        },
    }


def _required_bundle_role(
    candidate_id: str,
    *,
    definition_support_ids: Sequence[str],
    scope_support_ids: Sequence[str],
    assessment: Mapping[str, Any],
) -> str:
    candidate_id = str(candidate_id or "")
    definition_id_set = {str(item) for item in definition_support_ids or [] if str(item)}
    scope_id_set = {str(item) for item in scope_support_ids or [] if str(item)}
    if candidate_id in definition_id_set:
        if bool(assessment.get("equation_support")):
            return "equation_support"
        if bool(assessment.get("definition_candidate")):
            return "definition_support"
        return "context_support"
    if candidate_id in scope_id_set:
        return "context_support"
    if bool(assessment.get("equation_support")):
        return "equation_support"
    if bool(assessment.get("definition_candidate")):
        return "definition_support"
    return "context_support"


def _ensure_supported_bundle_items(
    *,
    selected_bundle: Sequence[Mapping[str, Any]],
    rows_by_id: Mapping[str, Mapping[str, Any]],
    assessments_by_id: Mapping[str, Mapping[str, Any]],
    definition_support_ids: Sequence[str],
    scope_support_ids: Sequence[str],
) -> List[Dict[str, Any]]:
    normalized_bundle: List[Dict[str, Any]] = [dict(item) for item in selected_bundle or [] if isinstance(item, Mapping)]
    seen_ids = {
        str(item.get("overlay_candidate_id") or "")
        for item in normalized_bundle
        if str(item.get("overlay_candidate_id") or "")
    }
    required_ids = [
        str(item)
        for item in unique_preserve_order([*(definition_support_ids or []), *(scope_support_ids or [])])
        if str(item)
    ]
    for candidate_id in required_ids:
        if candidate_id in seen_ids:
            continue
        row = rows_by_id.get(candidate_id)
        if not row:
            continue
        assessment = dict(assessments_by_id.get(candidate_id) or {})
        normalized_bundle.append(
            _bundle_item_from_row(
                row,
                assessment,
                bundle_role=_required_bundle_role(
                    candidate_id,
                    definition_support_ids=definition_support_ids,
                    scope_support_ids=scope_support_ids,
                    assessment=assessment,
                ),
            )
        )
        seen_ids.add(candidate_id)
    return normalized_bundle


def _allowed_candidate_base(assessment: Mapping[str, Any]) -> bool:
    return bool(
        bool(assessment.get("usable_evidence"))
        and not bool(assessment.get("question_like"))
        and not bool(assessment.get("bare_heading"))
        and not bool(assessment.get("background_drift_block"))
        and not bool(assessment.get("concept_mix_block"))
    )


def _field_candidate_from_support_pack_item(
    pack_item: Mapping[str, Any],
    *,
    rows_by_id: Mapping[str, Mapping[str, Any]],
    assessments_by_id: Mapping[str, Mapping[str, Any]],
    pack_rank: int,
) -> Optional[FieldCandidate]:
    candidate_id = str(pack_item.get("overlay_candidate_id") or "")
    if not candidate_id:
        return None
    row = dict(rows_by_id.get(candidate_id) or {})
    if not row:
        return None
    assessment = dict(assessments_by_id.get(candidate_id) or {})
    text = _normalize_ws(pack_item.get("candidate_text") or "")
    if not assessment or not text:
        return None

    verdict = _definition_candidate_verdict(row, assessment, text)
    issues = tuple(str(item) for item in unique_preserve_order(verdict.get("extended_issue_codes") or []))
    score = float(pack_item.get("support_pack_score") or 0.0)
    score += 12.0 - min(int(pack_rank), 2) * 1.5
    if bool(pack_item.get("text_changed")):
        score += 1.5
    if bool(verdict.get("accepted")):
        score += 1.0

    return FieldCandidate(
        overlay_candidate_id=candidate_id,
        score=round(score, 6),
        text=text,
        source_text_field=str(pack_item.get("source_text_field") or _candidate_source_text_field(row)),
        candidate_kind="definition",
        row=row,
        assessment=assessment,
        issues=issues,
        has_name_anchor=bool(verdict.get("has_name_anchor")),
        title_overlap=int(verdict.get("title_overlap") or 0),
        context_overlap=int(verdict.get("context_overlap") or 0),
        single_span_accepted=bool(verdict.get("accepted")),
    )


def _definition_candidates(
    rows_by_id: Mapping[str, Mapping[str, Any]],
    assessments_by_id: Mapping[str, Mapping[str, Any]],
    *,
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
    limit: int,
    support_pack: Sequence[Mapping[str, Any]] | None = None,
    build_support_pack: bool = True,
) -> List[FieldCandidate]:
    candidates: List[FieldCandidate] = []
    for candidate_id, row in rows_by_id.items():
        assessment = dict(assessments_by_id.get(candidate_id) or {})
        text = _normalize_ws(assessment.get("candidate_text") or "")
        if not text or not _allowed_candidate_base(assessment):
            continue
        verdict = _definition_candidate_verdict(row, assessment, text)
        issues = tuple(str(item) for item in unique_preserve_order(verdict.get("extended_issue_codes") or []))
        lowered = f" {text.lower()} "
        if _looks_bibliography_entry(text) and not bool(assessment.get("exact_named_equality_formula")):
            continue
        if (
            any(code in {"citation_or_slide_context", "ocr_noise", "traceback_noise"} for code in issues)
            and not bool(assessment.get("exact_named_equality_formula"))
        ):
            continue
        contrastive_alignment = _contrastive_alignment(
            text,
            target_descriptor=target_descriptor,
            sibling_descriptors=sibling_descriptors,
        )
        sibling_margin = float(contrastive_alignment.get("sibling_margin") or 0.0)
        target_profile = dict(contrastive_alignment.get("target") or {})
        score = float(_definition_candidate_choice_score(row, assessment, text, verdict))
        if bool(assessment.get("definition_candidate")):
            score += 3.0
        elif bool(assessment.get("context_candidate")):
            score += 1.5
        if bool(row.get("step67_completion_context")):
            score += 5.0
            if _looks_clause_continuation_fragment(text):
                score += 2.0
        if bool(assessment.get("exact_named_equality_formula")):
            score += 2.0
        if bool(assessment.get("theorem_statement_or_equation")):
            score += 1.0
        if bool(assessment.get("contamination_block")):
            score -= 3.5
        if " iff " in lowered or " if and only if " in lowered:
            score += 3.0
        if lowered.startswith("connectivity:") or " connectivity:" in lowered:
            score -= 4.0
        if " for each " in lowered and " iff " not in lowered and " if and only if " not in lowered:
            score -= 4.0
        if " it holds that " in lowered and " iff " not in lowered and " if and only if " not in lowered:
            score -= 2.5
        if _sibling_boundary_risk(
            text,
            target_descriptor=target_descriptor,
            sibling_descriptors=sibling_descriptors,
        ):
            score -= 9.0
        elif float(target_profile.get("score") or 0.0) > float((contrastive_alignment.get("best_sibling") or {}).get("score") or 0.0):
            score += 1.5
            if str(row.get("kc_id") or "") != str(target_descriptor.get("kc_id") or ""):
                score += 2.0
        elif sibling_margin > 0.0:
            score -= min(7.0, 2.0 + sibling_margin)
        for reason in verdict.get("reasons") or []:
            score -= _reason_penalty(str(reason))
        if not bool(verdict.get("has_name_anchor")) and int(verdict.get("title_overlap") or 0) == 0 and int(verdict.get("context_overlap") or 0) == 0:
            score -= 6.0
        if score < -5.0:
            continue
        candidates.append(
            FieldCandidate(
                overlay_candidate_id=str(candidate_id),
                score=round(score, 6),
                text=text,
                source_text_field=_candidate_source_text_field(row),
                candidate_kind="definition",
                row=dict(row),
                assessment=assessment,
                issues=issues,
                has_name_anchor=bool(verdict.get("has_name_anchor")),
                title_overlap=int(verdict.get("title_overlap") or 0),
                context_overlap=int(verdict.get("context_overlap") or 0),
                single_span_accepted=bool(verdict.get("accepted")),
            )
        )

    if support_pack is None and build_support_pack:
        support_pack = select_definition_support_pack(
            rows_by_id,
            assessments_by_id,
            target_kc_id=str(target_descriptor.get("kc_id") or ""),
            max_pack_size=min(3, max(1, int(limit))),
        )
    if support_pack:
        candidates_by_id: Dict[str, FieldCandidate] = {
            item.overlay_candidate_id: item
            for item in candidates
        }
        for pack_rank, pack_item in enumerate(support_pack):
            support_candidate = _field_candidate_from_support_pack_item(
                pack_item,
                rows_by_id=rows_by_id,
                assessments_by_id=assessments_by_id,
                pack_rank=pack_rank,
            )
            if support_candidate is None:
                continue
            candidates_by_id[support_candidate.overlay_candidate_id] = support_candidate
        candidates = list(candidates_by_id.values())

    candidates = _rerank_definition_candidates(
        candidates,
        target_descriptor=target_descriptor,
    )
    unique_by_key: Dict[str, FieldCandidate] = {}
    for item in candidates:
        key = _text_key(item.text) or item.overlay_candidate_id
        current = unique_by_key.get(key)
        if current is None:
            unique_by_key[key] = item
            continue
        unique_by_key[key] = _prefer_definition_duplicate_candidate(
            current,
            item,
            target_descriptor=target_descriptor,
        )

    unique_candidates = sorted(
        unique_by_key.values(),
        key=lambda item: (-float(item.score), item.overlay_candidate_id),
    )
    return unique_candidates[: max(1, int(limit))]


def _scope_candidates(
    rows_by_id: Mapping[str, Mapping[str, Any]],
    assessments_by_id: Mapping[str, Mapping[str, Any]],
    *,
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
    limit: int,
) -> List[FieldCandidate]:
    candidates: List[FieldCandidate] = []
    for candidate_id, row in rows_by_id.items():
        assessment = dict(assessments_by_id.get(candidate_id) or {})
        text = _normalize_ws(assessment.get("candidate_text") or "")
        if not text or not _allowed_candidate_base(assessment):
            continue
        title_overlap, context_overlap, has_name_anchor = _definition_alignment_features(row, text)
        lowered = f" {text.lower()} "
        if not (
            bool(assessment.get("scope_signal"))
            or bool(assessment.get("context_candidate"))
            or bool(assessment.get("definition_candidate"))
            or has_name_anchor
            or title_overlap > 0
            or context_overlap > 0
        ):
            continue
        if _looks_bibliography_entry(text):
            continue
        issues = tuple(str(item) for item in unique_preserve_order(_definition_extended_issue_codes(row, assessment, text)))
        if any(code in {"citation_or_slide_context", "ocr_noise", "traceback_noise"} for code in issues):
            continue
        contrastive_alignment = _contrastive_alignment(
            text,
            target_descriptor=target_descriptor,
            sibling_descriptors=sibling_descriptors,
        )
        sibling_margin = float(contrastive_alignment.get("sibling_margin") or 0.0)
        target_profile = dict(contrastive_alignment.get("target") or {})
        score = float(assessment.get("selection_score") or 0.0)
        classification = str(assessment.get("classification") or "")
        surface_type = str(assessment.get("positive_surface_type") or "")
        has_scope_explanation_cue = _has_scope_explanation_cue(text, assessment)
        if _selected_grounded_scope_support(row, assessment):
            score += 6.0
        if bool(assessment.get("scope_signal")):
            score += 4.0
        if bool(assessment.get("context_candidate")):
            score += 3.5
        if bool(assessment.get("definition_candidate")):
            score += 1.0
        if bool(row.get("strong_same_topic")) or bool(row.get("strong_structured_candidate")):
            score += 1.5
        if classification == "context_support":
            score += 3.5
        elif classification == "definition_support":
            score += 1.0
        elif classification == "equation_support":
            score -= 1.0
        elif classification == "formula_only_support":
            score -= 3.0
        elif classification == "weak_support":
            score -= 1.5
        if surface_type == "prose_definition":
            score += 2.5
        elif surface_type == "formula_backed_explanatory_clause":
            score += 2.0
        elif surface_type == "anchored_descriptive_clause":
            score += 1.5
        elif surface_type == "named_formula":
            score -= 2.0
        if has_scope_explanation_cue:
            score += 3.0
        if bool(assessment.get("contamination_block")):
            score -= 3.0
        if " iff " in lowered or " if and only if " in lowered:
            score += 2.0
        if _looks_generic_scope_lead_in(text) and " iff " not in lowered and " if and only if " not in lowered:
            score -= 3.5
        if lowered.count(":") >= 2 and not has_scope_explanation_cue:
            score -= 2.5
        if " for each " in lowered and " iff " not in lowered and " if and only if " not in lowered:
            score -= 2.5
        if " it holds that " in lowered and " iff " not in lowered and " if and only if " not in lowered:
            score -= 2.0
        token_count = _candidate_tokens(text)
        if 12 <= token_count <= 96:
            score += 1.5
        elif token_count < 7:
            score -= 2.5
        if bool(assessment.get("equation_support")) and not bool(assessment.get("scope_signal")) and not bool(assessment.get("context_candidate")):
            score -= 3.0
        if bool(assessment.get("definition_candidate")) and not bool(assessment.get("context_candidate")) and not has_scope_explanation_cue:
            score -= 1.5
        if _sibling_boundary_risk(
            text,
            target_descriptor=target_descriptor,
            sibling_descriptors=sibling_descriptors,
        ) and not has_scope_explanation_cue:
            score -= 5.0
        elif float(target_profile.get("score") or 0.0) > float((contrastive_alignment.get("best_sibling") or {}).get("score") or 0.0):
            score += 1.0
            if str(row.get("kc_id") or "") != str(target_descriptor.get("kc_id") or ""):
                score += 1.5
        elif sibling_margin > 0.0:
            score -= min(5.0, 1.5 + sibling_margin)
        for code in issues:
            if code in {"citation_or_slide_context", "ocr_noise", "generic_context_lead_in"}:
                score -= 4.5
            elif code in {"procedural_fragment", "generic_background"}:
                score -= 3.0
            elif code in {"weak_target_alignment", "ambiguous_retrieval"}:
                score -= 5.0
            elif code == "formula_dense_fragment":
                score -= 2.5
        if not has_name_anchor and title_overlap == 0 and context_overlap == 0 and not has_scope_explanation_cue:
            score -= 4.0
        if score < -5.0:
            continue
        candidates.append(
            FieldCandidate(
                overlay_candidate_id=str(candidate_id),
                score=round(score, 6),
                text=text,
                source_text_field=_candidate_source_text_field(row),
                candidate_kind="scope",
                row=dict(row),
                assessment=assessment,
                issues=issues,
                has_name_anchor=bool(has_name_anchor),
                title_overlap=int(title_overlap),
                context_overlap=int(context_overlap),
                single_span_accepted=bool(_selected_grounded_scope_support(row, assessment)),
            )
        )

    candidates.sort(key=lambda item: (-float(item.score), item.overlay_candidate_id))
    unique_candidates: List[FieldCandidate] = []
    seen_keys: set[str] = set()
    for item in candidates:
        key = _text_key(item.text)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        unique_candidates.append(item)
        if len(unique_candidates) >= max(1, int(limit)):
            break
    return unique_candidates


def _dynamic_field_schema(allowed_ids: Sequence[str]) -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["status", "text", "supporting_evidence_labels", "abstention_reason"],
        "properties": {
            "status": {"type": "string", "enum": ["grounded", "abstained"]},
            "text": {"type": "string"},
            "supporting_evidence_labels": {
                "type": "array",
                "items": {"type": "string", "enum": [str(item) for item in allowed_ids]},
                "uniqueItems": True,
            },
            "abstention_reason": {"type": "string"},
        },
    }


def _draft_schema(allowed_ids: Sequence[str]) -> Dict[str, Any]:
    field_schema = _dynamic_field_schema(allowed_ids)
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["definition", "scope"],
        "properties": {
            "definition": field_schema,
            "scope": field_schema,
        },
    }


def _scope_only_schema(allowed_ids: Sequence[str]) -> Dict[str, Any]:
    field_schema = _dynamic_field_schema(allowed_ids)
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["scope"],
        "properties": {
            "scope": field_schema,
        },
    }


def _definition_only_schema(allowed_ids: Sequence[str]) -> Dict[str, Any]:
    field_schema = _dynamic_field_schema(allowed_ids)
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["definition"],
        "properties": {
            "definition": field_schema,
        },
    }


def _request_payload(
    exemplar: Mapping[str, Any],
    definition_candidates: Sequence[FieldCandidate],
    scope_candidates: Sequence[FieldCandidate],
    *,
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
    max_chars: int,
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    definition_payloads, scope_payloads, overlay_to_label = _labeled_candidate_payloads(
        definition_candidates,
        scope_candidates,
        max_chars=max_chars,
    )
    definition_payloads = [
        {
            **_candidate_diag_payload_with_context(
                candidate,
                target_descriptor=target_descriptor,
                sibling_descriptors=sibling_descriptors,
                max_chars=max_chars,
            ),
            "evidence_label": overlay_to_label[candidate.overlay_candidate_id],
        }
        for candidate in definition_candidates
    ]
    scope_payloads = [
        {
            **_candidate_diag_payload_with_context(
                candidate,
                target_descriptor=target_descriptor,
                sibling_descriptors=sibling_descriptors,
                max_chars=max_chars,
            ),
            "evidence_label": overlay_to_label[candidate.overlay_candidate_id],
        }
        for candidate in scope_candidates
    ]
    return {
        "kc": _kc_prompt_payload(exemplar),
        "sibling_contrast": _sibling_descriptor_payloads(
            sibling_descriptors,
            limit=max(1, int(len(sibling_descriptors))),
        ),
        "definition_candidates": definition_payloads,
        "scope_candidates": scope_payloads,
    }, overlay_to_label


def _definition_request_payload(
    exemplar: Mapping[str, Any],
    *,
    definition_candidates: Sequence[FieldCandidate],
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
    max_chars: int,
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    definition_payloads, _, overlay_to_label = _labeled_candidate_payloads(
        definition_candidates,
        [],
        max_chars=max_chars,
    )
    definition_payloads = [
        {
            **_candidate_diag_payload_with_context(
                candidate,
                target_descriptor=target_descriptor,
                sibling_descriptors=sibling_descriptors,
                max_chars=max_chars,
            ),
            "evidence_label": overlay_to_label[candidate.overlay_candidate_id],
        }
        for candidate in definition_candidates
    ]
    return {
        "kc": _kc_prompt_payload(exemplar),
        "sibling_contrast": _sibling_descriptor_payloads(
            sibling_descriptors,
            limit=max(1, int(len(sibling_descriptors))),
        ),
        "definition_candidates": definition_payloads,
    }, overlay_to_label


def _definition_support_pack_request_payload(
    exemplar: Mapping[str, Any],
    *,
    packet: Mapping[str, Any],
    rows_by_id: Mapping[str, Mapping[str, Any]],
    assessments_by_id: Mapping[str, Mapping[str, Any]],
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
    max_chars: int,
) -> Tuple[Dict[str, Any], Dict[str, str], Dict[str, FieldCandidate]]:
    overlay_to_label: Dict[str, str] = {}
    supporting_lookup: Dict[str, FieldCandidate] = {}
    label_counter = 1

    def ensure_label(candidate_id: str) -> str:
        nonlocal label_counter
        label = overlay_to_label.get(candidate_id)
        if label:
            return label
        label = f"E{label_counter}"
        label_counter += 1
        overlay_to_label[candidate_id] = label
        return label

    support_pack_roles: Dict[str, List[Dict[str, Any]]] = {}
    for role in DEFINITION_EVIDENCE_PACKET_ROLES:
        role_payloads: List[Dict[str, Any]] = []
        for item in packet.get("roles", {}).get(role) or []:
            packet_item = dict(item or {})
            candidate_id = str(packet_item.get("overlay_candidate_id") or "")
            row = dict(rows_by_id.get(candidate_id) or {})
            candidate = (
                _supporting_lookup_candidate_from_row(
                    row,
                    assessments_by_id=assessments_by_id,
                )
                if row
                else None
            )
            if candidate is not None:
                supporting_lookup[candidate_id] = candidate
                payload = _candidate_diag_payload_with_context(
                    candidate,
                    target_descriptor=target_descriptor,
                    sibling_descriptors=sibling_descriptors,
                    max_chars=max_chars,
                )
            else:
                payload = {
                    "overlay_candidate_id": candidate_id,
                    "candidate_text": _clip_text(str(packet_item.get("candidate_text") or ""), max_chars),
                    "source_text_field": str(packet_item.get("source_text_field") or ""),
                    "score": round(float(packet_item.get("role_score") or 0.0), 6),
                    "candidate_kind": "definition",
                    "candidate_source_relation": _row_source_relation(
                        row,
                        target_kc_id=str(target_descriptor.get("kc_id") or ""),
                    ) if row else "",
                    "source_canonical_name": str(row.get("canonical_name") or ""),
                    "contrastive_alignment": {
                        "target_score": 0.0,
                        "best_sibling_score": 0.0,
                        "sibling_margin": 0.0,
                        "best_sibling_kc_id": "",
                    },
                }
            payload.update(
                {
                    "packet_role": role,
                    "anchor_eligible": bool(packet_item.get("anchor_eligible")),
                    "anchor_blocked_reason": str(packet_item.get("anchor_blocked_reason") or ""),
                    "disambiguation_only": bool(packet_item.get("disambiguation_only")),
                    "role_score": round(float(packet_item.get("role_score") or 0.0), 6),
                    "relation_score": round(float(packet_item.get("relation_score") or 0.0), 6),
                    "definition_verdict_accepted": bool(packet_item.get("definition_verdict_accepted")),
                    "definition_verdict_reasons": [
                        str(reason)
                        for reason in packet_item.get("definition_verdict_reasons") or []
                        if str(reason)
                    ],
                }
            )
            if role != "contrastive_sibling" and candidate_id:
                payload["evidence_label"] = ensure_label(candidate_id)
            role_payloads.append(payload)
        support_pack_roles[role] = role_payloads

    anchor_labels = [
        overlay_to_label[candidate_id]
        for candidate_id in [str(item) for item in packet.get("candidate_anchor_ids") or [] if str(item)]
        if candidate_id in overlay_to_label
    ]
    request_payload = {
        "kc": _kc_prompt_payload(exemplar),
        "sibling_contrast": _sibling_descriptor_payloads(
            sibling_descriptors,
            limit=max(1, int(len(sibling_descriptors))),
        ),
        "support_pack_summary": {
            "definitional_anchor_present": bool(packet.get("definitional_anchor_present")),
            "formula_anchor_allowed": bool(packet.get("formula_anchor_allowed")),
            "non_formula_anchor_present": bool(packet.get("non_formula_anchor_present")),
            "sole_anchor_blocked_reason": str(packet.get("sole_anchor_blocked_reason") or ""),
            "candidate_anchor_labels": anchor_labels,
            "hard_rules": dict(packet.get("hard_rules") or {}),
        },
        "support_pack_roles": support_pack_roles,
    }
    return request_payload, overlay_to_label, supporting_lookup


def _definition_support_pack_messages(
    exemplar: Mapping[str, Any],
    *,
    packet: Mapping[str, Any],
    rows_by_id: Mapping[str, Mapping[str, Any]],
    assessments_by_id: Mapping[str, Mapping[str, Any]],
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
    max_chars: int,
) -> List[Dict[str, str]]:
    request_payload, _, _ = _definition_support_pack_request_payload(
        exemplar,
        packet=packet,
        rows_by_id=rows_by_id,
        assessments_by_id=assessments_by_id,
        target_descriptor=target_descriptor,
        sibling_descriptors=sibling_descriptors,
        max_chars=max_chars,
    )
    return [
        {
            "role": "system",
            "content": (
                "You draft one grounded KC definition from a role-aware local support pack only. "
                "Return valid JSON only. "
                "Use the strongest same-KC definitional anchor as the core proposition. "
                "You may paraphrase conservatively and combine compatible support-pack items when needed to complete a readable definition. "
                "Use mechanism_or_scope items only to complete or minimally gloss a real definitional anchor. "
                "Use formula_or_notation only as auxiliary support unless the pack explicitly permits a formula anchor. "
                "Treat contrastive_sibling items as exclusion signals only; never cite them as supporting evidence. "
                "Do not invent textbook gloss, examples, thresholds, or neighboring-concept content."
            ),
        },
        {
            "role": "user",
            "content": (
                "Draft one `definition` field for this KC from the support pack.\n"
                "Return JSON with exactly this structure:\n"
                "{\n"
                '  "definition": {"status": "...", "text": "...", "supporting_evidence_labels": ["E1"], "abstention_reason": ""}\n'
                "}\n"
                "When grounded, supporting_evidence_labels must use only the evidence_label values attached to non-sibling support-pack items.\n"
                "Abstain if the pack lacks a real definitional anchor, if the best wording would fit a sibling concept better than the target, or if the remaining support is formula-only without enough natural-language anchoring.\n\n"
                + json.dumps(request_payload, ensure_ascii=False, indent=2)
            ),
        },
    ]


def _definition_support_pack_audit_messages(
    exemplar: Mapping[str, Any],
    *,
    packet: Mapping[str, Any],
    rows_by_id: Mapping[str, Mapping[str, Any]],
    assessments_by_id: Mapping[str, Mapping[str, Any]],
    draft_payload: Mapping[str, Any],
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
    max_chars: int,
) -> List[Dict[str, str]]:
    request_payload, _, _ = _definition_support_pack_request_payload(
        exemplar,
        packet=packet,
        rows_by_id=rows_by_id,
        assessments_by_id=assessments_by_id,
        target_descriptor=target_descriptor,
        sibling_descriptors=sibling_descriptors,
        max_chars=max_chars,
    )
    definition_payload = dict(draft_payload.get("definition") or {})
    request_payload["draft_definition"] = {
        "status": str(definition_payload.get("status") or ""),
        "text": str(definition_payload.get("text") or ""),
        "supporting_evidence_labels": [
            str(item)
            for item in definition_payload.get("supporting_evidence_labels")
            or definition_payload.get("supporting_overlay_candidate_ids")
            or []
            if str(item)
        ],
        "abstention_reason": str(definition_payload.get("abstention_reason") or ""),
    }
    return [
        {
            "role": "system",
            "content": (
                "You audit one drafted KC definition against a role-aware local support pack. "
                "Return valid JSON only. "
                "Allow concise supported paraphrase. "
                "Delete unsupported gloss, neighboring-concept bleed, and contamination leakage. "
                "Keep only evidence labels that still support the final wording. "
                "Reject formula-only wording when the pack lacks enough natural-language anchoring. "
                "If the definition can be repaired conservatively, rewrite it instead of abstaining; otherwise abstain."
            ),
        },
        {
            "role": "user",
            "content": (
                "Audit this drafted `definition` against the support pack.\n"
                "Return JSON with exactly this structure:\n"
                "{\n"
                '  "definition": {"status": "...", "text": "...", "supporting_evidence_labels": ["E1"], "abstention_reason": ""}\n'
                "}\n"
                "A grounded result may paraphrase the support pack, but every material claim must remain supported by the cited non-sibling evidence labels.\n"
                "Abstain if the remaining supported wording would still fit a sibling concept better than the target, or if only contamination / example / procedure / orphan formula content remains.\n\n"
                + json.dumps(request_payload, ensure_ascii=False, indent=2)
            ),
        },
    ]


def _definition_context_candidates(
    definition_full_candidate: Mapping[str, Any],
    *,
    supporting_lookup: Mapping[str, FieldCandidate],
    definition_candidates: Sequence[FieldCandidate],
    limit: int,
) -> List[FieldCandidate]:
    prioritized_ids = unique_preserve_order(
        [
            *[str(item) for item in definition_full_candidate.get("supporting_overlay_candidate_ids") or []],
            *[item.overlay_candidate_id for item in definition_candidates],
        ]
    )
    context_candidates: List[FieldCandidate] = []
    seen_ids: set[str] = set()
    for candidate_id in prioritized_ids:
        if candidate_id in seen_ids:
            continue
        candidate = supporting_lookup.get(candidate_id)
        if candidate is None:
            continue
        context_candidates.append(candidate)
        seen_ids.add(candidate_id)
        if len(context_candidates) >= max(1, int(limit)):
            break
    return context_candidates


def _scope_request_payload(
    exemplar: Mapping[str, Any],
    *,
    definition_full_candidate: Mapping[str, Any],
    definition_context_candidates: Sequence[FieldCandidate],
    scope_candidates: Sequence[FieldCandidate],
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
    max_chars: int,
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    definition_payloads, scope_payloads, overlay_to_label = _labeled_candidate_payloads(
        definition_context_candidates,
        scope_candidates,
        max_chars=max_chars,
    )
    definition_payloads = [
        {
            **_candidate_diag_payload_with_context(
                candidate,
                target_descriptor=target_descriptor,
                sibling_descriptors=sibling_descriptors,
                max_chars=max_chars,
            ),
            "evidence_label": overlay_to_label[candidate.overlay_candidate_id],
        }
        for candidate in definition_context_candidates
    ]
    scope_payloads = [
        {
            **_candidate_diag_payload_with_context(
                candidate,
                target_descriptor=target_descriptor,
                sibling_descriptors=sibling_descriptors,
                max_chars=max_chars,
            ),
            "evidence_label": overlay_to_label[candidate.overlay_candidate_id],
        }
        for candidate in scope_candidates
    ]
    supporting_labels = [
        overlay_to_label[str(item)]
        for item in definition_full_candidate.get("supporting_overlay_candidate_ids") or []
        if str(item) in overlay_to_label
    ]
    return {
        "kc": _kc_prompt_payload(exemplar),
        "sibling_contrast": _sibling_descriptor_payloads(
            sibling_descriptors,
            limit=max(1, int(len(sibling_descriptors))),
        ),
        "verified_definition": {
            "text": str(definition_full_candidate.get("text") or ""),
            "supporting_evidence_labels": supporting_labels,
        },
        "definition_context_evidence": definition_payloads,
        "scope_candidates": scope_payloads,
    }, overlay_to_label


def _draft_messages(
    exemplar: Mapping[str, Any],
    definition_candidates: Sequence[FieldCandidate],
    scope_candidates: Sequence[FieldCandidate],
    *,
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
    max_chars: int,
) -> List[Dict[str, str]]:
    request_payload, _ = _request_payload(
        exemplar,
        definition_candidates,
        scope_candidates,
        target_descriptor=target_descriptor,
        sibling_descriptors=sibling_descriptors,
        max_chars=max_chars,
    )
    return [
        {
            "role": "system",
            "content": (
                "You draft grounded knowledge-component fields from local evidence only. "
                "Return valid JSON only. "
                "Synthesize concise reviewer-facing prose from the provided evidence rather than copying one bad span. "
                "A field may combine multiple evidence spans when they are directly compatible. "
                "Some evidence may come from adjacent sibling concepts in the same local family; only use such evidence when it clearly defines or explains the target KC rather than the sibling. "
                "If support is sparse, noisy, or ambiguous, abstain. "
                "Do not invent facts, examples, formulas, thresholds, or scope statements not directly supported. "
                "Do not embed evidence ids or citations in the prose. "
                "If the evidence contains a logical-template definition opener such as `iff`, `such that`, or a trailing colon, do not stop at the opener when compatible cited clauses supply the missing condition."
            ),
        },
        {
            "role": "user",
            "content": (
                "Draft two fields for this KC.\n"
                "- definition: 1-2 concise sentences that directly define the target concept.\n"
                "- scope: 1 concise sentence that complements the definition by explaining interpretation, operational meaning, mechanism, practical reading, applicability, or intended use when supported.\n"
                "Prefer explanatory prose over bibliography fragments, citations, heading tails, OCR garbage, or generic family background.\n"
                "If the KC is inherently formulaic, the definition may include a formula plus a minimal explanatory gloss when the evidence supports it.\n"
                "A good scope does not need to be an explicit operating-condition statement; it may explain how to read the concept or what it captures when the evidence supports that.\n"
                "If the evidence adds nothing safely beyond the definition or is too generic/noisy, abstain on scope.\n"
                "Reject heading-like fragments, bibliography-style snippets, and incomplete logical openers as final definition text.\n"
                "Use the sibling_contrast list only as a guardrail: reject wording that fits a nearby sibling concept better than the target KC.\n"
                "Return JSON with exactly this structure:\n"
                "{\n"
                '  "definition": {"status": "...", "text": "...", "supporting_evidence_labels": ["E1"], "abstention_reason": ""},\n'
                '  "scope": {"status": "...", "text": "...", "supporting_evidence_labels": ["E2"], "abstention_reason": ""}\n'
                "}\n"
                "When grounded, supporting_evidence_labels must use the evidence_label values from the candidate list.\n\n"
                + json.dumps(request_payload, ensure_ascii=False, indent=2)
            ),
        },
    ]


def _definition_draft_messages(
    exemplar: Mapping[str, Any],
    *,
    definition_candidates: Sequence[FieldCandidate],
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
    max_chars: int,
) -> List[Dict[str, str]]:
    request_payload, _ = _definition_request_payload(
        exemplar,
        definition_candidates=definition_candidates,
        target_descriptor=target_descriptor,
        sibling_descriptors=sibling_descriptors,
        max_chars=max_chars,
    )
    return [
        {
            "role": "system",
            "content": (
                "You draft one grounded KC definition from local evidence only. "
                "Return valid JSON only. "
                "Write 1-2 concise reviewer-facing sentences that define the target concept. "
                "Stay close to the evidence wording and combine multiple spans only when they are directly compatible. "
                "Some candidates may come from nearby sibling concepts in the same family; use them only when they clearly support the target KC more than the sibling. "
                "If one span is definitional and another is mainly applicability or use context, keep the definition centered on the definitional span. "
                "If a cited span begins mid-clause, you may repair grammar by inserting the KC name or a simple copula, but do not add any new semantic claim. "
                "If a cited opener ends with `iff`, `such that`, or a trailing colon, include the missing clause only when the cited evidence explicitly supplies it. "
                "Prefer minimal, supported phrasing over explanatory elaboration. "
                "Do not replace the evidence with a standard textbook gloss unless that gloss is explicitly supported. "
                "Do not invent background facts, latent terms, thresholds, examples, or use cases."
            ),
        },
        {
            "role": "user",
            "content": (
                "Draft one `definition` field for this KC.\n"
                "Prefer the most target-defining evidence. If the concept is formulaic, a concise gloss may accompany the formula only when directly supported.\n"
                "If the evidence is fragmentary, combine only the minimum compatible fragments needed to make a readable supported definition.\n"
                "Do not draft a neighboring sibling concept even if its wording looks cleaner than the target.\n"
                "Return JSON with exactly this structure:\n"
                "{\n"
                '  "definition": {"status": "...", "text": "...", "supporting_evidence_labels": ["E1"], "abstention_reason": ""}\n'
                "}\n"
                "When grounded, supporting_evidence_labels must use the evidence_label values from the candidate list.\n\n"
                + json.dumps(request_payload, ensure_ascii=False, indent=2)
            ),
        },
    ]


def _scope_draft_messages(
    exemplar: Mapping[str, Any],
    *,
    definition_full_candidate: Mapping[str, Any],
    definition_context_candidates: Sequence[FieldCandidate],
    scope_candidates: Sequence[FieldCandidate],
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
    max_chars: int,
) -> List[Dict[str, str]]:
    request_payload, _ = _scope_request_payload(
        exemplar,
        definition_full_candidate=definition_full_candidate,
        definition_context_candidates=definition_context_candidates,
        scope_candidates=scope_candidates,
        target_descriptor=target_descriptor,
        sibling_descriptors=sibling_descriptors,
        max_chars=max_chars,
    )
    return [
        {
            "role": "system",
            "content": (
                "You draft one grounded KC scope/explanation field from local evidence only. "
                "Return valid JSON only. "
                "Use the verified definition as context, then synthesize one concise reviewer-facing explanation from the cited evidence. "
                "The scope may explain interpretation, operational meaning, mechanism, practical reading, parameter meaning, usage context, or applicability when directly supported. "
                "It should complement the verified definition rather than repeating it verbatim. "
                "A scope may be jointly supported by multiple compatible spans. "
                "Do not drift into a nearby sibling concept from the same family; keep the explanation anchored to the target KC and the verified definition. "
                "If the verified definition contains named symbols or variables, preserve their roles exactly as stated; do not swap or reinterpret them. "
                "If the evidence adds nothing safely beyond the verified definition or is too sparse, noisy, or ambiguous, abstain. "
                "Do not invent facts, examples, thresholds, or fake use cases."
            ),
        },
        {
            "role": "user",
            "content": (
                "Draft one `scope` field for this KC.\n"
                "Good scope may explain what the concept means in practice, how to read the condition or procedure, what the criterion measures/tests/captures, what a parameter controls, or when the concept is applicable.\n"
                "For formulaic verified definitions, scope may explain how to read the expression or which factors it depends on, but only by preserving the variable roles stated in the verified definition.\n"
                "Do not simply restate the verified definition. Prefer the most target-specific explanatory evidence.\n"
                "Return JSON with exactly this structure:\n"
                "{\n"
                '  "scope": {"status": "...", "text": "...", "supporting_evidence_labels": ["E2"], "abstention_reason": ""}\n'
                "}\n"
                "When grounded, supporting_evidence_labels must use the evidence_label values from the candidate list.\n\n"
                + json.dumps(request_payload, ensure_ascii=False, indent=2)
            ),
        },
    ]


def _verify_messages(
    exemplar: Mapping[str, Any],
    draft_payload: Mapping[str, Any],
    evidence_lookup: Mapping[str, Mapping[str, Any]],
    *,
    sibling_descriptors: Sequence[Mapping[str, Any]],
    max_chars: int,
) -> List[Dict[str, str]]:
    verify_lines = [
        f"kc_id: {str(exemplar.get('kc_id') or '')}",
        f"canonical_name: {str(exemplar.get('canonical_name') or '')}",
        f"hierarchy_context: {json.dumps(_descriptor_context_items(exemplar), ensure_ascii=False)}",
        f"sibling_contrast: {json.dumps(_sibling_descriptor_payloads(sibling_descriptors, limit=max(1, int(len(sibling_descriptors)))), ensure_ascii=False)}",
        "",
        "Return only this JSON object shape:",
        '{',
        '  "definition": {"status": "...", "text": "...", "supporting_evidence_labels": ["E1"], "abstention_reason": ""},',
        '  "scope": {"status": "...", "text": "...", "supporting_evidence_labels": ["E2"], "abstention_reason": ""}',
        '}',
        "",
        "Verify each field against its cited evidence. Rewrite conservatively or abstain.",
        "For scope, a valid grounded field may explain interpretation, operational meaning, mechanism, practical reading, parameter meaning, usage context, or applicability; it does not need to be a hard operating-condition statement.",
        "",
    ]
    for field_name in ("definition", "scope"):
        field_payload = dict(draft_payload.get(field_name) or {})
        ids = [str(item) for item in field_payload.get("supporting_evidence_labels") or field_payload.get("supporting_overlay_candidate_ids") or []]
        verify_lines.append(f"{field_name}_draft_text: {str(field_payload.get('text') or '')}")
        verify_lines.append(f"{field_name}_draft_labels: {ids}")
        verify_lines.append(f"{field_name}_evidence:")
        for candidate_id in ids:
            if candidate_id not in evidence_lookup:
                continue
            verify_lines.append(
                f"- {candidate_id}: {_clip_text(str((evidence_lookup.get(candidate_id) or {}).get('text') or ''), max_chars)}"
            )
        verify_lines.append("")
    return [
        {
            "role": "system",
            "content": (
                "You verify drafted KC fields against cited local evidence. "
                "Return valid JSON only. "
                "A field may be jointly supported by multiple cited spans. "
                "Keep only claims directly supported by the cited evidence. "
                "If a drafted field contains unsupported material, rewrite it conservatively using only supported content or abstain. "
                "Do not require one single span to carry the whole draft when multiple cited spans jointly support it. "
                "Also reject a field when its core proposition matches a nearby sibling concept more strongly than the target KC. "
                "Use the cited evidence_label values when returning supporting_evidence_labels."
            ),
        },
        {
            "role": "user",
            "content": "\n".join(verify_lines),
        },
    ]


def _definition_verify_messages(
    exemplar: Mapping[str, Any],
    *,
    draft_payload: Mapping[str, Any],
    evidence_lookup: Mapping[str, Mapping[str, Any]],
    sibling_descriptors: Sequence[Mapping[str, Any]],
    max_chars: int,
) -> List[Dict[str, str]]:
    definition_payload = dict(draft_payload.get("definition") or {})
    ids = [str(item) for item in definition_payload.get("supporting_evidence_labels") or definition_payload.get("supporting_overlay_candidate_ids") or []]
    verify_lines = [
        f"kc_id: {str(exemplar.get('kc_id') or '')}",
        f"canonical_name: {str(exemplar.get('canonical_name') or '')}",
        f"hierarchy_context: {json.dumps(_descriptor_context_items(exemplar), ensure_ascii=False)}",
        f"sibling_contrast: {json.dumps(_sibling_descriptor_payloads(sibling_descriptors, limit=max(1, int(len(sibling_descriptors)))), ensure_ascii=False)}",
        "",
        "Return only this JSON object shape:",
        "{",
        '  "definition": {"status": "...", "text": "...", "supporting_evidence_labels": ["E1"], "abstention_reason": ""}',
        "}",
        "",
        "Verify the drafted definition against its cited evidence.",
        "Keep only claims directly supported by the cited evidence and prefer the minimum supported wording.",
        "A definition may be jointly supported by multiple cited spans, but do not keep explanatory gloss that is not clearly grounded.",
        "If the draft can be made supported by deleting unsupported gloss or by turning a cited fragment into a grammatical sentence without changing its meaning, rewrite it instead of abstaining.",
        "Do not keep a definition that stops at a heading-like title, bibliography snippet, `iff` opener, `such that` opener, or trailing colon when the cited evidence has not supplied the missing clause.",
        "",
        f"definition_draft_text: {str(definition_payload.get('text') or '')}",
        f"definition_draft_labels: {ids}",
        "definition_evidence:",
    ]
    for candidate_id in ids:
        if candidate_id not in evidence_lookup:
            continue
        verify_lines.append(
            f"- {candidate_id}: {_clip_text(str((evidence_lookup.get(candidate_id) or {}).get('text') or ''), max_chars)}"
        )
    return [
        {
            "role": "system",
            "content": (
                "You verify one drafted KC definition against cited local evidence. "
                "Return valid JSON only. "
                "Keep only claims directly supported by the cited evidence. "
                "A definition may be jointly supported by multiple spans. "
                "Prefer the shortest fully supported formulation over a richer but partially unsupported paraphrase. "
                "If the draft is not fully supported, rewrite it conservatively or abstain. "
                "Reject heading-like titles, bibliography-like text, and incomplete logical-template openers as final definitions. "
                "Reject or rewrite any draft whose core proposition fits a nearby sibling concept better than the target KC. "
                "When possible, salvage a supported definition by staying very close to the cited wording rather than dropping the field."
            ),
        },
        {
            "role": "user",
            "content": "\n".join(verify_lines),
        },
    ]


def _scope_verify_messages(
    exemplar: Mapping[str, Any],
    *,
    definition_full_candidate: Mapping[str, Any],
    draft_payload: Mapping[str, Any],
    evidence_lookup: Mapping[str, Mapping[str, Any]],
    sibling_descriptors: Sequence[Mapping[str, Any]],
    max_chars: int,
) -> List[Dict[str, str]]:
    scope_payload = dict(draft_payload.get("scope") or {})
    ids = [str(item) for item in scope_payload.get("supporting_evidence_labels") or scope_payload.get("supporting_overlay_candidate_ids") or []]
    verify_lines = [
        f"kc_id: {str(exemplar.get('kc_id') or '')}",
        f"canonical_name: {str(exemplar.get('canonical_name') or '')}",
        f"hierarchy_context: {json.dumps(_descriptor_context_items(exemplar), ensure_ascii=False)}",
        f"verified_definition_text: {str(definition_full_candidate.get('text') or '')}",
        f"sibling_contrast: {json.dumps(_sibling_descriptor_payloads(sibling_descriptors, limit=max(1, int(len(sibling_descriptors)))), ensure_ascii=False)}",
        "",
        "Return only this JSON object shape:",
        "{",
        '  "scope": {"status": "...", "text": "...", "supporting_evidence_labels": ["E2"], "abstention_reason": ""}',
        "}",
        "",
        "Verify the drafted scope against its cited evidence.",
        "A valid grounded scope may explain interpretation, operational meaning, mechanism, practical reading, parameter meaning, usage context, or applicability when directly supported.",
        "Keep only claims directly supported by the cited evidence, but allow multiple cited spans to jointly support the scope.",
        "When the verified definition contains named symbols or variables, the scope must preserve their stated roles exactly.",
        "If the draft merely repeats the verified definition without distinct supported explanatory content, abstain.",
        "",
        f"scope_draft_text: {str(scope_payload.get('text') or '')}",
        f"scope_draft_labels: {ids}",
        "scope_evidence:",
    ]
    for candidate_id in ids:
        if candidate_id not in evidence_lookup:
            continue
        verify_lines.append(
            f"- {candidate_id}: {_clip_text(str((evidence_lookup.get(candidate_id) or {}).get('text') or ''), max_chars)}"
        )
    return [
        {
            "role": "system",
            "content": (
                "You verify one drafted KC scope/explanation field against cited local evidence. "
                "Return valid JSON only. "
                "Keep only claims directly supported by the cited evidence. "
                "A scope may be jointly supported by multiple spans. "
                "Allow concise explanatory scope when it complements the verified definition and remains evidence-grounded. "
                "For formula-based definitions, it is valid to explain how to read the expression or which explicit factors it depends on, but only if the variable roles stay consistent with the verified definition. "
                "Reject scope that drifts into a nearby sibling concept or explains the wrong member of a tightly related local family. "
                "If the scope is unsupported, redundant with the verified definition, or too generic, abstain."
            ),
        },
        {
            "role": "user",
            "content": "\n".join(verify_lines),
        },
    ]


def _normalize_field_payload(
    payload: Mapping[str, Any],
    *,
    allowed_ids: Sequence[str],
    id_lookup: Mapping[str, str],
) -> Dict[str, Any]:
    allowed_id_set = {str(item) for item in allowed_ids}
    raw_status = str(payload.get("status") or "abstained").strip().lower()
    status = "grounded" if raw_status in {"grounded", "verified", "supported"} else "abstained"
    text = _normalize_ws(payload.get("text") or "")
    raw_ids = payload.get("supporting_evidence_labels")
    if raw_ids is None:
        raw_ids = payload.get("supporting_overlay_candidate_ids") or []
    supporting_ids = [
        id_lookup.get(str(item), str(item))
        for item in unique_preserve_order(raw_ids)
        if str(item) in allowed_id_set or str(item) in id_lookup.values()
    ]
    abstention_reason = _normalize_ws(payload.get("abstention_reason") or "")
    if status != "grounded":
        return {
            "status": "abstained",
            "text": "",
            "supporting_overlay_candidate_ids": [],
            "abstention_reason": abstention_reason or "insufficient_evidence",
        }
    if not text or not supporting_ids:
        return {
            "status": "abstained",
            "text": "",
            "supporting_overlay_candidate_ids": [],
            "abstention_reason": abstention_reason or "insufficient_evidence",
        }
    return {
        "status": "grounded",
        "text": text,
        "supporting_overlay_candidate_ids": supporting_ids,
        "abstention_reason": abstention_reason,
    }


def _normalize_model_payload(
    payload: Mapping[str, Any],
    *,
    allowed_ids: Sequence[str],
    id_lookup: Mapping[str, str],
) -> Dict[str, Any]:
    return {
        "definition": _normalize_field_payload(dict(payload.get("definition") or {}), allowed_ids=allowed_ids, id_lookup=id_lookup),
        "scope": _normalize_field_payload(dict(payload.get("scope") or {}), allowed_ids=allowed_ids, id_lookup=id_lookup),
    }


def _call_phase(
    *,
    runtime: Step67ModelRuntime,
    counters: Counter[str],
    budget_state: Dict[str, Any],
    phase: str,
    request_payload: Dict[str, Any],
    schema: Dict[str, Any],
    messages: List[Dict[str, str]],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    max_calls = max(1, int(budget_state.get("max_calls") or 1))
    current_calls = int(counters.get("llm_calls") or 0)
    if current_calls >= max_calls:
        blocked_phases = [str(item) for item in budget_state.get("blocked_phases") or [] if str(item)]
        blocked_phases.append(str(phase))
        budget_state["blocked_phases"] = unique_preserve_order(blocked_phases)
        budget_state["calls_used"] = current_calls
        budget_state["remaining_calls"] = max(0, max_calls - current_calls)
        budget_state["budget_exhausted"] = True
        counters["llm_budget_exhaustions"] += 1
        counters[f"{phase}_budget_blocked"] += 1
        raise LLMCallBudgetExceededError(
            f"{phase} blocked by per-KC llm call budget ({current_calls}/{max_calls})"
        )

    counters["llm_calls"] += 1
    counters[f"{phase}_calls"] += 1
    phase_call_order = [str(item) for item in budget_state.get("phase_call_order") or [] if str(item)]
    phase_call_order.append(str(phase))
    budget_state["phase_call_order"] = phase_call_order
    phase_call_counts = {
        str(key): int(value)
        for key, value in dict(budget_state.get("phase_call_counts") or {}).items()
        if str(key)
    }
    phase_call_counts[str(phase)] = int(phase_call_counts.get(str(phase), 0)) + 1
    budget_state["phase_call_counts"] = phase_call_counts
    budget_state["calls_used"] = int(counters.get("llm_calls") or 0)
    budget_state["remaining_calls"] = max(0, max_calls - int(counters.get("llm_calls") or 0))
    model_profile = normalize_step67_model_profile(
        runtime.model_profile
        or {
            "generation_model": runtime.model,
            "thinking_enabled": runtime.think,
        }
    )
    resolved_messages = apply_step67_model_profile_to_messages(messages, model_profile)
    think_flag = step67_model_profile_think_flag(model_profile)
    invoker = (
        runtime.draft_invoker
        if phase in {"draft", "definition_redraft", "scope_redraft", "definition_support_pack_draft"}
        else runtime.verify_invoker
    )
    if invoker is not None:
        result = invoker(
            {
                "phase": phase,
                "request_payload": request_payload,
                "schema": schema,
                "messages": resolved_messages,
                "model": runtime.model,
                "model_profile": dict(model_profile),
            }
        )
        if isinstance(result, tuple) and len(result) == 2:
            payload, meta = result
        else:
            payload, meta = result, {"source": "custom_invoker"}
        if not isinstance(payload, Mapping):
            raise RuntimeError(f"{phase} invoker returned non-mapping payload")
        return dict(payload), dict(meta or {})

    errors: List[str] = []
    for attempt in range(max(1, int(runtime.max_retries))):
        try:
            payload, outer, raw = ollama_chat_json(
                base_url=runtime.base_url,
                model=runtime.model,
                messages=resolved_messages,
                format_schema=schema,
                temperature=float(runtime.temperature),
                top_p=float(runtime.top_p),
                num_ctx=int(runtime.num_ctx),
                repeat_penalty=float(runtime.repeat_penalty),
                think=think_flag,
                response_parse_mode=str(model_profile.get("response_parse_mode") or ""),
                strip_thought_block_before_parse=bool(model_profile.get("strip_thought_block_before_parse")),
                timeout_s=float(runtime.timeout_seconds),
            )
            if not isinstance(payload, Mapping):
                raise RuntimeError(f"{phase} model returned non-object payload")
            return dict(payload), {
                "source": "ollama",
                "attempt": attempt + 1,
                "raw_response": raw,
                "outer": outer,
            }
        except Exception as exc:
            errors.append(f"Attempt{attempt + 1}:{type(exc).__name__}:{exc}")
    counters[f"{phase}_runtime_failures"] += 1
    raise RuntimeError(";".join(errors))


def _payload_has_expected_shape(payload: Mapping[str, Any]) -> bool:
    if not isinstance(payload, Mapping):
        return False
    for field_name in ("definition", "scope"):
        field_payload = payload.get(field_name)
        if not isinstance(field_payload, Mapping):
            return False
        if "status" not in field_payload or "text" not in field_payload:
            return False
        if "supporting_evidence_labels" not in field_payload and "supporting_overlay_candidate_ids" not in field_payload:
            return False
        if "abstention_reason" not in field_payload:
            return False
    return True


def _single_field_payload_has_expected_shape(payload: Mapping[str, Any], *, field_name: str) -> bool:
    if not isinstance(payload, Mapping):
        return False
    field_payload = payload.get(field_name)
    if not isinstance(field_payload, Mapping):
        return False
    if "status" not in field_payload or "text" not in field_payload:
        return False
    if "supporting_evidence_labels" not in field_payload and "supporting_overlay_candidate_ids" not in field_payload:
        return False
    if "abstention_reason" not in field_payload:
        return False
    return True


def _scope_payload_has_expected_shape(payload: Mapping[str, Any]) -> bool:
    return _single_field_payload_has_expected_shape(payload, field_name="scope")


def _definition_payload_has_expected_shape(payload: Mapping[str, Any]) -> bool:
    return _single_field_payload_has_expected_shape(payload, field_name="definition")


def _candidate_value_from_verified(
    *,
    field_name: str,
    normalized_field: Mapping[str, Any],
    supporting_lookup: Mapping[str, FieldCandidate],
    selection_reason: str | None = None,
) -> Dict[str, Any]:
    if str(normalized_field.get("status") or "") != "grounded":
        return {}
    supporting_ids = [str(item) for item in normalized_field.get("supporting_overlay_candidate_ids") or []]
    if not supporting_ids:
        return {}
    first_candidate = supporting_lookup.get(supporting_ids[0])
    source_text_field = first_candidate.source_text_field if first_candidate is not None else ""
    return _candidate_value(
        text=str(normalized_field.get("text") or ""),
        supporting_ids=supporting_ids,
        selection_reason=selection_reason or f"{field_name}_llm_multispan_verified",
        source_text_field=source_text_field,
    )


def _candidate_value_from_single_candidate(
    *,
    field_name: str,
    candidate: FieldCandidate,
    selection_reason: str,
) -> Dict[str, Any]:
    return _candidate_value(
        text=candidate.text,
        supporting_ids=[candidate.overlay_candidate_id],
        selection_reason=selection_reason,
        source_text_field=candidate.source_text_field,
    )


def _definition_binding_overlap_count(definition_text: str, candidate_text: str) -> int:
    return len(_content_token_set(definition_text) & _content_token_set(candidate_text))


DEFINITION_BINDING_STRICT_BETTER_REASONS: set[str] = {
    "non_local_source",
    "context_only_anchor",
    "procedure_or_example_anchor",
    "formula_only_anchor",
    "broad_scope_anchor",
    "cross_concept_anchor",
    "weak_target_alignment",
    "low_definition_text_overlap",
}


def _definition_support_binding_diag(
    *,
    repair_state: str,
    repair_applied: bool,
    repair_reason: str,
    repair_attempt_reason: str,
    current_support_ids: Sequence[str],
    out_of_pool_support_ids: Sequence[str],
    chosen_support_ids: Sequence[str],
    current_binding_mode: str,
    final_binding_mode: str,
    stronger_same_kc_candidate_existed: bool,
    candidate_anchor_pool_considered: Sequence[Mapping[str, Any]],
    weaker_anchor_rejections: Mapping[str, Sequence[str]],
) -> Dict[str, Any]:
    return {
        "repair_state": str(repair_state or ""),
        "repair_attempted": str(repair_state or "").startswith("repair_attempted"),
        "repair_applied": bool(repair_applied),
        "repair_reason": str(repair_reason or ""),
        "repair_attempt_reason": str(repair_attempt_reason or ""),
        "current_support_ids": [str(item) for item in current_support_ids if str(item)],
        "out_of_pool_support_ids": [str(item) for item in out_of_pool_support_ids if str(item)],
        "chosen_support_ids": [str(item) for item in chosen_support_ids if str(item)],
        "current_binding_mode": str(current_binding_mode or "none"),
        "final_binding_mode": str(final_binding_mode or "none"),
        "stronger_same_kc_candidate_existed": bool(stronger_same_kc_candidate_existed),
        "candidate_anchor_pool_considered": [dict(item) for item in candidate_anchor_pool_considered],
        "weaker_anchor_rejections": {
            str(key): [str(item) for item in value if str(item)]
            for key, value in dict(weaker_anchor_rejections or {}).items()
            if str(key)
        },
    }


def _definition_grounding_diag(
    *,
    definition_candidates: Sequence[FieldCandidate],
    preservation_definition_candidates: Sequence[FieldCandidate],
    definition_support_pack: Sequence[Mapping[str, Any]],
    preservation_draft_response: Mapping[str, Any],
    preservation_verify_response: Mapping[str, Any],
    rescue_used: bool,
    rescue_draft_response: Mapping[str, Any],
    rescue_verify_response: Mapping[str, Any],
    definition_redraft_response: Mapping[str, Any],
    definition_redraft_verify_response: Mapping[str, Any],
    final_definition_candidate: Mapping[str, Any],
    control_fallback_candidate: Optional[FieldCandidate],
    control_fallback_source_phase: str,
    control_fallback_salvage_candidate: Optional[FieldCandidate],
) -> Dict[str, Any]:
    preservation_draft = dict(preservation_draft_response.get("definition") or {})
    preservation_verify = dict(preservation_verify_response.get("definition") or {})
    rescue_draft = dict(rescue_draft_response.get("definition") or {})
    rescue_verify = dict(rescue_verify_response.get("definition") or {})
    definition_redraft = dict(definition_redraft_response.get("definition") or {})
    definition_redraft_verify = dict(definition_redraft_verify_response.get("definition") or {})
    final_status = str(final_definition_candidate.get("status") or "")
    final_selection_reason = str(final_definition_candidate.get("selection_reason") or "")
    control_fallback_applied = final_selection_reason in {
        "definition_full_candidate_draft_supported_single_span_fallback",
        "definition_full_candidate_source_faithful_fallback_surface_normalization",
        "definition_full_candidate_draft_supported_single_span_fallback_same_kc_salvage",
        "definition_full_candidate_source_faithful_fallback_surface_same_kc_salvage_normalization",
    }

    if final_status == ENRICHMENT_LAYER_STATUS_GROUNDED:
        if final_selection_reason == "definition_full_candidate_draft_supported_single_span_fallback":
            collapse_stage = "control_fallback_applied"
        elif final_selection_reason == "definition_full_candidate_source_faithful_fallback_surface_normalization":
            collapse_stage = "control_fallback_surface_normalization_applied"
        elif final_selection_reason == "definition_full_candidate_draft_supported_single_span_fallback_same_kc_salvage":
            collapse_stage = "control_fallback_same_kc_salvage_applied"
        elif final_selection_reason == "definition_full_candidate_source_faithful_fallback_surface_same_kc_salvage_normalization":
            collapse_stage = "control_fallback_same_kc_salvage_surface_normalization_applied"
        else:
            collapse_stage = "grounded_before_control_fallback"
    elif not definition_candidates:
        collapse_stage = "no_usable_candidate_pool"
    elif str(preservation_draft.get("status") or "") != ENRICHMENT_LAYER_STATUS_GROUNDED:
        collapse_stage = "no_binding_after_preservation_draft_abstention"
    elif str(preservation_verify.get("status") or "") == "abstained":
        collapse_stage = "no_binding_after_preservation_verify_rejection"
    elif rescue_used and str(rescue_draft.get("status") or "") != ENRICHMENT_LAYER_STATUS_GROUNDED:
        collapse_stage = "no_binding_after_rescue_draft_abstention"
    elif rescue_used and str(rescue_verify.get("status") or "") == "abstained":
        collapse_stage = "no_binding_after_rescue_verify_rejection"
    elif str(definition_redraft_verify.get("status") or "") == "abstained":
        collapse_stage = "no_binding_after_definition_redraft_verify_rejection"
    else:
        collapse_stage = "no_binding_after_control_path_gating"

    return {
        "candidate_pool_size": len(definition_candidates),
        "preservation_candidate_pool_size": len(preservation_definition_candidates),
        "support_pack_size": len(definition_support_pack),
        "preservation_draft_status": str(preservation_draft.get("status") or ""),
        "preservation_verify_status": str(preservation_verify.get("status") or ""),
        "preservation_verify_reason": str(preservation_verify.get("abstention_reason") or ""),
        "rescue_used": bool(rescue_used),
        "rescue_draft_status": str(rescue_draft.get("status") or ""),
        "rescue_verify_status": str(rescue_verify.get("status") or ""),
        "rescue_verify_reason": str(rescue_verify.get("abstention_reason") or ""),
        "definition_redraft_status": str(definition_redraft.get("status") or ""),
        "definition_redraft_verify_status": str(definition_redraft_verify.get("status") or ""),
        "definition_redraft_verify_reason": str(definition_redraft_verify.get("abstention_reason") or ""),
        "control_fallback_candidate_present": bool(control_fallback_candidate),
        "control_fallback_source_phase": str(control_fallback_source_phase or ""),
        "control_fallback_support_ids": (
            [str(control_fallback_candidate.overlay_candidate_id)]
            if control_fallback_candidate is not None
            else []
        ),
        "control_fallback_applied": control_fallback_applied,
        "draft_supported_single_span_fallback_candidate_present": bool(control_fallback_candidate),
        "draft_supported_single_span_fallback_source_phase": str(control_fallback_source_phase or ""),
        "draft_supported_single_span_fallback_support_ids": (
            [str(control_fallback_candidate.overlay_candidate_id)]
            if control_fallback_candidate is not None
            else []
        ),
        "draft_supported_single_span_fallback_applied": control_fallback_applied,
        "draft_supported_single_span_fallback_normalized_applied": (
            final_selection_reason in {
                "definition_full_candidate_source_faithful_fallback_surface_normalization",
                "definition_full_candidate_source_faithful_fallback_surface_same_kc_salvage_normalization",
            }
        ),
        "draft_supported_single_span_fallback_salvage_candidate_present": bool(control_fallback_salvage_candidate),
        "draft_supported_single_span_fallback_salvage_support_ids": (
            [str(control_fallback_salvage_candidate.overlay_candidate_id)]
            if control_fallback_salvage_candidate is not None
            else []
        ),
        "draft_supported_single_span_fallback_salvage_applied": final_selection_reason in {
            "definition_full_candidate_draft_supported_single_span_fallback_same_kc_salvage",
            "definition_full_candidate_source_faithful_fallback_surface_same_kc_salvage_normalization",
        },
        "final_selection_reason": final_selection_reason,
        "collapse_stage": collapse_stage,
    }


def _definition_binding_candidate_analysis(
    candidate: FieldCandidate,
    *,
    definition_text: str,
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    assessment = dict(candidate.assessment)
    source_relation = _row_source_relation(
        candidate.row,
        target_kc_id=str(target_descriptor.get("kc_id") or ""),
    )
    overlap_count = _definition_binding_overlap_count(definition_text, candidate.text)
    reject_reasons: List[str] = []
    if source_relation != "local":
        reject_reasons.append("non_local_source")
    if bool(assessment.get("context_candidate")) and not bool(assessment.get("definition_candidate")):
        reject_reasons.append("context_only_anchor")
    if bool(candidate.row.get("is_procedure_like")) or bool(candidate.row.get("is_example_like")) or "procedural_fragment" in candidate.issues:
        reject_reasons.append("procedure_or_example_anchor")
    if bool(candidate.row.get("is_formula_like")) and not bool(assessment.get("definition_candidate")):
        reject_reasons.append("formula_only_anchor")
    if candidate.row.get("strong_same_topic") is False:
        reject_reasons.append("weak_topic_anchor")
    if any(issue in {"generic_background", "generic_context_lead_in", "citation_or_slide_context"} for issue in candidate.issues):
        reject_reasons.append("broad_scope_anchor")
    if _sibling_boundary_risk(
        candidate.text,
        target_descriptor=target_descriptor,
        sibling_descriptors=sibling_descriptors,
    ):
        reject_reasons.append("cross_concept_anchor")
    if not candidate.has_name_anchor and candidate.title_overlap <= 0 and candidate.context_overlap <= 0:
        reject_reasons.append("weak_target_alignment")
    if not candidate.single_span_accepted:
        reject_reasons.append("needs_multirow_support")
    if overlap_count <= 0:
        reject_reasons.append("low_definition_text_overlap")

    binding_score = float(candidate.score)
    binding_score += 8.0 if source_relation == "local" else -10.0
    binding_score += 6.0 if bool(assessment.get("definition_candidate")) else 0.0
    binding_score += 3.0 if candidate.single_span_accepted else 0.0
    binding_score += 2.0 if candidate.has_name_anchor else 0.0
    binding_score += 1.5 * float(min(candidate.title_overlap, 2))
    binding_score += 1.0 * float(min(candidate.context_overlap, 3))
    binding_score += 4.0 * float(min(overlap_count, 4))

    penalty_map = {
        "non_local_source": 12.0,
        "context_only_anchor": 8.0,
        "procedure_or_example_anchor": 9.0,
        "formula_only_anchor": 7.0,
        "weak_topic_anchor": 10.0,
        "broad_scope_anchor": 6.0,
        "cross_concept_anchor": 12.0,
        "weak_target_alignment": 8.0,
        "low_definition_text_overlap": 5.0,
    }
    for reason in reject_reasons:
        binding_score -= penalty_map.get(reason, 0.0)

    return {
        "candidate": candidate,
        "source_relation": source_relation,
        "overlap_count": overlap_count,
        "reject_reasons": unique_preserve_order(reject_reasons),
        "binding_score": round(binding_score, 6),
    }


def _definition_binding_replacement_is_strictly_better(
    *,
    current_analysis: Optional[Mapping[str, Any]],
    proposed_analysis: Mapping[str, Any],
) -> bool:
    if current_analysis is None:
        return True

    current_reject_reasons = set(current_analysis.get("reject_reasons") or [])
    proposed_reject_reasons = set(proposed_analysis.get("reject_reasons") or [])
    current_severe = current_reject_reasons & DEFINITION_BINDING_STRICT_BETTER_REASONS
    proposed_severe = proposed_reject_reasons & DEFINITION_BINDING_STRICT_BETTER_REASONS
    current_overlap = int(current_analysis.get("overlap_count") or 0)
    proposed_overlap = int(proposed_analysis.get("overlap_count") or 0)

    if proposed_overlap < current_overlap:
        return False
    if len(proposed_severe) > len(current_severe):
        return False

    if current_severe - proposed_severe:
        return True
    if "needs_multirow_support" in current_reject_reasons and "needs_multirow_support" not in proposed_reject_reasons:
        return proposed_overlap >= current_overlap
    if "low_definition_text_overlap" in current_reject_reasons and "low_definition_text_overlap" not in proposed_reject_reasons:
        return proposed_overlap > current_overlap
    return False


def _definition_binding_candidate_diag(
    analysis: Mapping[str, Any],
    *,
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
    max_chars: int,
    chosen_support_ids: Sequence[str],
) -> Dict[str, Any]:
    candidate = analysis["candidate"]
    payload = _candidate_diag_payload_with_context(
        candidate,
        target_descriptor=target_descriptor,
        sibling_descriptors=sibling_descriptors,
        max_chars=max_chars,
    )
    payload["binding_score"] = float(analysis.get("binding_score") or 0.0)
    payload["binding_source_relation"] = str(analysis.get("source_relation") or "")
    payload["binding_overlap_with_definition"] = int(analysis.get("overlap_count") or 0)
    payload["binding_reject_reasons"] = [str(item) for item in analysis.get("reject_reasons") or [] if str(item)]
    payload["chosen_for_final_binding"] = str(candidate.overlay_candidate_id) in {
        str(item) for item in chosen_support_ids or [] if str(item)
    }
    return payload


def _repair_definition_support_binding(
    *,
    current_value: Mapping[str, Any],
    definition_candidates: Sequence[FieldCandidate],
    rows_by_id: Mapping[str, Mapping[str, Any]],
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
    max_support_rows: int,
    max_chars: int,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    grounded = str(current_value.get("status") or "") == ENRICHMENT_LAYER_STATUS_GROUNDED
    current_support_ids = [
        str(item) for item in current_value.get("supporting_overlay_candidate_ids") or [] if str(item)
    ]
    current_binding_mode = "multi_row" if len(current_support_ids) > 1 else ("single_row" if current_support_ids else "none")
    if not grounded:
        return {}, _definition_support_binding_diag(
            repair_state="no_binding_possible",
            repair_applied=False,
            repair_reason="no_grounded_definition_candidate",
            repair_attempt_reason="",
            current_support_ids=current_support_ids,
            out_of_pool_support_ids=[],
            chosen_support_ids=[],
            current_binding_mode=current_binding_mode,
            final_binding_mode="none",
            stronger_same_kc_candidate_existed=False,
            candidate_anchor_pool_considered=[],
            weaker_anchor_rejections={},
        )

    definition_text = _normalize_ws(current_value.get("text") or "")
    candidate_pool: List[FieldCandidate] = []
    seen_ids: set[str] = set()
    for candidate in definition_candidates:
        candidate_id = str(candidate.overlay_candidate_id)
        if not candidate_id or candidate_id in seen_ids:
            continue
        candidate_pool.append(candidate)
        seen_ids.add(candidate_id)

    pool_by_id = {candidate.overlay_candidate_id: candidate for candidate in candidate_pool}
    out_of_pool_support_ids = [
        candidate_id for candidate_id in current_support_ids if candidate_id not in pool_by_id
    ]
    if not candidate_pool:
        return dict(current_value), _definition_support_binding_diag(
            repair_state="no_binding_possible",
            repair_applied=False,
            repair_reason="no_active_definition_anchor_pool",
            repair_attempt_reason="",
            current_support_ids=current_support_ids,
            out_of_pool_support_ids=out_of_pool_support_ids,
            chosen_support_ids=current_support_ids,
            current_binding_mode=current_binding_mode,
            final_binding_mode=current_binding_mode,
            stronger_same_kc_candidate_existed=False,
            candidate_anchor_pool_considered=[],
            weaker_anchor_rejections={},
        )

    analyses = [
        _definition_binding_candidate_analysis(
            candidate,
            definition_text=definition_text,
            target_descriptor=target_descriptor,
            sibling_descriptors=sibling_descriptors,
        )
        for candidate in candidate_pool
    ]
    analyses.sort(
        key=lambda item: (
            -float(item.get("binding_score") or 0.0),
            str(item["candidate"].overlay_candidate_id),
        )
    )
    current_in_pool_analyses = [
        analysis for analysis in analyses if analysis["candidate"].overlay_candidate_id in current_support_ids
    ]
    current_best_analysis = current_in_pool_analyses[0] if current_in_pool_analyses else None
    local_analyses = [analysis for analysis in analyses if str(analysis.get("source_relation") or "") == "local"]
    selected_primary = local_analyses[0] if local_analyses else analyses[0]
    current_support_weak = bool(out_of_pool_support_ids) or not current_in_pool_analyses
    if current_best_analysis is not None:
        weak_current_reasons = {
            "context_only_anchor",
            "procedure_or_example_anchor",
            "formula_only_anchor",
            "weak_topic_anchor",
            "broad_scope_anchor",
            "cross_concept_anchor",
            "weak_target_alignment",
            "low_definition_text_overlap",
        }
        current_support_weak = current_support_weak or bool(
            weak_current_reasons & set(current_best_analysis.get("reject_reasons") or [])
        )
    stronger_same_kc_candidate_existed = bool(
        current_best_analysis is not None
        and selected_primary["candidate"].overlay_candidate_id != current_best_analysis["candidate"].overlay_candidate_id
        and float(selected_primary.get("binding_score") or 0.0)
        >= float(current_best_analysis.get("binding_score") or 0.0) + 4.0
    )
    repair_attempted = bool(out_of_pool_support_ids or stronger_same_kc_candidate_existed or current_support_weak)
    repair_attempt_reason = ""

    chosen_support_ids = [
        candidate_id
        for candidate_id in current_support_ids
        if candidate_id in pool_by_id
    ][: max(1, int(max_support_rows))]
    if repair_attempted:
        chosen_support_ids = [selected_primary["candidate"].overlay_candidate_id]
        repair_attempt_reason = (
            "blocked_out_of_pool_definition_binding"
            if out_of_pool_support_ids
            else "promoted_stronger_same_kc_definition_anchor"
            if stronger_same_kc_candidate_existed
            else "replaced_weak_definition_anchor"
        )
        allow_multi_row = bool(
            "needs_multirow_support" in set(selected_primary.get("reject_reasons") or [])
            or len(current_support_ids) > 1
        )
        if allow_multi_row and int(max_support_rows) > 1:
            for analysis in local_analyses[1:]:
                candidate_id = analysis["candidate"].overlay_candidate_id
                reject_reasons = set(analysis.get("reject_reasons") or [])
                if candidate_id in chosen_support_ids:
                    continue
                if {"non_local_source", "cross_concept_anchor", "weak_topic_anchor"} & reject_reasons:
                    continue
                if int(analysis.get("overlap_count") or 0) <= 0 and int(selected_primary.get("overlap_count") or 0) <= 0:
                    continue
                chosen_support_ids.append(candidate_id)
                repair_attempt_reason = "promoted_bounded_multi_row_definition_binding"
                break

    chosen_support_ids = chosen_support_ids[: max(1, int(max_support_rows))]
    chosen_set = {str(item) for item in chosen_support_ids if str(item)}
    candidate_anchor_pool_considered = [
        _definition_binding_candidate_diag(
            analysis,
            target_descriptor=target_descriptor,
            sibling_descriptors=sibling_descriptors,
            max_chars=max_chars,
            chosen_support_ids=chosen_support_ids,
        )
        for analysis in analyses
    ]
    weaker_anchor_rejections = {
        str(analysis["candidate"].overlay_candidate_id): [str(item) for item in analysis.get("reject_reasons") or [] if str(item)]
        for analysis in analyses
        if str(analysis["candidate"].overlay_candidate_id) not in chosen_set
    }

    if not chosen_support_ids:
        return {}, _definition_support_binding_diag(
            repair_state="no_binding_possible",
            repair_applied=False,
            repair_reason="no_valid_definition_anchor_after_repair",
            repair_attempt_reason=repair_attempt_reason,
            current_support_ids=current_support_ids,
            out_of_pool_support_ids=out_of_pool_support_ids,
            chosen_support_ids=[],
            current_binding_mode=current_binding_mode,
            final_binding_mode="none",
            stronger_same_kc_candidate_existed=stronger_same_kc_candidate_existed,
            candidate_anchor_pool_considered=candidate_anchor_pool_considered,
            weaker_anchor_rejections=weaker_anchor_rejections,
        )

    non_monotonic_replacement_rejected = False
    current_support_set = {str(item) for item in current_support_ids if str(item)}
    chosen_support_set = {str(item) for item in chosen_support_ids if str(item)}
    replacing_existing_binding = bool(
        current_support_set
        and chosen_support_set
        and not out_of_pool_support_ids
        and not chosen_support_set.issuperset(current_support_set)
    )
    if replacing_existing_binding and not _definition_binding_replacement_is_strictly_better(
        current_analysis=current_best_analysis,
        proposed_analysis=selected_primary,
    ):
        chosen_support_ids = current_support_ids[: max(1, int(max_support_rows))]
        chosen_support_set = {str(item) for item in chosen_support_ids if str(item)}
        non_monotonic_replacement_rejected = True

    first_candidate = pool_by_id.get(chosen_support_ids[0])
    repaired_value = _candidate_value(
        text=definition_text,
        supporting_ids=chosen_support_ids,
        selection_reason=str(current_value.get("selection_reason") or "definition_full_candidate_llm_multispan_verified"),
        source_text_field=first_candidate.source_text_field if first_candidate is not None else str(current_value.get("source_text_field") or ""),
    )
    final_binding_mode = "multi_row" if len(chosen_support_ids) > 1 else "single_row"
    repair_applied = chosen_support_ids != current_support_ids
    if repair_applied:
        repair_state = "repair_attempted_and_applied"
        repair_reason = repair_attempt_reason or "updated_definition_binding"
    elif repair_attempted:
        repair_state = "repair_attempted_but_rejected"
        repair_reason = (
            "non_monotonic_single_row_replacement_rejected"
            if non_monotonic_replacement_rejected
            else "no_strictly_better_anchor_available"
        )
    else:
        repair_state = "no_repair_needed"
        repair_reason = "retained_existing_binding"
    return repaired_value, _definition_support_binding_diag(
        repair_state=repair_state,
        repair_applied=repair_applied,
        repair_reason=repair_reason,
        repair_attempt_reason=repair_attempt_reason,
        current_support_ids=current_support_ids,
        out_of_pool_support_ids=out_of_pool_support_ids,
        chosen_support_ids=chosen_support_ids,
        current_binding_mode=current_binding_mode,
        final_binding_mode=final_binding_mode,
        stronger_same_kc_candidate_existed=stronger_same_kc_candidate_existed,
        candidate_anchor_pool_considered=candidate_anchor_pool_considered,
        weaker_anchor_rejections=weaker_anchor_rejections,
    )


def _run_joint_drafting_phase(
    *,
    exemplar: Mapping[str, Any],
    definition_candidates: Sequence[FieldCandidate],
    scope_candidates: Sequence[FieldCandidate],
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
    policy: Step67DraftingPolicy,
    runtime: Step67ModelRuntime,
    counters: Counter[str],
    budget_state: Dict[str, Any],
) -> Dict[str, Any]:
    supporting_lookup = {
        item.overlay_candidate_id: item
        for item in [*definition_candidates, *scope_candidates]
    }
    available_overlay_ids = [str(item) for item in unique_preserve_order(list(supporting_lookup.keys())) if str(item)]

    draft_response: Dict[str, Any] = {
        "definition": {"status": "abstained", "text": "", "supporting_overlay_candidate_ids": [], "abstention_reason": "insufficient_evidence"},
        "scope": {"status": "abstained", "text": "", "supporting_overlay_candidate_ids": [], "abstention_reason": "insufficient_evidence"},
    }
    verify_response: Dict[str, Any] = dict(draft_response)
    draft_meta: Dict[str, Any] = {"source": "skipped"}
    verify_meta: Dict[str, Any] = {"source": "skipped"}
    draft_error = ""
    verify_error = ""

    if available_overlay_ids and definition_candidates:
        draft_request_payload, overlay_to_label = _request_payload(
            exemplar,
            definition_candidates,
            scope_candidates,
            target_descriptor=target_descriptor,
            sibling_descriptors=sibling_descriptors,
            max_chars=int(policy.evidence_text_max_chars),
        )
        label_to_overlay = {label: overlay_id for overlay_id, label in overlay_to_label.items()}
        allowed_ids = list(label_to_overlay.keys())
        draft_request_payload["label_to_overlay_candidate_id"] = label_to_overlay
        schema = _draft_schema(allowed_ids)
        draft_messages = _draft_messages(
            exemplar,
            definition_candidates,
            scope_candidates,
            target_descriptor=target_descriptor,
            sibling_descriptors=sibling_descriptors,
            max_chars=int(policy.evidence_text_max_chars),
        )
        try:
            raw_draft_payload, draft_meta = _call_phase(
                runtime=runtime,
                counters=counters,
                budget_state=budget_state,
                phase="draft",
                request_payload=draft_request_payload,
                schema=schema,
                messages=draft_messages,
            )
            if not _payload_has_expected_shape(raw_draft_payload):
                raise RuntimeError("draft_payload_shape_invalid")
            draft_response = _normalize_model_payload(
                raw_draft_payload,
                allowed_ids=allowed_ids,
                id_lookup=label_to_overlay,
            )
        except LLMCallBudgetExceededError as exc:
            draft_error = f"{type(exc).__name__}:{exc}"
        except Exception as exc:
            draft_error = f"{type(exc).__name__}:{exc}"
            counters["draft_runtime_failures"] += 1

        if not draft_error:
            evidence_lookup = {
                overlay_to_label[candidate.overlay_candidate_id]: {
                    "text": candidate.text,
                    "candidate_kind": candidate.candidate_kind,
                }
                for candidate in [*definition_candidates, *scope_candidates]
            }
            verify_request_payload = {
                "draft": raw_draft_payload,
                "evidence_lookup": evidence_lookup,
            }
            verify_messages = _verify_messages(
                exemplar,
                raw_draft_payload,
                evidence_lookup,
                sibling_descriptors=sibling_descriptors,
                max_chars=int(policy.evidence_text_max_chars),
            )
            try:
                raw_verify_payload, verify_meta = _call_phase(
                    runtime=runtime,
                    counters=counters,
                    budget_state=budget_state,
                    phase="verify",
                    request_payload=verify_request_payload,
                    schema=schema,
                    messages=verify_messages,
                )
                if not _payload_has_expected_shape(raw_verify_payload):
                    raise RuntimeError("verify_payload_shape_invalid")
                verify_response = _normalize_model_payload(
                    raw_verify_payload,
                    allowed_ids=allowed_ids,
                    id_lookup=label_to_overlay,
                )
            except LLMCallBudgetExceededError as exc:
                verify_error = f"{type(exc).__name__}:{exc}"
            except Exception as exc:
                verify_error = f"{type(exc).__name__}:{exc}"
                counters["verify_runtime_failures"] += 1
    else:
        draft_meta = {"source": "skipped", "reason": "no_definition_candidate_pool"}
        verify_meta = {"source": "skipped", "reason": "no_definition_candidate_pool"}

    definition_full_candidate = {}
    scope_candidate = {}
    if not draft_error and not verify_error:
        definition_full_candidate = _candidate_value_from_verified(
            field_name="definition_full_candidate",
            normalized_field=verify_response.get("definition") or {},
            supporting_lookup=supporting_lookup,
        )
        scope_candidate = _candidate_value_from_verified(
            field_name="scope_candidate",
            normalized_field=verify_response.get("scope") or {},
            supporting_lookup=supporting_lookup,
        )

    return {
        "definition_full_candidate": definition_full_candidate,
        "scope_candidate": scope_candidate,
        "draft_response": draft_response,
        "verify_response": verify_response,
        "draft_meta": draft_meta,
        "verify_meta": verify_meta,
        "draft_error": draft_error,
        "verify_error": verify_error,
        "supporting_lookup": supporting_lookup,
    }


def _run_definition_preservation_phase(
    *,
    exemplar: Mapping[str, Any],
    rows_by_id: Mapping[str, Mapping[str, Any]],
    assessments_by_id: Mapping[str, Mapping[str, Any]],
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
    scope_candidates: Sequence[FieldCandidate],
    policy: Step67DraftingPolicy,
    runtime: Step67ModelRuntime,
    counters: Counter[str],
    budget_state: Dict[str, Any],
) -> Dict[str, Any]:
    preservation_definition_candidates = _definition_candidates(
        rows_by_id,
        assessments_by_id,
        target_descriptor=target_descriptor,
        sibling_descriptors=sibling_descriptors,
        limit=int(policy.definition_candidate_limit),
        support_pack=[],
        build_support_pack=False,
    )
    phase_result = _run_joint_drafting_phase(
        exemplar=exemplar,
        definition_candidates=preservation_definition_candidates,
        scope_candidates=scope_candidates,
        target_descriptor=target_descriptor,
        sibling_descriptors=sibling_descriptors,
        policy=policy,
        runtime=runtime,
        counters=counters,
        budget_state=budget_state,
    )
    return {
        "definition_candidates": preservation_definition_candidates,
        "phase_result": phase_result,
        "preserved_definition_candidate": dict(phase_result.get("definition_full_candidate") or {}),
        "preserved_scope_candidate": dict(phase_result.get("scope_candidate") or {}),
    }


def _build_definition_support_pack_phase(
    *,
    rows_by_id: Mapping[str, Mapping[str, Any]],
    assessments_by_id: Mapping[str, Mapping[str, Any]],
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
    policy: Step67DraftingPolicy,
) -> Dict[str, Any]:
    support_pack = select_definition_support_pack(
        rows_by_id,
        assessments_by_id,
        target_kc_id=str(target_descriptor.get("kc_id") or ""),
        max_pack_size=min(3, max(1, int(policy.definition_candidate_limit))),
    )
    rescue_definition_candidates = _definition_candidates(
        rows_by_id,
        assessments_by_id,
        target_descriptor=target_descriptor,
        sibling_descriptors=sibling_descriptors,
        limit=int(policy.definition_candidate_limit),
        support_pack=support_pack,
        build_support_pack=False,
    )
    return {
        "support_pack": list(support_pack),
        "definition_candidates": rescue_definition_candidates,
    }


def _definition_candidate_pool_signature(
    definition_candidates: Sequence[FieldCandidate],
) -> List[Tuple[str, str]]:
    return [
        (str(candidate.overlay_candidate_id), _text_key(candidate.text))
        for candidate in definition_candidates
    ]


def _definition_candidate_quality_tier(
    candidate_value: Mapping[str, Any],
    *,
    rows_by_id: Mapping[str, Mapping[str, Any]],
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
) -> int:
    if str(candidate_value.get("status") or "") != "grounded":
        return 0
    text = _normalize_ws(candidate_value.get("text") or "")
    if not text:
        return 0
    if _looks_bibliography_entry(text) or _looks_metric_output_surface(text) or _looks_procedural_definition_header(text):
        return 0
    if _field_definition_sibling_risk(
        candidate_value,
        rows_by_id=rows_by_id,
        target_descriptor=target_descriptor,
        sibling_descriptors=sibling_descriptors,
    ):
        return 0
    lowered = f" {text.lower()} "
    relation_bearing = (
        any(cue in lowered for cue in DEFINITION_RELATION_CUES)
        or bool(re.search(r"\b(?:is|are|was|were|captures|represents|characterizes|measures|quantifies)\b", lowered))
        or "=" in text
        or " iff " in lowered
        or " if and only if " in lowered
    )
    fragmentary = _looks_definition_fragment_start(text) or _looks_definition_fragment_tail(text)
    if fragmentary:
        return 1
    if "=" in text and not relation_bearing:
        return 2
    selection_reason = str(candidate_value.get("selection_reason") or "")
    if selection_reason.startswith("definition_full_candidate_source_faithful_"):
        return 3
    if relation_bearing and text.endswith((".", "!", "?")):
        return 4
    if relation_bearing:
        return 3
    return 2


def _definition_candidate_is_strictly_better(
    candidate_value: Mapping[str, Any],
    *,
    reference_value: Mapping[str, Any],
    rows_by_id: Mapping[str, Mapping[str, Any]],
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
) -> bool:
    candidate_tier = _definition_candidate_quality_tier(
        candidate_value,
        rows_by_id=rows_by_id,
        target_descriptor=target_descriptor,
        sibling_descriptors=sibling_descriptors,
    )
    reference_tier = _definition_candidate_quality_tier(
        reference_value,
        rows_by_id=rows_by_id,
        target_descriptor=target_descriptor,
        sibling_descriptors=sibling_descriptors,
    )
    if candidate_tier <= 0:
        return False
    if reference_tier <= 0:
        return True
    if candidate_tier > reference_tier:
        return True
    if candidate_tier < reference_tier:
        return False

    candidate_reason = str(candidate_value.get("selection_reason") or "")
    reference_reason = str(reference_value.get("selection_reason") or "")
    candidate_normalized = candidate_reason.startswith("definition_full_candidate_source_faithful_")
    reference_normalized = reference_reason.startswith("definition_full_candidate_source_faithful_")
    candidate_text = _normalize_ws(candidate_value.get("text") or "")
    reference_text = _normalize_ws(reference_value.get("text") or "")
    reference_fragmentary = (
        _looks_definition_fragment_start(reference_text)
        or _looks_definition_fragment_tail(reference_text)
        or not reference_text.endswith((".", "!", "?"))
    )
    if reference_tier >= 3 and not reference_normalized and candidate_normalized:
        if not reference_fragmentary:
            return False
        if len(candidate_text) >= len(reference_text) + 12:
            return True
    if candidate_normalized != reference_normalized:
        return not candidate_normalized and reference_normalized

    if _text_key(candidate_text) == _text_key(reference_text):
        return False

    candidate_support_ids = [str(item) for item in candidate_value.get("supporting_overlay_candidate_ids") or [] if str(item)]
    reference_support_ids = [str(item) for item in reference_value.get("supporting_overlay_candidate_ids") or [] if str(item)]
    if len(candidate_support_ids) > len(reference_support_ids) and len(candidate_text) >= len(reference_text):
        return True
    return len(candidate_text) >= len(reference_text) + 12


def _definition_packet_role_items(packet: Mapping[str, Any], role: str) -> List[Dict[str, Any]]:
    roles = dict(packet.get("roles") or {})
    return [dict(item) for item in roles.get(role) or []]


def _definition_packet_first_anchor(
    packet: Mapping[str, Any],
    roles: Sequence[str],
) -> Dict[str, Any]:
    for role in roles:
        for item in _definition_packet_role_items(packet, role):
            if bool(item.get("anchor_eligible")):
                return item
    return {}


def _definition_packet_relation_bearing_opening(text: str) -> bool:
    first_sentence = re.split(r"(?<=[.!?])\s+", _normalize_ws(text), maxsplit=1)[0].strip()
    if not first_sentence:
        return False
    lowered = f" {first_sentence.lower()} "
    return bool(
        any(cue in lowered for cue in DEFINITION_RELATION_CUES)
        or re.search(
            r"\b(?:is|are|was|were|means|refers to|denotes|captures|represents|characterizes|measures|quantifies|uses)\b",
            lowered,
        )
        or "=" in first_sentence
        or " iff " in lowered
        or " if and only if " in lowered
    )


def _definition_packet_candidate_value(
    *,
    candidate_kind: str,
    text: str,
    support_items: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    support_ids = unique_preserve_order(
        str(item.get("overlay_candidate_id") or "")
        for item in support_items
        if str(item.get("overlay_candidate_id") or "")
    )
    first_item = dict(support_items[0] or {}) if support_items else {}
    return _candidate_value(
        text=_ensure_sentence(text),
        supporting_ids=support_ids,
        selection_reason=f"definition_full_candidate_packet_family_{candidate_kind}",
        source_text_field=str(first_item.get("source_text_field") or ""),
    )


def _definition_packet_candidate_family(
    packet: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []

    faithful_item = _definition_packet_first_anchor(
        packet,
        ("definition_gloss", "target_witness", "mechanism_or_scope", "formula_or_notation"),
    )
    if faithful_item:
        candidates.append(
            {
                "candidate_kind": "faithful_extractive",
                "candidate_value": _definition_packet_candidate_value(
                    candidate_kind="faithful_extractive",
                    text=str(faithful_item.get("candidate_text") or ""),
                    support_items=[faithful_item],
                ),
                "support_trace": {
                    "packet_roles": [str(faithful_item.get("role") or "")],
                    "anchor_roles": [str(faithful_item.get("role") or "")],
                },
            }
        )

    formula_item = _definition_packet_first_anchor(packet, ("formula_or_notation",))
    formula_items = _definition_packet_role_items(packet, "formula_or_notation")
    gloss_item = _definition_packet_first_anchor(packet, ("definition_gloss", "target_witness"))
    formula_source = formula_item or (formula_items[0] if formula_items else {})
    if formula_source and (formula_item or gloss_item):
        support_items = [item for item in (gloss_item, formula_source) if item]
        text = " ".join(
            _ensure_sentence(str(item.get("candidate_text") or ""))
            for item in support_items
            if str(item.get("candidate_text") or "")
        )
        if text:
            candidates.append(
                {
                    "candidate_kind": "formula_plus_gloss",
                    "candidate_value": _definition_packet_candidate_value(
                        candidate_kind="formula_plus_gloss",
                        text=text,
                        support_items=support_items,
                    ),
                    "support_trace": {
                        "packet_roles": [str(item.get("role") or "") for item in support_items],
                        "anchor_roles": [
                            str(item.get("role") or "")
                            for item in support_items
                            if bool(item.get("anchor_eligible"))
                        ],
                    },
                }
            )

    explanation_item = _definition_packet_first_anchor(packet, ("definition_gloss", "mechanism_or_scope"))
    mechanism_item = _definition_packet_first_anchor(packet, ("mechanism_or_scope",))
    if explanation_item:
        support_items = [explanation_item]
        if (
            mechanism_item
            and str(mechanism_item.get("overlay_candidate_id") or "")
            != str(explanation_item.get("overlay_candidate_id") or "")
        ):
            support_items.append(mechanism_item)
        text = " ".join(
            _ensure_sentence(str(item.get("candidate_text") or ""))
            for item in support_items
            if str(item.get("candidate_text") or "")
        )
        if text:
            candidates.append(
                {
                    "candidate_kind": "explanation_first",
                    "candidate_value": _definition_packet_candidate_value(
                        candidate_kind="explanation_first",
                        text=text,
                        support_items=support_items,
                    ),
                    "support_trace": {
                        "packet_roles": [str(item.get("role") or "") for item in support_items],
                        "anchor_roles": [
                            str(item.get("role") or "")
                            for item in support_items
                            if bool(item.get("anchor_eligible"))
                        ],
                    },
                }
            )

    unique_by_kind: Dict[str, Dict[str, Any]] = {}
    for candidate in candidates[:3]:
        kind = str(candidate.get("candidate_kind") or "")
        if kind and kind not in unique_by_kind:
            unique_by_kind[kind] = candidate
    return list(unique_by_kind.values())


def _definition_packet_candidate_rejection_reasons(
    candidate: Mapping[str, Any],
    *,
    packet: Mapping[str, Any],
    rows_by_id: Mapping[str, Mapping[str, Any]],
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
) -> List[str]:
    candidate_value = dict(candidate.get("candidate_value") or {})
    text = _normalize_ws(candidate_value.get("text") or "")
    support_ids = [str(item) for item in candidate_value.get("supporting_overlay_candidate_ids") or [] if str(item)]
    reasons: List[str] = []
    if not text:
        reasons.append("empty_candidate")
    if not support_ids:
        reasons.append("missing_support_trace")
    if any(candidate_id not in rows_by_id for candidate_id in support_ids):
        reasons.append("support_row_missing")
    trace = dict(candidate.get("support_trace") or {})
    anchor_roles = [str(item) for item in trace.get("anchor_roles") or [] if str(item)]
    packet_roles = [str(item) for item in trace.get("packet_roles") or [] if str(item)]
    if not anchor_roles:
        reasons.append("no_anchor_role")
    if anchor_roles == ["example_or_context"]:
        reasons.append("example_or_context_as_sole_anchor")
    if packet_roles == ["formula_or_notation"] and not bool(packet.get("formula_anchor_allowed")):
        reasons.append("formula_or_notation_as_sole_unjustified_anchor")
    if not _definition_packet_relation_bearing_opening(text):
        reasons.append("missing_relation_bearing_opening")
    if _definition_candidate_quality_tier(
        candidate_value,
        rows_by_id=rows_by_id,
        target_descriptor=target_descriptor,
        sibling_descriptors=sibling_descriptors,
    ) < 3:
        reasons.append("definition_quality_tier_insufficient")
    if _field_definition_sibling_risk(
        candidate_value,
        rows_by_id=rows_by_id,
        target_descriptor=target_descriptor,
        sibling_descriptors=sibling_descriptors,
    ):
        reasons.append("sibling_or_surface_risk")
    return unique_preserve_order(reasons)


def _build_definition_packet_candidate_family_phase(
    *,
    packet: Mapping[str, Any],
    rows_by_id: Mapping[str, Mapping[str, Any]],
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
    mode: str,
) -> Dict[str, Any]:
    candidates = _definition_packet_candidate_family(packet)
    diagnostics: List[Dict[str, Any]] = []
    accepted: List[Tuple[float, Dict[str, Any]]] = []
    for candidate in candidates:
        candidate_value = dict(candidate.get("candidate_value") or {})
        reject_reasons = _definition_packet_candidate_rejection_reasons(
            candidate,
            packet=packet,
            rows_by_id=rows_by_id,
            target_descriptor=target_descriptor,
            sibling_descriptors=sibling_descriptors,
        )
        quality_tier = _definition_candidate_quality_tier(
            candidate_value,
            rows_by_id=rows_by_id,
            target_descriptor=target_descriptor,
            sibling_descriptors=sibling_descriptors,
        )
        support_ids = [str(item) for item in candidate_value.get("supporting_overlay_candidate_ids") or [] if str(item)]
        kind = str(candidate.get("candidate_kind") or "")
        selector_score = float(quality_tier * 10 + len(support_ids))
        if kind == "faithful_extractive":
            selector_score += 2.0
        elif kind == "formula_plus_gloss":
            selector_score += 1.5 if len(support_ids) > 1 else 0.5
        elif kind == "explanation_first":
            selector_score += 1.0
        diagnostic = {
            "candidate_kind": kind,
            "candidate_value": candidate_value,
            "support_trace": dict(candidate.get("support_trace") or {}),
            "quality_tier": int(quality_tier),
            "selector_score": round(selector_score, 6),
            "rejected": bool(reject_reasons),
            "rejection_reasons": reject_reasons,
        }
        diagnostics.append(diagnostic)
        if not reject_reasons:
            accepted.append((selector_score, diagnostic))

    accepted.sort(
        key=lambda item: (
            -float(item[0]),
            str(item[1].get("candidate_kind") or ""),
        )
    )
    selected = dict((accepted[0][1] if accepted else {}).get("candidate_value") or {})
    selected_kind = str((accepted[0][1] if accepted else {}).get("candidate_kind") or "")
    return {
        "mode": str(mode),
        "candidate_count": len(diagnostics),
        "candidates": diagnostics,
        "selected_candidate": selected,
        "selected_candidate_kind": selected_kind,
        "used_for_selection": bool(selected),
    }


def _definition_only_phase_result(
    *,
    definition_full_candidate: Mapping[str, Any],
    draft_response: Mapping[str, Any],
    verify_response: Mapping[str, Any],
    draft_meta: Mapping[str, Any],
    verify_meta: Mapping[str, Any],
    draft_error: str,
    verify_error: str,
    supporting_lookup: Mapping[str, FieldCandidate],
) -> Dict[str, Any]:
    skipped_scope = {
        "status": "abstained",
        "text": "",
        "supporting_overlay_candidate_ids": [],
        "abstention_reason": "definition_only_phase",
    }
    normalized_draft = {
        "definition": dict(draft_response.get("definition") or skipped_scope),
        "scope": dict(draft_response.get("scope") or skipped_scope),
    }
    normalized_verify = {
        "definition": dict(verify_response.get("definition") or skipped_scope),
        "scope": dict(verify_response.get("scope") or skipped_scope),
    }
    return {
        "definition_candidates": [],
        "phase_result": {
            "definition_full_candidate": dict(definition_full_candidate or {}),
            "scope_candidate": {},
            "draft_response": normalized_draft,
            "verify_response": normalized_verify,
            "draft_meta": dict(draft_meta or {}),
            "verify_meta": dict(verify_meta or {}),
            "draft_error": str(draft_error or ""),
            "verify_error": str(verify_error or ""),
            "supporting_lookup": dict(supporting_lookup or {}),
        },
        "preserved_definition_candidate": dict(definition_full_candidate or {}),
        "preserved_scope_candidate": {},
        "preservation_mode": "definition_only",
    }


def _run_definition_support_pack_phase(
    *,
    exemplar: Mapping[str, Any],
    packet: Mapping[str, Any],
    rows_by_id: Mapping[str, Mapping[str, Any]],
    assessments_by_id: Mapping[str, Mapping[str, Any]],
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
    policy: Step67DraftingPolicy,
    runtime: Step67ModelRuntime,
    counters: Counter[str],
    budget_state: Dict[str, Any],
) -> Dict[str, Any]:
    skipped_definition = {
        "status": "abstained",
        "text": "",
        "supporting_overlay_candidate_ids": [],
        "abstention_reason": "insufficient_evidence",
    }
    if not bool(packet.get("definitional_anchor_present")):
        return _definition_only_phase_result(
            definition_full_candidate={},
            draft_response={"definition": dict(skipped_definition)},
            verify_response={
                "definition": {
                    **dict(skipped_definition),
                    "abstention_reason": "support_pack_missing_definitional_anchor",
                }
            },
            draft_meta={"source": "skipped", "reason": "support_pack_missing_definitional_anchor"},
            verify_meta={"source": "skipped", "reason": "support_pack_missing_definitional_anchor"},
            draft_error="",
            verify_error="",
            supporting_lookup={},
        )

    request_payload, overlay_to_label, supporting_lookup = _definition_support_pack_request_payload(
        exemplar,
        packet=packet,
        rows_by_id=rows_by_id,
        assessments_by_id=assessments_by_id,
        target_descriptor=target_descriptor,
        sibling_descriptors=sibling_descriptors,
        max_chars=int(policy.evidence_text_max_chars),
    )
    if not overlay_to_label:
        return _definition_only_phase_result(
            definition_full_candidate={},
            draft_response={"definition": dict(skipped_definition)},
            verify_response={
                "definition": {
                    **dict(skipped_definition),
                    "abstention_reason": "support_pack_missing_citable_support",
                }
            },
            draft_meta={"source": "skipped", "reason": "support_pack_missing_citable_support"},
            verify_meta={"source": "skipped", "reason": "support_pack_missing_citable_support"},
            draft_error="",
            verify_error="",
            supporting_lookup=supporting_lookup,
        )

    label_to_overlay = {
        label: overlay_id
        for overlay_id, label in overlay_to_label.items()
    }
    allowed_ids = list(label_to_overlay.keys())
    request_payload["label_to_overlay_candidate_id"] = label_to_overlay
    schema = _definition_only_schema(allowed_ids)
    draft_messages = _definition_support_pack_messages(
        exemplar,
        packet=packet,
        rows_by_id=rows_by_id,
        assessments_by_id=assessments_by_id,
        target_descriptor=target_descriptor,
        sibling_descriptors=sibling_descriptors,
        max_chars=int(policy.evidence_text_max_chars),
    )
    draft_response: Dict[str, Any] = {"definition": dict(skipped_definition)}
    verify_response: Dict[str, Any] = {"definition": dict(skipped_definition)}
    draft_meta: Dict[str, Any] = {"source": "skipped"}
    verify_meta: Dict[str, Any] = {"source": "skipped"}
    draft_error = ""
    verify_error = ""

    try:
        raw_draft_payload, draft_meta = _call_phase(
            runtime=runtime,
            counters=counters,
            budget_state=budget_state,
            phase="definition_support_pack_draft",
            request_payload=request_payload,
            schema=schema,
            messages=draft_messages,
        )
        if not _definition_payload_has_expected_shape(raw_draft_payload):
            raise RuntimeError("definition_support_pack_draft_payload_shape_invalid")
        draft_response = {
            "definition": _normalize_field_payload(
                dict(raw_draft_payload.get("definition") or {}),
                allowed_ids=allowed_ids,
                id_lookup=label_to_overlay,
            )
        }
    except LLMCallBudgetExceededError as exc:
        draft_error = f"{type(exc).__name__}:{exc}"
    except Exception as exc:
        draft_error = f"{type(exc).__name__}:{exc}"
        counters["definition_support_pack_draft_runtime_failures"] += 1

    if not draft_error:
        verify_request_payload = {
            "draft": raw_draft_payload,
            "support_pack": request_payload,
        }
        verify_messages = _definition_support_pack_audit_messages(
            exemplar,
            packet=packet,
            rows_by_id=rows_by_id,
            assessments_by_id=assessments_by_id,
            draft_payload=raw_draft_payload,
            target_descriptor=target_descriptor,
            sibling_descriptors=sibling_descriptors,
            max_chars=int(policy.evidence_text_max_chars),
        )
        try:
            raw_verify_payload, verify_meta = _call_phase(
                runtime=runtime,
                counters=counters,
                budget_state=budget_state,
                phase="definition_support_pack_audit",
                request_payload=verify_request_payload,
                schema=schema,
                messages=verify_messages,
            )
            if not _definition_payload_has_expected_shape(raw_verify_payload):
                raise RuntimeError("definition_support_pack_audit_payload_shape_invalid")
            verify_response = {
                "definition": _normalize_field_payload(
                    dict(raw_verify_payload.get("definition") or {}),
                    allowed_ids=allowed_ids,
                    id_lookup=label_to_overlay,
                )
            }
        except LLMCallBudgetExceededError as exc:
            verify_error = f"{type(exc).__name__}:{exc}"
        except Exception as exc:
            verify_error = f"{type(exc).__name__}:{exc}"
            counters["definition_support_pack_audit_runtime_failures"] += 1

    definition_full_candidate: Dict[str, Any] = {}
    if not draft_error and not verify_error:
        definition_full_candidate = _candidate_value_from_verified(
            field_name="definition_full_candidate",
            normalized_field=verify_response.get("definition") or {},
            supporting_lookup=supporting_lookup,
            selection_reason="definition_full_candidate_support_pack_audited",
        )

    return _definition_only_phase_result(
        definition_full_candidate=definition_full_candidate,
        draft_response=draft_response,
        verify_response=verify_response,
        draft_meta=draft_meta,
        verify_meta=verify_meta,
        draft_error=draft_error,
        verify_error=verify_error,
        supporting_lookup=supporting_lookup,
    )


def _skipped_joint_phase_for_packet_candidate(
    *,
    definition_candidate: Mapping[str, Any],
) -> Dict[str, Any]:
    skipped_definition = {
        "status": "abstained",
        "text": "",
        "supporting_overlay_candidate_ids": [],
        "abstention_reason": "packet_multicandidate_definition_selected",
    }
    return {
        "definition_candidates": [],
        "phase_result": {
            "definition_full_candidate": dict(definition_candidate),
            "scope_candidate": {},
            "draft_response": {"definition": skipped_definition, "scope": dict(skipped_definition)},
            "verify_response": {"definition": skipped_definition, "scope": dict(skipped_definition)},
            "draft_meta": {"source": "skipped", "reason": "packet_multicandidate_definition_selected"},
            "verify_meta": {"source": "skipped", "reason": "packet_multicandidate_definition_selected"},
            "draft_error": "",
            "verify_error": "",
            "supporting_lookup": {},
        },
        "preserved_definition_candidate": dict(definition_candidate),
        "preserved_scope_candidate": {},
    }


def _run_definition_rescue_phase(
    *,
    exemplar: Mapping[str, Any],
    preservation_phase: Mapping[str, Any],
    support_pack_phase: Mapping[str, Any],
    scope_candidates: Sequence[FieldCandidate],
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
    policy: Step67DraftingPolicy,
    runtime: Step67ModelRuntime,
    counters: Counter[str],
    budget_state: Dict[str, Any],
    rows_by_id: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    rescue_definition_candidates = list(support_pack_phase.get("definition_candidates") or [])
    preserved_definition_candidate = dict(preservation_phase.get("preserved_definition_candidate") or {})
    preservation_definition_candidates = list(preservation_phase.get("definition_candidates") or [])
    candidate_pool_changed = (
        _definition_candidate_pool_signature(rescue_definition_candidates)
        != _definition_candidate_pool_signature(preservation_definition_candidates)
    )
    preserved_tier = _definition_candidate_quality_tier(
        preserved_definition_candidate,
        rows_by_id=rows_by_id,
        target_descriptor=target_descriptor,
        sibling_descriptors=sibling_descriptors,
    )
    preserved_selection_reason = str(preserved_definition_candidate.get("selection_reason") or "")
    preservation_short_circuits = bool(preserved_definition_candidate) and (
        preserved_tier >= 4
        or preserved_selection_reason.startswith("definition_full_candidate_packet_family_")
        or preserved_selection_reason == "definition_full_candidate_support_pack_audited"
    )
    should_run = bool(rescue_definition_candidates) and not preservation_short_circuits and (
        not preserved_definition_candidate
        or candidate_pool_changed
        or preserved_tier < 4
    )
    if not should_run:
        skipped_reason = "preserved_strong_definition_candidate" if preservation_short_circuits else "rescue_candidate_pool_not_needed"
        return {
            "used": False,
            "definition_candidates": rescue_definition_candidates,
            "phase_result": {
                "definition_full_candidate": {},
                "scope_candidate": {},
                "draft_response": {
                    "definition": {
                        "status": "abstained",
                        "text": "",
                        "supporting_overlay_candidate_ids": [],
                        "abstention_reason": "preserved_definition_candidate",
                    },
                    "scope": {
                        "status": "abstained",
                        "text": "",
                        "supporting_overlay_candidate_ids": [],
                        "abstention_reason": "preserved_definition_candidate",
                    },
                },
                "verify_response": {
                    "definition": {
                        "status": "abstained",
                        "text": "",
                        "supporting_overlay_candidate_ids": [],
                        "abstention_reason": "preserved_definition_candidate",
                    },
                    "scope": {
                        "status": "abstained",
                        "text": "",
                        "supporting_overlay_candidate_ids": [],
                        "abstention_reason": "preserved_definition_candidate",
                    },
                },
                "draft_meta": {"source": "skipped", "reason": skipped_reason},
                "verify_meta": {"source": "skipped", "reason": skipped_reason},
                "draft_error": "",
                "verify_error": "",
                "supporting_lookup": {},
            },
            "candidate_pool_changed": candidate_pool_changed,
            "skipped_reason": skipped_reason,
            "preservation_short_circuited": preservation_short_circuits,
        }
    phase_result = _run_joint_drafting_phase(
        exemplar=exemplar,
        definition_candidates=rescue_definition_candidates,
        scope_candidates=scope_candidates,
        target_descriptor=target_descriptor,
        sibling_descriptors=sibling_descriptors,
        policy=policy,
        runtime=runtime,
        counters=counters,
        budget_state=budget_state,
    )
    return {
        "used": True,
        "definition_candidates": rescue_definition_candidates,
        "phase_result": phase_result,
        "candidate_pool_changed": candidate_pool_changed,
        "skipped_reason": "",
        "preservation_short_circuited": False,
    }


def _run_definition_verification_phase(
    *,
    preserved_definition_candidate: Mapping[str, Any],
    rescue_definition_candidate: Mapping[str, Any],
    preserved_scope_candidate: Mapping[str, Any],
    rescue_scope_candidate: Mapping[str, Any],
    rows_by_id: Mapping[str, Mapping[str, Any]],
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
    final_definition_candidate = dict(preserved_definition_candidate or {})
    final_scope_candidate = dict(preserved_scope_candidate or {})
    protection_action = ""

    if rescue_definition_candidate:
        if not final_definition_candidate:
            final_definition_candidate = dict(rescue_definition_candidate)
            protection_action = "accepted_definition_rescue_candidate"
        elif _definition_candidate_is_strictly_better(
            rescue_definition_candidate,
            reference_value=final_definition_candidate,
            rows_by_id=rows_by_id,
            target_descriptor=target_descriptor,
            sibling_descriptors=sibling_descriptors,
        ):
            final_definition_candidate = dict(rescue_definition_candidate)
            protection_action = "replaced_preserved_definition_with_strictly_better_rescue"
        else:
            protection_action = "preserved_definition_over_non_monotonic_rescue"

    if rescue_scope_candidate and not final_scope_candidate:
        final_scope_candidate = dict(rescue_scope_candidate)

    return final_definition_candidate, final_scope_candidate, protection_action


def _maybe_apply_reference_field_protection(
    *,
    field_name: str,
    current_value: Mapping[str, Any],
    reference_bundle: Mapping[str, Any] | None,
    rows_by_id: Mapping[str, Mapping[str, Any]],
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
) -> Tuple[Dict[str, Any], str]:
    reference_bundle = dict(reference_bundle or {})
    reference_value = dict(reference_bundle.get(field_name) or {})
    if not _grounded_candidate_available(reference_value, rows_by_id=rows_by_id):
        return dict(current_value or {}), ""

    current_grounded = str(current_value.get("status") or "") == "grounded"
    reference_candidate = _reference_candidate_value(
        reference_value,
        selection_reason=f"{field_name}_preserved_from_reference_bundle",
        rows_by_id=rows_by_id,
    )
    if not reference_candidate:
        return dict(current_value or {}), ""

    if field_name == "definition_full_candidate":
        reference_risky = _field_definition_sibling_risk(
            reference_value,
            rows_by_id=rows_by_id,
            target_descriptor=target_descriptor,
            sibling_descriptors=sibling_descriptors,
        )
        current_risky = _field_definition_sibling_risk(
            current_value,
            rows_by_id=rows_by_id,
            target_descriptor=target_descriptor,
            sibling_descriptors=sibling_descriptors,
        )
        if reference_risky:
            return dict(current_value or {}), ""
        if not current_grounded:
            return reference_candidate, "preserved_missing_definition_from_reference"
        if current_risky:
            return reference_candidate, "replaced_sibling_risky_definition_with_reference"
        return dict(current_value or {}), ""

    if field_name == "scope_candidate" and not current_grounded:
        return reference_candidate, "preserved_missing_scope_from_reference"

    return dict(current_value or {}), ""


def _definition_short_candidate(
    definition_full_candidate: Mapping[str, Any],
    *,
    max_chars: int,
    max_tokens: int,
) -> Dict[str, Any]:
    if str(definition_full_candidate.get("status") or "") != "grounded":
        return {}
    full_text = _normalize_ws(definition_full_candidate.get("text") or "")
    supporting_ids = [str(item) for item in definition_full_candidate.get("supporting_overlay_candidate_ids") or []]
    if not supporting_ids or not full_text:
        return {}
    first_sentence = re.split(r"(?<=[.!?])\s+", full_text, maxsplit=1)[0].strip()
    short_text = first_sentence or full_text
    if len(short_text) > max_chars or _candidate_tokens(short_text) > max_tokens:
        short_text = full_text if len(full_text) <= max_chars else short_text[: max(0, max_chars - 3)].rstrip() + "..."
    return _candidate_value(
        text=short_text,
        supporting_ids=supporting_ids,
        selection_reason="derived_from_verified_definition_full_candidate",
        source_text_field=str(definition_full_candidate.get("source_text_field") or ""),
    )


def _local_row_text(
    row: Mapping[str, Any],
    *,
    assessments_by_id: Mapping[str, Mapping[str, Any]],
) -> str:
    candidate_id = str(row.get("overlay_candidate_id") or "")
    assessment = dict(assessments_by_id.get(candidate_id) or {})
    return _normalize_ws(
        assessment.get("candidate_text")
        or row.get("source_block_text")
        or row.get("quote_surface")
        or ""
    )


def _ensure_sentence(text: str) -> str:
    cleaned = re.sub(r"^\d+[.)]\s*", "", _normalize_ws(text))
    if not cleaned:
        return ""
    if cleaned.endswith((".", "!", "?")):
        return cleaned
    return f"{cleaned}."


def _formula_clause_from_draft_text(draft_text: str) -> str:
    cleaned = re.sub(r"^\d+[.)]\s*", "", _normalize_ws(draft_text))
    if "=" not in cleaned:
        return ""
    lowered = cleaned.lower()
    for marker in (" states that ", " we have ", " is ", " are "):
        index = lowered.find(marker)
        if index >= 0:
            clause = cleaned[index + len(marker) :].strip()
            if "=" in clause:
                return clause.rstrip(".")
    return cleaned.rstrip(".")


def _contextual_formula_normalized_text(canonical_name: str, draft_text: str) -> str:
    cleaned = re.sub(r"^\d+[.)]\s*", "", _normalize_ws(draft_text))
    match = re.match(
        r"^(?:for|given)\s+(?P<context>[^,]{1,48}),\s+the\s+.+?\s+is\s+(?P<body>.+)$",
        cleaned,
        flags=re.IGNORECASE,
    )
    if not match:
        return ""
    body = match.group("body").strip().rstrip(".")
    if "=" not in body:
        return ""
    context = match.group("context").strip()
    return _ensure_sentence(f"The {canonical_name.lower()} for {context} is {body}")


def _title_led_formula_normalized_text(canonical_name: str, draft_text: str) -> str:
    clause = _formula_clause_from_draft_text(draft_text)
    if not clause or "=" not in clause:
        return ""
    return _ensure_sentence(f"{canonical_name} states that {clause}")


def _binary_split_normalized_text(canonical_name: str, draft_text: str, neighborhood_text: str) -> str:
    title_lower = canonical_name.lower()
    draft_lower = _normalize_ws(draft_text).lower()
    neighborhood_lower = _normalize_ws(neighborhood_text).lower()
    if "tree" not in title_lower:
        return ""
    if "binary split" not in neighborhood_lower and "binary splits" not in neighborhood_lower:
        return ""
    if not any(
        cue in draft_lower
        for cue in ("binary split", "binary splits", "two child", "two children", "internal node")
    ):
        return ""
    return _ensure_sentence(f"A {title_lower} uses only binary splits")


_LOCAL_ROW_DEFINITION_MARKERS: Tuple[str, ...] = (
    " is ",
    " are ",
    " was ",
    " were ",
    " refers to ",
    " denotes ",
    " means ",
    "=",
    ":",
)

_LOCAL_ROW_UNSAFE_CUES: Tuple[str, ...] = (
    " as described above",
    " according to ",
    " describes ",
    " discussed ",
    " shown ",
    " suppose ",
    " consider ",
    " let ",
)


_LOCAL_QUOTE_CONTEXTUAL_LEAD_INS: Tuple[str, ...] = (
    "although ",
    "although,",
    "for example",
    "for instance",
    "however",
    "hence",
    "in this case",
    "informally",
    "note that",
    "therefore",
    "thus",
)

_LOCAL_QUOTE_UNSAFE_CUES: Tuple[str, ...] = (
    " as described above",
    " history ",
    " named by ",
    " describes ",
    " discussed ",
    " shown ",
    " suppose ",
    " consider ",
    " let ",
)

_FALLBACK_DIRECT_DISCOURSE_PREFIXES: Tuple[str, ...] = (
    "as previously mentioned",
    "during training",
    "even though",
    "for the purpose of",
    "in the following",
    "on the other hand",
    "otherwise",
    "rejecting the null hypothesis",
    "the preceding example",
    "these techniques",
    "this can be represented",
    "this section",
    "to illustrate",
    "to realize",
    "using a sample",
)

_FALLBACK_DIRECT_IMPERATIVE_PREFIXES: Tuple[str, ...] = (
    "calculate",
    "comment",
    "compare",
    "compute",
    "consider",
    "describe",
    "derive",
    "discuss",
    "give",
    "let",
    "show",
    "suppose",
)

_FALLBACK_DIRECT_HEADING_PATTERN = re.compile(
    r"\b(?:example|examples|exercise|exercises)\b",
    flags=re.IGNORECASE,
)

_FALLBACK_DIRECT_PROVENANCE_CUES: Tuple[str, ...] = (
    " history ",
    " named by ",
    " studied by ",
    " proposed by ",
    " developed by ",
    " introduced by ",
    " discussed by ",
    " surveyed by ",
    " compared by ",
)


_LOCAL_SUPPORT_UNIT_VERBS: Tuple[str, ...] = (
    "is",
    "are",
    "use",
    "uses",
    "means",
    "refers to",
    "denotes",
    "captures",
    "represents",
    "characterizes",
    "measures",
    "quantifies",
)

_WEAK_TITLE_SUFFIX_TOKENS: Tuple[str, ...] = (
    "overview",
    "basics",
    "introduction",
    "intro",
    "fundamentals",
    "foundation",
    "foundations",
)


def _definition_name_variants(canonical_name: str, aliases: Sequence[str]) -> List[str]:
    variants: List[str] = []
    weak_suffix_pattern = "|".join(re.escape(token) for token in _WEAK_TITLE_SUFFIX_TOKENS)
    for raw_value in [canonical_name, *aliases]:
        cleaned = _normalize_ws(raw_value)
        if not cleaned:
            continue
        variants.append(cleaned.lower())
        stripped = _normalize_ws(re.sub(r"\s*\([^)]*\)", "", cleaned))
        if stripped:
            variants.append(stripped.lower())
        suffix_trimmed = _normalize_ws(
            re.sub(
                rf"(?:\s+(?:{weak_suffix_pattern}))+$",
                "",
                stripped or cleaned,
                flags=re.IGNORECASE,
            )
        )
        if suffix_trimmed and suffix_trimmed.lower() != (stripped or cleaned).lower():
            variants.append(suffix_trimmed.lower())
    return [str(item) for item in unique_preserve_order(variants) if str(item)]


def _first_quote_sentence(text: str) -> str:
    cleaned = re.sub(r"^\d+[.)]\s*", "", _normalize_ws(text))
    if not cleaned:
        return ""
    first_sentence = re.split(r"(?<=[.!?])\s+", cleaned, maxsplit=1)[0].strip()
    return _ensure_sentence(first_sentence or cleaned)


def _fallback_direct_surface_rejection_reasons(
    text: str,
    *,
    row: Mapping[str, Any],
    assessment: Mapping[str, Any],
    target_descriptor: Mapping[str, Any],
) -> List[str]:
    stripped = _normalize_ws(text)
    if not stripped:
        return ["empty_surface"]

    lowered = stripped.lower()
    patch_heading = _normalize_ws(row.get("patch_heading") or row.get("page_heading_norm") or "")
    question_like = bool(assessment.get("question_like")) or stripped.endswith("?")
    imperative_like = bool(
        re.match(
            rf"^(?:[a-z]\.\s*)?(?:{'|'.join(re.escape(item) for item in _FALLBACK_DIRECT_IMPERATIVE_PREFIXES)})\b",
            lowered,
        )
        or " comment on " in f" {lowered} "
    )
    discourse_led = any(lowered.startswith(prefix) for prefix in _FALLBACK_DIRECT_DISCOURSE_PREFIXES) or any(
        lowered.startswith(prefix) for prefix in _LOCAL_QUOTE_CONTEXTUAL_LEAD_INS
    )
    fragmentary = bool(
        _looks_definition_fragment_start(stripped)
        or _looks_definition_fragment_tail(stripped)
        or _looks_relation_tail_fragment(stripped)
        or (stripped[:1].islower() and "=" not in stripped and not re.match(r"^[a-z][A-Za-z0-9_]*\(", stripped))
    )

    name_variants = _definition_name_variants(
        str(target_descriptor.get("canonical_name") or ""),
        [str(item) for item in target_descriptor.get("aliases") or []],
    )
    relation_score = max(
        _quote_surface_relation_score(stripped, name_variants=name_variants),
        _support_unit_relation_score(stripped, name_variants=name_variants),
    )
    target_profile = _descriptor_alignment(stripped, target_descriptor)

    reasons: List[str] = []
    if _looks_bibliography_entry(stripped):
        reasons.append("bibliography_surface")
    if _looks_heading_like_definition(stripped):
        reasons.append("heading_like_surface")
    if _looks_metric_output_surface(stripped):
        reasons.append("formula_or_metric_surface")
    if _looks_procedural_definition_header(stripped):
        reasons.append("procedure_header_surface")
    if question_like:
        reasons.append("question_like_surface")
    if imperative_like:
        reasons.append("procedure_led_surface")
    if discourse_led:
        reasons.append("discourse_led_surface")
    if fragmentary:
        reasons.append("fragmentary_surface")
    if (
        patch_heading
        and _FALLBACK_DIRECT_HEADING_PATTERN.search(patch_heading)
        and (question_like or imperative_like or discourse_led)
    ):
        reasons.append("example_or_exercise_led_surface")
    if (
        _candidate_tokens(stripped) >= 28
        and relation_score <= 0.0
        and not bool(target_profile.get("exact_name_phrase"))
        and int(target_profile.get("name_overlap") or 0) < 2
    ):
        reasons.append("broad_expository_surface")
    return [str(item) for item in unique_preserve_order(reasons) if str(item)]


def _fallback_surface_safe_for_normalized(text: str, *, assessment: Mapping[str, Any]) -> bool:
    stripped = _normalize_ws(text)
    if not stripped:
        return False
    lowered = stripped.lower()
    if bool(assessment.get("question_like")) or stripped.endswith("?"):
        return False
    if (
        _looks_bibliography_entry(stripped)
        or _looks_heading_like_definition(stripped)
        or _looks_metric_output_surface(stripped)
        or _looks_procedural_definition_header(stripped)
        or _looks_definition_fragment_start(stripped)
        or _looks_definition_fragment_tail(stripped)
        or _looks_relation_tail_fragment(stripped)
    ):
        return False
    if stripped[:1].islower() and "=" not in stripped and not re.match(r"^[a-z][A-Za-z0-9_]*\(", stripped):
        return False
    if re.match(
        rf"^(?:[a-z]\.\s*)?(?:{'|'.join(re.escape(item) for item in _FALLBACK_DIRECT_IMPERATIVE_PREFIXES)})\b",
        lowered,
    ):
        return False
    if " comment on " in f" {lowered} ":
        return False
    return True


def _surface_starts_with_name_variant(text: str, *, name_variants: Sequence[str]) -> bool:
    stripped = re.sub(r"^\d+[.)]\s*", "", _normalize_ws(text))
    if not stripped:
        return False
    for variant in sorted(
        [str(item) for item in name_variants if str(item)],
        key=len,
        reverse=True,
    ):
        escaped = re.escape(variant)
        if re.search(
            rf"^(?:(?:the|a|an)\s+)?{escaped}\b",
            stripped,
            flags=re.IGNORECASE,
        ):
            return True
    return False


def _fallback_surface_history_or_provenance_like(text: str) -> bool:
    lowered = f" {_normalize_ws(text).lower()} "
    if any(cue in lowered for cue in _FALLBACK_DIRECT_PROVENANCE_CUES):
        return True
    return bool(
        re.search(
            r"\b(?:named|studied|proposed|developed|introduced|surveyed|compared|discussed|described)\b\s+by\b",
            lowered,
        )
    )


def _fallback_surface_name_led_direct_quality(
    text: str,
    *,
    name_variants: Sequence[str],
) -> bool:
    stripped = re.sub(r"^\d+[.)]\s*", "", _normalize_ws(text))
    if not stripped:
        return False
    direct_verbs = (
        "is",
        "are",
        "means",
        "refers to",
        "denotes",
        "captures",
        "represents",
        "characterizes",
        "measures",
        "quantifies",
        "operates",
    )
    verb_group = "|".join(re.escape(item) for item in direct_verbs)
    for variant in sorted((str(item) for item in name_variants if str(item)), key=len, reverse=True):
        escaped = re.escape(variant)
        if re.search(
            rf"^(?:(?:the|a|an)\s+)?{escaped}\b\s+(?:{verb_group})\b",
            stripped,
            flags=re.IGNORECASE,
        ):
            return True
    return False


def _fallback_surface_strong_enough_for_direct(
    text: str,
    *,
    source_text_field: str,
    candidate: FieldCandidate,
    row: Mapping[str, Any],
    assessment: Mapping[str, Any],
    target_descriptor: Mapping[str, Any],
) -> bool:
    stripped = _normalize_ws(text)
    if not stripped:
        return False
    if _fallback_direct_surface_rejection_reasons(
        stripped,
        row=row,
        assessment=assessment,
        target_descriptor=target_descriptor,
    ):
        return False

    alignment_signals = _salvage_surface_alignment_signals(
        stripped,
        candidate=candidate,
        target_descriptor=target_descriptor,
    )
    target_profile = dict(alignment_signals.get("target_profile") or {})
    if bool(alignment_signals.get("weak_alignment_issue")):
        return False
    if not bool(alignment_signals.get("strong_alignment")):
        return False
    if _fallback_surface_history_or_provenance_like(stripped):
        return False

    strong_named_alignment = bool(
        target_profile.get("exact_name_phrase")
        or candidate.has_name_anchor
        or int(candidate.title_overlap) >= 2
    )
    explicit_definition_relation = bool(alignment_signals.get("explicit_definition_relation"))
    name_variants = _definition_name_variants(
        str(target_descriptor.get("canonical_name") or ""),
        [str(item) for item in target_descriptor.get("aliases") or []],
    )
    name_led_surface = _surface_starts_with_name_variant(stripped, name_variants=name_variants)
    equation_identity = bool(
        (
            name_led_surface
            or bool(target_profile.get("exact_name_phrase"))
            or int(candidate.title_overlap) >= 2
        )
        and re.match(r"^(?:the\s+)?[A-Z][A-Za-z0-9_()[\]/ -]{0,80}\s*=", stripped)
        and "=" in stripped[: min(len(stripped), 120)]
        and not stripped.rstrip().endswith(":")
    )
    classification = str(assessment.get("classification") or "")
    positive_surface_type = str(assessment.get("positive_surface_type") or "")
    prose_definition_like = positive_surface_type in {
        "prose_definition",
        "anchored_descriptive_clause",
    }
    explicit_relation_direct = bool(
        explicit_definition_relation
        and strong_named_alignment
        and prose_definition_like
        and source_text_field == "quote_surface"
    )
    standalone_name_led_direct = bool(
        name_led_surface
        and _fallback_surface_name_led_direct_quality(
            stripped,
            name_variants=name_variants,
        )
        and strong_named_alignment
        and prose_definition_like
        and not bool(row.get("is_procedure_like"))
        and source_text_field == "quote_surface"
    )

    if classification in {"formula_only_support", "equation_support"}:
        return bool(
            equation_identity
            and strong_named_alignment
            and not bool(row.get("is_procedure_like"))
        )

    if source_text_field == "source_block_text" and bool(row.get("is_procedure_like")) and not equation_identity:
        return False

    relation_score = float(alignment_signals.get("relation_score") or 0.0)
    if (
        source_text_field == "quote_surface"
        and bool(row.get("is_procedure_like"))
        and relation_score <= 0.0
        and not equation_identity
        and not explicit_relation_direct
    ):
        return False

    if equation_identity:
        return bool(strong_named_alignment)

    if relation_score > 0.0 and strong_named_alignment:
        return True

    if explicit_relation_direct:
        return True

    if standalone_name_led_direct:
        return True

    return False


def _salvage_surface_alignment_signals(
    text: str,
    *,
    candidate: FieldCandidate,
    target_descriptor: Mapping[str, Any],
) -> Dict[str, Any]:
    normalized_text = _normalize_ws(text)
    target_profile = _descriptor_alignment(normalized_text, target_descriptor)
    name_variants = _definition_name_variants(
        str(target_descriptor.get("canonical_name") or ""),
        [str(item) for item in target_descriptor.get("aliases") or []],
    )
    relation_score = max(
        _quote_surface_relation_score(normalized_text, name_variants=name_variants),
        _support_unit_relation_score(normalized_text, name_variants=name_variants),
    )
    lowered = f" {normalized_text.lower()} "
    explicit_definition_relation = bool(
        relation_score > 0.0 or any(cue in lowered for cue in DEFINITION_RELATION_CUES)
    )
    named_alignment = bool(
        target_profile.get("exact_name_phrase")
        or candidate.has_name_anchor
        or int(target_profile.get("name_overlap") or 0) >= 1
        or int(candidate.title_overlap) >= 2
    )
    strong_alignment = bool(
        named_alignment
        or int(target_profile.get("context_overlap") or 0) >= 3
        or int(candidate.title_overlap) >= 2
        or int(candidate.context_overlap) >= 3
    )
    weak_alignment_issue = "weak_target_alignment" in {str(item) for item in candidate.issues}
    return {
        "target_profile": target_profile,
        "relation_score": float(relation_score),
        "explicit_definition_relation": explicit_definition_relation,
        "named_alignment": named_alignment,
        "strong_alignment": strong_alignment,
        "weak_alignment_issue": weak_alignment_issue,
    }


def _salvage_surface_strong_enough_for_direct(
    text: str,
    *,
    source_text_field: str,
    tail_trimmed: bool = False,
    candidate: FieldCandidate,
    row: Mapping[str, Any],
    assessment: Mapping[str, Any],
    target_descriptor: Mapping[str, Any],
) -> bool:
    rejection_reasons = _fallback_direct_surface_rejection_reasons(
        text,
        row=row,
        assessment=assessment,
        target_descriptor=target_descriptor,
    )
    alignment_signals = _salvage_surface_alignment_signals(
        text,
        candidate=candidate,
        target_descriptor=target_descriptor,
    )
    named_alignment = bool(alignment_signals.get("named_alignment"))
    if bool(alignment_signals.get("weak_alignment_issue")):
        return False
    if not bool(alignment_signals.get("explicit_definition_relation")):
        return False
    if not bool(alignment_signals.get("strong_alignment")):
        return False
    classification = str(assessment.get("classification") or "")
    if classification in {"formula_only_support", "equation_support"}:
        return False
    if classification == "weak_support":
        if not (bool(row.get("is_definition_like")) or bool(assessment.get("definition_signal"))):
            return False
        raw_surface_text = _normalize_ws(
            str(
                row.get("quote_surface")
                if source_text_field == "quote_surface"
                else row.get("source_block_text") or candidate.text or row.get("quote_surface") or ""
            )
        )
        raw_tail_fragment = bool(
            _looks_definition_fragment_tail(raw_surface_text)
            or _trim_salvage_surface_tail_fragment(raw_surface_text)
        )
        if not re.search(r"[.!?]$", raw_surface_text):
            if not (tail_trimmed and raw_tail_fragment):
                return False
        if tail_trimmed and not raw_tail_fragment:
            return False
        if (
            _looks_definition_fragment_start(text)
            or _looks_definition_fragment_tail(text)
            or _looks_relation_tail_fragment(text)
        ):
            return False
    if rejection_reasons:
        if set(rejection_reasons) != {"broad_expository_surface"}:
            return False
        if not named_alignment:
            return False
        if not (
            bool(assessment.get("definition_signal"))
            and str(assessment.get("positive_surface_type") or "") == "prose_definition"
        ):
            return False
    return True


def _trim_salvage_surface_tail_fragment(text: str) -> str:
    stripped = _normalize_ws(text)
    if not stripped:
        return ""
    trimmed = re.sub(r",?\s*i\.e\.,?[.!?]?\s*$", "", stripped, flags=re.IGNORECASE)
    trimmed = re.sub(r":\s*$", "", trimmed)
    trimmed = _normalize_ws(trimmed.rstrip(" ,;:"))
    if not trimmed or trimmed == stripped:
        return ""
    trimmed = _ensure_sentence(trimmed)
    if (
        not trimmed
        or _looks_definition_fragment_start(trimmed)
        or _looks_definition_fragment_tail(trimmed)
        or _looks_relation_tail_fragment(trimmed)
    ):
        return ""
    return trimmed


def _salvage_surface_safe_for_normalized(
    text: str,
    *,
    candidate: FieldCandidate,
    row: Mapping[str, Any],
    assessment: Mapping[str, Any],
    target_descriptor: Mapping[str, Any],
) -> bool:
    stripped = _normalize_ws(text)
    if not stripped:
        return False
    lowered = stripped.lower()
    if bool(assessment.get("question_like")) or stripped.endswith("?"):
        return False
    if (
        _looks_bibliography_entry(stripped)
        or _looks_heading_like_definition(stripped)
        or _looks_procedural_definition_header(stripped)
    ):
        return False
    if re.match(
        rf"^(?:[a-z]\.\s*)?(?:{'|'.join(re.escape(item) for item in _FALLBACK_DIRECT_IMPERATIVE_PREFIXES)})\b",
        lowered,
    ):
        return False
    if " comment on " in f" {lowered} ":
        return False

    alignment_signals = _salvage_surface_alignment_signals(
        stripped,
        candidate=candidate,
        target_descriptor=target_descriptor,
    )
    classification = str(assessment.get("classification") or "")
    explicit_definition_relation = bool(alignment_signals.get("explicit_definition_relation"))
    named_alignment = bool(alignment_signals.get("named_alignment"))
    strong_alignment = bool(alignment_signals.get("strong_alignment"))
    weak_alignment_issue = bool(alignment_signals.get("weak_alignment_issue"))

    if classification in {"formula_only_support", "equation_support"}:
        return bool(
            not weak_alignment_issue
            and named_alignment
            and strong_alignment
            and (bool(assessment.get("definition_signal")) or bool(row.get("is_definition_like")))
            and not _looks_definition_fragment_start(stripped)
            and not _looks_definition_fragment_tail(stripped)
            and not _looks_relation_tail_fragment(stripped)
        )

    if classification == "weak_support":
        return bool(
            explicit_definition_relation
            and named_alignment
            and strong_alignment
            and not _looks_definition_fragment_start(stripped)
            and not _looks_relation_tail_fragment(stripped)
        )

    if weak_alignment_issue:
        return False

    return bool(
        _fallback_surface_safe_for_normalized(stripped, assessment=assessment)
        and explicit_definition_relation
        and named_alignment
        and strong_alignment
    )


def _fallback_surface_safe_for_normalized_candidate(
    text: str,
    *,
    source_text_field: str,
    candidate: FieldCandidate,
    row: Mapping[str, Any],
    assessment: Mapping[str, Any],
    target_descriptor: Mapping[str, Any],
) -> bool:
    stripped = _normalize_ws(text)
    if not _fallback_surface_safe_for_normalized(stripped, assessment=assessment):
        return False

    alignment_signals = _salvage_surface_alignment_signals(
        stripped,
        candidate=candidate,
        target_descriptor=target_descriptor,
    )
    target_profile = dict(alignment_signals.get("target_profile") or {})
    if bool(alignment_signals.get("weak_alignment_issue")):
        return False
    if not bool(alignment_signals.get("strong_alignment")):
        return False

    strong_named_alignment = bool(
        target_profile.get("exact_name_phrase")
        or candidate.has_name_anchor
        or int(candidate.title_overlap) >= 2
    )
    name_variants = _definition_name_variants(
        str(target_descriptor.get("canonical_name") or ""),
        [str(item) for item in target_descriptor.get("aliases") or []],
    )
    name_led_surface = _surface_starts_with_name_variant(stripped, name_variants=name_variants)
    equation_identity = bool(
        (
            name_led_surface
            or bool(target_profile.get("exact_name_phrase"))
            or int(candidate.title_overlap) >= 2
        )
        and re.match(r"^(?:the\s+)?[A-Z][A-Za-z0-9_()[\]/ -]{0,80}\s*=", stripped)
        and "=" in stripped[: min(len(stripped), 120)]
        and not stripped.rstrip().endswith(":")
    )
    classification = str(assessment.get("classification") or "")

    if classification in {"formula_only_support", "equation_support"}:
        return bool(equation_identity and strong_named_alignment)

    if source_text_field == "source_block_text" and bool(row.get("is_procedure_like")) and not equation_identity:
        return False

    if source_text_field == "quote_surface":
        return bool(
            strong_named_alignment
            and (bool(assessment.get("definition_signal")) or bool(row.get("is_definition_like")))
        )

    relation_score = float(alignment_signals.get("relation_score") or 0.0)
    if relation_score > 0.0 and strong_named_alignment:
        return True

    return bool(
        name_led_surface
        and strong_named_alignment
        and bool(row.get("is_definition_like"))
        and not bool(row.get("is_procedure_like"))
    )


def _definition_draft_supported_single_span_fallback_value(
    *,
    field_name: str,
    candidate: FieldCandidate,
    target_descriptor: Mapping[str, Any],
) -> Tuple[Dict[str, Any], bool]:
    row = dict(candidate.row or {})
    assessment = dict(candidate.assessment or {})
    support_ids = [str(candidate.overlay_candidate_id)]
    surfaces: List[Tuple[str, str]] = []
    quote_text = _first_quote_sentence(str(row.get("quote_surface") or ""))
    block_text = _normalize_ws(
        candidate.text
        or row.get("source_block_text")
        or row.get("quote_surface")
        or ""
    )
    for source_text_field, surface_text in (
        ("quote_surface", quote_text),
        ("source_block_text", block_text),
    ):
        normalized_text = _normalize_ws(surface_text)
        if not normalized_text:
            continue
        surfaces.append((source_text_field, normalized_text))

    unique_surfaces: List[Tuple[str, str]] = []
    seen_surface_keys: set[str] = set()
    for source_text_field, surface_text in surfaces:
        surface_key = _text_key(surface_text)
        if surface_key in seen_surface_keys:
            continue
        seen_surface_keys.add(surface_key)
        unique_surfaces.append((source_text_field, surface_text))

    for source_text_field, surface_text in unique_surfaces:
        if not _fallback_surface_strong_enough_for_direct(
            surface_text,
            source_text_field=source_text_field,
            candidate=candidate,
            row=row,
            assessment=assessment,
            target_descriptor=target_descriptor,
        ):
            continue
        return (
            _candidate_value(
                text=surface_text,
                supporting_ids=support_ids,
                selection_reason="definition_full_candidate_draft_supported_single_span_fallback",
                source_text_field=source_text_field,
            ),
            False,
        )

    for source_text_field, surface_text in unique_surfaces:
        if not _fallback_surface_safe_for_normalized_candidate(
            surface_text,
            source_text_field=source_text_field,
            candidate=candidate,
            row=row,
            assessment=assessment,
            target_descriptor=target_descriptor,
        ):
            continue
        return (
            _candidate_value(
                text=surface_text,
                supporting_ids=support_ids,
                selection_reason="definition_full_candidate_source_faithful_fallback_surface_normalization",
                source_text_field=source_text_field,
            ),
            True,
        )

    return {}, False


def _definition_draft_supported_single_span_fallback_salvage_value(
    *,
    definition_candidates: Sequence[FieldCandidate],
    blocked_candidate: FieldCandidate,
    target_descriptor: Mapping[str, Any],
    local_rows: Sequence[Mapping[str, Any]] | None = None,
    assessments_by_id: Mapping[str, Mapping[str, Any]] | None = None,
) -> Tuple[Dict[str, Any], bool, Optional[FieldCandidate]]:
    target_kc_id = str(target_descriptor.get("kc_id") or "")
    blocked_candidate_id = str(blocked_candidate.overlay_candidate_id or "")
    ordered_candidates: List[FieldCandidate] = []
    seen_candidate_ids: set[str] = set()
    for candidate in definition_candidates:
        candidate_id = str(candidate.overlay_candidate_id or "")
        if not candidate_id or candidate_id in seen_candidate_ids or candidate_id == blocked_candidate_id:
            continue
        seen_candidate_ids.add(candidate_id)
        if _row_source_relation(candidate.row, target_kc_id=target_kc_id) != "local":
            continue
        if str(candidate.row.get("kc_id") or "") != target_kc_id:
            continue
        if not _normalize_ws(candidate.text):
            continue
        ordered_candidates.append(candidate)

    supplemental_assessments_by_id = dict(assessments_by_id or {})
    for row in local_rows or []:
        candidate_id = str(row.get("overlay_candidate_id") or "")
        if not candidate_id or candidate_id in seen_candidate_ids or candidate_id == blocked_candidate_id:
            continue
        if str(row.get("kc_id") or "") != target_kc_id:
            continue
        if _row_source_relation(row, target_kc_id=target_kc_id) != "local":
            continue
        candidate = _supporting_lookup_candidate_from_row(
            row,
            assessments_by_id=supplemental_assessments_by_id,
        )
        if candidate is None:
            continue
        if not (
            bool(candidate.assessment.get("definition_signal"))
            or bool(candidate.row.get("is_definition_like"))
        ):
            continue
        if not _normalize_ws(candidate.text):
            continue
        seen_candidate_ids.add(candidate_id)
        ordered_candidates.append(candidate)

    for allow_normalized in (False, True):
        for candidate in ordered_candidates:
            row = dict(candidate.row or {})
            assessment = dict(candidate.assessment or {})
            quote_text = _first_quote_sentence(str(row.get("quote_surface") or ""))
            block_text = _normalize_ws(
                candidate.text
                or row.get("source_block_text")
                or row.get("quote_surface")
                or ""
            )
            surfaces: List[Tuple[str, str, bool]] = []
            for source_text_field, surface_text in (
                ("quote_surface", quote_text),
                ("source_block_text", block_text),
            ):
                normalized_text = _normalize_ws(surface_text)
                if not normalized_text:
                    continue
                surfaces.append((source_text_field, normalized_text, False))
                trimmed_text = _trim_salvage_surface_tail_fragment(normalized_text)
                if trimmed_text:
                    surfaces.append((source_text_field, trimmed_text, True))

            unique_surfaces: List[Tuple[str, str, bool]] = []
            seen_surface_keys: set[str] = set()
            for source_text_field, surface_text, tail_trimmed in surfaces:
                surface_key = _text_key(surface_text)
                if surface_key in seen_surface_keys:
                    continue
                seen_surface_keys.add(surface_key)
                unique_surfaces.append((source_text_field, surface_text, tail_trimmed))

            if not allow_normalized:
                for source_text_field, surface_text, tail_trimmed in unique_surfaces:
                    if not _salvage_surface_strong_enough_for_direct(
                        surface_text,
                        source_text_field=source_text_field,
                        tail_trimmed=tail_trimmed,
                        candidate=candidate,
                        row=row,
                        assessment=assessment,
                        target_descriptor=target_descriptor,
                    ):
                        continue
                    return (
                        _candidate_value(
                            text=surface_text,
                            supporting_ids=[str(candidate.overlay_candidate_id)],
                            selection_reason="definition_full_candidate_draft_supported_single_span_fallback_same_kc_salvage",
                            source_text_field=source_text_field,
                        ),
                        False,
                        candidate,
                    )
                continue

            for source_text_field, surface_text, _ in unique_surfaces:
                if not _salvage_surface_safe_for_normalized(
                    surface_text,
                    candidate=candidate,
                    row=row,
                    assessment=assessment,
                    target_descriptor=target_descriptor,
                ):
                    continue
                return (
                    _candidate_value(
                        text=surface_text,
                        supporting_ids=[str(candidate.overlay_candidate_id)],
                        selection_reason="definition_full_candidate_source_faithful_fallback_surface_same_kc_salvage_normalization",
                        source_text_field=source_text_field,
                    ),
                    True,
                    candidate,
                )

    return {}, False, None


def _support_unit_sentences(text: str, *, limit: int = 3) -> List[str]:
    cleaned = re.sub(r"^\d+[.)]\s*", "", _normalize_ws(text))
    if not cleaned:
        return []
    parts = [_normalize_ws(part) for part in re.split(r"(?<=[.!?])\s+", cleaned) if _normalize_ws(part)]
    if not parts:
        parts = [cleaned]
    candidates = [_ensure_sentence(part.rstrip(".!?")) for part in parts[: max(1, int(limit))]]
    if ":" in cleaned:
        prefix, suffix = cleaned.split(":", 1)
        prefix = _normalize_ws(prefix)
        suffix = _normalize_ws(suffix)
        if prefix and suffix:
            candidates.append(_ensure_sentence(f"{prefix}: {suffix}"))
    return [str(item) for item in unique_preserve_order(candidates) if str(item)]


def _quote_surface_relation_score(sentence: str, *, name_variants: Sequence[str]) -> float:
    if not sentence:
        return 0.0
    prefix_stripped = re.sub(r"^(?:for|given)\b[^,.!?]{0,96},\s*", "", sentence, flags=re.IGNORECASE)
    for variant in name_variants:
        escaped = re.escape(str(variant))
        concept_led_patterns = (
            rf"^(?:the|a|an)\s+{escaped}\b\s*(?:=|\b(?:is|are|was|were|means|refers to|denotes)\b)",
            rf"^{escaped}\b\s*(?:=|\b(?:is|are|was|were|means|refers to|denotes)\b)",
        )
        for pattern in concept_led_patterns:
            if re.search(pattern, prefix_stripped, flags=re.IGNORECASE):
                return 3.0
        relation_led_patterns = (
            rf"^[A-Z][^.?!]{{0,140}}\b(?:is|are|was|were|means|refers to|denotes)\b\s+(?:the|a|an)\s+{escaped}\b",
            rf"^[A-Z][^.?!]{{0,140}}\b(?:is|are|was|were|means|refers to|denotes)\b\s+{escaped}\b",
            rf"^[A-Z][^.?!]{{0,140}}\b(?:is|are|was|were)\b\s+(?:often\s+|commonly\s+|sometimes\s+)?called\s+(?:the|a|an)\s+{escaped}\b",
            rf"^[A-Z][^.?!]{{0,140}}\b(?:is|are|was|were)\b\s+(?:often\s+|commonly\s+|sometimes\s+)?called\s+{escaped}\b",
            rf"^[A-Z][^.?!]{{0,140}}\b(?:called|known as)\s+(?:the|a|an)\s+{escaped}\b",
            rf"^[A-Z][^.?!]{{0,140}}\b(?:called|known as)\s+{escaped}\b",
        )
        for pattern in relation_led_patterns:
            if re.search(pattern, sentence, flags=re.IGNORECASE):
                return 2.0
    return 0.0


def _support_unit_relation_score(sentence: str, *, name_variants: Sequence[str]) -> float:
    relation_score = _quote_surface_relation_score(sentence, name_variants=name_variants)
    if relation_score > 0.0:
        return relation_score
    stripped = re.sub(r"^\d+[.)]\s*", "", _normalize_ws(sentence))
    if not stripped:
        return 0.0
    for variant in name_variants:
        escaped = re.escape(str(variant))
        verb_group = "|".join(re.escape(item) for item in _LOCAL_SUPPORT_UNIT_VERBS)
        if re.search(
            rf"^(?:the|a|an)\s+{escaped}\b\s*:\s+\S",
            stripped,
            flags=re.IGNORECASE,
        ) or re.search(
            rf"^{escaped}\b\s*:\s+\S",
            stripped,
            flags=re.IGNORECASE,
        ):
            return 2.25
        if re.search(
            rf"^(?:the|a|an)\s+{escaped}\b\s+(?:{verb_group})\b",
            stripped,
            flags=re.IGNORECASE,
        ) or re.search(
            rf"^{escaped}\b\s+(?:{verb_group})\b",
            stripped,
            flags=re.IGNORECASE,
        ):
            return 2.0
    return 0.0


def _name_variant_prefixed_sentence(text: str, *, name_variants: Sequence[str]) -> str:
    stripped = re.sub(r"^\d+[.)]\s*", "", _normalize_ws(text))
    if not stripped:
        return ""
    for variant in sorted(
        [str(item) for item in name_variants if str(item)],
        key=len,
        reverse=True,
    ):
        escaped = re.escape(variant)
        match = re.search(
            rf"^(?:(?:the|a|an)\s+)?(?P<title>{escaped})\s*:\s*(?P<body>.+)$",
            stripped,
            flags=re.IGNORECASE,
        )
        if not match:
            continue
        title = _normalize_ws(match.group("title") or "")
        body = _normalize_ws(match.group("body") or "")
        if (
            not title
            or not body
            or _looks_bibliography_entry(body)
            or _looks_heading_like_definition(body)
            or _looks_definition_fragment_start(body)
            or _looks_definition_fragment_tail(body)
        ):
            continue
        if re.match(r"^(?:The|A|An)\b", body):
            body = body[:1].lower() + body[1:]
        return _ensure_sentence(f"{title} is {body}")
    return ""


def _anchored_local_definition_sentence(canonical_name: str, row_text: str) -> str:
    cleaned = re.sub(r"^\d+[.)]\s*", "", _normalize_ws(row_text))
    if not cleaned or _looks_bibliography_entry(cleaned):
        return ""
    first_sentence = re.split(r"(?<=[.!?])\s+", cleaned, maxsplit=1)[0].strip()
    candidate = first_sentence or cleaned
    lowered = candidate.lower()
    title_lower = canonical_name.lower()
    if not lowered.startswith(title_lower):
        return ""
    if not any(marker in lowered for marker in _LOCAL_ROW_DEFINITION_MARKERS):
        return ""
    if any(cue in lowered for cue in _LOCAL_ROW_UNSAFE_CUES):
        return ""
    if "=" not in candidate and not re.search(r"[.!?]$", candidate):
        return ""
    if _looks_definition_fragment_tail(candidate) or _looks_definition_fragment_start(candidate):
        return ""
    return _ensure_sentence(candidate)


def _local_row_source_faithful_normalized_candidate(
    *,
    canonical_name: str,
    descriptor_context: str,
    draft_text: str,
    local_rows_by_id: Mapping[str, Mapping[str, Any]],
    local_texts: Mapping[str, str],
    assessments_by_id: Mapping[str, Mapping[str, Any]],
) -> Tuple[str, List[str]]:
    comparison_tokens = _content_token_set(draft_text) | _content_token_set(descriptor_context)
    ranked: List[Tuple[float, str, str]] = []
    for candidate_id, row in local_rows_by_id.items():
        assessment = dict(assessments_by_id.get(candidate_id) or {})
        if (
            bool(assessment.get("question_like"))
            or bool(assessment.get("bare_heading"))
            or bool(assessment.get("background_drift_block"))
            or bool(assessment.get("concept_mix_block"))
            or bool(assessment.get("contamination_block"))
        ):
            continue
        if not isinstance(row.get("page_index"), int) or int(row.get("page_index")) < 0:
            continue
        candidate_text = _anchored_local_definition_sentence(canonical_name, local_texts.get(candidate_id) or "")
        if not candidate_text:
            continue
        overlap = len(_content_token_set(candidate_text) & comparison_tokens)
        if overlap < 2 and "=" not in candidate_text:
            continue
        score = float(overlap) * 3.0
        if "=" in candidate_text:
            score += 3.0
        if bool(assessment.get("definition_candidate")):
            score += 1.0
        if "." in _normalize_ws(local_texts.get(candidate_id) or ""):
            score += 1.0
        score += min(float(len(candidate_text)) / 160.0, 1.0)
        ranked.append((score, candidate_id, candidate_text))
    if not ranked:
        return "", []
    ranked.sort(key=lambda item: (-item[0], -len(item[2]), item[1]))
    _, candidate_id, candidate_text = ranked[0]
    return candidate_text, [candidate_id]


def _local_quote_source_faithful_normalized_candidate(
    *,
    target_descriptor: Mapping[str, Any],
    descriptor_context: str,
    draft_text: str,
    local_rows_by_id: Mapping[str, Mapping[str, Any]],
    local_support_ids: Sequence[str],
    assessments_by_id: Mapping[str, Mapping[str, Any]],
) -> Tuple[str, List[str]]:
    name_variants = _definition_name_variants(
        str(target_descriptor.get("canonical_name") or ""),
        [str(item) for item in target_descriptor.get("aliases") or []],
    )
    if not name_variants:
        return "", []

    comparison_tokens = _content_token_set(draft_text) | _content_token_set(descriptor_context)
    ranked: List[Tuple[float, str, str]] = []
    for candidate_id in unique_preserve_order(str(item) for item in local_support_ids if str(item)):
        row = dict(local_rows_by_id.get(candidate_id) or {})
        if not row:
            continue
        assessment = dict(assessments_by_id.get(candidate_id) or {})
        if (
            bool(assessment.get("question_like"))
            or bool(assessment.get("bare_heading"))
            or bool(assessment.get("background_drift_block"))
            or bool(assessment.get("concept_mix_block"))
            or bool(assessment.get("contamination_block"))
        ):
            continue
        candidate_text = _first_quote_sentence(
            str(row.get("quote_surface") or assessment.get("candidate_text") or row.get("source_block_text") or "")
        )
        if not candidate_text:
            continue
        lowered = candidate_text.lower()
        if any(lowered.startswith(cue) for cue in _LOCAL_QUOTE_CONTEXTUAL_LEAD_INS):
            continue
        if any(cue in f" {lowered} " for cue in _LOCAL_QUOTE_UNSAFE_CUES):
            continue
        if not candidate_text[:1].isupper():
            continue
        if (
            _looks_bibliography_entry(candidate_text)
            or _looks_heading_like_definition(candidate_text)
            or _looks_definition_fragment_tail(candidate_text)
            or _looks_definition_fragment_start(candidate_text)
            or _looks_multi_proposition_surface(candidate_text)
        ):
            continue
        relation_score = _quote_surface_relation_score(candidate_text, name_variants=name_variants)
        if relation_score <= 0.0:
            continue
        target_profile = _descriptor_alignment(candidate_text, target_descriptor)
        if not (
            bool(target_profile.get("exact_name_phrase"))
            or int(target_profile.get("name_overlap") or 0) >= 2
        ):
            continue
        overlap = len(_content_token_set(candidate_text) & comparison_tokens)
        if overlap < 3 and "=" not in candidate_text:
            continue
        score = float(overlap) * 3.0 + relation_score
        if bool(target_profile.get("exact_name_phrase")):
            score += 1.5
        if bool(assessment.get("definition_candidate")):
            score += 1.0
        score += min(float(len(candidate_text)) / 160.0, 1.0)
        ranked.append((score, candidate_id, candidate_text))
    if not ranked:
        return "", []
    ranked.sort(key=lambda item: (-item[0], -len(item[2]), item[1]))
    _, candidate_id, candidate_text = ranked[0]
    return candidate_text, [candidate_id]


def _local_support_unit_quote_normalized_candidate(
    *,
    target_descriptor: Mapping[str, Any],
    descriptor_context: str,
    draft_text: str,
    local_rows_by_id: Mapping[str, Mapping[str, Any]],
    local_support_ids: Sequence[str],
    assessments_by_id: Mapping[str, Mapping[str, Any]],
) -> Tuple[str, List[str]]:
    name_variants = _definition_name_variants(
        str(target_descriptor.get("canonical_name") or ""),
        [str(item) for item in target_descriptor.get("aliases") or []],
    )
    if not name_variants:
        return "", []

    comparison_tokens = _content_token_set(draft_text) | _content_token_set(descriptor_context)
    ranked: List[Tuple[float, str, str]] = []
    candidate_ids = unique_preserve_order(
        [
            *[str(item) for item in local_support_ids if str(item)],
            *[str(item) for item in local_rows_by_id.keys() if str(item)],
        ]
    )
    for candidate_id in candidate_ids:
        row = dict(local_rows_by_id.get(candidate_id) or {})
        if not row:
            continue
        assessment = dict(assessments_by_id.get(candidate_id) or {})
        if (
            bool(assessment.get("question_like"))
            or bool(assessment.get("bare_heading"))
            or bool(assessment.get("background_drift_block"))
            or bool(assessment.get("concept_mix_block"))
            or bool(assessment.get("contamination_block"))
        ):
            continue
        raw_text = str(row.get("quote_surface") or assessment.get("candidate_text") or row.get("source_block_text") or "")
        for raw_sentence in _support_unit_sentences(raw_text):
            lowered = raw_sentence.lower()
            if any(lowered.startswith(cue) for cue in _LOCAL_QUOTE_CONTEXTUAL_LEAD_INS):
                continue
            if any(cue in f" {lowered} " for cue in _LOCAL_QUOTE_UNSAFE_CUES):
                continue
            candidate_text = _name_variant_prefixed_sentence(raw_sentence, name_variants=name_variants) or raw_sentence
            if (
                _looks_bibliography_entry(candidate_text)
                or _looks_heading_like_definition(candidate_text)
                or _looks_definition_fragment_tail(candidate_text)
                or _looks_definition_fragment_start(candidate_text)
                or _looks_relation_tail_fragment(candidate_text)
                or _looks_multi_proposition_surface(candidate_text)
            ):
                continue
            relation_score = _support_unit_relation_score(candidate_text, name_variants=name_variants)
            if relation_score <= 0.0:
                continue
            overlap = len(_content_token_set(candidate_text) & comparison_tokens)
            if overlap < 2 and "=" not in candidate_text:
                continue
            score = float(overlap) * 3.0 + relation_score
            if candidate_text != raw_sentence:
                score += 1.0
            if bool(assessment.get("definition_candidate")):
                score += 1.0
            score += min(float(len(candidate_text)) / 160.0, 1.0)
            ranked.append((score, candidate_id, candidate_text))
    if not ranked:
        return "", []
    ranked.sort(key=lambda item: (-item[0], -len(item[2]), item[1]))
    _, candidate_id, candidate_text = ranked[0]
    return candidate_text, [candidate_id]


def _row_pair_distance(left_row: Mapping[str, Any], right_row: Mapping[str, Any]) -> int | None:
    if str(left_row.get("doc_id") or "") != str(right_row.get("doc_id") or ""):
        return None
    left_page = left_row.get("page_index")
    right_page = right_row.get("page_index")
    if isinstance(left_page, int) and isinstance(right_page, int) and int(left_page) != int(right_page):
        return None
    left_block = _block_suffix_index(str(left_row.get("block_id") or ""))
    right_block = _block_suffix_index(str(right_row.get("block_id") or ""))
    if left_block is None or right_block is None:
        return None
    return abs(int(right_block) - int(left_block))


def _merge_local_support_unit_pair(
    first_text: str,
    second_text: str,
    *,
    name_variants: Sequence[str],
) -> str:
    first = _clean_completion_segment(first_text)
    second = _clean_completion_segment(second_text)
    if not first or not second or first.endswith("?") or second.endswith("?"):
        return ""
    if _looks_bibliography_entry(first) or _looks_bibliography_entry(second):
        return ""
    if _looks_heading_like_definition(first) or _looks_heading_like_definition(second):
        return ""
    if _looks_metric_output_surface(first) or _looks_metric_output_surface(second):
        return ""
    first_relation_tail = _looks_relation_tail_fragment(first.rstrip(".!?"))
    if _looks_definition_fragment_tail(first) or first_relation_tail or _looks_clause_continuation_fragment(second):
        second_clean = re.sub(r"^(?:and|or|then)\b\s*", "", second, flags=re.IGNORECASE)
        merged = _normalize_ws(f"{first.rstrip(' .,:;')} {second_clean}")
    elif _looks_clause_continuation_fragment(first) and _support_unit_relation_score(second, name_variants=name_variants) > 0.0:
        first_clean = re.sub(r"^(?:and|or|then)\b\s*", "", first, flags=re.IGNORECASE)
        merged = _normalize_ws(f"{second.rstrip(' .,:;')} {first_clean}")
    else:
        return ""
    merged = _ensure_sentence(merged)
    if (
        not merged
        or _looks_definition_fragment_start(merged)
        or _looks_definition_fragment_tail(merged)
        or _looks_multi_proposition_surface(merged)
    ):
        return ""
    return merged


def _local_two_span_source_faithful_normalized_candidate(
    *,
    target_descriptor: Mapping[str, Any],
    descriptor_context: str,
    draft_text: str,
    local_rows_by_id: Mapping[str, Mapping[str, Any]],
    local_support_ids: Sequence[str],
    assessments_by_id: Mapping[str, Mapping[str, Any]],
) -> Tuple[str, List[str]]:
    name_variants = _definition_name_variants(
        str(target_descriptor.get("canonical_name") or ""),
        [str(item) for item in target_descriptor.get("aliases") or []],
    )
    support_ids = [
        str(item)
        for item in unique_preserve_order(
            [
                *[str(item) for item in local_support_ids if str(item)],
                *[str(item) for item in local_rows_by_id.keys() if str(item)],
            ]
        )
        if str(item)
    ]
    if len(name_variants) <= 0 or len(support_ids) < 2:
        return "", []

    comparison_tokens = _content_token_set(draft_text) | _content_token_set(descriptor_context)
    prepared: List[Tuple[str, Mapping[str, Any], Mapping[str, Any], str]] = []
    for candidate_id in support_ids[:4]:
        row = dict(local_rows_by_id.get(candidate_id) or {})
        if not row:
            continue
        assessment = dict(assessments_by_id.get(candidate_id) or {})
        if (
            bool(assessment.get("question_like"))
            or bool(assessment.get("bare_heading"))
            or bool(assessment.get("background_drift_block"))
            or bool(assessment.get("concept_mix_block"))
            or bool(assessment.get("contamination_block"))
        ):
            continue
        candidate_text = _clean_completion_segment(
            str(assessment.get("candidate_text") or row.get("source_block_text") or row.get("quote_surface") or "")
        )
        if (
            not candidate_text
            or _looks_bibliography_entry(candidate_text)
            or _looks_heading_like_definition(candidate_text)
            or _looks_procedural_definition_header(candidate_text)
            or _looks_metric_output_surface(candidate_text)
        ):
            continue
        if _candidate_tokens(candidate_text) > 40 and not _looks_definition_fragment_tail(candidate_text):
            continue
        prepared.append((candidate_id, row, assessment, candidate_text))

    ranked: List[Tuple[float, List[str], str]] = []
    for index, left in enumerate(prepared):
        for right in prepared[index + 1 :]:
            distance = _row_pair_distance(left[1], right[1])
            if distance is None or distance <= 0 or distance > 3:
                continue
            for first, second in ((left, right), (right, left)):
                merged = _merge_local_support_unit_pair(
                    first[3],
                    second[3],
                    name_variants=name_variants,
                )
                if not merged:
                    continue
                relation_score = _support_unit_relation_score(merged, name_variants=name_variants)
                if relation_score <= 0.0 and "=" not in merged:
                    continue
                overlap = len(_content_token_set(merged) & comparison_tokens)
                if overlap < 2 and "=" not in merged:
                    continue
                score = float(overlap) * 3.0 + relation_score
                score += 4.0 if distance == 1 else (2.0 if distance == 2 else 1.0)
                if _looks_clause_continuation_fragment(second[3]):
                    score += 1.0
                ranked.append((score, [first[0], second[0]], merged))
    if not ranked:
        return "", []
    ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
    _, supporting_ids, normalized_text = ranked[0]
    return normalized_text, supporting_ids[:2]


def _grounded_definition_payload_candidates(
    *,
    current_value: Mapping[str, Any],
    draft_response: Mapping[str, Any],
    verify_response: Mapping[str, Any],
    definition_redraft_response: Mapping[str, Any],
    definition_redraft_verify_response: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for source_name, payload in (
        ("definition_full_candidate", current_value),
        ("definition_redraft_verify_response", dict(definition_redraft_verify_response.get("definition") or {})),
        ("definition_redraft_response", dict(definition_redraft_response.get("definition") or {})),
        ("verify_response", dict(verify_response.get("definition") or {})),
        ("draft_response", dict(draft_response.get("definition") or {})),
    ):
        if str(payload.get("status") or "") != "grounded":
            continue
        text = _normalize_ws(payload.get("text") or "")
        supporting_ids = [str(item) for item in payload.get("supporting_overlay_candidate_ids") or [] if str(item)]
        if not text or not supporting_ids:
            continue
        candidates.append(
            {
                "source_name": source_name,
                "text": text,
                "supporting_overlay_candidate_ids": supporting_ids,
            }
        )
    return candidates


def _source_faithful_normalized_definition_candidate(
    *,
    exemplar: Mapping[str, Any],
    current_value: Mapping[str, Any],
    draft_response: Mapping[str, Any],
    verify_response: Mapping[str, Any],
    definition_redraft_response: Mapping[str, Any],
    definition_redraft_verify_response: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    rows_by_id: Mapping[str, Mapping[str, Any]],
    assessments_by_id: Mapping[str, Mapping[str, Any]],
    target_descriptor: Mapping[str, Any],
    sibling_descriptors: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    canonical_name = _normalize_ws(exemplar.get("canonical_name") or "")
    target_kc_id = str(exemplar.get("kc_id") or "")
    descriptor_context = _descriptor_context_text(exemplar)
    if not canonical_name or not target_kc_id:
        return {}

    local_rows = [dict(row) for row in rows if str(row.get("kc_id") or "") == target_kc_id]
    local_rows_by_id = {str(row.get("overlay_candidate_id") or ""): row for row in local_rows}
    if not local_rows_by_id:
        return {}
    local_texts = {
        candidate_id: _local_row_text(row, assessments_by_id=assessments_by_id)
        for candidate_id, row in local_rows_by_id.items()
    }
    neighborhood_text = " ".join(text for text in local_texts.values() if text)

    for payload in _grounded_definition_payload_candidates(
        current_value=current_value,
        draft_response=draft_response,
        verify_response=verify_response,
        definition_redraft_response=definition_redraft_response,
        definition_redraft_verify_response=definition_redraft_verify_response,
    ):
        draft_text = str(payload.get("text") or "")
        local_support_ids = [
            candidate_id
            for candidate_id in payload.get("supporting_overlay_candidate_ids") or []
            if candidate_id in local_rows_by_id
        ]
        if not local_support_ids:
            continue

        formula_support_ids = [
            candidate_id
            for candidate_id, text in local_texts.items()
            if "=" in text and local_rows_by_id[candidate_id].get("kc_id") == target_kc_id
        ]
        title_support_ids = [
            candidate_id
            for candidate_id, text in local_texts.items()
            if canonical_name.lower() in text.lower()
        ]
        binary_split_support_ids = [
            candidate_id
            for candidate_id, text in local_texts.items()
            if "binary split" in text.lower() or "binary splits" in text.lower()
        ]

        candidate_specs: List[Tuple[str, List[str], str]] = []
        contextual_text = _contextual_formula_normalized_text(canonical_name, draft_text)
        if contextual_text:
            candidate_specs.append(
                (
                    contextual_text,
                    unique_preserve_order([*local_support_ids, *formula_support_ids, *title_support_ids]),
                    "definition_full_candidate_source_faithful_context_normalization",
                )
            )
        if formula_support_ids and title_support_ids:
            title_led_text = _title_led_formula_normalized_text(canonical_name, draft_text)
            if title_led_text:
                candidate_specs.append(
                    (
                        title_led_text,
                        unique_preserve_order([*local_support_ids, *title_support_ids, *formula_support_ids]),
                        "definition_full_candidate_source_faithful_formula_normalization",
                    )
                )
        binary_split_text = _binary_split_normalized_text(canonical_name, draft_text, neighborhood_text)
        if binary_split_text and binary_split_support_ids:
            candidate_specs.append(
                (
                    binary_split_text,
                    unique_preserve_order([*local_support_ids, *title_support_ids, *binary_split_support_ids]),
                    "definition_full_candidate_source_faithful_trimmed_normalization",
                )
            )
        local_row_text, local_row_support_ids = _local_row_source_faithful_normalized_candidate(
            canonical_name=canonical_name,
            descriptor_context=descriptor_context,
            draft_text=draft_text,
            local_rows_by_id=local_rows_by_id,
            local_texts=local_texts,
            assessments_by_id=assessments_by_id,
        )
        if local_row_text and local_row_support_ids:
            candidate_specs.append(
                (
                    local_row_text,
                    local_row_support_ids,
                    "definition_full_candidate_source_faithful_local_row_normalization",
                )
            )
        local_quote_text, local_quote_support_ids = _local_quote_source_faithful_normalized_candidate(
            target_descriptor=target_descriptor,
            descriptor_context=descriptor_context,
            draft_text=draft_text,
            local_rows_by_id=local_rows_by_id,
            local_support_ids=local_support_ids,
            assessments_by_id=assessments_by_id,
        )
        if local_quote_text and local_quote_support_ids:
            candidate_specs.append(
                (
                    local_quote_text,
                    local_quote_support_ids,
                    "definition_full_candidate_source_faithful_local_quote_normalization",
                )
            )
        support_unit_quote_text, support_unit_quote_support_ids = _local_support_unit_quote_normalized_candidate(
            target_descriptor=target_descriptor,
            descriptor_context=descriptor_context,
            draft_text=draft_text,
            local_rows_by_id=local_rows_by_id,
            local_support_ids=local_support_ids,
            assessments_by_id=assessments_by_id,
        )
        if support_unit_quote_text and support_unit_quote_support_ids:
            candidate_specs.append(
                (
                    support_unit_quote_text,
                    support_unit_quote_support_ids,
                    "definition_full_candidate_source_faithful_local_support_unit_normalization",
                )
            )
        local_two_span_text, local_two_span_support_ids = _local_two_span_source_faithful_normalized_candidate(
            target_descriptor=target_descriptor,
            descriptor_context=descriptor_context,
            draft_text=draft_text,
            local_rows_by_id=local_rows_by_id,
            local_support_ids=local_support_ids,
            assessments_by_id=assessments_by_id,
        )
        if local_two_span_text and local_two_span_support_ids:
            candidate_specs.append(
                (
                    local_two_span_text,
                    local_two_span_support_ids,
                    "definition_full_candidate_source_faithful_two_span_local_normalization",
                )
            )

        for normalized_text, supporting_ids, selection_reason in candidate_specs:
            normalized_text = _normalize_ws(normalized_text)
            if not normalized_text or normalized_text == _normalize_ws(draft_text):
                continue
            if not supporting_ids:
                continue
            candidate = _candidate_value(
                text=normalized_text,
                supporting_ids=supporting_ids,
                selection_reason=selection_reason,
                source_text_field="source_faithful_normalization",
            )
            if not _field_definition_sibling_risk(
                candidate,
                rows_by_id=rows_by_id,
                target_descriptor=target_descriptor,
                sibling_descriptors=sibling_descriptors,
            ):
                return candidate
    return {}


def _blocked_bundle_candidate_ids(
    rows_by_id: Mapping[str, Mapping[str, Any]],
    assessments_by_id: Mapping[str, Mapping[str, Any]],
    definition_rejected_candidates: Sequence[Mapping[str, Any]],
) -> List[str]:
    blocked = [
        str(item.get("overlay_candidate_id") or "")
        for item in definition_rejected_candidates
        if any(str(reason) in REVIEWER_BUNDLE_BLOCK_REASONS for reason in item.get("reasons") or [])
    ]
    for candidate_id, row in rows_by_id.items():
        assessment = dict(assessments_by_id.get(candidate_id) or {})
        if bool(assessment.get("contamination_block")) or bool(assessment.get("question_like")):
            blocked.append(candidate_id)
            continue
        issues = _definition_extended_issue_codes(row, assessment, str(assessment.get("candidate_text") or ""))
        if any(issue in {"citation_or_slide_context", "ocr_noise", "traceback_noise"} for issue in issues):
            blocked.append(candidate_id)
    return [str(item) for item in unique_preserve_order(blocked) if str(item)]


def _bundle_item_from_row(
    row: Mapping[str, Any],
    assessment: Mapping[str, Any],
    *,
    bundle_role: str,
) -> Dict[str, Any]:
    return {
        "bundle_role": bundle_role,
        "overlay_candidate_id": str(row.get("overlay_candidate_id") or ""),
        "selection_score": float(assessment.get("selection_score") or 0.0),
        "candidate_text": str(assessment.get("candidate_text") or ""),
        "quote_surface": _normalize_ws(row.get("quote_surface") or ""),
        "source_block_text": _normalize_ws(row.get("source_block_text") or ""),
        "doc_id": str(row.get("doc_id") or ""),
        "block_id": str(row.get("block_id") or ""),
        "page_index": row.get("page_index"),
        "sentence_id": str(row.get("sentence_id") or ""),
        "layer": str(row.get("layer") or ""),
        "alignment_score": float(row.get("alignment_score") or 0.0),
        "contamination_risk": str(row.get("contamination_risk") or ""),
        "provenance_normalization_status": str(row.get("provenance_normalization_status") or ""),
        "quote_verification_status": str(row.get("quote_verification_status") or ""),
        "assessment": {
            "classification": str(assessment.get("classification") or ""),
            "definition_signal": bool(assessment.get("definition_signal")),
            "scope_signal": bool(assessment.get("scope_signal")),
            "bare_heading": bool(assessment.get("bare_heading")),
            "formula_lead_in": bool(assessment.get("formula_lead_in")),
            "question_like": bool(assessment.get("question_like")),
        },
    }


def _coverage_state(exemplar: Mapping[str, Any]) -> Dict[str, Any]:
    canonical_name = _normalize_ws(exemplar.get("canonical_name") or "")
    return {
        "status": COVERAGE_STATE_STATUS_REPRESENTED,
        "canonical_name": canonical_name,
        "representation_basis": "hierarchy_identity",
        "source_field": "hierarchy.canonical_name",
        "review_lane_survival": True,
        "evidence_support_required": True,
    }


def _definition_enrichment_layer(
    definition_full_candidate: Mapping[str, Any],
    definition_short_candidate: Mapping[str, Any],
) -> Dict[str, Any]:
    grounded = str(definition_full_candidate.get("status") or "") == ENRICHMENT_LAYER_STATUS_GROUNDED
    if not grounded:
        return {
            "status": ENRICHMENT_LAYER_STATUS_MISSING,
            "text": "",
            "short_text": "",
            "supporting_overlay_candidate_ids": [],
            "source_field": "",
        }
    return {
        "status": ENRICHMENT_LAYER_STATUS_GROUNDED,
        "text": _normalize_ws(definition_full_candidate.get("text") or ""),
        "short_text": _normalize_ws(definition_short_candidate.get("text") or ""),
        "supporting_overlay_candidate_ids": [
            str(item)
            for item in definition_full_candidate.get("supporting_overlay_candidate_ids") or []
            if str(item)
        ],
        "source_field": "definition_full_candidate",
    }


def _authoritative_definition_status(
    *,
    definition_grounded: bool,
    normalized_grounded: bool,
) -> str:
    if definition_grounded:
        if normalized_grounded:
            return AUTHORITATIVE_DEFINITION_STATUS_NORMALIZED_GROUNDED
        return AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED
    return AUTHORITATIVE_DEFINITION_STATUS_INSUFFICIENT_SUPPORT


def _fallback_context_bundle(
    *,
    rows: Sequence[Mapping[str, Any]],
    assessments_by_id: Mapping[str, Mapping[str, Any]],
    selection: Mapping[str, Any],
    max_bundle_size: int,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    excluded_by_id: Dict[str, List[str]] = {
        str(item.get("overlay_candidate_id") or ""): [str(reason) for reason in item.get("exclusion_reasons") or []]
        for item in selection.get("excluded") or []
        if str(item.get("overlay_candidate_id") or "")
    }
    ranked_rows: List[Tuple[float, str, Mapping[str, Any], Mapping[str, Any], List[str]]] = []
    for row in rows:
        overlay_candidate_id = str(row.get("overlay_candidate_id") or "")
        if not overlay_candidate_id:
            continue
        quote_surface = _normalize_ws(row.get("quote_surface") or row.get("source_block_text") or row.get("candidate_text") or "")
        if not quote_surface:
            continue
        assessment = dict(assessments_by_id.get(overlay_candidate_id) or assess_overlay_candidate(row))
        exclusion_reasons = excluded_by_id.get(overlay_candidate_id, [])
        penalty = 0.0
        if bool(assessment.get("question_like")):
            penalty += 100.0
        if bool(assessment.get("contamination_block")):
            penalty += 40.0
        if "citation_or_slide_context" in exclusion_reasons or "ocr_noise" in exclusion_reasons or "traceback_noise" in exclusion_reasons:
            penalty += 80.0
        if "definition_verifier_bundle_block" in exclusion_reasons:
            penalty += 25.0
        if "high_contamination" in exclusion_reasons:
            penalty += 20.0
        if "formula_lead_in" in exclusion_reasons:
            penalty += 12.0
        ranked_rows.append(
            (
                float(assessment.get("selection_score") or 0.0) - penalty,
                overlay_candidate_id,
                row,
                assessment,
                exclusion_reasons,
            )
        )

    ranked_rows.sort(key=lambda item: (item[0], item[1]), reverse=True)
    fallback_bundle: List[Dict[str, Any]] = []
    fallback_reasons: List[str] = []
    for _, overlay_candidate_id, row, assessment, exclusion_reasons in ranked_rows:
        if any(item.get("overlay_candidate_id") == overlay_candidate_id for item in fallback_bundle):
            continue
        bundle_item = _bundle_item_from_row(row, assessment, bundle_role="context_support")
        if exclusion_reasons:
            bundle_item["fallback_exclusion_reasons"] = list(exclusion_reasons)
            fallback_reasons.extend(exclusion_reasons)
        bundle_item["fallback_context_floor"] = True
        fallback_bundle.append(bundle_item)
        if len(fallback_bundle) >= max(1, min(int(max_bundle_size), 3)):
            break
    return fallback_bundle, unique_preserve_order(fallback_reasons)


def _context_layer(
    *,
    context_bundle: Sequence[Mapping[str, Any]],
    context_status: str,
    family_context_rows: Sequence[Mapping[str, Any]],
    completion_context_rows: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    snippet_surfaces: List[str] = []
    doc_ids: List[str] = []
    overlay_ids: List[str] = []
    for item in context_bundle[:3]:
        snippet = _normalize_ws(item.get("quote_surface") or item.get("source_block_text") or item.get("candidate_text") or "")
        if snippet:
            snippet_surfaces.append(_clip_text(snippet, 220))
        overlay_candidate_id = str(item.get("overlay_candidate_id") or "")
        if overlay_candidate_id:
            overlay_ids.append(overlay_candidate_id)
        doc_id = str(item.get("doc_id") or "")
        if doc_id:
            doc_ids.append(doc_id)
    return {
        "status": context_status,
        "snippet_surfaces": unique_preserve_order(snippet_surfaces),
        "supporting_overlay_candidate_ids": unique_preserve_order(overlay_ids),
        "source_document_ids": unique_preserve_order(doc_ids),
        "family_context_candidate_ids": [
            str(item.get("overlay_candidate_id") or "")
            for item in family_context_rows
            if str(item.get("overlay_candidate_id") or "")
        ],
        "completion_context_candidate_ids": [
            str(item.get("overlay_candidate_id") or "")
            for item in completion_context_rows
            if str(item.get("overlay_candidate_id") or "")
        ],
        "selected_bundle_size": len(context_bundle),
    }


def _scope_layer(scope_candidate: Mapping[str, Any]) -> Dict[str, Any]:
    grounded = str(scope_candidate.get("status") or "") == SCOPE_LAYER_STATUS_GROUNDED
    return {
        "status": SCOPE_LAYER_STATUS_GROUNDED if grounded else SCOPE_LAYER_STATUS_ABSTAINED,
        "text": _normalize_ws(scope_candidate.get("text") or "") if grounded else "",
        "supporting_overlay_candidate_ids": [
            str(item)
            for item in scope_candidate.get("supporting_overlay_candidate_ids") or []
            if str(item)
        ]
        if grounded
        else [],
        "source_field": "scope_candidate" if grounded else "",
    }


def _semantic_risk_flags(
    *,
    contamination_flags: Sequence[str],
    hold_reasons: Sequence[str],
    definition_grounded: bool,
    scope_grounded: bool,
    context_status: str,
) -> List[str]:
    flags = unique_preserve_order([str(item) for item in [*contamination_flags, *hold_reasons] if str(item)])
    if not definition_grounded:
        flags = unique_preserve_order([*flags, COVERAGE_ONLY_ACTIVE_FLAG, DEFINITION_ENRICHMENT_MISSING_FLAG, LOW_TRUST_SURVIVOR_FLAG])
    if context_status == CONTEXT_LAYER_STATUS_FALLBACK:
        flags = unique_preserve_order([*flags, CONTEXT_FALLBACK_ACTIVE_FLAG, LOW_TRUST_SURVIVOR_FLAG])
    elif context_status == CONTEXT_LAYER_STATUS_MISSING:
        flags = unique_preserve_order([*flags, CONTEXT_BUNDLE_MISSING_FLAG, LOW_TRUST_SURVIVOR_FLAG])
    if not scope_grounded:
        flags = unique_preserve_order([*flags, "scope_gap_reviewer_editable"])
    if hold_reasons:
        flags = unique_preserve_order([*flags, REVIEW_NEEDS_ATTENTION_FLAG])
    return [str(item) for item in flags if str(item)]


def _trust_state(
    *,
    definition_grounded: bool,
    scope_grounded: bool,
    context_status: str,
    risk_flags: Sequence[str],
) -> Dict[str, Any]:
    if definition_grounded and scope_grounded and context_status == CONTEXT_LAYER_STATUS_GROUNDED and not any(
        flag in {REVIEW_NEEDS_ATTENTION_FLAG, LOW_TRUST_SURVIVOR_FLAG}
        for flag in risk_flags
    ):
        label = TRUST_STATE_GROUNDED
    elif definition_grounded:
        label = TRUST_STATE_GROUNDED_WITH_GAPS
    elif any(
        flag in {CONTEXT_FALLBACK_ACTIVE_FLAG, CONTEXT_BUNDLE_MISSING_FLAG, "sibling_boundary_mismatch"}
        for flag in risk_flags
    ):
        label = TRUST_STATE_COVERAGE_ONLY_WITH_RISKS
    else:
        label = TRUST_STATE_COVERAGE_ONLY
    return {
        "label": label,
        "definition_grounded": definition_grounded,
        "scope_grounded": scope_grounded,
        "context_status": context_status,
        "low_trust": label in {TRUST_STATE_COVERAGE_ONLY, TRUST_STATE_COVERAGE_ONLY_WITH_RISKS},
    }


def _review_readiness(
    *,
    trust_state: Mapping[str, Any],
    hold_reasons: Sequence[str],
    risk_flags: Sequence[str],
) -> Dict[str, Any]:
    trust_label = str(trust_state.get("label") or "")
    if trust_label == TRUST_STATE_GROUNDED and REVIEW_NEEDS_ATTENTION_FLAG not in risk_flags:
        label = REVIEW_READINESS_READY
    elif trust_label in {TRUST_STATE_COVERAGE_ONLY, TRUST_STATE_COVERAGE_ONLY_WITH_RISKS}:
        label = REVIEW_READINESS_COVERAGE_ONLY
    else:
        label = REVIEW_READINESS_NEEDS_ATTENTION
    readiness_reasons = unique_preserve_order(
        [
            *[str(item) for item in hold_reasons if str(item)],
            *[
                str(item)
                for item in risk_flags
                if str(item) in {
                    COVERAGE_ONLY_ACTIVE_FLAG,
                    CONTEXT_FALLBACK_ACTIVE_FLAG,
                    CONTEXT_BUNDLE_MISSING_FLAG,
                    REVIEW_NEEDS_ATTENTION_FLAG,
                    SELECTED_DEFINITION_SURFACE_REVIEW_SUPPRESSED_FLAG,
                    "sibling_boundary_mismatch",
                    "scope_gap_reviewer_editable",
                    "selected_definition_formula_only_anchor",
                    "selected_definition_broken_fragment",
                    "selected_definition_procedure_instruction_surface",
                    "selected_definition_example_update_surface",
                    "selected_definition_context_only_label_surface",
                    "selected_definition_severe_ocr_or_broken_math_surface",
                }
            ],
        ]
    )
    return {
        "label": label,
        "survives_review_lane": True,
        "needs_attention": label != REVIEW_READINESS_READY,
        "draft_status_compatibility": compatibility_draft_status(label),
        "reasons": readiness_reasons,
    }



def _step67_route_policy_text(value):
    return str(value or "").strip()


def _step67_route_policy_norm(value):
    return " ".join(_step67_route_policy_text(value).lower().split())


def _step67_route_policy_tokens(value):
    import re as _step67_re

    stop = {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
        "in", "into", "is", "it", "its", "of", "on", "or", "the", "to",
        "with", "without", "that", "this", "these", "those",
    }
    return {
        token
        for token in _step67_re.findall(r"[a-z0-9]+", _step67_route_policy_text(value).lower())
        if len(token) >= 2 and token not in stop
    }


def _step67_route_policy_token_jaccard(left, right):
    left_tokens = _step67_route_policy_tokens(left)
    right_tokens = _step67_route_policy_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _step67_route_policy_text_match(left, right, *, threshold=0.55):
    left_norm = _step67_route_policy_norm(left)
    right_norm = _step67_route_policy_norm(right)
    if not left_norm or not right_norm:
        return False
    if left_norm in right_norm or right_norm in left_norm:
        return True
    return _step67_route_policy_token_jaccard(left_norm, right_norm) >= threshold


def _step67_pack_has_drafting_core(exemplar):
    return bool(has_automatic_drafting_support(exemplar))


def _step67_ordered_pack_items(exemplar):
    if bool(exemplar.get("evidence_pack_available")) and not _step67_pack_has_drafting_core(exemplar):
        return []
    items = exemplar.get("ordered_pack_for_drafting") or []
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _step67_ordered_item_role(item):
    if not isinstance(item, dict):
        return ""
    return _step67_route_policy_text(item.get("role") or item.get("slot_role"))


def _step67_ordered_item_text(item):
    if not isinstance(item, dict):
        return ""
    for key in ("text", "candidate_text", "quote_surface", "source_block_text"):
        value = _step67_route_policy_text(item.get(key))
        if value:
            return value
    return ""


def _step67_overlay_row_texts(row):
    if not isinstance(row, dict):
        return []
    values = []
    for key in (
        "text",
        "candidate_text",
        "quote_surface",
        "source_block_text",
        "original_quote_surface",
        "original_source_block_text",
        "source_block_text_raw",
    ):
        value = _step67_route_policy_text(row.get(key))
        if value:
            values.append(value)
    return values


def _step67_bundle_item_texts(item):
    if not isinstance(item, dict):
        return []
    values = []
    for key in (
        "candidate_text",
        "quote_surface",
        "source_block_text",
        "text",
        "original_quote_surface",
        "original_source_block_text",
    ):
        value = _step67_route_policy_text(item.get(key))
        if value:
            values.append(value)
    return values


def _step67_find_overlay_id_for_text(text_value, rows):
    best_overlay_id = ""
    best_score = 0.0

    for row in rows or []:
        if not isinstance(row, dict):
            continue

        overlay_id = _step67_route_policy_text(row.get("overlay_candidate_id"))
        if not overlay_id:
            continue

        for candidate_text in _step67_overlay_row_texts(row):
            if _step67_route_policy_text_match(text_value, candidate_text):
                return overlay_id

            score = _step67_route_policy_token_jaccard(text_value, candidate_text)
            if score > best_score:
                best_score = score
                best_overlay_id = overlay_id

    if best_score >= 0.45:
        return best_overlay_id

    return ""


def _step67_ordered_definition_score(item, canonical_name):
    text_value = _step67_ordered_item_text(item)
    text_norm = _step67_route_policy_norm(text_value)
    canonical_tokens = _step67_route_policy_tokens(canonical_name)

    score = 0.0
    score += 10.0 if _step67_ordered_item_role(item) == "definition_kernel" else 0.0
    score += min(len(_step67_route_policy_tokens(text_value)), 28) / 10.0

    if canonical_tokens and canonical_tokens & _step67_route_policy_tokens(text_value):
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


def _step67_candidate_matches_ordered_role(candidate, exemplar, role):
    if not isinstance(candidate, dict):
        return False

    text_value = _step67_route_policy_text(candidate.get("text"))
    if not text_value:
        return False

    for item in _step67_ordered_pack_items(exemplar):
        if _step67_ordered_item_role(item) != role:
            continue
        if _step67_route_policy_text_match(text_value, _step67_ordered_item_text(item)):
            return True

    return False


def _step67_preferred_definition_kernel_candidate(exemplar, rows):
    items = [
        item
        for item in _step67_ordered_pack_items(exemplar)
        if _step67_ordered_item_role(item) == "definition_kernel"
        and _step67_ordered_item_text(item)
    ]

    if not items:
        return {}

    canonical_name = _step67_route_policy_text(exemplar.get("canonical_name"))
    ranked = sorted(
        items,
        key=lambda item: _step67_ordered_definition_score(item, canonical_name),
        reverse=True,
    )

    for item in ranked:
        text_value = _step67_ordered_item_text(item)
        overlay_id = _step67_find_overlay_id_for_text(text_value, rows)
        if not overlay_id:
            continue

        return {
            "status": ENRICHMENT_LAYER_STATUS_GROUNDED,
            "text": text_value,
            "supporting_overlay_candidate_ids": [overlay_id],
            "supporting_ordered_pack_candidate_ids": [
                _step67_route_policy_text(item.get("candidate_id"))
            ],
            "selection_reason": "definition_full_candidate_ordered_pack_definition_kernel_policy",
            "source_text_field": "ordered_pack_for_drafting.text",
            "stage3_v3_role_policy": {
                "applied": True,
                "policy": "prefer_definition_kernel_over_explanatory_gloss",
                "selected_role": _step67_ordered_item_role(item),
                "selected_ordered_pack_candidate_id": _step67_route_policy_text(item.get("candidate_id")),
            },
        }

    return {}


def _step67_evidence_pack_trace(exemplar):
    evidence_pack_quality = dict(exemplar.get("evidence_pack_quality") or {})
    ordered_items = _step67_ordered_pack_items(exemplar)

    role_counts = {}
    for item in ordered_items:
        role = _step67_ordered_item_role(item)
        if role:
            role_counts[role] = role_counts.get(role, 0) + 1

    insufficient_reasons = evidence_pack_quality.get("insufficient_reasons") or []
    if not isinstance(insufficient_reasons, list):
        insufficient_reasons = [str(insufficient_reasons)]

    route = _step67_route_policy_text(evidence_pack_quality.get("route"))
    if bool(exemplar.get("evidence_pack_available")) and not _step67_pack_has_drafting_core(exemplar):
        route = "insufficient_support_packet"

    return {
        "available": bool(exemplar.get("evidence_pack_available")),
        "version": _step67_route_policy_text(exemplar.get("evidence_pack_version")),
        "route": route,
        "ordered_pack_count": len(ordered_items),
        "ordered_pack_roles": role_counts,
        "evidence_lane_semantics": dict(exemplar.get("evidence_lane_semantics") or {}),
        "automatic_drafting_supported": bool((exemplar.get("evidence_lane_semantics") or {}).get("automatic_drafting_supported", _step67_pack_has_drafting_core(exemplar))),
        "definition_anchor_present": bool(evidence_pack_quality.get("definition_anchor_present", False)),
        "definition_anchor_natural_language": bool(
            evidence_pack_quality.get("definition_anchor_natural_language", False)
        ),
        "positive_support_count": int(evidence_pack_quality.get("positive_support_count") or 0),
        "auxiliary_support_count": int(evidence_pack_quality.get("auxiliary_support_count") or 0),
        "guardrail_support_count": int(evidence_pack_quality.get("guardrail_support_count") or 0),
        "context_completion_used": bool(evidence_pack_quality.get("context_completion_used", False)),
        "formula_dominance_risk": _step67_route_policy_text(evidence_pack_quality.get("formula_dominance_risk")),
        "sibling_contamination_risk": _step67_route_policy_text(evidence_pack_quality.get("sibling_contamination_risk")),
        "insufficient_reasons": [str(item) for item in insufficient_reasons],
    }


def _step67_item_matches_any_ordered_pack_text(item, ordered_items):
    item_texts = _step67_bundle_item_texts(item)
    if not item_texts:
        return False

    for item_text in item_texts:
        for ordered in ordered_items:
            if _step67_route_policy_text_match(item_text, _step67_ordered_item_text(ordered)):
                return True

    return False


def _step67_filter_context_bundle_by_evidence_pack_policy(
    context_bundle,
    exemplar,
    rows,
    definition_full_candidate,
    scope_candidate,
):
    route = _step67_route_policy_text(
        (exemplar.get("evidence_pack_quality") or {}).get("route")
    )
    if bool(exemplar.get("evidence_pack_available")) and not _step67_pack_has_drafting_core(exemplar):
        route = "insufficient_support_packet"
    ordered_items = _step67_ordered_pack_items(exemplar)

    selected_support_ids = set()
    if isinstance(definition_full_candidate, dict):
        for item in definition_full_candidate.get("supporting_overlay_candidate_ids") or []:
            item_text = _step67_route_policy_text(item)
            if item_text:
                selected_support_ids.add(item_text)
    if isinstance(scope_candidate, dict):
        for item in scope_candidate.get("supporting_overlay_candidate_ids") or []:
            item_text = _step67_route_policy_text(item)
            if item_text:
                selected_support_ids.add(item_text)

    grounding_roles = {
        "definition_support",
        "context_support",
        "scope_support",
    }

    filtered = []
    flags = []

    for item in context_bundle or []:
        if not isinstance(item, dict):
            continue

        role = _step67_route_policy_text(item.get("bundle_role"))
        overlay_id = _step67_route_policy_text(item.get("overlay_candidate_id"))

        if route == "insufficient_support_packet":
            flags.append("evidence_pack_policy_removed_grounding_bundle_for_insufficient_support")
            continue

        if route in {"partial_grounded_packet", "standard_drafting"}:
            if overlay_id in selected_support_ids:
                filtered.append(item)
                continue

            if ordered_items and _step67_item_matches_any_ordered_pack_text(item, ordered_items):
                filtered.append(item)
                continue

            if role in grounding_roles or role == "equation_support":
                flags.append("evidence_pack_policy_removed_unmatched_bundle_item")
                continue

        filtered.append(item)

    return filtered, unique_preserve_order(flags)


def build_kc_draft_bundles_llm(
    overlay_rows: Sequence[Mapping[str, Any]],
    *,
    runtime: Step67ModelRuntime,
    policy: Step67DraftingPolicy,
    reference_bundles: Mapping[str, Mapping[str, Any]] | None = None,
    reference_scope_bundles: Mapping[str, Mapping[str, Any]] | None = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    rows_by_kc: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    rows_by_page: Dict[Tuple[str, int], List[Mapping[str, Any]]] = defaultdict(list)
    for row in overlay_rows:
        kc_id = str(row.get("kc_id") or "")
        if kc_id:
            rows_by_kc[kc_id].append(row)
        page_key = _page_key(row)
        if page_key is not None:
            rows_by_page[page_key].append(row)

    exemplar_by_kc: Dict[str, Dict[str, Any]] = {
        kc_id: dict(sorted(rows, key=lambda row: str(row.get("overlay_candidate_id") or ""))[0])
        for kc_id, rows in rows_by_kc.items()
        if rows
    }
    descriptor_by_kc: Dict[str, Dict[str, Any]] = {
        kc_id: _kc_descriptor(exemplar)
        for kc_id, exemplar in exemplar_by_kc.items()
    }
    family_member_ids_by_key: Dict[str, List[str]] = defaultdict(list)
    for family_kc_id, descriptor in descriptor_by_kc.items():
        family_key = str(descriptor.get("family_group_key") or "")
        if family_key:
            family_member_ids_by_key[family_key].append(family_kc_id)

    bundles: List[Dict[str, Any]] = []
    draft_status_counter: Counter[str] = Counter()
    support_state_counter: Counter[str] = Counter()
    contamination_flag_counter: Counter[str] = Counter()
    evidence_bundle_size_distribution: Counter[str] = Counter()
    definition_rejection_counter: Counter[str] = Counter()
    runtime_counters: Counter[str] = Counter()
    kcs_with_definition_candidates = 0
    kcs_with_grounded_scopes = 0
    kcs_with_abstained_definitions = 0
    kcs_held_for_insufficient_support = 0
    kcs_with_contamination_flags = 0
    verifier_abstained_definition_kcs = 0
    verifier_abstained_scope_kcs = 0
    definition_redraft_recoveries = 0
    definition_source_faithful_normalization_recoveries = 0
    definition_context_completion_recoveries = 0
    definition_single_span_fallback_recoveries = 0
    definition_draft_supported_single_span_fallback_recoveries = 0
    scope_redraft_recoveries = 0
    reference_definition_preservations = 0
    reference_scope_preservations = 0
    sibling_definition_rejections = 0
    kcs_with_family_context_candidates = 0
    kcs_with_completion_context_candidates = 0
    trust_state_counter: Counter[str] = Counter()
    review_readiness_counter: Counter[str] = Counter()
    context_layer_status_counter: Counter[str] = Counter()
    authoritative_definition_status_counter: Counter[str] = Counter()
    coverage_only_count = 0
    context_fallback_count = 0
    kcs_with_llm_budget_exhaustion = 0
    definition_packet_family_recoveries = 0
    definition_support_pack_auditor_recoveries = 0
    definition_generation_mode = str(policy.definition_generation_mode or DEFINITION_GENERATION_MODE_LEGACY)
    selected_definition_review_suppressed_count = 0
    selected_definition_surface_risk_counter: Counter[str] = Counter()

    for kc_id in sorted(rows_by_kc.keys()):
        rows = sorted(rows_by_kc[kc_id], key=lambda row: str(row.get("overlay_candidate_id") or ""))
        exemplar = dict(rows[0])
        target_descriptor = descriptor_by_kc.get(kc_id) or _kc_descriptor(exemplar)
        sibling_descriptors = [
            descriptor_by_kc.get(sibling_kc_id) or _kc_descriptor(exemplar_by_kc[sibling_kc_id])
            for sibling_kc_id in family_member_ids_by_key.get(str(target_descriptor.get("family_group_key") or ""), [])
            if sibling_kc_id != kc_id and sibling_kc_id in exemplar_by_kc
        ]
        family_context_rows = _family_context_rows(
            rows_by_kc=rows_by_kc,
            target_descriptor=target_descriptor,
            sibling_descriptors=sibling_descriptors,
            limit=int(policy.family_context_limit),
        )
        if family_context_rows:
            kcs_with_family_context_candidates += 1
        completion_context_rows = _completion_context_rows(
            rows_by_page=rows_by_page,
            fragment_rows=rows,
            target_kc_id=kc_id,
            limit=int(policy.completion_context_limit),
        )
        if completion_context_rows:
            kcs_with_completion_context_candidates += 1
        candidate_rows = list(rows)
        seen_candidate_ids = {str(row.get("overlay_candidate_id") or "") for row in candidate_rows}
        for family_row in family_context_rows:
            family_candidate_id = str(family_row.get("overlay_candidate_id") or "")
            if family_candidate_id and family_candidate_id not in seen_candidate_ids:
                candidate_rows.append(dict(family_row))
                seen_candidate_ids.add(family_candidate_id)
        for completion_row in completion_context_rows:
            completion_candidate_id = str(completion_row.get("overlay_candidate_id") or "")
            if completion_candidate_id and completion_candidate_id not in seen_candidate_ids:
                candidate_rows.append(dict(completion_row))
                seen_candidate_ids.add(completion_candidate_id)
        rows_by_id = {str(row.get("overlay_candidate_id") or ""): row for row in candidate_rows}
        assessments_by_id = {
            str(row.get("overlay_candidate_id") or ""): assess_overlay_candidate(row)
            for row in candidate_rows
        }
        definition_evidence_packet = build_definition_evidence_packet(
            rows_by_id,
            assessments_by_id,
            target_kc_id=kc_id,
            max_items_per_role=2,
        )
        definition_candidate_family_phase: Dict[str, Any] = {
            "mode": definition_generation_mode,
            "candidate_count": 0,
            "candidates": [],
            "selected_candidate": {},
            "selected_candidate_kind": "",
            "used_for_selection": False,
        }
        if definition_generation_mode == DEFINITION_GENERATION_MODE_PACKET_MULTICANDIDATE:
            definition_candidate_family_phase = _build_definition_packet_candidate_family_phase(
                packet=definition_evidence_packet,
                rows_by_id=rows_by_id,
                target_descriptor=target_descriptor,
                sibling_descriptors=sibling_descriptors,
                mode=definition_generation_mode,
            )
        packet_selected_definition_candidate = dict(
            definition_candidate_family_phase.get("selected_candidate") or {}
        )
        definition_entries, definition_rejected_candidates, definition_rejected_by_reason = _definition_candidate_entries(
            {str(row.get("overlay_candidate_id") or ""): row for row in rows},
            {
                str(row.get("overlay_candidate_id") or ""): assessments_by_id.get(str(row.get("overlay_candidate_id") or ""), {})
                for row in rows
            },
        )
        kc_runtime_counters: Counter[str] = Counter()
        kc_llm_budget = _new_kc_llm_budget_state(policy.max_llm_calls_per_kc)
        for reason, count in dict(definition_rejected_by_reason).items():
            definition_rejection_counter[str(reason)] += int(count)

        scope_candidates = _scope_candidates(
            rows_by_id,
            assessments_by_id,
            target_descriptor=target_descriptor,
            sibling_descriptors=sibling_descriptors,
            limit=int(policy.scope_candidate_limit),
        )
        draft_response: Dict[str, Any] = {
            "definition": {"status": "abstained", "text": "", "supporting_overlay_candidate_ids": [], "abstention_reason": "insufficient_evidence"},
            "scope": {"status": "abstained", "text": "", "supporting_overlay_candidate_ids": [], "abstention_reason": "insufficient_evidence"},
        }
        verify_response: Dict[str, Any] = dict(draft_response)
        draft_meta: Dict[str, Any] = {"source": "skipped"}
        verify_meta: Dict[str, Any] = {"source": "skipped"}
        draft_error = ""
        verify_error = ""
        scope_redraft_response: Dict[str, Any] = {
            "scope": {"status": "abstained", "text": "", "supporting_overlay_candidate_ids": [], "abstention_reason": "insufficient_evidence"},
        }
        scope_redraft_verify_response: Dict[str, Any] = dict(scope_redraft_response)
        scope_redraft_meta: Dict[str, Any] = {"source": "skipped"}
        scope_redraft_verify_meta: Dict[str, Any] = {"source": "skipped"}
        scope_redraft_error = ""
        scope_redraft_verify_error = ""
        definition_redraft_response: Dict[str, Any] = {
            "definition": {"status": "abstained", "text": "", "supporting_overlay_candidate_ids": [], "abstention_reason": "insufficient_evidence"},
        }
        definition_redraft_verify_response: Dict[str, Any] = dict(definition_redraft_response)
        definition_redraft_meta: Dict[str, Any] = {"source": "skipped"}
        definition_redraft_verify_meta: Dict[str, Any] = {"source": "skipped"}
        definition_redraft_error = ""
        definition_redraft_verify_error = ""
        field_hold_reasons: Dict[str, List[str]] = {}
        field_protection_actions: List[str] = []
        definition_reference_bundle = dict((reference_bundles or {}).get(kc_id) or {})
        scope_reference_bundle = dict((reference_scope_bundles or reference_bundles or {}).get(kc_id) or {})
        normalized_definition_grounded = False
        control_fallback_candidate: Optional[FieldCandidate] = None
        control_fallback_source_phase = ""
        control_fallback_salvage_candidate: Optional[FieldCandidate] = None
        definition_support_binding_diagnostics: Dict[str, Any] = _definition_support_binding_diag(
            repair_state="no_binding_possible",
            repair_applied=False,
            repair_reason="definition_not_grounded",
            repair_attempt_reason="",
            current_support_ids=[],
            out_of_pool_support_ids=[],
            chosen_support_ids=[],
            current_binding_mode="none",
            final_binding_mode="none",
            stronger_same_kc_candidate_existed=False,
            candidate_anchor_pool_considered=[],
            weaker_anchor_rejections={},
        )
        if packet_selected_definition_candidate:
            preservation_phase = _skipped_joint_phase_for_packet_candidate(
                definition_candidate=packet_selected_definition_candidate,
            )
            field_protection_actions.append("accepted_packet_multicandidate_definition")
            definition_packet_family_recoveries += 1
        elif definition_generation_mode == DEFINITION_GENERATION_MODE_PACKET_MULTICANDIDATE:
            support_pack_preservation_phase = _run_definition_support_pack_phase(
                exemplar=exemplar,
                packet=definition_evidence_packet,
                rows_by_id=rows_by_id,
                assessments_by_id=assessments_by_id,
                target_descriptor=target_descriptor,
                sibling_descriptors=sibling_descriptors,
                policy=policy,
                runtime=runtime,
                counters=kc_runtime_counters,
                budget_state=kc_llm_budget,
            )
            support_pack_definition_candidate = dict(
                support_pack_preservation_phase.get("preserved_definition_candidate") or {}
            )
            if support_pack_definition_candidate:
                preservation_phase = support_pack_preservation_phase
                field_protection_actions.append("accepted_support_pack_audited_definition")
                definition_support_pack_auditor_recoveries += 1
            else:
                preservation_phase = _run_definition_preservation_phase(
                    exemplar=exemplar,
                    rows_by_id=rows_by_id,
                    assessments_by_id=assessments_by_id,
                    target_descriptor=target_descriptor,
                    sibling_descriptors=sibling_descriptors,
                    scope_candidates=scope_candidates,
                    policy=policy,
                    runtime=runtime,
                    counters=kc_runtime_counters,
                    budget_state=kc_llm_budget,
                )
        else:
            preservation_phase = _run_definition_preservation_phase(
                exemplar=exemplar,
                rows_by_id=rows_by_id,
                assessments_by_id=assessments_by_id,
                target_descriptor=target_descriptor,
                sibling_descriptors=sibling_descriptors,
                scope_candidates=scope_candidates,
                policy=policy,
                runtime=runtime,
                counters=kc_runtime_counters,
                budget_state=kc_llm_budget,
            )
        preservation_definition_candidates = list(preservation_phase.get("definition_candidates") or [])
        preservation_result = dict(preservation_phase.get("phase_result") or {})
        preservation_definition_candidate = dict(preservation_phase.get("preserved_definition_candidate") or {})
        preservation_scope_candidate = dict(preservation_phase.get("preserved_scope_candidate") or {})

        definition_support_pack_phase = _build_definition_support_pack_phase(
            rows_by_id=rows_by_id,
            assessments_by_id=assessments_by_id,
            target_descriptor=target_descriptor,
            sibling_descriptors=sibling_descriptors,
            policy=policy,
        )
        definition_support_pack = list(definition_support_pack_phase.get("support_pack") or [])
        rescue_phase = _run_definition_rescue_phase(
            exemplar=exemplar,
            preservation_phase=preservation_phase,
            support_pack_phase=definition_support_pack_phase,
            scope_candidates=scope_candidates,
            target_descriptor=target_descriptor,
            sibling_descriptors=sibling_descriptors,
            policy=policy,
            runtime=runtime,
            counters=kc_runtime_counters,
            budget_state=kc_llm_budget,
            rows_by_id=rows_by_id,
        )
        rescue_definition_candidates = list(rescue_phase.get("definition_candidates") or [])
        definition_candidates = rescue_definition_candidates or preservation_definition_candidates
        definition_redraft_candidates = _definition_rescue_candidates(
            definition_candidates,
            limit=int(policy.definition_candidate_limit),
        )

        preservation_draft_response = dict(preservation_result.get("draft_response") or draft_response)
        preservation_verify_response = dict(preservation_result.get("verify_response") or verify_response)
        preservation_draft_meta = dict(preservation_result.get("draft_meta") or {"source": "skipped"})
        preservation_verify_meta = dict(preservation_result.get("verify_meta") or {"source": "skipped"})
        preservation_draft_error = str(preservation_result.get("draft_error") or "")
        preservation_verify_error = str(preservation_result.get("verify_error") or "")

        rescue_result = dict(rescue_phase.get("phase_result") or {})
        rescue_draft_response = dict(rescue_result.get("draft_response") or draft_response)
        rescue_verify_response = dict(rescue_result.get("verify_response") or verify_response)
        rescue_draft_meta = dict(rescue_result.get("draft_meta") or {"source": "skipped"})
        rescue_verify_meta = dict(rescue_result.get("verify_meta") or {"source": "skipped"})
        rescue_draft_error = str(rescue_result.get("draft_error") or "")
        rescue_verify_error = str(rescue_result.get("verify_error") or "")
        rescue_definition_candidate = dict(rescue_result.get("definition_full_candidate") or {})
        rescue_scope_candidate = dict(rescue_result.get("scope_candidate") or {})
        preservation_short_circuited_rescue = bool(rescue_phase.get("preservation_short_circuited"))

        definition_full_candidate, scope_candidate, definition_monotonicity_action = _run_definition_verification_phase(
            preserved_definition_candidate=preservation_definition_candidate,
            rescue_definition_candidate=rescue_definition_candidate,
            preserved_scope_candidate=preservation_scope_candidate,
            rescue_scope_candidate=rescue_scope_candidate,
            rows_by_id=rows_by_id,
            target_descriptor=target_descriptor,
            sibling_descriptors=sibling_descriptors,
        )
        if definition_monotonicity_action:
            field_protection_actions.append(definition_monotonicity_action)

        effective_definition_phase = "preservation"
        if packet_selected_definition_candidate:
            effective_definition_phase = "packet_family"
        elif str(preservation_definition_candidate.get("selection_reason") or "") == "definition_full_candidate_support_pack_audited":
            effective_definition_phase = "support_pack"
        if definition_monotonicity_action in {
            "accepted_definition_rescue_candidate",
            "replaced_preserved_definition_with_strictly_better_rescue",
        } or (not definition_full_candidate and bool(rescue_phase.get("used"))):
            effective_definition_phase = "rescue"

        supporting_lookup = dict(preservation_result.get("supporting_lookup") or {})
        supporting_lookup.update(dict(rescue_result.get("supporting_lookup") or {}))
        available_overlay_ids = [
            str(item)
            for item in unique_preserve_order(list(supporting_lookup.keys()))
            if str(item)
        ]

        if effective_definition_phase == "rescue":
            draft_response = rescue_draft_response
            verify_response = rescue_verify_response
            draft_meta = rescue_draft_meta
            verify_meta = rescue_verify_meta
            draft_error = rescue_draft_error
            verify_error = rescue_verify_error
        else:
            draft_response = preservation_draft_response
            verify_response = preservation_verify_response
            draft_meta = preservation_draft_meta
            verify_meta = preservation_verify_meta
            draft_error = preservation_draft_error
            verify_error = preservation_verify_error

        legacy_redraft_path_enabled = not bool(definition_full_candidate)
        legacy_definition_redraft_allowed = bool(legacy_redraft_path_enabled and definition_redraft_candidates)

        if legacy_definition_redraft_allowed:
            definition_request_payload, definition_overlay_to_label = _definition_request_payload(
                exemplar,
                definition_candidates=definition_redraft_candidates,
                target_descriptor=target_descriptor,
                sibling_descriptors=sibling_descriptors,
                max_chars=int(policy.evidence_text_max_chars),
            )
            definition_label_to_overlay = {label: overlay_id for overlay_id, label in definition_overlay_to_label.items()}
            available_overlay_ids = [
                str(item)
                for item in unique_preserve_order(list(definition_overlay_to_label.keys()))
                if str(item)
            ]
            definition_allowed_ids = list(definition_label_to_overlay.keys())
            definition_request_payload["label_to_overlay_candidate_id"] = definition_label_to_overlay
            definition_schema = _definition_only_schema(definition_allowed_ids)
            definition_draft_messages = _definition_draft_messages(
                exemplar,
                definition_candidates=definition_redraft_candidates,
                target_descriptor=target_descriptor,
                sibling_descriptors=sibling_descriptors,
                max_chars=int(policy.evidence_text_max_chars),
            )
            try:
                raw_definition_draft_payload, definition_redraft_meta = _call_phase(
                    runtime=runtime,
                    counters=kc_runtime_counters,
                    budget_state=kc_llm_budget,
                    phase="definition_redraft",
                    request_payload=definition_request_payload,
                    schema=definition_schema,
                    messages=definition_draft_messages,
                )
                if not _definition_payload_has_expected_shape(raw_definition_draft_payload):
                    raise RuntimeError("definition_redraft_payload_shape_invalid")
                definition_redraft_response = {
                    "definition": _normalize_field_payload(
                        dict(raw_definition_draft_payload.get("definition") or {}),
                        allowed_ids=definition_allowed_ids,
                        id_lookup=definition_label_to_overlay,
                    )
                }
            except LLMCallBudgetExceededError as exc:
                definition_redraft_error = f"{type(exc).__name__}:{exc}"
            except Exception as exc:
                definition_redraft_error = f"{type(exc).__name__}:{exc}"
                kc_runtime_counters["definition_redraft_runtime_failures"] += 1

            if not definition_redraft_error:
                definition_evidence_lookup = {
                    definition_overlay_to_label[candidate.overlay_candidate_id]: {
                        "text": candidate.text,
                        "candidate_kind": candidate.candidate_kind,
                    }
                    for candidate in definition_redraft_candidates
                    if candidate.overlay_candidate_id in definition_overlay_to_label
                }
                definition_verify_request_payload = {
                    "draft": raw_definition_draft_payload,
                    "evidence_lookup": definition_evidence_lookup,
                }
                definition_verify_messages = _definition_verify_messages(
                    exemplar,
                    draft_payload=raw_definition_draft_payload,
                    evidence_lookup=definition_evidence_lookup,
                    sibling_descriptors=sibling_descriptors,
                    max_chars=int(policy.evidence_text_max_chars),
                )
                try:
                    raw_definition_verify_payload, definition_redraft_verify_meta = _call_phase(
                        runtime=runtime,
                        counters=kc_runtime_counters,
                        budget_state=kc_llm_budget,
                        phase="definition_verify",
                        request_payload=definition_verify_request_payload,
                        schema=definition_schema,
                        messages=definition_verify_messages,
                    )
                    if not _definition_payload_has_expected_shape(raw_definition_verify_payload):
                        raise RuntimeError("definition_verify_payload_shape_invalid")
                    definition_redraft_verify_response = {
                        "definition": _normalize_field_payload(
                            dict(raw_definition_verify_payload.get("definition") or {}),
                            allowed_ids=definition_allowed_ids,
                            id_lookup=definition_label_to_overlay,
                        )
                    }
                    definition_full_candidate = _candidate_value_from_verified(
                        field_name="definition_full_candidate",
                        normalized_field=definition_redraft_verify_response.get("definition") or {},
                        supporting_lookup=supporting_lookup,
                    )
                    if definition_full_candidate:
                        definition_redraft_recoveries += 1
                except LLMCallBudgetExceededError as exc:
                    definition_redraft_verify_error = f"{type(exc).__name__}:{exc}"
                except Exception as exc:
                    definition_redraft_verify_error = f"{type(exc).__name__}:{exc}"
                    kc_runtime_counters["definition_verify_runtime_failures"] += 1

        allow_post_verify_definition_fallback = bool(
            draft_error
            or verify_error
            or definition_redraft_error
            or definition_redraft_verify_error
        )

        if not definition_full_candidate and allow_post_verify_definition_fallback:
            definition_full_candidate = _definition_context_completion_candidate(
                definition_candidates,
                completion_context_rows=completion_context_rows,
                rows_by_page=rows_by_page,
                rows_by_id=rows_by_id,
                assessments_by_id=assessments_by_id,
                target_descriptor=target_descriptor,
                sibling_descriptors=sibling_descriptors,
            )
            if definition_full_candidate:
                definition_context_completion_recoveries += 1

        if not definition_full_candidate and allow_post_verify_definition_fallback:
            fallback_candidate = _definition_single_span_fallback_candidate(
                definition_candidates,
                target_descriptor=target_descriptor,
                sibling_descriptors=sibling_descriptors,
            )
            if fallback_candidate is not None:
                definition_full_candidate = _candidate_value_from_single_candidate(
                    field_name="definition_full_candidate",
                    candidate=fallback_candidate,
                    selection_reason="definition_full_candidate_single_span_fallback",
                )
                definition_single_span_fallback_recoveries += 1

        definition_candidate_for_normalization = dict(definition_full_candidate or {})
        definition_rejected_for_boundary = False
        if definition_full_candidate and _field_definition_sibling_risk(
            definition_full_candidate,
            rows_by_id=rows_by_id,
            target_descriptor=target_descriptor,
            sibling_descriptors=sibling_descriptors,
        ):
            sibling_definition_rejections += 1
            definition_rejected_for_boundary = True
            definition_full_candidate = {}

        if not definition_full_candidate:
            normalized_definition_candidate = _source_faithful_normalized_definition_candidate(
                exemplar=exemplar,
                current_value=definition_candidate_for_normalization,
                draft_response=draft_response,
                verify_response=verify_response,
                definition_redraft_response=definition_redraft_response,
                definition_redraft_verify_response=definition_redraft_verify_response,
                rows=rows,
                rows_by_id=rows_by_id,
                assessments_by_id=assessments_by_id,
                target_descriptor=target_descriptor,
                sibling_descriptors=sibling_descriptors,
            )
            if normalized_definition_candidate:
                definition_full_candidate = normalized_definition_candidate
                normalized_definition_grounded = True
                definition_source_faithful_normalization_recoveries += 1
            elif definition_rejected_for_boundary:
                field_hold_reasons.setdefault("definition_full_candidate", []).append("sibling_boundary_mismatch")

        if not definition_full_candidate and not definition_rejected_for_boundary:
            control_fallback_candidate, control_fallback_source_phase = _definition_draft_supported_single_span_fallback_candidate(
                definition_candidates=definition_candidates,
                preservation_draft_response=preservation_draft_response,
                rescue_draft_response=rescue_draft_response,
                definition_redraft_response=definition_redraft_response,
                target_descriptor=target_descriptor,
                sibling_descriptors=sibling_descriptors,
            )
            if control_fallback_candidate is not None:
                control_fallback_value, control_fallback_normalized = _definition_draft_supported_single_span_fallback_value(
                    field_name="definition_full_candidate",
                    candidate=control_fallback_candidate,
                    target_descriptor=target_descriptor,
                )
                if not control_fallback_value:
                    (
                        control_fallback_value,
                        control_fallback_normalized,
                        control_fallback_salvage_candidate,
                    ) = _definition_draft_supported_single_span_fallback_salvage_value(
                        definition_candidates=definition_candidates,
                        blocked_candidate=control_fallback_candidate,
                        target_descriptor=target_descriptor,
                        local_rows=rows,
                        assessments_by_id=assessments_by_id,
                    )
                if control_fallback_value:
                    definition_full_candidate = control_fallback_value
                    if control_fallback_normalized:
                        normalized_definition_grounded = True
                        definition_source_faithful_normalization_recoveries += 1
                    else:
                        definition_draft_supported_single_span_fallback_recoveries += 1

        protected_definition, definition_protection_action = _maybe_apply_reference_field_protection(
            field_name="definition_full_candidate",
            current_value=definition_full_candidate,
            reference_bundle=definition_reference_bundle,
            rows_by_id=rows_by_id,
            target_descriptor=target_descriptor,
            sibling_descriptors=sibling_descriptors,
        )
        if definition_protection_action:
            definition_full_candidate = protected_definition
            field_protection_actions.append(definition_protection_action)
            reference_definition_preservations += 1
        if definition_full_candidate:
            definition_full_candidate, definition_support_binding_diagnostics = _repair_definition_support_binding(
                current_value=definition_full_candidate,
                definition_candidates=definition_candidates,
                rows_by_id=rows_by_id,
                target_descriptor=target_descriptor,
                sibling_descriptors=sibling_descriptors,
                max_support_rows=int(policy.max_definition_binding_support_rows),
                max_chars=int(policy.evidence_text_max_chars),
            )
        normalized_definition_grounded = bool(
            normalized_definition_grounded
            and str(definition_full_candidate.get("status") or "") == ENRICHMENT_LAYER_STATUS_GROUNDED
            and str(definition_full_candidate.get("selection_reason") or "").startswith(
                "definition_full_candidate_source_faithful_"
            )
        )
        if definition_full_candidate:
            field_hold_reasons.pop("definition_full_candidate", None)
            _augment_supporting_lookup_from_value(
                definition_full_candidate,
                supporting_lookup=supporting_lookup,
                rows_by_id=rows_by_id,
                assessments_by_id=assessments_by_id,
            )
        definition_grounding_diagnostics = _definition_grounding_diag(
            definition_candidates=definition_candidates,
            preservation_definition_candidates=preservation_definition_candidates,
            definition_support_pack=definition_support_pack,
            preservation_draft_response=preservation_draft_response,
            preservation_verify_response=preservation_verify_response,
            rescue_used=bool(rescue_phase.get("used")),
            rescue_draft_response=rescue_draft_response,
            rescue_verify_response=rescue_verify_response,
            definition_redraft_response=definition_redraft_response,
                definition_redraft_verify_response=definition_redraft_verify_response,
                final_definition_candidate=definition_full_candidate,
                control_fallback_candidate=control_fallback_candidate,
                control_fallback_source_phase=control_fallback_source_phase,
                control_fallback_salvage_candidate=control_fallback_salvage_candidate,
            )

        legacy_scope_redraft_allowed = bool(
            legacy_redraft_path_enabled
            and not scope_candidate
            and definition_full_candidate
            and scope_candidates
        )

        if legacy_scope_redraft_allowed:
                definition_context_candidates = _definition_context_candidates(
                    definition_full_candidate,
                    supporting_lookup=supporting_lookup,
                    definition_candidates=definition_candidates,
                    limit=3,
                )
                scope_request_payload, scope_overlay_to_label = _scope_request_payload(
                    exemplar,
                    definition_full_candidate=definition_full_candidate,
                    definition_context_candidates=definition_context_candidates,
                    scope_candidates=scope_candidates,
                    target_descriptor=target_descriptor,
                    sibling_descriptors=sibling_descriptors,
                    max_chars=int(policy.evidence_text_max_chars),
                )
                scope_label_to_overlay = {label: overlay_id for overlay_id, label in scope_overlay_to_label.items()}
                scope_allowed_ids = list(scope_label_to_overlay.keys())
                scope_request_payload["label_to_overlay_candidate_id"] = scope_label_to_overlay
                scope_schema = _scope_only_schema(scope_allowed_ids)
                scope_draft_messages = _scope_draft_messages(
                    exemplar,
                    definition_full_candidate=definition_full_candidate,
                    definition_context_candidates=definition_context_candidates,
                    scope_candidates=scope_candidates,
                    target_descriptor=target_descriptor,
                    sibling_descriptors=sibling_descriptors,
                    max_chars=int(policy.evidence_text_max_chars),
                )
                try:
                    raw_scope_draft_payload, scope_redraft_meta = _call_phase(
                        runtime=runtime,
                        counters=kc_runtime_counters,
                        budget_state=kc_llm_budget,
                        phase="scope_redraft",
                        request_payload=scope_request_payload,
                        schema=scope_schema,
                        messages=scope_draft_messages,
                    )
                    if not _scope_payload_has_expected_shape(raw_scope_draft_payload):
                        raise RuntimeError("scope_redraft_payload_shape_invalid")
                    scope_redraft_response = {
                        "scope": _normalize_field_payload(
                            dict(raw_scope_draft_payload.get("scope") or {}),
                            allowed_ids=scope_allowed_ids,
                            id_lookup=scope_label_to_overlay,
                        )
                    }
                except LLMCallBudgetExceededError as exc:
                    scope_redraft_error = f"{type(exc).__name__}:{exc}"
                except Exception as exc:
                    scope_redraft_error = f"{type(exc).__name__}:{exc}"
                    kc_runtime_counters["scope_redraft_runtime_failures"] += 1

                if not scope_redraft_error:
                    scope_evidence_lookup = {
                        scope_overlay_to_label[candidate.overlay_candidate_id]: {
                            "text": candidate.text,
                            "candidate_kind": candidate.candidate_kind,
                        }
                        for candidate in [*definition_context_candidates, *scope_candidates]
                        if candidate.overlay_candidate_id in scope_overlay_to_label
                    }
                    scope_verify_request_payload = {
                        "verified_definition": definition_full_candidate,
                        "draft": raw_scope_draft_payload,
                        "evidence_lookup": scope_evidence_lookup,
                    }
                    scope_verify_messages = _scope_verify_messages(
                        exemplar,
                        definition_full_candidate=definition_full_candidate,
                        draft_payload=raw_scope_draft_payload,
                        evidence_lookup=scope_evidence_lookup,
                        sibling_descriptors=sibling_descriptors,
                        max_chars=int(policy.evidence_text_max_chars),
                    )
                    try:
                        raw_scope_verify_payload, scope_redraft_verify_meta = _call_phase(
                            runtime=runtime,
                            counters=kc_runtime_counters,
                            budget_state=kc_llm_budget,
                            phase="scope_verify",
                            request_payload=scope_verify_request_payload,
                            schema=scope_schema,
                            messages=scope_verify_messages,
                        )
                        if not _scope_payload_has_expected_shape(raw_scope_verify_payload):
                            raise RuntimeError("scope_verify_payload_shape_invalid")
                        scope_redraft_verify_response = {
                            "scope": _normalize_field_payload(
                                dict(raw_scope_verify_payload.get("scope") or {}),
                                allowed_ids=scope_allowed_ids,
                                id_lookup=scope_label_to_overlay,
                            )
                        }
                        scope_candidate = _candidate_value_from_verified(
                            field_name="scope_candidate",
                            normalized_field=scope_redraft_verify_response.get("scope") or {},
                            supporting_lookup=supporting_lookup,
                        )
                        if scope_candidate:
                            scope_redraft_recoveries += 1
                    except LLMCallBudgetExceededError as exc:
                        scope_redraft_verify_error = f"{type(exc).__name__}:{exc}"
                    except Exception as exc:
                        scope_redraft_verify_error = f"{type(exc).__name__}:{exc}"
                        kc_runtime_counters["scope_verify_runtime_failures"] += 1

        protected_scope, scope_protection_action = _maybe_apply_reference_field_protection(
            field_name="scope_candidate",
            current_value=scope_candidate,
            reference_bundle=scope_reference_bundle,
            rows_by_id=rows_by_id,
            target_descriptor=target_descriptor,
            sibling_descriptors=sibling_descriptors,
        )
        if scope_protection_action:
            scope_candidate = protected_scope
            field_protection_actions.append(scope_protection_action)
            reference_scope_preservations += 1
        if scope_candidate:
            field_hold_reasons.pop("scope_candidate", None)

        evidence_pack_trace = _step67_evidence_pack_trace(exemplar)
        evidence_pack_route = str(evidence_pack_trace.get("route") or "")

        if evidence_pack_route == "insufficient_support_packet":
            if (
                isinstance(definition_full_candidate, dict)
                and definition_full_candidate.get("status") == ENRICHMENT_LAYER_STATUS_GROUNDED
            ):
                field_hold_reasons.setdefault("definition_full_candidate", []).append(
                    "evidence_pack_route_insufficient_support"
                )
                definition_full_candidate = {}
            if (
                isinstance(scope_candidate, dict)
                and scope_candidate.get("status") == SCOPE_LAYER_STATUS_GROUNDED
            ):
                field_hold_reasons.setdefault("scope_candidate", []).append(
                    "evidence_pack_route_insufficient_support"
                )
                scope_candidate = {}
        elif not _step67_candidate_matches_ordered_role(
            definition_full_candidate,
            exemplar,
            "definition_kernel",
        ):
            role_policy_candidate = _step67_preferred_definition_kernel_candidate(exemplar, rows)
            if role_policy_candidate:
                definition_full_candidate = role_policy_candidate
                field_hold_reasons.pop("definition_full_candidate", None)

        if not definition_full_candidate:
            reasons = ["definition_support_insufficient", *field_hold_reasons.get("definition_full_candidate", [])]
            if draft_error or definition_redraft_error:
                reasons.append("definition_drafting_runtime_failed")
            elif verify_error or definition_redraft_verify_error:
                reasons.append("definition_verification_runtime_failed")
            elif available_overlay_ids:
                reasons.append("definition_candidate_verifier_rejected")
            else:
                reasons.append("no_definition_candidate_pool")
            definition_full_candidate = _abstained_value(field_name="definition_full_candidate", reasons=reasons)
            field_hold_reasons["definition_full_candidate"] = reasons
            verifier_abstained_definition_kcs += 1

        if not scope_candidate:
            reasons = ["scope_support_insufficient", *field_hold_reasons.get("scope_candidate", [])]
            if draft_error or scope_redraft_error:
                reasons.append("scope_drafting_runtime_failed")
            elif verify_error or scope_redraft_verify_error:
                reasons.append("scope_verification_runtime_failed")
            else:
                reasons.append("no_safe_scope_draft")
            scope_candidate = _abstained_value(field_name="scope_candidate", reasons=reasons)
            field_hold_reasons["scope_candidate"] = reasons
            verifier_abstained_scope_kcs += 1

        definition_short_candidate = _definition_short_candidate(
            definition_full_candidate,
            max_chars=int(policy.short_definition_max_chars),
            max_tokens=int(policy.short_definition_max_tokens),
        )
        if not definition_short_candidate:
            reasons = ["definition_short_unavailable"]
            definition_short_candidate = _abstained_value(field_name="definition_short_candidate", reasons=reasons)
            field_hold_reasons["definition_short_candidate"] = reasons

        prioritized_candidate_ids = unique_preserve_order(
            [
                *[str(item) for item in definition_full_candidate.get("supporting_overlay_candidate_ids") or []],
                *[str(item) for item in scope_candidate.get("supporting_overlay_candidate_ids") or []],
                *[item.overlay_candidate_id for item in definition_candidates],
                *[item.overlay_candidate_id for item in scope_candidates],
            ]
        )
        blocked_bundle_candidate_ids = _blocked_bundle_candidate_ids(
            rows_by_id,
            assessments_by_id,
            definition_rejected_candidates,
        )
        selection = select_evidence_bundle(
            rows,
            max_bundle_size=int(policy.max_bundle_size),
            max_explanatory_candidates=int(policy.max_explanatory_candidates),
            assessments_by_id=assessments_by_id,
            prioritized_candidate_ids=prioritized_candidate_ids,
            blocked_candidate_ids=blocked_bundle_candidate_ids,
        )
        selected_bundle = _ensure_supported_bundle_items(
            selected_bundle=selection.get("selected") or [],
            rows_by_id=rows_by_id,
            assessments_by_id=assessments_by_id,
            definition_support_ids=definition_full_candidate.get("supporting_overlay_candidate_ids") or [],
            scope_support_ids=scope_candidate.get("supporting_overlay_candidate_ids") or [],
        )
        selection = dict(selection)
        selection["selected"] = selected_bundle

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
        contamination_flags = [str(item) for item in unique_preserve_order(contamination_flags)]

        hold_reasons = unique_preserve_order(
            reason
            for reasons in field_hold_reasons.values()
            for reason in reasons
        )
        definition_grounded = definition_full_candidate.get("status") == ENRICHMENT_LAYER_STATUS_GROUNDED
        scope_grounded = scope_candidate.get("status") == SCOPE_LAYER_STATUS_GROUNDED
        if not definition_grounded:
            kcs_held_for_insufficient_support += 1
            kcs_with_abstained_definitions += 1

        fallback_context_bundle, fallback_context_reasons = _fallback_context_bundle(
            rows=rows,
            assessments_by_id=assessments_by_id,
            selection=selection,
            max_bundle_size=int(policy.max_bundle_size),
        )
        context_bundle = selected_bundle or fallback_context_bundle
        if selected_bundle:
            context_status = CONTEXT_LAYER_STATUS_GROUNDED
        elif fallback_context_bundle:
            context_status = CONTEXT_LAYER_STATUS_FALLBACK
        else:
            context_status = CONTEXT_LAYER_STATUS_MISSING
        if fallback_context_reasons:
            hold_reasons = unique_preserve_order([*hold_reasons, *fallback_context_reasons])

        selected_definition_surface_quality = selected_definition_review_quality(
            definition_full_candidate,
            rows_by_id,
            assessments_by_id,
        )
        selected_definition_surface_risk_flags = [
            str(item)
            for item in selected_definition_surface_quality.get("risk_flags") or []
            if str(item)
        ]
        selected_definition_review_suppressed = bool(
            selected_definition_surface_quality.get("suppressed")
        )
        if selected_definition_review_suppressed:
            hold_reasons = unique_preserve_order(
                [*hold_reasons, SELECTED_DEFINITION_SURFACE_REVIEW_SUPPRESSED_FLAG]
            )
            selected_definition_review_suppressed_count += 1
            for flag in selected_definition_surface_risk_flags:
                selected_definition_surface_risk_counter[str(flag)] += 1

        coverage_state = _coverage_state(exemplar)
        enrichment_layer = _definition_enrichment_layer(definition_full_candidate, definition_short_candidate)
        context_layer = _context_layer(
            context_bundle=context_bundle,
            context_status=context_status,
            family_context_rows=family_context_rows,
            completion_context_rows=completion_context_rows,
        )
        scope_layer = _scope_layer(scope_candidate)
        risk_flags = _semantic_risk_flags(
            contamination_flags=contamination_flags,
            hold_reasons=hold_reasons,
            definition_grounded=definition_grounded,
            scope_grounded=scope_grounded,
            context_status=context_status,
        )
        if selected_definition_surface_risk_flags:
            risk_flags = unique_preserve_order(
                [
                    *risk_flags,
                    *selected_definition_surface_risk_flags,
                    REVIEW_NEEDS_ATTENTION_FLAG,
                ]
            )
        trust_state = _trust_state(
            definition_grounded=definition_grounded,
            scope_grounded=scope_grounded,
            context_status=context_status,
            risk_flags=risk_flags,
        )
        review_readiness = _review_readiness(
            trust_state=trust_state,
            hold_reasons=hold_reasons,
            risk_flags=risk_flags,
        )
        authoritative_definition_status = _authoritative_definition_status(
            definition_grounded=definition_grounded,
            normalized_grounded=normalized_definition_grounded,
        )
        draft_status = str(review_readiness.get("draft_status_compatibility") or "draft_ready_with_holds")
        draft_status_counter[draft_status] += 1
        trust_state_counter[str(trust_state.get("label") or "unknown")] += 1
        review_readiness_counter[str(review_readiness.get("label") or "unknown")] += 1
        context_layer_status_counter[context_status] += 1
        authoritative_definition_status_counter[authoritative_definition_status] += 1
        if not definition_grounded:
            coverage_only_count += 1
        if context_status == CONTEXT_LAYER_STATUS_FALLBACK:
            context_fallback_count += 1

        if definition_grounded:
            kcs_with_definition_candidates += 1
        if scope_grounded:
            kcs_with_grounded_scopes += 1
        if contamination_flags:
            kcs_with_contamination_flags += 1
            for flag in contamination_flags:
                contamination_flag_counter[str(flag)] += 1

        support_state = str(support_summary.get("support_state") or "insufficient_support")
        support_state_counter[support_state] += 1
        context_bundle, evidence_bundle_policy_flags = _step67_filter_context_bundle_by_evidence_pack_policy(
            context_bundle=context_bundle,
            exemplar=exemplar,
            rows=rows,
            definition_full_candidate=definition_full_candidate,
            scope_candidate=scope_candidate,
        )
        if evidence_bundle_policy_flags:
            hold_reasons = unique_preserve_order([*hold_reasons, *evidence_bundle_policy_flags])
            contamination_flags = unique_preserve_order([*contamination_flags, *evidence_bundle_policy_flags])

        evidence_bundle_size_distribution[str(len(context_bundle))] += 1

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
                "status": context_status,
                "overlay_candidate_ids": [str(item.get("overlay_candidate_id") or "") for item in context_bundle],
                "source_set_ids": source_set_ids,
                "source_run_ids": source_run_ids,
            },
        }
        if bool(kc_llm_budget.get("budget_exhausted")):
            kcs_with_llm_budget_exhaustion += 1
        runtime_counters.update(kc_runtime_counters)
        hierarchy_fields = typed_topic_hierarchy_fields(exemplar)
        evidence_pack_quality = dict(exemplar.get("evidence_pack_quality") or {})
        evidence_pack_diagnostics = {
            "available": bool(exemplar.get("evidence_pack_available", False)),
            "version": str(exemplar.get("evidence_pack_version") or ""),
            "route": str(evidence_pack_quality.get("route") or ""),
            "definition_anchor_present": bool(evidence_pack_quality.get("definition_anchor_present", False)),
            "definition_anchor_natural_language": bool(
                evidence_pack_quality.get("definition_anchor_natural_language", False)
            ),
            "formula_dominance_risk": str(evidence_pack_quality.get("formula_dominance_risk") or ""),
            "sibling_contamination_risk": str(evidence_pack_quality.get("sibling_contamination_risk") or ""),
            "context_completion_used": bool(evidence_pack_quality.get("context_completion_used", False)),
            "ordered_pack_count": len(exemplar.get("ordered_pack_for_drafting") or []),
            "membership_roles": [
                str(item)
                for item in ((exemplar.get("evidence_pack_membership") or {}).get("slot_roles") or [])
            ],
        }

        bundle = {
            "draft_contract_version": DRAFT_CONTRACT_VERSION,
            "semantic_contract_version": STEP67_SEMANTIC_CONTRACT_VERSION,
            "drafting_mode": MODEL_DRAFTING_MODE,
            "kc_id": kc_id,
            "knowledge_unit_id": str(exemplar.get("knowledge_unit_id") or exemplar.get("kc_id") or kc_id),
            "knowledge_unit_type": str(exemplar.get("knowledge_unit_type") or "kc"),
            "canonical_name": str(exemplar.get("canonical_name") or ""),
            "aliases": [str(item) for item in exemplar.get("aliases") or []],
            "authoritative_definition_status": authoritative_definition_status,
            "coverage_state": coverage_state,
            **hierarchy_fields,
            "draft_input_overlay_set_id": str(exemplar.get("draft_input_overlay_set_id") or ""),
            "draft_status": draft_status,
            "enrichment_layer": enrichment_layer,
            "context_layer": context_layer,
            "scope_layer": scope_layer,
            "trust_state": trust_state,
            "risk_flags": risk_flags,
            "review_readiness": review_readiness,
            "selected_definition_surface_quality": selected_definition_surface_quality,
            "selected_definition_surface_risk_flags": selected_definition_surface_risk_flags,
            "selected_definition_review_suppressed": selected_definition_review_suppressed,
            "definition_full_candidate": definition_full_candidate,
            "definition_short_candidate": definition_short_candidate,
            "scope_candidate": scope_candidate,
            "evidence_bundle": context_bundle,
            "support_summary": support_summary,
            "evidence_pack_trace": evidence_pack_trace,
            "contamination_flags": contamination_flags,
            "hold_reasons": hold_reasons,
            "field_hold_reasons": field_hold_reasons,
            "field_provenance_map": field_provenance_map,
            "selection_diagnostics": {
                "evidence_pack": evidence_pack_diagnostics,
                "prioritized_candidate_ids": prioritized_candidate_ids,
                "blocked_bundle_candidate_ids": blocked_bundle_candidate_ids,
                "selected_candidate_ids": [str(item.get("overlay_candidate_id") or "") for item in context_bundle],
                "selected_bundle_candidate_ids": [str(item.get("overlay_candidate_id") or "") for item in selected_bundle],
                "fallback_context_candidate_ids": [str(item.get("overlay_candidate_id") or "") for item in fallback_context_bundle],
                "context_bundle_mode": "selected" if selected_bundle else ("fallback" if fallback_context_bundle else "missing"),
                "excluded_by_reason": dict(selection.get("excluded_by_reason") or {}),
                "excluded_candidates": list(selection.get("excluded") or []),
                "definition_candidate_diagnostics": {
                    "accepted_candidate_ids": [str(item.get("candidate_id") or "") for item in definition_entries[:5]],
                    "rejected_by_reason": definition_rejected_by_reason,
                    "rejected_candidates": definition_rejected_candidates[:10],
                },
                "field_candidate_sets": {
                    "definition_evidence_packet": dict(definition_evidence_packet),
                    "definition_candidate_family": list(
                        definition_candidate_family_phase.get("candidates") or []
                    ),
                    "definition_candidate_family_selected": dict(
                        definition_candidate_family_phase.get("selected_candidate") or {}
                    ),
                    "definition_generation_mode": definition_generation_mode,
                    "selected_definition_surface_quality": dict(
                        selected_definition_surface_quality
                    ),
                    "definition": [
                        _candidate_diag_payload_with_context(
                            item,
                            target_descriptor=target_descriptor,
                            sibling_descriptors=sibling_descriptors,
                            max_chars=int(policy.evidence_text_max_chars),
                        )
                        for item in definition_candidates
                    ],
                    "definition_preservation": [
                        _candidate_diag_payload_with_context(
                            item,
                            target_descriptor=target_descriptor,
                            sibling_descriptors=sibling_descriptors,
                            max_chars=int(policy.evidence_text_max_chars),
                        )
                        for item in preservation_definition_candidates
                    ],
                    "definition_support_pack": [dict(item) for item in definition_support_pack],
                    "scope": [
                        _candidate_diag_payload_with_context(
                            item,
                            target_descriptor=target_descriptor,
                            sibling_descriptors=sibling_descriptors,
                            max_chars=int(policy.evidence_text_max_chars),
                        )
                        for item in scope_candidates
                    ],
                    "family_context_candidate_ids": [
                        str(item.get("overlay_candidate_id") or "")
                        for item in family_context_rows
                    ],
                    "completion_context_candidate_ids": [
                        str(item.get("overlay_candidate_id") or "")
                        for item in completion_context_rows
                    ],
                    "sibling_contrast": _sibling_descriptor_payloads(
                        sibling_descriptors,
                        limit=int(policy.family_context_limit),
                    ),
                },
                "definition_support_binding": dict(definition_support_binding_diagnostics),
                "definition_grounding_diagnostics": dict(definition_grounding_diagnostics),
                "field_protection_actions": field_protection_actions,
                "llm_drafting": {
                    "effective_definition_phase": effective_definition_phase,
                    "preservation_mode": str(preservation_phase.get("preservation_mode") or "joint_draft"),
                    "support_pack_mode_requested": (
                        definition_generation_mode == DEFINITION_GENERATION_MODE_PACKET_MULTICANDIDATE
                    ),
                    "packet_family_selected": bool(packet_selected_definition_candidate),
                    "support_pack_audited_definition_selected": (
                        str(preservation_definition_candidate.get("selection_reason") or "")
                        == "definition_full_candidate_support_pack_audited"
                    ),
                    "preservation_short_circuited_rescue": preservation_short_circuited_rescue,
                    "rescue_used": bool(rescue_phase.get("used")),
                    "rescue_candidate_pool_changed": bool(rescue_phase.get("candidate_pool_changed")),
                    "draft_supported_single_span_fallback_applied": bool(
                        definition_grounding_diagnostics.get("draft_supported_single_span_fallback_applied")
                    ),
                    "legacy_redraft_path_enabled": legacy_redraft_path_enabled,
                    "legacy_definition_redraft_allowed": legacy_definition_redraft_allowed,
                    "legacy_scope_redraft_allowed": legacy_scope_redraft_allowed,
                    "draft_response": draft_response,
                    "verify_response": verify_response,
                    "draft_error": draft_error,
                    "verify_error": verify_error,
                    "preservation_draft_response": preservation_draft_response,
                    "preservation_verify_response": preservation_verify_response,
                    "preservation_draft_error": preservation_draft_error,
                    "preservation_verify_error": preservation_verify_error,
                    "rescue_draft_response": rescue_draft_response,
                    "rescue_verify_response": rescue_verify_response,
                    "rescue_draft_error": rescue_draft_error,
                    "rescue_verify_error": rescue_verify_error,
                    "scope_redraft_response": scope_redraft_response,
                    "scope_redraft_verify_response": scope_redraft_verify_response,
                    "scope_redraft_error": scope_redraft_error,
                    "scope_redraft_verify_error": scope_redraft_verify_error,
                    "definition_redraft_response": definition_redraft_response,
                    "definition_redraft_verify_response": definition_redraft_verify_response,
                    "definition_redraft_error": definition_redraft_error,
                    "definition_redraft_verify_error": definition_redraft_verify_error,
                    "draft_meta": {key: value for key, value in draft_meta.items() if key != "raw_response"},
                    "verify_meta": {key: value for key, value in verify_meta.items() if key != "raw_response"},
                    "preservation_draft_meta": {
                        key: value for key, value in preservation_draft_meta.items() if key != "raw_response"
                    },
                    "preservation_verify_meta": {
                        key: value for key, value in preservation_verify_meta.items() if key != "raw_response"
                    },
                    "rescue_draft_meta": {
                        key: value for key, value in rescue_draft_meta.items() if key != "raw_response"
                    },
                    "rescue_verify_meta": {
                        key: value for key, value in rescue_verify_meta.items() if key != "raw_response"
                    },
                    "scope_redraft_meta": {key: value for key, value in scope_redraft_meta.items() if key != "raw_response"},
                    "scope_redraft_verify_meta": {
                        key: value for key, value in scope_redraft_verify_meta.items() if key != "raw_response"
                    },
                    "definition_redraft_meta": {
                        key: value for key, value in definition_redraft_meta.items() if key != "raw_response"
                    },
                    "definition_redraft_verify_meta": {
                        key: value for key, value in definition_redraft_verify_meta.items() if key != "raw_response"
                    },
                    "llm_call_budget": {
                        "max_calls": int(kc_llm_budget.get("max_calls") or 0),
                        "calls_used": int(kc_llm_budget.get("calls_used") or 0),
                        "remaining_calls": int(kc_llm_budget.get("remaining_calls") or 0),
                        "budget_exhausted": bool(kc_llm_budget.get("budget_exhausted")),
                        "blocked_phases": [str(item) for item in kc_llm_budget.get("blocked_phases") or [] if str(item)],
                        "phase_call_order": [str(item) for item in kc_llm_budget.get("phase_call_order") or [] if str(item)],
                        "phase_call_counts": {
                            str(key): int(value)
                            for key, value in dict(kc_llm_budget.get("phase_call_counts") or {}).items()
                            if str(key)
                        },
                    },
                },
            },
            "step5_3_review_queue_aux": dict(exemplar.get("step5_3_review_queue_aux") or {}),
            "source_run_id": source_run_ids[0] if source_run_ids else "",
            "source_set_id": source_set_ids[0] if source_set_ids else "",
        }
        if str(bundle.get("knowledge_unit_type") or "kc") == "kc":
            bundle = attach_kc_specific_criteria_placeholder(bundle)
        bundles.append(bundle)

    stats = {
        "draft_contract_version": DRAFT_CONTRACT_VERSION,
        "semantic_contract_version": STEP67_SEMANTIC_CONTRACT_VERSION,
        "drafting_mode": MODEL_DRAFTING_MODE,
        "model_name": runtime.model,
        "total_kcs": len(bundles),
        "llm_call_budget_per_kc_max": int(policy.max_llm_calls_per_kc),
        "kcs_with_llm_budget_exhaustion": kcs_with_llm_budget_exhaustion,
        "kcs_with_definition_candidates": kcs_with_definition_candidates,
        "kcs_with_grounded_scopes": kcs_with_grounded_scopes,
        "kcs_with_abstained_definitions": kcs_with_abstained_definitions,
        "kcs_with_contamination_flags": kcs_with_contamination_flags,
        "kcs_held_for_insufficient_support": kcs_held_for_insufficient_support,
        "definition_redraft_recoveries": definition_redraft_recoveries,
        "definition_source_faithful_normalization_recoveries": definition_source_faithful_normalization_recoveries,
        "definition_context_completion_recoveries": definition_context_completion_recoveries,
        "definition_single_span_fallback_recoveries": definition_single_span_fallback_recoveries,
        "definition_draft_supported_single_span_fallback_recoveries": definition_draft_supported_single_span_fallback_recoveries,
        "definition_generation_mode": definition_generation_mode,
        "definition_packet_family_recoveries": definition_packet_family_recoveries,
        "definition_support_pack_auditor_recoveries": definition_support_pack_auditor_recoveries,
        "selected_definition_review_suppressed_count": selected_definition_review_suppressed_count,
        "selected_definition_surface_risk_breakdown": dict(
            sorted(selected_definition_surface_risk_counter.items())
        ),
        "scope_redraft_recoveries": scope_redraft_recoveries,
        "reference_definition_preservations": reference_definition_preservations,
        "reference_scope_preservations": reference_scope_preservations,
        "sibling_definition_rejections": sibling_definition_rejections,
        "kcs_with_family_context_candidates": kcs_with_family_context_candidates,
        "kcs_with_completion_context_candidates": kcs_with_completion_context_candidates,
        "verifier_abstained_definition_kcs": verifier_abstained_definition_kcs,
        "verifier_abstained_scope_kcs": verifier_abstained_scope_kcs,
        "coverage_only_count": coverage_only_count,
        "context_fallback_count": context_fallback_count,
        "extractive_definition_rejection_breakdown": dict(sorted(definition_rejection_counter.items())),
        "draft_status_breakdown": dict(sorted(draft_status_counter.items())),
        "trust_state_breakdown": dict(sorted(trust_state_counter.items())),
        "review_readiness_breakdown": dict(sorted(review_readiness_counter.items())),
        "context_layer_status_breakdown": dict(sorted(context_layer_status_counter.items())),
        "authoritative_definition_status_breakdown": dict(sorted(authoritative_definition_status_counter.items())),
        "support_state_breakdown": dict(sorted(support_state_counter.items())),
        "evidence_bundle_size_distribution": dict(sorted(evidence_bundle_size_distribution.items())),
        "contamination_flag_breakdown": dict(sorted(contamination_flag_counter.items())),
        "llm_runtime": dict(sorted(runtime_counters.items())),
    }
    return bundles, stats


def _ensure_kc_specific_criteria_placeholder(row: Dict[str, Any]) -> Dict[str, Any]:
    """Local guard for Step6.7 draft rows.

    The model does not author KC-specific criteria. The field is reserved for expert review.
    """
    try:
        return attach_kc_specific_criteria_placeholder(row)
    except NameError:
        out = dict(row)
        out.setdefault("kc_specific_criteria", [])
        out.setdefault("kc_specific_criteria_status", "expert_pending")
        out.setdefault("kc_specific_criteria_source", "deterministic_placeholder_not_model_authored")
        return out
