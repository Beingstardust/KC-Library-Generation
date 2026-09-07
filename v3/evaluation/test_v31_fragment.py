"""Does v31 catch the real Feature Selection Definition fragment, and leave good content alone?"""
import json
import sys
import time

sys.path.insert(0, '/path/to/kc_l/src')
from kc_l.retrieval_gate.evidence_pack import (
    assemble_passages, build_corpus_block_index, build_document_long_sentences,
    is_severed_fragment)

CORPUS = ('/path/to/shared'
          'retrieval_sentence_overlay/20260727T022835Z_9e856df6/2026-07-27_085228/'
          'sentence_corpus.jsonl')

t0 = time.time()
corpus = [json.loads(l) for l in open(CORPUS, encoding='utf-8')]
print('corpus loaded: %d sentences (%.1fs)' % (len(corpus), time.time() - t0))

t0 = time.time()
long_sentences = build_document_long_sentences(corpus)
print('doc_long_sentences built: %d docs (%.1fs)' % (len(long_sentences), time.time() - t0))
for doc, sents in long_sentences.items():
    print('   %-45s %6d long sentences' % (doc, len(sents)))

# the exact fragment that produced the real failure
frag = 'feature selection is performed outside cross-validation.'
doc = 'DOC_introduction_to_data_mining'
t0 = time.time()
hit = is_severed_fragment(frag, doc, long_sentences)
print()
print('is_severed_fragment(real fragment) = %s  (%.4fs)' % (hit, time.time() - t0))

# end-to-end: build the actual block and see if assemble_passages rejects it
block = [r for r in corpus if r.get('block_id') == 'DOC_introduction_to_data_mining:pymupdf:235:16']
print('block members:', [r.get('sentence_text') for r in block])
blocks = build_corpus_block_index(block)
hits = [{'sentence': block[0], 'rerank_prob': 0.68, 'bm25_score': 1.0}]
passages = assemble_passages(hits, blocks, max_passages=10, max_chars=9000, min_relevance=0.55,
                             doc_long_sentences=long_sentences)
print('passages admitted:', len(passages))

print()
print('=' * 90)
print('REGRESSION GUARDS')
print('=' * 90)

# 1. a lowercase-starting sentence with NO longer counterpart anywhere must survive
lonely = {'sentence_text': 'x denotes the feature vector for a single training instance.',
          'doc_id': 'DOC_introduction_to_data_mining', 'block_id': 'D:b:900', 'sent_idx': 0,
          'sentence_id': 'lonely'}
print('lonely lowercase sentence (no longer counterpart) flagged:',
      is_severed_fragment(lonely['sentence_text'], lonely['doc_id'], long_sentences))

# 2. a normal capital-starting sentence must never be flagged regardless of content
normal = 'Node impurity measures how mixed the class labels are within a node of the tree.'
print('normal capital-starting sentence flagged:',
      is_severed_fragment(normal, doc, long_sentences))

# 3. timing sanity for the whole build (this runs once per packet build, not per unit)
print()
print('total one-time cost so far: corpus load + long_sentences build measured above')
