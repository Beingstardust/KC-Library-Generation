"""Does v33's narrower signal catch the real bad cases while leaving the v27-breaking cases alone?

Pure string logic, no reranker needed - fast, exhaustive test against real corpus text and the
exact sentences that broke v27 last time.
"""
import sys
sys.path.insert(0, '/path/to/kc_l/src')
from kc_l.retrieval_gate.evidence_pack import attributes_via_definitional_marker

BAD_CASES = [
    ('MAX (Complete Linkage)', ['MAX (Complete Linkage)'],
     'MAX (Complete Linkage), also referred to as Complete Link or CLIQUE'),
    ('MAX (Complete Linkage) v2', ['MAX (Complete Linkage)'],
     'Complete Link or MAX or CLIQUE'),
    ('Core Point', ['Core Point'],
     'A point is a core point if the number of points within a given neighborhood around the '
     'point, as determined by SNN similarity and a supplied parameter Eps exceeds a certain '
     'threshold MinPts.'),
]

GOOD_CASES_THAT_BROKE_V27 = [
    ('Sequential Forward Generation (SFG)', ['Sequential Forward Generation (SFG)'],
     'The methods presented are SFG, SBG, BG, and RG.'),
    ('Sequential Forward Generation (SFG) v2', ['Sequential Forward Generation (SFG)'],
     'SFG starts from the empty set and adds the next best feature until the selected set '
     'satisfies the criterion.'),
    ('Core Point (legit)', ['Core Point'],
     'Other techniques, such as DBSCAN and SNN density-based clustering, have the notion of '
     'core points, which strongly belong to one cluster.'),
    ('Core Point (legit 2)', ['Core Point'],
     'However, the use of core points and SNN density adds considerable power and flexibility '
     'to this approach.'),
    ('Density-Connected (legit contrast)', ['Density-Connected'],
     'Unlike Jarvis-Patrick, which performs a simple thresholding and then takes the connected '
     'components as clusters, SNN density-based clustering uses a less brittle approach.'),
    ('Zero-Frequency Problem', ['Zero-Frequency Problem'],
     'The zero-frequency problem can be addressed using the Laplace estimator, which adds one '
     'to every count.'),
    ('ID3 Algorithm', ['ID3 Algorithm'],
     "ID3 is based on Hunt's algorithm and employs entropy as its splitting criterion."),
]

print('=' * 100)
print('BAD CASES (expect: caught)')
print('=' * 100)
all_bad_caught = True
for name, labels, text in BAD_CASES:
    hit = attributes_via_definitional_marker(text, labels)
    ok = hit is not None
    all_bad_caught &= ok
    print('%-5s %-30s -> %r' % ('OK' if ok else 'MISS', name, hit))
    print('      %r' % text[:110])

print()
print('=' * 100)
print('GOOD CASES THAT BROKE v27 (expect: NOT caught)')
print('=' * 100)
all_good_safe = True
for name, labels, text in GOOD_CASES_THAT_BROKE_V27:
    hit = attributes_via_definitional_marker(text, labels)
    ok = hit is None
    all_good_safe &= ok
    print('%-5s %-30s -> %r' % ('OK' if ok else 'FALSE POSITIVE', name, hit))
    print('      %r' % text[:110])

print()
print('ALL BAD CAUGHT:', all_bad_caught)
print('ALL GOOD SAFE:', all_good_safe)
