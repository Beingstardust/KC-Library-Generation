from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, List, Mapping, Sequence

from .text_normalize import match_normalize, normalize_ws

TOKEN_RE = re.compile(r"[A-Za-z0-9_']+")
SENTENCE_SPLIT_RE = re.compile(r"(?:\r?\n)+|(?<=[\.\?!;:])\s+")
STOPWORDS = {
    "the",
    "and",
    "for",
    "that",
    "with",
    "from",
    "this",
    "into",
    "when",
    "where",
    "what",
    "which",
    "have",
    "will",
    "than",
    "then",
    "used",
    "using",
    "between",
    "over",
    "under",
    "into",
    "onto",
    "your",
    "their",
    "them",
    "they",
    "also",
    "must",
    "able",
    "should",
    "would",
    "could",
    "being",
    "such",
    "each",
    "same",
    "more",
    "most",
    "very",
    "much",
    "many",
    "some",
    "only",
    "just",
    "both",
    "less",
    "than",
    "after",
    "before",
    "about",
    "because",
    "through",
    "while",
    "whose",
    "across",
    "there",
    "here",
    "been",
    "were",
    "into",
    "does",
    "done",
    "doesnt",
}
def tokenize(text: str, *, min_len: int = 3) -> List[str]:
    return [token.lower() for token in TOKEN_RE.findall(text) if len(token) >= min_len]


def unique_preserve_order(items: Sequence[Any]) -> List[Any]:
    seen: set[Any] = set()
    out: List[Any] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def ensure_string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        text = normalize_ws(str(item))
        if text:
            out.append(text)
    return out


def derive_doc_group(doc_id: str) -> str:
    lower = match_normalize(doc_id)
    if any(token in lower for token in ["clustering", "silhouette", "cluster", "dbscan", "hierarch"]):
        return "clustering"
    if any(token in lower for token in ["evaluation", "bestmodel"]):
        return "evaluation"
    if any(token in lower for token in ["dataeng", "featureselection", "handout"]):
        return "dataeng"
    if "underpinnings" in lower:
        return "underpinnings"
    if any(token in lower for token in ["classification", "_unit_nb", "_unit_dts"]):
        return "classification"
    return "other"


def derive_kc_group(kc_path: Sequence[Any]) -> str:
    joined = match_normalize(" ".join(str(part) for part in kc_path))
    if any(token in joined for token in ["clustering", "silhouette", "dbscan", "hierarch"]):
        return "clustering"
    if any(token in joined for token in ["evaluation", "precision", "recall", "roc", "confusion", "cross validation"]):
        return "evaluation"
    if any(token in joined for token in ["data engineering", "feature selection"]):
        return "dataeng"
    if "underpinnings" in joined:
        return "underpinnings"
    if any(token in joined for token in ["classification", "decision trees", "naive bayes"]):
        return "classification"
    return "other"


def build_query_text(
    canonical_name: str,
    aliases: Sequence[str],
    hierarchy_context: Sequence[str] | None = None,
) -> str:
    alias_part = " ; ".join(normalize_ws(alias) for alias in aliases if normalize_ws(alias))
    hierarchy_part = " ; ".join(normalize_ws(item) for item in hierarchy_context or [] if normalize_ws(item))
    pieces = [normalize_ws(canonical_name), alias_part, hierarchy_part]
    return " | ".join(piece for piece in pieces if piece)


def build_name_context_terms(
    canonical_name: str,
    aliases: Sequence[str],
    hierarchy_context: Sequence[str] | None = None,
    *,
    context_limit: int = 24,
) -> Mapping[str, Any]:
    canonical_norm = match_normalize(canonical_name)
    alias_norms = [match_normalize(alias) for alias in aliases if normalize_ws(alias)]
    canonical_tokens = set(tokenize(canonical_norm))
    alias_tokens = set(token for alias in alias_norms for token in tokenize(alias))
    context_tokens = [
        token
        for token in tokenize(match_normalize(" ".join(str(item) for item in hierarchy_context or [])))
        if token not in canonical_tokens and token not in alias_tokens and token not in STOPWORDS
    ]
    return {
        "canonical_norm": canonical_norm,
        "alias_norms": alias_norms,
        "canonical_tokens": canonical_tokens,
        "alias_tokens": alias_tokens,
        "context_keywords": unique_preserve_order(context_tokens)[:context_limit],
    }


def build_name_seed_terms(
    canonical_name: str,
    aliases: Sequence[str],
    seed_definition: str,
    *,
    seed_limit: int = 24,
) -> Mapping[str, Any]:
    # Archived compatibility wrapper for historical retrieval code. The active
    # Step 6.6 to Step 6.8 path must call build_name_context_terms instead.
    return build_name_context_terms(
        canonical_name,
        aliases,
        [seed_definition] if normalize_ws(seed_definition) else [],
        context_limit=seed_limit,
    )


def exact_phrase_hits(sentence_norm: str, canonical_norm: str, alias_norms: Sequence[str]) -> tuple[bool, bool]:
    exact_name = bool(canonical_norm and canonical_norm in sentence_norm)
    exact_alias = any(alias and alias in sentence_norm for alias in alias_norms)
    return exact_name, exact_alias


def split_sentences(raw_text: str) -> List[str]:
    pieces = [normalize_ws(part) for part in SENTENCE_SPLIT_RE.split(raw_text) if normalize_ws(part)]
    if pieces:
        return pieces
    normalized = normalize_ws(raw_text)
    return [normalized] if normalized else []


def split_exact_sentences(raw_text: str) -> List[str]:
    text = str(raw_text or "")
    if not text:
        return []
    out: List[str] = []
    start = 0
    for match in SENTENCE_SPLIT_RE.finditer(text):
        piece = text[start:match.start()].strip()
        if normalize_ws(piece):
            out.append(piece)
        start = match.end()
    tail = text[start:].strip()
    if normalize_ws(tail):
        out.append(tail)
    if out:
        return out
    stripped = text.strip()
    return [stripped] if normalize_ws(stripped) else []


def collect_competitor_tokens(
    kc_rows: Mapping[str, Mapping[str, Any]],
    competitor_ids: Sequence[str],
    *,
    min_token_len: int = 4,
) -> List[str]:
    tokens: List[str] = []
    for competitor_id in competitor_ids:
        row = kc_rows.get(str(competitor_id))
        if not row:
            continue
        name = normalize_ws(str(row.get("canonical_name") or ""))
        aliases = ensure_string_list(row.get("aliases"))
        for token in tokenize(name, min_len=min_token_len):
            tokens.append(token)
        for alias in aliases:
            for token in tokenize(alias, min_len=min_token_len):
                tokens.append(token)
    return unique_preserve_order(tokens)


def competitor_token_hit_count(text: str, competitor_tokens: Iterable[str]) -> int:
    token_set = set(tokenize(match_normalize(text), min_len=4))
    return sum(1 for token in competitor_tokens if token in token_set)


def preferred_good_name_order() -> List[str]:
    return [
        "bayes' theorem",
        "gini index",
        "silhouette coefficient",
        "mutual information",
        "entropy",
        "conditional independence",
        "naive independence assumption",
        "misclassification rate",
        "information gain",
        "gain ratio",
    ]


@dataclass
class CandidateSentence:
    candidate_id: str
    doc_id: str
    block_id: str
    page_index: int
    layer: str
    bbox: Any
    quote: str
    source_text: str
    patch_heading: str
    block_anchor_id: str
    origin: str
    doc_group: str
    kc_group: str
    doc_mismatch: bool
    name_alias_hits: int
    seed_kw_overlap: int
    exact_name_phrase: bool
    exact_alias_phrase: bool
    heading_name_hits: int
    primary_alignment_score: float
    primary_combined_score: float
    pre_score: float
    sentence_id: str = ""
    sent_idx: int = -1
    char_start: int = -1
    char_end: int = -1
    reveal_group_id: int | None = None
    reveal_canonical_page_index: int | None = None
    patch_id: str = ""
    patch_type: str = ""
    patch_span_source: str = ""
    page_heading_norm: str = ""
    text_source: str = ""
    source_block_text: str = ""
    quote_raw: str = ""
    quote_match_norm: str = ""
    text_raw: str = ""
    text_match_norm: str = ""
    source_block_text_raw: str = ""
    source_block_text_match_norm: str = ""
    quote_verified: bool = False
    quote_rebound: bool = False
    quote_rebind_reason: str = ""
    sentence_flags: dict[str, bool] = field(default_factory=dict)
    embed_sim_target: float = 0.0
    embed_best_other: float = 0.0
    embed_margin: float = 0.0
    embed_best_other_kc_id: str = ""
    rerank_target: float = 0.0
    rerank_best_other: float = 0.0
    rerank_margin: float = 0.0
    rerank_best_other_kc_id: str = ""
    semantic_route: str = ""
    gate_reasons: List[str] = field(default_factory=list)
    d2_used: bool = False
    d2_decision: str = ""
    d2_confidence: str = ""
    accepted: bool = False
    final_role: str = "other"
    original_block_id: str = ""
    original_page_index: int = -1
    original_layer: str = ""
    provenance_status: str = "original"
    provenance_source: str = ""
    provenance_note: str = ""
    provenance_quality_flags: List[str] = field(default_factory=list)
    role_scores: dict[str, float] = field(default_factory=dict)
    role_source: str = "heuristic"
    role_confidence: str = "high"
    role_ambiguous: bool = False
    role_ambiguity_reason: str = ""

    def as_dict(self) -> Mapping[str, Any]:
        return asdict(self)
