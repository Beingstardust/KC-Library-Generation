# Pre-registration — F-40 prompt-asymmetry calibration

**Status: PRE-REGISTERED. Written and committed BEFORE the calibration is run.**
The commit adding this file contains the protocol and the implementing script and **no results**.

## The problem

The v2 report's organising claim is **failure attribution**: context recall is measured on the
retrieved evidence with no generator in the loop, nugget recall is measured on the draft, and the
gap between them is read as "the drafter used / failed to use the available content".

Every arm except `intrinsic_P-D` shows nugget recall **above** context recall (+0.04 to +0.14).
Read naively that says drafts convey content the retrieval did not supply — which would mean
parametric leakage. F-40 records that this reading is **not licensed**, because the two numbers come
from different prompts with different label sets:

| | prompt | labels |
|---|---|---|
| nugget recall | "does this DESCRIPTION convey the nugget" | SUPPORTED / PARTIAL / NOT_SUPPORTED |
| context recall | "do these PASSAGES contain what is needed to state it" | PRESENT / PARTIAL / ABSENT |

The context prompt asks for something strictly harder ("contains the information needed to state
it") than the assignment prompt ("states this fact, or states something that entails it"). A
systematic offset between the two would produce a positive gap for **every** arm regardless of
generator behaviour — which is close to what is observed.

So the gap as reported confounds two things: real generator behaviour, and a constant instrument
offset. Absolute gaps are uninterpretable until the offset is measured.

## The calibration

Measure both prompts' **ceiling on identical content**, where the correct answer is known.

The nuggets for a KC were extracted *from* that KC's expert reference. So when the reference itself
is supplied as the material being judged, every nugget is present **by construction** and both
prompts should return 1.0. Any shortfall is prompt-specific conservatism, not a property of any
pipeline.

- **Ceiling_assign** — `build_nugget_assignment_prompt(nuggets, reference_text)`:
  the reference judged as if it were a candidate description.
- **Ceiling_context** — `build_context_recall_prompt(nuggets, reference_as_single_passage)`:
  the reference judged as if it were a retrieved passage.

Both over the same 151 scored KCs, same frozen judge, same decoding, same blinding enforcement.
302 calls total.

**Bias estimate:** `B = Ceiling_assign - Ceiling_context`, computed per KC and averaged.

**Adjusted gap:** `adjusted_gap(arm) = observed_gap(arm) - B`.

## Registered predictions

Fixed before the run; not adjustable afterwards.

1. **If `B` is large and positive** (say > 0.05) and comparable in size to the observed gaps, then
   the positive gaps are largely instrument offset. The absolute attribution reading is **withdrawn**
   and only *relative* gaps across arms are reported. F-40 closes as CONFIRMED-CONFOUNDED.
2. **If `B` is near zero** (|B| < 0.02), the prompts are on a common scale, the absolute attribution
   reading is licensed, and F-40 closes as REFUTED — the gap means what the report says it means.
3. **If `B` is negative**, the context prompt is the *more* generous one and the observed positive
   gaps understate real generator contribution. Reported as such.

In all three cases the **relative** ordering of arms by gap is unaffected, because `B` is a constant
subtracted from every arm. The paired within-family comparisons in the report therefore stand
regardless of outcome; only the absolute reading of the gap is at stake.

## Limits stated in advance

- The ceiling is measured on the reference, which is *cleaner and shorter* than real retrieved
  evidence (17-123 passages). `B` is therefore a **lower bound** on the true offset under realistic
  conditions; a long noisy passage set plausibly depresses the context prompt further.
- This calibrates the instrument against itself. It does **not** address absolute
  `JUDGE_QUALIFIED=false`, and nothing here licenses absolute quality claims.
- Same single-annotator and non-random-exclusion caveats as the rest of v2 (F-36, F-42).
