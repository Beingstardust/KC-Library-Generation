# Repair Note: Config Render Truth Boundary

## Recovered State Summary

This pass was grounded in the clean-repo validator and renderer surfaces, the April 4 audit notes,
and the prior operator-shell truthfulness repair. Before this pass,
`scripts/hpc/render_main_quest_config.py` and `src/kc_l/runtime/main_quest_config.py` could return
`ok: true` for the example `local_gpu` and `hpc_gpu` overlays without saying that the check was
limited to operator-shell config structure and referenced-file presence. The repaired surface now
uses the same truth boundary as Pass 3: it reports operator-shell config validity while explicitly
stating that strict retained-pipeline runtime readiness was not validated.

## Files Changed

- `src/kc_l/runtime/main_quest_config.py`
- `scripts/hpc/render_main_quest_config.py`
- `tests/test_main_quest_config.py`
- `CHANGELOG.md`

No README or workflow-doc edits were needed in this pass because the user-facing docs from the
prior operator-shell truthfulness repair already described the config renderer as a preparation and
discoverability surface rather than proof of end-to-end pipeline readiness.

## Exact Validation And Output Semantics Changed

The validator report in `src/kc_l/runtime/main_quest_config.py` now emits explicit truth-boundary
metadata:

- `status_scope: operator_shell_only`
- `validation_scope: operator_shell_config_only`
- `truth_boundary`
- `full_pipeline_runnable_claimed: false`
- `strict_runtime_readiness_checked: false`
- `operator_shell_config_valid`
- `input_overlay_path`
- `runtime_profile_status`
- `example_overlay`

The warning surface now explicitly states that:

- the validation checks config structure, repo layout binding, and referenced file presence
- the example overlays are preparation/example surfaces rather than proof of retained-pipeline
  runtime readiness
- model endpoints are not contacted during validation
- HPC interpreter and external storage values are treated as planned operator-shell values rather
  than strict cluster-readiness proof

The renderer CLI in `scripts/hpc/render_main_quest_config.py` now mirrors that metadata in its JSON
output and its help text now describes the command as operator-shell validation rather than full
runtime certification.

## Before/After Example Render Behavior

Before this pass, the audit recorded the following misleading behavior:

- `python scripts/hpc/render_main_quest_config.py --mode local_gpu`
  returned `ok: true` with `warnings: []`
- `python scripts/hpc/render_main_quest_config.py --mode hpc_gpu`
  returned `ok: true` with `warnings: []`
- the persisted validation reports under `data/work/cache/generated_configs/` likewise reported
  success without an explicit truth boundary

After this pass:

- `python scripts/hpc/render_main_quest_config.py --mode local_gpu` still returns `ok: true`, but
  now pairs that with `status_scope: operator_shell_only`,
  `validation_scope: operator_shell_config_only`,
  `full_pipeline_runnable_claimed: false`,
  `strict_runtime_readiness_checked: false`,
  `example_overlay: true`, and explicit warnings that the overlay is an example/prep surface and
  that model endpoints were not runtime-validated
- `python scripts/hpc/render_main_quest_config.py --mode hpc_gpu` now returns the same truth
  boundary metadata plus an HPC-specific warning that cluster interpreter/storage values were not
  strict-runtime validated
- the persisted validation reports under `data/work/cache/generated_configs/` now carry the same
  explicit metadata and warnings

## Validation Performed

- `python -m py_compile scripts/hpc/render_main_quest_config.py src/kc_l/runtime/main_quest_config.py tests/test_main_quest_config.py`
- `python scripts/hpc/render_main_quest_config.py --mode local_gpu`
- `python scripts/hpc/render_main_quest_config.py --mode hpc_gpu`
- `python scripts/local/run_stage.py --json status`
- `python scripts/maintenance/check_operator_repo.py`

`python -m pytest tests/test_main_quest_config.py` could not run in the current interpreter because
`pytest` is not installed there.

## Forbidden Surfaces Confirmed Untouched

This pass did not edit any of the preserved low-level runners or protected
`steps/step_06_main_quest_execution/resources/step6_main_quest_v1.*` files named in the pass
constraints. The pass write set stayed within the validator, renderer, test, audit-note, and
changelog surfaces.

## Exact Next Recommended Pass

Add an opt-in strict runtime readiness probe for the main-quest overlays, separate from the current
default operator-shell validator, so the repo can intentionally distinguish:

- config/example validity
- local-machine interpreter and device readiness
- cluster/HPC launch readiness

That next pass should remain additive and should not rewrite the preserved execution ladder or
change the historically anchored late-stage configs.
