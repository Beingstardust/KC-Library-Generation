# Pending validation

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
