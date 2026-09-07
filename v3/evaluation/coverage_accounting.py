"""Which of the 51 registered failures do the shipped fixes actually reach?

"Accounted for" and "fixed" are different claims and this keeps them apart. Every failure is
documented and diagnosed; far fewer are addressed by v24-v26, and this reports the difference
honestly by testing each failure against the precondition its candidate fix requires.

  v25 can only help a unit whose admitted lead-in is followed by a formula-shaped block. A passage
       ending in "is." that introduces prose is not a payload case, however similar it looks.
  v26 can only help a unit that HAS a rival in the library - the wrong-sense cases whose competing
       concept is not a library unit (CLIQUE, SNN, Jarvis-Patrick) have nothing to lose to.
  v24 can only help where a cleaner rendering of the damaged text exists elsewhere in the corpus.

Everything else is reported as not addressed, which is the honest state of clusters 3 and 4.
"""
import io
import json
import os
import sys

sys.path.insert(0, '/path/to/kc_l/src')
from kc_l.retrieval_gate.evidence_pack import (
    ends_with_lead_in, is_formula_payload, find_rival_units,
    build_corpus_block_index, build_block_successor_index, control_char_damage)

MIR = '/path/to/kc_l'
DATA = os.path.join(MIR, 'data/v3/runs/v3_20260812')
CORPUS = ('/path/to/shared'
          'retrieval_sentence_overlay/20260727T022835Z_9e856df6/2026-07-27_085228/'
          'sentence_corpus.jsonl')

reg = [json.loads(l) for l in io.open(os.path.join(MIR, 'v3/evaluation/failure_register.jsonl'),
                                      encoding='utf-8') if l.strip()]
packets = {}
with io.open(os.path.join(DATA, 'packets/kc_packets.jsonl'), encoding='utf-8') as f:
    for line in f:
        r = json.loads(line)
        packets[r.get('kc_id')] = r
all_names = [str(p.get('canonical_name') or '') for p in packets.values()]

corpus = [json.loads(l) for l in io.open(CORPUS, encoding='utf-8')]
blocks = build_corpus_block_index(corpus)
succ = build_block_successor_index(corpus)

for r in reg:
    pk = packets.get(r['kc_id']) or {}
    ev = pk.get('evidence_for_synthesis') or []
    verdict, why = 'not addressed', ''

    # --- v25 precondition: an admitted lead-in whose successor block is a formula ---
    payload_found = None
    for e in ev:
        txt = e.get('text') or ''
        if not ends_with_lead_in(txt):
            continue
        key = (e.get('doc_id'), (e.get('evidence_id') or ''))
        # recover the real block key from the corpus by matching the seed sentence
        for (doc, bid), members in blocks.items():
            if doc != e.get('doc_id'):
                continue
            joined = ' '.join(str(m.get('sentence_text') or '').strip() for m in
                              sorted(members, key=lambda m: int(m.get('sent_idx') or 0))).strip()
            if joined and joined == txt.strip():
                nxt = succ.get((doc, bid))
                if nxt:
                    nxt_txt = ' '.join(str(m.get('sentence_text') or '').strip() for m in
                                       sorted(blocks.get(nxt, []),
                                              key=lambda m: int(m.get('sent_idx') or 0))).strip()
                    if is_formula_payload(nxt_txt):
                        payload_found = nxt_txt[:70]
                break
        if payload_found:
            break
    if payload_found:
        verdict, why = 'v25 recovers a formula', payload_found

    # --- v26 precondition: a rival unit exists ---
    rivals = find_rival_units(r['canonical_name'] or '', all_names)
    if r['root_cause_refined'] == 'ADMISSION_WRONG_SENSE':
        if rivals:
            verdict = 'v26 has rivals' if verdict == 'not addressed' else verdict + ' + v26'
            why = why or ('rivals: ' + ', '.join(rivals[:3]))
        else:
            verdict, why = 'NOT addressed (no library rival)', 'competing sense is not a unit'

    # --- v24 precondition: damaged text in evidence with a cleaner rendering available ---
    if r['root_cause_refined'] == 'MATH_EXTRACTION_SHATTERED':
        dmg = [e.get('text') or '' for e in ev if control_char_damage(e.get('text') or '')]
        if dmg:
            key_words = [w for w in (r['canonical_name'] or '').lower().split() if len(w) > 4]
            clean = [s for s in corpus
                     if not control_char_damage(s.get('sentence_text') or '')
                     and all(w in (s.get('sentence_text') or '').lower() for w in key_words[:2])
                     and any(ch in (s.get('sentence_text') or '') for ch in '=√∑\\')]
            verdict = 'v24 may recover' if clean else 'NOT addressed (all renderings damaged)'
            why = ('%d clean candidates' % len(clean)) if clean else ''

    r['fix_coverage'] = verdict
    r['fix_coverage_note'] = why

io.open(os.path.join(MIR, 'v3/evaluation/failure_register.jsonl'), 'w', encoding='utf-8').write(
    ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in reg))

from collections import Counter
print('=' * 96)
print('FIX COVERAGE OF THE 51 REGISTERED FAILURES')
print('=' * 96)
for k, n in Counter(r['fix_coverage'] for r in reg).most_common():
    print('  %-42s %3d' % (k, n))
print()
by_cluster = {}
for r in reg:
    by_cluster.setdefault(r['root_cause_refined'], []).append(r)
for cl, rs in sorted(by_cluster.items(), key=lambda kv: -len(kv[1])):
    reached = sum(1 for r in rs if not r['fix_coverage'].startswith(('not addressed', 'NOT')))
    print('-' * 96)
    print('%-30s %2d failures   reached by a shipped fix: %d' % (cl, len(rs), reached))
    for r in sorted(rs, key=lambda r: r['row']):
        print('   row %3d  %-42s %-34s %s' % (
            r['row'], (r['canonical_name'] or '')[:42], r['fix_coverage'],
            (r['fix_coverage_note'] or '')[:40]))
