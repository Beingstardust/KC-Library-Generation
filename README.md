# KC Library Operator Repo

This repo is the clean operator-facing shell for the offline KC Library generation system.
It preserves the legacy execution ladder, but the public scripts in this repo are mainly
readiness, intake, and discoverability surfaces rather than a full replacement for the
research-era pipeline entry ladder.
Its clean layout is designed to start with:

- no course materials in the live input tree
- no hierarchy input in the live input tree
- no runs
- no processed artifact clutter
- no frozen library
- no active library pointer

The goal of this copy is to support fresh future runs, not to preserve visible archaeology from
older thesis execution histories.

## What This Repo Is For

The system is designed to:

1. ingest course materials and hierarchy input
2. generate machine KC drafts and reviewer packets
3. keep Topic Library and KC Library as separate typed collections
4. require human review before anything becomes usable
5. freeze and index an approved-only library
6. expose later UI-friendly and downstream-friendly read surfaces
7. support a future textbook-scale HPC run

UI work is intentionally not implemented in this pass.

## Clean Runtime Topology

- `data/input/course_materials/`: add source PDFs here
- `data/input/hierarchy/`: add hierarchy JSON or YAML here
- `data/work/cache/`: generated config cache and lightweight local cache
- `data/work/staging/`: transient staging artifacts for a run
- `data/runs/`: run manifests and auditable runtime outputs
- `data/library/active/`: active frozen-library pointer
- `data/library/frozen/`: frozen approved library bundles
- `data/exports/`: export surfaces for downstream use

The active library pointer now lives at
`data/library/active/knowledge_library_release_pointer.json`.
In this clean repo it is intentionally set to `state = "none"`.

## Architectural Invariants

- Topic Library and KC Library remain separate typed collections.
- Knowledge Library remains the umbrella packaging concept only.
- Machine-generated KCs are drafts, not automatically approved truth.
- Human review is the usability boundary.
- The final usable library is approved-only.
- `topic_contains_kc` remains conservative candidate membership only.
- `kc_specific_criteria` remains present in the locked core contract and empty in this phase.

## Bootstrap Paths

For a full retained-pipeline environment that is operationally close to the old repo, use:

```powershell
python -m pip install -r requirements.txt
```

Equivalent editable bootstrap:

```powershell
python -m pip install -e .[runtime]
```

If you are managing the torch build separately for a target host, use:

```powershell
python -m pip install -r requirements-runtime-notorch.txt
```

The operator-light convenience surface remains available, but it is secondary and not enough for the
preserved low-level step tree:

```powershell
python -m pip install -r requirements-operator.txt
```

Important truth boundary:

- `requirements.txt` now means full retained-pipeline bootstrap, not operator-only convenience.
- `requirements-operator.txt` is only for the public readiness / maintenance shell.
- plain `pip install -e .` installs the package baseline, but not the full retained-pipeline runtime stack.
- preserved internal step runners still assume editable install or an equivalent `PYTHONPATH=src` setup.

## Operator Commands

Use these operator-shell readiness and preflight surfaces to inspect the clean repo state.
They help you stage a first run and discover the preserved legacy execution surfaces; they do
not prove that the full retained pipeline is runnable end to end.

```powershell
python scripts/local/run_stage.py list
python scripts/local/run_stage.py status --json
python scripts/local/run_stage.py draft-preflight --json
python scripts/maintenance/check_operator_repo.py
python scripts/hpc/render_main_quest_config.py --mode hpc_gpu
```

For actual corpus-level Step 2 intake from the clean input layout, use the cross-platform launcher:

Local example:

```powershell
python scripts/local/run_corpus_intake.py
```

Sofja example:

```bash
python3 scripts/local/run_corpus_intake.py
```

Step 3 after intake:

```powershell
python steps/step_03_doctree_index/scripts/run_step3.py --config steps/step_03_doctree_index/resources/step3.default.yaml
```

The new `run_corpus_intake.py` launcher scans every top-level `*.pdf` in
`data/input/course_materials/`, derives deterministic `doc_id` values from the filenames, runs
Step 2 once per PDF, and preserves the existing `ACTIVE_STEP2_SET.txt` accumulation path for Step
3. The retained PowerShell wrapper at
`steps/step_02_pdf_ingest_blockstore/scripts/run_step2_all.ps1` remains available as a
Windows-specific alternate, but `scripts/local/run_corpus_intake.py` is now the primary truthful
corpus intake surface.

## Preserved Legacy Execution Surfaces

The public operator shell now explicitly coexists with restored legacy execution authority and
late-stage launchers:

- `PROJECT_STATE/MAIN_QUEST_EXECUTION_AUTHORIZATION.md`
- `PROJECT_STATE/MAIN_QUEST_ENTRY_CONTRACT.md`
- `PROJECT_STATE/MAIN_QUEST_PREFLIGHT_RECIPE.md`
- `PROJECT_STATE/KC_SEMANTIC_GATING_POLICY_FROM_SIDEQUEST.md`
- `PROJECT_STATE/REPO_GROUNDED_MASTER_DOSSIER.md`
- `steps/step_06_main_quest_execution/resources/step6_main_quest_v1.base.yaml`
- `steps/step_06_main_quest_execution/resources/step6_main_quest_v1.local_gpu.yaml`
- `steps/step_06_main_quest_execution/resources/step6_main_quest_v1.hpc_gpu.yaml`
- `run_step6_7_model_draft_generation.py`
- the restored root `step6_6_*.yaml`, `step6_7_*.yaml`, and `step6_8_*.yaml` family

For late-stage model-backed drafting, the restored root launcher keeps its original default:

```powershell
python run_step6_7_model_draft_generation.py --config step6_7_full128_model_rewrite_2026-03-27.yaml
```

That launcher and the retained downstream `steps/` tree remain the real late-stage execution
lane. The public operator shell does not replace them.

## Docs

- `docs/architecture/operator_repo.md`
- `docs/architecture/schema_model.md`
- `docs/workflows/offline_generation_lifecycle.md`
- `docs/workflows/hpc_first_run_preparation.md`
- `docs/supervisor_overview/operator_repo_overview.md`

## First-Run Reality

The operator shell is ready for first use, but it is intentionally empty of active runtime state.
That is not the same thing as claiming that every preserved late-stage legacy surface is runnable
out of the box. The first real run still requires you to:

1. add course materials
2. add a hierarchy file
3. choose or edit an extension schema profile
4. fill the local or HPC runtime placeholders in the generated config overlays

The public status and preflight commands should be read as operator-shell readiness surfaces.
They are not proof that the full retained late-stage pipeline, historical manifests, or restored
root launchers are all runnable without further review.

Until a real approved library is frozen, `kc_l.knowledge_library.load_release()` will fail
intentionally with a clear "no active frozen release" error.



