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

---

Date: 2026-04-28
Mode: `Stage 2 scored-candidates sidecar`
Status: Side-by-side v3 scored-candidate layer added locally; no pack composition or Step 6.x integration changes

## Current Objective

Implement only the second bounded v3 evidence-stage layer:

- consume Stage 1 candidate-bank rows and emit exactly one scored row per candidate
- preserve candidate identity and Stage 1 provenance
- add deterministic lexical, structural, topic-alignment, formula, fragment, contamination, sibling, and recurrence diagnostics
- do not compose packs
- do not touch Step 5.4, Step 6.6, Step 6.7, Step 6.75, or Step 6.8
- do not create any ACTIVE pointer

## Files Changed In This Stage

- `src/kc_l/retrieval_gate/evidence_stage_v3_scored_candidates.py`
- `steps/step_05_x_evidence_stage_v3/scripts/run_step5x_v3_scored_candidates.py`
- `steps/step_05_x_evidence_stage_v3/resources/step5x_v3_scored_candidates.default.yaml`
- `steps/step_05_x_evidence_stage_v3/resources/step5x_v3_scored_candidates.regression_gemma_slice10.yaml`
- `tests/test_step5x_v3_scored_candidates.py`
- `docs/operator_notes/EVIDENCE_STAGE_V3_STATE.md`

## Validation Commands

- `python -m py_compile src\kc_l\retrieval_gate\evidence_stage_v3_scored_candidates.py steps\step_05_x_evidence_stage_v3\scripts\run_step5x_v3_scored_candidates.py tests\test_step5x_v3_scored_candidates.py`
- direct callable execution of every `test_*` function in `tests/test_step5x_v3_scored_candidates.py`
- bounded 10-KC regression scored-candidate extraction:
  - `python steps\step_05_x_evidence_stage_v3\scripts\run_step5x_v3_scored_candidates.py --config steps\step_05_x_evidence_stage_v3\resources\step5x_v3_scored_candidates.regression_gemma_slice10.yaml --run-id step5x_v3_scored_candidates_regression10_20260428_002325`

## Validation Results

- `py_compile` passed on all new Stage 2 Python files
- direct callable tests passed with `STEP5X_V3_SCORED_CANDIDATES_TESTS_OK`
- bounded 10-KC Stage 2 regression succeeded:
  - `data/processed/evidence_stage_v3_scored_candidates/step5x_v3_scored_candidates_regression10_20260428_002325/`
  - `data/processed/evidence_stage_v3_scored_candidates/_sets/step5x_v3_scored_candidates_regression10_20260428_002325_step5x_v3_scored_candidates_set.json`
- regression contract checks passed:
  - `row_count = 180`
  - `duplicate_candidate_id_count = 0`
  - `scored_candidate_id == candidate_id` for all rows
  - `forbidden_seed_field_hits = 0`
  - `forbidden_pack_field_hits = 0`
  - no `ACTIVE_STEP5X_V3*` pointer created
- regression assessment JSON created:
  - `data/work/cache/diagnostics/stage2_v3_scored_candidates_regression_assessment_20260428_002305.json`

## Current Risks

- Stage 2 is still candidate-level only and does not improve final Step 5.4 pack quality by itself
- several KCs now fail more honestly, but some fragmentary rows still score as `context_completion_candidate` or guarded auxiliary evidence
- `KC_EVAL_BASIC_005` and `KC_CLU_EVAL_012` remain weak in the current 10-KC slice, which suggests upstream recall or later-stage composition work is still needed
- no Step 6.6 or Step 6.7 improvement is proven in this stage

## Next Action

- sync the Stage 2 patch archive to Sofja
- rerun the 10-KC scored-candidate regression against the accepted Stage 1 Sofja manifest
- inspect the scored-candidate diagnostics there before beginning Stage 3 contextual completion

## Resume Point

- authoritative next step starts from `data/work/cache/diagnostics/stage2_v3_scored_candidates_regression_assessment_20260428_002305.json`
- local Stage 2 output to compare on Sofja:
  - `data/processed/evidence_stage_v3_scored_candidates/step5x_v3_scored_candidates_regression10_20260428_002325/`

---

Date: 2026-04-28
Mode: `Stage 3 v3 evidence-pack composition sidecar`
Status: Stage 3 design patch prepared manually; source validation pending in the target repo

## Current Objective

Implement the third bounded v3 evidence-stage layer:

- consume Stage 2 scored-candidate rows and emit one KC-level evidence pack per KC
- keep Stage 1 and Stage 2 candidate identity traceable inside every selected slot item
- expose Step 6.6-compatible `kc_evidence_packs_jsonl` in the set manifest
- allow only Stage 2 positive candidates into positive drafting slots
- keep context-completion material auxiliary
- keep sibling-contrast material guardrail-only and out of `ordered_pack_for_drafting`
- preserve representation for weak KCs by emitting `insufficient_support_packet` rather than dropping them
- avoid ACTIVE pointer creation

## Files Added Or Updated For This Stage

- `src/kc_l/retrieval_gate/evidence_stage_v3_pack_composition.py`
- `steps/step_05_x_evidence_stage_v3/scripts/run_step5x_v3_pack_composition.py`
- `steps/step_05_x_evidence_stage_v3/resources/step5x_v3_pack_composition.default.yaml`
- `steps/step_05_x_evidence_stage_v3/resources/step5x_v3_pack_composition.regression_gemma_slice10.yaml`
- `tests/test_step5x_v3_pack_composition.py`
- `docs/operator_notes/EVIDENCE_STAGE_V3_STATE.md`

## Validation Required After Landing

- compile the Stage 3 module, runner, and tests
- run every `test_*` function in `tests/test_step5x_v3_pack_composition.py`
- run bounded 10-KC pack composition from the latest accepted Stage 2 scored-candidate manifest
- verify:
  - exactly 10 packs emitted on the regression slice
  - no sibling-contrast item appears in `ordered_pack_for_drafting`
  - weak KCs remain represented as insufficient packs
  - no seed fields leak into output
  - set manifest contains `artifacts.kc_evidence_packs_jsonl`
  - no `ACTIVE_STEP5X_V3*` pointer is created

## Current Boundary

This stage only composes packs from Stage 2. It does not modify Step 5.4, Step 6.6, Step 6.7, Step 6.75, or Step 6.8.
