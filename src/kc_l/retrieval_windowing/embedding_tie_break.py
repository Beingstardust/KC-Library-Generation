from __future__ import annotations

"""Embedding-assisted tie-breaking for the source-surface fallback kernel's score-tied
candidate pools.

Scope, deliberately narrow: embedding similarity is used only to *rank within* a set of
candidates that already passed the existing deterministic lexical relevance kernel
(source_surface_fallback.py). It never expands the candidate set and never searches the
corpus independently - it operates on the small, already-filtered tied group the kernel
produces (confirmed: up to ~36 pre-trim candidates per KC, often many tied on an
identical score with no principled way to break the tie other than file order). This keeps
the corpus-variety/false-positive risk bounded to exactly the same pool the lexical kernel
already vouched for.

Reuses the existing Step 4.3 embedding index verbatim (qwen3-embedding:8b, 4096-dim,
L2-normalized, cosine similarity = dot product) - no new index, no new model. The only new
runtime cost is one embedding call per KC (its own canonical_name/seed_definition/aliases
text) plus a lookup of each tied candidate's already-precomputed block-level embedding by
block_id - no new embeddings are computed for corpus text at query time.

One sanctioned exception to "never searches the corpus independently":
zero_candidate_embedding_fallback below, used ONLY when the lexical kernel returns zero
candidates for a KC (confirmed case: KC_CLF_UND_002, "Querying Phase" - the corpus discusses
the same concept as "deduction", a pure vocabulary-mismatch/lexical-gap case with zero token
overlap, so no lexical kernel tuning can ever find it). This is a distinct, explicitly-gated
code path from rerank_windows_with_embedding_tie_break above - it is never invoked when the
lexical kernel finds even one weak candidate.
"""

import json
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

import numpy as np


def l2_normalize(vec: np.ndarray) -> np.ndarray:
    denom = float(np.linalg.norm(vec)) + 1e-12
    return vec / denom


def ollama_embed(
    base_url: str,
    model: str,
    inputs: List[str],
    *,
    truncate: bool = True,
    dimensions: int = 4096,
    keep_alive: str = "2h",
    options: Mapping[str, Any] | None = None,
    timeout_s: float = 120.0,
) -> List[List[float]]:
    """Verbatim call shape reused from steps/step_04_structure_retrieval_index/scripts/
    run_step4_3.py's own ollama_embed - the same function that built the corpus embedding
    index this module reads, so a freshly-computed KC-definition embedding lands in the exact
    same vector space as the precomputed corpus embeddings.
    """
    url = base_url.rstrip("/") + "/api/embed"
    payload = {
        "model": model,
        "input": inputs,
        "truncate": bool(truncate),
        "dimensions": int(dimensions),
        "keep_alive": keep_alive,
        "options": dict(options or {}),
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    obj = json.loads(raw)
    embs = obj.get("embeddings")
    if not isinstance(embs, list):
        raise RuntimeError(f"Ollama embed response missing embeddings: keys={list(obj.keys())}")
    return embs


_BLOCK_EMBEDDING_CACHE: Dict[str, Dict[str, np.ndarray]] = {}


def load_block_embeddings(embedding_index_root: Path, doc_id: str) -> Dict[str, np.ndarray]:
    """Load a single document's precomputed block-level embeddings from the Step 4.3 index,
    keyed by block_id. Cached per (embedding_index_root, doc_id) since each doc's embedding
    matrix is a real file (hundreds of MB) not worth reloading per KC.
    """
    cache_key = f"{embedding_index_root}::{doc_id}"
    if cache_key in _BLOCK_EMBEDDING_CACHE:
        return _BLOCK_EMBEDDING_CACHE[cache_key]

    doc_dirs = sorted((embedding_index_root / doc_id).glob("*"))
    if not doc_dirs:
        _BLOCK_EMBEDDING_CACHE[cache_key] = {}
        return {}
    doc_dir = doc_dirs[-1]
    emb_dir = doc_dir / "embeddings"
    npy_path = emb_dir / "embeddings.f32.npy"
    rows_path = emb_dir / "rows.jsonl"
    if not npy_path.exists() or not rows_path.exists():
        _BLOCK_EMBEDDING_CACHE[cache_key] = {}
        return {}

    matrix = np.load(npy_path)
    block_ids: List[str] = []
    with rows_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            block_ids.append(str(row.get("block_id") or ""))

    lookup: Dict[str, np.ndarray] = {}
    for idx, block_id in enumerate(block_ids):
        if not block_id or idx >= matrix.shape[0]:
            continue
        lookup[block_id] = matrix[idx]

    _BLOCK_EMBEDDING_CACHE[cache_key] = lookup
    return lookup


def kc_definition_text(kc_row: Mapping[str, Any]) -> str:
    """The text embedded to represent the KC's own meaning for similarity comparison -
    canonical_name plus whatever definition/alias text is available, matching what a reader
    would use to judge "is this passage actually about this KC" (not just the label alone,
    since a bare label is often too short to embed meaningfully)."""
    parts = [str(kc_row.get("canonical_name") or "")]
    seed_definition = kc_row.get("seed_definition") or kc_row.get("definition")
    if seed_definition:
        parts.append(str(seed_definition))
    aliases = kc_row.get("aliases") or []
    if isinstance(aliases, list) and aliases:
        parts.append(", ".join(str(a) for a in aliases if a))
    text = " - ".join(p for p in parts if p.strip())

    specific = _most_specific_segment(str(kc_row.get("canonical_name") or ""))
    if specific:
        # Compound-name weighting: the same compound-name pattern already
        # identified (Mechanism B - "External Index: Precision" etc.) also dilutes
        # embedding similarity, not just lexical matching - confirmed directly for
        # KC_CLF_NB_003 ("Conditional Probability (Likelihood)"): a single pooled embedding of
        # the full name is dominated by the two-word "Conditional Probability" phrase, and the
        # parenthetical "Likelihood" qualifier never wins a tie-break against generic
        # conditional-probability text. Repeating the most-specific segment biases the pooled
        # vector toward it without discarding the surrounding context (the full name is still
        # present once, for background sense).
        text = f"{specific}. {specific}. {text}"
    return text


def _most_specific_segment(canonical_name: str) -> str:
    """Extract a compound canonical_name's most-specific distinguishing segment - the
    parenthetical (e.g. "Conditional Probability (Likelihood)" -> "Likelihood") or the text
    after a colon (e.g. "External Index: Precision" -> "Precision"). Returns "" when the name
    has no compound structure, matching the confirmed Mechanism-B name shapes exactly
    rather than guessing at other punctuation patterns.
    """
    import re

    paren_match = re.search(r"\(([^)]+)\)\s*$", canonical_name)
    if paren_match:
        return paren_match.group(1).strip()
    if ":" in canonical_name:
        return canonical_name.rsplit(":", 1)[-1].strip()
    return ""


def rerank_tied_group_by_similarity(
    tied_windows: Sequence[Dict[str, Any]],
    kc_embedding: np.ndarray,
    embedding_index_root: Path,
) -> List[Dict[str, Any]]:
    """Re-sort a group of score-tied windows by cosine similarity to the KC's own definition
    embedding (dot product, since both sides are L2-normalized). Windows whose block_id has no
    precomputed embedding (rare - e.g. a block dropped during indexing) keep their original
    relative order at the back of the group, never crash, never get silently dropped.
    """
    scored: List[tuple] = []
    unscored: List[Dict[str, Any]] = []
    for window in tied_windows:
        doc_id = str(window.get("doc_id") or "")
        block_id = str(window.get("block_id") or "")
        if not doc_id or not block_id:
            unscored.append(window)
            continue
        block_embeddings = load_block_embeddings(embedding_index_root, doc_id)
        vec = block_embeddings.get(block_id)
        if vec is None:
            unscored.append(window)
            continue
        similarity = float(np.dot(kc_embedding, vec))
        scored.append((similarity, window))

    scored.sort(key=lambda item: item[0], reverse=True)
    result = [w for _, w in scored] + unscored
    for rank, (similarity, window) in enumerate(scored):
        window["embedding_tie_break_similarity"] = round(similarity, 6)
        window["embedding_tie_break_rank"] = rank
    return result


def _window_tier(window: Mapping[str, Any]) -> str:
    """Extract the source_surface_fallback tier ("exact_surface", "target_token",
    "definition_head", "branch_local_heading") from a window's score_reasons list, where
    it's always the first entry (f"tier:{candidate['tier']}" - see _score_candidate in
    source_surface_fallback.py). Falls back to "" for windows with no score_reasons (e.g.
    candidates from a different source entirely), which simply become their own tier bucket -
    never silently merged with a real tier.
    """
    for reason in window.get("score_reasons") or []:
        reason = str(reason)
        if reason.startswith("tier:"):
            return reason[len("tier:"):]
    return ""


def rerank_windows_with_embedding_tie_break(
    windows: List[Dict[str, Any]],
    kc_row: Mapping[str, Any],
    *,
    embedding_index_root: Path,
    ollama_host: str,
    embedding_model: str = "qwen3-embedding:8b",
    score_band_width: float = 1.0,
) -> List[Dict[str, Any]]:
    """Top-level entry point: given a score-sorted windows list (as source_window_kernel.py
    already produces), group windows into score bands and re-rank each band by embedding
    similarity to the KC's own definition. Returns a new list, same length, same items (only
    reordered within bands) - never adds or removes candidates.

    Band definition (2026-07-25, generalizing the original exact-score-tie grouping):
    scanning top-down within a single tier, a band starts at the first unassigned window's
    score and includes every subsequent window whose score is within `score_band_width` of
    that band's starting (highest) score; the next unassigned window (score below the band)
    starts a new band. score_band_width=0.0 reproduces the original exact-tie-only behavior.

    Bands never cross tier boundaries (exact_surface / target_token / definition_head /
    branch_local_heading), even if their score ranges would otherwise overlap - confirmed
 (KC_EVAL_ROC_001) that within a single tier, score differences of a few points
    come from secondary heuristic bonuses (hierarchy-match subtype, cue bonus, formula
    penalty) that don't reliably track true relevance as well as embedding similarity does
    (e.g. at an identical score of 8.0, similarity ranged from 0.60 to 0.81), whereas the tier
    itself is a coarser, more reliable relevance signal that a similarity band should not be
    allowed to override.
    """
    if not windows:
        return windows

    definition_text = kc_definition_text(kc_row)
    if not definition_text.strip():
        return windows

    kc_embs = ollama_embed(ollama_host, embedding_model, [definition_text])
    if not kc_embs:
        return windows
    kc_embedding = l2_normalize(np.array(kc_embs[0], dtype=np.float32))

    result: List[Dict[str, Any]] = []
    i = 0
    n = len(windows)
    while i < n:
        band_tier = _window_tier(windows[i])
        band_top_score = float(windows[i].get("score") or 0.0)
        j = i + 1
        while j < n:
            same_tier = _window_tier(windows[j]) == band_tier
            within_band = (band_top_score - float(windows[j].get("score") or 0.0)) <= score_band_width
            if not (same_tier and within_band):
                break
            j += 1
        group = windows[i:j]
        if len(group) > 1:
            group = rerank_tied_group_by_similarity(group, kc_embedding, embedding_index_root)
        result.extend(group)
        i = j
    return result


def apply_source_diversity_floor(
    reranked: List[Dict[str, Any]],
    pre_rerank_sorted: List[Dict[str, Any]],
    limit: int,
) -> List[Dict[str, Any]]:
    """Guarantee that any doc_id present in the pre-rerank top-`limit` slice (a source that
    would have survived truncation on lexical score/file-order alone) still has at least one
    representative after the embedding-reranked list is truncated to `limit`.

    Confirmed 2026-07-25 (KC_CLU_EVAL_004 "Separation"): a bare, alias-less canonical name
    ("Separation") produces a single ambiguous-word embedding query, and when the lexical
    kernel's entire candidate pool collapses into one score band (no tiering to protect it),
    reranking that band by similarity to the weak query can push an entire source document
    (DOC_Guides_merged, phrased differently from the textbook corpus but equally on-topic)
    below the truncation cutoff - a real content loss the tie-break was only ever meant to
    reorder around, not cause. Embedding similarity remains a secondary signal: it may still
    reorder freely, it just may not evict a source that had already earned a slot on the
    kernel's own lexical relevance gate.
    """
    if limit <= 0 or len(reranked) <= limit:
        return reranked[:limit]

    baseline_doc_ids = {str(w.get("doc_id") or "") for w in pre_rerank_sorted[:limit]}
    truncated = list(reranked[:limit])
    truncated_doc_ids = [str(w.get("doc_id") or "") for w in truncated]
    overflow = list(reranked[limit:])

    for doc_id in baseline_doc_ids:
        if doc_id in truncated_doc_ids:
            continue
        replacement_idx = next(
            (i for i, w in enumerate(overflow) if str(w.get("doc_id") or "") == doc_id), None
        )
        if replacement_idx is None:
            continue
        counts = Counter(truncated_doc_ids)
        evict_idx = next(
            (i for i in range(len(truncated) - 1, -1, -1) if counts[truncated_doc_ids[i]] > 1),
            None,
        )
        if evict_idx is None:
            continue
        counts[truncated_doc_ids[evict_idx]] -= 1
        truncated[evict_idx] = overflow.pop(replacement_idx)
        truncated_doc_ids[evict_idx] = doc_id

    return truncated


_BLOCK_TEXT_CACHE: Dict[str, Dict[str, Dict[str, Any]]] = {}


def load_block_text_corpus(embedding_index_root: Path, doc_id: str) -> Dict[str, Dict[str, Any]]:
    """Load a single document's block_text_corpus.jsonl (text + page_index per block_id) - the
    sibling artifact to the block-level embeddings load_block_embeddings reads, living
    alongside embeddings/ in the same run-id-named directory. Cached per
    (embedding_index_root, doc_id) for the same reason load_block_embeddings is (a real file,
    not worth reloading per KC).
    """
    cache_key = f"{embedding_index_root}::{doc_id}"
    if cache_key in _BLOCK_TEXT_CACHE:
        return _BLOCK_TEXT_CACHE[cache_key]

    doc_dirs = sorted((embedding_index_root / doc_id).glob("*"))
    if not doc_dirs:
        _BLOCK_TEXT_CACHE[cache_key] = {}
        return {}
    doc_dir = doc_dirs[-1]
    text_path = doc_dir / "block_text_corpus.jsonl"
    if not text_path.exists():
        _BLOCK_TEXT_CACHE[cache_key] = {}
        return {}

    lookup: Dict[str, Dict[str, Any]] = {}
    with text_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            block_id = str(row.get("block_id") or "")
            if block_id:
                lookup[block_id] = row

    _BLOCK_TEXT_CACHE[cache_key] = lookup
    return lookup


def zero_candidate_embedding_fallback(
    kc_row: Mapping[str, Any],
    *,
    embedding_index_root: Path,
    ollama_host: str,
    embedding_model: str = "qwen3-embedding:8b",
    top_n: int = 20,
) -> List[Dict[str, Any]]:
    """Last-resort, full-corpus embedding search. Callers must only invoke this when the
    deterministic lexical kernel (source_surface_fallback.py) has already returned zero
    candidates for this KC - this function performs no lexical check of its own and does not
    know whether the kernel already found something, by design (keeps the trigger condition
    visible and auditable at the one call site in builder.py rather than duplicated here).

    Searches every indexed document's block embeddings (this corpus: 4 documents, ~49k blocks
    total, well within a single in-memory dot-product pass), ranks by cosine similarity to the
    KC's own definition text, and returns the top `top_n` blocks in the same window-dict shape
    the rest of the pipeline expects (doc_id, block_id, page_index, text, score,
    score_reasons). Every returned window carries tier "embedding_fallback" - a value never
    produced by the lexical kernel's own TIER_PRIORITY - so it can always be told apart
    downstream, and "score": 0.0 so it never outranks any lexically-scored candidate in a
    plain score sort.
    """
    definition_text = kc_definition_text(kc_row)
    if not definition_text.strip():
        return []

    kc_embs = ollama_embed(ollama_host, embedding_model, [definition_text])
    if not kc_embs:
        return []
    kc_embedding = l2_normalize(np.array(kc_embs[0], dtype=np.float32))

    doc_ids = sorted(
        p.name for p in embedding_index_root.iterdir() if p.is_dir() and p.name != "_sets"
    )

    scored: List[tuple] = []
    for doc_id in doc_ids:
        block_embeddings = load_block_embeddings(embedding_index_root, doc_id)
        if not block_embeddings:
            continue
        block_texts = load_block_text_corpus(embedding_index_root, doc_id)
        for block_id, vec in block_embeddings.items():
            text_row = block_texts.get(block_id)
            if not text_row:
                continue
            text = str(text_row.get("text") or "").strip()
            if not text:
                continue
            similarity = float(np.dot(kc_embedding, vec))
            scored.append((similarity, doc_id, block_id, text_row.get("page_index"), text))

    scored.sort(key=lambda item: item[0], reverse=True)

    windows: List[Dict[str, Any]] = []
    for rank, (similarity, doc_id, block_id, page_index, text) in enumerate(scored[:top_n]):
        windows.append(
            {
                "doc_id": doc_id,
                "block_id": block_id,
                "page_index": page_index,
                "text": text,
                "score": 0.0,
                "score_reasons": [
                    "tier:embedding_fallback",
                    f"embedding_fallback_similarity:{round(similarity, 6)}",
                ],
                "surface_name": "embedding_fallback",
                "surface_match_type": "embedding_fallback",
                "embedding_tie_break_similarity": round(similarity, 6),
                "embedding_tie_break_rank": rank,
                "source_surface": "embedding_fallback",
            }
        )
    return windows
