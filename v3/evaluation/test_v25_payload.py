"""Does lead-in payload admission actually recover the formulas it was built for?

Runs the real assemble_passages over the real corpus blocks for the Sample Mean and Variance case,
admitting only the lead-in block that the failing run admitted, and asks whether the formula block
that follows it now comes along. Also checks the guard: a lead-in followed by ordinary prose must
NOT drag that prose in, or this becomes a new contamination path.
"""
import json
import sys

sys.path.insert(0, '/path/to/kc_l/src')

from kc_l.retrieval_gate.evidence_pack import (
    assemble_passages, build_corpus_block_index, build_block_successor_index,
    ends_with_lead_in, is_formula_payload)

CORPUS = ('/path/to/shared'
          'retrieval_sentence_overlay/20260727T022835Z_9e856df6/2026-07-27_085228/'
          'sentence_corpus.jsonl')

corpus = []
with open(CORPUS, encoding='utf-8') as f:
    for line in f:
        r = json.loads(line)
        b = r.get('block_id') or ''
        if 'Guides_merged:mineru' in b:
            try:
                if int(b.split(':')[2]) == 38:
                    corpus.append(r)
            except (IndexError, ValueError):
                pass

blocks = build_corpus_block_index(corpus)
succ = build_block_successor_index(corpus)
print('blocks in scope: %d   successors: %d' % (len(blocks), len(succ)))

# the sentence the failing run admitted, and nothing else
seed = None
for r in corpus:
    if 'then the sample mean is' in (r.get('sentence_text') or ''):
        seed = r
        break
assert seed is not None, 'lead-in sentence not found'
print('seed block   :', seed.get('block_id'))
print('lead-in?     :', ends_with_lead_in(seed.get('sentence_text')))

key = (seed.get('doc_id'), seed.get('block_id'))
nxt = succ.get(key)
print('successor    :', nxt)
if nxt:
    nxt_text = ' '.join(s.get('sentence_text') or '' for s in blocks.get(nxt, []))
    print('successor txt:', repr(nxt_text[:120]))
    print('is payload?  :', is_formula_payload(nxt_text))

hits = [{'sentence': seed, 'rerank_prob': 0.80, 'bm25_score': 1.0}]

for label, kwargs in [
    ('WITHOUT payload admission', {}),
    ('WITH payload admission', {'block_successors': succ}),
]:
    passages = assemble_passages(
        hits, blocks, max_passages=10, max_chars=9000, min_relevance=0.55,
        member_verifier=lambda texts: [0.05 for _ in texts],  # hostile: strips everything it can
        **kwargs)
    joined = ' | '.join(p.get('text') or '' for p in passages)
    print()
    print('=' * 96)
    print(label)
    print('  passages: %d' % len(passages))
    for p in passages:
        print('   [%s] %r' % (p.get('admission_basis'), (p.get('text') or '')[:150]))
    print('  formula recovered:', ('\\sum' in joined or '\\frac' in joined))

# guard: a lead-in followed by prose must not pull the prose in
print()
print('=' * 96)
print('GUARD: lead-in followed by PROSE (must not admit)')
print('  is_formula_payload(prose) =', is_formula_payload(
    'This section explains how the estimator behaves when the sample is small and noisy.'))
print('  is_formula_payload(formula) =', is_formula_payload(
    '$$ \\mu _ { j } = \\bar { z } = \\frac { 1 } { n } \\sum _ { r = 1 } ^ { n } z _ { r } , $$'))
print('  is_formula_payload(damaged) =', is_formula_payload('\x12|Dj| p X \x13 .'))
