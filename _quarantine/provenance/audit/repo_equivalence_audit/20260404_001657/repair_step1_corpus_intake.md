# Repair Note: Step 1 Corpus Intake Bridge

## Scope

This pass restores only the corpus-level first-run Step 2 intake bridge from the clean input layout
into the already-retained Step 2 -> Step 3 handoff. It does not claim full repo equivalence and it
does not patch later-stage review, freeze, indexing, or config-pinning surfaces.

## Files Changed

- `steps/step_02_pdf_ingest_blockstore/scripts/run_step2_all.ps1`
- `steps/step_02_pdf_ingest_blockstore/scripts/run_step2.ps1`
- `README.md`
- `docs/workflows/offline_generation_lifecycle.md`
- `docs/architecture/operator_repo.md`
- `data/input/course_materials/README.md`
- `src/kc_l/runtime/operator_stages.py`
- `scripts/local/run_stage.py`
- `CHANGELOG.md`

## Old Behavior Recovered

- The retained corpus wrapper once again provides one command that discovers all supported PDFs in
  `data/input/course_materials`.
- It invokes Step 2 once per PDF and preserves the clean repo’s existing `run_step2.py` behavior
  that merges documents into `data/processed/blockstore/_sets/*.json` and updates
  `data/processed/blockstore/_sets/ACTIVE_STEP2_SET.txt`.
- The wrapper now derives deterministic `doc_id` values from filenames and adds deterministic hash
  suffixes only when sanitized filename collisions would otherwise overwrite entries in the Step 2
  active set.
- Step 3 can continue consuming the active Step 2 set through the existing command below.

## Exact Command Restored

```powershell
powershell -ExecutionPolicy Bypass -File steps/step_02_pdf_ingest_blockstore/scripts/run_step2_all.ps1
```

After Step 2 completes, Step 3 should consume the full active Step 2 set with:

```powershell
python steps/step_03_doctree_index/scripts/run_step3.py --config steps/step_03_doctree_index/resources/step3.default.yaml
```

## Smoke Test With 3 PDFs

```powershell
# Place exactly 3 PDFs in data/input/course_materials/
powershell -ExecutionPolicy Bypass -File steps/step_02_pdf_ingest_blockstore/scripts/run_step2_all.ps1
Get-Content data/processed/blockstore/_sets/ACTIVE_STEP2_SET.txt
python steps/step_03_doctree_index/scripts/run_step3.py --config steps/step_03_doctree_index/resources/step3.default.yaml
```

Expected result:

- `run_step2_all.ps1` processes all 3 PDFs from `data/input/course_materials`
- the Step 2 set JSON named by `ACTIVE_STEP2_SET.txt` contains 3 `docs` entries
- Step 3 sees those same 3 docs through the active Step 2 pointer

## Remaining Known Unrepaired Mismatches

- `python scripts/local/run_stage.py intake` remains a readiness/preflight surface, not a full
  corpus-execution wrapper.
- `steps/step_02_pdf_ingest_blockstore/resources/step2.default.yaml` still contains historical
  placeholder `doc.pdf_path` and `frozen_store_dir` values; the repaired wrappers restore the clean
  corpus bridge by overriding `doc.pdf_path` per PDF, but this pass does not redesign Step 2’s
  broader runtime storage semantics.
- Later stages that still reference older path conventions, including Step 3.5+ and review/freeze
  surfaces, were intentionally left untouched in this pass.
