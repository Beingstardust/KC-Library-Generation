# AGENTS.md

This file is the durable repo-local operating guide for work inside this repository.

It is the repo-grounded source of truth for how coding sessions should proceed when chat history is crowded, partially missing, or inconsistent with durable artifacts.

## Mission

This repository exists to build a thesis-grade, evidence-grounded, human-supervised Knowledge Library pipeline, with current active focus on the KC drafting and review boundary.

Current practical mission:
- improve Step 6.7 drafting quality
- preserve Step 6.8 reviewer packet usefulness and completeness
- keep the architecture domain-agnostic at the control-logic level
- preserve curriculum coverage and review-lane survival

Do not treat this repo as a general brainstorming sandbox.
Work should be narrow, auditable, and grounded in repo artifacts.

## Project invariants

These are durable and must not be violated.

1. Machine-generated KCs are drafts only.
2. Final usable KC library contains only human-approved KCs.
3. Primary expert actions remain:
   - Approve
   - Edit
   - Reject
4. `kc_specific_criteria` must remain present and empty at drafting time.
5. Every hierarchy KC must survive into the review lane and the KC library.
6. Topic and KC layers remain distinct typed layers.
7. Core control logic must remain domain-agnostic.
8. Data Mining is a validation corpus, not architecture-specific truth.
9. Sparse fields are acceptable.
10. Do not invent unsupported content to make drafts or packets look complete.
11. Be strict on:
    - contradiction
    - sibling leakage
    - foreign provenance
    - fake scope
    - unsupported added meaning
12. Be softer on source-faithful normalization when evidence is local, traceable, and meaning-preserving.

## Active stage boundary

Unless durable repo artifacts explicitly show otherwise, current active engineering focus is:

- Step 6.7 drafting
- Step 6.8 reviewer packet emission
- immediate upstream dependencies that materially affect Step 6.7 quality

Do not broaden into downstream stages unless strictly required for compatibility and explicitly documented.

Do not reopen raw extraction or unrelated earlier stages unless artifact evidence shows they are the dominant current bottleneck.

## Active production path

Prefer patching the active production path, not obsolete compatibility code.

Current active path:
- `steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py`
- `src/kc_l/kc_drafting/orchestration.py`
- `src/kc_l/kc_drafting/backend.py`
- `src/kc_l/kc_drafting/heuristic_core.py`
- `src/kc_l/utils/kc_step67_model_drafting.py`

Current Step 6.8 path:
- `steps/step_06_8_kc_review_packet_emission/scripts/run_step6_8_kc_review_packet_emission.py`
- `src/kc_l/kc_drafting/orchestration.py`
- `src/kc_l/kc_drafting/packetization.py`

Historical compatibility code under `src/kc_l/kc/` must not be patched unless the active path truly depends on it.

## Task modes

Every session must declare one of these modes before doing work.

### Mode A: Audit only

Use when evaluating run quality, diagnosing regressions, or deciding whether a candidate run should become the new baseline.

Rules:
- do not edit production code in the first pass
- recover state from repo artifacts first
- separate direct evidence from inference
- audit actual artifacts, not just summary counts
- end with a baseline decision or a smallest-next-move recommendation

### Mode B: Patch implementation

Use only after an audit proves a real remaining defect.

Rules:
- patch the smallest domain-agnostic seam that explains the defect
- do not broaden scope without artifact evidence
- do not add Data Mining specific rules, KC-specific exceptions, or corpus-specific hacks
- validate with py_compile, targeted tests, and artifact-driven replay or rerun evidence
- distinguish local proof from authoritative rerun proof

### Mode C: Rerun / validation

Use when code is already patched and the goal is to measure effect.

Rules:
- state exact config, exact run command, and exact target run ids
- report authoritative counts and compare against the accepted baseline
- do not claim improvement without new artifacts
- record whether the rerun is local-mirror only or authoritative Sofja proof

## Execution environments

There are two working environments and they must not be conflated.

### Local mirror

Purpose:
- code inspection
- forensics
- prompt-driven coding work
- bounded local validation
- sync target for authoritative artifacts

### Sofja authoritative repo

Purpose:
- authoritative reruns
- Slurm jobs
- final run artifacts used for acceptance decisions

Rules:
- local mirror audits do not by themselves prove authoritative improvement
- authoritative Sofja reruns outrank local mirror results
- after meaningful Sofja reruns, sync back the changed source files, relevant run artifacts, set manifests, and current-step manifests
- do not assume the local mirror contains the latest authoritative artifacts until verified

## Working style

- Be decisive, exact, and repo-grounded.
- Prefer the smallest coherent fix that attacks the real bottleneck.
- Do not ask the user to manually inspect files or patch files unless blocked by actual filesystem or permission issues.
- Do not ask for permission for small repo-local actions when the task is already clear.
- Do not rely on chat memory when durable repo artifacts exist.
- Do not make broad speculative redesigns without artifact evidence.
- Quality is more important than quickness.
- Another tiny low-yield patch is worse than one well-justified higher-yield patch.

## Recovery and artifact precedence

When recovering state, use this precedence order:

1. live source files in this repo
2. latest authoritative processed artifacts and set manifests
3. `docs/operator_notes/CODEX_ACTIVE_STEP6_REFACTOR_STATE.md`
4. `CHANGELOG.md`
5. `AGENTS.md`
6. chat memory only when confirmed against repo artifacts

If chat memory conflicts with durable repo artifacts, durable repo artifacts win.

## Mandatory session recovery

At the start of each coding session, read at minimum:

- `AGENTS.md`
- `CHANGELOG.md`
- `docs/operator_notes/CODEX_ACTIVE_STEP6_REFACTOR_STATE.md`
- exact source files likely on the active production path
- latest relevant processed artifacts
- latest relevant current-step alias files under `data/work/cache/current_step_artifacts/`

Before making edits, write a concise recovered-state summary in the coding thread or durable note.

## Mandatory compaction control

Assume long sessions can lose context.

A durable state note must be updated:
- before a major architectural edit
- after any meaningful patch
- after any validation replay
- before switching subtasks
- before ending the session
- whenever the thread is getting crowded

Canonical durable state note:
- `docs/operator_notes/CODEX_ACTIVE_STEP6_REFACTOR_STATE.md`

This file must always contain:
- current objective
- recovered state summary
- exact files changed in the current session
- exact commands run
- exact validations passed
- exact validations failed
- latest important artifact paths
- current known risks
- exact next action
- explicit stop point for resume

## Common validation commands

Use repo-relative commands and adjust interpreter path per environment.

Typical compile validation:
- `python -m py_compile <touched files>`

Typical Step 6.7 entrypoint:
- `python steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py --config <config_path>`

Typical Step 6.8 entrypoint:
- `python steps/step_06_8_kc_review_packet_emission/scripts/run_step6_8_kc_review_packet_emission.py --config <config_path>`

Typical forensic entrypoints:
- `python scripts/forensics/compare_step67_runs.py --candidate-run-id <run_id> --output-json <path>`
- `python scripts/forensics/audit_step67_definition_not_grounded.py`

Typical current-artifact refresh:
- `python scripts/maintenance/refresh_current_step_artifacts.py`

When reporting commands, always record the exact command actually run in the durable state note.

## Validation rules

Never claim success without evidence.

Minimum validation after code changes:
1. `py_compile` on touched Python files
2. targeted tests for the changed contract
3. artifact-driven rescan or bounded replay proving expected direction of effect
4. separate local proof from authoritative rerun proof

When reporting validation:
- distinguish synthetic or unit proof from real artifact proof
- distinguish local mirror validation from authoritative Sofja rerun proof
- state exactly what remains unproven

## Truthfulness rules

Do not:
- fake groundedness
- silently weaken truth validation
- hide a broken Step 6.7 by widening Step 6.8
- claim reruns happened without concrete artifacts
- claim a patch is high-yield without real counts
- move Data Mining specific rules into generic control logic

## Current decision focus

Do not assume the dominant bottleneck class from older sessions.

Current priority is:
1. determine whether the latest Step 6.7 candidate run is strong enough to become the accepted baseline
2. if not, identify the smallest remaining domain-agnostic defect from artifacts
3. only then patch and rerun

Do not anchor on older fallback taxonomies unless the latest artifacts still support them.

## Definition of done

Done depends on task mode.

### Audit-only done means
- exact files used are named
- direct evidence is separated from inference
- candidate run quality is judged from artifacts, not just metrics
- an explicit baseline decision is made

### Patch done means
- smallest relevant files changed
- py_compile passed on touched files
- targeted tests passed or exact reason they could not run is stated
- artifact-driven proof shows expected direction of effect
- durable state note and changelog are updated

### Rerun done means
- rerun completed with concrete run artifacts
- authoritative counts are reported
- comparison against accepted baseline is explicit
- remaining risks are stated exactly

## CHANGELOG discipline

Keep the repo-root `CHANGELOG.md` updated for every repo change made during a session.

Each entry should state:
- date
- what changed
- where it changed
- why it changed
- validation scope when important

## Closeout requirements

Before ending a session:
1. update `docs/operator_notes/CODEX_ACTIVE_STEP6_REFACTOR_STATE.md`
2. update `CHANGELOG.md` if behavior changed
3. ensure the active state note includes the exact next action
4. record any files that must be synced back to the authoritative Sofja repo

Do not leave important state only in chat memory.