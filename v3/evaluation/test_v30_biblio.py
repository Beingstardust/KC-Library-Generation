"""Does v30 actually reject the real BIRCH citation block, and leave real content alone?"""
import json
import sys

sys.path.insert(0, '/path/to/kc_l/src')
from kc_l.retrieval_gate.evidence_pack import assemble_passages, build_corpus_block_index

CORPUS = ('/path/to/shared'
          'retrieval_sentence_overlay/20260727T022835Z_9e856df6/2026-07-27_085228/'
          'sentence_corpus.jsonl')

corpus = []
with open(CORPUS, encoding='utf-8') as f:
    for line in f:
        r = json.loads(line)
        if r.get('block_id') in (
                'DOC_introduction_to_data_mining:pymupdf:1036:17',
                'DOC_introduction_to_data_mining:pymupdf:1036:18'):
            corpus.append(r)

print('members loaded:', len(corpus))
for r in sorted(corpus, key=lambda r: (r['block_id'], r.get('sent_idx') or 0)):
    print(' ', r['block_id'], r.get('sent_idx'), repr(r.get('sentence_text')))

blocks = build_corpus_block_index(corpus)
seed = next(r for r in corpus if r.get('sentence_text') == 'clustering method for very large databases.')
hits = [{'sentence': seed, 'rerank_prob': 0.65, 'bm25_score': 1.0}]
passages = assemble_passages(hits, blocks, max_passages=10, max_chars=9000, min_relevance=0.55)
print()
print('passages admitted:', len(passages))
for p in passages:
    print('  ', repr(p.get('text')))

# regression guard: real, legitimate content must not be affected
print()
print('REGRESSION GUARD: legitimate content with a bracket citation survives')
good = {'sentence_text': 'Node impurity measures how mixed the class labels are within a node of the tree [3].',
        'doc_id': 'D', 'block_id': 'D:b:200', 'sent_idx': 0, 'sentence_id': 'g1'}
blocks2 = build_corpus_block_index([good])
hits2 = [{'sentence': good, 'rerank_prob': 0.70, 'bm25_score': 1.0}]
p2 = assemble_passages(hits2, blocks2, max_passages=10, max_chars=9000, min_relevance=0.55)
print('  passages:', len(p2), '->', repr(p2[0]['text']) if p2 else None)
