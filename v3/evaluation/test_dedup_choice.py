"""Does deduplication actually keep the intact rendering when a damaged one competes?

The dedup scorer already intends to prefer clean math, but its has_math test looks only for "$" or
"\\". Unicode mathematics - the summation sign docling emits, the sigma pymupdf mangles - contains
neither, so both variants score has_math=0 and the decision falls through to later tiebreakers,
the last of which is raw length. A damaged-but-longer rendering would then win.

This runs the real scorer on the real pairs found in the corpus and reports which one it keeps.
"""
import sys

sys.path.insert(0, '/path/to/kc_l/src')

from kc_l.retrieval_gate import evidence_pack as EP

PAIRS = [
    ("expectation-sum",
     'For a function depending on B h(B) the expectation is trivially obtained by E[h(B)] = \x07 b P(b)h(b).',
     'For a function depending on B h ( B ) the expectation is trivially obtained by E [ h ( B ) ] = ∑ b P ( b ) h ( b ) .'),
    ("theta-estimate",
     'An estimation of θ would be \x03θ = h/n.',
     'An estimation of θ would be θ = h / n .'),
    ("kl-inequality",
     'The key is that if \x07 b Pθ′(b|a)logPθ(b, a) > \x07 b Pθ′(b|a)logPθ′(b, a) then Pθ(a) > Pθ′(a).',
     'The key is that if ∑ b P θ ′ ( b | a ) logP θ ( b , a ) > ∑ b P θ ′ ( b | a ) logP θ ′ ( b , a ) then P θ ( a ) > P θ ′ ( a ) .'),
    ("splitinfo-vs-latex",
     'Gain ratio=ΔinfoSplit Info=Entropy(Parent)-∑i=1kN(vi)NEntropy(vi) -∑i=1kN(vi)Nlog2N(vi)N (3.9)',
     '$$ \\sigma _ { j } ^ { 2 } = s ^ { 2 } = { \\frac { 1 } { n - 1 } } \\sum _ { r = 1 } ^ { n } ( z _ { r } - { \\bar { z } } ) ^ { 2 } .'),
]


def as_passage(text):
    return {'text': text, 'shapes': ['formula'], 'sentence_count': 1}


print('=' * 100)
print('DEDUP VARIANT CHOICE')
print('=' * 100)
for name, damaged, clean in PAIRS:
    sig_d = EP.content_signature(damaged)
    sig_c = EP.content_signature(clean)
    same_bucket = (sig_d == sig_c)
    sd = EP._information_score(as_passage(damaged))
    sc = EP._information_score(as_passage(clean))
    winner = 'CLEAN' if sc > sd else ('DAMAGED' if sd > sc else 'TIE')
    print()
    print('%-22s  same dedup bucket: %s' % (name, same_bucket))
    print('   damaged score %s' % (sd,))
    print('   clean   score %s' % (sc,))
    print('   -> keeps: %s%s' % (winner, '' if same_bucket else '   (different buckets: both kept, no choice made)'))
    print('   garbled_math_penalty  damaged=%.3f  clean=%.3f' % (
        EP.garbled_math_penalty(damaged), EP.garbled_math_penalty(clean)))

print()
print('=' * 100)
print('CONTROL-CHARACTER DETECTION')
print('=' * 100)
for probe in ['\x07 b P(b)h(b)', '\x03θ = h/n', '\x12|Dj|', 'p X', 'SE = √']:
    print('  penalty %.3f  structural_junk %-5s  %r' % (
        EP.garbled_math_penalty(probe),
        EP.is_structural_junk({'sentence_text': probe, 'doc_id': 'D',
                               'block_id': 'D:b:1', 'sent_idx': 0}),
        probe))
