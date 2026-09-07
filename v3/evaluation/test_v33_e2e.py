"""End-to-end test of v33 through the real assemble_passages() call, mirroring v30/v31's e2e tests."""
import sys
sys.path.insert(0, '/path/to/kc_l/src')
from kc_l.retrieval_gate.evidence_pack import assemble_passages, build_corpus_block_index

def sentence(text, **flags):
    row = {"sentence_text": text, "doc_id": "D", "block_id": "D:b:1", "sent_idx": 0}
    row.update(flags)
    return row

seed = sentence("Complete Link or MAX or CLIQUE", block_id="D:b:500", sent_idx=0, sentence_id="s0")
blocks = build_corpus_block_index([seed])
hits = [{"sentence": seed, "rerank_prob": 0.70, "bm25_score": 1.0}]
passages = assemble_passages(hits, blocks, max_passages=10, max_chars=9000, min_relevance=0.55,
                             unit_labels=["MAX (Complete Linkage)"])
print("MAX/CLIQUE case - passages admitted:", len(passages))
for p in passages:
    print("  ", repr(p.get("text")))

# regression: same text, but a unit that does NOT own "MAX" as part of its name must not trigger
seed2 = sentence("Complete Link or MAX or CLIQUE", block_id="D:b:501", sent_idx=0, sentence_id="s1")
blocks2 = build_corpus_block_index([seed2])
hits2 = [{"sentence": seed2, "rerank_prob": 0.70, "bm25_score": 1.0}]
passages2 = assemble_passages(hits2, blocks2, max_passages=10, max_chars=9000, min_relevance=0.55,
                              unit_labels=["Some Unrelated Unit"])
print("unrelated unit - passages admitted:", len(passages2), "(expect 1, unaffected)")

# regression: legitimate sibling-comparison content must survive
seed3 = sentence("The methods presented are SFG, SBG, BG, and RG.",
                 block_id="D:b:502", sent_idx=0, sentence_id="s2")
blocks3 = build_corpus_block_index([seed3])
hits3 = [{"sentence": seed3, "rerank_prob": 0.70, "bm25_score": 1.0}]
passages3 = assemble_passages(hits3, blocks3, max_passages=10, max_chars=9000, min_relevance=0.55,
                              unit_labels=["Sequential Forward Generation (SFG)"])
print("SFG legit comparison - passages admitted:", len(passages3), "(expect 1, unaffected)")
