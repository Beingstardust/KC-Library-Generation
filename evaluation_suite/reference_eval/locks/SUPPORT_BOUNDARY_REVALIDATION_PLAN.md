# Support-boundary revalidation plan (P1)

**Status: PLAN. Not executed. Do not run without explicit authorization.**

## The problem

Seven KCs carry `support_state = UNSUPPORTED`, meaning the course corpus does not support writing a
description. Those labels drive the abstention comparison: Proposed abstained on 7/7, DOS-RAG drafted
on 5/7.

The seed-blind reconstruction audit included three of these seven in its sample. The independent
reviewer classified **all three as SUPPORTED**. Two readings are possible and the audit cannot
separate them:

1. the original adjudication was too strict, and the corpus does support these KCs; or
2. the seed-blind reviewer applied a looser threshold, having produced 24-word references citing
   about one passage each.

Either way, the boundary is contested, and the abstention result is a measurement of that boundary.

## Population

All **seven** KCs currently adjudicated `NO_REFERENCE_CORPUS_UNSUPPORTED`. Not a sample — the
population is small enough to enumerate, and sampling would leave the same ambiguity.

Recommended: add **five** KCs adjudicated `SUPPORTED` as blinded controls, so the reviewer cannot
infer that every item is expected to be a gap. The reviewer is not told the mix.

## Reviewer conditions

Provided: KC id, canonical name, hierarchy path, full corpus access with search.

Withheld: the Qwen seed, the current support state, the existing reference, any system output from
any arm, any judge output, and the previous expert's rationale or reason codes.

If the reviewer has previously seen this project's evaluation results, they are not eligible.

## Task

For each KC, before writing anything, record:

| classification | meaning |
|---|---|
| `SUPPORTED` | The corpus contains enough to write a correct, self-contained description. |
| `PARTIALLY_SUPPORTED` | The corpus touches the concept but something definitional is missing. |
| `UNSUPPORTED` | The corpus does not support describing this concept. |
| `AMBIGUOUS` | Genuinely cannot be decided from the corpus. |

Require, for every classification, the passages consulted (document, locator, short quotation) and a
one-paragraph justification. A classification without cited passages is not usable.

## Adjudication

Disagreements between the original adjudication and the new one go to a third reviewer who sees both
justifications and both passage sets, but still not the system outputs. Record the adjudicated state
and the reason.

## Outcomes and what each licenses

- **Original labels upheld (>= 6 of 7).** `ABSTAIN_UNSUPPORTED` moves to `SUPPORTED_WITH_SCOPE`, and
  the abstention comparison may be reported as a substantive result with n=7 stated.
- **Substantial disagreement (>= 3 of 7 overturned).** The abstention comparison is withdrawn as a
  safety claim. The counts remain in the record as a descriptive property of the adjudicated
  standard, and the disagreement itself becomes the reportable finding.
- **Mixed.** Report per-KC, and confine any claim to the KCs whose status survived adjudication.

A result that overturns the original labels is a legitimate outcome, not a failure of the audit.
