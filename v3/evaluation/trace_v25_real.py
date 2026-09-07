"""Why did v25 not fire for Sample Mean and Variance in the real, full-corpus build?

The isolated test used a hand-filtered subset (16 sentences from one page) and worked. This
replicates it against the ACTUAL full 100k-sentence corpus and the real successor index, to find
where the real build diverges from the isolated one.
"""
import json
import sys

sys.path.insert(0, '/path/to/kc_l/src')
from kc_l.retrieval_gate.evidence_pack import (
    build_corpus_block_index, build_block_successor_index, is_formula_payload,
    _block_key)

CORPUS = ('/path/to/shared'
          'retrieval_sentence_overlay/20260727T022835Z_9e856df6/2026-07-27_085228/'
          'sentence_corpus.jsonl')

corpus = [json.loads(l) for l in open(CORPUS, encoding='utf-8')]
print('full corpus loaded: %d sentences' % len(corpus))

seed = None
for r in corpus:
    t = r.get('sentence_text') or ''
    if 'then the sample mean is' in t and 'y _ { j }' in t:
        seed = r
        break
assert seed, 'seed sentence not found in full corpus'
print('seed:', repr(seed.get('sentence_text')[:80]))
print('seed doc_id  :', seed.get('doc_id'))
print('seed block_id:', seed.get('block_id'))
print('seed key     :', _block_key(seed))

print()
print('building full-corpus block index...')
blocks = build_corpus_block_index(corpus)
print('building full-corpus successor index...')
succ = build_block_successor_index(corpus)
print('blocks: %d   successors: %d' % (len(blocks), len(succ)))

key = _block_key(seed)
print()
print('lookup key in successors dict:', key)
nxt = succ.get(key)
print('successor found:', nxt)
if nxt:
    members = blocks.get(nxt, [])
    txt = ' '.join(str(m.get('sentence_text') or '').strip() for m in
                   sorted(members, key=lambda m: int(m.get('sent_idx') or 0)))
    print('successor text:', repr(txt[:150]))
    print('is_formula_payload:', is_formula_payload(txt))
else:
    print('NO SUCCESSOR FOUND - this key has no next block in the index')
    # is the key even present as a SOURCE in the successor mapping's groups?
    print()
    print('is this key present in `blocks` at all?', key in blocks)
    # find any successor entries sharing this doc_id to see if adjacency was computed for this doc
    doc_succ = [(k, v) for k, v in succ.items() if k[0] == key[0]]
    print('successor entries for doc %r: %d' % (key[0], len(doc_succ)))
    # is the block_id format consistent with what build_block_successor_index expects?
    print('seed block_id parts:', str(seed.get('block_id')).split(':'))
