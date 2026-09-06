# 72. Final state: r7

The frozen artifact. Packets `data/v3/runs/final_vnext_r7_20260821/`, drafts `r7_kc_drafts` and
`r7_topic_drafts` on Cluster A, code at HEAD (INT-20, INT-21, INT-22, INT-22b on top of INT-11..INT-19).

```
kc units      159        topic units 23
status        grounded 116   partial 30   abstained 13
suite         484 checks, 0 failed
```

## The external review's findings, as the final drafts state them

**Group Average Linkage - FIXED.** The review's clearest mathematical error was the draft calling
WPGMA's coefficients "constants independent of the cluster sizes" and then giving UPGMA's
size-dependent ones. The final draft:

> The weighted version of group average, known as WPGMA, uses coefficients that are constants
> independent of cluster sizes, specifically **alphaA = 1/2, alphaB = 1/2, beta = 0, and gamma = 0**.

Those are the textbook's WPGMA values. Fixed by INT-22, which removed the spliced row that had put
UPGMA's coefficients inside the sentence introducing WPGMA.

**Separation - FIXED.** The review said the draft invented a normalisation that is not the
textbook's graph-based definition. The final draft:

> separation(Ci, Cj) = proximity(ci, cj) ... separation(Y) = (1 / (|zeta| - 1)) * SUM
> d_N(center(Y), center(Y'))

Fixed by INT-21, which taught the defining-equation rescue to read through `\mathsf{...}` wrappers.

**Rand Index - FIXED.** "The index is calculated using the formula: Rand Index = (f11 + f00) /
(f11 + f10 + f01 + f00)." The unit whose apparently-missing formula started the investigation that
produced INT-20, INT-21 and INT-22. Its status moved partial -> grounded.

**Accuracy - FIXED**, status partial -> grounded, gaining the symbolic form INT-20 could not reach.

**Multi-class Confusion Matrix** now abstains rather than drafting an abstention explanation.

## What remains, and why

**External Index: Purity** still states `purity = SUM m_i purity(i)`, missing the `/m`. The
corpus's only rendering is bar-loss damaged with no intact twin; the row carrying the correct
`(m_i/m)` weighting is a candidate in the pool at rank 98 and falls below the cross-encoder floor.
Ceiling: no repair without inventing the formula, no admission without lowering the floor.

**External Index: Entropy** still states node entropy. The block carrying the whole cluster-entropy
definition reaches the pool at rank 105 and its members fall below the floor. Ancestor context in
the reranker query was tried twice before this audit and rejected on measurement. The corpus writes
the symbol as `e_i`, and inferring "Entropy -> e" collides with probability `p` versus Precision
`p`. Ceiling. See doc 61.

**Mutually Exclusive Classes** still defines rule sets - and is FLAGGED by INT-19. The corpus
defines mutually exclusive rule sets and never mutually exclusive classes, so this is a genuine
negative control the pipeline fails at the abstention stage and catches at the verification stage.
See doc 69.

**Chi-Squared** - the general degrees-of-freedom form exists in the corpus only as spliced content;
repairing that row would delete it. Ceiling.

**Classification Threshold** - a registry alias gap, not a pipeline defect: `aliases: []` while the
corpus says "score threshold" 58 times, and the substantive rows sit at ranks 964-1396.

## Hygiene sidecar over the final drafts

```
BODY_SENTENCE_NOT_COVERED_BY_LEDGER    278
STATED_ARITHMETIC_EVALUATED             17
SOURCE_META_COMMENTARY_IN_BODY           9
DUPLICATED_SENTENCE                      8
DEFINITIONAL_SUBJECT_IS_NOT_THE_UNIT     6
UNRENDERED_MARKUP_IN_BODY                5
```

The six INT-19 flags: Mutually Exclusive Classes ("rule set"), Conditional Probability
("concept"), Cluster Definition ("Sometimes a threshold"), External Index: Rand Index / Jaccard
("They"), Redundant Features ("common example"), Irrelevant Features ("attribute").

## A correction to how the A/B blast radius was reported

Every A/B in this audit counted "units changed" by comparing the admitted evidence TEXT. Comparing
the whole packet instead, r6 against r7:

```
units whose evidence TEXT differs : 33
units with ANY packet difference  : 152 / 159
sub-fields moving: support_profile_summary 1971, sentence_id 569, source_block_text 442,
                   text 442, relevance 420, patch_heading 330
```

A corpus-level repair changes the BM25 index globally, so scores and row identity move even where
admitted text does not. The correctness conclusions stand - no unit lost distinct content in any
A/B - but the reach of INT-11 and INT-22 was wider than the text-only counts implied, and any
future A/B on a corpus-level change should report both numbers.

## Reproducibility

Packet building is deterministic on fixed hardware: three builds on gpu01, identical admitted
evidence in all 159 units, only a float in `support_profile_summary` moving in 2. Across GPU
generations (A100 vs A30) one unit differs by one non-formula row.

Drafting is greedy (`temperature=0`, `top_p=1.0`) with a pinned seed. Two runs with DIFFERENT seeds
produced 159/159 byte-identical drafts, which verifies the greedy path end to end rather than
measuring sampling variance - there is none to measure.

So every A/B delta in this audit was measured against a floor of zero, and the "content noise floor
of 4 units" quoted in earlier commits and in docs 57 and 60 was a cross-hardware artefact. See
doc 68.
