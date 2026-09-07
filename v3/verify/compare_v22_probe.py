"""Compare pre-v22 vs post-v22 evidence for the 8 flagged units.

Reads the OLD evidence from the live v3 run's kc_packets.jsonl (built before the member_verifier
patch) and the NEW evidence from the probe's rebuild, and reports, per unit:
  - passage/char counts before and after
  - which passages had text actually removed (member sentences stripped)
  - whether known contaminating substrings are gone
  - whether the total evidence collapsed to near-nothing (the "choking it" failure mode)
"""
import json
import os

MIR = '/path/to/kc_l'
OLD = os.path.join(MIR, 'data/v3/runs/v3_20260812/packets/kc_packets.jsonl')
NEW = os.path.join(MIR, 'v3/logs/probe_v22_packets.jsonl')

UNITS = [
    'KC_CLF_DT_011', 'KC_EVAL_IMBAL_006', 'KC_CLF_DT_010', 'KC_CLU_EVAL_008',
    'KC_CLU_EVAL_011', 'KC_CLF_UND_002', 'KC_CLF_UND_005', 'KC_CLU_DBS_002',
]

# known contaminating substrings pulled from the earlier manual evaluation / evidence audit
KNOWN_BAD = {
    'KC_EVAL_IMBAL_006': ['one-sided hypothesis test', 'critical value'],
}


def load(path):
    out = {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            uid = row.get('kc_id') or row.get('knowledge_unit_id') or row.get('id')
            out[uid] = row
    return out


def evidence_texts(row):
    ev = row.get('evidence_for_synthesis') or []
    texts = []
    for e in ev:
        if isinstance(e, dict):
            t = e.get('text') or ''
        else:
            t = str(e)
        texts.append(t)
    return texts


def evidence_meta(row):
    ev = row.get('evidence_for_synthesis') or []
    return [(e.get('evidence_id'), e.get('score_for_packet'), e.get('admission_basis')) for e in ev if isinstance(e, dict)]


def main():
    old = load(OLD)
    new = load(NEW)
    print('old rows:', len(old), 'new rows:', len(new))
    print()
    for uid in UNITS:
        o = old.get(uid)
        n = new.get(uid)
        print('=' * 100)
        print(uid)
        if o is None:
            print('  MISSING from old packets')
            continue
        if n is None:
            print('  MISSING from probe rebuild -- NOT YET PRESENT / job may still be writing')
            continue
        ot = evidence_texts(o)
        nt = evidence_texts(n)
        ochars = sum(len(x) for x in ot)
        nchars = sum(len(x) for x in nt)
        print('  passages: old=%d new=%d   chars: old=%d new=%d  (%.1f%% of old)' % (
            len(ot), len(nt), ochars, nchars, 100.0 * nchars / max(ochars, 1)))

        old_by_id = {e.get('evidence_id'): e for e in (o.get('evidence_for_synthesis') or []) if isinstance(e, dict)}
        new_by_id = {e.get('evidence_id'): e for e in (n.get('evidence_for_synthesis') or []) if isinstance(e, dict)}
        for eid, oe in old_by_id.items():
            ne = new_by_id.get(eid)
            a = oe.get('text') or ''
            if ne is None:
                print('    evidence_id=%s DROPPED ENTIRELY (old_len=%d)  basis=%s score=%.3f' % (
                    eid, len(a), oe.get('admission_basis'), float(oe.get('score_for_packet') or 0)))
                print('      OLD: %s' % a[:300].replace('\n', ' '))
                continue
            b = ne.get('text') or ''
            if a != b:
                removed = len(a) - len(b)
                print('    evidence_id=%s text changed: old_len=%d new_len=%d removed_chars=%d' % (
                    eid, len(a), len(b), removed))
                print('      OLD: %s' % a[:300].replace('\n', ' '))
                print('      NEW: %s' % b[:300].replace('\n', ' '))
        for eid in new_by_id:
            if eid not in old_by_id:
                print('    evidence_id=%s NEW (not in old set)' % eid)
        if len(ot) != len(nt):
            print('    passage COUNT changed: old=%d new=%d' % (len(ot), len(nt)))
        # known bad substrings
        for needle in KNOWN_BAD.get(uid, []):
            in_old = any(needle.lower() in t.lower() for t in ot)
            in_new = any(needle.lower() in t.lower() for t in nt)
            print('    known-bad %r : was_in_old=%s still_in_new=%s%s' % (
                needle, in_old, in_new, '  <-- STILL CONTAMINATED' if in_new else (
                    '  -- REMOVED (fix worked)' if in_old else '')))
        if nchars < 0.3 * ochars:
            print('    !!! evidence collapsed to <30% of original size -- possible over-stripping ("choking")')
        print()


if __name__ == '__main__':
    main()
