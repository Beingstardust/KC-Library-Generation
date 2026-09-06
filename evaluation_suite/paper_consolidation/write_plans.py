"""Emit the non-claims document, the pending-validation register, and the three bounded plans."""
from pathlib import Path

D = Path(__file__).parent
PLANS = D.parent / "reference_eval" / "locks"

FILES = {}

FILES[D / "PAPER_NONCLAIMS.md"] = """# What we do not claim

A guard against accidental overclaiming while writing. Every line here is a sentence that must **not**
appear in the thesis, followed by what may be said instead.

| We do NOT claim | Say instead |
|---|---|
| Proposed universally outperforms DOS-RAG. | Proposed ranks relevant material earlier and operates on a smaller evidence set; DOS-RAG recovers more by rank 20 under its larger budget. |
| DOS-RAG cannot construct KC drafts. | DOS-RAG is a strong high-recall comparator that produces usable drafts; the question is what KC-specific evidence construction adds. |
| The Qwen-seeded references are unbiased. | The seed-blind audit found no distortion or unsupported assertion in the audited sample; residual content-selection and support-boundary risks remain. |
| The reference is lexically independent of Qwen. | The reference is machine-seeded and explicitly not independent of Qwen; evaluation is semantic, and the residual asymmetry is localised to the Qwen-lineage arms' completeness figures. |
| All seven corpus-gap labels are independently confirmed. | Seven KCs are labelled corpus-unsupported under the adjudicated standard; a seed-blind reviewer disagreed on all three sampled, and revalidation is pending. |
| The groundedness arm ordering is judge-independent. | Only the endpoints reproduce across instruments; the middle ordering is instrument-sensitive. |
| The pipeline is model-agnostic. | Gemma >= Qwen > DeepSeek is stable in mathematics and data-mining across instruments; the equivalence result is evaluator-dependent. |
| The pipeline is domain-agnostic. | Partial cross-domain transfer, with a persistent mathematics effect. |
| 99.83% end-to-end KC-generation reproducibility. | A rerun of the claim-decomposition and judging stages reproduced 99.83% of matched per-claim decisions. Retrieval and drafting were not re-run. |
| MiniCheck establishes human truth. | MiniCheck is an independent entailment verifier used for instrument-sensitivity analysis; neither instrument is ground truth. |
| The pooled relevance labels are human gold. | Automated pooled relevance judgements produced by the frozen judge; no human validation exists. |
| Similar P@10/R@10 proves statistical equivalence. | The paired intervals contain zero; no retrieval equivalence margin was pre-registered, so no equivalence test is reported. |
| Batch-invariant serving is required for reproducible LLM judging. | In our configuration, concurrent serving changed a judgment at temperature zero; batch-invariant kernels removed the observed discrepancy. |
| LLM judges are serial-position sensitive. | Our judge, in our configuration, showed severe serial-position sensitivity as the passage set grew. |
| A judge failing a binary rubric can always be fixed by grading. | For completeness in this evaluation, retaining graded information substantially improved agreement with the available human labels. |
| The automated editorial triage measures quality. | The triage failed: it did not discriminate between arms and agreed with expert codes only 0.462 exactly. |
| Four in five drafts are accurate. | Approximately four in five **seed-arm** drafts required no more than local human editing under the adjudicated construction workflow. This is a review-burden figure, not an accuracy figure, and not a cross-model comparison. |
"""

FILES[D / "PAPER_PENDING_VALIDATION.md"] = """# Pending validation

Empirical work that is **specified but not executed**. Nothing here has been run. Each item names the
claims it blocks and the wording permitted until it is done.

---

## P1 — Seed-blind revalidation of the seven corpus-gap KCs
**Blocks:** `ABSTAIN_UNSUPPORTED` (and the corpus-gap component of `REVIEW_BURDEN`).

**Why needed.** The abstention result rests entirely on which KCs are labelled corpus-unsupported.
The seed-blind audit sampled three of those seven and classified **all three as supported**. Until
that disagreement is adjudicated, the 7/7-versus-5/7 comparison is measuring a contested boundary.

**Minimum sufficient design.** All seven KCs; one seed-blind reviewer with corpus access and no sight
of any system output, prior support state, or previous rationale; four-way classification
(SUPPORTED / PARTIALLY_SUPPORTED / UNSUPPORTED / AMBIGUOUS); then adjudication of disagreements.
Plan: `SUPPORT_BOUNDARY_REVALIDATION_PLAN.md`.

**Wording permitted until complete.** The conditional formulation in the ledger, marked
`PROVISIONAL_PENDING_SUPPORT_BOUNDARY_AUDIT`. Do not headline as a safety result.

---

## P2 — Human validation of the pooled relevance labels
**Blocks:** strength of `RET_PROP_VS_BASE`, `RET_DOS_NDCG`, `RET_DOS_TOP10`, `RET_DOS_DEEP`.

**Why needed.** All 8,246 relevance labels were produced by the same judge whose behaviour the rest
of the campaign shows to be construct-sensitive. The retrieval conclusions therefore inherit
evaluator-validity risk that no amount of bootstrapping addresses.

**Minimum sufficient design.** Stratified sample across configuration (Proposed / DOS-RAG /
BaseDense), predicted label (relevant / not), rank band (1-5 / 6-10 / 11-20), and hierarchy branch.
Plan: `POOLED_QREL_HUMAN_VALIDATION_PLAN.md`.

**Wording permitted until complete.** Every retrieval sentence must carry "under automated pooled
relevance judgements".

---

## P3 — Human audit of nugget extraction and VITAL assignment
**Blocks:** validity of every completeness figure (`vital-nugget recall`, the adoption test, and
`JUDGE_COMPLETENESS_CAL` indirectly).

**Why needed.** Completeness is defined as reference -> nuggets -> VITAL/OKAY -> coverage. The
middle two steps are automated and **have never been audited by a human**. An error there propagates
to every completeness number without being visible in any agreement statistic.

**Minimum sufficient design.** Stratified KC sample; per nugget check omission, invention, formula
and procedure preservation, over-fragmentation, and defensibility of the VITAL/OKAY label.
Plan: `NUGGET_DECOMPOSITION_VALIDATION_PLAN.md`.

**Wording permitted until complete.** Completeness results must be reported as resting on an
unaudited decomposition step, listed as a residual measurement limitation.
"""

FILES[PLANS / "SUPPORT_BOUNDARY_REVALIDATION_PLAN.md"] = """# Support-boundary revalidation plan (P1)

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
"""

FILES[PLANS / "POOLED_QREL_HUMAN_VALIDATION_PLAN.md"] = """# Pooled qrel human-validation plan (P2)

**Status: PLAN. Not executed. Do not run without explicit authorization.**

## The problem

The retrieval comparison rests on 8,246 passage-level relevance labels, all produced by the frozen
Selene judge:

| grade | n |
|---|---|
| DEFINITIONAL | 1,751 |
| RELATED | 2,505 |
| NOT_RELEVANT | 3,990 |

No human has validated any of them. The rest of this campaign has repeatedly shown that this judge's
behaviour is construct- and configuration-sensitive, so the retrieval conclusions inherit a validity
risk that paired bootstrapping does not touch: resampling KCs quantifies sampling variability, not
label correctness.

## Sample design

Stratified, with strata chosen so that a systematic labelling error would be visible rather than
averaged away:

| facet | levels |
|---|---|
| retrieval configuration | Proposed · DOS-RAG · BaseDense |
| predicted label | relevant (DEFINITIONAL or RELATED) · NOT_RELEVANT |
| rank band | 1-5 · 6-10 · 11-20 |
| hierarchy branch | at least four distinct top-level branches |

Suggested 15 passages per configuration x label x rank-band cell = **270 passages**, which is about
3% of the pool and enough to detect a systematic error of moderate size in any single cell.

Record the sampling probability per stratum. Agreement must be reweighted to pool proportions;
unweighted agreement over a stratified sample is not an estimate of pool-level agreement.

## Task given to the human

Identical wording to the automated prompt, so that any disagreement is attributable to the judge
rather than to a different question being asked. One passage at a time, no batching, no visibility of
the automated label.

## Reporting

- Per-stratum and reweighted overall agreement, with Gwet AC1 alongside raw agreement (the label
  distribution is skewed, so kappa will behave badly for the reasons already documented).
- The confusion matrix, so that the *direction* of any systematic error is visible.
- If agreement is high: retrieval claims move from `SUPPORTED_WITH_SCOPE` to `SUPPORTED`, and the
  "automated pooled relevance judgements" qualifier may be relaxed to a footnote.
- If agreement is poor: the retrieval ranking claims are downgraded, and the pooled qrels are
  reported as an automated proxy with measured error.

## What this cannot fix

Pool incompleteness. Passages ranked below 20 by every configuration were never judged by anyone and
are counted non-relevant regardless of what a human would say. That limitation is structural and
must remain stated.
"""

FILES[PLANS / "NUGGET_DECOMPOSITION_VALIDATION_PLAN.md"] = """# Nugget decomposition and VITAL-assignment validation plan (P3)

**Status: PLAN. Not executed. Do not run without explicit authorization.**

## The problem

Completeness is a four-step construct:

    expert reference -> nuggets -> VITAL / OKAY -> semantic coverage by the candidate

Steps two and three are automated and **have never been audited**. The campaign has validated the
fourth step (against 36 human labels) and frozen the first. An error in decomposition or importance
labelling propagates into every completeness number and is invisible to any agreement statistic
computed downstream, because the nuggets are the yardstick rather than the thing measured.

Scale of the unaudited artifact: **1,185 nuggets across 151 KCs, of which 475 are labelled VITAL.**

## Sample design

Stratify so that the known failure mode is represented rather than averaged away:

| facet | levels |
|---|---|
| reference length | short · medium · long tercile |
| content type | definitional prose · formula-bearing · procedure-bearing |
| nugget count | low · high |
| hierarchy branch | at least four distinct branches |

Suggested **25 KCs**, giving roughly 200 nuggets — enough to detect a systematic decomposition
pathology, not enough to estimate a precise per-nugget error rate. State that limit.

Formula-bearing references must be over-sampled: the one known decomposition failure
(`KC_CLF_NB_009`) was formula-driven, and mathematics is the weakest domain, so this is where a
defect is most likely.

## Checks, per KC

**Decomposition fidelity**
1. Is any substantive reference content missing from the nugget set?
2. Does any nugget assert something the reference does not?
3. Are formulae preserved exactly, including symbols and subscripts?
4. Are multi-step procedures preserved as usable steps rather than flattened?
5. Is the decomposition over-fragmented — one fact split across nuggets such that a correct
   description could miss one and be penalised?

**Importance labelling**
6. Is each `VITAL` label defensible: would a description omitting it be materially incomplete?
7. Is each `OKAY` label defensible: is it genuinely elaboration rather than definition?
8. Is the VITAL share plausible for this KC? Corpus-wide it is 40.1%; sharp per-KC departures
   deserve a look.

## Reporting

Per-check error counts with examples, and a judgement on whether any observed error is *systematic*
(affecting a content type) or *idiosyncratic*. A systematic error is far more damaging: it would bias
whole strata of the completeness results in one direction.

## Consequences

- **Few errors, none systematic.** Completeness results keep their current status; the residual
  limitation is downgraded to a measured error rate.
- **Systematic error found.** Completeness figures must be recomputed or withdrawn for the affected
  content type. Note this would touch the adoption test and, indirectly, the completeness calibration
  in `JUDGE_COMPLETENESS_CAL`.

## Explicit non-goal

This audit does **not** revisit the reference text. The reference is frozen. The question is only
whether the automated decomposition faithfully represents it.
"""

for path, text in FILES.items():
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path.relative_to(D.parent)}")
