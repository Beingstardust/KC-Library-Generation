# Repair Note: Step 5 And Step 6 Resource Default De-Pinning

Date: 2026-04-05
Scope: local-only late-stage resource truthfulness repair in `R:\Thesis Project\KC_L v2 - Cleaner`

## Recovered State Summary

This pass was grounded in the April 4 forensic audit bundle plus the retained Step 5 and Step 6
resource YAMLs and runner expectations. The audit had already established that the shipped Step 5
and Step 6 resource files were still pointing at dated processed artifacts from historical runs.

Repo-grounded facts that shaped this repair:
- `steps/step_05_kc_evidence_mining/resources/step5.default.yaml`,
  `steps/step_05_2_evidence_sharpen/resources/step5_2.default.yaml`, and
  `steps/step_05_3_evidence_recalibrated/resources/step5_3.default.yaml` all hardcoded the same
  dated `kc_registry_path` from `data/processed/hierarchy/20260228T211719Z/kc_registry.jsonl`
- `steps/step_06_6_kc_drafting_input_overlay/resources/step6_6.slice10.yaml` and
  `steps/step_06_6_kc_drafting_input_overlay/resources/step6_6.full128.yaml` hardcoded a dated
  hierarchy overlay manifest under `data/processed/hierarchy_overlay/2026-03-10_005659_hierarchy_overlay/`
- `steps/step_06_7_kc_draft_generation/resources/step6_7.slice10.yaml` and
  `steps/step_06_7_kc_draft_generation/resources/step6_7.full128.yaml` hardcoded dated Step 6.6
  set manifests
- `steps/step_06_8_kc_review_packet_emission/resources/step6_8.slice10.yaml` and
  `steps/step_06_8_kc_review_packet_emission/resources/step6_8.full128.yaml` hardcoded dated Step 6.7
  set manifests
- the preserved runners were left untouched, so the repair had to work by changing resource roles
  rather than changing runner semantics
- there is no current active-pointer convention for the Step 1 KC registry, the Step 1.5 overlay
  manifest, or the Step 6.6 / Step 6.7 set manifests in this clean repo, so those inputs had to
  become explicit placeholders rather than fake current paths

## Files Changed

Current/default resource role updates:
- `steps/step_05_kc_evidence_mining/resources/step5.default.yaml`
- `steps/step_05_2_evidence_sharpen/resources/step5_2.default.yaml`
- `steps/step_05_3_evidence_recalibrated/resources/step5_3.default.yaml`
- `steps/step_06_6_kc_drafting_input_overlay/resources/step6_6.slice10.yaml`
- `steps/step_06_6_kc_drafting_input_overlay/resources/step6_6.full128.yaml`
- `steps/step_06_7_kc_draft_generation/resources/step6_7.slice10.yaml`
- `steps/step_06_7_kc_draft_generation/resources/step6_7.full128.yaml`
- `steps/step_06_8_kc_review_packet_emission/resources/step6_8.slice10.yaml`
- `steps/step_06_8_kc_review_packet_emission/resources/step6_8.full128.yaml`

Historical-role preservation or clarification:
- `steps/step_05_kc_evidence_mining/resources/step5.historical_pinned_registry_20260228.yaml`
- `steps/step_05_2_evidence_sharpen/resources/step5_2.historical_pinned_registry_20260228.yaml`
- `steps/step_05_3_evidence_recalibrated/resources/step5_3.historical_pinned_registry_20260228.yaml`
- `steps/step_06_6_kc_drafting_input_overlay/resources/step6_6.slice10_historical_overlay_20260310.yaml`
- `steps/step_06_6_kc_drafting_input_overlay/resources/step6_6.full128_historical_overlay_20260310.yaml`
- `steps/step_06_7_kc_draft_generation/resources/step6_7.slice10_historical_set_20260322.yaml`
- `steps/step_06_7_kc_draft_generation/resources/step6_7.full128_historical_set_20260327.yaml`
- `steps/step_06_8_kc_review_packet_emission/resources/step6_8.slice10_historical_set_20260323.yaml`
- `steps/step_06_8_kc_review_packet_emission/resources/step6_8.full128_historical_set_20260327.yaml`
- `steps/step_06_6_kc_drafting_input_overlay/resources/step6_6.slice24.yaml`
- `steps/step_06_6_kc_drafting_input_overlay/resources/step6_6.slice48.yaml`
- `steps/step_06_7_kc_draft_generation/resources/step6_7.slice24.yaml`
- `steps/step_06_7_kc_draft_generation/resources/step6_7.slice48.yaml`
- `steps/step_06_8_kc_review_packet_emission/resources/step6_8.slice24.yaml`
- `steps/step_06_8_kc_review_packet_emission/resources/step6_8.slice48.yaml`

Minimal directly affected docs:
- `steps/README.md`
- `CHANGELOG.md`

## Exact Pinned Paths Removed Or Reclassified

Removed from the live current/default role:
- `data/processed/hierarchy/20260228T211719Z/kc_registry.jsonl`
  from Step 5, Step 5.2, and Step 5.3 current defaults
- `data/processed/hierarchy_overlay/2026-03-10_005659_hierarchy_overlay/overlay_manifest.json`
  from Step 6.6 `slice10` and `full128` current templates
- `data/processed/kc_drafting_input_overlay/_sets/2026-03-22_210716_step6_6_kc_drafting_input_overlay_set.json`
  from Step 6.7 `slice10`
- `data/processed/kc_drafting_input_overlay/_sets/2026-03-27_112701_step6_6_kc_drafting_input_overlay_set.json`
  from Step 6.7 `full128`
- `data/processed/kc_drafts/_sets/2026-03-23_001608_step6_7_kc_drafts_set.json`
  from Step 6.8 `slice10`
- `data/processed/kc_drafts/_sets/2026-03-27_112751_step6_7_kc_drafts_set.json`
  from Step 6.8 `full128`

Reclassified as historical or preserved historical:
- all of the pinned values above now survive only in explicit `historical_*` YAMLs or in bounded
  `slice24` / `slice48` files that now carry historical-role comments

## Exact New Config Role Structure Introduced

Current clean-start templates:
- Step 5 / 5.2 / 5.3 `*.default.yaml`
  - keep stable active-pointer inputs where those already exist
  - replace the dated Step 1 KC registry with
    `data/processed/hierarchy/REPLACE_WITH_STEP1_RUN_ID/kc_registry.jsonl`
- Step 6.6 `slice10` and `full128`
  - keep the stable active Step 4 / 4.5 / 5.3 pointers
  - replace the dated Step 1.5 overlay manifest with
    `data/processed/hierarchy_overlay/REPLACE_WITH_STEP1_5_RUN_ID/overlay_manifest.json`
- Step 6.7 `slice10` and `full128`
  - replace the dated Step 6.6 set manifests with
    `data/processed/kc_drafting_input_overlay/_sets/REPLACE_WITH_STEP6_6_RUN_ID_step6_6_kc_drafting_input_overlay_set.json`
- Step 6.8 `slice10` and `full128`
  - replace the dated Step 6.7 set manifests with
    `data/processed/kc_drafts/_sets/REPLACE_WITH_STEP6_7_RUN_ID_step6_7_kc_drafts_set.json`

Historical/example surfaces:
- the newly added `historical_*` copies preserve the previously shipped pinned values explicitly
- the retained `slice24` and `slice48` Step 6 files now carry comments stating that they are
  historical bounded configs rather than clean-start defaults
- the already dated or scenario-specific one-off files such as `full128_quality_redraft_*`,
  `eval_model_comparison_sandbox10`, and `slice48_patchrun_*` were left untouched because their
  names already mark them as non-current calibrations or one-off runs

## Before / After Current Versus Historical Summary

Before this pass:
- Step 5 `default` files looked like current defaults but hardcoded a dated hierarchy registry
- Step 6 `slice10` runner-default files looked like current defaults but hardcoded dated overlay or
  set-manifest inputs
- Step 6 `full128` files looked like current full-run configs but hardcoded dated overlay or
  set-manifest inputs
- several bounded historical Step 6 files had no explicit comment saying they were historical

After this pass:
- Step 5 `default` files are clean-start templates with explicit Step 1 placeholders
- Step 6 `slice10` runner-default files are clean-start templates with explicit Step 1.5 / 6.6 / 6.7 placeholders
- Step 6 `full128` files are clean-start full-run templates with explicit Step 1.5 / 6.6 / 6.7 placeholders
- the old pinned current/default contents are preserved under explicit `historical_*` filenames
- the bounded `slice24` and `slice48` Step 6 files are now explicitly marked historical in comments
- `steps/README.md` now explains the clean-start-template versus historical-config split

## Validation Performed

Validated in this pass:
- read back all modified Step 5 defaults, Step 6 runner-defaults, and Step 6 `full128` templates
- confirmed the placeholders replaced the dated live current/default pins
- confirmed the preserved historical YAML copies exist under explicit historical names
- confirmed the bounded historical Step 6 `slice24` / `slice48` files now carry historical-role comments
- confirmed `steps/README.md` reflects the new resource-role split

No runner code was changed and no strict runtime probe was added in this pass.

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

Add a clean current-pointer or generated-artifact discovery convention for the Step 1 KC registry,
Step 1.5 overlay manifest, and the Step 6.6 / Step 6.7 set manifests, so the new clean-start
Step 5 and Step 6 templates can stop using explicit placeholders and can resolve current artifacts
honestly without reintroducing dated historical defaults.
