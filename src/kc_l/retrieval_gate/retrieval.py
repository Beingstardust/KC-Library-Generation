"""Hybrid candidate retrieval for Step 5x: BM25 recall + cross-encoder precision.

WHY THIS EXISTS
---------------
Step 5x generated candidates by exact-phrase matching against retrieval-route terms invented by
the Step 5p LLM. Measured on the audited baseline run:

    corpus sentences                                        100218
    distinct sentences the candidate bank ever touches         2164  (2.2%)
    recall of sentences literally containing the unit name      5.5%  (763 / 13971)

Ten units had ZERO name-bearing sentences banked while the corpus held them - "ROC Space
(TPR vs. FPR)" had 582 available and banked none. Every downstream gate was therefore arguing
over a bank that had already discarded 94.5% of the obviously relevant material, and no admission
change can recover a sentence that was never retrieved.

Exact-phrase matching is the wrong instrument. It cannot match morphological variation, word
order, or paraphrase, and its recall is capped by the quality of LLM-invented surface forms - only
10.6% of which were canonical variants of the unit's own registry label.

WHAT THIS DOES
--------------
Two stages, the standard hybrid-retrieval shape:

  1. RECALL - BM25 (Robertson/Sparck-Jones, k1=1.5, b=0.75) over the whole sentence corpus.
     The query is built ONLY from registry labels: canonical name, deterministic label variants,
     parent topic label, trailing topic-path labels. No model-invented terms, so the recall
     channel no longer inherits Step 5p's surface-form defects. Prototype measured 25.1% recall
     at k=150 against the same yardstick the old matcher scored 5.4% on.

  2. PRECISION - cross-encoder reranking of the BM25 pool with a local relevance model
     (a local cross-encoder relevance model; several are present on this host).
     The reranker scores aboutness directly, which is a stronger and more honest signal than
     "does this sentence repeat the unit's name", and it is what lets the recall stage be
     generous without importing noise.

The cross-encoder score travels with the candidate as a binding basis, so downstream scoring can
treat reranker-established relevance as target binding instead of requiring lexical name
repetition - the requirement that formulas and procedure steps structurally cannot satisfy.

DOMAIN AGNOSTICITY
------------------
Queries come from registry labels only. BM25 is a statistical weighting over whatever corpus it is
given. The reranker is a general-purpose relevance model. Nothing here encodes subject-matter
vocabulary, and the module is inert on a corpus it is not pointed at.
"""
from __future__ import annotations

import collections
import hashlib
import math
import os
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

# Compute nodes on this cluster have no internet access; must be set before any
# sentence_transformers/huggingface_hub import in this process (including the reranker's),
# since huggingface_hub reads this once at its own import time.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import numpy as np
from scipy import sparse

TOKEN_RE = re.compile(r"[a-z0-9]+")

# Structural/rhetorical words only; no subject-matter vocabulary.
STOPWORDS = frozenset("""
the of a an and or for in on to is are be been being with without by as it its that this these
those from into within between among not no than then so such can may might must should would
could also when where how what which there here using use used uses we you they their our
""".split)

BM25_K1 = 1.5
BM25_B = 0.75
DEFAULT_BM25_TOPK = 150
DEFAULT_RERANK_TOPN = 40
DEFAULT_RERANKER = "/path/to/scratch/kc_l/models/rerankers/BAAI__bge-reranker-v2-m3"
# General-purpose, non-domain-specific pretrained sentence-embedding model, used only as a
# fixed similarity scorer (never for generation) - see DenseIndex.
DEFAULT_EMBEDDER = "sentence-transformers/all-mpnet-base-v2"
# Identity of the text preprocessing applied before embedding. Written into the
# embedding cache and verified on load, so a cache built under different
# preprocessing can never be silently reused - the caller's cache key is derived
# from the corpus FILE (path/size/mtime/rows) and is content-independent, so it
# cannot detect this on its own. Bump this on any change to embedded text.
_EMBED_PREPROC_VERSION = "ligatures_expanded_v1"


def _disable_tf32_for_reproducible_scores() -> None:
    """Keep GPU relevance scores numerically equivalent to the CPU ones.

    The cross-encoder's score is compared against a fixed admission floor (0.55) and a relative
    floor (0.85 of the unit's own best). Ampere GPUs default to TF32 for matmul, which has fewer
    mantissa bits than fp32 and can move a score by roughly 1e-4 - enough, in principle, for a
    passage sitting exactly on a threshold to be admitted on one device and rejected on another.
    Nothing about this pipeline should depend on which hardware it ran on, so TF32 is turned off.
    Called at import, before any model is constructed.
    """
    try:
        import torch
    except Exception:
        return
    try:
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
    except Exception:
        # Older torch, or a CPU-only build: nothing to disable, and nothing to worry about.
        pass


_disable_tf32_for_reproducible_scores()


# A 1-2 char alnum segment at a word boundary, immediately followed by a hyphen and another
# word, is joined to it before tokenizing - "F-Measure" -> "fmeasure", "K-Means" -> "kmeans",
# "T-test" -> "ttest". Without this, the plain [a-z0-9]+ tokenizer splits these into a dropped
# single-char token and a bare generic word, making the query indistinguishable from unrelated
# sentences that merely share that generic word (confirmed: this made the corpus's own F-measure
# formula sentences unreachable in the BM25 pool for KC_EVAL_BASIC_006 even though they exist).
# General across any short-prefix compound name; nothing here names a specific term.
_HYPHEN_JOIN_RE = re.compile(r"(?<![a-z0-9])([a-z0-9]{1,2})-(?=[a-z])")


# Typographic ligatures are not in [a-z0-9], so TOKEN_RE treats each one as a word separator and
# the word around it is destroyed rather than merely misspelled ("deﬁne" -> nothing at all,
# "classiﬁcation" -> "classi" + "cation"). Queries come from cleanly-typed hierarchy labels, so
# any corpus sentence carrying a ligature in its key term is unreachable by lexical retrieval.
# An explicit map, NOT unicodedata NFKD: NFKD also rewrites superscripts and other compatibility
# forms ("x²" -> "x2"), quietly altering mathematical text. This touches ligatures only.
_LIGATURE_MAP = {
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl",
    "\ufb05": "st", "\ufb06": "st", "\u0132": "IJ", "\u0133": "ij", "\u0152": "OE",
    "\u0153": "oe", "\u00c6": "AE", "\u00e6": "ae",
}
_LIGATURE_TABLE = {ord(k): v for k, v in _LIGATURE_MAP.items()}


def expand_ligatures(text: Any) -> str:
    """Ligature codepoints -> their letter pairs. Lossless, deterministic, math-safe."""
    return str(text or "").translate(_LIGATURE_TABLE)


def tokenize(text: Any) -> List[str]:
    normalized = _HYPHEN_JOIN_RE.sub(r"\1", expand_ligatures(text).lower())
    return [t for t in TOKEN_RE.findall(normalized)
            if t not in STOPWORDS and len(t) > 2]


class BM25Index:
    """Sparse BM25 over a fixed sentence collection."""

    def __init__(self, texts: Sequence[str]):
        vocab: Dict[str, int] = {}
        indptr, indices, data = [0], [], []
        doc_len = np.zeros(len(texts), dtype=np.float32)
        for i, txt in enumerate(texts):
            tf = collections.Counter(tokenize(txt))
            doc_len[i] = float(sum(tf.values()))
            for term, n in tf.items():
                indices.append(vocab.setdefault(term, len(vocab)))
                data.append(float(n))
            indptr.append(len(indices))
        tf_matrix = sparse.csr_matrix(
            (np.array(data, dtype=np.float32), np.array(indices), np.array(indptr)),
            shape=(len(texts), max(len(vocab), 1)),
        )
        n_docs = tf_matrix.shape[0]
        df = np.asarray((tf_matrix > 0).sum(axis=0)).ravel()
        idf = np.log(1.0 + (n_docs - df + 0.5) / (df + 0.5)).astype(np.float32)
        avgdl = float(doc_len.mean()) or 1.0
        coo = tf_matrix.tocoo()
        denom = coo.data + BM25_K1 * (1.0 - BM25_B + BM25_B * (doc_len[coo.row] / avgdl))
        weights = ((coo.data * (BM25_K1 + 1.0)) / denom) * idf[coo.col]
        weighted = sparse.csr_matrix(
            (weights.astype(np.float32), (coo.row, coo.col)), shape=tf_matrix.shape
        )
        self.matrix = weighted.tocsc()
        self.matrix_csr = weighted.tocsr()
        self.vocab = vocab
        self.terms: List[str] = [""] * len(vocab)
        for term, idx in vocab.items():
            self.terms[idx] = term
        self.n_docs = n_docs

    def top_k(self, query_tokens: Iterable[str], k: int) -> List[Tuple[int, float]]:
        cols = [self.vocab[t] for t in set(query_tokens) if t in self.vocab]
        if not cols:
            return []
        scores = np.asarray(self.matrix[:, cols].sum(axis=1)).ravel()
        k = min(k, self.n_docs)
        idx = np.argpartition(-scores, k - 1)[:k] if k < self.n_docs else np.arange(self.n_docs)
        idx = idx[np.argsort(-scores[idx])]
        return [(int(i), float(scores[i])) for i in idx if scores[i] > 0.0]

    def expansion_terms(self, seed_doc_indices: Sequence[int], exclude: Iterable[str],
                        top_n: int) -> List[str]:
        """Pseudo-relevance feedback (Rocchio 1971 / RM3-style): the most distinctive terms
        (by this corpus's own BM25 weighting) in a seed set of documents, excluding terms
        already in the query. A pure function of the corpus's own term statistics and the seed
        documents - no external vocabulary, no model, nothing domain-specific."""
        if not seed_doc_indices:
            return []
        agg = np.asarray(self.matrix_csr[list(seed_doc_indices), :].sum(axis=0)).ravel()
        if not agg.any():
            return []
        exclude_set = {str(x).lower() for x in exclude}
        order = np.argsort(-agg)
        out: List[str] = []
        for col in order:
            if agg[col] <= 0:
                break
            term = self.terms[col]
            if term in exclude_set:
                continue
            out.append(term)
            if len(out) >= top_n:
                break
        return out


def expand_query_tokens(index: "BM25Index", base_tokens: Sequence[str], *,
                        seed_k: int = 15, expand_n: int = 8,
                        seed_pool: Optional[int] = None) -> List[str]:
    """Widen a base BM25 query with pseudo-relevance feedback drawn from this corpus alone.

    This is the corpus-derived replacement for alias-based query expansion: instead of reading
    externally-proposed name variants (which, traced to their source, always terminate in some
    LLM call), it runs the base query, looks at what the corpus's own top-ranked sentences for
    that query actually say, and pulls the most distinctive recurring terms out of them. If a
    KC's canonical name has a different surface form elsewhere in the corpus, that form tends to
    co-occur with the canonical name's own strongly-matching context and gets pulled in this way
    - without needing any process to have pre-guessed it.
    """
    seed_pool = seed_pool if seed_pool is not None else max(seed_k, 50)
    seed_hits = index.top_k(base_tokens, seed_pool)[:seed_k]
    seed_indices = [i for i, _ in seed_hits]
    expansion = index.expansion_terms(seed_indices, exclude=base_tokens, top_n=expand_n)
    if not expansion:
        return list(base_tokens)
    return list(base_tokens) + expansion


def build_query(profile: Mapping[str, Any]) -> Tuple[str, List[str]]:
    """Registry-label query for the reranker's natural-language text; BM25 recall tokens are
    additionally widened with safely-filtered profile aliases (see _safe_expansion_terms).
    The reranker's own query text is deliberately kept to registry labels only, so its relevance
    judgment is never influenced by a model-invented alias - only the recall pool is widened.
    """
    parts: List[str] = []
    name = str(profile.get("canonical_name") or "").strip()
    if name:
        parts.append(name)
    for entry in (profile.get("deterministic_label_variants") or []):
        term = entry.get("term") if isinstance(entry, Mapping) else entry
        term = str(term or "").strip()
        if term and term not in parts:
            parts.append(term)
    parent = str(profile.get("parent_topic_label") or "").strip()
    if parent:
        parts.append(parent)
    labels = [str(x) for x in (profile.get("topic_path_labels") or [])][-2:]
    parts.extend(l for l in labels if l)
    query_text = name or " ".join(parts)

    # No ancestor/parent context is folded into the reranker's own query text, in either the
    # direct parent_topic_label form or the topic_path_labels-fallback form tried earlier this
    # session. Both forms were traced to the same failure mode on real data: appending an
    # ancestor label pulls the reranker's semantic read toward that category's generic prose
    # instead of the unit's own specific content. KC_FSEL_GOOD_003 "Covariance" (whose registry
    # row has parent_topic_label == canonical_name, so the fallback fired) had its top reranked
    # results become generic "goodness of a clustering" passages once "(Goodness Criteria)" was
    # appended - the same mechanism meant to help KC_DE_MISS_005 "Informative Missingness"
    # turned out, on the real full corpus, to still leave that unit's actual best passages
    # topically off; the mechanism's one demonstrated effect on real data is negative. BM25
    # recall still sees parent and ancestor-label tokens unconditionally (bm25_terms below), so
    # recall breadth is unaffected - only the reranker's precision judgment is anchored strictly
    # to the unit's own name and deterministic label variants.
    bm25_terms = " ".join(parts)
    return query_text, tokenize(bm25_terms)


_ACRONYM_RE = re.compile(r"^[A-Z0-9]{2,5}$")


def _initials(label: str) -> str:
    """First letters of a label's words, e.g. 'Naive Bayes' -> 'NB'. Structural only."""
    return "".join(w[0] for w in re.findall(r"[A-Za-z]+", str(label or "")) if w).upper()


def expand_acronyms(name: str, ancestors: Sequence[str]) -> List[str]:
    """Replace a short all-caps token in `name` with an ancestor label whose initials match it.

    Purely structural: an acronym is recognised by shape (2-5 uppercase chars), and it is only
    expanded using the unit's OWN ancestor labels, never an external vocabulary. Nothing here
    encodes what any particular acronym stands for.
    """
    out: List[str] = []
    tokens = str(name or "").split()
    for idx, token in enumerate(tokens):
        stripped = token.strip("().,:;")
        if not _ACRONYM_RE.match(stripped):
            continue
        for ancestor in ancestors:
            ancestor = str(ancestor or "").strip()
            if not ancestor or _initials(ancestor) != stripped.upper():
                continue
            replaced = list(tokens)
            replaced[idx] = ancestor
            candidate = " ".join(replaced)
            if candidate != name and candidate not in out:
                out.append(candidate)
    return out


def candidate_query_texts(profile: Mapping[str, Any]) -> List[str]:
    """Deterministic candidate query formulations that denote ONLY this unit.

    Built from the unit's own identity fields, and deliberately limited to forms that name the
    unit and nothing else: the canonical name, and the same name with an acronym in it expanded
    to the ancestor label it abbreviates. An ancestor label is never appended as extra context,
    because the cross-encoder scores the query text as a whole - given "Unit (Category)" it
    scores passages about the CATEGORY highly, and those enter the packet as if they were
    evidence about the unit. Measured on real data: that construct gained one unit 15 passages
    while losing both its definition and its formula. Ancestor labels still widen BM25 recall
    and seed PRF (see build_query's bm25_terms); they are excluded only from the text used to
    judge relevance.
    """
    name = str(profile.get("canonical_name") or "").strip()
    if not name:
        return [""]
    path = [str(x).strip() for x in (profile.get("topic_path_labels") or []) if str(x).strip()]
    parent = str(profile.get("parent_topic_label") or "").strip()
    # nearest-first ancestors that are not just the unit's own name repeated
    ancestors = [a for a in ([parent] + list(reversed(path))) if a and a.lower() != name.lower()]
    seen_a: set = set()
    ancestors = [a for a in ancestors if not (a.lower() in seen_a or seen_a.add(a.lower()))]

    out: List[str] = [name]
    for expanded in expand_acronyms(name, ancestors):
        if expanded not in out:
            out.append(expanded)
    return out


class CrossEncoderReranker:
    """Local relevance model. Degrades to BM25 order if the model cannot be loaded."""

    def __init__(self, model_path: str = DEFAULT_RERANKER, device: Optional[str] = None,
                 batch_size: int = 64):
        self.available = False
        self.model = None
        self.batch_size = batch_size
        try:
            import torch  # noqa: F401
            from sentence_transformers import CrossEncoder
            if device is None:
                import torch as _t
                device = "cuda" if _t.cuda.is_available() else "cpu"
            self.model = CrossEncoder(model_path, device=device, max_length=512)
            self.device = device
            self.available = True
        except Exception as exc:  # pragma: no cover - environment dependent
            self.load_error = repr(exc)

    def score(self, query: str, passages: Sequence[str]) -> List[float]:
        if not self.available or not passages:
            return [0.0] * len(passages)
        pairs = [(query, p) for p in passages]
        raw = self.model.predict(pairs, batch_size=self.batch_size, show_progress_bar=False)
        return [float(x) for x in np.asarray(raw).ravel().tolist()]


class DenseIndex:
    """Corpus-wide sentence embeddings from a fixed, general-purpose pretrained model.

    A second, semantic recall channel alongside BM25+PRF: catches cases where the corpus
    describes a concept in genuinely different words than the unit's own name and hierarchy
    labels, which no purely lexical technique (including PRF) can bridge. Recall only - the
    cross-encoder relevance gate is the sole admission authority regardless of which channel
    surfaced a candidate.
    """

    def __init__(self, texts: Sequence[str], model_name: str = DEFAULT_EMBEDDER,
                device: Optional[str] = None, batch_size: int = 64,
                cache_path: Optional[str] = None):
        self.available = False
        self.embeddings = None
        self.cache_status = "disabled" if not cache_path else "miss"
        try:
            import torch
            from sentence_transformers import SentenceTransformer
            if device is None:
                device = "cuda" if torch.cuda.is_available() else "cpu"
            self.model = SentenceTransformer(model_name, device=device)

            cached = None
            if cache_path and os.path.exists(cache_path):
                try:
                    blob = np.load(cache_path)
                    # preproc is checked as well as n/model: a cache written under different
                    # text preprocessing holds vectors of different strings, and the caller's
                    # file-identity key cannot see that. Missing field = older cache = rebuild.
                    if (int(blob["n"]) == len(texts) and str(blob["model"]) == model_name
                            and str(blob.get("preproc", "")) == _EMBED_PREPROC_VERSION):
                        cached = blob["emb"]
                        self.cache_status = "hit"
                    else:
                        self.cache_status = "stale_rebuild"
                except Exception:
                    cached = None  # unreadable/stale cache is simply rebuilt

            if cached is None:
                # Same normalisation the lexical channel applies, so both channels agree about
                # what a sentence says. Without it "classiﬁcation" and "classification" embed as
                # different strings and a name query is needlessly far from its own evidence.
                cached = np.asarray(self.model.encode(
                    [expand_ligatures(x) for x in texts], normalize_embeddings=True,
                    batch_size=batch_size,
                    show_progress_bar=False, convert_to_numpy=True,
                ), dtype=np.float32)
                if cache_path:
                    try:
                        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                        np.savez(cache_path, emb=cached, n=len(texts),
                                 model=model_name, preproc=_EMBED_PREPROC_VERSION)
                        self.cache_status = "written"
                    except Exception:
                        self.cache_status = "write_failed"

            self.embeddings = cached
            self.device = device
            self.available = True
        except Exception as exc:  # pragma: no cover - environment dependent
            self.load_error = repr(exc)

    def top_k(self, query_text: str, k: int) -> List[Tuple[int, float]]:
        if not self.available or not query_text:
            return []
        q = np.asarray(self.model.encode([expand_ligatures(query_text)],
                                         normalize_embeddings=True,
                                         show_progress_bar=False, convert_to_numpy=True),
                       dtype=np.float32)[0]
        sims = self.embeddings @ q
        k = min(k, len(sims))
        idx = np.argpartition(-sims, k - 1)[:k] if k < len(sims) else np.arange(len(sims))
        idx = idx[np.argsort(-sims[idx])]
        return [(int(i), float(sims[i])) for i in idx]


def sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


SENTENCE_FIELDS = (
    "sentence_id", "block_id", "patch_id", "doc_id", "page_index", "sent_idx",
    "char_start", "char_end", "bbox", "layer", "patch_heading", "reveal_group_id",
)


def synthesize_bank_row(template: Mapping[str, Any], sentence: Mapping[str, Any],
                        *, bm25_score: float, rerank_score: float,
                        rerank_prob: float, rank: int) -> Dict[str, Any]:
    """Build a candidate-bank row for a hybrid-retrieved sentence.

    Unit-level fields are inherited from a real row for the same unit so the downstream schema
    contract is preserved exactly; sentence-level fields come from the corpus row.
    """
    row: Dict[str, Any] = dict(template)
    for field in SENTENCE_FIELDS:
        if field in sentence:
            row[field] = sentence.get(field)
    text = str(sentence.get("sentence_text") or "")
    row["text"] = text
    row["context_text"] = text
    row["source_block_text"] = sentence.get("source_block_text") or text
    row["raw_text_hash"] = hashlib.sha1(text.encode("utf-8")).hexdigest()
    seed = "%s|%s|%s" % (row.get("kc_id"), sentence.get("sentence_id"), rank)
    row["candidate_id"] = "cand_hyb_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:24]
    row["candidate_origin"] = "hybrid_bm25_cross_encoder"
    row["candidate_source"] = "hybrid_retrieval"
    row["surface_match_type"] = "hybrid_semantic_relevance"

    scores = dict(row.get("retrieval_scores") or {})
    scores.update({
        "hybrid_bm25": round(bm25_score, 6),
        "hybrid_cross_encoder": round(rerank_score, 6),
        "hybrid_cross_encoder_prob": round(rerank_prob, 6),
        "hybrid_rank": rank,
    })
    row["retrieval_scores"] = scores

    # The route contract belongs to the lexical channel. A hybrid candidate did not come from a
    # route, so it must not be judged by one: an absent contract is the honest state, and
    # _evaluate_profile_routes_for_sentence already treats that as "no route blocking".
    row["step5p_route_evaluation"] = {
        "route_contract_present": False,
        "matched_route_count": 0,
        "positive_route_match_count": 0,
        "context_only_route_match_count": 0,
        "route_positive_blocked_by_missing_support_count": 0,
        "context_only_match_without_positive_route": False,
        "positive_route_required_but_absent": False,
        "matched_routes": [],
        "route_control_role": "hybrid_retrieval_no_route_contract",
    }
    row["hybrid_retrieval"] = {
        "bm25_score": round(bm25_score, 6),
        "cross_encoder_score": round(rerank_score, 6),
        "cross_encoder_prob": round(rerank_prob, 6),
        "rank": rank,
    }
    # Every field below is an analysis of the TEMPLATE's own sentence. Leaving them in place made
    # scoring read stale judgments about different text - a clean definitional hit came back
    # rejected because it inherited another sentence's binding basis. Clear them so the scorer
    # recomputes from this row's text; unit-level config (aliases, profile guidance, topic path,
    # policy plan) is deliberately retained.
    for stale in (
        "alignment_score", "alignment_breakdown", "evidence_shape_match", "matched_surface_terms",
        "matched_target_tokens", "near_miss_reason", "retrieval_failure_signals",
        "structural_flags", "support_profile", "target_binding_basis", "target_branch_tokens",
        "target_surface_origin", "source_heading_text", "source_evidence_index",
        "source_row_index", "review_only_candidate", "hierarchy_compatibility_signal",
        "hierarchy_match_type", "fallback_reason", "fallback_score", "fallback_tier",
        "fallback_score_reasons", "fallback_caution_reason",
    ):
        if stale in row:
            current = row.get(stale)
            if isinstance(current, list):
                row[stale] = []
            elif isinstance(current, dict):
                row[stale] = {}
            elif isinstance(current, bool):
                row[stale] = False
            elif isinstance(current, (int, float)):
                row[stale] = 0
            else:
                row[stale] = None
    row["source_heading_text"] = sentence.get("patch_heading") or ""
    return row


def retrieve_for_unit(profile: Mapping[str, Any], index: BM25Index,
                      corpus: Sequence[Mapping[str, Any]], reranker: CrossEncoderReranker,
                      *, bm25_topk: int = DEFAULT_BM25_TOPK,
                      rerank_topn: int = DEFAULT_RERANK_TOPN,
                      min_rerank_prob: float = 0.5,
                      dense_index: Optional["DenseIndex"] = None,
                      dense_topk: int = 50) -> List[Dict[str, Any]]:
    """Return ranked hits: [{sentence, bm25_score, rerank_score, rerank_prob, rank}]."""
    query_text, query_tokens = build_query(profile)
    expanded_tokens = expand_query_tokens(index, query_tokens)
    pool = index.top_k(expanded_tokens, bm25_topk)
    pool_idx = {i for i, _ in pool}
    if dense_index is not None and dense_index.available:
        for i, _ in dense_index.top_k(query_text, dense_topk):
            if i not in pool_idx:
                pool.append((i, 0.0))
                pool_idx.add(i)
    if not pool:
        return []
    passages = [str(corpus[i].get("sentence_text") or "") for i, _ in pool]
    scores = reranker.score(query_text, passages)
    ranked = sorted(
        ({"sentence": corpus[i], "bm25_score": s, "rerank_score": r, "rerank_prob": sigmoid(r)}
         for (i, s), r in zip(pool, scores)),
        key=lambda h: -h["rerank_score"],
    )
    kept = [h for h in ranked if h["rerank_prob"] >= min_rerank_prob][:rerank_topn]
    for rank, hit in enumerate(kept):
        hit["rank"] = rank
    return kept
