# Evaluation overhaul v2 — pre-registered

**Status: PRE-REGISTERED. Written and committed BEFORE any v2 metric was computed.**
The commit adding this file contains the protocol and the implementing code and **no results**.

**Motivation.** The v1 evaluation was rigorously *validated* but used metrics behind current
practice. Three specific defects, two of which were found by the project owner and one confirmed by
literature review:

1. **Faithfulness aggregation is non-standard.** v1 derived M1 as PASS only if *every* claim is
   supported. RAGAS-standard faithfulness is the **ratio of supported claims to total claims**. The
   all-or-nothing form is a function of draft length (F-34: observed ≈ p^n almost exactly) and it
   **inverts the extrinsic Proposed-vs-BaseDense ranking** relative to the per-claim rate. A ranking
   that flips on an arbitrary aggregation choice cannot support a claim.
2. **No retrieval-side metric.** The extrinsic family exists to compare *retrieval architectures*,
   but v1 measured only downstream drafts. End-to-end RAG performance confounds retrieval quality,
   the generator's ability to exploit context, and its parametric knowledge; measuring retrieval
   through a single generator cannot separate them. This is a documented pitfall, and it is the
   project owner's objection: had Gemma4 been the fixed drafter rather than Qwen3.8, the
   faithfulness picture would likely differ.
3. **Holistic completeness is coarse.** TREC RAG decomposes references into atomic **nuggets**
   labelled vital/okay and scores recall over vital nuggets. v1's single holistic
   CORE_COMPLETE/MATERIAL_OMISSION verdict is why one disputed item (the Wilson formula, F-17) could
   flip an entire KC's verdict instead of costing 1/N of a graded score — and it is a plausible
   cause of the M3 qualification failure (F-14).

**What v2 does NOT change.** The frozen judge model, decoding config, blinding enforcement,
candidate freeze, expert reference library, and the human calibration labels all stand unchanged.
v2 adds and replaces *metrics*, not the instrument.

---

## M1v2 — per-claim faithfulness (replaces all-or-nothing M1)

`faithfulness = supported_claims / total_claims`, computed per draft, aggregated by KC.

**No new inference required.** The per-claim verdicts already exist in the v1 campaign output; v1's
scalar was a lossy derivation of data we already hold. Reporting the ratio adds information rather
than substituting a different measurement.

All-or-nothing M1 continues to be reported alongside, as the frozen-instrument derivation.

---

## M3v2 — vital-nugget recall (replaces holistic M3)

**Step A — nugget decomposition (arm-independent, once per KC).** Each of the 159 expert references
is decomposed into atomic, self-contained nuggets. Each nugget is labelled:
- `VITAL` — a defining component; a draft omitting it is materially incomplete
- `OKAY` — accurate and useful, but not defining

Decomposition happens **once per KC and is shared by every arm**, so no arm can be advantaged by a
different nugget set. It is also independent of any draft.

**Step B — nugget assignment (per draft).** For each (KC, arm) draft, every nugget is assigned
`SUPPORTED` / `PARTIAL` / `NOT_SUPPORTED` against the draft text.

**Score.** `vital_nugget_recall = supported_vital / total_vital`, with `PARTIAL` counted as 0 for
the primary score and reported separately (a lenient variant crediting PARTIAL at 0.5 is reported
as secondary, fixed here in advance).

**Why this addresses the F-17 dispute directly:** "is the exact Wilson formula a defining
component?" becomes an explicit `VITAL`/`OKAY` label on **one nugget**, visible and auditable,
costing 1/N of a graded score rather than flipping a binary verdict.

---

## CR — context recall (NEW; retrieval measured directly, no generator involved)

For each **evidence configuration** and KC, each reference nugget is assigned
`PRESENT` / `PARTIAL` / `ABSENT` **against the retrieved evidence itself**, not against any draft.

`context_recall = present_vital / total_vital`

**This is the metric the extrinsic ablation actually needs.** It is computed on the evidence a
retrieval architecture surfaced, with **no drafter in the loop**, so it cannot be confounded by a
generator's ability to exploit context.

Measured empirically: the 7 arms use only **4 distinct evidence configurations** —
`Proposed` (shared by all three intrinsic arms *and* extrinsic_P-Q), `BaseDense`, `DOS-RAG`, and
`DOS-RAG budget-matched`. So CR costs 4 × 159 = **636 judgements**, not 1113, and the intrinsic
family is confirmed to genuinely hold evidence fixed.

---

## CP — context precision (NEW, secondary)

Fraction of retrieved evidence items that are relevant to the KC's reference. Reported as secondary
because evidence sets are large (8–40 items) and precision is less decision-relevant than recall for
this study's question. Computed on the same 4 configurations.

---

## Validation required before any v2 result is used

v2 introduces new prompts and schemas, so it is a new measurement instrument and is gated exactly as
v1 was:

1. **Grammar enforcement.** New schemas must pass the EBNF-level checks (`oneOf` branches
   materialise and bind; `if/then/else` is never relied on).
2. **Preflight.** Branch reachability in both directions, and no truncation stalls.
3. **Human alignment — a falsifiable claim.** The 36 human-labelled calibration rows carry holistic
   `CORE_COMPLETE` / `MATERIAL_OMISSION` judgements. v2 predicts:

   > **Vital-nugget recall separates the human's CORE_COMPLETE and MATERIAL_OMISSION rows better
   > than the judge's holistic M3 verdict did.**

   Tested by AUC of vital-nugget recall against the human label, compared against holistic M3's
   agreement on the same rows. **If v2 does not beat v1 here, v2 is not adopted** as the primary
   completeness metric and this is reported.

Registered **before** the comparison is run. Thresholds are not adjustable afterwards.

---

## Reporting rules

- Per-claim faithfulness becomes primary; all-or-nothing M1 reported alongside, with F-34's
  length-artifact explanation attached.
- Context recall becomes the **primary extrinsic (retrieval) metric**; draft-mediated metrics are
  reported as secondary for that family, with the generator-confound stated.
- Vital-nugget recall becomes primary for completeness **only if** it passes the human-alignment
  test above.
- The v1 results are **retained and reported**, not deleted. v2 supersedes v1 metrics; it does not
  erase the record of what v1 measured or why it was inadequate.
- All standing caveats persist: absolute `JUDGE_QUALIFIED=false`, LOW POWER arm-independence,
  single-annotator human gold.

---

## ADDENDUM — final design decisions (pre-registered, 2026-08-31)

Recorded before execution. These close the design rather than extend it; v2 is intended to be the
final evaluation.

### The organising principle: failure attribution

The four primary metrics form a precision/recall pair on each pipeline stage:

| | precision-like | recall-like |
|---|---|---|
| **retrieval** | context precision | **context recall** |
| **generation** | **per-claim faithfulness** | **vital-nugget recall** |

This is what makes the numbers interpretable rather than arbitrary. Because context recall is
measured on the evidence with **no generator in the loop**, failure can be attributed to a stage:

- **low context recall** -> retrieval did not surface the required content; the drafter could not
  have covered it.
- **high context recall + low nugget recall** -> the content was available and the drafter failed to
  use it.
- **high nugget recall + low per-claim faithfulness** -> the drafter covers the reference but also
  asserts unsupported material.

v1 could not distinguish these, which is precisely why the objection "a different drafter would
change the retrieval ranking" had no answer within v1.

### Metrics demoted, with reason

- **M2 (correctness)** and **TARGET (alignment)**: ceiling effects, 0.912-0.977 and 0.973-1.000, with
  **zero** significant pairwise differences under either verdict rule (F-32). Reported as
  non-discriminating at this quality level. They are NOT evidence that arms are equivalent, and are
  demoted from primary rather than deleted.
- **all-or-nothing M1** and **holistic M3**: superseded by their v2 replacements, retained in the
  record with F-34/F-17 attached.

### Reliability evidence: second judge *(superseded 2026-09-02 - see note)*

> **Superseded.** This section planned `RootSignals-Judge-Llama-70B`. That model was never present on the cluster, and it would in any case have shared Selene's Llama family and so its verbosity bias. The executed check used **MiniCheck-Flan-T5-Large**, an encoder-decoder chosen for architectural independence. See F-56/F-57 and `PLAN_judge_qualification_and_second_judge.md`.

Human validation is our weakest link - 36 rows, one annotator, against a literature benchmark of
roughly 150 calibration samples [R-02]. No metric redesign fixes that. We therefore add
**inter-judge agreement** using `RootSignals-Judge-Llama-70B` (already present on Cluster A, 68 GB,
15 shards, serve script ready) on a subset of the v2 judgements.

Stated honestly: inter-judge agreement measures **reliability, not validity**. Two judges can agree
and both be wrong; [R-08] warns explicitly against reading reliability as validity. It is reported
as reliability evidence only, alongside - never instead of - the failed absolute qualification.

### Domain runs are NOT re-run

Mathematics and sociology already store per-claim verdicts, so per-claim faithfulness is recomputed
from existing output at zero cost. Nugget and context metrics are undefined there because no
reference exists (F-27/C-05). The existing domain run is therefore already v2-compatible; only the
aggregation changes.

### Adoption test unchanged

Vital-nugget recall must separate the 36 human CORE_COMPLETE / MATERIAL_OMISSION rows better than
holistic M3 did, or it is not adopted as primary and that is reported. Passing makes v2 **better
than v1**, not **validated in absolute terms** - the test inherits the single-annotator limitation.
