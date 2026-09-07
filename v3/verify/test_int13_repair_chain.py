"""INT-13 unit tests: the content repair chain, and that the real drafting loop iterates it.

The defect being fixed is not a wrong rule, it is an UNREACHED one. Two repairs existed in the
runner with passing behaviour and never executed, because the loop that runs in production is the
schema-contract probe and it invoked repairs by name, one at a time. So these tests check both
halves: that the chain behaves, and that the probe consumes the chain rather than naming its
members.
"""
import importlib.util
import pathlib
import sys

V = '/path/to/shared'
sys.path.insert(0, V + '/src')

_spec = importlib.util.spec_from_file_location('dr_under_test', V + '/v3/pipeline/04_draft_runner.py')
DR = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(DR)

PROBE = pathlib.Path(V) / 'steps/step_06_7_kc_draft_generation/scripts/v2_chain/run_step67_v2_schema_contract_probe.py'
PROBE_SRC = PROBE.read_text(encoding='utf-8')

FAILURES = []


def check(label, condition):
    print('  %-78s %s' % (label, 'ok' if condition else 'FAIL'))
    if not condition:
        FAILURES.append(label)


def kc_packet(**over):
    packet = {
        'knowledge_unit_type': 'kc',
        'canonical_name': 'Silhouette Coefficient',
        'packet_support_state': 'draftable',
        'evidence_for_synthesis': [
            {'text': 'The silhouette coefficient compares the average distance from a point to '
                     'its own cluster with the minimum average distance to another cluster, and '
                     'is an internal validity measure.'},
            {'text': 'A silhouette coefficient close to one indicates a well assigned point.'},
        ],
    }
    packet.update(over)
    return packet


def draft(status='abstained', text=''):
    return {'contextual_kc_draft': {'status': status, 'text': text,
                                    'supporting_evidence_ids': []},
            'evidence_map': []}


print('the chain itself')
chain = DR.content_repair_chain()
check('the chain declares three repairs', len(chain) == 3)
check('in the documented order: abstention, damaged math, schema',
      [r.phase for r in chain] == ['invalid_abstention_content_repair',
                                   'damaged_math_content_repair', 'schema_repair'])
check('every predicate takes the same (packet, draft, issues) signature',
      all(r.needs_repair(kc_packet(), draft('grounded', 'x'), []) in (True, False)
          for r in chain))
check('every entry carries a prompt builder', all(callable(r.build_prompt) for r in chain))
check('phases are unique', len({r.phase for r in chain}) == 3)

print('the abstention repair fires where it should')
abst = chain[0]
check('an abstention on a draftable, on-target packet needs repair',
      abst.needs_repair(kc_packet(), draft('abstained'), []) is True)
check('a grounded draft does not', abst.needs_repair(kc_packet(), draft('grounded', 'x'), []) is False)
check('an abstention the packet EXPECTED does not',
      abst.needs_repair(kc_packet(abstention_expected=True), draft('abstained'), []) is False)
check('an abstention on a packet with no on-target evidence does not',
      abst.needs_repair(kc_packet(evidence_for_synthesis=[{'text': 'Select a search strategy.'}]),
                        draft('abstained'), []) is False)

print('repair_resolved is what stops a repair being accepted for being merely well-formed')
check('a parse error is never resolved',
      DR.repair_resolved(abst, kc_packet(), draft('grounded', 'x'), 'ValueError', []) is False)
check('outstanding validation issues are never resolved',
      DR.repair_resolved(abst, kc_packet(), draft('grounded', 'x'), '', [{'code': 'x'}]) is False)
check('a model that abstains AGAIN keeps its abstention (repair discarded)',
      DR.repair_resolved(abst, kc_packet(), draft('abstained'), '', []) is False)
check('a clean repair that clears the predicate is resolved',
      DR.repair_resolved(abst, kc_packet(), draft('grounded', 'x'), '', []) is True)

print('the production loop consumes the chain')
check('the probe calls content_repair_chain()', 'content_repair_chain()' in PROBE_SRC)
check('the probe uses repair_resolved rather than its own accept rule',
      'repair_resolved(' in PROBE_SRC)
check('the probe names NO individual repair predicate',
      not any(name in PROBE_SRC for name in
              ('should_attempt_schema_repair', 'invalid_abstention_needs_content_repair',
               'damaged_math_needs_content_repair')),
      )
check('the probe records which repair ran', '"repair_phase"' in PROBE_SRC)
# A hardcoded phase literal would mean the probe knows the chain's membership, which is the
# coupling that let two repairs be forgotten. Substring matching would be wrong here: the summary
# still emits the legacy contract keys "schema_repair_attempt_count" and
# "schema_repair_success_count", which are output-contract names, not phase literals.
check('the probe hardcodes no repair PHASE literal',
      not any(('"%s"' % r.phase) in PROBE_SRC or ("'%s'" % r.phase) in PROBE_SRC
              for r in chain))
check('the phase written onto a repaired row comes from the chain entry',
      'phase=repair.phase' in PROBE_SRC)

print()
if FAILURES:
    print('FAILED %d check(s):' % len(FAILURES))
    for f in FAILURES:
        print('   - %s' % f)
    sys.exit(1)
print('INT-13 UNIT TESTS: ALL PASS')
