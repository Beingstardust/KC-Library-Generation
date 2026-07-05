# Recovered State Summary

Audit root: `audit/repo_equivalence_audit/20260404_001657`

Repos compared:
- `OLD_REPO = R:\Thesis Project\KC_L v2 - Copy`
- `CLEAN_REPO = R:\Thesis Project\KC_L v2 - Cleaner`

## Durable context recovered before comparison

OLD_REPO durable context read:
- `AGENTS.md`
- `README.md`
- `docs/knowledge_library_pilot.md`
- `PROJECT_STATE/MAIN_QUEST_ENTRY_CONTRACT.md`
- `PROJECT_STATE/MAIN_QUEST_PREFLIGHT_RECIPE.md`
- `PROJECT_STATE/MAIN_QUEST_EXECUTION_AUTHORIZATION.md`
- `PROJECT_STATE/KC_SEMANTIC_GATING_POLICY_FROM_SIDEQUEST.md`
- `PROJECT_STATE/REPO_GROUNDED_MASTER_DOSSIER.md`
- root execution helpers such as `run_step6_7_model_draft_generation.py`
- root state pointers such as `CURRENT_ACTIVE_STATE.md`, `CURRENT_KNOWLEDGE_LIBRARY_PILOT_RELEASE.md`, `STEP6_SCHEMA_LINEAGE.md`, `Target design.md`
- the retained `steps/` tree and key tracked `_sets` manifests under `data/processed/`

CLEAN_REPO durable context read:
- `AGENTS.md`
- `README.md`
- `CHANGELOG.md`
- `docs/architecture/operator_repo.md`
- `docs/architecture/schema_model.md`
- `docs/workflows/offline_generation_lifecycle.md`
- `docs/workflows/hpc_first_run_preparation.md`
- `docs/supervisor_overview/operator_repo_overview.md`
- `scripts/local/run_stage.py`
- `scripts/hpc/render_main_quest_config.py`
- `scripts/maintenance/check_operator_repo.py`
- `configs/pipeline/main_quest.base.yaml`
- `configs/pipeline/main_quest.local_gpu.example.yaml`
- `configs/pipeline/main_quest.hpc_gpu.example.yaml`
- `src/kc_l/runtime/*.py`
- the retained `steps/` tree and key step resource YAMLs

## Recovered state of the OLD_REPO

- The old repo is not just a generic code snapshot. It is a working thesis repo with:
  - an active frozen April 1 Knowledge Library pilot (`README.md`, `docs/knowledge_library_pilot.md`)
  - durable project-state authority for main-quest execution (`PROJECT_STATE/*.md`)
  - preserved low-level step runners in `steps/`
  - additional root-level Step 6.7 model-backed launcher and root YAMLs
- The old repo had multi-PDF corpus execution in practice.
  - `data/processed/blockstore/_sets/2026-03-02_214129_step2_set.json` records eight `doc_id` entries and their `processed_out_dir` values.
  - `data/processed/doctree/_sets/2026-03-03_120609_step3_step3_set.json` explicitly names `input_step2_set: 2026-03-02_214129_step2_set.json` and resolves each `step2_out_dir`.
- The old repo's durable main-quest execution authority is explicit.
  - `PROJECT_STATE/MAIN_QUEST_EXECUTION_AUTHORIZATION.md:73-81` names the live main-quest execution surface as `steps/step_06_main_quest_execution/resources/step6_main_quest_v1.*` plus `steps/step_06_main_quest_execution/scripts/render_step6_main_quest_config.py`.

## Recovered state of the CLEAN_REPO

- The clean repo is a new operator-facing shell layered over much of the same retained step tree.
- It introduces a new public control plane:
  - `scripts/local/run_stage.py`
  - `scripts/hpc/render_main_quest_config.py`
  - `scripts/maintenance/check_operator_repo.py`
  - `src/kc_l/runtime/*.py`
  - `configs/`
  - `docs/architecture/`, `docs/workflows/`, `docs/supervisor_overview/`
- It removes old durable project-state and root launch/state surfaces from the scoped comparison:
  - `PROJECT_STATE/`
  - `CURRENT_ACTIVE_STATE.md`
  - `CURRENT_KNOWLEDGE_LIBRARY_PILOT_RELEASE.md`
  - `docs/knowledge_library_pilot.md`
  - `run_step6_7_model_draft_generation.py`
  - root Step 6.6/6.7/6.8 YAMLs
- The clean repo changes the default active library pointer contract.
  - Old `src/kc_l/knowledge_library/access.py:14-15` resolved `CURRENT_KNOWLEDGE_LIBRARY_PILOT_RELEASE.md`.
  - Clean `src/kc_l/knowledge_library/access.py:10-17` delegates to `src/kc_l/runtime/library_state.py`.
  - `data/library/active/knowledge_library_release_pointer.json:3-7` is currently `state = "none"`, so default `load_release()` now fails until a new frozen bundle is created.

## Inventory summary

The scoped inventory written to `file_inventory_old_vs_clean.csv` excludes compiled/runtime byproducts and reports:
- `225` same paths
- `7` changed paths
- `44` old-only paths
- `30` clean-only paths

Changed in place:
- `README.md`
- `CHANGELOG.md`
- `pyproject.toml`
- `requirements.txt`
- `src/kc_l/knowledge_library/access.py`
- `src/kc_l/knowledge_library/grounding_bridge.py`
- `steps/step_02_pdf_ingest_blockstore/scripts/run_step2.py`

## Behavioral checks captured during recovery

- `python scripts/local/run_stage.py --json intake` in CLEAN_REPO returned `"ready_for_first_run": true`.
- `python scripts/local/run_stage.py --json draft-preflight` in CLEAN_REPO returned `"ready_for_first_run": true`.
- `python scripts/maintenance/check_operator_repo.py` in CLEAN_REPO returned `"ok": true`.
- `powershell -ExecutionPolicy Bypass -File steps/step_02_pdf_ingest_blockstore/scripts/run_step2_all.ps1` in CLEAN_REPO failed immediately with `ERROR: Folder not found: ...data/raw/pdfs`.
- `PYTHONPATH=src python -c "from kc_l.knowledge_library import load_release; ..."` succeeded in OLD_REPO and failed in CLEAN_REPO with `No active frozen Knowledge Library release is set`.

## Scope exclusions honored

- No mismatch judgment in this audit depends only on empty `data/runs/`, empty `data/library/frozen/`, missing active frozen pointer state, or absent historical run outputs.
- Input PDF contents were not compared as semantic evidence.
- Runtime artifacts were only used when they defined a durable contract or proved an execution path in practice.
