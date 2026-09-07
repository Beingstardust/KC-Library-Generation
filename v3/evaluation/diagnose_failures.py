"""Diagnose each registered failure by locating the needed content in corpus / evidence / draft.

The whole point is to stop guessing at causes. For every failure the register carries probe terms
describing what the source actually supports; this checks those probes at three levels and lets the
answer fall out of where the content is:

    in corpus, in evidence, wrong in draft   -> DRAFTING     (model had it, composed it wrong)
    in corpus, NOT in evidence               -> RETRIEVAL    (never reached the drafter)
    NOT in corpus                            -> CORPUS_LIMIT (abstention would have been correct)

It additionally checks the PRE-v22 packet for the same probes, which separates a retrieval failure
that v22/v23 caused (content was there before, stripped by member verification) from one that
predates it. Those two need opposite fixes, so conflating them would send the next cycle the wrong
way.

Wrong-sense probes are checked in evidence too: content the KC should NOT contain, present in the
pack, is admission failure rather than drafting failure even when the drafter used it faithfully.
"""
import io
import json
import os
import re

MIR = '/path/to/kc_l'
PROD = '/path/to/shared'
DATA = os.path.join(MIR, 'data/v3/runs/v3_20260812')
REG = os.path.join(MIR, 'v3/evaluation/failure_register.jsonl')
CORPUS = os.path.join(
    PROD, 'data/processed/retrieval_sentence_overlay/20260727T022835Z_9e856df6',
    '2026-07-27_085228/sentence_corpus.jsonl')


def norm(s):
    """Loose match: collapse whitespace, drop latex/markup noise, casefold."""
    s = (s or '').lower()
    s = s.replace('\\', ' ').replace('$', ' ').replace('{', ' ').replace('}', ' ')
    return re.sub(r'\s+', ' ', s)


def hits(text, probes):
    t = norm(text)
    return [p for p in probes if norm(p) in t]


def load_packets(path):
    out = {}
    if not os.path.exists(path):
        return out
    with io.open(path, encoding='utf-8') as f:
        for line in f:
            r = json.loads(line)
            out[r.get('kc_id')] = r
    return out


def evidence_text(row):
    return ' '.join((e.get('text') or '') for e in (row.get('evidence_for_synthesis') or []))


def draft_text(row):
    d = row.get('draft')
    if isinstance(d, str):
        try:
            d = json.loads(d)
        except Exception:
            return str(d)
    inner = (d or {}).get('contextual_kc_draft', d) or {}
    return str(inner.get('text') or '')


def main():
    reg = [json.loads(l) for l in io.open(REG, encoding='utf-8') if l.strip()]
    new_pk = load_packets(os.path.join(DATA, 'packets/kc_packets.jsonl'))
    old_pk = load_packets(os.path.join(DATA, '_prefix_v22_backup/packets_prefix_backup/kc_packets.jsonl'))
    drafts = {}
    with io.open(os.path.join(DATA, 'drafts/kc_drafts.jsonl'), encoding='utf-8') as f:
        for line in f:
            r = json.loads(line)
            drafts[r.get('kc_id')] = r

    # one pass over the corpus, collecting hits for every probe of every failure
    all_probes = set()
    for r in reg:
        all_probes.update(r['probes_expected'])
    corpus_hit = {p: 0 for p in all_probes}
    normed = {p: norm(p) for p in all_probes}
    with io.open(CORPUS, encoding='utf-8') as f:
        for line in f:
            t = norm(json.loads(line).get('sentence_text'))
            if not t:
                continue
            for p, np_ in normed.items():
                if np_ in t:
                    corpus_hit[p] += 1

    for r in reg:
        kc = r['kc_id']
        ev_new = evidence_text(new_pk.get(kc, {}))
        ev_old = evidence_text(old_pk.get(kc, {}))
        dr = draft_text(drafts.get(kc, {}))

        exp = r['probes_expected']
        in_corpus = [p for p in exp if corpus_hit.get(p, 0) > 0]
        in_ev_new = hits(ev_new, exp)
        in_ev_old = hits(ev_old, exp)
        in_draft = hits(dr, exp)
        wrong_in_ev = hits(ev_new, r['probes_wrong'])
        wrong_in_draft = hits(dr, r['probes_wrong'])

        if not in_corpus:
            verdict = 'CORPUS_LIMIT'
        elif not in_ev_new and in_ev_old:
            verdict = 'RETRIEVAL_REGRESSION_v22'
        elif not in_ev_new:
            verdict = 'RETRIEVAL_PREEXISTING'
        elif wrong_in_ev:
            verdict = 'ADMISSION_WRONG_SENSE'
        elif not in_draft:
            verdict = 'DRAFTING_OMITTED'
        else:
            verdict = 'DRAFTING_MALFORMED'

        r['evidence_diagnosis'] = {
            'probes_in_corpus': in_corpus,
            'probes_in_evidence_new': in_ev_new,
            'probes_in_evidence_prefix': in_ev_old,
            'probes_in_draft': in_draft,
            'wrong_sense_in_evidence': wrong_in_ev,
            'wrong_sense_in_draft': wrong_in_draft,
            'evidence_chars_new': len(ev_new),
            'evidence_chars_prefix': len(ev_old),
        }
        r['root_cause'] = verdict

    with io.open(REG, 'w', encoding='utf-8') as f:
        for r in reg:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')

    from collections import Counter
    print('=' * 92)
    print('ROOT CAUSE DISTRIBUTION  (%d failures)' % len(reg))
    print('=' * 92)
    for v, n in Counter(r['root_cause'] for r in reg).most_common():
        print('  %-28s %3d  (%.0f%%)' % (v, n, 100.0 * n / len(reg)))
    print()
    for v in ['RETRIEVAL_REGRESSION_v22', 'ADMISSION_WRONG_SENSE', 'RETRIEVAL_PREEXISTING',
              'DRAFTING_OMITTED', 'DRAFTING_MALFORMED', 'CORPUS_LIMIT']:
        rs = [r for r in reg if r['root_cause'] == v]
        if not rs:
            continue
        print('-' * 92)
        print('%s  (%d)' % (v, len(rs)))
        for r in rs:
            d = r['evidence_diagnosis']
            print('  row %3d  %-42s ev %5d->%5d  hit %d/%d%s' % (
                r['row'], (r['canonical_name'] or '')[:42],
                d['evidence_chars_prefix'], d['evidence_chars_new'],
                len(d['probes_in_evidence_new']), len(r['probes_expected']),
                ('  WRONG:' + ','.join(d['wrong_sense_in_evidence'])) if d['wrong_sense_in_evidence'] else ''))


if __name__ == '__main__':
    main()
