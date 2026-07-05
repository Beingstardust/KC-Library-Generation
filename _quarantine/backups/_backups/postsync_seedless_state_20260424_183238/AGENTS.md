# AGENTS.md

This file is the durable repo-local operating guide for the active seedless refactor stage.

It is the repo-grounded source of truth for work inside this editable seedless mirror when chat memory is crowded, stale, or inconsistent with durable repo evidence.

## Mission

This repository exists to make the KC Library architecture honestly seedless while preserving thesis-grade control:

- machine outputs remain drafts only
- final usable KC library remains human-approved only
- topic and KC layers remain distinct typed layers
- coverage survival must come from representation and evidence architecture, not injected seed text

Current practical mission:

- remove KC-leaf `definition` fields from active source-of-truth hierarchy inputs
- remove `seed_definition` and seed-derived scoring from the active Step 5.3 runtime
- remove `seed_definition` from the active architecture
- remove seed-derived fallback and review shortcuts from the active Step 6.6 to Step 6.8 path
- preserve full KC representation coverage without pretending sparse KCs are grounded
- formalize explicit separation between coverage survival, evidence support quality, and review-lane eligibility

`seed_definition` is removed from the active source-of-truth hierarchy, the active Step 5.3 to Step 6.8 runtime, and the active architecture overall. It may not be reintroduced without explicit user approval.

Do not treat this repo as a brainstorming sandbox.
Work should be bounded, auditable, and grounded in live source plus durable repo artifacts.

## Project Invariants

These are non-negotiable.

1. Machine-generated KCs are drafts only.
2. Final usable KC library contains only human-approved KCs.
3. Primary human actions remain `Approve`, `Edit`, and `Reject`.
4. Topic and KC layers remain distinct typed layers.
5. Core control logic must remain domain-agnostic.
6. Data Mining is a validation corpus, not architecture-specific truth.
7. Every curriculum-relevant KC must remain represented somewhere in the system.
8. Coverage survival and review-lane eligibility must stay separate.
9. Do not invent unsupported content.
10. Do not preserve seed semantics under a hidden alias.
11. `kc_specific_criteria` remains present and empty at drafting and packet time.
12. Sparse or unresolved KCs may survive as coverage-only representations, but they are not review-ready by default.

## Active Task Boundary

Unless later durable repo notes explicitly override this, current active engineering scope is:

- source-of-truth hierarchy inputs for KC leaves
- Step 1 and Step 1.5 regeneration prerequisites only when needed to remove stale seed-bearing aliases
- Step 5.3 evidence recalibration
- Step 6.6 drafting input overlay
- Step 6.7 KC draft generation
- Step 6.75 canonicalization compatibility
- Step 6.8 review packet emission
- immediate hierarchy and packet contracts that materially control those stages

Do not broaden into unrelated downstream tasks.
Do not perform full reruns in this task.
Do not patch historical validation-only seed-rescue lanes unless the active production path still depends on them.

## Active Production Path

Prefer patching the active seedless production path, not obsolete compatibility code.

Primary files and entrypoints:

- `data/input/hierarchy/data_mining_kc_hierarchy_revised_.json`
- `steps/step_01_hierarchy/scripts/01_hierarchy_normalize.py`
- `steps/step_01_5_hierarchy_overlay/scripts/run_step01_5_hierarchy_overlay.py`
- `steps/step_05_3_evidence_recalibrated/scripts/run_step5_3.py`
- `steps/step_06_6_kc_drafting_input_overlay/scripts/run_step6_6_kc_drafting_input_overlay.py`
- `steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py`
- `steps/step_06_75_kc_draft_canonicalization/scripts/run_step6_75_kc_draft_canonicalization.py`
- `steps/step_06_8_kc_review_packet_emission/scripts/run_step6_8_kc_review_packet_emission.py`
- `src/kc_l/hierarchy/`
- `src/kc_l/kc/drafting_input_overlay.py`
- `src/kc_l/retrieval_gate/semantic.py`
- `src/kc_l/kc_drafting/contracts.py`
- `src/kc_l/kc_drafting/heuristic_core.py`
- `src/kc_l/kc_drafting/packetization.py`
- `src/kc_l/utils/kc_step67_model_drafting.py`
- `src/kc_l/kc/curriculum_kc_coverage.py`
- `src/kc_l/kc/schemas/review_packet.schema.json`

Historical seed-rescue modules such as Step 6.7B and Step 6.7C are analysis lineage unless the current active manifests explicitly route through them.

## Task Modes

Every session should state one mode before substantial work.

### Mode A: Recovery And Audit

Use when rebuilding state or mapping contamination surfaces.

Rules:

- recover state from repo artifacts first
- separate direct repo evidence from inference
- classify seed dependencies by contract surface
- record the exact stop boundary before patching

### Mode B: Patch Implementation

Use only after the active seam and contamination surfaces are clear.

Rules:

- patch the smallest coherent seedless seam that makes the architecture honest
- remove seed text from source-of-truth inputs before claiming later stages are seedless
- remove active seed-based contracts rather than hiding them
- preserve coverage representation separately from grounded definition support
- keep review-lane eligibility explicit and non-compensatory
- update docs, durable state, and tests in the same session

### Mode C: Validation And Rerun Planning

Use after code changes.

Rules:

- run `py_compile` on touched Python files
- run targeted tests when available
- use deterministic smoke checks when `pytest` is unavailable
- state exactly what remains unproven
- state the minimum authoritative rerun boundary and why

### Mode D: Historical Comparison Only

Use when consulting the seed reference repo or stale artifacts.

Rules:

- reference repo is read-only unless the user explicitly says otherwise
- historical seed-based artifacts may inform diagnosis, not active architecture
- if historical evidence conflicts with live editable-repo source, live editable-repo source wins

## Execution Environments

Do not conflate these environments.

### Editable Seedless Mirror

Path:
- `R:\Thesis Project\kc_l_v2_seedless_rework_sync\20260423_214049_kc_l_v2_seedless_rework_sync\unpacked\repo_source`

Purpose:

- active code edits
- local inspection
- bounded validation
- durable notes and changelog

This tree is a synced mirror, not a live Git checkout at the repo root.

### Seed Architecture Reference Repo

Path:
- `R:\Thesis Project\kc_l_v2_clean_sofja_authoritative_sync\20260421_220803_kc_l_v2_sync\unpacked\repo_source`

Purpose:

- read-only historical comparison
- prior operator-control reference
- old seed-based behavior diagnosis

Do not edit this repo in this stage.

### Authoritative External Environment

Purpose:

- authoritative reruns
- proof beyond local mirror inspection

Rules:

- local mirror edits and smoke checks do not prove authoritative runtime success
- authoritative reruns outrank local mirror assumptions
- if current-step aliases or manifests point to missing or remote targets, record that explicitly instead of pretending the local mirror is complete

## Artifact Precedence

When recovering state or resolving contradictions, use this exact order:

1. live source files in the editable seedless repo
2. durable artifacts and manifests in the editable seedless repo
3. operator notes and changelog in the editable seedless repo
4. seed reference repo for historical comparison
5. stale aliases only if their targets actually exist

If chat memory conflicts with repo evidence, repo evidence wins.

## Mandatory Session Recovery

Before substantive edits, read at minimum:

- `AGENTS.md`
- `CHANGELOG.md`
- `docs/operator_notes/CODEX_ACTIVE_STEP6_REFACTOR_STATE.md`
- relevant active production-path source files
- current-step alias manifests under `data/work/cache/current_step_artifacts/`
- latest durable manifests actually present in the editable repo

Before patching, write a recovered-state summary in the thread and durable state note that includes:

1. exact editable repo root
2. exact reference repo root
3. whether the editable repo is a live Git checkout or a synced mirror
4. exact active objective
5. exact truth boundary
6. likely active files
7. likely seed-definition dependency surfaces
8. rollback plan
9. stop boundary for the task

## Mandatory Compaction Control

Assume long sessions can lose context.

Canonical durable state note:

- `docs/operator_notes/CODEX_ACTIVE_STEP6_REFACTOR_STATE.md`

Update it:

- before a major architectural edit
- after any meaningful patch
- after validation
- before switching subtasks
- before ending the session
- whenever the thread is getting crowded

Each closeout pack in that note must contain:

- current objective
- exact files changed
- exact validations run
- exact validations passed
- exact validations failed
- current risks
- next action
- explicit resume point

## Validation Minimums

Never claim success without evidence.

Minimum validation after code changes:

1. `python -m py_compile` on every touched Python file
2. targeted tests for touched contracts when runnable
3. deterministic smoke checks if `pytest` is unavailable
4. an explicit list of what remains unproven
5. an explicit minimum authoritative rerun boundary

Record the exact commands run in the durable state note.

## Truthfulness Rules

Do not:

- claim the architecture is seedless while active source still depends on seed text
- claim Step 5.3 is seedless while it still reads, scores, or emits `seed_definition`
- treat a historical artifact as authoritative just because it exists
- claim a rerun happened without concrete artifacts
- hide missing local artifacts behind stale aliases
- conflate coverage survival with grounded definition support
- conflate review-lane inclusion with approve-readiness
- silently preserve seed text under a renamed active field

When the repo evidence is incomplete, say so directly.

## CHANGELOG Discipline

Keep the repo-root `CHANGELOG.md` updated for every behavior or contract change made in a session.

Each entry should state:

- date
- what changed
- where it changed
- why it changed
- validation scope when important

## Closeout Requirements

Before ending a session:

1. update `docs/operator_notes/CODEX_ACTIVE_STEP6_REFACTOR_STATE.md`
2. update `CHANGELOG.md`
3. record exact files changed
4. record exact validations run and outcomes
5. record the minimum authoritative rerun boundary
6. record the exact next action or next prompt

Do not leave crucial state only in chat memory.
