# 58. Reconciling an external content review of r3 against this audit

An expert review of `r3_kc_drafts_qwen38_27b.jsonl` was carried out against the three textbooks
rather than against status labels, packet counts or retrieval scores. This records what it found,
what this audit had already found independently, what it found that this audit had missed, where
it proved this audit wrong, and what each of its findings turns out to be **mechanically** once
traced to a cause.

Written for future reference, not as a summary for anyone. Every number here is reproducible from
a script in `_int14/`, `_int16/`, `_int17/` or `_taxonomy/`.

## Version note

The review is of **r3**. r4 (job 1682935) ran afterwards with the INT-14 acceptance rule live,
against the same packets. Its findings therefore split in two: the ones about repaired abstentions
are already closed by r4, and the ones about packet content still stand, because r4 changed no
packets.

## Independent convergence

The review's section 4 lists four drafts that are "really abstention explanations and should not be
counted as usable KC content": Multi-class Confusion Matrix, Bushy Decision Tree (Multi-split),
Models of Randomness (Approach 1) and (Approach 2).

Those are **exactly** the four units INT-14's substance rule rejects. This audit reached them by
reading `repair_attempted` rows; the review reached them by reading the drafts against the
textbooks. Two methods with no shared input, same four units. r4 reverts all four to `abstained`
and changes nothing else.

The review's headline claim, that a `grounded` label is not a correctness signal, is directly
checkable in the data and holds:

- `External Index: Purity` is **grounded**, and its formula omits the `/m` normalisation.
- `External Index: Recall` is **grounded**, and its own body says `m_ij` is undefined.

## Where the review proved this audit wrong

INT-14 **kept** `Classification Threshold (Cutoff)`. Doc 56 called it "the weakest keep" and
shipped it anyway. The review lists it as a must-repair, and it is right: the body defines the
term as "a value chosen for a model, as indicated by the instruction to 'choose the cutoff
threshold'", which defines nothing.

The rule tests for claims that the evidence is ABSENT. This draft instead quotes the source as its
definition. Same defect, different shape, not covered. Recorded as a known gap; not patched onto
this instance.

## What each finding is, mechanically

Tracing each category to a cause rather than accepting the category:

### External Index: Entropy is a retrieval miss, not lost local context

Its packet received **zero of the 42 corpus blocks** that define `p_ij`/`m_ij`, including the
textbook's own "Entropy: The degree to which each cluster consists of objects of a single class".
Its nine admitted passages are two generic "external structure" sentences, one statistical-testing
sentence, and six decision-tree entropy rows.

`Entropy (Node)` and `Shannon Entropy (Uncertainty Measure)` are both already in this unit's
`rival_units_considered`. The rival contest did not move the passages because the cross-encoder
margin (`CLAIM_MARGIN = 0.08`) was not cleared. Lowering that margin globally is the threshold
relaxation this audit has refused throughout.

### The p_ij / m_ij cases are two different problems

`_int16/diag_where_clause.py` over every packet:

```
    501  successor is not a qualifier
     12  qualifier carries no symbols
      9  formula has no successor block
      7  qualifier LEFT BEHIND
      3  qualifier ALREADY admitted
```

For **7 units** the symbol glossary is the block immediately after an admitted formula and is
simply not admitted: Information Gain, Precision, Significance Level (alpha), Redundant
Attributes, Pearson Product-Moment Correlation, Covariance, Information Gain (Feature Goodness).
Nothing in the pipeline admits the block AFTER a formula; `lead_in_payload` admits the block after
a promise. This is its mirror and is the fourth sibling of three existing payload branches.

For **External Precision / Recall / Entropy** the definition sits elsewhere in the corpus
entirely, so adjacency cannot reach it. Different problem, same symptom.

### External Purity's missing /m is extraction bar-loss

The corpus row is `purity=∑i=1Kmimpurity(i)`: `m_i/m` lost its bar and became `mim`.
`math_rendering_damaged` returns **False** on it. Same defect class as INT-11's Bayes case, in a
form the detector misses. See the rejected interventions below for why it stays that way.

### SFG / SBG / Non-Deterministic Search is a taxonomy defect, not a pipeline defect

The hierarchy puts all seven under one parent, `Feature Set Generation Algorithms`:

```
Bidirectional Generation (BG)          direction
Random Generation (RG)                 direction
Sequential Backward Generation (SBG)   direction
Sequential Forward Generation (SFG)    direction
Exhaustive Search                      strategy
Heuristic Search                       strategy
Non-Deterministic Search               strategy
```

The source does not agree. It puts the first group under **7.2.1.1 Search Directions** and the
second under **7.2.2 Selection Criteria** / **7.4 Description of the Most Representative Feature
Selection Methods**. Presented as peers by the taxonomy, they read as alternatives of one kind, and
a drafter calling SFG "a heuristic method" is being faithful to the hierarchy it was given.

No retrieval or drafting change can repair this: the units are siblings by construction. See
doc 59 for the detector this motivated.

## Interventions this produced

Four, in descending order of evidential support. Numbers are measured, not estimated.

| id | intervention | side | evidence |
|---|---|---|---|
| INT-16 | admit the qualifier block after a formula | retrieval | 7 units, 7 qualifiers left behind |
| INT-17 | `SYMBOL_STATED_AS_UNDEFINED` | verification, flag-only | 3 hits, all 3 are the review's cases |
| INT-18 | per-unit source provenance | reporting | review section 6 |
| doc 59 | taxonomy conflation report | taxonomy audit | 2 flags, 1 real |

`SYMBOL_STATED_AS_UNDEFINED` measured over all 159 r3 drafts: **3 hits, zero false positives**, and
they are precisely External Index: Entropy, Precision and Recall, one of them labelled `grounded`.
The drafter is being honest and saying the glossary was missing; the check turns that self-report
into a pointer at a specific absent evidence row.

## Rejected on measurement

Recorded so none of them is attempted again without new evidence.

**Widening the bar-loss detector by repeated identifiers.** 74 rows flagged, roughly 60 legitimate
(`∑λᵢyᵢ`, `2x₁x₂`, and the word "non-empty"). Not usable.

**The narrow `X/(X+Y)` bar-loss signature.** 6 rows, **100% precision**: `TPR=TPTP+FN`,
`FPR=FPFP+TN`, `FNR=FNFN+TP`, `Precision=TPTP+FP`, and the relative-closeness formula twice.
Rejected anyway, and this is the important one: `math_rendering_damaged` is a **drop** predicate,
and `_int16/diag_narrow_twins.py` shows **none of the 6 has an intact twin**. Detecting them would
delete four core evaluation definitions and put nothing in their place. Detection without repair
is a regression here.

**Proving bar-loss by twin comparison** (strip every division marker, compare skeletons). 19
provable pairs in the whole corpus, **18 already caught**. Adds one row.

**Bar-loss detection on drafted text.** Zero hits over 159 drafts: the drafter re-renders formulas
rather than copying the damaged string, so the signature has no purchase there.

**Section headings as an ownership label.** In the document that matters most, five of nine
External Index: Entropy passages carry no heading at all and one "heading" is an exercise question
("4. Show that the entropy of a node never increases after splitting it"). Restricting to numbered
headings leaves 970 passages, 306 naming the holder and 150 naming only another unit, but reading
those 150 shows the label overcounts: a passage inside a section about X can legitimately support
Y. Usable as a feature, not as ground truth.

**Lexical name-in-text as an ownership label.** 545 `keep` and 105 `flip` pairs
(`_int17/build_ownership_eval.py`). The `keep` side is sound and is kept as a **safety** set. The
`flip` side is not: "Handling Missing Values in NB" holding a passage plainly about itself gets
labelled flip because its own compound name is not fully present. Systematically biased against
long-named units.

## Still open

The review's category C, completeness, has no mechanism here. ID3 says what family it belongs to
but not how it builds a tree; Ranker says it exists but not that it scores, sorts and cuts. This
needs a notion of what a unit type owes its reader, which is closer to the taxonomy than to the
pipeline, and inventing one from these examples would be fitting to them. Recorded, not attempted.
