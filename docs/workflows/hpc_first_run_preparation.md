# HPC First-Run Preparation

## Scope

This repo is prepared for a future textbook-scale HPC run, but that run is not started here. The
public HPC renderer in this repo is a preparation and discoverability surface, not proof that the
full retained legacy pipeline is runnable on the current machine or already cluster-ready end to
end.

## HPC Rules

- use SSH and Slurm outside this repo
- keep heavy runtime data outside the repo working tree
- keep code, configs, templates, and lightweight manifests in the repo
- keep staged corpora, caches, logs, and heavy outputs in external storage such as scratch
- do not store credentials in the repo

## Repo Surfaces

- Slurm template: `configs/hpc/slurm_textbook_first_run.template.sh`
- External runtime storage template: `configs/hpc/runtime_storage.template.yaml`
- HPC config renderer: `scripts/hpc/render_main_quest_config.py --mode hpc_gpu`
- Restored legacy execution authority:
  - `PROJECT_STATE/MAIN_QUEST_EXECUTION_AUTHORIZATION.md`
  - `PROJECT_STATE/MAIN_QUEST_ENTRY_CONTRACT.md`
  - `PROJECT_STATE/MAIN_QUEST_PREFLIGHT_RECIPE.md`
- Retained main-quest execution resources:
  - `steps/step_06_main_quest_execution/resources/step6_main_quest_v1.base.yaml`
  - `steps/step_06_main_quest_execution/resources/step6_main_quest_v1.local_gpu.yaml`
  - `steps/step_06_main_quest_execution/resources/step6_main_quest_v1.hpc_gpu.yaml`
- Restored late-stage launcher surface:
  - `run_step6_7_model_draft_generation.py`
  - root `step6_6_*.yaml`
  - root `step6_7_*.yaml`
  - root `step6_8_*.yaml`

## What Must Stay Outside The Repo

- staged input corpora copied for the cluster run
- model caches
- temporary work directories
- run logs
- heavy run outputs

## What Stays In The Repo

- source code
- config templates
- schema profiles
- lightweight run manifests
- frozen-library pointer metadata
- documentation

## Truth Boundary

`python scripts/hpc/render_main_quest_config.py --mode hpc_gpu` helps validate the clean operator
shell's HPC preparation surfaces. It does not certify that the preserved late-stage lane, the
restored root Step 6.7 launcher family, or the retained main-quest execution resources are fully
runnable without further launch-specific review.
