"""Would a lower CLAIM_MARGIN catch the wrong-sense cases v26 currently misses, without
damaging units the review already accepted?

Reuses the same real reranker and real packets as the original v26 verification. Only the margin
changes. Answers a factual question before touching the shipped constant: is there a margin where
persisting failures get caught AND accepted units stay intact, or does every failure that survives
at 0.08 only get caught by a margin that also starts damaging good units?
"""
import json
import math
import sys

sys.path.insert(0, '/path/to/kc_l/src')
from kc_l.retrieval_gate.evidence_pack import find_rival_units
from kc_l.retrieval_gate.retrieval import CrossEncoderReranker

DATA = '/path/to/kc_l/data/v3/runs/v3_20260812'

packets = {}
with open(DATA + '/_v24to28_prescorerfix/packets/kc_packets.jsonl', encoding='utf-8') as f:
    for line in f:
        r = json.loads(line)
        packets[r.get('canonical_name')] = r
all_names = sorted(packets.keys())

rr = CrossEncoderReranker()
assert rr.available


def sigmoid(x):
    return 1.0 / (1.0 + math.exp(-x))


def scorer(query, texts):
    return [sigmoid(s) for s in rr.score(query, texts)]


PERSISTING_WRONG_SENSE = ['Core Point', 'Density-Connected', 'External Index: Entropy',
                          'F-Measure', 'Mutually Exclusive Classes']
ACCEPTED = ['Border Point', 'Noise Point', 'K-Means Algorithm', 'Information Gain',
           'Binary Decision Tree', 'DBSCAN Cluster Definition', 'Sequential Forward Generation (SFG)']

KNOWN_BAD = {
    'Core Point': 'SNN similarity',
    'Density-Connected': None,
    'External Index: Entropy': None,
    'F-Measure': 'hierarchical clustering',
    'Mutually Exclusive Classes': 'mutually exclusive rules',
}

MARGINS = [0.08, 0.05, 0.03, 0.01]

# score everything ONCE per unit against own+rivals, then just resweep margins in-memory - the
# expensive part (reranker calls) should not be repeated per margin value
cache = {}
for name in PERSISTING_WRONG_SENSE + ACCEPTED:
    pk = packets.get(name)
    if not pk:
        print('MISSING', name)
        continue
    passages = pk.get('evidence_for_synthesis') or []
    rivals = find_rival_units(name, all_names)
    texts = [p.get('text') or '' for p in passages]
    if not texts or not rivals:
        cache[name] = (passages, rivals, None, None)
        continue
    own = scorer(name, texts)
    best_rival = [0.0] * len(texts)
    best_rival_name = [''] * len(texts)
    for rival in rivals:
        for i, sc in enumerate(scorer(rival, texts)):
            if sc > best_rival[i]:
                best_rival[i] = sc
                best_rival_name[i] = rival
    cache[name] = (passages, rivals, own, list(zip(best_rival, best_rival_name)))
    print('scored', name, '(%d passages, %d rivals)' % (len(passages), len(rivals)))

print()
print('=' * 100)
for margin in MARGINS:
    print('MARGIN =', margin)
    print('-' * 100)
    for name in PERSISTING_WRONG_SENSE:
        passages, rivals, own, rival_info = cache.get(name, (None, None, None, None))
        if own is None:
            print('  %-30s (no rivals / missing)' % name)
            continue
        dropped = [(passages[i], rival_info[i]) for i in range(len(passages))
                  if rival_info[i][0] - own[i] > margin]
        bad_marker = KNOWN_BAD.get(name)
        caught_bad = bad_marker and any(bad_marker.lower() in (p.get('text') or '').lower() for p, _ in dropped)
        print('  %-30s dropped=%-3d %s' % (
            name, len(dropped), ('CAUGHT KNOWN-BAD' if caught_bad else '')))
    for name in ACCEPTED:
        passages, rivals, own, rival_info = cache.get(name, (None, None, None, None))
        if own is None:
            print('  [accepted] %-30s (no rivals)' % name)
            continue
        dropped = [(passages[i], rival_info[i]) for i in range(len(passages))
                  if rival_info[i][0] - own[i] > margin]
        flag = '  <-- accepted unit losing evidence' if dropped else ''
        print('  [accepted] %-30s dropped=%-3d%s' % (name, len(dropped), flag))
    print()
