# Missing Or Changed Execution Surfaces

## Old executable entry points that materially existed

First-run and corpus-stage entry points in OLD_REPO:
- `steps/step_01_hierarchy/scripts/01_hierarchy_normalize.py`
- `steps/step_01_5_hierarchy_overlay/scripts/run_step01_5_hierarchy_overlay.py`
- `steps/step_02_pdf_ingest_blockstore/scripts/run_step2.py`
- `steps/step_02_pdf_ingest_blockstore/scripts/run_step2_all.ps1`
  - `run_step2_all.ps1:24` scans `data/raw/pdfs`
  - `run_step2_all.ps1:48` shells into `run_step2.py`
- `steps/step_03_doctree_index/scripts/run_step3.py`
- `steps/step_03_5_blockstore_cleanup/scripts/run_step3_5.py`
- `steps/step_03_6_math_salvage/scripts/run_step3_6.py`
- `steps/step_04_structure_retrieval_index/scripts/run_step4.py`
- `steps/step_04_2_patches/scripts/freeze_step4_patches_set.py`
- `steps/step_04_structure_retrieval_index/scripts/run_step4_3.py`
- `steps/step_04_5_sentence_overlay/scripts/run_step4_5.py`
- `steps/step_05_kc_evidence_mining/scripts/run_step5.py`
- `steps/step_05_2_evidence_sharpen/scripts/run_step5_2.py`
- `steps/step_05_3_evidence_recalibrated/scripts/run_step5_3.py`
- `steps/step_06_6_kc_drafting_input_overlay/scripts/run_step6_6_kc_drafting_input_overlay.py`
- `steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py`
- `steps/step_06_8_kc_review_packet_emission/scripts/run_step6_8_kc_review_packet_emission.py`

Old dedicated Step 6 execution authority:
- `PROJECT_STATE/MAIN_QUEST_EXECUTION_AUTHORIZATION.md:73-81`
  - explicitly names `steps/step_06_main_quest_execution/resources/step6_main_quest_v1.base.yaml`
  - `steps/step_06_main_quest_execution/resources/step6_main_quest_v1.local_gpu.yaml`
  - `steps/step_06_main_quest_execution/resources/step6_main_quest_v1.hpc_gpu.yaml`
  - `steps/step_06_main_quest_execution/scripts/render_step6_main_quest_config.py`
- `PROJECT_STATE/MAIN_QUEST_EXECUTION_AUTHORIZATION.md:62`
  - explicitly reuses `steps/step_06_4_2_semantic_safe_enrich/scripts/run_step6_4_2.py` as the execution substrate

Old additional root launcher/config surface:
- `run_step6_7_model_draft_generation.py:28`
  - default root config `step6_7_full128_model_rewrite_2026-03-27.yaml`
- `run_step6_7_model_draft_generation.py:92-110`
  - model-backed Step 6.7 launcher requiring a `model` section
- root `step6_6_*.yaml`, `step6_7_*.yaml`, and `step6_8_*.yaml`

## Clean executable entry points that now exist

Retained internal execution surfaces in CLEAN_REPO:
- The same low-level `steps/` tree is largely preserved.
- `file_inventory_old_vs_clean.csv` marks the major 3.x, 4.x, 5.x, and 6.x step runners as unchanged.
- The old multi-PDF wrapper still exists at `steps/step_02_pdf_ingest_blockstore/scripts/run_step2_all.ps1`.
- The old internal main-quest execution resources under `steps/step_06_main_quest_execution/` also still exist.

New clean public surface:
- `scripts/local/run_stage.py`
- `scripts/hpc/render_main_quest_config.py`
- `scripts/maintenance/check_operator_repo.py`

## What is missing, degraded, or changed

### 1. The new public operator surface is not an execution-equivalent replacement

- `scripts/local/run_stage.py` only exposes `list`, `status`, `intake`, `draft-preflight`, `review-preflight`, and `freeze-preflight`.
- There is no new public command that actually runs corpus intake, Step 4/5 evidence mining, or Step 6 draft generation.
- `src/kc_l/runtime/operator_stages.py:80-82` maps intake only to Step 1, Step 2, and Step 3.
- `src/kc_l/runtime/operator_stages.py:91-94` maps draft generation only to Step 5.3, Step 6.6, Step 6.7, and Step 6.8.
- But `configs/pipeline/main_quest.base.yaml:55-67` claims the preserved internal flow also includes Step 3.5, Step 3.6, Step 4, Step 4.5, Step 5, and Step 5.2.

Audit judgment:
- The clean public operator surface is a new preflight/status shell, not a faithful executable replacement for the old operational entry ladder.

### 2. Multi-PDF corpus intake existed in OLD_REPO and is only half-preserved in CLEAN_REPO

OLD_REPO evidence that multi-PDF corpus intake worked in practice:
- `data/processed/blockstore/_sets/2026-03-02_214129_step2_set.json:2`
  - tracked Step 2 set manifest
- `data/processed/blockstore/_sets/2026-03-02_214129_step2_set.json:7-65`
  - eight separate `doc_id` entries and `processed_out_dir` values
- `data/processed/doctree/_sets/2026-03-03_120609_step3_step3_set.json:6`
  - Step 3 records `input_step2_set = 2026-03-02_214129_step2_set.json`

CLEAN_REPO current state:
- The same wrapper still exists.
- `run_step2_all.ps1:24` still expects `data/raw/pdfs`.
- CLEAN_REPO no longer has `data/raw/pdfs`; a smoke run returned `ERROR: Folder not found: ...data/raw/pdfs`.
- README and public preflight surfaces point the operator instead to `data/input/course_materials` and `data/input/hierarchy`.

Audit judgment:
- Corpus-level multi-PDF intake was preserved only as a hidden legacy wrapper.
- The clean repo lost an honestly exposed corpus-level orchestration path because its public operator surface does not replace the old wrapper and its new layout no longer satisfies the wrapper.

### 3. The old Step 6.7 model-backed launcher surface was removed

Old-only execution surface:
- `run_step6_7_model_draft_generation.py`
- root `step6_6_*.yaml`, `step6_7_*.yaml`, `step6_8_*.yaml`

Clean replacement:
- none at repo root
- the retained internal `steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py` is the simpler non-model wrapper

Audit judgment:
- This is not just cosmetic loss. It removes a real model-backed root launch path and its calibrated root YAML set.

### 4. The old durable main-quest authority surface was removed from the cleaned docs/state layer

Old-only durable authority:
- `PROJECT_STATE/MAIN_QUEST_EXECUTION_AUTHORIZATION.md`
- `PROJECT_STATE/MAIN_QUEST_ENTRY_CONTRACT.md`
- `PROJECT_STATE/MAIN_QUEST_PREFLIGHT_RECIPE.md`
- `PROJECT_STATE/KC_SEMANTIC_GATING_POLICY_FROM_SIDEQUEST.md`

Clean state:
- the low-level step files survive
- the durable authority and recovery docs do not
- the clean docs instead point to `configs/pipeline/main_quest.*` and the new public renderer

Audit judgment:
- The clean repo preserved some internal execution files but removed the durable operator/recovery context that made the old execution lane honest and reproducible.

## Changed in-place execution-relevant files

Execution-relevant changed paths from `file_inventory_old_vs_clean.csv`:
- `README.md`
- `pyproject.toml`
- `requirements.txt`
- `src/kc_l/knowledge_library/access.py`
- `src/kc_l/knowledge_library/grounding_bridge.py`
- `steps/step_02_pdf_ingest_blockstore/scripts/run_step2.py`

Important nuance:
- `steps/step_02_pdf_ingest_blockstore/scripts/run_step2.py` was improved in CLEAN_REPO.
  - `run_step2.py:35` now names `ACTIVE_STEP2_SET.txt`
  - `run_step2.py:101-111` merges `docs` into a Step 2 set manifest
  - `run_step2.py:155-160` writes the set manifest path into the summary
- That strengthens the internal Step 2 to Step 3 contract.
- It does not fix the clean repo's larger entry-surface mismatch because the retained multi-PDF wrapper and default Step 2 config still point at `data/raw/...`.
