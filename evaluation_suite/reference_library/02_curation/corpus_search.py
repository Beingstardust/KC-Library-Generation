"""Deterministic, LLM-free search/navigation over the original course corpus
(sentence_corpus.jsonl). For HUMAN navigation only - this module never suggests
a definition, a correct passage, or an edit. It returns matches; the expert
interprets them.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

DEFAULT_CORPUS_PATH = "../corpus_support/sentence_corpus.jsonl"


@dataclass
class Sentence:
    sentence_id: str
    doc_id: str
    block_id: str
    sent_idx: int
    page_index: int
    sentence_text: str
    source_block_text: str
    is_formula_like: bool
    is_definition_like: bool
    is_procedure_like: bool
    is_example_like: bool


class CorpusIndex:
    def __init__(self, path: str = DEFAULT_CORPUS_PATH):
        self.path = path
        self.by_id: dict[str, Sentence] = {}
        self.by_block: dict[str, list[str]] = {}  # block_id -> [sentence_id in sent_idx order]
        self.doc_ids: set[str] = set()
        self._load()

    def _load(self) -> None:
        rows = []
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                s = Sentence(
                    sentence_id=d["sentence_id"], doc_id=d["doc_id"], block_id=d["block_id"],
                    sent_idx=d["sent_idx"], page_index=d["page_index"],
                    sentence_text=d.get("sentence_text", ""), source_block_text=d.get("source_block_text", ""),
                    is_formula_like=d.get("is_formula_like", False), is_definition_like=d.get("is_definition_like", False),
                    is_procedure_like=d.get("is_procedure_like", False), is_example_like=d.get("is_example_like", False),
                )
                rows.append(s)
                self.by_id[s.sentence_id] = s
                self.doc_ids.add(s.doc_id)
        for s in rows:
            self.by_block.setdefault(s.block_id, []).append(s.sentence_id)
        for block_id, ids in self.by_block.items():
            ids.sort(key=lambda sid: self.by_id[sid].sent_idx)

    def resolve(self, sentence_id: str) -> bool:
        return sentence_id in self.by_id

    def get(self, sentence_id: str) -> Sentence | None:
        return self.by_id.get(sentence_id)

    def search(self, query: str, doc_id: str = None, page: int = None, regex: bool = False,
               content_type: str = None, limit: int = 30) -> list[Sentence]:
        """content_type: one of formula/definition/procedure/example, or None."""
        if not query and not content_type:
            return []
        matcher = None
        if query:
            if regex:
                try:
                    pattern = re.compile(query, re.IGNORECASE)
                except re.error as e:
                    raise ValueError(f"invalid regex: {e}")
                matcher = pattern.search
            else:
                q_lower = query.lower()
                matcher = lambda text: q_lower in text.lower()

        hits = []
        for s in self.by_id.values():
            if doc_id and s.doc_id != doc_id:
                continue
            if page is not None and s.page_index != page:
                continue
            if content_type:
                flag = {
                    "formula": s.is_formula_like, "definition": s.is_definition_like,
                    "procedure": s.is_procedure_like, "example": s.is_example_like,
                }.get(content_type)
                if not flag:
                    continue
            if matcher is not None:
                haystack = s.sentence_text or s.source_block_text
                if not matcher(haystack):
                    continue
            hits.append(s)
            if len(hits) >= limit:
                break
        return hits

    def context(self, sentence_id: str, before: int = 3, after: int = 3) -> list[Sentence]:
        s = self.by_id.get(sentence_id)
        if s is None:
            return []
        block_sent_ids = self.by_block.get(s.block_id, [])
        idx = block_sent_ids.index(sentence_id)
        lo, hi = max(0, idx - before), min(len(block_sent_ids), idx + after + 1)
        return [self.by_id[sid] for sid in block_sent_ids[lo:hi]]

    def doc_summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for s in self.by_id.values():
            counts[s.doc_id] = counts.get(s.doc_id, 0) + 1
        return counts
