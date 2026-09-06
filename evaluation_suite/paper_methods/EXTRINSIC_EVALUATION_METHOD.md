# Extrinsic Evaluation Method (retrieval architecture comparison)

## Question

With the drafter held fixed at Qwen3.8 27B, which retrieval/evidence architecture produces the strongest expert-reference-aligned KC library?

## Design

| Arm | Retrieval |
|---|---|
| `extrinsic P-Q` | Proposed |
| `extrinsic B-Q` | Base Dense |
| `extrinsic DOS-Q` | native/full DOS-RAG |

All three built at commit `450c88c` under `controlled_comparator` prompt mode, with one shared decoding configuration. `controlled_comparator` matters: it keeps the Proposed architecture's drafting instruction out of the model's view, matching the structural constraint that Base Dense and DOS-RAG never carried one. Commit parity, decoding parity, and 159/159 KC-set identity are re-verified before scoring.

**Note on the Proposed/Qwen arm.** `extrinsic P-Q` is a different artifact from `intrinsic P-Q` — different commit, different prompt mode, different hash, and only 17/159 identical drafts. They are not interchangeable, and substituting one for the other would break the within-experiment control the other was built to satisfy. This is why the evaluation uses six unique primary arms rather than the five a shared-Proposed/Qwen assumption would imply.

The seeding arm is `intrinsic P-Q`, so the extrinsic Proposed arm is one step removed from the reference seed. It is *not* independent of it either — same drafter model on byte-identical evidence — and must not be described as such.

## Reported measures

| Measure | What it isolates |
|---|---|
| ~~`retrieval_reference_recall` (M4A)~~ | **SUPERSEDED 2026-09-02.** Never validated - M4A has zero human labels (`INSUFFICIENT_VALIDATION_SUPPORT`). The primary retrieval diagnostic is now the pooled test collection: Recall@k / Precision@k / nDCG@k over per-passage relevance judgements. See `PAPER_CLAIM_LEDGER.md` sections A. |
| `faithfulness_precision` | did the draft stay within its supplied evidence |
| `authority_correctness_precision` | was the content correct per reference and source |
| `core_complete` | did the draft retain the defining content |
| `materially_sound` | strict conjunction, primary curriculum-coverage outcome |
| `unsafe_draft` rate | wrong target, or incorrect/ungrounded content |
| `safe_gap_handling` | behavior on the 7 adjudicated corpus gaps |
| evidence volume | descriptive context for the above |
| technical completion | parse failures and abstentions, reported not repaired |

## On retrieval coverage

Retrieval coverage was measured as the proportion of substantive expert-reference claims supported by the evidence supplied to the drafter. We did **not** equate incomplete reference coverage with evidence inadequacy, since a concise but sufficient evidence set need not reproduce every reference detail.

The holistic evidence-adequacy classifier that would have made that judgment directly was demoted to exploratory during development after it reproducibly treated nonessential reference details as mandatory (see `../reference_eval/output/m4_scope_decision.md`). Retrieval coverage is therefore reported as a continuous diagnostic and interpreted alongside the generation-side measures, never thresholded into a sufficiency verdict.

## Failure decomposition

The reason M3 and M4 are separate relations is that together they localize *where* a pipeline fails:

- reference content **absent from retrieval** → retrieval failure
- content **present in retrieval but absent from the draft** → drafting/utilization failure
- content **in the draft but not in the supplied evidence** → faithfulness failure
- **wrong target despite apparently relevant evidence** → target-binding failure

A system with high retrieval recall and low completeness is failing to use what it retrieved; one with low retrieval recall cannot be blamed for the resulting omission. An aggregate quality score cannot make this distinction, which is why no weighted composite is constructed.

## Statistics

Paired by KC across all three arms. Cochran Q omnibus, then pairwise exact McNemar with Holm correction inside the extrinsic family (kept separate from the intrinsic family). Wilson 95% intervals for proportions; deterministic paired bootstrap (5,000 replicates) for continuous per-KC metrics with mean difference, 95% interval, and win/tie/loss counts. Superiority is not inferred from raw percentages.

## Matched-budget DOS-RAG

Evaluated **after** primary results are frozen and reported strictly as a **sensitivity analysis**, never as a primary comparator. It asks whether DOS-RAG retains quality when its evidence allowance is constrained to approximately the Proposed architecture's evidence volume, comparing native DOS, matched DOS, and Proposed on the same reference-based metrics.

## The result this design must remain able to produce

DOS-RAG beating Proposed. The evaluation is built to localize failures wherever they fall, and a finding that a different retrieval architecture produces a better library is a legitimate outcome to report.
