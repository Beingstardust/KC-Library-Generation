"""Corpus-to-document-text adapter for the DOS-RAG comparator.

Reconstructs per-document flowing text from the SAME shared sentence_corpus.jsonl the existing
Base Dense RAG baseline already reads (see 07_CORPUS_INTERFACE_ANALYSIS.md, the feasibility
audit's corpus-fairness recommendation). This is a shared-upstream-extraction reconstruction
only - no KC_L-specific processing (no shape flags, no boilerplate filtering, no block assembly,
no junk/damage detection) is applied here. DOS-RAG's own split_text (vendored, unmodified)
re-chunks this text with its own sentence tokenizer and its own token budget; nothing in this
module performs any chunking of its own.

Ordering rule, empirically verified (see 05_CORPUS_ADAPTER.md): sentence_corpus.jsonl rows for a
given doc_id are concatenated in the FILE'S OWN row order. char_start/char_end in the corpus
schema are BLOCK-LOCAL offsets that reset to 0 at every new block_id - confirmed by direct
inspection of a real document's page-5 blocks (18 consecutive blocks, char_start restarting at 0
each time) - so they cannot be used as a cross-block sort key. The file's own row order was
separately confirmed, on that same real page, to already be true reading order (block index
0..18 emitted sequentially); this module trusts that native order rather than inventing a new
sort key that the corpus schema does not actually support.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class SentenceSpan:
    """One original corpus sentence row's location inside the RECONSTRUCTED per-document text
    (NOT an offset into the original PDF - char_start_in_doc/char_end_in_doc are indices into the
    joined string this module builds, used only to map a DOS-RAG chunk back to the real
    sentence_id/page_index rows it was built from).
    """
    doc_id: str
    sentence_id: str
    page_index: int
    char_start_in_doc: int
    char_end_in_doc: int
    text: str


def load_documents(corpus_jsonl_path: str) -> Tuple[Dict[str, str], Dict[str, List[SentenceSpan]]]:
    """Returns (doc_id -> joined_text, doc_id -> ordered list of SentenceSpan).

    Join rule: sentence_text values for the same doc_id, in corpus-file row order, joined with a
    single space (deterministic, and precise enough to locate a DOS-RAG chunk's source span later
    via substring search - see provenance.py).
    """
    texts: Dict[str, List[str]] = {}
    spans: Dict[str, List[SentenceSpan]] = {}
    offsets: Dict[str, int] = {}

    with open(corpus_jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            doc_id = row.get("doc_id")
            sent = str(row.get("sentence_text") or "").strip()
            if not doc_id or not sent:
                continue

            texts.setdefault(doc_id, [])
            spans.setdefault(doc_id, [])
            start = offsets.get(doc_id, 0)
            if texts[doc_id]:
                start += 1  # the join separator that will precede this sentence
            end = start + len(sent)

            spans[doc_id].append(SentenceSpan(
                doc_id=doc_id,
                sentence_id=str(row.get("sentence_id") or ""),
                page_index=row.get("page_index"),
                char_start_in_doc=start,
                char_end_in_doc=end,
                text=sent,
            ))
            texts[doc_id].append(sent)
            offsets[doc_id] = end

    joined = {doc_id: " ".join(parts) for doc_id, parts in texts.items()}
    return joined, spans


def combine_documents(
    joined: Dict[str, str], spans: Dict[str, List[SentenceSpan]]
) -> Tuple[str, List[SentenceSpan]]:
    """Concatenates all documents into ONE combined text, in first-appearance order in `joined`'s
    own key order (i.e. the corpus file's own document order - deterministic, not arbitrary).

    Why one combined text rather than one RAG instance per document: DOS-RAG's own RAG class has
    no multi-document concept at all - chunk_and_embed_document/retrieve operate over
    whatever single text they are given, and the authors' own experiments (QuALITY, NarrativeQA,
    InfinityBench) are each single-document-per-question tasks, so the class was never designed
    or tested for cross-document merging. Inventing a cross-document merge/rerank step ourselves
    would be new logic DOS-RAG's authors never wrote - a real method alteration. Treating the
    whole course corpus as one combined text and letting the UNMODIFIED chunk_and_embed_document/
    retrieve run over it once is the faithful adaptation: no new ranking logic, and the
    "restore to source position" mechanism still does something real and meaningful (position
    within the fixed, deterministic whole-corpus concatenation), matching how a real deployment
    of DOS-RAG against a multi-document knowledge base would have to be assembled anyway, since
    nothing in the method assumes single-document scope.
    """
    parts: List[str] = []
    combined_spans: List[SentenceSpan] = []
    cursor = 0
    for doc_id, text in joined.items():
        if parts:
            cursor += 2  # "\n\n" document separator inserted below
        offset = cursor
        parts.append(text)
        for sp in spans[doc_id]:
            combined_spans.append(SentenceSpan(
                doc_id=sp.doc_id,
                sentence_id=sp.sentence_id,
                page_index=sp.page_index,
                char_start_in_doc=sp.char_start_in_doc + offset,
                char_end_in_doc=sp.char_end_in_doc + offset,
                text=sp.text,
            ))
        cursor = offset + len(text)
    combined_text = "\n\n".join(parts)
    return combined_text, combined_spans


def locate_chunk_provenance(chunk_text: str, spans: List[SentenceSpan]) -> dict:
    """Best-effort, honest provenance for one DOS-RAG chunk's text within one document's spans.

    DOS-RAG's split_text re-tokenizes sentences with nltk and rejoins with single spaces
    (utils.py: sent_tokenize then " ".join(chunk)) - its sentence boundaries are not guaranteed
    to align 1:1 with this corpus's own original sentence rows, so exact span matching is not
    always possible. This function reports what it can actually establish and says so honestly
    when it cannot, rather than inventing a page number (per the task's explicit "do not invent
    page numbers or source locations that cannot be recovered reliably").

    Strategy: find the first ~40 non-whitespace characters of the chunk as a substring inside the
    document's own concatenated sentence texts (not the DOS-RAG-rejoined chunk itself, which may
    have different internal whitespace) using a whitespace-normalized comparison. If found,
    resolve which SentenceSpan(s) overlap that offset range for the whole chunk length; report
    the resulting page_index range and the covered sentence_ids. If not found, report
    "provenance": "unresolved" - never a guessed value.
    """
    def norm(s: str) -> str:
        return " ".join(s.split())

    chunk_norm = norm(chunk_text)
    doc_norm_parts = []
    norm_to_orig_start = []  # doc_norm char offset -> original span index this offset falls in
    cursor = 0
    for i, sp in enumerate(spans):
        t = norm(sp.text)
        doc_norm_parts.append(t)
        norm_to_orig_start.append((cursor, cursor + len(t), i))
        cursor += len(t) + 1  # +1 for the join space added below
    doc_norm = " ".join(doc_norm_parts)

    probe = chunk_norm[:40] if len(chunk_norm) >= 40 else chunk_norm
    pos = doc_norm.find(probe) if probe else -1
    if pos < 0:
        return {"provenance": "unresolved", "reason": "chunk text not located in document spans"}

    end_pos = pos + len(chunk_norm)
    covered_span_indices = [i for (s, e, i) in norm_to_orig_start if e > pos and s < end_pos]
    if not covered_span_indices:
        return {"provenance": "unresolved", "reason": "offset match found no overlapping spans"}

    covered = [spans[i] for i in covered_span_indices]
    pages = sorted({s.page_index for s in covered if s.page_index is not None})
    return {
        "provenance": "resolved",
        "doc_id": covered[0].doc_id,
        "page_index_min": pages[0] if pages else None,
        "page_index_max": pages[-1] if pages else None,
        "sentence_ids": [s.sentence_id for s in covered],
        "n_source_sentences_covered": len(covered),
    }
