# 54. Final state after INT-11 and INT-12

Run `final_vnext_r2_20260820`. Packets are arm B of the INT-11 A/B verbatim
(`md5 c32399fd746014fbd68fd2d9b9f34c6b`, identical on the primary compute cluster and on the drafting cluster), so the
packets that were audited are the packets that shipped.

## Validation

```
KC     packets 159  drafts 159   grounded 114 (71.7%)  partial 29 (18.2%)  abstained 16 (10.1%)
                                 mean 1528 chars over 143 drafted units    HARD FAILURES 0
TOPIC  packets  22  drafts  22   grounded  15 (68.2%)  partial  7 (31.8%)  abstained  0
                                 mean 2190 chars                            HARD FAILURES 0
RESULT: SCHEMA_OK for both
```

Against the previous run: grounded 108 -> 114, partial 37 -> 29, mean length 1494 -> 1528.

## What is attributable to INT-11, and what is not

The drafter is nondeterministic run to run - measured earlier at 12 status changes between two
runs on IDENTICAL packets. So the status shift above cannot be claimed as INT-11's effect, and is
not claimed here.

What IS attributable is content, in the units whose packets actually changed:

| unit | before | after |
|---|---|---|
| Bayes' Theorem | `partial`; its only equation was a PPCA proportionality from another book | **grounded**, stating `P(y\|x) = (P(x\|y)P(y)) / P(x)` |
| Rand Index | `partial`; "the specific mathematical formula ... is not provided" | **grounded**, stating `(f11+f00)/(f11+f10+f01+f00)` |
| Information Gain | grounded, no general form | **grounded**, stating `IG(A) = I(D) - sum (\|Dj\|/\|D\|) I(Dj^A)` |
| Precision | — | **grounded**, stating `p = TP/(TP+FP)` |
| Jaccard Coefficient | — | **grounded**, with its formula |
| Silhouette Coefficient | `partial` | `partial`, but now defining a(x) and b(x) properly |

These units previously reported those formulas as missing from their evidence. They are no longer
missing, because the corpus held intact renderings that the damage checks were discarding.

## Validation failures: 6 -> 9, none attributable

```
r1 failures (6): Bushy Decision Tree, Evaluation Workflow, F-Measure,
                 Multi-class Confusion Matrix, Models of Randomness 1 and 2
r2 failures (9): the above minus F-Measure, plus Learning Phase, Target Attribute,
                 Classification Threshold (Cutoff), External Index: Recall
```

Eight are `unjustified_abstention_on_draftable_packet`. Cross-referenced against the 13 units
whose packet content changed: **none of the four new failures is among them.** All four have
byte-identical packets in both runs, so they are drafter variation, not an effect of the
intervention. F-Measure, which failed in r1, now passes.

Two of the three new abstentions replace drafts that doc 50 judged poor: `Target Attribute` (whose
r1 draft carried the filler claim "a central concept in data mining, and its proper understanding
is essential", ledgered against five evidence ids that support none of it) and
`Classification Threshold (Cutoff)` (three trivial claims). An abstention there is more honest
than the draft it replaces, even though the validator counts it as a failure.

The ninth, `External Index: Recall`, is a new issue TYPE: `evidence_map_cites_unknown_evidence_id`
for `KC_CLU_EVAL_0001`. Read rather than assumed - that is a truncation of
`KC_CLU_EVAL_012:comprehensive:0001`, a model transcription slip, and the same claim also cites a
valid id. The validator catching it is the system working.

## INT-12 hygiene, r1 vs r2

```
check                                  r1     r2
BODY_SENTENCE_NOT_COVERED_BY_LEDGER   239    255
STATED_ARITHMETIC_EVALUATED            21     17
SOURCE_META_COMMENTARY_IN_BODY         11     12
DUPLICATED_SENTENCE                     0      3
SELF_REFERENTIAL_SENTENCE               1      0
UNRENDERED_MARKUP_IN_BODY               2      2
```

Roughly flat. The three duplicated sentences are all in one unit, `Confidence Interval for
Accuracy`, whose packet did not change - a degenerate draft that INT-12 caught, which is what it
is for.

## Repository

```
762fd2b  test(INT-11): guard the invariant that a repair must not move a row
f03a826  test(INT-12): make the ledger-coverage guard actually test union scoring
b68268b  feat(vNext INT-12): draft hygiene checks over the drafted text. Flag-only.
d120f4d  fix(verify): a check that raises must not discard the report for every other check
5b4e100  feat(vNext INT-11): repair a damaged formula from an intact twin instead of dropping it
ed4b1fa  (previous freeze point)
```

Verification suite 364 -> 393 checks, 0 failed. Sabotage audits: INT-11 9 of 9 and INT-12 8 of 8
caught by their target guard, every file restored, post-audit baseline green.

## Ceilings, with numbers attached

- **D2 defining-equation misrouting** (doc 53). Rejected: even the narrowest symbol-binding form
  is 52% ambiguous, because sibling units share label words by construction. Fifth distinct
  failure mode recorded for target binding.
- **D7 scope creep, D8 name-vs-content mismatch** (doc 50). Consequences of the unit taxonomy -
  what counts as a unit and what its name promises - which is an input to the pipeline rather
  than something the pipeline can decide.
- **The remaining 1640 damaged renderings** have no intact twin anywhere in the corpus. 45 of
  1685 were repairable; the rest are extraction losses with nothing to recover from.
- **Drafter nondeterminism**, ~12 status changes per run on identical packets, sets the floor on
  what any single drafting run can demonstrate.
