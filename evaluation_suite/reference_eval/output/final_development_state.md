# Final Development State — Reference-Based KC Evaluator

**Date:** 2026-08-25
**Status:** Evaluator frozen. Ready for human calibration. **`JUDGE_QUALIFIED = false`.**

> **DEVELOPMENT SENTINEL PERFORMANCE.** Everything below comes from a 36-case development suite whose purpose is to check that the evaluator can measure the intended construct. It is **not** a judge qualification pass. Formal qualification happens only against blinded human labels.

---

## 1–6. Final penalty-free sentinel results

Judge: `selene-1-llama-3.3-70b`. Decoding: `temperature=0, top_p=1, frequency_penalty=0.0, presence_penalty=0.0, repetition_penalty=1.0`.

| Task | Scope | n valid | Agreement | PASS prec | PASS rec | FAIL prec | FAIL rec | false PASS | false FAIL | NOT_JUDGEABLE | gold pending |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **M1** faithfulness | primary | 34 | **88.2%** | 100% | 77.8% | 80.0% | **100%** | **0** | 4 | 0 | 0 |
| **M2** correctness | primary | 31 | **96.8%** | 94.1% | 100% | 100% | 93.3% | 1 | **0** | 0 | 2 |
| **M3** core completeness | primary | 32 | **90.6%** | 100% | 82.4% | 83.3% | **100%** | **0** | 3 | 0 | 0 |
| **TARGET** alignment | primary | 33 | **81.8%** | 100% | 80.0% | 33.3% | **100%** | **0** | 6 | 0 | 0 |

**M4A — reference-claim retrieval recall (primary retrieval diagnostic).** n=34, mean **0.791**, median **1.000**, range 0.0–1.0, **25 KCs at 1.0**, 9 below. Continuous by design; a value below 1.0 is **not** evidence inadequacy, and it is **not** a condition of `materially_sound`.

**M4B — holistic evidence adequacy (EXPLORATORY, non-primary).** n=34, agreement 23.5%, 26 false FAIL, 33 of 34 cases marked `MATERIAL_EVIDENCE_GAP`. Reported for continuity only. **Not restored to primary status**, and would not be even if its numbers improved.

### Key property: zero false PASS on every primary task

M1, M3 and TARGET each achieve **100% FAIL-recall with zero false PASS**. M2 has a single false PASS (`SENT_029`). All four primary tasks err *strict*, never permissive — the safe direction for an instrument whose most dangerous error is accepting incorrect content, wrong-target content, or unsupported claims.

The corresponding cost is PASS-recall: M1 77.8%, M3 82.4%, TARGET 80.0%. **This has deliberately not been tuned.** Whether the conservatism is acceptable is a question for blinded human labels, not for the sentinel suite.

---

## 7. Structural validity and branch reachability

**Structural and contract validity: 100% on all six tasks.** Zero truncations, zero invalid outputs, zero call failures.

| Task | Calls | Structural | Contract | Truncated | Invalid |
|---|---|---|---|---|---|
| M1 | 34 | 100% | 100% | 0 | 0 |
| M2 | 33 | 100% | 100% | 0 | 0 |
| M3 | 33 | 100% | 100% | 0 | 0 |
| M4A | 34 | 100% | 100% | 0 | 0 |
| M4B | 34 | 100% | 100% | 0 | 0 |
| TARGET | 33 | 100% | 100% | 0 | 0 |

**Branch reachability verified in both directions** for every primary task (preflight): M1 PASS/FAIL, M2 PASS/FAIL, M3 `CORE_COMPLETE`/`MATERIAL_OMISSION`, TARGET `TARGET_ALIGNED`/`WRONG_TARGET`. No verdict the rubric defines is silently unreachable.

This check exists because of a real regression: an earlier schema ordering placed the verdict last, which forced the model to select the `oneOf` branch by choosing the *next key* before it had articulated a verdict. It took the short clean-branch path essentially always and produced **zero** `MATERIAL_OMISSION` across all 36 cases — while every response remained valid JSON and structural validity read 100%. Structural validity alone cannot detect an impossible branch.

---

## 8. `SENT_032` / `SENT_033` — GOLD_PENDING

Both carry `GOLD_PENDING` on their disputed **M2** label, awaiting project-owner adjudication.

- They remain in the 36-case suite; their other criteria score normally.
- The disputed label is **excluded from agreement**, counted, and reported. No aggregate was computed from a guessed label.
- Judge prompts have **not** been tuned against them.
- Package: `pending_sentinel_adjudication.json` — reference, draft, evidence, frozen rationale, model outputs, and the precise question to decide.

**The question:** is the injected claim supported anywhere in the *original course corpus* (not merely in the system evidence shown to the drafter)? If yes → `REFERENCE_SILENT_BUT_SOURCE_SUPPORTED` → gold **PASS**. If no → `NOT_SUPPORTED_BY_AUTHORITY` → gold **FAIL**. Their M1 gold (FAIL) is settled and not in dispute.

On adjudication: update gold only, version the file, recompute metrics. **Do not rerun inference** — the analyzer reads gold and predictions from separate files precisely so a gold revision never requires new inference.

---

## 9. Decoding configuration: FROZEN

`FINAL_JUDGE_DECODING_MANIFEST.json` pins the instrument:

| | |
|---|---|
| Model | AtlaAI/Selene-1-Llama-3.3-70B |
| vLLM | 0.27.1 |
| XGrammar | 0.2.3 |
| torch / transformers | 2.13.0 / 5.15.1 |
| GPU | NVIDIA H100 NVL 95830 MiB × 4 (TP=4) |
| dtype | bfloat16 |
| temperature / top_p | 0.0 / 1.0 |
| **frequency_penalty** | **0.0** |
| presence_penalty / repetition_penalty | 0.0 / 1.0 |
| max_tokens | 3000 (4000 decomposition) |

Also recorded: per-function prompt hashes, per-schema hashes, blinding pattern hash, sentinel-suite hash, and hashes of the unchanged reference and candidate artifacts.

### The frequency-penalty decision

`frequency_penalty` was briefly set to 0.2 while diagnosing structured-output stalls, and has been **removed**. vLLM applies a frequency penalty directly to generation logits as a function of how often a token has already appeared, so a nonzero value is not a formatting control — it can alter semantic decisions even under greedy decoding.

The measurement is clean. `penalty_0.2` and `penalty_free_final` are **identical in every respect except decoding** — same schema, same prompts, same sentinels:

| Task | penalty 0.2 | penalty-free final |
|---|---|---|
| M1 | 12 PASS / 22 FAIL | **14 PASS / 20 FAIL** |
| M2 | 18 / 15 | 18 / 15 (identical) |
| M3 | 14 / 19 | 14 / 19 (identical) |
| TARGET | 24 / 9 | 24 / 9 (identical) |

Exactly **two** verdicts changed, both M1: `SENT_007` and `SENT_014`, each PASS→FAIL under the penalty and back to PASS without it. M2, M3 and TARGET were unaffected. An independent earlier penalty-free run agrees with the final run at 14/20 on M1.

**The penalty was also unnecessary.** The decisive structural remedy was making `rationale` optional; the penalty alone moved preflight failures only from 5 to 4, and the penalty-free preflight passes all 18 structural checks. Removing it restores default decoding.

**Selection basis:** penalty-free was chosen because it removes a demonstrated generation-logit confound and because the structural problem no longer requires it — **not** because it maximises sentinel accuracy. `penalty_decision_comparison.csv` is diagnostic only.

---

## 10. Human calibration readiness: READY

The **180-row sample is unchanged** — same KC identities, arm assignments, random seed (20260825), stratification, row order and blinding mapping. Not resampled.

- Workbook: `output/human_calibration/reference_human_calibration_workbook_v2.jsonl` (30 KCs × 6 arms). v1 retained; v2 verified field-for-field identical on sample identity and materials.
- Scope: `output/human_calibration/calibration_scope_v2.json`
- Primary human labels: **M1, M2, M3, TARGET, M4A**. M4B optional/exploratory only.
- Seed-bias audit fields retained on every row: `VALID_SOURCE_SUPPORTED_ALTERNATIVE_BEYOND_REFERENCE`, `POSSIBLE_REFERENCE_DEFECT` — to be reported **per arm** after labels and predictions are frozen and arm identities restored.
- Annotators are blind to judge output, system/drafter identity, retrieval architecture, machine status, sentinel results, and the Qwen seed origin.

Human annotation may begin now: the semantic rubric is frozen, the sample is fixed, no human instruction depends on decoding configuration, and annotators cannot see judge output.

**Before opening human results**, a qualification gate must be pre-registered — per-task thresholds, not one overall average, with false-PASS behaviour explicitly gated for M1, M2 and TARGET so it cannot be masked by high aggregate agreement.

---

## 11. `JUDGE_QUALIFIED = false`

The judge is **formally unqualified**. Sentinel performance does not qualify it. `JUDGE_QUALIFIED.lock.json` records `qualified: false` and there is no override flag anywhere in the pipeline.

Not run, and not to be run until qualification passes: the 795-row final campaign, intrinsic model comparison, extrinsic retrieval comparison, DOS sensitivity analysis, paired system statistics, and any system ranking. **No candidate ranking has been inspected at any point.**

---

## Outstanding methodological issues

1. **`SENT_032` / `SENT_033`** — M2 gold pending owner adjudication.
2. **M4B construct-validity failure** — third instance of the same shape after v3 F4 and F5, reproduced across two independently trained 70B judges. Retained as negative-method evidence; permanently non-primary.
3. **Conservative PASS-recall** on M1 (77.8%), M3 (82.4%), TARGET (80.0%), all with zero false PASS. Deliberately untuned; for human calibration to adjudicate.
4. **Structured-output decoding pathology** — the model pads whitespace wherever the grammar permits continuation. Property of the vLLM + XGrammar + Selene combination; required four schema-shape changes plus making `rationale` optional. Must be re-checked for any future judge model.
5. **Seed anchoring unmeasured** — the reference is machine-seeded from `intrinsic_P-Q` (159/159 exact match). No seed-blind reconstruction has been performed, so the magnitude of any anchoring effect is unknown and must **not** be described as ruled out.
6. **Decomposition human validation outstanding** — structural checks pass (3 candidate problems, 0 reference; 206 candidate / 258 reference claims), but the bounded human validation of claim decomposition has not been run.

---

## Artifacts

`penalty_free_preflight_report.md` · `penalty_free_sentinel_results.json` · `penalty_free_sentinel_report.md` · `penalty_free_sentinel_confusions.csv` · `penalty_decision_comparison.csv` · `locks/FINAL_JUDGE_DECODING_MANIFEST.json` · `final_development_state.md` · `m4_scope_decision.md` · `pending_sentinel_adjudication.json` · `locks/EVALUATION_SCOPE_AMENDMENT_v2.json`

Superseded runs preserved for audit: `selene_reference_sentinel_raw.PRE_FIELDORDER_FIX.json`, `selene_reference_sentinel_raw.PRE_LABEL_ORDER_REVERT.json`.
