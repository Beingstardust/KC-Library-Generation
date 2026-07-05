# AGENTS.md

## Project operating rules

This repo is part of the KC_L v2 thesis project. Work must be careful, auditable, domain-agnostic, and model-agnostic.

## Non-negotiable constraints

- Do not hardcode Data Mining terms, KC IDs, textbook names, page numbers, model names, provider names, or Sofja-specific behavior into implementation logic.
- Do not edit `.bak`, `.BEFORE_*`, or historical backup files.
- Do not delete historical artifacts.
- Do not run GPU jobs.
- Do not run full144 jobs.
- Do not run Step 6.7.
- Do not mutate ACTIVE baselines.
- Do not assume Sofja paths exist locally unless explicitly used as reference strings.
- Keep changes small, testable, and auditable.
- False positives are more harmful than false negatives. When uncertain, quarantine, mark insufficient, or require verification rather than admitting broad evidence.
- Step 5p is guidance only. Step 5p may suggest search guidance, aliases, source-equivalent phrases, risk notes, or evidence-shape hints. Step 5p must not certify final evidence.
- Step 5x is responsible for source verification, evidence admission, and pack composition.
- Model-suggested or unverified profile guidance must not become positive evidence without source-local verification.
- Every curriculum KC expected by the run must survive into Step 5x pack output, even if only as a zero-candidate insufficient-support packet.

## Seedless runtime rule

Active runtime must use the seedless hierarchy registry:

`data/work/cache/current_step_artifacts/step1_seedless_hierarchy_registry.current.jsonl`

or the pointer:

`data/work/cache/current_step_artifacts/ACTIVE_SEEDLESS_KC_REGISTRY.txt`

Never use the old alias:

`data/work/cache/current_step_artifacts/step1_kc_registry.current.jsonl`

Forbidden seed fields in active runtime inputs:

- `seed_definition`
- `seed_keywords`
- `seed_floor`
- `seed_floor_fallback`
- `seed_definition_text`
- `seed_scope`

If active runtime input contains forbidden seed fields, fail fast unless an explicit diagnostic escape hatch is passed.

## Testing expectations

For code changes, run targeted tests and compile checks for changed Python files. Report exact commands and results.

## Compaction recovery expectation

At the end of a task, write a compact recovered-state summary covering files changed, tests run, behavior changed, unresolved risks, and exact next commands.
