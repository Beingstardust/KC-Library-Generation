# Repair Note: Operator Shell Truthfulness Alignment

Date: 2026-04-04
Scope: local-only public-shell/doc alignment in `R:\Thesis Project\KC_L v2 - Cleaner`

## Recovered State Summary

This pass aligned the clean public operator/docs surface with the restored legacy execution-authority
and root launcher surfaces. It did not redesign the architecture, rewrite the preserved internal
step ladder, de-pin historically anchored Step 5 or Step 6 resource defaults, or touch the
parity-bearing late-stage runners.

The guiding repo-grounded facts were:
- the public shell is an operator-shell readiness and discoverability layer
- the preserved `steps/` tree remains the real downstream execution lane
- the restored `PROJECT_STATE` docs remain meaningful execution-authority surfaces
- the restored `run_step6_7_model_draft_generation.py` and root `step6_6_*.yaml`,
  `step6_7_*.yaml`, and `step6_8_*.yaml` family are real late-stage launch surfaces

## Files Changed

Docs:
- `README.md`
- `docs/architecture/operator_repo.md`
- `docs/workflows/offline_generation_lifecycle.md`
- `docs/workflows/hpc_first_run_preparation.md`
- `steps/README.md`

Thin public shell:
- `src/kc_l/runtime/operator_stages.py`
- `scripts/local/run_stage.py`
- `scripts/maintenance/check_operator_repo.py`

Audit/changelog:
- `audit/repo_equivalence_audit/20260404_001657/repair_operator_shell_truthfulness_alignment.md`
- `CHANGELOG.md`

## Exact Doc Claims Removed Or Rewritten

Rewritten claims:
- `README.md` no longer frames the public shell as a replacement for the research-era execution
  ladder.
- `README.md` now says the public scripts are mainly readiness, intake, and discoverability
  surfaces.
- `README.md` now explicitly lists the restored `PROJECT_STATE` authority docs, retained
  `step6_main_quest_v1.*` resources, restored `run_step6_7_model_draft_generation.py`, and the
  restored root late-stage YAML family.
- `README.md` now says operator-shell readiness is not proof that every preserved late-stage legacy
  surface is runnable out of the box.
- `docs/architecture/operator_repo.md` now says the public control plane is a shell over the
  preserved execution lane rather than an honest replacement for it.
- `docs/workflows/offline_generation_lifecycle.md` now says the public stage model is an operator
  abstraction over the retained ladder, not the same thing as replacing it.
- `docs/workflows/offline_generation_lifecycle.md` now makes the intake story explicit:
  `scripts/local/run_corpus_intake.py` is primary, the repaired PowerShell wrapper is a Windows
  legacy helper, and the preserved `steps/` tree remains the downstream lane.
- `docs/workflows/hpc_first_run_preparation.md` now says the public HPC renderer is a preparation
  and discoverability surface, not proof that the full preserved pipeline is runnable end to end.
- `steps/README.md` no longer tells the user to treat the public shell as a replacement for the
  retained execution ladder.

## Exact Shell / Status Wording Changes

- `scripts/local/run_stage.py`
  - parser description now says the CLI is an operator-shell readiness and discoverability surface
  - subcommand help text now says `status`, `intake`, `draft-preflight`, `review-preflight`, and
    `freeze-preflight` are operator-shell inspections or preflights
  - `list` text output now ends with a note that the shell is not a full replacement for the
    retained legacy execution ladder
- `src/kc_l/runtime/operator_stages.py`
  - stage descriptions now explicitly say `operator-shell`
  - `draft_generation` now exposes the preserved Step 3.5 -> 6.8 lane in `internal_surfaces`
  - intake and draft preflights now return `status_scope: operator_shell_only`
  - intake and draft preflights now return a `truth_boundary` string and
    `full_pipeline_runnable_claimed: false`
  - status/preflight payloads now include `legacy_execution_surfaces`, exposing the restored
    `PROJECT_STATE` docs, retained `step6_main_quest_v1.*` resources, restored
    `run_step6_7_model_draft_generation.py`, and the restored root YAML families
  - `PROJECT_STATE` is no longer treated as a fatal historical-live-surface error
- `scripts/maintenance/check_operator_repo.py`
  - now emits `status_scope`, `truth_boundary`, `full_pipeline_runnable_claimed`, and
    `legacy_execution_surfaces` so the maintenance view reflects the same honesty boundary

## Validation Snapshot

Validated in this pass:
- `python -m py_compile scripts/local/run_stage.py scripts/maintenance/check_operator_repo.py src/kc_l/runtime/operator_stages.py`
- `python scripts/local/run_stage.py list`
- `python scripts/local/run_stage.py --json status`
- `python scripts/local/run_stage.py --json intake`
- `python scripts/local/run_stage.py --json draft-preflight`
- `python scripts/maintenance/check_operator_repo.py`

Observed outcomes:
- `status` now reports `ok: true` for the operator shell on this local clone
- `status` and preflights now explicitly declare their `operator_shell_only` scope
- `status` and preflights now expose the restored legacy execution surfaces instead of silently
  ignoring them
- `check_operator_repo.py` now exposes the same truth boundary instead of implying full-pipeline
  certification

## Forbidden Files Confirmed Untouched

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

Make the new config-render truth boundary honest as well. The next narrow pass should align
`src/kc_l/runtime/main_quest_config.py` and `scripts/hpc/render_main_quest_config.py` with the same
operator-shell-only wording and stop treating example overlays as if they certify real late-stage
runnability.
