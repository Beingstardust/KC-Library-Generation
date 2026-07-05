# Evidence Stage V3 State

Date: 2026-04-27
Mode: `Stage 1 candidate-bank foundation`
Status: Side-by-side v3 candidate-bank layer added locally; no role scoring or pack composition implemented here

## Current Objective

Implement only the first bounded v3 evidence-stage layer:

- flatten Step 5.3 nested candidate evidence into one durable candidate-bank row per candidate unit
- preserve provenance and diagnostics
- exclude seed fields completely from the new v3 artifact contract
- do not change Step 5.4, Step 6.6, Step 6.7, Step 6.75, or Step 6.8 behavior

## Files Created In This Stage

- `src/kc_l/retrieval_gate/evidence_stage_v3_candidate_bank.py`
- `steps/step_05_x_evidence_stage_v3/scripts/run_step5x_v3_candidate_bank.py`
- `steps/step_05_x_evidence_stage_v3/resources/step5x_v3_candidate_bank.default.yaml`
- `steps/step_05_x_evidence_stage_v3/resources/step5x_v3_candidate_bank.regression_gemma_slice10.yaml`
- `tests/test_step5x_v3_candidate_bank.py`
- `docs/operator_notes/EVIDENCE_STAGE_V3_STATE.md`

## Input Boundary

- live Repo A source is implementation truth
- Stage 1 read-only regression fallback source is:
  - `_reference_artifacts/evidence_stage_v3_audit_inputs_20260427_184622.tar.gz`
- Stage 1 reads the Step 5.3 nested candidate bank from:
  - `data/processed/kc_evidence_recalibrated/_sets/2026-04-26_195746_step5_3_kc_evidence_recalibrated_set.json`
  - `data/processed/kc_evidence_recalibrated/2026-04-26_195746/kc_evidence_candidates_recalibrated.jsonl`
- Stage 1 does not write any active pointer

## Validation Commands

- `python -m py_compile src\kc_l\retrieval_gate\evidence_stage_v3_candidate_bank.py steps\step_05_x_evidence_stage_v3\scripts\run_step5x_v3_candidate_bank.py tests\test_step5x_v3_candidate_bank.py`
- direct callable execution of every `test_*` function in `tests/test_step5x_v3_candidate_bank.py`
- synthetic runner smoke using a temporary Step 5.3 nested-candidate JSONL
- bounded 10-KC regression candidate-bank extraction only if the read-only Step 5.3 source is available

## Validation Results

- `py_compile` passed on all new Stage 1 Python files
- direct callable tests passed with `STEP5X_V3_CANDIDATE_BANK_TESTS_OK`
- synthetic runner smoke succeeded:
  - `.codex_tmp_step5x_v3_smoke/output/smoke_step5x_v3_candidate_bank_v2/`
  - `.codex_tmp_step5x_v3_smoke/output/_sets/smoke_step5x_v3_candidate_bank_v2_step5x_v3_candidate_bank_set.json`
- bounded 10-KC regression extraction succeeded from the read-only tar bundle:
  - `data/processed/evidence_stage_v3_candidate_bank/step5x_v3_regression10_20260427_221930/`
  - `data/processed/evidence_stage_v3_candidate_bank/_sets/step5x_v3_regression10_20260427_221930_step5x_v3_candidate_bank_set.json`
- regression stats:
  - `total_kc_rows_seen = 10`
  - `total_candidate_rows_emitted = 180`
  - `kcs_with_candidates = 10`
  - `kcs_without_candidates = 0`
  - `seed_fields_detected_in_input = 0`
  - `seed_fields_propagated_to_output = 0`
  - `granularity_breakdown = {'sentence': 180}`

## Current Risks

- this stage does not improve evidence quality yet
- the live Step 1 registry alias still contains `seed_definition`, so the candidate-bank reader must ignore it and never propagate it
- the current-step status file and live alias payloads are not fully aligned for Step 1.5 and Step 6.6
- role scoring, contextual completion, constrained composition, and pack auditing are not implemented in this stage

## Next Action

- validate the new candidate-bank layer locally
- confirm deterministic output on the 10-KC regression slice on Sofja if needed
- begin Stage 2 only after the Stage 1 contract is stable
