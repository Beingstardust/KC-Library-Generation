# M3 disagreement diagnostic — why `M3_CORE_COMPLETENESS` returned NOT_QUALIFIED

**Date:** 2026-08-30
**Status:** diagnostic only. Nothing here re-scores, re-labels, or re-runs the frozen qualification.
The `NOT_QUALIFIED` decision in `qualification_decision.json` stands exactly as computed.

---

## The headline numbers, restated

| gate | observed | threshold | met |
|---|---|---|---|
| raw agreement | 0.556 | 0.80 | no |
| Gwet AC1 | 0.392 | 0.65 | no |
| PASS recall | 0.40 | 0.75 | no |
| FAIL recall | 1.00 | 0.75 | **yes** |

Confusion: `PASS→FAIL 12`, `PASS→PASS 8`, `FAIL→FAIL 12`, `FAIL→NOT_JUDGEABLE 4`.
False-pass rate **0.00**; false-fail rate **0.60**.

The judge caught **every** material omission the annotator identified, and missed none. The entire
failure is one-directional over-flagging.

---

## Finding 1 — the sample is clustered, not 36 independent observations

The 36 rows are (KC x arm) pairs drawn from only **17 distinct knowledge components**.

The 12 false-fails come from just **7 distinct KCs**, and are dominated by one:

| KC | false-fails / rows |
|---|---|
| **KC_EVAL_COMP_002** | **6 / 6** |
| KC_CLU_SIM_008 | 1 / 2 |
| KC_EVAL_ENS_002 | 1 / 2 |
| KC_EVAL_SAMP_004 | 1 / 2 |
| KC_CLF_DT_002 | 1 / 1 |
| KC_DE_MISS_004 | 1 / 1 |
| KC_FSEL_GEN_006 | 1 / 1 |

`KC_EVAL_COMP_002` alone accounts for **half of all M3 false-fails** — and it is one underlying
KC-level judgement replicated across six arms, not six independent errors. The gate treated
clustered rows as independent, which both overstates precision and lets a single KC drive the
verdict.

**This is a disclosure, not a licence to re-analyse.** Recomputing the gate at KC level *after*
seeing the result would forfeit the pre-registration that makes this decision credible. A clustered
analysis must be pre-registered before any future run.

---

## Finding 2 — the dominant KC is a rubric-boundary disagreement, and the judge is factually right

`KC_EVAL_COMP_002` = *Confidence Interval for Accuracy*. Its expert reference centres on the
**Wilson score interval**:

> The source gives the resulting confidence interval for p as
> `[2N·acc + z² ± z√(z² + 4N·acc − 4N·acc²)] / [2(N + z²)]`, where z = Z_{α/2} …

Checked mechanically: **all six candidate drafts omit that exact formula.** Three substitute a
Wald-style approximation, three give no formula at all.

With rationale capture enabled (see Finding 4), the judge's stated `missing_defining_components`
across the six rows were:

- the confidence-interval formula (**all 6 rows**)
- the binomial model and its normal approximation for large N (2 rows)
- the role of `z = Z_{α/2}` for confidence level 1−α (2 rows)
- the effect of N on interval width / tightness (2 rows)

Every one of those items **is present in the reference and absent from the draft**. The judge is
not hallucinating, not inconsistent, and not misreading the task. It is applying a strict reading of
"defining component".

The annotator applied a looser one, explicitly:

> "Omitting the reference's exact Wilson formula is not a material defect."
> "The exact closed-form interval formula is useful detail …"

Both positions are internally coherent. **The disagreement is about where the construct boundary
sits, not about who read the text correctly.** No change of judge model resolves it.

Note also: this KC yields **zero discriminative signal between arms** — all six arms omit the same
content and receive the same verdict — while consuming 6 of 36 calibration rows.

---

## Finding 3 — the annotator separates correctness from completeness; the judge does not

Recurring pattern in the human notes on contested rows:

> "…statistically incorrect, so M2 fails. **However**, the response still adequately explains the purpose…"
> "M1 and M2 fail. **Nevertheless**, it adequately explains…"

The annotator marks content **wrong** (M1/M2) but coverage **complete** (M3). On several of those
same rows the judge returns `MATERIAL_OMISSION` — i.e. incorrectness is leaking into a
*completeness* construct.

If confirmed more broadly, this is a **prompt/rubric separation defect**, and it would be inherited
by any substitute judge model.

---

## Finding 4 — tooling gap, now fixed

`run_selene_on_calibration.py` originally persisted only the derived scalar label, discarding each
task's full response. That made it impossible to ask *why* a verdict was reached — the single most
useful diagnostic. The script now retains full validated responses (including
`missing_defining_components` and `rationale`) under a `responses` key, for M1, M2, M3 and TARGET.

Evidence for Finding 2 came from re-running only the 6 affected rows under the identical verified
stack: `output/human_calibration/diag_kc_eval_comp_002_predictions.json`.

---

## Finding 5 — annotation instability, unresolvable as recorded

- Two contested rows carry explicit `"REVISED on recheck (M3 MATERIAL_OMISSION→CORE_COMPLETE)"` —
  the annotator first agreed with the judge, then reversed.
- `KC_DE_MISS_004` is labelled `CORE_COMPLETE` while its own note reads *"it materially underdefines
  the KC. It does not explain the reference/non-reference attributes…"* — the note contradicts the label.

With a single LLM-suggestion-assisted annotator and `human_human = {}`, there is **no way to
adjudicate these**. Low judge–human agreement therefore cannot be cleanly attributed to judge error
rather than annotation error. The frozen protocol's own instruction — flag the construct first when
human–human agreement is poor — cannot be executed here.

---

## What this does and does not license

**Does not:** re-score M3, relabel human data, recompute the gate at KC level, or swap judge models
in search of a pass. Any of those after seeing results would destroy the pre-registration advantage.

**Does:** support reporting `NOT_QUALIFIED` for M3 as a genuine result, accompanied by three
disclosed limitations — sample clustering, an unresolved construct boundary concentrated in one KC,
and single-annotator provenance.

The open question is a **definitional one for the project owner**, not an empirical one for a larger
model: *is a reference's exact closed-form formula a defining component whose absence is material?*
Answering it requires either an explicit rubric rule (which breaks the freeze and mandates a
re-derivation + re-run) or reporting M3 as construct-limited — the same route already taken for M4B.
