from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence


GENERIC_EVIDENCE_LANE_POLICY_VERSION = "step67_generic_evidence_lane_policy_v3_3_source_sense"

LANE_DEFINITION = "definition_lane"
LANE_SCOPE = "scope_lane"
LANE_CONTEXT = "context_lane"
LANE_SIBLING = "sibling_contrast_lane"
LANE_QUARANTINE = "quarantine_lane"


STOPWORDS = {
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
    "there",
    "these",
    "this",
    "those",
    "to",
    "with",
    "within",
}


# Internal source-sense matching stopwords.
# These are intentionally generic. They prevent broad curriculum words
# and generic object/type words from creating false hierarchy compatibility.
SENSE_STOPWORDS = STOPWORDS | {
    "about",
    "above",
    "after",
    "all",
    "also",
    "another",
    "approach",
    "basic",
    "case",
    "cases",
    "class",
    "classes",
    "component",
    "components",
    "concept",
    "concepts",
    "data",
    "definition",
    "definitions",
    "different",
    "example",
    "examples",
    "figure",
    "following",
    "general",
    "group",
    "groups",
    "index",
    "indices",
    "input",
    "inputs",
    "introduction",
    "item",
    "items",
    "kind",
    "kinds",
    "label",
    "labels",
    "method",
    "methods",
    "mining",
    "object",
    "objects",
    "output",
    "outputs",
    "overview",
    "point",
    "points",
    "process",
    "quality",
    "rule",
    "rules",
    "score",
    "scores",
    "section",
    "set",
    "sets",
    "system",
    "systems",
    "table",
    "tables",
    "technique",
    "techniques",
    "type",
    "types",
    "value",
    "values",
}

# Generic type words used only for heading-level surface-family checks.
# Example: target "Boundary Object" can match heading "Boundary and Interior Objects".
# These words are intentionally domain-neutral.
SENSE_GENERIC_TYPE_TOKENS = {
    "algorithm",
    "approach",
    "attribute",
    "case",
    "category",
    "class",
    "component",
    "concept",
    "criterion",
    "element",
    "entity",
    "factor",
    "field",
    "function",
    "group",
    "index",
    "indicator",
    "instance",
    "item",
    "label",
    "measure",
    "method",
    "metric",
    "model",
    "node",
    "object",
    "operation",
    "parameter",
    "point",
    "procedure",
    "process",
    "property",
    "record",
    "rule",
    "score",
    "set",
    "step",
    "table",
    "term",
    "type",
    "value",
    "variable",
}


FRAGMENT_TAIL_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "if",
    "in",
    "into",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
    "within",
}

SHORT_TARGET_TOKEN_MAX = 3

INCOMPLETE_ENDING_PATTERNS = (
    r"\b(?:in|for|with|using)\s+(?:a|an)\s+(?:given|greedy|particular|specific|single|certain)\b$",
    r"\baccording to the\b$",
)


def _normalize_ws(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _normalize_text(text: Any) -> str:
    cleaned = _normalize_ws(text).lower()
    cleaned = cleaned.replace("\u2010", "-").replace("\u2011", "-")
    cleaned = cleaned.replace("\u2012", "-").replace("\u2013", "-")
    cleaned = cleaned.replace("\u2014", "-").replace("\u2212", "-")
    cleaned = re.sub(r"[^a-z0-9()=/+\-]+", " ", cleaned)
    cleaned = cleaned.replace("-", " ")
    return re.sub(r"\s+", " ", cleaned).strip()


def _tokenize(text: Any) -> list[str]:
    return re.findall(r"[a-z0-9]+", _normalize_text(text))


def _contains_phrase(text_norm: str, phrase_norm: str) -> bool:
    if not text_norm or not phrase_norm:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(phrase_norm)}(?![a-z0-9])", text_norm) is not None


def _starts_with_normalized_phrase(text_norm: str, phrase_norm: str) -> bool:
    if not text_norm or not phrase_norm:
        return False
    return text_norm == phrase_norm or text_norm.startswith(phrase_norm + " ")


def _has_complete_definition_predication(text_norm: str) -> bool:
    if not text_norm:
        return False
    return re.search(
        r"\b(?:is|are|was|were)\s+(?:"
        r"defined\s+as|"
        r"given\s+by|"
        r"computed\s+as|"
        r"calculated\s+as|"
        r"defined\s+by\s+the\s+following\s+equation|"
        r"given\s+by\s+the\s+following\s+equation"
        r")\b",
        text_norm,
    ) is not None


def _unique_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        item = str(value or "")
        if not item or item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _strip_parenthetical(text: str) -> str:
    return _normalize_ws(re.sub(r"\([^)]*\)", " ", text or ""))


def _singularize_token(token: str) -> str:
    if len(token) <= 3:
        return token
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("ses") and len(token) > 4:
        return token[:-2]
    if token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _phrase_lexical_variants(text: str) -> list[str]:
    base = _normalize_ws(text)
    if not base:
        return []
    variants = [base]
    stripped = _strip_parenthetical(base)
    if stripped and stripped != base:
        variants.append(stripped)
    for match in re.findall(r"\(([^)]*)\)", base):
        item = _normalize_ws(match)
        if item:
            variants.append(item)
    for part in re.split(r"/", base):
        item = _normalize_ws(part)
        if item and item != base:
            variants.append(item)
    singular_parts = [_singularize_token(token) for token in _tokenize(base)]
    singular_phrase = _normalize_ws(" ".join(singular_parts))
    if singular_phrase and singular_phrase != base:
        variants.append(singular_phrase)
    return _unique_preserve_order(variants)


def _abbreviations(values: Sequence[str]) -> list[str]:
    found: list[str] = []
    for value in values:
        for match in re.findall(r"\b[A-Z][A-Z0-9]{1,9}\b", str(value or "")):
            found.append(match.lower())
    return _unique_preserve_order(found)


def _subject_terms(values: Sequence[str]) -> list[str]:
    terms: list[str] = []
    for value in values:
        for token in _tokenize(value):
            singular = _singularize_token(token)
            if len(singular) >= 3 and singular not in STOPWORDS:
                terms.append(singular)
    return _unique_preserve_order(terms)


def _topic_terms(topic_path_labels: Sequence[str], blocked_terms: Sequence[str]) -> list[str]:
    blocked = {str(term) for term in blocked_terms}
    terms: list[str] = []
    for label in topic_path_labels:
        for token in _tokenize(label):
            singular = _singularize_token(token)
            if len(singular) >= 3 and singular not in STOPWORDS and singular not in blocked:
                terms.append(singular)
    return _unique_preserve_order(terms)


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    overlay_candidate_id: str
    quote_text: str
    context_text: str
    provenance: dict[str, Any] = field(default_factory=dict)
    support_profile: dict[str, Any] = field(default_factory=dict)
    role_hint: dict[str, Any] = field(default_factory=dict)
    retrieval_scores: dict[str, Any] = field(default_factory=dict)
    contamination_risk: str = ""
    contamination_signals: tuple[str, ...] = ()
    role_hints: tuple[str, ...] = ()
    risk_hints: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "EvidenceItem":
        support_profile = value.get("support_profile")
        role_hint = value.get("role_hint")
        retrieval_scores = value.get("retrieval_scores")
        provenance = value.get("provenance")
        return cls(
            evidence_id=str(value.get("evidence_id") or value.get("id") or ""),
            overlay_candidate_id=str(value.get("overlay_candidate_id") or ""),
            quote_text=str(value.get("quote_text") or value.get("quote") or value.get("text") or ""),
            context_text=str(
                value.get("context_text")
                or value.get("source_block_text")
                or value.get("candidate_text")
                or value.get("quote_text")
                or value.get("text")
                or ""
            ),
            provenance=dict(provenance) if isinstance(provenance, dict) else {},
            support_profile=dict(support_profile) if isinstance(support_profile, dict) else {},
            role_hint=dict(role_hint) if isinstance(role_hint, dict) else {},
            retrieval_scores=dict(retrieval_scores) if isinstance(retrieval_scores, dict) else {},
            contamination_risk=str(value.get("contamination_risk") or ""),
            contamination_signals=tuple(
                str(item) for item in (value.get("contamination_signals") or []) if str(item)
            ),
            role_hints=tuple(str(item) for item in (value.get("role_hints") or []) if str(item)),
            risk_hints=tuple(str(item) for item in (value.get("risk_hints") or []) if str(item)),
            metadata=dict(value),
        )


@dataclass(frozen=True)
class KCProfile:
    kc_id: str
    canonical_name: str
    aliases: tuple[str, ...]
    topic_path_labels: tuple[str, ...]
    target_phrases: tuple[str, ...]
    abbreviations: tuple[str, ...]
    subject_terms: tuple[str, ...]
    topic_terms: tuple[str, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "KCProfile":
        canonical_name = _normalize_ws(value.get("canonical_name") or "")
        aliases = tuple(
            _unique_preserve_order(
                _normalize_ws(item) for item in (value.get("aliases") or []) if _normalize_ws(item)
            )
        )
        topic_path_labels = tuple(
            _unique_preserve_order(
                _normalize_ws(item)
                for item in (
                    value.get("topic_path_labels")
                    or value.get("source_hierarchy_path")
                    or value.get("ancestor_labels")
                    or []
                )
                if _normalize_ws(item)
            )
        )

        phrase_sources = [canonical_name, *aliases]
        target_phrases = tuple(
            _unique_preserve_order(
                _normalize_text(item)
                for source in phrase_sources
                for item in _phrase_lexical_variants(source)
                if len(_tokenize(item)) >= 2 or len(_normalize_text(item)) >= 2
            )
        )
        abbreviations = tuple(_abbreviations([canonical_name, *aliases]))
        subject_terms = tuple(_subject_terms([canonical_name, *aliases]))
        topic_terms = tuple(_topic_terms(topic_path_labels, subject_terms))

        return cls(
            kc_id=str(value.get("kc_id") or ""),
            canonical_name=canonical_name,
            aliases=aliases,
            topic_path_labels=topic_path_labels,
            target_phrases=target_phrases,
            abbreviations=abbreviations,
            subject_terms=subject_terms,
            topic_terms=topic_terms,
        )


@dataclass(frozen=True)
class LaneDecision:
    evidence_id: str
    overlay_candidate_id: str
    primary_lane: str
    reason: str
    flags: tuple[str, ...]
    target_binding_strength: str
    quote_target_binding_strength: str
    context_target_binding_strength: str
    decisive_surface: str
    selection_score: float
    quote_binding_score: float
    context_binding_score: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "overlay_candidate_id": self.overlay_candidate_id,
            "primary_lane": self.primary_lane,
            "reason": self.reason,
            "flags": list(self.flags),
            "target_binding_strength": self.target_binding_strength,
            "quote_target_binding_strength": self.quote_target_binding_strength,
            "context_target_binding_strength": self.context_target_binding_strength,
            "decisive_surface": self.decisive_surface,
            "selection_score": round(float(self.selection_score), 6),
            "quote_binding_score": round(float(self.quote_binding_score), 6),
            "context_binding_score": round(float(self.context_binding_score), 6),
        }


@dataclass(frozen=True)
class EvidenceLanePolicy:
    version: str = GENERIC_EVIDENCE_LANE_POLICY_VERSION
    definition_lane_limit: int = 2
    scope_lane_limit: int = 3
    context_lane_limit: int = 3
    sibling_lane_limit: int = 2
    relation_cues: tuple[str, ...] = (
        "extension of",
        "extended",
        "generalization of",
        "special case of",
        "reduces to",
        "derived from",
        "equivalent to",
        "related to",
        "used to handle",
        "frequently used",
        "in contrast",
        "unlike",
    )
    use_cues: tuple[str, ...] = (
        "used for",
        "used to",
        "can be used",
        "often used",
        "commonly used",
        "frequently used",
        "most commonly used",
        "has a tendency to",
        "helps",
        "allows",
        "advantage",
        "limitation",
        "when",
        "if",
        "in the context of",
        "leads to",
        "results in",
    )
    contrast_cues: tuple[str, ...] = (
        "not a",
        "neither",
        "rather than",
        "but not",
        "unlike",
        "instead of",
        "as opposed to",
    )
    explicit_definition_cues: tuple[str, ...] = (
        "is defined as",
        "are defined as",
        "is given by",
        "are given by",
        "given by the following equation",
        "defined by the following equation",
        "is computed as",
        "are computed as",
        "computed as",
        "is calculated as",
        "are calculated as",
        "calculated as",
    )
    target_bound_definition_verbs: tuple[str, ...] = (
        "means",
        "refers to",
    )
    target_bound_naming_cues: tuple[str, ...] = (
        "called",
        "known as",
    )
    context_cues: tuple[str, ...] = (
        "for example",
        "for instance",
        "such as",
        "in practice",
        "for the example",
        "procedure",
        "algorithm",
        "step",
        "steps",
        "section",
        "figure",
    )
    prompt_starts: tuple[str, ...] = (
        "assume that",
        "show that",
        "prove that",
        "compute",
        "calculate",
        "derive",
        "find",
        "determine",
        "explain why",
    )
    fragment_starts: tuple[str, ...] = (
        ",",
        "and ",
        "or ",
        "where ",
        "with ",
        "for ",
        "because ",
    )


@dataclass(frozen=True)
class _BindingResult:
    score: float
    strength: str
    exact_phrase_hits: tuple[str, ...]
    abbreviation_hits: tuple[str, ...]
    subject_hits: tuple[str, ...]
    topic_hits: tuple[str, ...]


@dataclass(frozen=True)
class _DemotionResult:
    lane: str
    reason: str
    flag: str


@dataclass(frozen=True)
class _SourceSenseAssessment:
    status: str
    reason: str
    flags: tuple[str, ...]
    target_surface_tokens: tuple[str, ...]
    target_branch_tokens: tuple[str, ...]
    target_repeated_branch_tokens: tuple[str, ...]
    target_specific_branch_tokens: tuple[str, ...]
    source_heading_tokens: tuple[str, ...]
    source_context_tokens: tuple[str, ...]
    surface_overlap: tuple[str, ...]
    branch_overlap: tuple[str, ...]
    specific_branch_overlap: tuple[str, ...]
    heading_branch_overlap: tuple[str, ...]
    context_branch_overlap: tuple[str, ...]
    source_heading_text: str
    source_hierarchy_path_diagnostic: tuple[str, ...]


def _sense_token_variants(token: str) -> list[str]:
    token = _singularize_token(str(token or "").lower())
    if not token or len(token) < 3:
        return []

    variants = [token]

    # Conservative morphology only.
    # Do not create short unsafe stems such as mining -> min, based -> bas,
    # missing -> miss, or handling -> handl.
    if token.endswith("ing") and len(token) > 7:
        stem = token[:-3]
        if len(stem) >= 5 and not stem.endswith(("ss", "dl", "th", "nn", "rn")):
            variants.append(stem)

    return _unique_preserve_order(variants)


def _sense_tokens(values: Iterable[Any], *, extra_blocked: Iterable[str] = ()) -> set[str]:
    blocked = set(SENSE_STOPWORDS) | {str(item).lower() for item in extra_blocked if str(item)}
    out: list[str] = []
    for value in values:
        if isinstance(value, (list, tuple)):
            text = " ".join(str(item or "") for item in value)
        else:
            text = str(value or "")
        for raw_token in _tokenize(text):
            token = _singularize_token(str(raw_token or "").lower())
            if not token or token in blocked or raw_token.lower() in blocked:
                continue
            for variant in _sense_token_variants(token):
                if variant not in blocked:
                    out.append(variant)
    return set(_unique_preserve_order(out))


def _metadata_text(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return _normalize_ws(" ".join(str(item or "") for item in value))
    return _normalize_ws(value)


def _source_heading_text(item: EvidenceItem) -> str:
    fields = []
    for key in (
        "page_heading_norm",
        "patch_heading",
        "original_patch_heading",
        "original_page_heading_norm",
    ):
        value = item.metadata.get(key)
        if value:
            fields.append(_metadata_text(value))
    patch_heading = item.provenance.get("patch_heading")
    if patch_heading:
        fields.append(_metadata_text(patch_heading))
    return _normalize_ws(" ; ".join(_unique_preserve_order(x for x in fields if x)))


def _source_hierarchy_path_diagnostic(item: EvidenceItem) -> tuple[str, ...]:
    value = item.metadata.get("source_hierarchy_path")
    if isinstance(value, (list, tuple)):
        return tuple(_normalize_ws(v) for v in value if _normalize_ws(v))
    if isinstance(value, str) and value.strip():
        return tuple(part.strip() for part in re.split(r"[;>/|]+", value) if part.strip())
    return ()


def _raw_surface_tokens(values: Iterable[Any]) -> set[str]:
    out: list[str] = []
    for value in values:
        if isinstance(value, (list, tuple)):
            text = " ".join(str(item or "") for item in value)
        else:
            text = str(value or "")
        for raw_token in _tokenize(text):
            token = _singularize_token(str(raw_token or "").lower())
            if token and len(token) >= 3:
                out.append(token)
    return set(_unique_preserve_order(out))


def _heading_surface_family_match(source_heading: str, profile: KCProfile) -> bool:
    """Return True when the source heading itself names the same target family.

    This catches generic cases like:
    target = "Boundary Object"
    heading = "Boundary and Interior Objects"

    It intentionally requires the heading, not the full context, because context
    can contain same-surface wrong-sense terms.
    """

    heading_tokens = _raw_surface_tokens([source_heading])
    if not heading_tokens:
        return False

    target_raw = _raw_surface_tokens([profile.canonical_name, *profile.aliases])
    if not target_raw:
        return False

    target_type_tokens = target_raw & SENSE_GENERIC_TYPE_TOKENS
    target_content_tokens = {
        token
        for token in target_raw
        if token not in SENSE_GENERIC_TYPE_TOKENS and token not in SENSE_STOPWORDS
    }

    if not target_content_tokens:
        return False

    if target_type_tokens:
        return bool(target_content_tokens & heading_tokens) and bool(target_type_tokens & heading_tokens)

    # For targets without a generic type word, require all target content
    # tokens to appear in the source heading. This is conservative.
    return target_content_tokens <= heading_tokens


def _branch_token_profile(profile: KCProfile, target_surface_tokens: set[str]) -> tuple[set[str], set[str]]:
    """Return repeated branch tokens and more specific branch tokens.

    Repeated tokens across hierarchy labels are usually broad branch labels.
    More specific tokens come from the deepest non-target hierarchy label and
    are safer evidence of same-sense compatibility.
    """

    labels = [_metadata_text(label) for label in profile.topic_path_labels if _metadata_text(label)]

    if len(labels) > 1:
        branch_labels = labels[:-1]
    else:
        branch_labels = labels

    label_token_sets = [
        _sense_tokens([label], extra_blocked=target_surface_tokens)
        for label in branch_labels
    ]
    label_token_sets = [tokens for tokens in label_token_sets if tokens]

    token_counts: dict[str, int] = {}
    for token_set in label_token_sets:
        for token in token_set:
            token_counts[token] = token_counts.get(token, 0) + 1

    repeated_tokens = {token for token, count in token_counts.items() if count >= 2}

    deepest_tokens = label_token_sets[-1] if label_token_sets else set()
    specific_tokens = deepest_tokens - repeated_tokens - set(target_surface_tokens)

    if not specific_tokens:
        all_tokens = set().union(*label_token_sets) if label_token_sets else set()
        specific_tokens = all_tokens - repeated_tokens - set(target_surface_tokens)

    return repeated_tokens, specific_tokens


def _source_sense_assessment(
    item: EvidenceItem,
    profile: KCProfile,
    *,
    quote_binding: _BindingResult,
    context_binding: _BindingResult,
) -> _SourceSenseAssessment:
    """Assess whether a candidate's source context fits the KC hierarchy sense.

    This is not a final semantic judge. It is a conservative gate to prevent
    same-surface, wrong-sense evidence from entering synthesis lanes.
    """

    target_surface_tokens = _sense_tokens([profile.canonical_name, *profile.aliases])
    target_branch_tokens = _sense_tokens(profile.topic_path_labels, extra_blocked=target_surface_tokens)
    target_repeated_branch_tokens, target_specific_branch_tokens = _branch_token_profile(
        profile,
        target_surface_tokens,
    )

    source_heading = _source_heading_text(item)
    source_hierarchy_diag = _source_hierarchy_path_diagnostic(item)

    source_heading_tokens = _sense_tokens([source_heading])
    source_context_tokens = _sense_tokens([item.quote_text, item.context_text])

    surface_overlap = target_surface_tokens & source_context_tokens
    heading_branch_overlap = target_branch_tokens & source_heading_tokens
    context_branch_overlap = target_branch_tokens & source_context_tokens
    branch_overlap = heading_branch_overlap | context_branch_overlap
    specific_branch_overlap = target_specific_branch_tokens & (source_heading_tokens | source_context_tokens)

    heading_meaning_tokens = source_heading_tokens - target_surface_tokens
    has_heading_context = bool(heading_meaning_tokens)
    heading_surface_family_match = _heading_surface_family_match(source_heading, profile)

    strong_surface_anchor = bool(
        quote_binding.exact_phrase_hits
        or quote_binding.abbreviation_hits
        or context_binding.exact_phrase_hits
        or context_binding.abbreviation_hits
    )

    broad_branch_only = bool(branch_overlap) and not specific_branch_overlap and not heading_surface_family_match

    flags: list[str] = []
    status = "not_applicable"
    reason = "no hierarchy branch signal available"

    if not target_branch_tokens and not heading_surface_family_match:
        status = "not_applicable"
        reason = "target hierarchy branch has no usable non-surface tokens"
    elif specific_branch_overlap:
        status = "same_sense_positive"
        reason = "source heading or context overlaps specific target hierarchy branch"
        flags.append("source_sense_positive")
    elif heading_surface_family_match:
        status = "same_sense_positive"
        reason = "source heading contains target surface-family pattern"
        flags.append("source_sense_positive")
        flags.append("source_sense_heading_surface_family")
    elif broad_branch_only and strong_surface_anchor:
        status = "same_sense_positive"
        reason = "source has broad branch overlap plus exact target surface anchor"
        flags.append("source_sense_positive")
        flags.append("source_sense_broad_branch_only")
    elif broad_branch_only and surface_overlap and has_heading_context:
        status = "cross_sense_risk"
        reason = "surface target match has only broad branch overlap and source heading indicates another local context"
        flags.append("source_sense_surface_only")
        flags.append("source_sense_broad_branch_only")
        flags.append("source_sense_heading_mismatch")
    elif branch_overlap:
        status = "weak_sense"
        reason = "source has only broad target-branch overlap"
        flags.append("source_sense_broad_branch_only")
        flags.append("source_sense_weak")
    elif surface_overlap and has_heading_context:
        status = "cross_sense_risk"
        reason = "surface target match lacks target-branch support and source heading indicates another local context"
        flags.append("source_sense_surface_only")
        flags.append("source_sense_heading_mismatch")
    elif surface_overlap:
        status = "weak_sense"
        reason = "surface target match lacks target-branch support"
        flags.append("source_sense_weak")
    else:
        status = "no_surface_or_branch_support"
        reason = "source lacks usable surface or target-branch support"
        flags.append("source_sense_no_support")

    if source_hierarchy_diag:
        flags.append("source_hierarchy_path_diagnostic_only")

    return _SourceSenseAssessment(
        status=status,
        reason=reason,
        flags=tuple(_unique_preserve_order(flags)),
        target_surface_tokens=tuple(sorted(target_surface_tokens)),
        target_branch_tokens=tuple(sorted(target_branch_tokens)),
        target_repeated_branch_tokens=tuple(sorted(target_repeated_branch_tokens)),
        target_specific_branch_tokens=tuple(sorted(target_specific_branch_tokens)),
        source_heading_tokens=tuple(sorted(source_heading_tokens)),
        source_context_tokens=tuple(sorted(source_context_tokens)),
        surface_overlap=tuple(sorted(surface_overlap)),
        branch_overlap=tuple(sorted(branch_overlap)),
        specific_branch_overlap=tuple(sorted(specific_branch_overlap)),
        heading_branch_overlap=tuple(sorted(heading_branch_overlap)),
        context_branch_overlap=tuple(sorted(context_branch_overlap)),
        source_heading_text=source_heading,
        source_hierarchy_path_diagnostic=source_hierarchy_diag,
    )


def _first_text(mapping: Mapping[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _overlay_index(overlay_rows: Mapping[str, Mapping[str, Any]] | Sequence[Mapping[str, Any]] | None) -> dict[str, dict[str, Any]]:
    if overlay_rows is None:
        return {}
    if isinstance(overlay_rows, Mapping):
        indexed: dict[str, dict[str, Any]] = {}
        for key, value in overlay_rows.items():
            if not isinstance(value, Mapping):
                continue
            indexed[str(key)] = dict(value)
        return indexed
    indexed = {}
    for row in overlay_rows:
        if not isinstance(row, Mapping):
            continue
        overlay_candidate_id = str(row.get("overlay_candidate_id") or "")
        if overlay_candidate_id:
            indexed[overlay_candidate_id] = dict(row)
    return indexed


def _materialize_item(
    evidence_row: Mapping[str, Any],
    overlay_row: Mapping[str, Any] | None,
    *,
    fallback_evidence_id: str,
) -> EvidenceItem:
    overlay = dict(overlay_row) if isinstance(overlay_row, Mapping) else {}
    merged: dict[str, Any] = dict(evidence_row)

    merged.setdefault("evidence_id", fallback_evidence_id)
    merged.setdefault("overlay_candidate_id", str(evidence_row.get("overlay_candidate_id") or overlay.get("overlay_candidate_id") or ""))

    quote_text = _first_text(
        merged,
        ("quote_text", "quote", "quote_surface", "candidate_text", "text"),
    ) or _first_text(
        overlay,
        ("quote_surface", "original_quote_surface", "text", "sentence_text"),
    )
    context_text = _first_text(
        overlay,
        ("source_block_text", "source_block_text_raw", "original_source_block_text"),
    ) or _first_text(
        merged,
        ("context_text", "source_block_text", "candidate_text", "quote_text", "text"),
    ) or quote_text

    merged["quote_text"] = quote_text
    merged["context_text"] = context_text

    provenance = dict(merged.get("provenance") or {})
    if not provenance:
        provenance = {
            "doc_id": overlay.get("doc_id") or "",
            "page_index": overlay.get("page_index"),
            "block_id": overlay.get("block_id") or "",
            "sentence_id": overlay.get("sentence_id") or "",
            "patch_id": overlay.get("patch_id") or "",
            "patch_heading": overlay.get("patch_heading") or "",
            "layer": overlay.get("layer") or "",
        }
    merged["provenance"] = provenance

    for key in (
        "support_profile",
        "role_hint",
        "retrieval_scores",
        "contamination_risk",
        "contamination_signals",
        "role_hints",
        "risk_hints",
    ):
        if key not in merged and key in overlay:
            merged[key] = overlay[key]

    # Preserve source surfaces for source-sense compatibility checks.
    # These are internal evidence metadata, not final KC schema fields.
    for key in (
        "page_heading_norm",
        "patch_heading",
        "original_patch_heading",
        "original_page_heading_norm",
        "source_hierarchy_path",
        "ancestor_labels",
        "source_block_text",
        "source_block_text_raw",
        "original_source_block_text",
        "strong_same_topic",
        "strong_structured_candidate",
        "alignment_score",
        "alignment_breakdown",
        "evidence_pack_membership",
        "evidence_pack_slots",
        "source_candidate_index",
    ):
        if key not in merged and key in overlay:
            merged[key] = overlay[key]

    return EvidenceItem.from_mapping(merged)


def _target_binding(text: str, profile: KCProfile) -> _BindingResult:
    text_norm = _normalize_text(text)
    text_tokens = {_singularize_token(token) for token in _tokenize(text_norm)}
    exact_phrase_hits = [phrase for phrase in profile.target_phrases if _contains_phrase(text_norm, phrase)]
    abbreviation_hits = [abbr for abbr in profile.abbreviations if _contains_phrase(text_norm, abbr)]
    subject_hits = [term for term in profile.subject_terms if term in text_tokens]
    topic_hits = [term for term in profile.topic_terms if term in text_tokens]

    score = 0.0
    score += 4.0 * float(len(exact_phrase_hits))
    score += 3.5 * float(len(abbreviation_hits))
    if len(subject_hits) >= 2:
        score += 2.5
    elif len(subject_hits) == 1:
        score += 1.1
    score += min(1.2, 0.35 * float(len(topic_hits)))
    if subject_hits and topic_hits:
        score += 0.4

    strength = "none"
    if exact_phrase_hits or abbreviation_hits or len(subject_hits) >= 2 or score >= 4.0:
        strength = "strong"
    elif score >= 2.0:
        strength = "moderate"
    elif score > 0.0:
        strength = "weak"

    return _BindingResult(
        score=round(score, 6),
        strength=strength,
        exact_phrase_hits=tuple(exact_phrase_hits),
        abbreviation_hits=tuple(abbreviation_hits),
        subject_hits=tuple(subject_hits),
        topic_hits=tuple(topic_hits),
    )


def _contains_any(text_norm: str, cues: Sequence[str]) -> bool:
    return any(_contains_phrase(text_norm, _normalize_text(cue)) for cue in cues)


def _word_boundary_pattern(phrase_norm: str) -> str:
    return rf"(?<![a-z0-9]){re.escape(phrase_norm)}(?![a-z0-9])"


def _has_unmatched_brackets(text: str) -> bool:
    pairs = {"(": ")", "[": "]", "{": "}"}
    closing = {value: key for key, value in pairs.items()}
    stack: list[str] = []
    for char in str(text or ""):
        if char in pairs:
            stack.append(char)
        elif char in closing:
            if not stack or stack[-1] != closing[char]:
                return True
            stack.pop()
    return bool(stack)


def _formula_like(text: str) -> bool:
    raw = str(text or "")
    if not raw:
        return False
    if "$" in raw or "\\begin" in raw or "\\sum" in raw:
        return True
    symbol_count = len(re.findall(r"[=<>_^{}+/]", raw))
    return symbol_count >= 4 and symbol_count >= max(3, len(_tokenize(raw)) // 5)


def _prompt_like_quote(quote_text: str, policy: EvidenceLanePolicy) -> bool:
    raw = _normalize_ws(quote_text)
    text_norm = _normalize_text(raw)
    if not text_norm:
        return False
    if "?" in raw:
        return True
    return any(text_norm.startswith(_normalize_text(prefix)) for prefix in policy.prompt_starts)


def _fragmentary_quote(quote_text: str, policy: EvidenceLanePolicy) -> bool:
    raw = _normalize_ws(quote_text)
    if not raw:
        return True
    token_list = _tokenize(raw)
    text_norm = _normalize_text(raw)
    if len(token_list) <= 5:
        return True
    fragment_prefixes = [
        _normalize_text(prefix)
        for prefix in policy.fragment_starts
        if _normalize_text(prefix)
    ]
    for prefix in fragment_prefixes:
        if not _starts_with_normalized_phrase(text_norm, prefix):
            continue
        # A complete target-bound definition may legitimately start with a
        # lead-in such as "For the X version ...". Do not quarantine it only
        # because it starts with "for".
        if (
            prefix == "for"
            and len(token_list) > 10
            and _has_complete_definition_predication(text_norm)
        ):
            continue
        return True
    if _has_unmatched_brackets(raw):
        return True
    if (
        len(token_list) >= 2
        and token_list[0].endswith("ed")
        and token_list[1] in {"in", "by", "for", "with", "as", "from"}
    ):
        return True
    if token_list and token_list[-1] in FRAGMENT_TAIL_WORDS:
        return True
    if any(re.search(pattern, text_norm) is not None for pattern in INCOMPLETE_ENDING_PATTERNS):
        return True
    return False


def _is_short_target_variant(phrase_norm: str) -> bool:
    token_list = _tokenize(phrase_norm)
    return len(token_list) == 1 and len(token_list[0]) <= SHORT_TARGET_TOKEN_MAX


def _definition_anchor_variants(binding: _BindingResult) -> tuple[str, ...]:
    exact_hits = list(binding.exact_phrase_hits)
    abbreviation_hits = list(binding.abbreviation_hits)
    long_hits = [
        hit
        for hit in [*exact_hits, *abbreviation_hits]
        if not _is_short_target_variant(hit)
    ]
    short_hits = [
        hit
        for hit in [*exact_hits, *abbreviation_hits]
        if _is_short_target_variant(hit)
    ]

    variants = list(long_hits)
    if short_hits and (long_hits or len(binding.topic_hits) >= 2):
        variants.extend(short_hits)
    return tuple(_unique_preserve_order(variants))


def _has_short_definition_only_binding(binding: _BindingResult) -> bool:
    hits = [*binding.exact_phrase_hits, *binding.abbreviation_hits]
    return bool(hits) and not _definition_anchor_variants(binding) and any(
        _is_short_target_variant(hit) for hit in hits
    )


def _strict_definition_binding_strength(binding: _BindingResult) -> str:
    variants = _definition_anchor_variants(binding)
    if variants:
        return "strong"
    if binding.exact_phrase_hits or binding.abbreviation_hits:
        return "weak"
    return "none"


def _subject_target_pattern(phrase_norm: str) -> str:
    return rf"^(?:(?:the|a|an)\s+)?{_word_boundary_pattern(phrase_norm)}(?:\s+[a-z0-9()]+){{0,2}}\s+"


def _quote_has_definition_subject_prefix(quote_norm: str, binding: _BindingResult) -> bool:
    for phrase in _definition_anchor_variants(binding):
        if re.search(_subject_target_pattern(phrase), quote_norm) is not None:
            return True
    return False


def _target_bound_formula_clause(
    quote_norm: str,
    binding: _BindingResult,
    policy: EvidenceLanePolicy,
) -> bool:
    if not quote_norm:
        return False
    for phrase in _definition_anchor_variants(binding):
        pattern = _subject_target_pattern(phrase)
        if re.search(pattern + r"(?:is|are)\s+defined as\b", quote_norm) is not None:
            return True
        if re.search(pattern + r"(?:is|are)\s+given by\b", quote_norm) is not None:
            return True
        if re.search(pattern + r"(?:is|are)\s+computed as\b", quote_norm) is not None:
            return True
        if re.search(pattern + r"(?:is|are)\s+calculated as\b", quote_norm) is not None:
            return True
        if re.search(
            pattern + r"(?:is|are)\s+defined by the following equation\b",
            quote_norm,
        ) is not None:
            return True
        if re.search(
            pattern + r"(?:is|are)\s+given by the following equation\b",
            quote_norm,
        ) is not None:
            return True
        if re.search(
            rf"^for\b"
            rf"(?=[a-z0-9()=/+\-\s]{{0,220}}{_word_boundary_pattern(phrase)})"
            rf"(?=[a-z0-9()=/+\-\s]{{0,280}}\b(?:is|are)\s+"
            rf"(?:defined as|given by|computed as|calculated as)\b)",
            quote_norm,
        ) is not None:
            return True
    return _formula_like(quote_norm) and _contains_any(quote_norm, policy.explicit_definition_cues)


def _named_target_trailer_pattern() -> str:
    return r"(?=$|\s+(?:because|when|where|which|that|who|whose|for|if|with|as|while|after|before|during)\b)"


def _explicit_definition_clause(
    quote_norm: str,
    binding: _BindingResult,
    policy: EvidenceLanePolicy,
) -> bool:
    if not quote_norm:
        return False
    for phrase in _definition_anchor_variants(binding):
        pattern = _subject_target_pattern(phrase)
        if re.search(pattern + r"means\b", quote_norm) is not None:
            return True
        if re.search(pattern + r"refers to\b", quote_norm) is not None:
            return True
        if re.search(
            rf"\bcalled\s+(?:(?:a|an|the)\s+)?{_word_boundary_pattern(phrase)}{_named_target_trailer_pattern()}",
            quote_norm,
        ) is not None:
            return True
        if re.search(
            rf"\bknown as\s+(?:(?:a|an|the)\s+)?{_word_boundary_pattern(phrase)}{_named_target_trailer_pattern()}",
            quote_norm,
        ) is not None:
            return True
    return False


def _subject_copula_definition(
    quote_norm: str,
    binding: _BindingResult,
    policy: EvidenceLanePolicy,
) -> bool:
    if not quote_norm or not _quote_has_definition_subject_prefix(quote_norm, binding):
        return False
    if _contains_any(quote_norm, policy.relation_cues):
        return False
    if _contains_any(quote_norm, policy.use_cues):
        return False
    if _contains_any(quote_norm, policy.contrast_cues):
        return False
    for phrase in _definition_anchor_variants(binding):
        if re.search(
            _subject_target_pattern(phrase) + r"(?:is|are)\s+(?:a|an|the|one|any|each)\b",
            quote_norm,
        ) is not None:
            return True
    return False


def _formula_definition_clause(
    quote_norm: str,
    binding: _BindingResult,
    policy: EvidenceLanePolicy,
) -> bool:
    if not quote_norm:
        return False
    if _strict_definition_binding_strength(binding) == "none":
        return False
    return _target_bound_formula_clause(quote_norm, binding, policy)


def _predefinition_demotion(
    quote_norm: str,
    binding: _BindingResult,
) -> _DemotionResult | None:
    for phrase in _unique_preserve_order([*binding.exact_phrase_hits, *binding.abbreviation_hits]):
        target_pattern = _word_boundary_pattern(phrase)
        article_prefix = rf"(?:(?:the|a|an)\s+)?{target_pattern}"

        if re.search(rf"^using\s+{article_prefix}\s+to\b", quote_norm) is not None:
            return _DemotionResult(
                lane=LANE_SCOPE,
                reason="usage-style lead-in is scoped, not definitional",
                flag="usage_leadin",
            )
        if re.search(
            rf"^steps?\s+[a-z0-9,\s-]+\s+of\s+{article_prefix}(?!\s+(?:is|are)\s+(?:a|an|the)\b)",
            quote_norm,
        ) is not None:
            return _DemotionResult(
                lane=LANE_CONTEXT,
                reason="procedural step evidence is contextual, not definitional",
                flag="procedural_step",
            )
        if re.search(rf"^{article_prefix}\s+(?:is|are)\s+then\s+applied\b", quote_norm) is not None:
            return _DemotionResult(
                lane=LANE_CONTEXT,
                reason="procedural application evidence is contextual, not definitional",
                flag="procedural_application",
            )
        if re.search(rf"^{article_prefix}\s+directly\s+attempts\s+to\b", quote_norm) is not None:
            return _DemotionResult(
                lane=LANE_CONTEXT,
                reason="optimization or action evidence is contextual, not definitional",
                flag="procedural_action",
            )
        if re.search(
            rf"^{article_prefix}(?:\s+[a-z0-9()]+){{0,2}}\s+(?:is|are)\s+(?:often|commonly|frequently)\s+used\b",
            quote_norm,
        ) is not None:
            return _DemotionResult(
                lane=LANE_SCOPE,
                reason="common usage evidence is scoped, not definitional",
                flag="common_usage",
            )
        if re.search(
            rf"^{article_prefix}(?:\s+[a-z0-9()]+){{0,2}}\s+(?:is|are)\s+the\s+most\s+commonly\s+used\b",
            quote_norm,
        ) is not None:
            return _DemotionResult(
                lane=LANE_SCOPE,
                reason="common usage evidence is scoped, not definitional",
                flag="common_usage",
            )
        if re.search(rf"^{article_prefix}\s+can\s+be\s+used\b", quote_norm) is not None:
            return _DemotionResult(
                lane=LANE_SCOPE,
                reason="capability evidence is scoped, not definitional",
                flag="capability_usage",
            )
        if re.search(rf"^{article_prefix}\s+has\s+a\s+tendency\s+to\b", quote_norm) is not None:
            return _DemotionResult(
                lane=LANE_SCOPE,
                reason="property evidence is scoped, not definitional",
                flag="property_tendency",
            )
    return None


def _selection_score(
    *,
    quote_binding: _BindingResult,
    context_binding: _BindingResult,
    explicit_definition_quote: bool,
    subject_definition_quote: bool,
    relation_quote: bool,
    use_quote: bool,
    contrast_quote: bool,
    formula_definition_quote: bool,
    context_definition_only: bool,
    prompt_like_quote: bool,
    fragmentary_quote: bool,
    contamination_risk: str,
) -> float:
    score = (1.35 * quote_binding.score) + (0.45 * context_binding.score)
    if explicit_definition_quote:
        score += 3.5
    if formula_definition_quote:
        score += 2.0
    if subject_definition_quote:
        score += 1.5
    if use_quote:
        score += 1.25
    if relation_quote:
        score += 0.8
    if contrast_quote:
        score += 0.9
    if context_definition_only:
        score += 0.4
    if prompt_like_quote:
        score -= 5.0
    if fragmentary_quote:
        score -= 4.0
    if contamination_risk.lower() == "high":
        score -= 2.0
    return round(score, 6)


def classify_evidence_item(
    item: Mapping[str, Any] | EvidenceItem,
    profile: Mapping[str, Any] | KCProfile,
    policy: EvidenceLanePolicy | None = None,
) -> dict[str, Any]:
    active_policy = policy or EvidenceLanePolicy()
    evidence_item = item if isinstance(item, EvidenceItem) else EvidenceItem.from_mapping(item)
    kc_profile = profile if isinstance(profile, KCProfile) else KCProfile.from_mapping(profile)

    quote_text = _normalize_ws(evidence_item.quote_text)
    context_text = _normalize_ws(evidence_item.context_text)
    quote_norm = _normalize_text(quote_text)
    context_norm = _normalize_text(context_text)

    quote_binding = _target_binding(quote_text, kc_profile)
    context_binding = _target_binding(context_text, kc_profile)
    quote_definition_binding_strength = _strict_definition_binding_strength(quote_binding)
    context_definition_binding_strength = _strict_definition_binding_strength(context_binding)

    explicit_definition_quote = _explicit_definition_clause(quote_norm, quote_binding, active_policy)
    formula_definition_quote = _formula_definition_clause(quote_norm, quote_binding, active_policy)
    subject_definition_quote = (
        _subject_copula_definition(quote_norm, quote_binding, active_policy)
        and not _formula_like(quote_text)
    )

    relation_quote = _contains_any(quote_norm, active_policy.relation_cues)
    use_quote = _contains_any(quote_norm, active_policy.use_cues)
    contrast_quote = _contains_any(quote_norm, active_policy.contrast_cues)
    context_cue_quote = _contains_any(quote_norm, active_policy.context_cues)
    prompt_like_quote = _prompt_like_quote(quote_text, active_policy)
    fragmentary_quote = _fragmentary_quote(quote_text, active_policy)
    unmatched_brackets = _has_unmatched_brackets(quote_text)
    predefinition_demotion = _predefinition_demotion(quote_norm, quote_binding)

    context_definition_only = (
        not explicit_definition_quote
        and not formula_definition_quote
        and not subject_definition_quote
        and (
            _explicit_definition_clause(context_norm, context_binding, active_policy)
            or _formula_definition_clause(context_norm, context_binding, active_policy)
            or _subject_copula_definition(context_norm, context_binding, active_policy)
        )
    )

    flags: list[str] = []
    if _formula_like(quote_text):
        flags.append("formula_like_quote")
    if _formula_like(context_text):
        flags.append("formula_like_context")
    if prompt_like_quote:
        flags.append("prompt_like_quote")
    if fragmentary_quote:
        flags.append("fragmentary_quote")
    if unmatched_brackets:
        flags.append("unmatched_brackets")
    if _has_short_definition_only_binding(quote_binding):
        flags.append("short_target_definition_protection")
    if relation_quote:
        flags.append("relation_cue")
    if use_quote:
        flags.append("scope_cue")
    if contrast_quote:
        flags.append("contrast_cue")
    if predefinition_demotion is not None:
        flags.append(predefinition_demotion.flag)
    if context_definition_only:
        flags.append("context_definition_leak")
    if evidence_item.contamination_risk.lower() == "high":
        flags.append("high_contamination_risk")
    if quote_binding.strength in {"none", "weak"}:
        flags.append("weak_quote_binding")
    if quote_binding.strength == "none" and context_binding.strength == "none":
        flags.append("no_target_anchor")

    selection_score = _selection_score(
        quote_binding=quote_binding,
        context_binding=context_binding,
        explicit_definition_quote=explicit_definition_quote,
        subject_definition_quote=subject_definition_quote,
        relation_quote=relation_quote,
        use_quote=use_quote,
        contrast_quote=contrast_quote,
        formula_definition_quote=formula_definition_quote,
        context_definition_only=context_definition_only,
        prompt_like_quote=prompt_like_quote,
        fragmentary_quote=fragmentary_quote,
        contamination_risk=evidence_item.contamination_risk,
    )

    primary_lane = LANE_QUARANTINE
    reason = "no sufficiently bound target evidence"
    decisive_surface = "quote_text" if quote_binding.score >= context_binding.score else "context_text"

    local_definition_quote = (
        quote_definition_binding_strength == "strong"
        and not relation_quote
        and not use_quote
        and not contrast_quote
        and not prompt_like_quote
        and not fragmentary_quote
        and not unmatched_brackets
        and predefinition_demotion is None
        and (
            explicit_definition_quote
            or formula_definition_quote
            or subject_definition_quote
        )
    )

    if prompt_like_quote or fragmentary_quote or unmatched_brackets:
        primary_lane = LANE_QUARANTINE
        reason = "fragmentary or prompt-like quote is quarantined"
        decisive_surface = "quote_text"
    elif contrast_quote and quote_binding.strength in {"strong", "moderate"}:
        primary_lane = LANE_SIBLING
        reason = "sibling or negative contrast is not positive evidence"
        decisive_surface = "quote_text"
    elif predefinition_demotion is not None and quote_binding.strength in {"strong", "moderate"}:
        primary_lane = predefinition_demotion.lane
        reason = predefinition_demotion.reason
        decisive_surface = "quote_text"
    elif local_definition_quote:
        primary_lane = LANE_DEFINITION
        if formula_definition_quote:
            reason = "quote-local target-bound formula definition clause"
        elif explicit_definition_quote:
            reason = "quote-local target-bound explicit definition clause"
        else:
            reason = "quote-local target-bound subject definition"
        decisive_surface = "quote_text"
    elif relation_quote and quote_binding.strength in {"strong", "moderate"}:
        primary_lane = LANE_CONTEXT
        reason = "relation or extension evidence is contextual"
        decisive_surface = "quote_text"
    elif use_quote and quote_binding.strength in {"strong", "moderate"}:
        primary_lane = LANE_SCOPE
        reason = "use or boundary evidence is scoped but not definitional"
        decisive_surface = "quote_text"
    elif context_definition_only and context_definition_binding_strength == "strong":
        if quote_binding.strength in {"strong", "moderate"} and (relation_quote or use_quote or context_cue_quote):
            primary_lane = LANE_SCOPE if use_quote else LANE_CONTEXT
            reason = "context contains a definition-like clause but the local quote does not"
        else:
            primary_lane = LANE_CONTEXT
            reason = "definition-like material appears only in surrounding context"
        decisive_surface = "context_text"
    elif quote_binding.strength in {"strong", "moderate"} and context_cue_quote:
        primary_lane = LANE_CONTEXT
        reason = "anchored contextual evidence"
        decisive_surface = "quote_text"
    elif quote_binding.strength in {"strong", "moderate"}:
        primary_lane = LANE_CONTEXT
        reason = "anchored evidence lacks a local definition clause"
        decisive_surface = "quote_text"
    elif context_binding.strength in {"strong", "moderate"}:
        primary_lane = LANE_CONTEXT
        reason = "target is bound only in surrounding context"
        decisive_surface = "context_text"

    source_sense = _source_sense_assessment(
        evidence_item,
        kc_profile,
        quote_binding=quote_binding,
        context_binding=context_binding,
    )
    flags.extend(source_sense.flags)

    if primary_lane in {LANE_DEFINITION, LANE_SCOPE, LANE_CONTEXT}:
        if source_sense.status == "cross_sense_risk":
            primary_lane = LANE_QUARANTINE
            reason = "source context appears cross-sense relative to target hierarchy"
            decisive_surface = "quote_text" if quote_binding.score >= context_binding.score else "context_text"
            selection_score = round(selection_score - 4.0, 6)
            flags.append("source_sense_demoted")
        elif source_sense.status == "weak_sense":
            flags.append("source_sense_review_required")

    overall_strength = quote_binding.strength
    if context_binding.score > quote_binding.score and context_binding.strength != "none":
        overall_strength = context_binding.strength

    decision = LaneDecision(
        evidence_id=evidence_item.evidence_id,
        overlay_candidate_id=evidence_item.overlay_candidate_id,
        primary_lane=primary_lane,
        reason=reason,
        flags=tuple(_unique_preserve_order(flags)),
        target_binding_strength=overall_strength,
        quote_target_binding_strength=quote_binding.strength,
        context_target_binding_strength=context_binding.strength,
        decisive_surface=decisive_surface,
        selection_score=selection_score,
        quote_binding_score=quote_binding.score,
        context_binding_score=context_binding.score,
    ).as_dict()

    decision.update(
        {
            "quote_text": quote_text,
            "context_text": context_text,
            "provenance": dict(evidence_item.provenance),
            "contamination_risk": evidence_item.contamination_risk,
            "contamination_signals": list(evidence_item.contamination_signals),
            "role_hints": list(evidence_item.role_hints),
            "risk_hints": list(evidence_item.risk_hints),
            "support_profile": dict(evidence_item.support_profile),
            "role_hint": dict(evidence_item.role_hint),
            "retrieval_scores": dict(evidence_item.retrieval_scores),
            "source_sense_status": source_sense.status,
            "source_sense_reason": source_sense.reason,
            "source_sense_flags": list(source_sense.flags),
            "source_sense_target_surface_tokens": list(source_sense.target_surface_tokens),
            "source_sense_target_branch_tokens": list(source_sense.target_branch_tokens),
            "source_sense_target_repeated_branch_tokens": list(source_sense.target_repeated_branch_tokens),
            "source_sense_target_specific_branch_tokens": list(source_sense.target_specific_branch_tokens),
            "source_sense_source_heading_tokens": list(source_sense.source_heading_tokens),
            "source_sense_surface_overlap": list(source_sense.surface_overlap),
            "source_sense_branch_overlap": list(source_sense.branch_overlap),
            "source_sense_specific_branch_overlap": list(source_sense.specific_branch_overlap),
            "source_sense_heading_branch_overlap": list(source_sense.heading_branch_overlap),
            "source_sense_context_branch_overlap": list(source_sense.context_branch_overlap),
            "source_heading_text": source_sense.source_heading_text,
            "source_hierarchy_path_diagnostic": list(source_sense.source_hierarchy_path_diagnostic),
        }
    )
    return decision


def _sorted_lane_items(items: Sequence[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    ordered = sorted(
        items,
        key=lambda item: (
            -float(item.get("selection_score") or 0.0),
            -float(item.get("quote_binding_score") or 0.0),
            str(item.get("evidence_id") or ""),
        ),
    )
    return [dict(item) for item in ordered[: max(0, int(limit))]]


def build_lane_packet(
    packet: Mapping[str, Any],
    overlay_rows: Mapping[str, Mapping[str, Any]] | Sequence[Mapping[str, Any]] | None = None,
    policy: EvidenceLanePolicy | None = None,
) -> dict[str, Any]:
    active_policy = policy or EvidenceLanePolicy()
    profile = KCProfile.from_mapping(packet)
    overlay_by_id = _overlay_index(overlay_rows)

    classified_items: list[dict[str, Any]] = []
    for index, evidence_row in enumerate(packet.get("evidence") or [], start=1):
        if not isinstance(evidence_row, Mapping):
            continue
        overlay_candidate_id = str(evidence_row.get("overlay_candidate_id") or "")
        overlay_row = overlay_by_id.get(overlay_candidate_id) or {}
        materialized_item = _materialize_item(
            evidence_row,
            overlay_row,
            fallback_evidence_id=f"E{index}",
        )
        classified_items.append(classify_evidence_item(materialized_item, profile, policy=active_policy))

    definition_items = [item for item in classified_items if item.get("primary_lane") == LANE_DEFINITION]
    scope_items = [item for item in classified_items if item.get("primary_lane") == LANE_SCOPE]
    context_items = [item for item in classified_items if item.get("primary_lane") == LANE_CONTEXT]
    sibling_items = [item for item in classified_items if item.get("primary_lane") == LANE_SIBLING]
    quarantine_items = [item for item in classified_items if item.get("primary_lane") == LANE_QUARANTINE]

    lane_packet = {
        "lane_policy_version": active_policy.version,
        "kc_id": profile.kc_id,
        "canonical_name": profile.canonical_name,
        "aliases": list(profile.aliases),
        "topic_path_labels": list(profile.topic_path_labels),
        "query_text": str(packet.get("query_text") or ""),
        "packet_contract_version": str(packet.get("packet_contract_version") or ""),
        "packet_notes": list(packet.get("packet_notes") or []),
        "support_pack_summary": dict(packet.get("support_pack_summary") or {}),
        "review_queue_aux": dict(packet.get("review_queue_aux") or {}),
        "source_candidate_row_count_for_kc": packet.get("source_candidate_row_count_for_kc"),
        "source_packets_path": str(packet.get("source_packets_path") or ""),
        "source_overlay_path": str(packet.get("source_overlay_path") or ""),
        "all_items": classified_items,
        "definition_lane": _sorted_lane_items(
            definition_items,
            limit=active_policy.definition_lane_limit,
        ),
        "scope_lane": _sorted_lane_items(
            scope_items,
            limit=active_policy.scope_lane_limit,
        ),
        "context_lane": _sorted_lane_items(
            context_items,
            limit=active_policy.context_lane_limit,
        ),
        "sibling_contrast_lane": _sorted_lane_items(
            sibling_items,
            limit=active_policy.sibling_lane_limit,
        ),
        "sibling_lane": _sorted_lane_items(
            sibling_items,
            limit=active_policy.sibling_lane_limit,
        ),
        "quarantine_lane": _sorted_lane_items(
            quarantine_items,
            limit=len(quarantine_items),
        ),
    }
    lane_packet["summary"] = summarize_lane_packet(lane_packet)
    return lane_packet


def summarize_lane_packet(lane_packet: Mapping[str, Any]) -> dict[str, Any]:
    all_items = [item for item in (lane_packet.get("all_items") or []) if isinstance(item, Mapping)]
    lane_counter = Counter(str(item.get("primary_lane") or "") for item in all_items if str(item.get("primary_lane") or ""))
    flag_counter = Counter(
        str(flag)
        for item in all_items
        for flag in (item.get("flags") or [])
        if str(flag)
    )

    definition_count = len(lane_packet.get("definition_lane") or [])
    scope_count = len(lane_packet.get("scope_lane") or [])
    context_count = len(lane_packet.get("context_lane") or [])
    sibling_count = len(lane_packet.get("sibling_contrast_lane") or [])
    quarantine_count = len(lane_packet.get("quarantine_lane") or [])

    return {
        "all_item_count": len(all_items),
        "all_item_lane_counts": dict(lane_counter),
        "selected_lane_counts": {
            LANE_DEFINITION: definition_count,
            LANE_SCOPE: scope_count,
            LANE_CONTEXT: context_count,
            LANE_SIBLING: sibling_count,
            LANE_QUARANTINE: quarantine_count,
        },
        "flag_counter": dict(flag_counter),
        "lane_pattern": f"d{definition_count}_s{scope_count}_c{context_count}_x{sibling_count}_q{quarantine_count}",
    }


def summarize_lane_packets(lane_packets: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    lane_counter_all_items: Counter[str] = Counter()
    selected_counter: Counter[str] = Counter()
    flag_counter: Counter[str] = Counter()

    for lane_packet in lane_packets:
        summary = summarize_lane_packet(lane_packet)
        lane_counter_all_items.update(dict(summary.get("all_item_lane_counts") or {}))
        selected_counter.update(dict(summary.get("selected_lane_counts") or {}))
        flag_counter.update(dict(summary.get("flag_counter") or {}))

    return {
        "packet_count": len(lane_packets),
        "lane_counter_all_items": dict(lane_counter_all_items),
        "selected_counter": dict(selected_counter),
        "flag_counter": dict(flag_counter),
    }


__all__ = [
    "GENERIC_EVIDENCE_LANE_POLICY_VERSION",
    "LANE_CONTEXT",
    "LANE_DEFINITION",
    "LANE_QUARANTINE",
    "LANE_SCOPE",
    "LANE_SIBLING",
    "EvidenceItem",
    "EvidenceLanePolicy",
    "KCProfile",
    "LaneDecision",
    "build_lane_packet",
    "classify_evidence_item",
    "summarize_lane_packet",
    "summarize_lane_packets",
]
