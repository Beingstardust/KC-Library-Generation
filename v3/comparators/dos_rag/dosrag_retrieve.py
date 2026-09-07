"""Retrieval driver for the DOS-RAG comparator.

Calls the vendored, unmodified authors' RAG class directly:
  - RAG.chunk_and_embed_document  (chunking + embedding, DOS-RAG's own code, untouched)
  - RAG.retrieve                  (similarity rank -> budget select -> source-order restore,
                                      DOS-RAG's own code, untouched)

No retrieval or reordering logic is reimplemented anywhere in this file. The only new code here
is (a) building the combined multi-document corpus text (corpus_text.py, an orchestration choice
about WHAT text to feed DOS-RAG, not a change to HOW it retrieves), (b) the query string
(canonical_name + hierarchy path, same convention as the existing Base Dense RAG baseline), and
(c) a thin index-cache so chunk_and_embed_document is not rerun per KC query.

DOES NOT import or call anything from KC_L's own retrieval stack (src/kc_l/retrieval_gate/*) -
see 12_LEAK_TEST.md for the enforced negative-import test.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_VENDOR_ROOT = os.path.join(_THIS_DIR, "vendor", "dos-rag-eval")
if _VENDOR_ROOT not in sys.path:
    sys.path.insert(0, _VENDOR_ROOT)

from source.method.RAG import RAG  # noqa: E402  (vendored, unmodified authors' code)
from source.method.EmbeddingModels import SnowflakeArcticEmbeddingModel  # noqa: E402
from scipy.spatial import distance as _scipy_distance  # noqa: E402 (already a RAG.py dependency)

from corpus_text import load_documents, combine_documents, locate_chunk_provenance  # noqa: E402


DEFAULT_CHUNK_SIZE = 100  # DOS-RAG paper/repo default (source/experiments/*/precreate_nodes.py)


@dataclass
class DosRagRetrievalResult:
    query: str
    top_k: int
    max_tokens: int
    context: str
    pre_reorder_node_indices: List[int]      # similarity-rank order, straight from RAG.retrieve()
    final_order_node_indices: List[int]      # source-position order, derived from context content
    selected_chunk_count: int
    selected_source_chars: int
    estimated_source_tokens: int             # len(context) // 4, a rough char/4 heuristic, labeled as such
    chunk_provenance: List[Dict[str, Any]]    # one entry per selected node, source-position order
    pre_reorder_scores: List[Dict[str, Any]]  # [{"node_index", "rank", "cosine_distance"}], similarity-rank order


class DosRagCorpusIndex:
    """One combined-corpus RAG index. Embeds once (chunk_and_embed_document), reused across every
    KC query via RAG.retrieve - matches the authors' own precompute-once-query-many-times
    pattern (RAG.store_nodes/load_nodes).
    """

    def __init__(self, corpus_jsonl_path: str, embedding_model_dir: str,
                 chunk_size: int = DEFAULT_CHUNK_SIZE, cache_path: Optional[str] = None):
        self.chunk_size = chunk_size
        embedder = SnowflakeArcticEmbeddingModel(model_name=embedding_model_dir)
        self.rag = RAG(chunk_size=chunk_size, embedding_model=embedder, qa_model=None)

        joined, spans = load_documents(corpus_jsonl_path)
        self.combined_text, self.combined_spans = combine_documents(joined, spans)

        if cache_path and os.path.exists(cache_path):
            self.rag.load_nodes(cache_path)
        else:
            self.rag.chunk_and_embed_document(self.combined_text)
            if cache_path:
                self.rag.store_nodes(cache_path)

        self.n_chunks = len(self.rag.nodes)

    def retrieve(self, query: str, top_k: int, max_tokens: int) -> DosRagRetrievalResult:
        context, pre_reorder_ids = self.rag.retrieve(query=query, top_k=top_k, max_tokens=max_tokens)

        # Telemetry only, per the full-run brief's explicit "preserve initial retrieval
        # scores/ranks" requirement - RAG.retrieve computes cosine distance internally
        # (scipy.spatial.distance.cosine, RAG.py) but does not return it. This recomputes the
        # EXACT same real quantity, over the SAME query embedding and the SAME stored node
        # embeddings retrieve already used, purely for reporting. It is never fed back into
        # selection, ordering, or admission - those remain 100% inside the unmodified
        # RAG.retrieve call above, already completed by this point.
        query_embedding = self.rag.embedding_model.create_query_embedding(query)
        pre_reorder_scores = [
            {
                "node_index": idx,
                "rank": rank,
                "cosine_distance": round(
                    float(_scipy_distance.cosine(query_embedding, self.rag.nodes[idx].embedding)), 6
                ),
            }
            for rank, idx in enumerate(pre_reorder_ids)
        ]

        # Final source-order is recovered by reading which chunk text appears where in the
        # returned context string, not by re-deriving it ourselves - this checks the actual
        # returned artifact of the real retrieve call, matching the Stage 1 synthetic test's
        # own verification method.
        node_by_id = {i: self.rag.nodes[i] for i in pre_reorder_ids}
        positioned = []
        for i, node in node_by_id.items():
            pos = context.find(node.text.replace("\n", " ").strip()[:60])
            positioned.append((pos if pos >= 0 else 10**9, i))
        positioned.sort()
        final_order_ids = [i for _, i in positioned]

        provenance = []
        for i in final_order_ids:
            node = self.rag.nodes[i]
            prov = locate_chunk_provenance(node.text, self.combined_spans)
            prov["chunk_index"] = i
            prov["chunk_char_len"] = len(node.text)
            provenance.append(prov)

        return DosRagRetrievalResult(
            query=query, top_k=top_k, max_tokens=max_tokens, context=context,
            pre_reorder_node_indices=list(pre_reorder_ids),
            final_order_node_indices=final_order_ids,
            selected_chunk_count=len(pre_reorder_ids),
            selected_source_chars=len(context),
            estimated_source_tokens=len(context) // 4,
            chunk_provenance=provenance,
            pre_reorder_scores=pre_reorder_scores,
        )


def dosrag_query_text(canonical_name: str, hierarchy_path: List[str]) -> str:
    """Method-neutral query: canonical KC name + hierarchy path, space-joined - the SAME
    convention the existing Base Dense RAG baseline already uses
    (v3/pipeline/build_baseline_rag_packets.py:hierarchy_query_text), reused here rather than
    invented fresh, per 05_QUERY_ADAPTER.md / the feasibility audit's query-fairness section.
    No proposed-only query expansion, disambiguation terms, or PRF is included.
    """
    parts = [canonical_name] + [p for p in (hierarchy_path or []) if p]
    return " ".join(parts).strip()
