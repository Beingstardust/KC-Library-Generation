# Amendment 02 — blinding exemption for KC_EVAL_ENS_004 (sensitivity arm)

**Status: GRANTED, with the triggering text quoted in full below.**

## What happened

One row of the v2 faithfulness stage failed, and it was **not** a server error:

```
key:   KC_EVAL_ENS_004|sensitivity_DOS-Q_matched
error: BlindingViolation: prompt contains blinding-violating text 'variant proposed'
       (pattern '\b(system|arm|pipeline|architecture|retrieval|evidence\s+pack\w*|packet|
        condition|variant|configuration)\s+proposed\b')
```

The blinding guard exists because one of the compared pipelines is literally named **Proposed**. A
draft containing "…the proposed system…" would tell the judge which arm it is looking at and destroy
the comparison. The guard therefore refuses any prompt where a system-ish noun precedes "proposed".

## Why this instance is a false positive

The KC is **Boosting**, and the phrase is ordinary machine-learning prose:

> "Notable implementations include AdaBoost, developed by Freund and Schapire, and Arcing, **a
> variant proposed by Breiman** that uses non-uniform weights assigned to training examples to
> resample the data for building an ensemble of training sets."

"Arcing, a variant proposed by Breiman" refers to a 1998 boosting algorithm. It carries no
information about which arm produced the draft.

Checked before granting: **no other arm's draft for this KC contains the phrase**, so the exemption
cannot systematically advantage or disadvantage any arm — it applies to exactly one row of the
`sensitivity_DOS-Q_matched` arm, which is reported as exploratory-only and carries no ranking claim.

## What was granted

The single pattern above is passed via the guard's existing `allow=` parameter for **this row only**.
Per `assert_blinded`'s contract the exemption is recorded in the judge row, so it cannot be granted
silently. All other blinding patterns remain armed for this row, and no other row receives an
exemption.

## Why not simply drop the row

Dropping it would be the quieter option and is rejected: the row is a genuine measurement, and
silently discarding rows that trip a guard biases the sample toward drafts that happen to avoid
certain vocabulary. The guard did its job — it demanded a human decision, and this document is that
decision.

## Execution constraint

The re-run is deferred until the F-46 job finishes rather than run alongside it. Concurrency was
measured to flip verdicts on this stack (`VLLM_BATCH_INVARIANT` is not enabled server-side), so
issuing requests in parallel with a sequential campaign could alter that campaign's results. One row
is not worth that risk.
