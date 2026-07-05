# CODEX Step 6.7 To 6.8 Hierarchy And Normalization

Date: 2026-04-11
Repo: `r:\Thesis Project\kc_l_v2_clean_sofja_authoritative_2026-04-10_225640`

## Pre-Edit Recovery

- Active Step 6.7 slice10 set:
  - `data/processed/kc_drafts/2026-04-11_012622/`
- Active Step 6.8 slice10 set:
  - `data/processed/kc_review_packets_restarted/2026-04-11_013627/`
- Current bounded slice counts:
  - Step 6.7 `review_readiness_breakdown = {low_trust: 6, needs_attention: 4}`
  - Step 6.8 `packet_count = 10`
  - Step 6.8 `fallback_definition_count = 6`
  - Step 6.8 `excluded_kcs = []`
- Real inspected cases:
  - `KC_CLF_DT_011`
    - current packet survives through `survival_floor`
    - local evidence neighborhood contains binary-tree and binary-split wording that looks semantically recoverable but not source-near enough for current acceptance
  - `KC_CLF_NB_001`
    - current packet survives through `survival_floor`
    - live local neighborhood shows Bayes-theorem and posterior-probability evidence, but the current verifier rejects the broader paraphrase as not text-near enough
  - `KC_CLU_EVAL_005`
    - current packet survives through `survival_floor`
    - a formula-faithful definition already appears in the redraft verify response, but the final field is dropped because the wording still looks like a contextual scaffold
- Current hierarchy surface:
  - Step 6.7 bundles expose only `hierarchy_ancestry`
  - Step 6.8 packets expose no typed topic-path fields
  - the active overlay ancestry artifacts are:
    - `data/processed/hierarchy_overlay/2026-04-08_103432_hierarchy_overlay/leaf_to_overlay_ancestry.json`
    - `data/work/cache/current_step_artifacts/step1_kc_registry.current.jsonl`
- Existing typed topic-id derivation logic already exists in-repo at:
  - `src/kc_l/topic/minimal_draft.py::_topic_id`

## Current Objective

- Add explicit typed hierarchy fields to the active Step 6.7 bundle and Step 6.8 packet surfaces without collapsing Topic Library and KC Library into one layer.
- Add an evidence-local, hierarchy-aware, source-faithful normalization path that can distinguish:
  - `direct_grounded`
  - `normalized_grounded`
  - `seed_floor_fallback`

## Exact Next Action

- Patch the Step 6.7 authoritative drafting core first so the definition acceptance decision becomes explicit before Step 6.8 packetization reads it.

## Post-Edit Record

- Files changed:
  - `src/kc_l/kc_drafting/contracts.py`
  - `src/kc_l/kc_drafting/hierarchy_refs.py`
  - `src/kc_l/kc_drafting/heuristic_core.py`
  - `src/kc_l/utils/kc_step67_model_drafting.py`
  - `src/kc_l/kc_drafting/packetization.py`
  - `src/kc_l/kc/schemas/review_packet.schema.json`
  - `src/kc_l/kc/restarted_reviewed_library_assembly.py`
  - `tests/test_kc_drafting_architecture.py`
  - `docs/operator_notes/CODEX_ACTIVE_STEP6_REFACTOR_STATE.md`
  - `docs/operator_notes/CODEX_STEP67_68_HIERARCHY_NORMALIZATION_2026-04-11.md`
  - `CHANGELOG.md`
  - refreshed current-artifact aliases and bounded replay outputs under:
    - `data/work/cache/current_step_artifacts/`
    - `data/processed/kc_drafts/2026-04-11_124428/`
    - `data/runs/2026-04-11_124428_step6_7/`
    - `data/processed/kc_review_packets_restarted/2026-04-11_125521/`
    - `data/runs/2026-04-11_125521_step6_8/`
- Commands run:
  - `.\.venv\Scripts\python.exe -m py_compile src\kc_l\kc_drafting\contracts.py src\kc_l\kc_drafting\hierarchy_refs.py src\kc_l\kc_drafting\heuristic_core.py src\kc_l\utils\kc_step67_model_drafting.py src\kc_l\kc_drafting\packetization.py src\kc_l\kc\restarted_reviewed_library_assembly.py tests\test_kc_drafting_architecture.py`
  - `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests\test_kc_drafting_architecture.py`
  - `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests\test_step6_7_contract.py`
  - `.\.venv\Scripts\python.exe steps\step_06_8_kc_review_packet_emission\scripts\run_step6_8_kc_review_packet_emission.py --config steps\step_06_8_kc_review_packet_emission\resources\step6_8.slice10.yaml`
  - first local Step 6.7 replay attempt:
    - `.\.venv\Scripts\python.exe steps\step_06_7_kc_draft_generation\scripts\run_step6_7_kc_draft_generation.py --config data\work\cache\generated_configs\main_quest.local_gpu.slice10.yaml`
    - timed out at `180000 ms`
  - successful bounded local Step 6.7 replay:
    - `.\.venv\Scripts\python.exe steps\step_06_7_kc_draft_generation\scripts\run_step6_7_kc_draft_generation.py --config data\work\cache\generated_configs\main_quest.local_gpu.slice10.yaml`
  - refreshed the stable alias to the fresh Step 6.7 set:
    - `.\.venv\Scripts\python.exe scripts\maintenance\refresh_current_step_artifacts.py`
  - bounded local Step 6.8 replay against the refreshed Step 6.7 alias:
    - `.\.venv\Scripts\python.exe steps\step_06_8_kc_review_packet_emission\scripts\run_step6_8_kc_review_packet_emission.py --config steps\step_06_8_kc_review_packet_emission\resources\step6_8.slice10.yaml`
- Validations:
  - compile validation passed for all touched Python files
  - `tests/test_kc_drafting_architecture.py`: `13 passed`
  - `tests/test_step6_7_contract.py`: `3 passed`
  - bounded local Step 6.7 replay passed:
    - run: `data/runs/2026-04-11_124428_step6_7/`
    - processed dir: `data/processed/kc_drafts/2026-04-11_124428/`
    - runtime: `execution_mode = llm`
    - resolved model alias: `qwen3.5:9b`
    - `llm_calls = 50`
    - authoritative definition status breakdown:
      - `direct_grounded = 3`
      - `normalized_grounded = 2`
      - `seed_floor_fallback = 5`
    - normalization recoveries: `2`
  - bounded local Step 6.8 replay passed after alias refresh:
    - run: `data/runs/2026-04-11_125521_step6_8/`
    - processed dir: `data/processed/kc_review_packets_restarted/2026-04-11_125521/`
    - `packet_count = 10`
    - `excluded_candidate_count = 0`
    - authoritative definition status counts:
      - `direct_grounded = 3`
      - `normalized_grounded = 2`
      - `seed_floor_fallback = 5`
    - normalized grounded packet KCs:
      - `KC_CLF_DT_011`
      - `KC_CLU_EVAL_005`
  - hierarchy fields are present on the fresh Step 6.7 bundles and Step 6.8 packets:
    - `topic_path_ids`
    - `topic_path_labels`
    - `parent_topic_id`
    - `parent_topic_label`
    - `ancestor_topic_ids`
    - `ancestor_topic_labels`
- Remaining risks:
  - `KC_CLF_NB_001` still lands at `seed_floor_fallback` on the bounded local slice because the local same-KC evidence neighborhood did not expose a formula-bearing support row that the source-faithful normalizer could safely recover; the redraft still cites a row the verifier treats as too PPCA-specific.
  - the tiny Step 6.11 compatibility pass-through for typed hierarchy refs and `authoritative_definition_status` compiles cleanly, but I did not rerun the full review-resolution / reviewed-library assembly ladder in this turn.
- Exact next HPC command:
  - `python steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py --config data/work/cache/generated_configs/main_quest.hpc_gpu.slice10.yaml`
