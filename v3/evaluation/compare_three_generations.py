"""Compare packet quality across three generations: pre-v22, v23, and v24-v28 (current).

Three packet sets exist for the same 159 units, same corpus, same profiles:

    pre-v22   $DATA/_prefix_v22_backup/packets_prefix_backup/kc_packets.jsonl   (75.5% draft quality)
    v23       $DATA/_v23_baseline/packets/kc_packets.jsonl                     (67.9% draft quality - regression)
    current   $DATA/packets/kc_packets.jsonl                                    (v24-v28, not yet draft-evaluated)

This does not re-run the human review - that is the real test and hasn't happened on this
generation yet. It does what IS mechanically checkable right now: does the SPECIFIC evidence
that caused each of the 51 registered failures still exist, per generation, and did fixing it
strip evidence from units the review already accepted.
"""
import io
import json
import os
import re

MIR = '/path/to/kc_l'
DATA = os.path.join(MIR, 'data/v3/runs/v3_20260812')
REG = os.path.join(MIR, 'v3/evaluation/failure_register.jsonl')

GENS = [
    ('pre-v22', os.path.join(DATA, '_prefix_v22_backup/packets_prefix_backup/kc_packets.jsonl')),
    ('v23', os.path.join(DATA, '_v23_baseline/packets/kc_packets.jsonl')),
    ('current', os.path.join(DATA, 'packets/kc_packets.jsonl')),
]

CTRL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')


def load(path):
    out = {}
    if not os.path.exists(path):
        return out
    with io.open(path, encoding='utf-8') as f:
        for line in f:
            r = json.loads(line)
            out[r.get('kc_id') or r.get('knowledge_unit_id')] = r
    return out


def ev_text(row):
    return ' '.join((e.get('text') or '') for e in (row.get('evidence_for_synthesis') or []))


def norm(s):
    return re.sub(r'\s+', ' ', (s or '').lower().replace('\\', ' ').replace('$', ' '))


packets = {g: load(p) for g, p in GENS}
for g, p in GENS:
    print('%-10s %4d units   (%s)' % (g, len(packets[g]), 'MISSING' if not packets[g] else p.split('/')[-3]))
print()

# ================= 1. global stats =================
print('=' * 100)
print('GLOBAL EVIDENCE STATS')
print('=' * 100)
print('%-10s %8s %10s %10s %8s %8s %8s %8s %6s' % (
    'gen', 'units', 'mean_ch', 'total_ch', 'empty', 'ctrl_dmg', 'def', 'formula', 'proc'))
for g, _ in GENS:
    rows = list(packets[g].values())
    if not rows:
        continue
    chars = [len(ev_text(r)) for r in rows]
    ctrl_units = sum(1 for r in rows if any(CTRL.search(e.get('text') or '')
                     for e in (r.get('evidence_for_synthesis') or [])))
    has_def = sum(1 for r in rows if any('definition' in (e.get('shape_tags') or [])
                  for e in (r.get('evidence_for_synthesis') or [])))
    has_formula = sum(1 for r in rows if any('formula' in (e.get('shape_tags') or [])
                      for e in (r.get('evidence_for_synthesis') or [])))
    has_proc = sum(1 for r in rows if any('procedure' in (e.get('shape_tags') or [])
                   for e in (r.get('evidence_for_synthesis') or [])))
    print('%-10s %8d %10.0f %10d %8d %8d %8d %8d %6d' % (
        g, len(rows), sum(chars) / max(len(chars), 1), sum(chars),
        sum(1 for c in chars if c == 0), ctrl_units, has_def, has_formula, has_proc))
print()

# ================= 2. per-failure evidence check =================
reg = [json.loads(l) for l in io.open(REG, encoding='utf-8') if l.strip()]
print('=' * 100)
print('PER-FAILURE: is the SPECIFIC content that caused each failure still present, per generation?')
print('  probe = the passing/failing probe terms already recorded in the register')
print('=' * 100)

resolved = fixed_across = still_present = mixed = 0
rows_out = []
for r in reg:
    kc = r['kc_id']
    exp = r.get('probes_expected') or []
    wrong = r.get('probes_wrong') or []
    status = {}
    for g, _ in GENS:
        row = packets[g].get(kc)
        if row is None:
            status[g] = '(missing)'
            continue
        t = norm(ev_text(row))
        has_exp = sum(1 for p in exp if norm(p) in t)
        has_wrong = sum(1 for p in wrong if norm(p) in t)
        status[g] = 'exp=%d/%d wrong=%d/%d' % (has_exp, len(exp), has_wrong, len(wrong))
    rows_out.append((r['row'], r['canonical_name'], r['root_cause_refined'], status))

for row, name, cause, status in rows_out:
    print('row %3d  %-40s [%s]' % (row, (name or '')[:40], cause))
    for g, _ in GENS:
        print('    %-10s %s' % (g, status[g]))
print()

# ================= 3. targeted wins: did the claimed mechanisms actually fire? =================
print('=' * 100)
print('TARGETED MECHANISM CHECKS')
print('=' * 100)
checks = [
    ('KC_CLF_DT_008', 'Gain Ratio', 'garbled split-info gone',
     lambda t: 'entropy(parent)-' not in norm(t).replace(' ', '')),
    ('KC_EVAL_COMP_003', 'Sample Mean and Variance', 'formula payload present (v25)',
     lambda t: '\\frac' in t or '\\sum' in t),
    ('KC_CLU_SIM_003', 'Euclidean Distance', 'shattered radical gone',
     lambda t: 'euclidean distance = √' not in norm(t)),
    ('KC_CLU_EVAL_004', 'External Index: Precision', 'classifier TP/FP gone (v26)',
     lambda t: 'tp / (tp + fp)' not in norm(t).replace(' ', '') and 'tptp+fp' not in norm(t).replace(' ', '')),
]
# resolve real kc_ids by canonical_name since my guessed ids above may be off
by_name = {name: kid for kid, row in packets['current'].items() for name in [row.get('canonical_name')]}
for _guess_id, name, label, fn in checks:
    kid = by_name.get(name)
    if not kid:
        print('  [skip] %-42s (unit not found by name)' % name)
        continue
    print('  %-42s %s' % (name, label))
    for g, _ in GENS:
        row = packets[g].get(kid)
        t = ev_text(row) if row else ''
        ok = fn(t) if row else None
        print('      %-10s %s   (%d chars)' % (g, ('n/a' if ok is None else ('OK' if ok else 'FAIL')), len(t)))
print()

# ================= 4. choking check on ACCEPTED units =================
print('=' * 100)
print('CHOKING CHECK: units the human review ACCEPTED (not in the failure register)')
print('=' * 100)
flagged_ids = {r['kc_id'] for r in reg}
accepted = [kid for kid in packets['current'] if kid not in flagged_ids]
print('accepted units in current packet set: %d' % len(accepted))

deltas = []
for kid in accepted:
    a = packets['pre-v22'].get(kid)
    b = packets['current'].get(kid)
    if not a or not b:
        continue
    la, lb = len(ev_text(a)), len(ev_text(b))
    if la == 0:
        continue
    deltas.append((lb / la, la, lb, b.get('canonical_name')))
deltas.sort()
worst = [d for d in deltas if d[0] < 0.3]
print('accepted units retaining <30%% of pre-v22 evidence: %d / %d' % (len(worst), len(deltas)))
for ratio, la, lb, name in deltas[:12]:
    print('   %5.0f%%  %5d -> %5d   %s' % (ratio * 100, la, lb, name))
mean_ratio = sum(r for r, *_ in deltas) / max(len(deltas), 1)
print('mean retention across accepted units: %.0f%%' % (mean_ratio * 100))

went_empty = [kid for kid in accepted
             if packets['pre-v22'].get(kid) and ev_text(packets['pre-v22'][kid])
             and packets['current'].get(kid) and not ev_text(packets['current'][kid])]
print('accepted units that went from evidence to EMPTY: %d' % len(went_empty))
for kid in went_empty:
    print('   ', kid, packets['current'][kid].get('canonical_name'))
