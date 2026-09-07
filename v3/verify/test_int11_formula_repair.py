"""INT-11 unit tests: repairing a math-damaged rendering from an intact twin.

Synthetic rows only. Nothing here mentions a Data Mining unit, a document name or a corpus path,
so the tests state the RULE rather than re-asserting one run's output. The two shapes exercised
are the ones the corpus measurement showed matter: an equation whose fraction bar was lost, and a
row truncated to "= 0." whose normalised right-hand side proves nothing.
"""
import sys

sys.path.insert(0, '/path/to/shared')

from kc_l.retrieval_gate.evidence_pack import (  # noqa: E402
    FOREIGN_DOCUMENT, SAME_DOCUMENT, SAME_PAGE, apply_damaged_formula_repairs,
    build_damaged_formula_repairs, build_intact_formula_substitutions, build_intact_twin_index,
    find_intact_formula_twin, formula_twin_locality, repaired_formula_provenance,
    twin_corroboration_is_sufficient,
)

FAILURES = []


def check(label, condition):
    print('  %-72s %s' % (label, 'ok' if condition else 'FAIL'))
    if not condition:
        FAILURES.append(label)


def row(text, doc='D1', page=1, layer='pymupdf'):
    return {'sentence_text': text, 'doc_id': doc, 'page_index': page, 'layer': layer}


# A fraction bar lost between numerator and denominator: the symbols survive, the structure does
# not. This is the shape that made a unit's defining equation unusable.
BAR_LOST = 'P(Y|X)=P(X|Y)P(Y)P(X).'
INTACT = '$$ P ( y | x ) = \\frac { P ( x | y ) P ( y ) } { P ( x ) } .'
# A row cut off mid-number. Its right-hand side normalises to a bare "0", which is contained in
# almost any intact right-hand side and therefore cannot corroborate anything.
TRUNCATED = '$$ M _ { 1 } = ( 0 .'
UNRELATED_INTACT = 'M1 = m/3 + 0.05'

print('locality classification')
check('same page and document is SAME_PAGE',
      formula_twin_locality(row('a'), row('b')) == SAME_PAGE)
check('same document, other page is SAME_DOCUMENT',
      formula_twin_locality(row('a', page=1), row('b', page=9)) == SAME_DOCUMENT)
check('other document is FOREIGN_DOCUMENT',
      formula_twin_locality(row('a', doc='D1'), row('b', doc='D2')) == FOREIGN_DOCUMENT)

print('corroboration rule')
check('same page requires a DIFFERENT extraction layer',
      not twin_corroboration_is_sufficient(SAME_PAGE, 'pxypypx', 'mineru', 'mineru'))
check('same page accepts a different layer even for a bare numeral right-hand side',
      twin_corroboration_is_sufficient(SAME_PAGE, '0', 'pymupdf', 'mineru'))
check('away from the page a symbolic right-hand side is required',
      twin_corroboration_is_sufficient(SAME_DOCUMENT, 'pxypypx', 'a', 'b'))
check('away from the page a bare numeral right-hand side is refused',
      not twin_corroboration_is_sufficient(FOREIGN_DOCUMENT, '0', 'a', 'b'))
check('the layer is irrelevant once the twin is off the page',
      twin_corroboration_is_sufficient(FOREIGN_DOCUMENT, 'pxypypx', 'mineru', 'mineru'))

print('twin search')
corpus = [row(BAR_LOST, doc='D1', page=295, layer='pymupdf'),
          row(INTACT, doc='D2', page=31, layer='mineru'),
          row(TRUNCATED, doc='D3', page=17, layer='mineru'),
          row(UNRELATED_INTACT, doc='D4', page=1073, layer='pymupdf')]
index = build_intact_twin_index(corpus)
chosen, chosen_row, _agree = find_intact_formula_twin(
    BAR_LOST, corpus[0], index, allow_non_local=True)
check('a bar-loss rendering is matched to its intact twin in another document', chosen == INTACT)
check('the chosen twin reports where it came from',
      chosen_row is not None and chosen_row.get('doc_id') == 'D2')

chosen_local, _r, _a = find_intact_formula_twin(BAR_LOST, corpus[0], index, allow_non_local=False)
check('the same match is refused when the search is restricted to the page',
      chosen_local is None)

chosen_trunc, _r, _a = find_intact_formula_twin(
    TRUNCATED, corpus[2], index, allow_non_local=True)
check('a truncated row is NOT matched on its bare numeral right-hand side',
      chosen_trunc is None)

print('stranded-numerator path is unchanged')
same_page_corpus = [row('a(x) = s(x) n', doc='D1', page=5, layer='pymupdf'),
                    row('$$ a ( x ) = \\frac { s ( x ) } { n }', doc='D1', page=5,
                        layer='mineru')]
subs = build_intact_formula_substitutions(same_page_corpus, {'a(x) = s(x) n'})
check('a same-page cross-layer substitution still resolves by default', len(subs) == 1)
check('the default search does not reach another document',
      build_intact_formula_substitutions(corpus, {BAR_LOST}) == {})
check('the widened search does reach it when asked',
      build_intact_formula_substitutions(corpus, {BAR_LOST}, allow_non_local=True) != {})

print('repair application')
repairs = build_damaged_formula_repairs(corpus, index)
check('the bar-loss rendering is offered a repair', BAR_LOST in repairs)
check('the truncated rendering is not offered a repair', TRUNCATED not in repairs)
repaired, n = apply_damaged_formula_repairs(corpus, repairs)
check('exactly the repairable rows are rewritten', n == 1)
target = [r for r in repaired if r.get('formula_repaired_from_damaged_text')]
check('the repaired row now carries the intact text',
      len(target) == 1 and target[0]['sentence_text'] == INTACT)
check('the original rendering is retained for inspection',
      target[0]['formula_repaired_from_damaged_text'] == BAR_LOST)
check('provenance names the document the text came from',
      target[0]['formula_repaired_from_doc_id'] == 'D2')
check('provenance names the locality it was found at',
      target[0]['formula_repair_locality'] == FOREIGN_DOCUMENT)
check('rows without a repair are passed through untouched',
      all('formula_repaired_from_doc_id' not in r for r in repaired if r is not target[0]))
check('an empty repair map leaves the corpus alone',
      apply_damaged_formula_repairs(corpus, {}) == (corpus, 0))

print('passage-level provenance')
check('provenance is found on a non-seed member of the passage',
      repaired_formula_provenance([row('lead in:'), target[0]])
      .get('formula_repaired_from_doc_id') == 'D2')
check('a passage with no repaired member reports nothing',
      repaired_formula_provenance([row('a'), row('b')]) == {})

print()
if FAILURES:
    print('FAILED %d check(s):' % len(FAILURES))
    for f in FAILURES:
        print('   - %s' % f)
    sys.exit(1)
print('INT-11 UNIT TESTS: ALL PASS')
