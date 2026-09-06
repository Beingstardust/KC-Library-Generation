# 52. INT-12: draft hygiene checks

Flag-only, additive sidecar, never rewrites a draft. Repairs four of the eight defect classes in
doc 50 that live in the drafted TEXT rather than in retrieval: D1 meta-commentary, D4 body
sentences outside the ledger, D5 vacuous or circular prose, D6 damaged math presented as a result.

## Why one module rather than four scripts

The five checks share one input (a draft and its ledger), one traversal (sentence segmentation)
and one output contract. Four scripts would duplicate that boilerplate four times without
separating any concern. INT-6 already implements two checks in one file for the same reason.

## The checks

| id | what it detects |
|---|---|
| `SOURCE_META_COMMENTARY_IN_BODY` | the unit narrates the condition of its evidence instead of describing its subject |
| `BODY_SENTENCE_NOT_COVERED_BY_LEDGER` | a body sentence whose content is absent from `evidence_map` |
| `SELF_REFERENTIAL_SENTENCE` | a term explained by naming itself as what it produces |
| `UNRENDERED_MARKUP_IN_BODY` | extraction markup that reached the drafted text |
| `STATED_ARITHMETIC_EVALUATED` | a reviewer aid: closed numeric expressions are evaluated and reported |

`BODY_SENTENCE_NOT_COVERED_BY_LEDGER` exists for a specific structural reason. INT-2 verifies
entailment **per ledger entry**, so a body sentence that never entered `evidence_map` is invisible
to it. The drafting instruction's STEP 4 says to write using only claims that appear in the
ledger, and nothing enforces it. This check bounds that blind spot; it does not second-guess the
prose.

`STATED_ARITHMETIC_EVALUATED` assumes no bound and uses no subject knowledge. It simply shows the
reviewer what a drafted expression evaluates to, which is how `errp(T_L) = 0.3 + 2 * 5` was found
being presented as an error estimate. The evaluator parses and walks the AST rather than calling
`eval()`: the input is model-generated text, and an evaluator that accepts more than arithmetic on
literals is an arbitrary-code path.

## Precision was measured, not assumed

Every check was run over the real 159 drafts, the findings were read, and each check was tightened
until its output was worth a reviewer's attention. Every false positive observed is now a
regression test.

```
check                                 first run   after tightening
SOURCE_META_COMMENTARY_IN_BODY            12            11   all true positives
SELF_REFERENTIAL_SENTENCE                 21             1   20 were ordinary prose
BODY_SENTENCE_NOT_COVERED_BY_LEDGER      404           239   see below
UNRENDERED_MARKUP_IN_BODY                  2             2
STATED_ARITHMETIC_EVALUATED               21            21   reviewer aid, not a defect claim
```

**Meta-commentary.** The first version tested for a source-referring subject and an
availability predicate independently, anywhere in the sentence. That flagged "...wipes out the
entire class product, **rendering** the class impossible to predict regardless of other
**evidence**", where "rendering" is a verb meaning "making" and "evidence" is subject matter. The
fix requires the subject to come FIRST with no clause boundary between them.

A second attempt used a 60-character window as a proxy for "same clause". That removed the false
positive but silently discarded real findings whose predicate sat further along - "The source
material indicates that ..., but the specific mathematical formula ... is not provided in the
supplied passages". Order and clause membership are now checked directly, with no distance cap.
Recall recovered from 6 to 11 with precision intact.

**Self-reference.** "Two mentions of the unit name with a definitional verb between them" flagged
`Accuracy is an estimate ... not guaranteed to be the exact true accuracy`, `Precision is closely
related to the false discovery rate ... precision = 1 - FDR`, and `The Gini index is used to
select the best split by minimizing the weighted average Gini index`. All three are ordinary
prose. Circularity is the narrower shape where the unit is the direct object of a verb that
PRODUCES or DEFINES it - "...is used to **construct** the confusion matrix". One finding remains,
and it is the real one.

**Ledger coverage.** Scoring each sentence against the best SINGLE claim flagged 404 sentences
across 125 of 159 units - a volume no reviewer can act on, and mostly composition: a body sentence
routinely combines two claims, so no single claim carries a majority of it. The ledger as a whole
is the support set, so coverage is now measured against the union of its claims. 239 remain, each
reporting which of its content words appear nowhere in the ledger.

## Arithmetic evaluator bug caught by its own test

The expression regex ended with a lookahead rejecting a following word character **or period**.
A sentence-final period therefore blocked the full match and the regex backtracked to a shorter
one: `0.3 + 2 * 5.` was reported as `0.3 + 2` = **2.3**, for an expression worth 10.3. A check that
shows a reviewer the wrong value is worse than no check. The guard now rejects only a following
digit, which is the narrowest thing that prevents cutting a number in half.

## Verification

36 unit tests on synthetic drafts, each pairing a positive case with the negative case that must
not fire. 12 regression guards in the suite (INT12-1..12); suite 379 -> 391 checks, 0 failed.

Sabotage audit: seven cases, each re-introducing one of the loosenings measured to misfire.

## Not repaired here

D7 (scope creep, cross-unit duplication) and D8 (unit name vs content mismatch) are consequences
of the unit taxonomy - what counts as a unit, and what its name promises - which is an input to
the pipeline rather than something the pipeline can decide. Recorded in doc 50 as a taxonomy-level
finding.
