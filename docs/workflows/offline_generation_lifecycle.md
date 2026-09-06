# Offline Generation Lifecycle

## Operator Stages

The public stage model is a clean operator-shell abstraction over the retained execution ladder.
It is useful for readiness, intake, and discoverability, but it is not a claim that the shell fully
replaces the numbered `steps/` lane.

The public stage model is:

1. source preparation and ingest
2. draft generation
3. review and resolution
4. freeze, package, and index
5. inspection, export, and maintenance

## Public Commands

Preflight and readiness for the operator shell:

```powershell
python scripts/local/run_stage.py list
python scripts/local/run_stage.py status --json
python scripts/local/run_stage.py intake --json
python scripts/local/run_stage.py draft-preflight --json
python scripts/local/run_stage.py review-preflight --json
python scripts/local/run_stage.py freeze-preflight --json
```

Primary cross-platform corpus intake bridge:

Local example:

```powershell
python scripts/local/run_corpus_intake.py
```

HPC cluster example:

```bash
python3 scripts/local/run_corpus_intake.py
```

Step 3 after intake:

```powershell
python steps/step_03_doctree_index/scripts/run_step3.py --config steps/step_03_doctree_index/resources/step3.default.yaml
```

## Stage Meaning

### 1. Source Preparation And Ingest

- add PDFs to `data/input/course_materials/`
- add hierarchy input to `data/input/hierarchy/`
- validate the locked core schema and chosen extension schema
- prepare clean staging and run manifests
- run the cross-platform `scripts/local/run_corpus_intake.py` launcher to ingest every top-level PDF in `data/input/course_materials/`
- let Step 3 consume the refreshed `ACTIVE_STEP2_SET.txt` pointer after Step 2 completes
- treat `steps/step_02_pdf_ingest_blockstore/scripts/run_step2_all.ps1` as a repaired Windows legacy helper, not the primary intake story

### 2. Draft Generation

- resolve the local or HPC runtime config
- preserve the internal downstream lane that still lives in the retained `steps/` tree
- use the restored `PROJECT_STATE` execution docs when moving into late-stage execution authority
- use the restored root `run_step6_7_model_draft_generation.py` plus the root `step6_6_*.yaml`, `step6_7_*.yaml`, and `step6_8_*.yaml` family when the old model-backed Step 6.7 surface is the intended launcher
- remember that this public stage label is a discoverability shell, not the late-stage executor itself

### 3. Review And Resolution

- review packets offline
- approve, edit-and-approve, or reject
- keep unresolved or rejected cases outside the usable frozen library

### 4. Freeze, Package, And Index

- freeze approved-only outputs
- package a later retrieval-ready surface
- update `data/library/active/knowledge_library_release_pointer.json`

### 5. Inspection, Export, And Maintenance

- inspect repo readiness
- inspect stage preflight state
- render HPC configs
- export later read surfaces

## Internal Mapping

The old numbered `steps/` directories remain mostly internal only. The public first-run execution
exception is now `scripts/local/run_corpus_intake.py`, which shells into the retained
`steps/step_02_pdf_ingest_blockstore/scripts/run_step2.py` runner and preserves the existing Step
2 -> Step 3 contract. The PowerShell wrapper remains available as a Windows-specific alternate.

After intake, the real preserved downstream lane still lives in the retained `steps/` tree,
including Step 3.5, Step 3.6, Step 4, Step 4.3, Step 4.5, Step 5, Step 5.2, Step 5.3, Step 6.6,
Step 6.7, and Step 6.8. The restored late-stage discoverability surfaces are:

- `PROJECT_STATE/MAIN_QUEST_EXECUTION_AUTHORIZATION.md`
- `PROJECT_STATE/MAIN_QUEST_ENTRY_CONTRACT.md`
- `PROJECT_STATE/MAIN_QUEST_PREFLIGHT_RECIPE.md`
- `PROJECT_STATE/KC_SEMANTIC_GATING_POLICY_FROM_SIDEQUEST.md`
- `run_step6_7_model_draft_generation.py`
- root `step6_6_*.yaml`
- root `step6_7_*.yaml`
- root `step6_8_*.yaml`

The public operator shell should be read as a truthful front door into those preserved surfaces,
not as proof that the legacy ladder has been replaced.
