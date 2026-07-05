# Operator Repo Architecture

## Purpose

This repo is the clean operator-facing control plane for KC Library generation. It preserves the
real pipeline logic, but the public control plane is only a shell over that preserved execution
lane. It does not honestly replace the retained research-era step ladder or the restored late-stage
legacy launchers.

## Core Story

The public operator shell now tells one simple top-level story:

1. add source materials and hierarchy input
2. choose a bounded schema profile
3. generate draft KCs and review packets
4. approve, edit-and-approve, or reject
5. freeze an approved-only library
6. index and expose a later UI-safe read surface

## Runtime Roots

- `data/input/course_materials/`
- `data/input/hierarchy/`
- `data/work/cache/`
- `data/work/staging/`
- `data/runs/`
- `data/library/active/`
- `data/library/frozen/`
- `data/exports/`

These are the live operator roots that should matter during normal operator-shell use. They do not
replace the preserved late-stage `steps/` resources, root launchers, or execution-authority docs.

## Typed Separation

- Topic Library: reviewed topic objects only
- KC Library: approved KC objects only
- Knowledge Library: umbrella packaging over those typed collections plus validation, graph, and
  later retrieval/index surfaces

Topic Library and KC Library must not be flattened into one undifferentiated collection.

## Review Boundary

Machine-generated KCs remain drafts until a human explicitly approves or edits-and-approves them.
Rejected or unresolved items must not silently cross into the usable frozen library.

## Graph Semantics

- `topic_contains_topic`: resolved structural hierarchy
- `topic_contains_kc`: conservative candidate membership only

The repo must not silently relabel `topic_contains_kc` as prerequisite, dependency, mastery order,
or any stronger semantic relation.

## Legacy Internal Surface

The research-era `steps/` tree is retained as internal implementation lineage because it still
contains calibrated low-level control flow. The public operator shell is mainly for readiness,
intake, and discoverability; actual downstream execution still depends on the preserved legacy
surfaces.

Use `scripts/local/run_stage.py` and the configs under `configs/` for readiness and preflight.
For actual first-run corpus intake from the clean input layout, use
`python scripts/local/run_corpus_intake.py` locally or `python3 scripts/local/run_corpus_intake.py`
on Sofja/Linux. The retained PowerShell wrapper remains available at
`steps/step_02_pdf_ingest_blockstore/scripts/run_step2_all.ps1` as a Windows-specific alternate.

## Restored Legacy Authority And Launchers

The restored legacy authority surfaces are now part of the truthful repo story and should be read
alongside the public shell:

- `PROJECT_STATE/MAIN_QUEST_EXECUTION_AUTHORIZATION.md`
- `PROJECT_STATE/MAIN_QUEST_ENTRY_CONTRACT.md`
- `PROJECT_STATE/MAIN_QUEST_PREFLIGHT_RECIPE.md`
- `PROJECT_STATE/KC_SEMANTIC_GATING_POLICY_FROM_SIDEQUEST.md`
- `PROJECT_STATE/REPO_GROUNDED_MASTER_DOSSIER.md`

The late-stage launch discoverability surfaces are also restored:

- `run_step6_7_model_draft_generation.py`
- root `step6_6_*.yaml`
- root `step6_7_*.yaml`
- root `step6_8_*.yaml`
- `steps/step_06_main_quest_execution/resources/step6_main_quest_v1.base.yaml`
- `steps/step_06_main_quest_execution/resources/step6_main_quest_v1.local_gpu.yaml`
- `steps/step_06_main_quest_execution/resources/step6_main_quest_v1.hpc_gpu.yaml`

These legacy materials define real downstream execution and recovery context. The operator shell
exists to make that reality easier to inspect, not to pretend it disappeared.
