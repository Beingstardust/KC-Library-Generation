# Config Semantic Mismatches

## 1. The new clean `configs/pipeline/main_quest.*` family is not the old executable main-quest config

Old semantics:
- `PROJECT_STATE/MAIN_QUEST_EXECUTION_AUTHORIZATION.md:73-81` names the real executable main-quest surface as:
  - `steps/step_06_main_quest_execution/resources/step6_main_quest_v1.base.yaml`
  - `steps/step_06_main_quest_execution/resources/step6_main_quest_v1.local_gpu.yaml`
  - `steps/step_06_main_quest_execution/resources/step6_main_quest_v1.hpc_gpu.yaml`
  - `steps/step_06_main_quest_execution/scripts/render_step6_main_quest_config.py`
- The old renderer enforced strict runtime checks.
  - `steps/step_06_main_quest_execution/scripts/render_step6_main_quest_config.py:136`
    - missing required input paths are errors
  - `...:146-148`
    - `device_mode == cuda` and `interpreter_path` must exist in strict runtime mode
  - `...:154-155`
    - generation and gate endpoints must be pinned

Clean semantics:
- `configs/pipeline/main_quest.base.yaml` is an operator repo descriptor with `operator_runtime`, `schema_profile`, `outputs`, and `legacy_internal_flow`.
- `src/kc_l/runtime/main_quest_config.py:109-167` validates:
  - expected clean layout paths
  - schema/profile file existence
  - existence of `legacy_internal_flow` files
  - placeholder strings
  - in HPC mode, only presence of `storage.external_runtime_root`
- It does not validate:
  - that the example interpreter exists
  - that model endpoints are reachable or even appropriate for the current machine
  - that the historically pinned step resource YAMLs are runnable

Impact:
- The clean config renderer produces a config that looks valid, but it is not semantically equivalent to the old executable main-quest config path.

## 2. The clean renderer path is operationally overpermissive

Evidence:
- `configs/pipeline/main_quest.local_gpu.example.yaml:7`
  - hardcodes `/home/aryp26yc/venvs/kc_l_v2/bin/python`
- `configs/pipeline/main_quest.hpc_gpu.example.yaml:7`
  - hardcodes the same Linux interpreter
- `configs/pipeline/main_quest.hpc_gpu.example.yaml:17-20`
  - hardcodes `/beegfs2/...` scratch paths
- Yet:
  - `python scripts/hpc/render_main_quest_config.py --mode local_gpu` returned `"ok": true`
  - `python scripts/hpc/render_main_quest_config.py --mode hpc_gpu` returned `"ok": true`
  - `data/work/cache/generated_configs/main_quest.local_gpu.validation.json` reports no errors or warnings
  - `data/work/cache/generated_configs/main_quest.hpc_gpu.validation.json` reports no errors or warnings

Impact:
- The clean rendering path is not honest about runtime readiness.
- It certifies example overlays as `ok` even when their concrete interpreter/storage assumptions are not valid on this machine.

## 3. The clean public layout (`data/input`, `data/library`) is not bridged into retained legacy step configs

Evidence:
- `README.md:32-33`
  - tells operators to use `data/input/course_materials` and `data/input/hierarchy`
- But retained Step 2 still ships with:
  - `steps/step_02_pdf_ingest_blockstore/scripts/run_step2_all.ps1:24`
    - `data/raw/pdfs`
  - `steps/step_02_pdf_ingest_blockstore/resources/step2.default.yaml:6`
    - `data/raw/docs/dm2_slides.pdf`

Impact:
- The clean repo's new runtime layout is not semantically wired into the preserved intake code.

## 4. Mid-pipeline resource defaults still hardcode historical processed artifacts

Evidence:
- `steps/step_05_kc_evidence_mining/resources/step5.default.yaml:5`
  - `kc_registry_path: data/processed/hierarchy/20260228T211719Z/kc_registry.jsonl`
- `steps/step_05_2_evidence_sharpen/resources/step5_2.default.yaml:5`
  - same dated `kc_registry_path`
- `steps/step_05_3_evidence_recalibrated/resources/step5_3.default.yaml:5`
  - same dated `kc_registry_path`
- `steps/step_06_6_kc_drafting_input_overlay/resources/step6_6.full128.yaml:5`
  - dated `hierarchy_overlay_manifest`
- `steps/step_06_7_kc_draft_generation/resources/step6_7.full128.yaml:2`
  - dated `step6_6_set_manifest`
- `steps/step_06_8_kc_review_packet_emission/resources/step6_8.full128.yaml:2`
  - dated `step6_7_set_manifest`

Impact:
- The retained late-stage ladder is not clean-first-run runnable from its shipped resource defaults.
- Cleanup removed the historical processed roots from the clean repo, but the default configs still assume them.

## 5. Step 4 ships in dry-run mode by default

Evidence:
- `steps/step_04_structure_retrieval_index/resources/step4.default.yaml:21-22`
  - comment explicitly says dry-run does not write processed outputs
  - `dry_run: true`

Impact:
- Even where internal contracts survive, the shipped default config does not represent a live end-to-end execution lane.

## 6. Knowledge-library default pointer semantics changed

Old semantics:
- `src/kc_l/knowledge_library/access.py:14-15`
  - default pointer is `CURRENT_KNOWLEDGE_LIBRARY_PILOT_RELEASE.md`
- Old `load_release()` resolves immediately against the frozen April 1 release

Clean semantics:
- `src/kc_l/knowledge_library/access.py:10-17`
  - now delegates to `src/kc_l/runtime/library_state.py`
- `src/kc_l/runtime/library_state.py:31-34`
  - default pointer payload is `state = "none"`
- `src/kc_l/runtime/library_state.py:92-97`
  - `resolve_active_release_manifest_path()` fails until a frozen library is created and the JSON pointer is updated

Impact:
- Package behavior changed by design.
- That change is acceptable for a clean-start operator repo, but it is not execution-equivalent with the old read-only pilot repo.

## 7. `review.default.yaml` and `freeze.default.yaml` are high-level notes, not old operational configs

Evidence:
- `configs/pipeline/review.default.yaml`
- `configs/pipeline/freeze.default.yaml`

Impact:
- These new files are useful operator scaffolding, but they do not preserve the old operational semantics by themselves.
- They contribute to a surface that looks complete while still depending on retained legacy step configs for real behavior.
