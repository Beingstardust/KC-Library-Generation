# CODEX Step6X Curriculum Representation Layer

Date: 2026-04-09

## Recovered State

- Durable Step 1 atomic KC authority is `data/work/cache/current_step_artifacts/step1_kc_registry.current.jsonl`, resolved to `data/processed/hierarchy/20260407T125310Z/kc_registry.jsonl`.
- Durable hierarchy ancestry authority is `data/work/cache/current_step_artifacts/step1_5_overlay_manifest.current.json`, with leaf ancestry in `data/processed/hierarchy_overlay/2026-04-08_103432_hierarchy_overlay/leaf_to_overlay_ancestry.json`.
- Durable current Step 6.7 draft set is `data/work/cache/current_step_artifacts/step6_7_set_manifest.current.json`, pointing at `data/processed/kc_drafts/2026-04-08_131447/`.
- Durable pre-existing Step 6.8 ready surface was `data/processed/kc_review_packets_restarted/2026-04-08_204029/`.
- The repo-local actual-corpus problem was structural, not merely packet-count related: Step 1 still represented all 144 atomic curriculum KCs, but the ready reviewer lane was narrower and there was no durable parallel manifest preserving curriculum existence outside the ready lane.
- No local approved/frozen KC library artifact is present in this repo copy at the time of this pass. The approved-only boundary therefore had to remain explicit and untouched rather than guessed.

## Decision

Implement a parallel coverage-complete curriculum KC representation layer at Step 6.8 instead of weakening the approved-only frozen library or pretending the ready reviewer lane is equivalent to curriculum existence.

This pass keeps three layers separate:

1. Coverage-complete curriculum representation
   One row per Step 1 atomic KC, regardless of Step 6.7 / Step 6.8 conservatism.
2. Review-ready packet lane
   Only KCs that survive the Step 6.8 review boundary.
3. Approved frozen usable library
   Explicitly unchanged and still separate from the two layers above.

## Files Changed

- `src/kc_l/kc/curriculum_kc_coverage.py`
- `steps/step_06_8_kc_review_packet_emission/scripts/run_step6_8_kc_review_packet_emission.py`
- `src/kc_l/kc/restarted_reviewer_session.py`
- `src/kc_l/kc/restarted_human_review_capture.py`
- `steps/step_06_review_supervision/scripts/build_curriculum_kc_coverage_audit.py`
- `src/kc_l/utils/json_io.py`
- `CHANGELOG.md`

## What Changed

### 1. Parallel curriculum representation layer

- Added `curriculum_kc_coverage_manifest.jsonl` and `curriculum_kc_coverage_summary.json` as Step 6.8 sibling artifacts.
- The manifest is keyed by `kc_id` and is built from the Step 1 registry plus Step 1.5 ancestry, overlaid with:
  - current Step 6.7 drafting state
  - current Step 6.8 review-lane state
  - explicit approved-frozen state
  - fallback tier and eligibility flags
  - present-and-empty `kc_specific_criteria`
- The layer is intentionally representational, not a machine-promotion surface:
  - it preserves curriculum anchor data such as canonical name, aliases, hierarchy path, and Step 1 seed definition
  - it does not pretend quarantined or excluded KCs are review-ready
  - it does not modify approved-only semantics

### 2. Step 6.8 runner now emits the coverage layer

- `run_step6_8_kc_review_packet_emission.py` now emits the curriculum coverage artifacts into the same processed directory as the review packets and records them in the Step 6.8 set manifest plus run summary.
- The runner was also made more robust for local repo validation: when Step 4 / Step 4.5 set manifests are unavailable locally but durable upstream path hints exist in Step 6.6 metadata, the runner now derives the set IDs from those hints instead of failing. This preserves provenance labels without pretending the external HPC files are present locally.

### 3. Reviewer queue ordering and wording

- `restarted_reviewer_session.py` now orders the queue to put cleaner and more actionable cases first:
  - `approve_ready`
  - clean review
  - repairable scope-gap review
  - caution review
  - held-salvage / low-support backlog
- The reviewer-session artifacts now reference the curriculum coverage manifest when present and explicitly distinguish:
  - ready packets
  - quarantined packets
  - unrecoverable held exclusions
  - curriculum-only coverage rows

### 4. Human review capture wording

- `restarted_human_review_capture.py` now records quarantined counts separately from unrecoverable held exclusions so the human-review prep surface no longer implies that non-ready KCs vanished.

### 5. Local JSON fallback

- `json_io.py` now falls back to stdlib `json` when `orjson` is unavailable in the active shell.
- This was necessary because the current local operator shell lacked `orjson`, and the Step 6.x regeneration/validation surfaces should remain runnable from repo code rather than depending on hidden environment repair.

## Commands Run

1. `python -m py_compile src/kc_l/kc/curriculum_kc_coverage.py src/kc_l/kc/restarted_reviewer_session.py src/kc_l/kc/restarted_human_review_capture.py steps/step_06_8_kc_review_packet_emission/scripts/run_step6_8_kc_review_packet_emission.py steps/step_06_review_supervision/scripts/build_curriculum_kc_coverage_audit.py`
2. `python steps/step_06_8_kc_review_packet_emission/scripts/run_step6_8_kc_review_packet_emission.py --config steps/step_06_8_kc_review_packet_emission/resources/step6_8.full128.yaml`
3. `python steps/step_06_review_supervision/scripts/build_restarted_human_review_capture_template.py --review-packet-dir data/processed/kc_review_packets_restarted/2026-04-09_010605 --batch-size 12`
4. `python steps/step_06_review_supervision/scripts/build_curriculum_kc_coverage_audit.py --review-packet-dir data/processed/kc_review_packets_restarted/2026-04-09_010605`

## Produced Artifacts

### Live processed Step 6.8 surface

- `data/processed/kc_review_packets_restarted/2026-04-09_010605/`
- Key files:
  - `review_packets.jsonl`
  - `review_packet_summary.json`
  - `curriculum_kc_coverage_manifest.jsonl`
  - `curriculum_kc_coverage_summary.json`
  - `real_reviewer_session_manifest.json`
  - `human_review_capture_manifest.json`

### Standard Step 6.8 run audit

- `data/runs/2026-04-09_010605_step6_8/`

### Curriculum-representation validation bundle

- `data/runs/_audit/2026-04-09_010617_curriculum_kc_coverage_validation/validation_summary.json`

## Validation Results

From `data/processed/kc_review_packets_restarted/2026-04-09_010605/curriculum_kc_coverage_summary.json` and `data/runs/_audit/2026-04-09_010617_curriculum_kc_coverage_validation/validation_summary.json`:

- total curriculum atomic KC count: `144`
- represented KC count: `144`
- missing KC count: `0`
- ready packet count: `105`
- quarantine count: `25`
- excluded count: `14`
- representation tiers:
  - `review_ready_packet`: `105`
  - `coverage_complete_curriculum_only`: `39`
- approved frozen state counts:
  - `not_available_in_repo`: `144`
- drafting state counts:
  - `draft_ready`: `20`
  - `draft_ready_with_holds`: `43`
  - `held`: `81`
- `kc_specific_criteria` present and empty: `true`
- reviewer-session artifacts build: `true`
- human-review capture artifacts build: `true`
- approved frozen library semantics unchanged: `true`

Reviewer-session ordering evidence from the validation bundle:

- session bucket counts:
  - `approve_ready`: `16`
  - `repairable_scope_gap`: `29`
  - `caution_review`: `4`
  - `salvage_backlog`: `56`
- the first 15 session-order rows are all `approve_ready` packets, confirming the queue no longer starts with salvage backlog items.

## Remaining Risks / Open Questions

- The coverage layer fixes representational loss, not semantic weakness. `39` KCs remain outside the ready lane and therefore still require either quarantine review or later drafting improvements before they can become review-ready.
- `56` ready packets remain in the held-salvage / `reject_recommended` backlog. They now remain visible in the system and available for lower-trust fallback, but reviewer burden is still non-trivial.
- No local approved/frozen library artifact is present in this repo copy, so the approved tier is recorded honestly as unavailable rather than inferred.

## Sync To Sofja

Yes. The source changes should later be synced to Sofja because they alter durable Step 6.8 architecture and reviewer-surface behavior:

- coverage-complete curriculum representation is now a real emitted artifact
- Step 6.8 local provenance recovery is more robust
- reviewer queue ordering and wording changed
- validation tooling changed

The processed artifacts in `data/processed/kc_review_packets_restarted/2026-04-09_010605/` and the audit bundle under `data/runs/_audit/2026-04-09_010617_curriculum_kc_coverage_validation/` are also useful reference outputs for the port.

## Exact Next Recommended Action

Proceed with expert review from `data/processed/kc_review_packets_restarted/2026-04-09_010605/` rather than the older `2026-04-08_204029` surface, using:

- the ready reviewer lane for human decisions
- the new curriculum coverage manifest as the lower-trust fallback layer for segmentation and evaluator-context use

Do not rerun Step 6.7 before that review. The highest-value next improvement after review would be targeted reduction of the `39` curriculum KCs still outside the ready lane, using the coverage manifest as the durable non-loss baseline.
