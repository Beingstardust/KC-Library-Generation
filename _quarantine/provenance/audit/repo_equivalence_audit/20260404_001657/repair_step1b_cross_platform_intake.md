# Repair Note: Step 1B Cross-Platform Intake

## Recovered State Summary

- `audit/repo_equivalence_audit/20260404_001657/final_verdict.md` still classifies CLEAN_REPO as
  `not honestly equivalent` and says the Step 2 -> Step 3 contract survived internally while the
  public first-run intake surface was misleading.
- `audit/repo_equivalence_audit/20260404_001657/repair_step1_corpus_intake.md` shows Pass 1
  restored multi-PDF intake only through the repaired PowerShell wrappers
  `steps/step_02_pdf_ingest_blockstore/scripts/run_step2_all.ps1` and
  `steps/step_02_pdf_ingest_blockstore/scripts/run_step2.ps1`.
- `audit/repo_equivalence_audit/20260404_001657/missing_or_changed_execution_surfaces.md` says the
  clean public operator surface still had no truthful corpus-level execution replacement.
- `audit/repo_equivalence_audit/20260404_001657/stage_contract_matrix.md` says Step 3 still
  consumes `data/processed/blockstore/_sets/ACTIVE_STEP2_SET.txt`, and the retained clean
  `steps/step_02_pdf_ingest_blockstore/scripts/run_step2.py` now writes that pointer plus the
  merged Step 2 set manifest.
- Before this pass, the intake-facing docs and operator surfaces still pointed to the repaired
  PowerShell wrapper instead of a cross-platform primary launcher.

## Files Changed

- `scripts/local/run_corpus_intake.py`
- `scripts/local/run_stage.py`
- `src/kc_l/runtime/operator_stages.py`
- `README.md`
- `docs/workflows/offline_generation_lifecycle.md`
- `docs/architecture/operator_repo.md`
- `data/input/course_materials/README.md`
- `audit/repo_equivalence_audit/20260404_001657/repair_step1b_cross_platform_intake.md`
- `CHANGELOG.md`

## Exact Behavior Restored

- Added a cross-platform corpus launcher that discovers all top-level `*.pdf` files in
  `data/input/course_materials`.
- The launcher derives deterministic `doc_id` values from filenames and adds collision-safe hash
  suffixes only when sanitized stems would otherwise collide.
- It invokes the retained
  `steps/step_02_pdf_ingest_blockstore/scripts/run_step2.py` runner once per PDF using the current
  Python interpreter and repo-local runtime environment variables.
- It preserves the repaired Step 2 active-set accumulation behavior because `run_step2.py` still
  merges successful docs into the active Step 2 set and refreshes `ACTIVE_STEP2_SET.txt`.
- It exits nonzero on real execution failures and prints a concise summary including discovered PDFs,
  successful ingests, failures, the active Step 2 pointer path, and the exact Step 3 command to run
  next.
- Intake-facing docs/control-plane guidance now points to this Python launcher as the primary corpus
  intake entrypoint for both local and Sofja/Linux use.

## Exact New Primary Command

Local:

```powershell
python scripts/local/run_corpus_intake.py
```

Sofja/Linux:

```bash
python3 scripts/local/run_corpus_intake.py
```

## What Verified

- Parsed the new launcher with:

```powershell
python -m py_compile scripts/local/run_corpus_intake.py
```

- Ran the new launcher through discovery and orchestration planning logic without triggering a full
  heavy ingest:

```powershell
python scripts/local/run_corpus_intake.py --dry-run
```

- Verified the intake preflight/control-plane surface now points to the new primary command:

```powershell
python scripts/local/run_stage.py --json intake
```

- Did not execute a full real multi-PDF Step 2 ingest in this pass.

## What Remains Unrepaired

- `scripts/local/run_stage.py` remains a readiness/preflight shell; it still is not a full
  end-to-end pipeline executor.
- The PowerShell wrappers remain available as secondary helpers, but they are no longer the primary
  truthful intake surface.
- Later-stage review/freeze/index surfaces, historical pinning in later configs, and broader clean
  versus old repo equivalence gaps remain intentionally untouched in this pass.
