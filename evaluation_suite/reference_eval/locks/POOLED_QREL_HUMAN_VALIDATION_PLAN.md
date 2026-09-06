# Pooled qrel human-validation plan (P2)

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
