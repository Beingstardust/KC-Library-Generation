"""Authority-context construction for the R9 final judge campaign (FINAL R9 KC CONTENT QUALITY
EVALUATION spec, section 8).

This module owns the part that is pure and portable: given passage lists already retrieved by
each system (Proposed/Base Dense/DOS-RAG) for a KC, plus an optional list of deterministic
high-recall augmentation passages found elsewhere, it deduplicates by REAL SOURCE IDENTITY (doc,
page, block/sentence coordinate - never by text similarity, which would let two independently
-extracted renderings of the same source sentence count as two authority items), strips every
system-identifying field, and assigns neutral AUTH_NNN IDs in deterministic source order.

What this module deliberately does NOT do: run BM25/dense lookup against the corpus, or decide
which "bounded immediate source neighbours" to pull in. That augmentation step must reuse the
project's own existing tokenize/BM25/DenseIndex implementation (src/kc_l/retrieval_gate/ on
Cluster-B) rather than a second, competing implementation living in evaluation_suite - the campaign
spec's section 8 explicitly says "do not invent aliases using model world knowledge" and this
package's own convention (see statistics.py) is to reuse tested generic utilities rather than
duplicate them. A thin Cluster-B-side companion script (not yet written - needs a live corpus/BM25
index to run against) is expected to call the real retrieval utilities and hand their output to
combine_authority_passages below, exactly like every other augmentation source.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

# Fields kept in a neutral authority-context item. Nothing outside this whitelist survives -
# any retrieval-score, method-tag, or system-status field on the input passage is dropped by
# construction, not by a denylist that could miss a new field later.
_NEUTRAL_FIELDS = ("doc_id", "page_index", "block_id", "sentence_id", "text")


class AuthorityContextError(ValueError):
    """Raised when a passage cannot be safely reduced to a neutral authority item - e.g. it has
    no resolvable source identity at all. Never silently dropped, since a silently-dropped
    passage is indistinguishable from one that was never retrieved."""


def source_identity_key(passage: Mapping[str, Any]) -> tuple[Any, ...]:
    """Real source identity: (doc_id, page_index, block_id or sentence_id). Two passages with
    this same key are the SAME source location even if their extracted text differs slightly
    (e.g. two PDF extractors rendering the same paragraph) - deduplication collapses them, kept
    text prefers the longer/more complete rendering deterministically (ties broken by the first
    system encountered, since input order is itself deterministic - callers pass systems in a
    fixed order)."""
    doc_id = passage.get("doc_id")
    page_index = passage.get("page_index")
    block_or_sentence = passage.get("block_id") if passage.get("block_id") is not None else passage.get("sentence_id")
    if doc_id is None or page_index is None or block_or_sentence is None:
        raise AuthorityContextError(
            f"passage has no resolvable source identity (doc_id={doc_id!r}, "
            f"page_index={page_index!r}, block/sentence={block_or_sentence!r})"
        )
    return (doc_id, page_index, block_or_sentence)


def strip_system_identity(passage: Mapping[str, Any]) -> dict[str, Any]:
    """Whitelist-only projection - the only way a new system-identifying field on the input
    (e.g. a future retrieval method's own score name) can leak through is if it were added to
    _NEUTRAL_FIELDS itself, which is a deliberate code review event, not an accidental omission
    from a denylist."""
    return {k: passage[k] for k in _NEUTRAL_FIELDS if k in passage}


def _source_order_key(item: Mapping[str, Any]) -> tuple[Any, ...]:
    return (str(item.get("doc_id", "")), item.get("page_index", 0),
            str(item.get("block_id") or item.get("sentence_id") or ""))


def combine_authority_passages(
    system_passages: Mapping[str, Iterable[Mapping[str, Any]]],
    augmentation_passages: Iterable[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """system_passages is {system_label: [passage, ...], ...} in a fixed, caller-determined
    order (e.g. {"proposed": ..., "base_dense": ..., "dos_rag": ...} every time, so tie-breaking
    on duplicate source identity is reproducible run to run). augmentation_passages is the
    deterministic high-recall lookup's output, appended last (lowest tie-break priority - a
    system's own retrieved passage is preferred verbatim over a rebuilt augmentation copy of the
    same source location).

    Returns a list of neutral items, each with doc_id/page_index/block_id-or-sentence_id/text
    only, sorted by source order (doc_id, page_index, block/sentence position) and carrying a
    fresh auth_id field ("AUTH_001", "AUTH_002", ...) assigned AFTER sorting, so the ID sequence
    itself reflects source order and nothing about which system(s) contributed the passage.
    """
    seen: dict[tuple[Any, ...], dict[str, Any]] = {}
    for label in system_passages:  # iteration order is the caller's fixed order, not a set
        for passage in system_passages[label]:
            key = source_identity_key(passage)
            if key not in seen:
                seen[key] = strip_system_identity(passage)
    for passage in augmentation_passages:
        key = source_identity_key(passage)
        if key not in seen:
            seen[key] = strip_system_identity(passage)

    ordered = sorted(seen.values(), key=_source_order_key)
    for idx, item in enumerate(ordered, start=1):
        item["auth_id"] = f"AUTH_{idx:03d}"
    return ordered


def approximate_token_count(text: str) -> int:
    """Whitespace-split word count - NOT the real tokenizer. Distinct name from the exact
    ollama-based counting used elsewhere in this project (see R9 DOS budget matching, which uses
    ollama:qwen3.8:27b:generate_prompt_eval_count) so nobody mistakes this for that precision."""
    return len(text.split())


@dataclass(frozen=True)
class AuthorityManifestRow:
    kc_id: str
    canonical_name: str
    authority_item_count: int
    authority_chars: int
    authority_approximate_token_count: int
    source_documents: tuple[str, ...]
    sha256: str


def authority_manifest_row(kc_id: str, canonical_name: str,
                            authority_items: list[dict[str, Any]]) -> AuthorityManifestRow:
    chars = sum(len(item.get("text", "")) for item in authority_items)
    tokens = sum(approximate_token_count(item.get("text", "")) for item in authority_items)
    docs = tuple(sorted({str(item.get("doc_id")) for item in authority_items}))
    serialized = json.dumps(authority_items, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return AuthorityManifestRow(
        kc_id=kc_id, canonical_name=canonical_name,
        authority_item_count=len(authority_items), authority_chars=chars,
        authority_approximate_token_count=tokens, source_documents=docs, sha256=digest,
    )
