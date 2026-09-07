"""Library-wide impact of v33, mirroring the exact measurement that caught v27's collateral damage
before it shipped. If this shows meaningful loss on units the review accepted, v33 gets rejected
and deleted the same way v27 was - the discipline applies regardless of how good the isolated test
looked.
"""
import json
import sys
from collections import Counter

sys.path.insert(0, '/path/to/kc_l/src')
from kc_l.retrieval_gate.evidence_pack import attributes_via_definitional_marker

DATA = '/path/to/kc_l/data/v3/runs/v3_20260812'

packets = []
with open(DATA + '/_v24to28_prescorerfix/packets/kc_packets.jsonl', encoding='utf-8') as f:
    for line in f:
        packets.append(json.loads(line))


def labels_of(pk):
    h = pk.get('hierarchy') or {}
    out = [pk.get('canonical_name') or '']
    out += list(pk.get('aliases') or [])
    out += list(h.get('topic_path') or [])
    return out


tot = flag = 0
names = Counter()
per_unit = []
flagged_detail = []
for pk in packets:
    labels = labels_of(pk)
    ev = pk.get('evidence_for_synthesis') or []
    n = 0
    for e in ev:
        tot += 1
        f = attributes_via_definitional_marker(e.get('text'), labels)
        if f:
            flag += 1
            n += 1
            names[f] += 1
            flagged_detail.append((pk.get('canonical_name'), f, e.get('text')))
    if ev:
        per_unit.append((n / len(ev), n, len(ev), pk.get('canonical_name')))

print('=' * 100)
print('LIBRARY-WIDE IMPACT')
print('=' * 100)
print('evidence flagged: %d / %d (%.2f%%)' % (flag, tot, 100.0 * flag / max(tot, 1)))
print()
print('flagged, in full:')
for name, marker, text in flagged_detail:
    print('  %-38s [%s]  %r' % (name, marker, (text or '')[:130]))
print()
print('most-flagged method names:', dict(names.most_common(10)))
print()
per_unit.sort(reverse=True)
print('units losing the largest share (top 10):')
for share, n, total, nm in per_unit[:10]:
    print('   %5.0f%%  %2d/%2d  %s' % (100 * share, n, total, nm))
