"""INT-12 unit tests. Synthetic drafts only.

Each test states the property the check is meant to detect and, just as importantly, a NEGATIVE
case that must not be flagged. A hygiene check that fires on ordinary prose is worse than no check
at all: it trains a reviewer to ignore the sidecar.
"""
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SPEC = importlib.util.spec_from_file_location(
    "int12_draft_hygiene", os.path.join(_HERE, "int12_draft_hygiene.py"))
H = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(H)

FAILURES = []


def check(label, condition):
    print('  %-76s %s' % (label, 'ok' if condition else 'FAIL'))
    if not condition:
        FAILURES.append(label)


def checks_of(findings, name):
    return [f for f in findings if f['check'] == name]


print('sentence splitting')
check('a multi-sentence body splits on terminal punctuation',
      len(H.split_sentences('One thing is true. Another thing is also true.')) == 2)
check('a decimal number does not split a sentence',
      len(H.split_sentences('The value is 0.75 for this measure.')) == 1)
check('paragraph breaks separate sentences',
      len(H.split_sentences('First para.\n\nSecond para.')) == 2)

print('A: source meta-commentary')
meta = H.find_source_meta_commentary(H.split_sentences(
    'The source rendering of the formula is incomplete in the provided passages.'))
check('a sentence about the rendering of the evidence is flagged', len(meta) == 1)
check('a sentence about the subject is not flagged',
      H.find_source_meta_commentary(H.split_sentences(
          'The measure is defined as the ratio of true positives to predicted positives.')) == [])
check('an ordinary mention of evidence in a subject sentence is not flagged',
      H.find_source_meta_commentary(H.split_sentences(
          'Bayes theorem combines prior belief with the evidence observed.')) == [])
check('"does not provide" about the evidence is flagged',
      len(H.find_source_meta_commentary(H.split_sentences(
          'The evidence does not provide a step-by-step procedure.'))) == 1)
# Real false positive from the first run over the 159 drafts: "rendering" as a verb meaning
# "making", plus "evidence" as subject matter, in a sentence that is entirely about the topic.
check('"rendering X impossible ... other evidence" is NOT flagged',
      H.find_source_meta_commentary(H.split_sentences(
          'This wipes out the entire class product, rendering the class impossible to predict '
          'regardless of other evidence.')) == [])
check('a clause boundary between subject and predicate blocks the match',
      H.find_source_meta_commentary(H.split_sentences(
          'The evidence is clear. The formula is incomplete only in one variant.')) == [])

print('B: ledger coverage')
CLAIMS = ['The silhouette coefficient compares within-cluster distance to nearest-cluster distance.',
          'A positive silhouette value indicates good assignment.']
covered = H.find_uncovered_body_sentences(
    ['The silhouette coefficient compares within-cluster distance to nearest-cluster distance.'],
    CLAIMS)
check('a sentence restating a ledger claim is not flagged', covered == [])
uncovered = H.find_uncovered_body_sentences(
    ['The relationship is symmetric and both points belong to the same cluster.'], CLAIMS)
check('a sentence with no corresponding ledger claim is flagged', len(uncovered) == 1)
check('the flag reports the coverage and which words were absent',
      uncovered and uncovered[0]['ledger_coverage'] < H.LEDGER_COVERAGE_FLOOR
      and 'symmetric' in uncovered[0]['words_absent_from_ledger'])
check('a sentence COMBINING two ledger claims is not flagged',
      H.find_uncovered_body_sentences(
          ['The silhouette coefficient compares within-cluster distance to nearest-cluster '
           'distance, and a positive value indicates good assignment.'], CLAIMS) == [])
check('a very short sentence is not judged on an overlap ratio',
      H.find_uncovered_body_sentences(['It is zero.'], CLAIMS) == [])
check('an empty ledger flags substantive sentences rather than crashing',
      len(H.find_uncovered_body_sentences(
          ['The measure compares within-cluster distance to nearest-cluster distance.'], [])) == 1)

print('C: self-reference and duplication')
circular = H.find_self_referential_sentences(
    ['The confusion matrix is a fundamental tool and it is used to construct the confusion '
     'matrix and evaluate classifiers.'], 'confusion matrix')
check('a term defined by restating itself is flagged', len(circular) == 1)
check('a single mention of the unit name is not flagged',
      H.find_self_referential_sentences(
          ['The confusion matrix summarises four counts.'], 'confusion matrix') == [])
check('two mentions without a definitional verb between them are not flagged',
      H.find_self_referential_sentences(
          ['A confusion matrix differs from a multi-class confusion matrix.'],
          'confusion matrix') == [])
# Real false positives from the first run: ordinary prose that mentions the unit twice.
check('"X is an estimate ... not the exact true X" is NOT flagged',
      H.find_self_referential_sentences(
          ['Accuracy is an estimate based on a finite test set and is not guaranteed to be the '
           'exact true accuracy of a classifier.'], 'Accuracy') == [])
check('"X is related to Y ... X = 1 - Y" is NOT flagged',
      H.find_self_referential_sentences(
          ['Precision is closely related to the false discovery rate, with the relationship '
           'expressed as precision = 1 - FDR.'], 'Precision') == [])
check('"X is used to select ... by minimizing the weighted average X" is NOT flagged',
      H.find_self_referential_sentences(
          ['The Gini index is used to select the best split by minimizing the weighted average '
           'Gini index of the child nodes.'], 'Gini index') == [])
dup = H.find_duplicated_sentences([
    'Accuracy counts every correct prediction made by the model.',
    'Accuracy counts every correct prediction made by the model.'])
check('an exactly repeated sentence is flagged', len(dup) == 1 and dup[0]['occurrences'] == 2)
check('two different sentences are not flagged as duplicates',
      H.find_duplicated_sentences(['Precision uses predicted positives here.',
                                   'Recall uses actual positives instead.']) == [])

print('D: unrendered markup')
check('LaTeX macros in the body are flagged',
      len(H.find_unrendered_markup([r'The density is { \frac { 1 } { \sqrt { 2 \pi } } }.'])) == 1)
check('display delimiters in the body are flagged',
      len(H.find_unrendered_markup(['$$ P ( y ) $$'])) == 1)
check('a readable formula is not flagged',
      H.find_unrendered_markup(['Precision = TP / (TP + FP).']) == [])

print('E: stated arithmetic')
arith = H.find_stated_arithmetic(['The estimate for this tree is 0.3 + 2 * 5.'])
check('a closed numeric expression is evaluated', len(arith) == 1)
check('the reported value is correct', arith and abs(arith[0]['value'] - 10.3) < 1e-9)
check('a plain number is not treated as an expression',
      H.find_stated_arithmetic(['The accuracy was 0.75 on the test set.']) == [])
check('the evaluator handles the middle-dot multiplication sign',
      abs(H.evaluate_arithmetic('2 - 1 - 0.5') - 0.5) < 1e-9)
check('division by zero yields no value rather than an exception',
      H.evaluate_arithmetic('1/0') is None)
check('a non-arithmetic string yields no value',
      H.evaluate_arithmetic('__import__("os")') is None)
check('names are refused even when they would evaluate',
      H.evaluate_arithmetic('len') is None)

print('end to end')
draft = {
    'contextual_kc_draft': {
        'text': 'Recall measures the fraction of actual positives found. '
                'The source rendering of the formula is incomplete. '
                'The relationship is symmetric across every pair.'},
    'evidence_map': [{'claim': 'Recall measures the fraction of actual positives found.'}],
}
body, claims = H.draft_body_and_claims(draft)
found = H.hygiene_findings('Recall', body, claims)
check('the meta-commentary sentence is reported', len(checks_of(found, 'SOURCE_META_COMMENTARY_IN_BODY')) == 1)
check('the unledgered sentence is reported',
      any(f['sentence'].startswith('The relationship is symmetric')
          for f in checks_of(found, 'BODY_SENTENCE_NOT_COVERED_BY_LEDGER')))
check('the ledgered sentence is not reported as uncovered',
      not any(f['sentence'].startswith('Recall measures')
              for f in checks_of(found, 'BODY_SENTENCE_NOT_COVERED_BY_LEDGER')))
check('a topic draft is read from its own field',
      H.draft_body_and_claims({'contextual_topic_draft': {'text': 'x'}})[0] == 'x')

print()
if FAILURES:
    print('FAILED %d check(s):' % len(FAILURES))
    for f in FAILURES:
        print('   - %s' % f)
    sys.exit(1)
print('INT-12 UNIT TESTS: ALL PASS')
