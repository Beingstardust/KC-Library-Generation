"""End-to-end: does the real assemble_passages() now rescue precision(i,j)=pij at 0.515, the exact
real score measured against the real reranker for External Index: Precision?"""
import sys
sys.path.insert(0, '/path/to/kc_l/src')
from kc_l.retrieval_gate.evidence_pack import assemble_passages, build_corpus_block_index

def sentence(text, **flags):
    row = {"sentence_text": text, "doc_id": "D", "block_id": "D:b:1", "sent_idx": 0}
    row.update(flags)
    return row

# below the 0.55 floor, matching the real measured score (0.515)
seed = sentence("precision(i,j)=pij.", block_id="D:b:600", sent_idx=0, sentence_id="s0",
                is_formula_like=True)
blocks = build_corpus_block_index([seed])
hits = [{"sentence": seed, "rerank_prob": 0.515, "bm25_score": 1.0}]
passages = assemble_passages(
    hits, blocks, max_passages=10, max_chars=9000, min_relevance=0.55,
    unit_labels=["External Index: Precision", "external precision"])
print("real-score rescue - passages admitted:", len(passages))
for p in passages:
    print("   basis=%s  text=%r" % (p.get("admission_basis"), p.get("text")))

# regression: the sibling classifier formula at the SAME low score must NOT be rescued by
# External Index: Precision's patterns
seed2 = sentence("Precision = TP / (TP + FP).", block_id="D:b:601", sent_idx=0, sentence_id="s1",
                 is_formula_like=True)
blocks2 = build_corpus_block_index([seed2])
hits2 = [{"sentence": seed2, "rerank_prob": 0.515, "bm25_score": 1.0}]
passages2 = assemble_passages(
    hits2, blocks2, max_passages=10, max_chars=9000, min_relevance=0.55,
    unit_labels=["External Index: Precision", "external precision"])
print("sibling classifier formula NOT rescued - passages admitted:", len(passages2), "(expect 0)")

# below floor AND not formula-shaped at all - must not be rescued regardless
seed3 = sentence("The classifier performed reasonably well on the test set.",
                 block_id="D:b:602", sent_idx=0, sentence_id="s2")
blocks3 = build_corpus_block_index([seed3])
hits3 = [{"sentence": seed3, "rerank_prob": 0.515, "bm25_score": 1.0}]
passages3 = assemble_passages(
    hits3, blocks3, max_passages=10, max_chars=9000, min_relevance=0.55,
    unit_labels=["External Index: Precision", "external precision"])
print("unrelated below-floor prose NOT rescued - passages admitted:", len(passages3), "(expect 0)")
