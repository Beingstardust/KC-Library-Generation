# Pre-registration — F-45 evidence-dilution test

**Status: PRE-REGISTERED. Written and committed BEFORE the test is run.**
The commit adding this file contains the protocol and the implementing script and **no results**.

## Why this test exists

The F-40 calibration (PREREG_F40_calibration.md) returned `B = 0.0000`: shown the same clean
reference passage, the assignment prompt and the context prompt both recover **100%** of vital
nuggets. The registered hypothesis — that the context prompt is inherently stricter in wording — is
**disconfirmed**. There is no constant label-severity offset.

But that test saturates at the ceiling, so it has **no power** to detect a confound that scales with
the *size* of the evidence set, and it explicitly recorded `B` as a lower bound. The sharper threat
is dilution:

> Context recall is measured over evidence sets of very different sizes — Proposed 17.2 passages,
> DOS-RAG 33.7, BaseDense 123.1. If a judge's ability to spot a nugget degrades as the passage set
> grows, then BaseDense's low context recall (0.4664) is partly an artifact of **having more
> passages**, not of retrieving worse content.

This matters more than F-40 did, because BaseDense has both the largest evidence set and the lowest
score, and the extrinsic retrieval ranking is the paper's central claim. A reviewer will ask this.

## The test

For each of the 151 scored KCs, construct a synthetic evidence set that **provably contains every
nugget**: the KC's own expert reference, embedded among `K` distractor passages.

- Distractors are drawn from the retrieved evidence of KCs in a **different top-level cluster**
  (`KC_CLF` / `KC_CLU` / `KC_EVAL` / …), so they are realistic prose but topically separated. Drawing
  from the same cluster risks distractors genuinely containing the nuggets, which would mask exactly
  the effect we are testing for.
- The reference is placed at a **uniformly random position** with a fixed seed, so the measurement
  averages over serial position rather than confounding with "lost in the middle".
- `K ∈ {16, 32, 122}`, matching the three observed mean evidence sizes (17.2, 33.7, 123.1) once the
  reference itself is counted.

Ground truth is 1.0 at every level, by construction. Same frozen judge, decoding, blinding and
sequential execution as every other v2 stage. 151 × 3 = **453 calls**.

## Registered predictions

Fixed before the run; not adjustable afterwards.

1. **Flat and high** (recall ≥ 0.95 at every `K`, and the 16→122 drop < 0.03): no meaningful
   dilution. Evidence-set size does not depress the judge, the extrinsic context-recall ranking is
   **not** a set-size artifact, and the central retrieval claim stands as reported. F-45 closes as
   NO EFFECT.
2. **Monotone decline** (recall falls materially as `K` grows, 16→122 drop ≥ 0.03): dilution is
   real. BaseDense's context recall is depressed by set size, the raw extrinsic ranking is
   **partly an artifact**, and the report must either apply the measured correction or downgrade the
   context-recall ranking to non-robust. F-45 closes as CONFOUNDED.
3. **Non-monotone / noisy**: report the observed curve, treat the magnitude at `K=122` as the
   relevant bound, and caveat accordingly.

## What the outcome can and cannot license

- A flat result does **not** make context recall valid in absolute terms; `JUDGE_QUALIFIED=false`
  still stands. It removes one specific confound from the *relative* retrieval comparison.
- A declining result does **not** invalidate the nugget-recall or faithfulness findings, which are
  measured on single drafts of comparable length and are separately length-adjusted.
- The distractors are topically separated by construction, which is the *favourable* case for the
  judge. Real retrieved sets are topically adjacent and therefore harder. Any decline measured here
  is a **lower bound** on the decline under real conditions.
