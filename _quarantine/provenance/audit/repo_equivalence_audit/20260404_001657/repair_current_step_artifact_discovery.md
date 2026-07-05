# Repair Note: Current Step Artifact Discovery

Date: 2026-04-05
Scope: local-only current-artifact discovery repair in `R:\Thesis Project\KC_L v2 - Cleaner`

## Recovered State Summary

This pass was grounded in the April 4 audit bundle plus the immediately preceding Step 5 / Step 6
resource de-pinning pass. After that prior pass, the live Step 5 and Step 6 clean-start templates
no longer hardcoded dated historical processed artifacts, but they still depended on manual
placeholder replacement for four required current inputs:

- the Step 1 `kc_registry.jsonl`
- the Step 1.5 `overlay_manifest.json`
- the Step 6.6 set manifest
- the Step 6.7 set manifest

The preserved runners were still off-limits, so the minimal honest repair had to happen outside the
runner logic. The chosen convention was:

- stable current-artifact alias files under `data/work/cache/current_step_artifacts/`
- one runtime helper that discovers the latest compatible source artifacts under the retained
  `data/processed/...` families
- one maintenance script that can either refresh those aliases or report missing-current-artifact
  failures explicitly

## Files Changed

Runtime / maintenance layer:
- `src/kc_l/runtime/current_step_artifacts.py`
- `src/kc_l/runtime/__init__.py`
- `scripts/maintenance/refresh_current_step_artifacts.py`
- `tests/test_current_step_artifacts.py`

Current template updates:
- `steps/step_05_kc_evidence_mining/resources/step5.default.yaml`
- `steps/step_05_2_evidence_sharpen/resources/step5_2.default.yaml`
- `steps/step_05_3_evidence_recalibrated/resources/step5_3.default.yaml`
- `steps/step_06_6_kc_drafting_input_overlay/resources/step6_6.slice10.yaml`
- `steps/step_06_6_kc_drafting_input_overlay/resources/step6_6.full128.yaml`
- `steps/step_06_7_kc_draft_generation/resources/step6_7.slice10.yaml`
- `steps/step_06_7_kc_draft_generation/resources/step6_7.full128.yaml`
- `steps/step_06_8_kc_review_packet_emission/resources/step6_8.slice10.yaml`
- `steps/step_06_8_kc_review_packet_emission/resources/step6_8.full128.yaml`

Minimal directly affected docs / audit trail:
- `steps/README.md`
- `CHANGELOG.md`

Historical configs were preserved as historical and were not converted back into live defaults.

## Exact Current-Artifact Discovery Convention Introduced

Stable alias root:
- `data/work/cache/current_step_artifacts/`

Stable alias files used by the live clean-start templates:
- `data/work/cache/current_step_artifacts/step1_kc_registry.current.jsonl`
- `data/work/cache/current_step_artifacts/step1_5_overlay_manifest.current.json`
- `data/work/cache/current_step_artifacts/step6_6_set_manifest.current.json`
- `data/work/cache/current_step_artifacts/step6_7_set_manifest.current.json`

Status file written by the refresh path:
- `data/work/cache/current_step_artifacts/current_step_artifacts.status.json`

Discovery rules:
- Step 1 registry
  - latest compatible `data/processed/hierarchy/*/kc_registry.jsonl`
  - selected by latest parent directory name under that glob
- Step 1.5 overlay manifest
  - latest compatible `data/processed/hierarchy_overlay/*/overlay_manifest.json`
  - selected by latest parent directory name under that glob
- Step 6.6 set manifest
  - latest compatible `data/processed/kc_drafting_input_overlay/_sets/*_step6_6_kc_drafting_input_overlay_set.json`
  - selected by latest file name under that glob
- Step 6.7 set manifest
  - latest compatible `data/processed/kc_drafts/_sets/*_step6_7_kc_drafts_set.json`
  - selected by latest file name under that glob

Refresh / check command:
- `python scripts/maintenance/refresh_current_step_artifacts.py`
  - refreshes the alias files and writes the status JSON
- `python scripts/maintenance/refresh_current_step_artifacts.py --check`
  - reports discovery status without writing alias files

Truth boundary:
- this layer resolves current alias files for the clean-start Step 5 / Step 6 templates
- it does not claim semantic correctness or full retained-pipeline runtime readiness

## Before / After Placeholder Dependence Summary

Before this pass:
- live Step 5 defaults depended on manual replacement of a Step 1 run-id placeholder
- live Step 6.6 templates depended on manual replacement of a Step 1.5 run-id placeholder
- live Step 6.7 templates depended on manual replacement of a Step 6.6 run-id placeholder
- live Step 6.8 templates depended on manual replacement of a Step 6.7 run-id placeholder

After this pass:
- live Step 5 defaults point to the stable Step 1 current-registry alias
- live Step 6.6 templates point to the stable Step 1.5 overlay-manifest alias
- live Step 6.7 templates point to the stable Step 6.6 set-manifest alias
- live Step 6.8 templates point to the stable Step 6.7 set-manifest alias
- no live current/default Step 5 or Step 6 config now requires manual placeholder replacement for
  normal current-path resolution

## Honest Missing-Artifact Failure Behavior

`python scripts/maintenance/refresh_current_step_artifacts.py --check` on this clean local clone now
fails explicitly with precise missing-current-artifact messages, including:

- no current Step 1 registry discovered under `data/processed/hierarchy/*/kc_registry.jsonl`
- no current Step 1.5 overlay manifest discovered under `data/processed/hierarchy_overlay/*/overlay_manifest.json`
- no current Step 6.6 set manifest discovered under `data/processed/kc_drafting_input_overlay/_sets/*_step6_6_kc_drafting_input_overlay_set.json`
- no current Step 6.7 set manifest discovered under `data/processed/kc_drafts/_sets/*_step6_7_kc_drafts_set.json`

The messages also name the exact upstream runner to execute first.

## Validation Performed

Validated in this pass:
- `python -m py_compile src/kc_l/runtime/current_step_artifacts.py src/kc_l/runtime/__init__.py scripts/maintenance/refresh_current_step_artifacts.py tests/test_current_step_artifacts.py`
- `python scripts/maintenance/refresh_current_step_artifacts.py --check`
  - returned `ok: false` with explicit missing-current-artifact messages on this clone
- synthetic temp-directory validation of `refresh_current_step_artifacts(..., persist=True)`
  - confirmed that all four stable alias files are written when compatible source artifacts exist

`python -m pytest tests/test_current_step_artifacts.py` could not run in the current interpreter
because `pytest` is not installed there.

## Forbidden Surfaces Confirmed Untouched

No edits were made to:
- `steps/step_03_doctree_index/scripts/run_step3.py`
- `steps/step_03_5_blockstore_cleanup/scripts/run_step3_5.py`
- `steps/step_03_6_math_salvage/scripts/run_step3_6.py`
- `steps/step_04_structure_retrieval_index/scripts/run_step4.py`
- `steps/step_04_structure_retrieval_index/scripts/run_step4_3.py`
- `steps/step_04_5_sentence_overlay/scripts/run_step4_5.py`
- `steps/step_05_kc_evidence_mining/scripts/run_step5.py`
- `steps/step_05_2_evidence_sharpen/scripts/run_step5_2.py`
- `steps/step_05_3_evidence_recalibrated/scripts/run_step5_3.py`
- `steps/step_06_6_kc_drafting_input_overlay/scripts/run_step6_6_kc_drafting_input_overlay.py`
- `steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py`
- `steps/step_06_8_kc_review_packet_emission/scripts/run_step6_8_kc_review_packet_emission.py`
- `steps/step_06_main_quest_execution/resources/step6_main_quest_v1.base.yaml`
- `steps/step_06_main_quest_execution/resources/step6_main_quest_v1.local_gpu.yaml`
- `steps/step_06_main_quest_execution/resources/step6_main_quest_v1.hpc_gpu.yaml`

## Exact Next Recommended Pass

Expose the new current-artifact discovery state through the operator maintenance/status surface, so
`check_operator_repo.py` or a similar operator-shell report can tell the user whether the late-stage
current aliases are ready, stale, or missing without requiring a separate manual check command.
