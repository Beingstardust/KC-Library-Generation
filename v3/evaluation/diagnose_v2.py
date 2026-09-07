"""Second-pass diagnosis: separate 'the concept is named' from 'the definition is present'.

The first pass reported content present whenever a probe term appeared anywhere in the evidence.
Reading the actual packets showed that is not good enough. Sample Mean and Variance's evidence
contains "then the sample mean is" and "and the sample variance is" - the prose LEAD-INS - while
the formula they introduce was never admitted, although the corpus carries it in clean LaTeX
(DOC_Guides_merged:mineru:38:708). A probe for "sample mean" hits the lead-in and reports success
for a packet that contains no definition at all.

This pass adds three mechanical signals that catch what the term probes miss:

  dangling_lead_ins  - admitted sentences that introduce a formula ("... is:", "given by",
                       "as follows") with no formula admitted anywhere in the pack. Direct
                       evidence that the payload was dropped and only its introduction kept.
  has_real_formula   - does the pack contain anything with actual mathematical structure, as
                       opposed to prose that merely mentions the quantity?
  shattered_math     - control characters, orphaned radicals ("= √" at end of text), summation
                       signs rendered as bare letters: PDF extraction destroyed the expression,
                       so no amount of retrieval or drafting work can recover it.

corpus_has_clean_variant re-checks the corpus for a same-content rendering from a DIFFERENT
extractor that survives the shattered-math test - the difference between "this formula is
unavailable" and "this formula is available, we picked the wrong rendering of it".
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

LEAD_IN = re.compile(r'(is|are|given by|defined as|as follows|computed as|expressed as)\s*[:.]?\s*$', re.I)
CTRL = re.compile(r'[\x00-\x1f]')
ORPHAN_RADICAL = re.compile(r'(=|\bis\b)\s*√\s*$')
# real mathematical structure: an operator with operands, a latex construct, or a relation
FORMULA_SHAPE = re.compile(
    r'(\\frac|\\sum|\\sqrt|\\int|\\bar|\^\s*\{?2|[A-Za-z0-9\)\]]\s*[=<>]\s*[-+A-Za-z0-9\\(√]|'
    r'∑|√|σ|µ|μ)')


def is_shattered(t):
    if CTRL.search(t):
        return True
    if ORPHAN_RADICAL.search(t.strip()):
        return True
    # a summation rendered as a bare capital X between operands, e.g. "p X"
    if re.search(r'(?:^|\s)p\s+X(?:\s|$)', t):
        return True
    return False


def main():
    reg = [json.loads(l) for l in io.open(REG, encoding='utf-8') if l.strip()]

    packets = {}
    with io.open(os.path.join(DATA, 'packets/kc_packets.jsonl'), encoding='utf-8') as f:
        for line in f:
            r = json.loads(line)
            packets[r.get('kc_id')] = r

    # corpus index: normalised prose key -> list of (block_id, text, shattered)
    # used to find a cleaner rendering of the same content from another extractor
    corpus = []
    with io.open(CORPUS, encoding='utf-8') as f:
        for line in f:
            r = json.loads(line)
            t = r.get('sentence_text') or ''
            if FORMULA_SHAPE.search(t):
                corpus.append((r.get('block_id') or '', t))

    for r in reg:
        pk = packets.get(r['kc_id']) or {}
        ev = [(e.get('text') or '') for e in (pk.get('evidence_for_synthesis') or [])]

        dangling = [t for t in ev if LEAD_IN.search(t.strip()) and len(t.strip()) < 160]
        has_formula = any(FORMULA_SHAPE.search(t) for t in ev)
        shattered = [t for t in ev if is_shattered(t)]

        # does a clean rendering of this unit's math exist somewhere in the corpus?
        name_tokens = [w.lower() for w in re.findall(r'[A-Za-z]{4,}', r['canonical_name'] or '')]
        clean_elsewhere = []
        if name_tokens:
            for bid, t in corpus:
                tl = t.lower()
                if all(w in tl for w in name_tokens[:2]) and not is_shattered(t):
                    clean_elsewhere.append((bid, t[:150]))
                    if len(clean_elsewhere) >= 3:
                        break

        d = r.get('evidence_diagnosis') or {}
        d.update({
            'dangling_lead_ins': dangling[:4],
            'dangling_lead_in_count': len(dangling),
            'evidence_has_formula_shape': has_formula,
            'shattered_math_in_evidence': shattered[:3],
            'corpus_clean_variant_examples': clean_elsewhere,
        })
        r['evidence_diagnosis'] = d

        # refine root cause using the new signals
        rc = r['root_cause']
        if shattered:
            rc = 'MATH_EXTRACTION_SHATTERED'
        elif dangling and not has_formula:
            rc = 'FORMULA_PAYLOAD_DROPPED'
        r['root_cause_refined'] = rc

    with io.open(REG, 'w', encoding='utf-8') as f:
        for r in reg:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')

    from collections import Counter
    print('=' * 92)
    print('REFINED ROOT CAUSE  (%d failures)' % len(reg))
    print('=' * 92)
    for v, n in Counter(r['root_cause_refined'] for r in reg).most_common():
        print('  %-30s %3d  (%.0f%%)' % (v, n, 100.0 * n / len(reg)))
    print()
    for v in ['MATH_EXTRACTION_SHATTERED', 'FORMULA_PAYLOAD_DROPPED']:
        rs = [r for r in reg if r['root_cause_refined'] == v]
        if not rs:
            continue
        print('-' * 92)
        print('%s (%d)' % (v, len(rs)))
        for r in rs:
            d = r['evidence_diagnosis']
            print('  row %3d  %s' % (r['row'], r['canonical_name']))
            for t in (d['shattered_math_in_evidence'] or d['dangling_lead_ins'])[:2]:
                print('        %r' % t[:110])
            if d['corpus_clean_variant_examples']:
                print('        CLEAN ELSEWHERE: %s' % d['corpus_clean_variant_examples'][0][0])


if __name__ == '__main__':
    main()
