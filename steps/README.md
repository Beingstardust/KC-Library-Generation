# Internal Legacy Steps

The `steps/` tree is retained because it still contains real low-level pipeline logic and provenance.

It is not the public operator shell, but it is still the real downstream execution lane.

Use the public shell for readiness and discoverability:

- `python scripts/local/run_stage.py list`
- `python scripts/local/run_stage.py status --json`
- `python scripts/local/run_stage.py intake --json`
- `python scripts/maintenance/check_operator_repo.py`
- `python scripts/hpc/render_main_quest_config.py --mode hpc_gpu`

Use the public intake bridge for first-run corpus intake from the clean input layout:

- `python scripts/local/run_corpus_intake.py`

Keep these preserved legacy execution surfaces in view for downstream and late-stage work:

- `PROJECT_STATE/MAIN_QUEST_EXECUTION_AUTHORIZATION.md`
- `PROJECT_STATE/MAIN_QUEST_ENTRY_CONTRACT.md`
- `PROJECT_STATE/MAIN_QUEST_PREFLIGHT_RECIPE.md`
- `PROJECT_STATE/KC_SEMANTIC_GATING_POLICY_FROM_SIDEQUEST.md`
- `run_step6_7_model_draft_generation.py`
- root `step6_6_*.yaml`
- root `step6_7_*.yaml`
- root `step6_8_*.yaml`

Late-stage Step 5 and Step 6 shipped current/default resource YAMLs now resolve stable alias files
under `data/work/cache/current_step_artifacts/`.
Refresh those aliases with `python scripts/maintenance/refresh_current_step_artifacts.py` after
Step 1, Step 1.5, Step 6.6, or Step 6.7 produces new artifacts.
If the required current artifacts do not exist yet, the refresh script and the downstream Step 5 or
Step 6 run will fail explicitly with the missing current path.
The repaired PowerShell intake wrappers remain available as legacy Windows helpers, but the public
operator shell does not replace the retained execution ladder inside `steps/`.



