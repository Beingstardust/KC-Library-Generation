"""Does the foreign-method guard catch the wrong-attribution failures without eating good evidence?

Pure string logic, no reranker, so this runs fast over every packet. Two questions:
  1. on the failing units, is the specific contaminating sentence flagged?
  2. across the whole library, how much evidence would this remove, and from where?
The second matters most: a guard that flags 30% of the library is a new failure, not a fix.
"""
import json
import sys
from collections import Counter

sys.path.insert(0, '/path/to/kc_l/src')
from kc_l.retrieval_gate.evidence_pack import attributes_to_foreign_method

DATA = '/path/to/kc_l/data/v3/runs/v3_20260812'

packets = []
with open(DATA + '/packets/kc_packets.jsonl', encoding='utf-8') as f:
    for line in f:
        packets.append(json.loads(line))


def labels_of(pk):
    h = pk.get('hierarchy') or {}
    out = [pk.get('canonical_name') or '']
    out += list(pk.get('aliases') or [])
    out += list(h.get('topic_path') or [])
    return out


TARGETS = {
    'MAX (Complete Linkage)': 'CLIQUE',
    'Core Point': 'SNN',
    'DBSCAN Parameters (eps, minPts)': 'SNN',
    'Hierarchical Clustering Complexity': 'JP',
    'Euclidean Distance': 'Bregman',
    'Cosine Similarity': 'Bregman',
}

print('=' * 100)
print('TARGETED CASES')
print('=' * 100)
for pk in packets:
    name = pk.get('canonical_name')
    if name not in TARGETS:
        continue
    want = TARGETS[name]
    labels = labels_of(pk)
    flagged = []
    for e in pk.get('evidence_for_synthesis') or []:
        f = attributes_to_foreign_method(e.get('text'), labels)
        if f:
            flagged.append((f, (e.get('text') or '')[:110]))
    hit = any(want.lower() in f.lower() for f, _ in flagged)
    print()
    print('%-38s expect %-8s caught=%s   flagged %d/%d passages' % (
        name, want, 'YES' if hit else 'no', len(flagged), len(pk.get('evidence_for_synthesis') or [])))
    for f, txt in flagged[:3]:
        print('    [%s] %r' % (f, txt))

print()
print('=' * 100)
print('LIBRARY-WIDE IMPACT')
print('=' * 100)
tot = flag = 0
per_unit = []
names = Counter()
for pk in packets:
    labels = labels_of(pk)
    ev = pk.get('evidence_for_synthesis') or []
    n = 0
    for e in ev:
        tot += 1
        f = attributes_to_foreign_method(e.get('text'), labels)
        if f:
            flag += 1
            n += 1
            names[f] += 1
    if ev:
        per_unit.append((n / len(ev), n, len(ev), pk.get('canonical_name')))
print('evidence flagged: %d / %d (%.1f%%)' % (flag, tot, 100.0 * flag / max(tot, 1)))
print()
print('most-flagged method names:')
for nm, c in names.most_common(12):
    print('   %-18s %d' % (nm, c))
print()
per_unit.sort(reverse=True)
print('units losing the largest share:')
for share, n, total, nm in per_unit[:10]:
    print('   %5.0f%%  %2d/%2d  %s' % (100 * share, n, total, nm))
