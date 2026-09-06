# 50. Semantic assessment of all 159 KC drafts

Doc 49 read 15 drafts against full evidence. This reads **all 159** drafts and ledgers, with
evidence pulled for every claim that looked wrong. Extraction (`_semantic_read/dump_all.py`, SLURM
248815) only laid draft beside source; every judgement below is a reading, not a classifier.

Doc 49's methodological correction applies throughout: `patch_heading` and `source_block_text`
carry real assertive content, so "unsupported" here means checked across all three text fields.

---

## D1. Source meta-commentary inside the unit body — ~12 units

The draft narrates the condition of its own evidence in the text that downstream consumers read.

- `Confidence Interval for Accuracy` — a whole paragraph: "The source rendering of the defining
  formula ... is incomplete and unreadable in the provided passages."
- `Threshold Effect on Precision, Recall, F1` — a whole paragraph beginning "The evidence provided
  does not contain a specific formula or procedure for calculating F1 ..."
- `K-Means Complexity` — **two of its seven ledger claims are about the document**: "The K-means
  algorithm has a time complexity, though the specific value is not fully rendered in the provided
  text" and "The analysis ... follows a detailed consideration of the steps ...".
- `External Index: Entropy` — a ledger claim "An alternative formula rendering is ..., which is
  incomplete or garbled".
- Also `Misclassification Rate`, `ID3 Algorithm`, `Specificity`, `Rand Index`, `External Index:
  Precision`, `Properties of a Similarity Function`, `Attribute/Variable Types` ("The source
  material defines..."), `Comparing Two Models` ("This unit focuses on...").

This belongs in `uncertainty_notes`, where it already appears. A Knowledge Library unit consumed
for dialogue segmentation should describe the concept, not the state of its sources.

## D2. A unit's defining formula routed to a sibling's packet — 3 verified

Verified exhaustively across `text`, `source_block_text` and `patch_heading` of every item in both
packets:

| unit missing it | says | where the formula actually is |
|---|---|---|
| `Euclidean Distance` | "not explicitly written out in the evidence" | `Cosine Similarity` item 02, boxed and complete |
| `Chi-Squared Test` | "exact mathematical formula ... not explicitly written out" | `Redundant Attributes`, with o_ij, e_ij and all symbols defined |
| `External Index: Precision` | "does not specify the underlying formula for calculating pij" | `External Index: Purity` defines p_ij = m_ij / m_i |

In each case the two units are siblings whose content shares a source page. `Euclidean Distance`
draws three items from that same page — including the **Manhattan** worked example — but not the
boxed Euclidean formula on it.

Consequence in the draft: `Euclidean Distance` states the 2D special case as the definition, and
`External Index: Precision` defines precision as `precision(i,j) = p_ij` without p_ij ever being
defined.

## D3. Lead-in admitted without its payload — 6+ units

Already doc 48's top candidate; the full read raises its severity.

- `Bayes' Theorem` — **six** pointers at the theorem (`"...which is known as Bayes theorem:"`,
  `"By Bayes' theorem, we have"`, `"Using the Bayes Theorem, we can"`, ...) and no payload. The
  unit's only equation is a PPCA proportionality from a different book.
- `Group Average Linkage` — the WPGMA payload never arrives, and the UPGMA formula floats into the
  WPGMA sentence, producing a draft that says the coefficients are "constants independent of
  cluster sizes" and then writes coefficients made of cluster sizes. Factually wrong.
- `Specificity`, `RIPPER Rule Induction`, `Confidence Interval for Accuracy`, `Rand Index`.

`Confidence Interval for Accuracy` propagates the defect verbatim: a paragraph of its body **ends
on a dangling lead-in colon** — "the confidence interval for acc can be derived as follows:" — with
no formula after it.

## D4. Body claims not covered by the ledger — systemic, and it bounds INT-2

STEP 3 says fill `evidence_map` first; STEP 4 says write "using only claims that appear in
evidence_map". Nothing enforces the second.

- `Density-Connected` (**grounded**, empty uncertainty_notes) asserts "The relationship is
  symmetric" and "they belong to the same cluster". Whole-packet search: `symmetric` 0 occurrences,
  `same cluster` 0 occurrences. Neither is in its 5-claim ledger.
- `Silhouette Coefficient` — the subcluster sentence is source-supported but unledgered.
- `Optimistic Error Estimate`, `Split Information` (introduces `k` and "log k" with no ledger
  entry and inconsistent with its own `p`), `NB Classification Phase`.

**INT-2 verifies entailment per ledger entry against that entry's `evidence_ids`. A body sentence
that never entered the ledger is invisible to it.** The verifier's coverage is bounded by the
model's own honesty about what it claimed.

## D5. Vacuous, circular or degenerate prose in `grounded` drafts — ~6

- `Confusion Matrix` — "The confusion matrix is a fundamental tool ... and it is used to **construct
  the confusion matrix**"; the sentence "The confusion matrix is also used in the context of
  evaluating classification performance where ..." appears twice.
- `Accuracy` — "In binary classification, accuracy can be 0 or 1 depending on the predictions"
  (true of any metric in [0,1]); "A higher raw accuracy alone is not always a significant win; a
  raw accuracy difference is not automatically a significant win" (same claim twice in one
  sentence).
- `Target Attribute` — "The target attribute is a central concept in data mining, and its proper
  understanding is essential for the development of effective data mining models." Pure filler,
  **entered in the ledger citing five evidence ids, none of which support it**. The same draft
  turns a parenthetical into "The target attribute is a key component in the bias-variance
  decomposition" and conflates a patch heading ("3.5 Model Selection") with Naive Bayes content.
- `K-Means Limitations` — disconnected exercise fragments, one claim repeated.
- `NB Classification Phase` — replaces the source's actual tie rule ("would assign the instance to
  class 1") with the contentless "based on the defined tie-breaking rule".

## D6. Damaged math reproduced as a valid result — 2

- `Pessimistic Error Estimate` — "the pessimistic error estimate for a specific tree TL is
  calculated as **0.3 + 2 · 5**". That is 10.3; an error estimate cannot exceed 1. A lost
  denominator passed the math-damage guards and was restated as a finished calculation, and the
  coverage notes repeat it as if valid.
- `NB for Numerical Attributes` — the body carries raw spaced LaTeX
  (`{ \frac { 1 } { { \sqrt { 2 \pi } } \sigma _ { i j } } }`) while `Conditional Probability`
  renders the *same* formula readably. Inconsistent rendering across units.

## D7. Scope creep and cross-unit duplication — systemic

- `Redundant Attributes` — **42 ledger claims** (median ~8). Absorbs the chi-squared test, the
  Pearson coefficient, `Data Integration` verbatim, and how seven different classifiers handle
  redundancy.
- `Binary Decision Tree` — a third of it is the `Overfitting` unit, whose definition sentence
  appears verbatim in at least three drafts.
- `Majority Voting` covers Random Forest and k-NN; `Cost Matrix` and `Cost-Sensitive
  Classification` share the M3 example and method list; `ROC Curve` and `ROC Space` overlap heavily.

## D8. Unit name vs content mismatch — 1

`Mutually Exclusive Classes` is drafted entirely about mutually exclusive **rules**. Every claim is
sourced and correct; none is about classes.

---

## What is working (unchanged from doc 49, now confirmed at scale)

- **Refusal of damaged math where guards fired**: AUC, Ensemble Classifier, Boosting, Bootstrap
  Sampling all declined garbled formulas and named the gap.
- **Abstention discipline**: 14 abstentions, all defensible. `Multi-class Confusion Matrix` cites
  the sibling rule explicitly; `Bushy Decision Tree` reasons that a decision stump is a *single*-split
  tree and therefore cannot establish a multi-split unit; `Querying Phase`, `Evaluation Workflow`,
  `McNemar Test`, `Models of Randomness 1/2`, `Informative Missingness`, `Cost-Based Model
  Selection` all correctly refuse fragmentary or off-subject evidence.
- **INT-1 visible end-to-end**: `Misclassification Rate` reasons about
  `not_assertable_interrogative`; `Mutually Exclusive Classes` ignores its flagged interrogative.
- **INT-7 formulas landed**: `r_s = ρ(R(X), R(Y))`, `Sensitivity = TP/(TP+FN)`.
- **Hard reconstructions correct**: Shannon Entropy recovered its summation and read "1020" as
  10/20; Silhouette transcribed five formulas faithfully; `Purity`, `Cohesion`, `Ward's Method`,
  `k-Fold Cross Validation`, `Random Forest`, `Cluster Definition` are clean, complete and accurate.
- **Misconception discrimination**: Naive Independence Assumption used the *correction* of a quoted
  student misconception, not the misconception.
- **Rival discrimination**: `Recall` ignored cluster-external recall; `Density-Connected` ignored
  the bisecting-K-means numbers sharing its page.

## Repair plan

| id | defect | side | risk |
|---|---|---|---|
| INT-11 | D3 lead-in without payload | retrieval | needs A/B + rebuild |
| INT-12 | D2 defining formula routed to sibling | retrieval | needs A/B + rebuild |
| INT-13 | D1 meta-commentary in body | verification, flag-only | none |
| INT-14 | D4 body not covered by ledger | verification, flag-only | none |
| INT-15 | D5 vacuous / circular / duplicated claim | verification, flag-only | none |
| INT-16 | D6 impossible numeric, raw LaTeX in body | verification, flag-only | none |

D7 and D8 are not repaired: both are consequences of the unit taxonomy itself (what counts as a
unit, and what its name promises), which is an input to the pipeline rather than something the
pipeline can decide. Recorded as a taxonomy-level finding.

Every rule above is stated without reference to any Data Mining KC.
