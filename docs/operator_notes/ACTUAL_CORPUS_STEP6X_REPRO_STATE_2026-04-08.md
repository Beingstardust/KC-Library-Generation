# Actual-Corpus Step 6.x Reproducibility State
Date: 2026-04-08
Repo: /beegfs1/home/aryp26yc/projects/kc_l_v2_clean

## Scope
This note freezes the current operational truth for the actual-corpus KC drafting branch so future work does not need to rediscover selector-surface drift, scratch-vs-repo storage splits, or the Step 6.7 shadow-runner split.

## Current accepted / important runs
- Step 1.5 hierarchy overlay:
  - run_id: 2026-04-08_103432_hierarchy_overlay
- Step 5.3 accepted actual-corpus baseline:
  - set: 2026-04-07_203250_step5_3_kc_evidence_recalibrated_set.json
- Step 6.6 accepted actual-corpus overlay:
  - run_id: 2026-04-08_105028
  - set_id: 2026-04-08_105028_step6_6_kc_drafting_input_overlay_set
- Step 6.7 model-backed actual-corpus diagnosis run:
  - run_id: 2026-04-08_131447
  - set_id: 2026-04-08_131447_step6_7_kc_drafts_set
- Step 6.7 slice-5 truth check:
  - run_id: 2026-04-08_162229
- Step 6.7 slice-20 adversarial check:
  - run_id: 2026-04-08_162838

## Critical operational truths

### 1. Accepted Step 6.6 branch is valid
The accepted Step 6.6 manifest records real upstream surfaces for:
- Step 1.5 overlay
- Step 4 active set and target
- Step 4.5 active set and target
- Step 5.3 active set and target

### 2. Upstream of Step 6 is not fully self-contained in this clean repo
For the accepted actual-corpus branch:
- Step 4 and Step 4.5 selector surfaces used by Step 6.6 live under scratch
- those scratch paths are recorded in the accepted Step 6.6 set manifest
- local clean-repo upstream selector surfaces are incomplete mirrors of the accepted upstream branch

### 3. Step 6.7 has a real shadow-runner split
- Root runner:
  - run_step6_7_model_draft_generation.py
  - authoritative model-backed lane
- Step-local runner:
  - steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py
  - bounded non-equivalent lane
Do not treat them as interchangeable.

### 4. current_step_artifacts is only a discovery layer
It resolves stable aliases for clean-start templates.
It does NOT certify semantic suitability or full runtime readiness.

### 5. Main current blocker is Step 6.7 quality, not a missing upstream generic stage
Current evidence indicates:
- no missing generic upstream stage before Step 6 has been found
- the dominant remaining issue is Step 6.7 definition-lane quality / recall

## Scratch surfaces currently backing the accepted Step 6.6 branch
Recorded from the accepted Step 6.6 manifest:
- /beegfs2/scratch/aryp26yc/kc_l/data/processed/retrieval_index/_sets/ACTIVE_STEP4_SET.txt
- /beegfs2/scratch/aryp26yc/kc_l/data/processed/retrieval_index/_sets/2026-04-07_000855_step4_3_1_step4_index_set.json
- /beegfs2/scratch/aryp26yc/kc_l/data/processed/retrieval_sentence_overlay/_sets/ACTIVE_STEP4_5_SET.txt
- /beegfs2/scratch/aryp26yc/kc_l/data/processed/retrieval_sentence_overlay/_sets/2026-04-07_104900_step4_5_sentence_set.json

## Naming / selector caveats
- Step 4.5 selector naming is not uniform across all surfaces:
  - ACTIVE_STEP4_5_SET.txt
  - ACTIVE_STEP4_5_SENTENCE_SET.txt
Do not assume those names are interchangeable without checking the actual config and target path.

## Safe operating rule for future work
Before trusting any Step 6.x default config:
1. identify the exact runner
2. identify the exact config
3. identify the exact selector surface that config resolves through
4. confirm whether the selected artifact is local-repo or scratch-resident
5. record the resolved target in notes or a manifest


## Preflight reproducibility check result
Saved report:
- data/runs/_audit/2026-04-08_step6x_repro_surfaces_check.json

### Confirmed by preflight
- step67_root_runner exists
- step67_step_local_runner exists
- step1_registry_alias exists
- step1_5_overlay_alias exists
- step6_6_alias exists
- step6_7_alias exists
- local_step5_active exists
- local_step5_2_active exists
- local_step5_3_active exists
- accepted_branch_step4_active_set_pointer exists on scratch
- accepted_branch_step4_active_set_target exists on scratch
- accepted_branch_step4_5_active_set_pointer exists on scratch
- accepted_branch_step4_5_active_set_target exists on scratch

### Missing locally in clean repo
- local_step4_active
- local_step4_patches_active
- local_step4_5_active
- local_step4_5_sentence_active

### Operational implication
The clean Sofja repo is not self-contained upstream of Step 6.
The accepted actual-corpus Step 6.6 branch remains valid because it resolves through scratch-backed Step 4 / Step 4.5 selector surfaces recorded in the accepted Step 6.6 manifest.

### Alias freshness warning
current_step_artifacts aliases are not guaranteed to track the exploratory run you most recently created.
Before using Step 6.8 defaults or any alias-dependent stage:
1. inspect the alias content
2. refresh aliases intentionally if needed
3. record which exact set_id is being consumed


## Step 6 review boundary clarification
- `build_restarted_human_review_capture_template.py` is valid for the actual-corpus ready packet lane.
- `build_restarted_human_reviewer_pass.py` is a legacy dry-run script with a frozen verdict plan and is not the generic actual-corpus reviewer pass.
- For the current actual-corpus run `2026-04-08_204029`, expert review must proceed from:
  - `reviewer_dry_run_verdicts.json`
  - `human_supervised_draft_actions.json`
  - `manual_inspection_bundle.md`
  - `real_reviewer_session.md`
- Do not patch the legacy dry-run pass to auto-produce actual-corpus verdicts.
- Do not rerun Step 6.7 before measuring review outcomes on the 49 ready packets.
