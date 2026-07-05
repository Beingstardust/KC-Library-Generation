# Repair Note: Bootstrap Continuity

Date: 2026-04-05
Scope: local-only packaging/bootstrap continuity repair in `R:\Thesis Project\KC_L v2 - Cleaner`

## Recovered State Summary

The April 4 audit found that the clean repo had split bootstrap semantics in a materially misleading
way:

- the old repo exposed one root `requirements.txt` that matched its default heavier package story
- the clean repo changed `requirements.txt` into an operator-light convenience install
- the preserved low-level step tree still assumed editable install or `PYTHONPATH=src`
- the public operator scripts worked anyway because they inject `src` manually

That meant the clean repo could look install-ready while the retained step tree was still missing an
honest default bootstrap path.

This pass repaired that continuity narrowly:

- `requirements.txt` is once again the default full retained-pipeline bootstrap surface
- the runtime requirement files now install `kc_l` editably so preserved step runners can import
  `kc_l.*` without undocumented `PYTHONPATH` workarounds
- the operator-light requirement file remains available, but is now explicitly secondary
- the editable package baseline in `pyproject.toml` once again includes `orjson` and `rich`, which
  were part of the old repo's default package dependency surface

## Files Changed

Packaging / bootstrap files:
- `pyproject.toml`
- `requirements.txt`
- `requirements-runtime.txt`
- `requirements-runtime-notorch.txt`
- `requirements-operator.txt`

Minimal directly affected docs / audit trail:
- `README.md`
- `CHANGELOG.md`

## Exact Bootstrap Semantics Repaired

Old repo baseline:
- `requirements.txt` was the only root requirements file
- `pyproject.toml` base dependencies included `orjson` and `rich`
- the preserved step tree assumed an environment where `kc_l` imports were already available

Clean repo before this pass:
- `requirements.txt` only installed `requirements-operator.txt`
- `requirements-runtime.txt` carried the heavier stack, but it did not install `kc_l` editably
- `pip install -r requirements.txt` therefore prepared the operator shell more than the retained
  step tree

Clean repo after this pass:
- `requirements.txt`
  - now points to `requirements-runtime.txt`
  - now means full retained-pipeline bootstrap by default
- `requirements-runtime.txt`
  - now installs `-e .[runtime]`
  - keeps the external non-Python runtime caveats explicit
- `requirements-runtime-notorch.txt`
  - now installs `-e .`
  - remains the variant for hosts where torch is being managed separately
- `requirements-operator.txt`
  - remains available, but is explicitly labeled as operator-shell-only convenience
- `pyproject.toml`
  - base dependencies again include `orjson` and `rich`
  - runtime-heavy packages remain in the `runtime` extra

## Before / After Install Behavior Summary

Before this pass:
- `pip install -r requirements.txt`
  - installed only the operator-light dependency surface
- `pip install -e .`
  - installed only `PyYAML`
- the retained step tree still needed either manual editable install choices or `PYTHONPATH=src`
  knowledge that the repo did not surface honestly

After this pass:
- `pip install -r requirements.txt`
  - is the default full retained-pipeline bootstrap path again
- `pip install -e .[runtime]`
  - is the explicit editable equivalent for the preserved full pipeline
- `pip install -r requirements-operator.txt`
  - remains the operator-shell-only convenience path
- `pip install -e .`
  - now restores the old-compatible base package surface (`PyYAML`, `orjson`, `rich`) but is still
    not the full retained-pipeline bootstrap unless the runtime extra is also installed

## Validation Performed

Validated in this pass:
- `python -c "import pathlib, tomllib; tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8'))"`
- `python scripts/local/run_stage.py --json list`
  - still succeeds after the packaging/doc changes

No package download/install was executed in this pass.
The repair is file-grounded and documentation-grounded, not a full environment rebuild.

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

Expose the repaired bootstrap distinction through a small operator-shell status surface so the repo
can report whether the current interpreter looks like an operator-only environment or a full
retained-pipeline environment without changing any preserved runner logic.
