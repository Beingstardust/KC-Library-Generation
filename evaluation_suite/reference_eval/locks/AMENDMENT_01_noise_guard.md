# Amendment 01 — the noise guard is not commensurable with a paired difference

**Date:** 2026-08-31
**Amends:** `COMPARATIVE_USE_PROTOCOL.md` section 3, final bullet ("prespecified interpretation guard")
**Status:** the original guard is **retained and reported**. This amendment **adds** a second verdict
column; it does not replace or delete the registered result.

---

## What the original guard said

> "if an arm difference is smaller than the judge–human disagreement rate for that task, it is
> reported as **within instrument noise** and no ranking claim is made from it."

## Why it is wrong

It compares two quantities that are not on the same scale:

- the **arm difference** is a *paired, within-KC* quantity — the same KC judged under two arms, so
  any constant judge offset cancels;
- the **judge–human disagreement rate** is an *absolute, unpaired* quantity — how often the judge's
  label differs from a human's on a single draft.

The disagreement rate is largely produced by exactly the systematic offset that pairing removes.
Finding F-15 measured that offset directly: the judge over-flags material omissions with a false-fail
rate of 0.60 and a false-pass rate of 0.00 — a one-directional bias applied to *every* arm, which
finding F-21 then confirmed is arm-independent. Subtracting that absolute rate from a paired
difference double-counts a bias the pairing has already cancelled.

The thresholds it produces are unreachable by construction: M1 0.367, M2 0.333, **M3 0.444**,
TARGET 0.094. An M3 effect would have to exceed 44 percentage points on paired KC proportions to
"clear noise".

## What it did to the result

**All 24 comparisons were flagged `WITHIN_INSTRUMENT_NOISE`**, including:

| comparison | Δ | 95% CI (KC bootstrap) | exact McNemar p | discordant |
|---|---|---|---|---|
| M3 · extrinsic Proposed vs BaseDense | **+0.421** | [+0.322, +0.513] | 0.0 | 73 / 9 |
| M3 · intrinsic Qwen3.8 vs Gemma4 | +0.193 | [+0.133, +0.260] | 0.0 | **29 / 0** |
| M1 · intrinsic Gemma4 vs DeepSeek-R1 | +0.364 | [+0.258, +0.470] | 0.0 | 59 / 11 |

A 29-vs-0 perfectly one-directional split being reported as "noise" is a reductio of the rule, not a
finding about the data.

## Timing — why this is a correction and not post-hoc tuning

The defect was identified and committed **before** these results existed:

- commit `5dbdf54` (analysis script) states in its message: *"the noise guard compares an ARM
  DIFFERENCE against the ABSOLUTE judge-human disagreement rate. These are not commensurable … so
  the guard is likely too conservative and will flag real differences as noise. It is applied
  exactly as pre-registered regardless."*
- commit `63fc707` records the unmodified as-specified run, with all 24 nullified.
- only then was this amendment written.

`git log` is the evidence. The threshold was never adjusted to change which comparisons survived.

## The amendment

Inference for a paired difference rests on the controls the protocol **already registered** for it,
with no new parameter introduced:

> A comparison is **significant** when its Holm-adjusted exact-McNemar p < 0.05 **and** its
> KC-clustered bootstrap 95% CI excludes zero.

Both verdicts are reported side by side in `ABLATION_RESULTS.md`:
`verdict_as_specified` (the registered guard) and `verdict_amended` (the rule above).

## What does not change

- The judge remains unqualified for absolute claims on M1/M2/TARGET/M4A. *(Updated 2026-09-02: the blanket phrasing is superseded by F-55 - graded completeness met its gates under leave-one-out development calibration; the binary v1 verdict is what failed.)* Only
  *relative, within-KC* claims are licensed. No absolute quality claim follows from any of this.
- Arm-independence was established at **LOW POWER** (4–6 calibration rows per arm). That is weak
  evidence, not proof, and travels with every result.
- M2 and TARGET remain at ceiling and discriminate between no arms; the amendment does not
  manufacture signal there.
