"""Does competitive assignment separate the confused senses, and does it leave clean units alone?

Runs the real reranker over the real evidence of the wrong-sense failures. Two things have to hold
for this to be worth shipping:

  1. the wrong-sense passages that produced the failures are claimed by their true owner and dropped
  2. units that were NOT wrong-sense failures keep their evidence - the "without choking it" side,
     which the last cycle got wrong by verifying only the first half
"""
import json
import math
import sys

sys.path.insert(0, '/path/to/kc_l/src')

from kc_l.retrieval_gate.evidence_pack import find_rival_units, drop_passages_claimed_by_rivals
from kc_l.retrieval_gate.retrieval import CrossEncoderReranker

DATA = '/path/to/kc_l/data/v3/runs/v3_20260812'

packets = {}
with open(DATA + '/packets/kc_packets.jsonl', encoding='utf-8') as f:
    for line in f:
        r = json.loads(line)
        packets[r.get('canonical_name')] = r
all_names = sorted(packets.keys())

rr = CrossEncoderReranker()
assert rr.available, 'reranker unavailable'


def sigmoid(x):
    return 1.0 / (1.0 + math.exp(-x))


def scorer(query, texts):
    return [sigmoid(s) for s in rr.score(query, texts)]


# units the review found wrong-sense, and units it accepted (regression guard)
WRONG_SENSE = ['External Index: Entropy', 'External Index: Precision', 'F-Measure',
               'Core Point', 'DBSCAN Parameters (eps, minPts)', 'MAX (Complete Linkage)',
               'Mutually Exclusive Classes']
CLEAN = ['Border Point', 'Noise Point', 'K-Means Algorithm', 'Bayes’ Theorem',
         'Information Gain', 'Hunt’s Algorithm', 'Binary Decision Tree']

print('=' * 100)
print('WRONG-SENSE UNITS  (expect: rival-claimed passages dropped)')
print('=' * 100)
for name in WRONG_SENSE:
    pk = packets.get(name)
    if not pk:
        print('  [missing] %s' % name)
        continue
    passages = pk.get('evidence_for_synthesis') or []
    rivals = find_rival_units(name, all_names)
    kept, dropped = drop_passages_claimed_by_rivals(passages, name, rivals, scorer)
    print()
    print('%-38s  passages %2d -> %2d   dropped %d' % (name, len(passages), len(kept), len(dropped)))
    print('   rivals: %s' % ', '.join(rivals) if rivals else '   rivals: (none)')
    for d in dropped[:3]:
        print('   DROP own=%.3f rival=%.3f (%s)' % (d['own_score'], d['rival_score'], d['rival']))
        print('        %r' % d['text'][:120])

print()
print('=' * 100)
print('ACCEPTED UNITS  (expect: little or no loss)')
print('=' * 100)
total_before = total_after = 0
for name in CLEAN:
    pk = packets.get(name)
    if not pk:
        print('  [missing] %s' % name)
        continue
    passages = pk.get('evidence_for_synthesis') or []
    rivals = find_rival_units(name, all_names)
    kept, dropped = drop_passages_claimed_by_rivals(passages, name, rivals, scorer)
    total_before += len(passages)
    total_after += len(kept)
    flag = '   <-- LOSS' if len(dropped) > max(1, len(passages) // 4) else ''
    print('%-38s  passages %2d -> %2d   dropped %d%s' % (
        name, len(passages), len(kept), len(dropped), flag))
    for d in dropped[:1]:
        print('        own=%.3f rival=%.3f (%s)  %r' % (
            d['own_score'], d['rival_score'], d['rival'], d['text'][:90]))

print()
print('accepted-unit retention: %d/%d passages (%.0f%%)' % (
    total_after, total_before, 100.0 * total_after / max(total_before, 1)))
