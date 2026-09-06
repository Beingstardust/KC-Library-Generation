# v3 evaluation plan — property-based, corpus-grounded

**Status: PLAN. Not pre-registered yet. Nothing here has been run.**
This document exists to be argued with before any GPU time is spent. Predictions and thresholds are
marked `TO FIX` where they must be committed before execution.

---

## 1. The reframing that drives everything

The three ablation families are not three "which is better" contests. Each substantiates a different
**property of the pipeline**, and two of the three are *consistency* claims rather than *ranking*
claims:

| family | property claimed | claim type | correct statistical form |
|---|---|---|---|
| extrinsic | retrieval performance | ranking | difference tests, IR metrics |
| intrinsic | **model-agnostic** — quality does not depend on which drafter | **equivalence** | TOST + variance decomposition |
| domain | **domain-agnostic** — quality does not depend on the subject | **equivalence** | TOST + variance decomposition |

**This invalidates the statistics used so far for two of the three families.** v2 tested the
intrinsic and domain families with *difference* tests and reported non-significance. A
non-significant difference is **not** evidence of equivalence — it is failure to detect one, which
is equally consistent with low power. Any reviewer will catch this. Claiming model-agnosticism
requires rejecting the hypothesis that the difference *exceeds* a pre-specified margin, which is a
different test [TOST].

---

## 2. What survives from v1/v2, and what does not

### Survives unchanged — instrument findings
These are properties of the judge, established by controlled experiment, and untouched by anything
below: batch-invariance requirement (F-07), the all-or-nothing length artifact (F-34, replicated
out-of-domain to within 0.021), serial-position sensitivity (F-45), the task-dependent sign flip
(F-46), determinism and cross-instrument agreement (F-12).

### Survives — abstention correctness
Already computed, corpus-grounded, needs no reference. Ground truth is the expert's
`support_state` (SUPPORTED 150 / UNSUPPORTED 7 / PARTIALLY 2), which is a judgement about the
**corpus**, made source-first. Scored as selective-refusal, per RefusalBench.

Result already in hand: Proposed catches 7/7 unsupported KCs (**0 missed refusals**); DOS-RAG misses
5 of 7. This cuts directly against the faithfulness ranking and is the clearest pipeline-safety
result we have.

### Survives, but reframed — groundedness
Per-claim faithfulness against the arm's **own retrieved evidence** measures *did the drafter stay
inside its evidence*. That is a **generation** property, not overall quality. Keep it, rename it
**groundedness**, and stop presenting it as "faithfulness to truth".

### Demoted — vital-nugget recall and context recall
- **Context recall is discarded as primary.** It has no rank cutoff, so comparing a 17-passage system
  against a 123-passage system on it is not well defined — which is exactly what F-45 exposed. IR
  solved this decades ago with `@k` metrics. Superseded by §3.1.
- **Vital-nugget recall is demoted to secondary**, reported with the seed-provenance caveat. Not
  deleted: it passed its adoption test and it is a valid *relative* completeness signal among the
  non-seed arms.

### Corrected — the seed-bias write-up (F-48)
F-48 over-claimed. The reference library was *designed* as expert-edited machine output, with
source-first review before seed exposure; `ACCEPT` means **corpus-verified complete**, not
unexamined, so a seed-arm score of 1.0 on that stratum is a true positive and not a tautology. The
`CHANGED` stratum is *selected on Qwen having failed*, so it is a biased-low sample for Qwen by
construction — a selection effect, which F-48 buried as a caveat instead of leading with. The
residual, real issue is narrower: **the nugget set inherits Qwen's content selection**, so
completeness comparisons carry an asymmetry that cannot be sized without control 6. That is a
limitation to disclose, not grounds for withdrawal. F-48 must be rewritten accordingly.

---

## 3. What to build

### 3.1 Retrieval evaluation via a pooled test collection <span>— for the extrinsic property</span>

The standard, 30-year-precedent method for comparing retrieval systems [TREC pooling].

**Construction.** For each KC, pool the top-*k* passages from every one of the 7 arms. Judge each
pooled passage **individually** for whether it supports describing that KC. Unjudged passages are
treated as non-relevant, per standard practice.

**Why this fixes the confound.** Each judgement sees exactly one passage, so the serial-position
failure (F-45) cannot occur. And `@k` metrics are *designed* for systems that return different
numbers of results — the thing that made context recall meaningless.

**Measured pool sizes** (union of arms' evidence per KC, computed from `ablation_rows.jsonl`):

| pool depth | mean pool / KC | total judgements |
|---|---|---|
| top-10 | 30.5 | **4 853** |
| top-20 | 51.9 | 8 246 |
| top-30 | 69.6 | 11 063 |
| uncapped | 166.1 | 26 417 |

**Recommendation: pool at top-20, report metrics at @5, @10, @20.** 8 246 judgements ≈ 6 h sequential.

**Metrics** — all standard and interpretable without explanation to an IR reviewer:
- `Recall@k` — of the known-relevant evidence for this KC, how much did the system surface in its
  top k?
- `Precision@k` — how much of what it surfaced was relevant? This is the efficiency claim, properly
  measured.
- `nDCG@k` — does it rank the relevant material highly?

**Pool composition, measured.** BaseDense contributes 19 349 passages unique to it (it returns 123
per KC); DOS-RAG 2 941; **the four Proposed-lineage arms contribute 0 unique passages** — everything
Proposed retrieves is also retrieved by another system. This is favourable for pool fairness: the
ground truth cannot be accused of being Proposed's own output.

**Disclosed limitation: pool bias** [Buckley et al. 2007]. Relevant passages outside the pool count
as non-relevant. Mitigated by pooling 7 diverse runs including one that returns 123 passages/KC.

**Blocker RESOLVED (2026-09-01).** `candidate_system_evidence` carries only `id` and `text`, with no
relevance score, so every `@k` metric depends on list order being rank order. Tested directly: the
expert evidence store records the Proposed lane's ranking explicitly in its ids
(`KC:comprehensive:0000`, `:0001`, ...). Comparing that ranking against the order in
`ablation_rows.jsonl` by text hash, **153 of 155 KCs are order-consistent**; the 2 exceptions are
duplicate-text artifacts, not reordering. List order is rank order.

*Caveat to disclose:* this verifies the Proposed lane, because that is the only lane with an
independent rank record. DOS-RAG and BaseDense are assumed order-preserving on the grounds that all
arms were extracted through the same `evidence_for_synthesis` contract. Cheap to confirm if their
packets are still on Cluster-B.

### 3.2 Corpus-grounded factuality <span>— generation quality, reference-free</span>

FActScore / VeriScore design: decompose the draft into atomic claims, then verify each against the
corpus using **verification retrieval that is independent of the pipeline under test**.

For each claim, retrieve the top-5 most similar passages from that KC's **union pool** (mean 166
passages) and judge support against those. Short contexts, so no F-45 exposure. Using the union pool
rather than a new index avoids building a retriever whose quality would contaminate the metric.

**The output is a 2×2 that names the failure mode**, which is what makes it interpretable:

| | supported by corpus | not supported by corpus |
|---|---|---|
| **supported by own evidence** | properly grounded | propagated error — evidence itself was wrong |
| **not supported by own evidence** | retrieval miss — the drafter knew it anyway (parametric leak) | **hallucination** |

This finally answers the parametric-leakage question F-40 gestured at, and it does so by measurement
rather than inference.

Cost: ~9 900 claims (1113 drafts × 8.9) + ~2 000 domain. Claim texts were **not** stored, so
re-decomposition is required (deterministic ⇒ identical claims). ≈ 1 h decompose + 8 h verify.

### 3.3 Acceptability triage <span>— human-anchored, corpus-grounded</span>

An editorial judgement per draft: **publishable as-is / minor edit / major edit / unusable**,
following post-editing effort scales from MT evaluation [MQM, post-editing levels].

**The reason this is strong:** we can validate the judge against real human labels. The expert's
`review_action` (`ACCEPT` 117 / `MINOR_EDIT` 10 / `MAJOR_EDIT` 15 / `REPLACE` 10) *is* this scale,
human-assigned, on 159 drafts, decided against the corpus. Validate on the seed arm, then apply to
all seven.

Note the asymmetry to disclose: those labels exist only for the seed arm, so validation is on Qwen
drafts. Whether judge–human agreement transfers to other drafters is an assumption, and should be
stated as one.

Cost: 1113 judgements ≈ 45 min.

### 3.4 Equivalence testing and variance decomposition <span>— for both agnosticism claims</span>

Run on the reference-free metrics from §3.2 and the abstention outcome.

**(a) TOST equivalence tests.** For each pair of drafters (and each pair of domains), test whether
the difference falls inside ±δ. Report the 90% CI against the equivalence bounds.

> `TO FIX before running:` the equivalence margin δ. This is a **scientific** choice and must be
> justified, not tuned. Two defensible anchors: (i) the judge's own measurement error, estimated from
> judge–human disagreement on the 36 annotated rows; (ii) a substantive threshold — the smallest
> quality difference that would change which drafter a practitioner deploys. **I recommend deriving δ
> from (i) and reporting (ii) as a sensitivity analysis.**

**(b) Generalizability-theory variance decomposition.** Decompose score variance into KC, drafter,
and residual components, and report each as a percentage plus a G-coefficient [Shavelson & Webb;
Brennan].

This is the number the paper actually wants: *"the drafter accounts for X% of quality variance
against the KC's Y%"*. A small drafter component **is** model-agnosticism, stated quantitatively,
and it degrades gracefully — if the property holds only within a competence band, the decomposition
shows that instead of forcing a binary.

**Predicted honest outcome:** the pipeline is *not* fully model-agnostic. DeepSeek-R1 sits far below
Qwen and Gemma on groundedness (0.8249 vs 0.9520 / 0.9680). The likely defensible claim is
**"model-agnostic across drafters of comparable capability, with graceful degradation"** — which the
variance decomposition can support and a difference test cannot.

---

## 4. Cost and sequencing

| step | GPU | depends on |
|---|---|---|
| 0. Verify evidence list order is rank order | none | **blocks 3.1** |
| 1. Pooled relevance judgements (top-20) | ~6 h | step 0 |
| 2. Claim re-decomposition | ~1 h | — |
| 3. Corpus-grounded verification | ~8 h | step 2 |
| 4. Acceptability triage | ~45 min | — |
| 5. Domain extension | ~2 h | steps 2–4 |
| 6. Equivalence + G-theory analysis | none | steps 3–5 |

≈ **18 h GPU**, one 24 h Cluster A job, plus CPU analysis. The Cluster A queue was empty at last check.

---

## 5. Open questions that must be settled before execution

1. ~~Is `candidate_system_evidence` rank-ordered?~~ **RESOLVED — yes**, 153/155 verified. §3.1 is
   unblocked.
2. **What is δ?** Blocks §3.4. Scientific choice, must be pre-registered.
3. **Do we extend the domain runs to a second drafter?** Domain-agnosticism is currently confounded
   with drafter — only Qwen ran on mathematics and sociology, so "domain-agnostic" and
   "Qwen-on-other-domains" are the same measurement. One more drafter × 220 rows ≈ 2 h would
   decouple them.
4. **Is control 6 in scope?** A seed-blind reconstruction of ~30 references is the only thing that
   would restore vital-nugget recall to primary status. It needs a human who has not seen any system
   output. If that is not available, completeness stays secondary and the paper says so.

---

## 6. What this plan deliberately does not do

- It does not discard the reference library. The library becomes a **validation asset** —
  the source of human-anchored labels for §3.3 and the corpus-support ground truth for abstention —
  rather than the measurement instrument. That is a better use of it, and it is immune to the seed
  concern because `support_state` and `review_action` are judgements about the corpus.
- It does not add metrics for their own sake. Every metric above maps to exactly one claim the paper
  makes, and any metric that maps to no claim is not run.
