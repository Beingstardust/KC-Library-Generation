# Comparative-use qualification protocol (ablation ranking)

**Status: PRE-REGISTERED. Written and committed BEFORE the criteria below were computed.**
The git history of this file is the proof of that ordering — the commit adding this document
contains no results, and the analysis script `run_comparative_qualification.py` is committed in the
same commit, before it was ever executed. Any later commit that changes a threshold is a visible,
reviewable amendment, not a silent retune.

**This protocol does NOT replace, relax, or reopen `JUDGE_QUALIFICATION_PROTOCOL.md`.**
That protocol tested *absolute* validity and returned `JUDGE_QUALIFIED=false`. That result stands,
is reported, and is not revisited here.

---

## 1. Why a second, different qualification is warranted

Absolute qualification asks: *does the judge's verdict match a human's verdict?* On
`M3_CORE_COMPLETENESS` it does not (NOT_QUALIFIED, n=36), and on M1/M2/TARGET/M4A there were too few
minority-class examples to say.

The ablation study asks a **different question**: *which arm is better?* Every arm drafts the same
knowledge components, so the comparison is **paired within KC**. Under a paired comparison, two
things that broke absolute qualification cancel out:

- **KC difficulty** — the same KC appears in every arm.
- **A constant judge threshold offset** — if the judge is uniformly strict about what counts as a
  "defining component", that strictness is applied to every arm's draft of that KC alike.

The diagnostic in `output/qualification/M3_DISAGREEMENT_DIAGNOSTIC.md` shows exactly this shape:
the dominant failure KC (`KC_EVAL_COMP_002`) received `MATERIAL_OMISSION` on **all six arms** — a
constant offset carrying **zero** between-arm signal. A miscalibrated but *arm-independent* judge
can still rank arms validly.

The requirement for valid ranking is therefore **arm-independence**, not absolute accuracy. That is
a weaker claim, and — unlike absolute accuracy — it is testable with the calibration data already
collected.

**Scope of any claim licensed by this protocol:** relative ordering of arms and paired
within-KC differences. It does **not** license absolute statements about KC quality
("system X produces complete KCs"), only comparative ones ("system X is judged more complete than
system Y on the same KCs, by an instrument that is uncalibrated in absolute terms").

---

## 2. The four conditions (all must hold for a task to be COMPARATIVE_QUALIFIED)

### C1 — Structural blinding (arm identity not observable to the judge)
Arm identity must be absent from every prompt. Already enforced: 36 forbidden patterns checked at
prompt-build time by `assert_blinded()`, which **raises** rather than warns; native evidence ids
(which encode the retrieval lane) are replaced with opaque `SRC_*` ids; the draft's self-reported
`grounded`/`partial`/`abstained` status is dropped.
**Check:** re-run the blinding sweep over the evaluation rows; require **zero** violations.
*Residual risk, stated not dismissed:* blinding removes explicit identifiers, but a drafter's
writing style may still correlate with its identity. C2 is the empirical test for whether that
residual leakage actually produces differential treatment.

### C2 — No detectable arm-dependent disagreement
Using the frozen human calibration labels, compare judge-vs-human disagreement across arms.
- **Test:** Fisher–Freeman–Halton exact test on the arm x {agree, disagree} table, per task.
- **Threshold:** fail if `p < 0.05` (evidence of arm-dependent behaviour).
- **Also reported unconditionally:** per-arm disagreement rate, per-arm *signed* bias
  (false_pass − false_fail), and Wilson intervals.
- **Power is low** (n≈5–6 per arm). A non-significant result is therefore **weak** evidence of
  arm-independence, not proof. This is recorded as `LOW_POWER` on every task where any arm has
  fewer than 10 labelled rows, and must be reported alongside the decision.

### C3 — Determinism / instrument stability
Same input must yield the same verdict. Already established: `temperature=0.0`, `seed=20260812`,
frozen decoding, and a 36/36-sentinel equivalence check across two different GPU architectures with
**zero** primary-verdict differences.
**Check:** assert the evaluation run used the manifest decoding block unmodified.

### C4 — Paired coverage
Every arm must have a verdict for the same KC for that KC to enter the paired comparison. KCs where
any arm is missing a verdict are **excluded from the paired statistic and reported as excluded**,
never imputed. Genuine abstentions (empty drafts) are **not** missing data — they are a real
behaviour of that system and are scored as such.

---

## 3. Analysis plan for the ablation evaluation (fixed here, before running)

- **Unit of analysis:** the KC. Not the row. The 36-row calibration failure showed that rows cluster
  by KC; all ablation statistics are therefore computed with KC as the unit and confidence intervals
  from a **KC-level bootstrap** (10,000 resamples, resampling KCs with replacement).
- **Primary statistic:** paired within-KC comparison between arms. For binary tasks
  (M1/M2/M3/TARGET), report per-arm pass rate plus, for each arm pair, the **paired difference** with
  a KC-clustered bootstrap CI and an exact **McNemar** test on discordant pairs.
- **Multiplicity:** the two ablations are pre-specified as separate families —
  intrinsic (P-Q / P-G / P-D) and extrinsic (P-Q / B-Q / DOS-Q). Within each family, pairwise arm
  comparisons are Holm-corrected across the 3 pairs, per task. The sensitivity arm
  (`DOS-Q_matched_budget`) is analysed only against `DOS-Q` and is labelled exploratory.
- **M4B remains exploratory** and is excluded from all confirmatory claims (unchanged).
- **M3 reporting rule:** because M3 is absolutely NOT_QUALIFIED, any M3 result is reported as a
  paired comparison **only**, with the absolute failure disclosed in the same table. No absolute M3
  completeness claim is made.
- **Prespecified interpretation guard:** if an arm difference is smaller than the judge–human
  disagreement rate for that task, it is reported as **within instrument noise** and no ranking claim
  is made from it.

---

## 4. Decision values

Per task, one of:
- `COMPARATIVE_QUALIFIED` — C1–C4 all hold.
- `NOT_COMPARATIVE_QUALIFIED` — C2 detected arm-dependent behaviour (p < 0.05), or C1/C3/C4 failed.
- `INSUFFICIENT_COMPARATIVE_SUPPORT` — no labelled rows for the task (e.g. M4A), so C2 is untestable.

`COMPARATIVE_QUALIFIED` is **criterion-wise per task**. No averaging across tasks. A task that fails
does not invalidate the others, and a task that passes does not rehabilitate the absolute
`JUDGE_QUALIFIED=false` verdict.

---

## 5. What this protocol may never be used to do

- Re-score, relabel, or reinterpret the absolute qualification result.
- Recompute the absolute gate at KC level after having seen it fail at row level.
- Select a judge model by trying candidates until one passes.
- Convert a comparative pass into an absolute quality claim.
