"""Direct re-measurement of the original clusters 3 (DRAFTING_OMITTED, 16) and 4
(RETRIEVAL_PREEXISTING, 12) against the second human review, by canonical_name.

This was promised explicitly in the original failure-anatomy report ("re-measure after 1 & 2",
"probe first") and on this session's own todo list, and needs to be done against the ACTUAL
original membership lists, not a fresh loose re-bucketing of run 2's findings under similarly-named
tags - those are two different things and conflating them is exactly the kind of unverified claim
this project's discipline exists to prevent.
"""
import io
import json
import os

MIR = '/path/to/kc_l'
reg1 = [json.loads(l) for l in io.open(os.path.join(MIR, 'v3/evaluation/failure_register.jsonl'),
                                       encoding='utf-8') if l.strip()]
reg2 = [json.loads(l) for l in io.open(os.path.join(MIR, 'v3/evaluation/failure_register_run2.jsonl'),
                                       encoding='utf-8') if l.strip()]
run2_names = {r['canonical_name'] for r in reg2}

for cluster_tag, label in [('DRAFTING_OMITTED', 'Cluster 3: drafting omission'),
                           ('RETRIEVAL_PREEXISTING', 'Cluster 4: under-retrieval')]:
    members = [r for r in reg1 if r['root_cause_refined'] == cluster_tag]
    still_failing = [r for r in members if r['canonical_name'] in run2_names]
    resolved = [r for r in members if r['canonical_name'] not in run2_names]
    print('=' * 100)
    print('%s - original membership: %d' % (label, len(members)))
    print('=' * 100)
    print('STILL FAILING in run 2: %d / %d' % (len(still_failing), len(members)))
    for r in still_failing:
        r2 = next((x for x in reg2 if x['canonical_name'] == r['canonical_name']), None)
        print('   row%3d  %-42s  run2_status=%s' % (
            r['row'], r['canonical_name'], r2['fix_status'] if r2 else '?'))
    print()
    print('RESOLVED since run 1: %d / %d' % (len(resolved), len(members)))
    for r in resolved:
        print('   row%3d  %-42s' % (r['row'], r['canonical_name']))
    print()

print('=' * 100)
print('HEADLINE ANSWER')
print('=' * 100)
c3 = [r for r in reg1 if r['root_cause_refined'] == 'DRAFTING_OMITTED']
c4 = [r for r in reg1 if r['root_cause_refined'] == 'RETRIEVAL_PREEXISTING']
c3_still = sum(1 for r in c3 if r['canonical_name'] in run2_names)
c4_still = sum(1 for r in c4 if r['canonical_name'] in run2_names)
print('Cluster 3 (drafting omission):  %d/%d still failing (%d resolved)' % (
    c3_still, len(c3), len(c3) - c3_still))
print('Cluster 4 (under-retrieval):    %d/%d still failing (%d resolved)' % (
    c4_still, len(c4), len(c4) - c4_still))
