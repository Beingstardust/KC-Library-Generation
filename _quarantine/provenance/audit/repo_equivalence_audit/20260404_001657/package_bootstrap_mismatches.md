# Package Bootstrap Mismatches

## 1. Default install semantics changed

Old repo:
- `pyproject.toml:11-13`
  - base project dependencies included `orjson` and `rich`
- `requirements.txt`
  - installed those same package-level dependencies plus dev tools

Clean repo:
- `pyproject.toml:11-12`
  - base project dependency is only `PyYAML`
- `pyproject.toml:15-25`
  - the fuller pipeline stack moved into the optional `runtime` extra
- `requirements.txt:2`
  - now installs only `requirements-operator.txt`
- `requirements-runtime.txt:2-26`
  - is now the file that brings in `orjson`, `rich`, `torch`, `transformers`, `sentence-transformers`, `huggingface-hub`, and notes the external CLI dependencies

Impact:
- `pip install -r requirements.txt` in CLEAN_REPO no longer produces a full retained-pipeline environment.
- `pip install -e .` in CLEAN_REPO no longer gives the old default dependency set unless the `runtime` extra is explicitly requested.

## 2. Public scripts and internal step scripts now have different import bootstrap assumptions

Public clean scripts:
- `scripts/local/run_stage.py:10-12`
- `scripts/hpc/render_main_quest_config.py:10-12`
- `scripts/maintenance/check_operator_repo.py:9-11`
- These scripts manually add `src` to `sys.path`.

Retained internal step scripts:
- Example: `steps/step_01_hierarchy/scripts/01_hierarchy_normalize.py:11-19`
- It imports `kc_l.*` directly and does not inject `src` into `sys.path`.

Impact:
- The public operator shell works in a repo checkout without an editable install.
- The retained low-level steps still assume either editable install or `PYTHONPATH=src`.
- This split can make the clean repo appear more bootstrap-ready than the real full pipeline is.

## 3. Package behavior changed at the default knowledge-library import surface

Old repo behavior:
- `PYTHONPATH=src python -c "from kc_l.knowledge_library import load_release; ..."` succeeded and resolved `knowledge_library_pilot_release:2026-04-01_181217`

Clean repo behavior:
- The same command fails with:
  - `FileNotFoundError: No active frozen Knowledge Library release is set. Freeze a library first, then update data/library/active/knowledge_library_release_pointer.json.`

Source evidence:
- Old `src/kc_l/knowledge_library/access.py:14-15`
  - default pointer is `CURRENT_KNOWLEDGE_LIBRARY_PILOT_RELEASE.md`
- Clean `src/kc_l/knowledge_library/access.py:10-17`
  - default pointer comes from `kc_l.runtime.library_state`
- Clean `src/kc_l/runtime/library_state.py:31-34`
  - default pointer payload uses `state = "none"`

Impact:
- This is an intentional semantic change for the clean operator repo.
- It is not package/import-equivalent with the old repo.

## 4. The clean repo's default bootstrap is operator-light, not full-pipeline-equivalent

Why this matters:
- The new public scripts can succeed with `PyYAML` and local `sys.path` injection.
- The retained step tree still depends on the heavier runtime stack and the old path contracts.
- Therefore the clean repo preserved installability for the operator shell, but it did not preserve default bootstrap continuity for the old full pipeline.

Audit judgment:
- Packaging metadata is not broken.
- Bootstrap continuity is changed in a materially non-equivalent way.
