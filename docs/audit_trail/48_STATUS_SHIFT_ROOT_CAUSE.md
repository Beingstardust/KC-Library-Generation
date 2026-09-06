# 48. Why grounded appeared to fall and partial to rise

Triggered by the observation that the final vNext run reports 67.7% grounded against the frozen
comparator arm's 75.3%. The premise is correct as stated; the comparison is against the wrong
baseline. This document establishes that empirically rather than by argument.

## The three runs

```
run                     n    grounded      partial     abstained   mean_prompt_chars
frozen_proposed(A40)   158  119 (75.3%)   25 (15.8%)  14 (8.9%)         43,711
datamining_full(A40)   158  106 (67.1%)   39 (24.7%)  13 (8.2%)         48,449
final_vnext(H100)      158  107 (67.7%)   37 (23.4%)  14 (8.9%)         49,918
```

`datamining_full` is the production pipeline on production packets on the SAME A40 hardware, run
BEFORE any vNext intervention existed. It already sat at 67.1%. The frozen comparator arm is the
outlier, not the vNext run.

## Root cause: the comparator arm drafted without the sufficiency instruction

`04_draft_runner.py` is byte-identical between the mirror and the vNext worktree, so the prompt
template did not change. But `build_prompt()` takes a `mode`, and `visible_packet_for_prompt()`
drops `drafting_instruction` from the prompt under `controlled_comparator`. That mode exists for a
good reason - only the proposed pipeline attaches the field, so leaving it in would have been a
generator-side confound in the three-way Base Dense / DOS-RAG / Proposed experiment (docs 14, 15).

`drafting_instruction` is where the sufficiency machinery lives:

- STEP 2 - SUFFICIENCY: decide whether the supplied passages are sufficient, partially
  sufficient, or insufficient.
- conflicts: record the conflict in uncertainty_notes and report partial rather than choosing
  silently.
- STEP 3 - SUPPORT LEDGER: fill evidence_map first.

Arithmetic confirms the mechanism rather than merely being consistent with it: the field
serializes to a mean of 5,510 chars, and the observed production-minus-comparator prompt gap is
48,449 - 43,711 = 4,738 chars. No retries are involved in either run (`repair_attempted` = 0 for
both), so the gap is not retry inflation.

So the comparator arm was asked to draft with the step that tells it when to say `partial`
removed from its prompt. Its higher grounded rate is a direct and expected consequence.

## Corroboration: the comparator flagged nothing, ever

```
run                     grounded  of which carry uncertainty_notes
frozen_proposed(A40)      119                 0
datamining_full(A40)      106                 1
final_vnext(H100)         107                 3
```

Zero of 119. Not a few - none.

## The 12 grounded->partial flips are not caused by any intervention

Every one of the 12 KCs that moved grounded (comparator) -> partial (final) has BYTE-IDENTICAL
evidence between the two packet sets: same item count, same char count, same formula-row count,
same `packet_support_state` (draftable -> draftable in all 12). The interventions changed nothing
about these units' evidence.

What changed is that the final run reported gaps the comparator run did not. All 12 had
`uncertainty_notes` empty before and specific afterwards. Examples, all checkable against evidence
present in BOTH runs:

- Area Under the ROC Curve: "AUC = number of correctly ranked positive-negative pairs", missing
  the denominator.
- Ensemble Classifier: two formulas "present in the evidence but garbled and cannot be
  reconstructed cleanly".
- Silhouette Coefficient: the range renders as "between and 1" - the minus one is gone.

Those defects were in the comparator's evidence too. It called them grounded anyway. That is the
failure mode already named at `02_build_kc_packets.py:565` - wrongly-"grounded" drafts.

## Against the correct baseline the vNext run improves

```
datamining_full(A40) -> final_vnext(H100),   6 of 158 changed
  grounded  -> grounded  : 104        partial  -> grounded  : 3
  partial   -> partial   :  35        grounded -> partial   : 2
  abstained -> abstained :  13        partial  -> abstained : 1

  mean draft chars   1,451 -> 1,496
  mean linked claims   8.1 -> 8.2      (total 1,173 -> 1,181)
```

Grounded +1, partial -2, and more content with more evidence-linked claims. Net movement favours
grounded 3 to 2.

## Every partial names a specific gap

The prompt forbids a bare hedge: "If you cannot name a specific gap, the status is grounded, not
partial." Measured: 37 of 37 partials in the final run carry a named gap, 0 carry empty notes.
Same for 39 of 39 in the production baseline and 25 of 25 in the comparator. `partial` is
therefore not a degradation signal - it is a declared, auditable source defect.

## Where the remaining headroom actually is

Classifying all 37 partials by the cause their own notes name:

```
  extraction defect - garbled or incomplete RENDERING      15 of 37
  source absence    - the source genuinely does not say it  22 of 37
```

The 22 are ceiling: a formula that is not in the corpus cannot be retrieved. Raising grounded on
those would require external knowledge, which the design forbids.

The 15 are ours. A recurring, domain-agnostic sub-class is visible in the packets: a lead-in is
ADMITTED but its formula payload is NOT. `Confidence Interval for Accuracy` admits four such
pointers with no payload, among them "the confidence interval for the true difference dt is given
by the following equation:" and "gives a plausible range ... under the normal approximation:".
`Specificity` admits the pointer whose payload the drafter reports as absent; `RIPPER Rule
Induction` reports the pruning metric pointer's equation missing.

This is the MIRROR IMAGE of INT-7. INT-7 repaired "pointer suppressed by a mislabel flag, so the
payload was unreachable by the existing lead-in-to-payload rescue". This class is "pointer
admitted, payload still not admitted" - the rescue either did not fire or its successor linkage
did not resolve. Stated without reference to any unit or corpus:

> Where an admitted passage ends in a lead-in that announces a formula, and the source successor
> block carries that formula, the payload should be admitted alongside the pointer. A pointer
> admitted without its payload is strictly worse than admitting neither, because it tells the
> drafter something exists that it cannot state.

NOT IMPLEMENTED. Recorded as the highest-value remaining candidate, subject to the same evidence
discipline as every other intervention: blast radius first, controlled A/B, regression audit,
promotion only on measurement.

## What must NOT be done

Raising the grounded count by weakening the sufficiency instruction, relaxing what qualifies as a
named gap, or removing `drafting_instruction` from the production prompt would all raise the
number and lower the trustworthiness of every draft. The comparator arm is the natural experiment
showing exactly how much grounded can be bought that way: about 8 percentage points, at the cost
of 119 drafts that flag nothing.

`status` is a drafter self-report. It is a reporting signal, not a quality measurement.

## Reproduction

Scripts under `_status_probe/`, all run through SLURM on partition `short`:
`status_delta2.py` (job 248810), `baseline3.py` (248811), `partials4.py` (248812),
`leadin5.py` (248813).

One correction made during this audit: the first version of the probe read evidence from a
non-existent packet field (`evidence` / `evidence_items` rather than `evidence_for_synthesis`),
which made every evidence delta print as +0. That would have supported the right conclusion for
the wrong reason. Fixed in `status_delta2.py` before any conclusion was drawn; the byte-identical
evidence finding above comes from the corrected loader.
