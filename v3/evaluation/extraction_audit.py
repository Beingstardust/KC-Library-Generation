"""Audit the corpus extraction stack: which extractor preserves what, and what is recoverable.

The failure analysis found mathematics destroyed before retrieval ever saw it, and found the three
extractors failing differently on the same source. This decides whether the next cycle should touch
the extraction stack at all, by answering three questions with counts rather than impressions:

  1. How much of the corpus carries damaged mathematics, per extractor?
  2. When one extractor damages a formula, does another one hold it intact?
  3. Are formulas being separated from the prose that introduces them (a segmentation artefact
     rather than an extraction one)?

Question 2 is the decisive one. If intact renderings already exist in the corpus, the fix is variant
selection - cheap, local, no re-extraction. If they do not, the only real fix is re-running the
extraction stack, which invalidates every prior measurement and is a different size of project.
"""
import collections
import io
import json
import re

CORPUS = ('/path/to/shared'
          'retrieval_sentence_overlay/20260727T022835Z_9e856df6/2026-07-27_085228/'
          'sentence_corpus.jsonl')

CTRL = re.compile(r'[\x00-\x1f]')
ORPHAN = re.compile(r'(?:=|\bis\b)\s*[√∑∏]\s*$')
SUM_AS_X = re.compile(r'(?:^|\s)p\s+X(?:\s|$)')
LATEX_STRUCT = re.compile(r'\\(?:frac|sum|sqrt|int|prod|bar)')
MATHISH = re.compile(r'[=<>]|[√∑∏σμµ]|\\')
LEAD_IN = re.compile(r'(?:is|are|given by|defined as|as follows|computed as)\s*[:.]?\s*$', re.I)


def extractor_of(block_id):
    parts = (block_id or '').split(':')
    return parts[1] if len(parts) > 1 else '?'


def damaged(t):
    return bool(CTRL.search(t) or ORPHAN.search(t.strip()) or SUM_AS_X.search(t))


def norm_key(t):
    """Content key robust to extractor formatting, for aligning the same passage across variants."""
    t = re.sub(r'[^a-z0-9 ]+', ' ', (t or '').lower())
    return re.sub(r'\s+', ' ', t).strip()[:90]


def main():
    stat = collections.defaultdict(collections.Counter)
    rows = []
    with io.open(CORPUS, encoding='utf-8') as f:
        for line in f:
            r = json.loads(line)
            t = r.get('sentence_text') or ''
            e = extractor_of(r.get('block_id'))
            s = stat[e]
            s['n'] += 1
            mi = bool(MATHISH.search(t))
            if mi:
                s['mathish'] += 1
            if LATEX_STRUCT.search(t):
                s['latex'] += 1
            if damaged(t):
                s['damaged'] += 1
                if mi:
                    s['damaged_mathish'] += 1
            if LEAD_IN.search(t.strip()) and len(t.strip()) < 160:
                s['leadin'] += 1
            rows.append((e, r.get('doc_id'), t))

    print('=' * 96)
    print('EXTRACTOR QUALITY')
    print('=' * 96)
    print('%-10s %8s %9s %8s %9s %9s' % ('extractor', 'n', 'mathish', 'LaTeX', 'damaged', 'leadIns'))
    for e in ('pymupdf', 'mineru', 'docling'):
        s = stat[e]
        print('%-10s %8d %9d %8d %9d %9d' % (
            e, s['n'], s['mathish'], s['latex'], s['damaged'], s['leadin']))
    print()
    for e in ('pymupdf', 'mineru', 'docling'):
        s = stat[e]
        m = max(s['mathish'], 1)
        print('%-10s  LaTeX structure on %5.1f%% of mathish  |  damage on %5.1f%% of mathish' % (
            e, 100.0 * s['latex'] / m, 100.0 * s['damaged_mathish'] / m))

    # ---- question 2: is a damaged passage held intact by another extractor? ----
    by_key = collections.defaultdict(dict)
    for e, doc, t in rows:
        if not MATHISH.search(t) or len(t.strip()) < 25:
            continue
        k = (doc, norm_key(t))
        if not k[1]:
            continue
        prev = by_key[k].get(e)
        # keep the least damaged, longest rendering per extractor
        if prev is None or (damaged(prev) and not damaged(t)) or (
                damaged(prev) == damaged(t) and len(t) > len(prev)):
            by_key[k][e] = t

    multi = {k: v for k, v in by_key.items() if len(v) > 1}
    rescuable = []
    all_damaged = 0
    for k, v in multi.items():
        dmg = {e: damaged(t) for e, t in v.items()}
        if any(dmg.values()):
            if all(dmg.values()):
                all_damaged += 1
            else:
                good = [e for e, d in dmg.items() if not d]
                bad = [e for e, d in dmg.items() if d]
                rescuable.append((k, good, bad, v))

    print()
    print('=' * 96)
    print('CROSS-EXTRACTOR RECOVERY  (passages present in >1 extractor: %d)' % len(multi))
    print('=' * 96)
    print('  damaged in some extractor but INTACT in another : %d   <- recoverable by variant choice'
          % len(rescuable))
    print('  damaged in every available extractor            : %d   <- needs re-extraction' % all_damaged)
    if rescuable:
        share = 100.0 * len(rescuable) / max(len(rescuable) + all_damaged, 1)
        print('  recoverable share of damaged multi-variant math : %.0f%%' % share)

    print()
    print('examples of recoverable damage (intact rendering exists):')
    for (doc, _), good, bad, v in rescuable[:6]:
        ge = good[0]
        be = bad[0]
        print('-' * 96)
        print('  %s   damaged in %s, intact in %s' % (doc, be, ge))
        print('    %-8s %r' % (be, v[be][:130]))
        print('    %-8s %r' % (ge, v[ge][:130]))

    # ---- question 3: formula separated from its lead-in ----
    print()
    print('=' * 96)
    print('POINTER / PAYLOAD SEPARATION')
    print('=' * 96)
    tot = sum(stat[e]['leadin'] for e in stat)
    print('  sentences that end mid-introduction ("... is:", "given by") : %d' % tot)
    print('  these are pointers whose payload is a separate sentence, so any per-sentence relevance')
    print('  judgement scores the pointer and the payload independently.')


if __name__ == '__main__':
    main()
