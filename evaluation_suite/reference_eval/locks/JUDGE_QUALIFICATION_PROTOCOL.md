# Judge Qualification Protocol (FROZEN)

**Frozen:** 2026-08-25, **before any human calibration label existed** and before any Selene–human agreement statistic was computed.

At the moment of freezing, the calibration workbook contained **zero** human annotations across all 180 rows and all eight label fields. No Selene prediction on the calibration sample had been produced. The thresholds below therefore cannot have been selected in response to observed results — the results did not exist.

Machine-readable twin: `JUDGE_QUALIFICATION_PROTOCOL_FROZEN.json` (hashed).

---

## Status of these thresholds

These are **project-level acceptance thresholds**, chosen for this study's risk profile. They are **not** claimed to be universal thresholds from the literature. They are stated here so that the qualification decision is a pre-committed test rather than a post-hoc rationalisation.

Once human results are opened, these values may not be changed. If the frozen evaluator fails, **it fails** — it is not repaired against the validation labels and re-tested on the same labels.

---

## 5A. Structural reliability (applies to all tasks)

| Requirement | Threshold |
|---|---|
| Structured / contract validity | **≥ 99.5%** |

Any systematic truncation, or any semantic branch shown to be inaccessible, is an **automatic failure regardless of semantic agreement**. This clause exists because a schema ordering was once found that produced 100% valid JSON while making the `MATERIAL_OMISSION` branch unreachable — high validity with a dead branch is worse than visible breakage, because it is invisible.

## 5B. M1 — Evidence faithfulness

| Metric | Threshold |
|---|---|
| Raw agreement | ≥ 85% |
| Gwet AC1 | ≥ 0.70 |
| FAIL recall | ≥ 85% |
| False-PASS rate | ≤ 10% |

*Rationale:* a false PASS lets an unsupported draft claim be treated as grounded. False FAILs are undesirable but less dangerous for a trust-oriented primary outcome.

## 5C. M2 — Reference/source correctness

| Metric | Threshold |
|---|---|
| Raw agreement | ≥ 85% |
| Gwet AC1 | ≥ 0.70 |
| FAIL recall | ≥ 85% |
| False-PASS rate | ≤ 10% |

*Rationale:* safety-critical. A fluent but materially incorrect claim must not routinely pass.

The `REFERENCE_SILENT_BUT_SOURCE_SUPPORTED` escape path **must remain operative**, so that legitimate non-Qwen content is not penalised merely because the expert reference is silent about it.

## 5D. M3 — Core completeness

| Metric | Threshold |
|---|---|
| Raw agreement | ≥ 80% |
| Gwet AC1 | ≥ 0.65 |
| **PASS recall** | ≥ 75% |
| **FAIL recall** | ≥ 75% |

*Rationale:* completeness has a larger legitimate human-boundary component than direct factual support, so a slightly lower agreement gate is allowed. But M3 is gated on **both** directions: systematic one-sided rejection is not acceptable, and gating only on FAIL recall would reward exactly that.

## 5E. TARGET — Alignment

| Metric | Threshold |
|---|---|
| Raw agreement | ≥ 80% |
| Gwet AC1 | ≥ 0.65 |
| FAIL recall | ≥ 85% |
| False-PASS rate | ≤ 10% |

*Rationale:* wrong-target drafts are a major failure mode in this project. The evaluator must retain high sensitivity to sibling / near-neighbour substitution.

## 5F. M4A — Retrieval-reference claim support

Qualification applies to the **atomic support decisions**, not to the derived continuous recall scalar. The scalar is deterministically computed from the atomic labels, so validating the scalar directly would confuse measurement error with aggregation.

| Metric | Threshold |
|---|---|
| Raw atomic-decision agreement | ≥ 85% |
| Gwet AC1 | ≥ 0.70 |
| `SUPPORTED_BY_RETRIEVAL` recall | ≥ 80% |
| `NOT_SUPPORTED_BY_RETRIEVAL` recall | ≥ 80% |

The LLM's per-KC continuous recall is **not** required to match a human scalar exactly.

## 5G. M4B — Holistic evidence adequacy

**No qualification gate. Not used.** Demoted to exploratory on 2026-08-25 for construct-validity failure. It may not be re-promoted, including if its numbers later improve.

---

## 6. Small-denominator safeguard

Every task must report its **human PASS count** and **human FAIL count** alongside any rate.

If a qualification statistic rests on **fewer than 10** relevant positive or negative examples, it is flagged `SMALL_DENOMINATOR` and reported with the exact numerator/denominator and a **Wilson 95% interval**. A criterion is never silently declared qualified from a tiny class count.

If class prevalence is too extreme for a gate to be tested meaningfully, the task is reported as **`INSUFFICIENT_VALIDATION_SUPPORT`** rather than manufacturing confidence. Resampling is **not** automatic — the project owner decides whether more blinded human examples are needed.

---

## 7. Human gold resolution

- Two independent labels agree → use that label.
- They disagree → **adjudicate before judge qualification**, with the adjudicator blind to Selene's prediction.
- Record annotator A, annotator B, adjudicated label, adjudication rationale.
- Human labels are **frozen before** any comparison with Selene predictions.

Human–human agreement is computed **first**. If it is poor on a task, the construct is flagged as potentially insufficiently reproducible — Selene is not blamed first. Changing the rubric after seeing these results requires formally declaring the current validation set **burned**.

---

## 10. Qualification decision rule

Each task is classified **QUALIFIED** / **NOT_QUALIFIED** / **INSUFFICIENT_VALIDATION_SUPPORT**.

Selene is qualified for the primary final campaign only if **M1, M2, M3 and TARGET are all QUALIFIED**.

If **M4A alone** fails, that does **not** invalidate M1/M2/M3/TARGET. It is reported that automated retrieval-reference recall is unvalidated, and a separate decision is taken on whether that diagnostic needs human scoring or another validated method.

If any of M1, M2, M3, TARGET fails its gate → `JUDGE_QUALIFIED = false`, and no final system-quality evaluation is run with that judge.

## 11. No averaging across tasks

Mean qualification score, mean AC1, and overall judge accuracy are **not** acceptance rules. Qualification is **criterion-wise**. A judge with excellent correctness but poor faithfulness is not qualified because the average looks good.

---

## Reported statistics (every task)

human n · human PASS n · human FAIL n · raw agreement · Gwet AC1 · Cohen κ (secondary only) · PASS precision · PASS recall · FAIL precision · FAIL recall · false-PASS count and rate · false-FAIL count and rate · Wilson intervals where relevant · threshold · decision.

Gwet AC1 is primary rather than Cohen κ because these label distributions are heavily imbalanced and κ behaves paradoxically under high prevalence — a documented property with a hand-verified demonstration in this project's statistics module (90% raw agreement yielding κ = 0.0 while AC1 ≈ 0.89).

---

## Anti-contamination clauses

1. Selene inference on the calibration rows completes and is **hashed before** any agreement statistic is computed. Metrics are not visible while inference is incomplete.
2. Human calibration data is **validation data, not development data**. M1 PASS recall, TARGET PASS recall, M2 false PASS and M3 false FAILs may **not** be tuned against it.
3. The evaluator is under hard freeze: model, revision, tokenizer, vLLM version, chat template, decoding parameters, max-token policy, response schemas, prompt wording, rubric definitions, claim-decomposition protocol, reason-code definitions, expert reference, candidate artifacts, calibration sample and blinding map are all fixed.
4. If the frozen evaluator fails qualification, it fails. It is not repaired against these labels and re-tested on them.
5. `SENT_032` / `SENT_033` remain `GOLD_PENDING` development sentinels. They are **not** calibration rows and do not block human annotation.

---

## Seed-bias diagnostic (post-freeze, threat-to-validity)

After human labels and Selene predictions are frozen and arm identities restored, report **by arm**: judge–human disagreement rate, false-PASS rate, false-FAIL rate, and the two audit flags (`VALID_SOURCE_SUPPORTED_ALTERNATIVE_BEYOND_REFERENCE`, `POSSIBLE_REFERENCE_DEFECT`).

The question is whether legitimate non-Qwen formulations are disproportionately flagged because the expert reference originated from Qwen. **Absence of bias may not be inferred from a nonsignificant difference** — counts, proportions and confidence intervals are reported, and this stays a disclosed threat to validity.

Differential-error diagnostics are additionally reported by drafter family, retrieval architecture, reference edit-action stratum, formula vs non-formula, and procedure vs non-procedure. These are **diagnostic only**: the judge is never selected or tuned on the basis of which system it favours.
