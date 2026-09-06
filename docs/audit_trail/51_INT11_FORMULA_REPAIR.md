# 51. INT-11: repair a damaged formula from an intact twin

Repairs D3 in doc 50 - a lead-in admitted without its payload - at its root. Tracing the six
dangling Bayes' Theorem pointers showed the payload was **not a corpus gap**: the equation is in
the corpus immediately after its lead-in, with the fraction bar lost in extraction.

```
"4.11, which is known as Bayes theorem:"   ==>   "P(Y|X)=P(X|Y)P(Y)P(X). (4.11)"
```

`math_rendering_damaged()` correctly refuses that rendering, and `drop_damaged_math_passages()`
drops it. Correct behaviour - but the corpus also holds an intact rendering of the same equation
in a math-aware layer:

```
DOC_Guides_merged p31 mineru:   $$ P ( y | x ) = \frac { P ( x | y ) P ( y ) } { P ( x ) } .
```

## The mechanism already existed

`build_intact_formula_substitutions()` knows how to swap a damaged rendering for an intact one
under five gates: different extraction layer, same page, explicit fraction notation, survives the
damage checks, same normalised left-hand side, and the damaged right-hand side contained in the
replacement's. It was only ever called with the STRANDED-NUMERATOR set, and its search could not
look past the damaged row's own page.

Extending an exemption the codebase already contains, rather than inventing a mechanism, is the
same shape as INT-7.

## Three changes, one mechanism

1. **The twin search is factored out and shared** (`build_intact_twin_index`,
   `find_intact_formula_twin`), so the safety gates cannot drift between the stranded-numerator
   path and this one. The index is built once by left-hand side instead of rescanning a page list
   per damaged text.
2. **Locality becomes a named three-way property** (`SAME_PAGE`, `SAME_DOCUMENT`,
   `FOREIGN_DOCUMENT`) instead of a same-page boolean, with the corroboration rule stated
   explicitly in `twin_corroboration_is_sufficient()`.
3. **The repair is applied to the corpus once, before any index is built.** Retrieval, block
   assembly, the lead-in payload rescue and the drop passes then all read one consistent text.
   Repairing at the point of use would leave each of those paths to remember the repair
   separately, which is how the two math paths drifted apart in the first place.

## The corroboration rule is derived, not tuned

On the page, the page corroborates the match: two extraction layers read the same region and one
kept the fraction. Off the page there is no such corroboration and the equation text is the only
evidence the two rows are the same equation.

Measuring locality alone produced exactly one false match:

```
DAMAGED  "$$ M _ { 1 } = ( 0 ."          (truncated mid-number)
INTACT   "m1=m/3  a=0.05"                (an unrelated quantity in another book)
```

Its entire matched right-hand side was the character `0`, which the truncation left behind.
Requiring a non-local twin to match on a **symbolic** right-hand side blocks precisely that and
keeps every correct repair: both Bayes repairs match on `pxypypx`. The rule is a categorical
property of the match - is there any mathematics in what agreed - not a numeric threshold.

## Measured through the shipped functions

```
distinct damaged renderings in corpus : 1685
repairs clearing every gate           :   45   (53 corpus rows)
   same_page                          :   36
   same_document                      :    6
   foreign_document                   :    3
```

Repaired equations include:

```
Precision  = TP TP + FP              ->  \frac{TP}{TP + FP}
Recall     = TP TP + FN              ->  \frac{TP}{TP + FN}
Accuracy   = TP + TN TP + TN + FP+FN ->  \frac{TP + TN}{TP + TN + FP + FN}
Specificity= TN TN + FP              ->  \frac{TN}{TN + FP}
TPR, FPR                             ->  intact
GainRatio(A) = IG(A) SplitInfo(A)    ->  \frac{IG(A)}{SplitInfo(A)}
IG(A) = Entropy(D) -                 ->  the complete summation
eij = count(A=ai) count(B=bj)        ->  \frac{count(A=ai) count(B=bj)}{m}
RandIndex, JaccardCoefficient        ->  intact
silhouette(x) = b(x) - a(x) max(...) ->  \frac{b(x)-a(x)}{max(a(x),b(x))}
P(Y|X) = P(X|Y)P(Y)P(X)              ->  \frac{P(x|y)P(y)}{P(x)}
```

Those bar-losses were previously recorded as a ceiling. This single repair addresses the source
of six defects found by reading in doc 50: Bayes' Theorem, Rand Index, Gain Ratio, Information
Gain, the chi-squared expected-frequency term, and Silhouette.

## Provenance

A repaired row carries the rendering it replaced, the document, page and layer the replacement
came from, and the locality it was found at. That provenance travels onto the evidence item
through `repaired_formula_provenance()`, which reads across a passage's members because the
repaired row is frequently not the block's seed. A repair that cannot be inspected afterwards is
indistinguishable from a fabrication.

## Verification

24 unit tests on synthetic rows. 15 regression guards (INT11-1..15), four of them liveness guards
asserting the builder reaches the repair and reaches it **before** every index - a repair applied
after indexing is a repair retrieval never sees.

Sabotage audit: nine cases, all caught by their target guard, tree restored, suite green. The
audit also exposed three weaknesses in the harness and the guards themselves, fixed in `d120f4d`.

## A/B

Both arms in one SLURM job on one GPU, identical corpus, profiles, bm25 pool, max passages, max
chars and min relevance. The arms were materialised by `git archive` on the LOGIN node - git is
not on the compute nodes' PATH, and an in-job `git archive` fails in a way `tar` reports as a
malformed archive rather than as a missing command. The job verifies the arms rather than creating
them: different `evidence_pack.py` md5, arm A free of the intervention, arm B containing it.

### The noise floor, measured first

Arm A and the previous final run were built by the SAME commit, so anything separating them is
run-to-run variation - GPU tie-breaks in the reranker resolving differently - not an effect of the
intervention:

```
units whose item list differs : 6
of which the CONTENT differs  : 1     (ordering-only: 5)
item-count delta              : -1
```

Reporting the intervention's delta without this number would invite reading noise as signal.

### The intervention

```
                       before      after     delta
packets                   159  ->    159        +0
items                    2593  ->   2604       +11
chars                  783038  -> 784792     +1754
formula rows              620  ->    630       +10
DAMAGED rows                0  ->      0        +0
support states     151/4/4    ->  151/4/4   unchanged

units unchanged        : 146 / 159
units changed          :  13          (noise floor: 6, of which 1 content)
rows gained / lost     :  21 / 10
support-state moves    :   0
rows carrying a repair :  20          same_page 15, foreign_document 3, same_document 2
```

**Regression audit of every gained row: 21 of 21 clean.** No damaged mathematics, no structural
junk, and the damaged-row count in the packets is zero before and after.

### The ten lost rows are improvements

| unit | lost | why this is better |
|---|---|---|
| `Node Impurity`, `Misclassification Rate` | the truncated "Students often think entropy is the same as error rate." | superseded by the repaired longer rendering carrying the worked values |
| `Information Gain` | `[Foil's Information Gain]` | a bare heading, replaced by the GainRatio formula |
| `Specificity` | "Select an evaluation measure." | instructional filler |
| `Silhouette Coefficient` | `silhouette(s4) = 1 −2.1213` | a damaged worked value, replaced by the defining formula |
| `Precision` | `F(i,j)=(2×precision×recall)/(precision+recall)` | **the F-measure formula, which was never Precision's** |
| `Overfitting` | a garbled association-rule fragment, a dropout sentence | off-target either way |
| `Imputation` | two rows, one of which returns repaired | re-rendered, not lost |

### The one gained row that needed checking

`Overfitting` gained Bayes' theorem, which is off-target for that unit. Investigated rather than
waved through: the Overfitting packet ALREADY carried the Bayes lead-in ("...we are interested in
computing the probability of observing a class label y for a data instance...") and Bayes prose
about prior probability, admitted at `context_anchored_relevance` 0.622. INT-11 completed a
formula that was already half-present; it did not introduce new off-target content. The scope
creep is pre-existing, recorded as D7 in doc 50, and is a unit-taxonomy issue rather than a
retrieval one.

## Promotion: PASS

The signal is well clear of the noise floor, no support state moved, no damaged mathematics
entered any packet, every gained row is clean, and every loss is an improvement. Promoted.

The final KC packet set is arm B's output verbatim - `md5 c32399fd746014fbd68fd2d9b9f34c6b`,
identical on the primary compute cluster and on the drafting cluster - so the packets that were audited are the packets
that ship, rather than a second unaudited rebuild that merely ought to match. Topic packets were
rebuilt from them and match the previous run's structure (22 units, 6.68 mean children, all 22
carrying a definition, a formula and a procedure).

