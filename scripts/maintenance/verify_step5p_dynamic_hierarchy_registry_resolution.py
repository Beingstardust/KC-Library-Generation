#!/usr/bin/env python3
"""Proves step_05p's hierarchy_registry-side resolution is genuinely dynamic (registry_jsonl
changes correctly between two different real hierarchy outputs, never a hardcoded default).

The step_04_5 side of this fixture used to be a flat historical directory
(STEP45_OUTPUT_ROOT/sentence_corpus.jsonl directly) - that assumption is now confirmed WRONG
(see ORCHESTRATOR_BUILD_STATE.md's "step_05p final flip-and-verify pass" / the follow-up fix
commit): the real run_step4_5.py never writes a flat file, and
resolve_sentence_overlay_jsonl_from_output_root() was fixed to read the stage's own
ACTIVE_STEP4_5_SET.txt pointer + set manifest instead. This script's step_04_5 stand-in is
updated to match that real contract: a small STAGING directory (not a mutation of the real
historical archive) containing a real-shaped ACTIVE_STEP4_5_SET.txt pointer + set manifest whose
own artifacts.sentence_corpus_jsonl field references the real historical sentence_corpus.jsonl
file directly - genuinely exercising the fixed resolution path, not bypassing it.

verify_step05p_step05x_full_chain_dry_run.py separately covers the FULLY real, freshly-produced
end-to-end case (real step_04_3 -> real run_step4_5.py execution -> real nested output). This
script's own remaining value is the two-different-hierarchy-outputs check below, which that
script does not repeat.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from kc_l.runtime import run_state as run_state_mod
from kc_l.runtime.layout import get_operator_layout
import kc_l.runtime.stage_registry as stage_registry_mod

ORCHESTRATOR_SCRIPT = REPO_ROOT / "scripts" / "kc_l_orchestrator.py"
STAGE_ID = "step_05p_kc_retrieval_profiles"

# Verification-only historical stand-ins for "current run chain" upstream outputs. These are
# not defaults and are intentionally kept local to this verifier.
REAL_SENTENCE_CORPUS_JSONL = (
    REPO_ROOT
    / "_archive/repo_cleanup_candidates/local_audits/"
    / "package_complete_raw_5p5x_assessment_bundle_20260516T134659Z/stage/files/0016_sentence_overlay_jsonl"
    / "sentence_corpus.jsonl"
)
# Writable staging dir (never mutates the real historical archive above) shaped like a real
# step_04_5 output: _sets/ACTIVE_STEP4_5_SET.txt -> a set manifest whose own
# artifacts.sentence_corpus_jsonl field points at the real historical file - genuinely
# exercising resolve_sentence_overlay_jsonl_from_output_root()'s real (fixed) pointer-based
# resolution, not a flat-file shortcut.
STEP45_OUTPUT_ROOT = REPO_ROOT / "data/processed/_verify_step5p_hierarchy_resolution_step45_stand_in"
HIERARCHY_OUTPUT_ROOT_A = REPO_ROOT / "data/processed/hierarchy_overlay/2026-04-08_103432_hierarchy_overlay"
HIERARCHY_OUTPUT_ROOT_B = REPO_ROOT / "data/processed/hierarchy_overlay/2026-04-24_203905_hierarchy_overlay"


def _build_step45_stand_in() -> None:
    if STEP45_OUTPUT_ROOT.exists():
        shutil.rmtree(STEP45_OUTPUT_ROOT)
    sets_dir = STEP45_OUTPUT_ROOT / "_sets"
    sets_dir.mkdir(parents=True, exist_ok=True)
    set_manifest_path = sets_dir / "verify_stand_in_step4_5_sentence_set.json"
    set_manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "kind": "step4_5_sentence_overlay_set",
                "set_id": set_manifest_path.stem,
                "artifacts": {
                    "sentence_corpus_jsonl": str(REAL_SENTENCE_CORPUS_JSONL.relative_to(REPO_ROOT)).replace("\\", "/"),
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (sets_dir / "ACTIVE_STEP4_5_SET.txt").write_text(set_manifest_path.name + "\n", encoding="utf-8")


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        raise SystemExit(f"Verification failed: {label}")


def _cleanup_run_id(run_id: str) -> None:
    layout = get_operator_layout(REPO_ROOT)
    run_dir = layout.pipeline_runs_root / run_id
    if run_dir.exists():
        shutil.rmtree(run_dir)


def _load_orchestrator_module():
    spec = importlib.util.spec_from_file_location("kc_l_orchestrator_step5p_verify", ORCHESTRATOR_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _seed_run_state(*, run_id: str, hierarchy_output_root: Path) -> None:
    layout = get_operator_layout(REPO_ROOT)
    state_path = run_state_mod.run_state_path(layout.pipeline_runs_root, run_id)
    state = run_state_mod.new_run_state(run_id)
    run_state_mod.set_stage_completed(
        state,
        "step_04_5_sentence_overlay",
        output_root=str(STEP45_OUTPUT_ROOT),
        set_manifest_path=None,
        run_folder_symlink=None,
    )
    run_state_mod.set_stage_completed(
        state,
        "hierarchy_registry",
        output_root=str(hierarchy_output_root),
        set_manifest_path=None,
        run_folder_symlink=None,
    )
    run_state_mod.write_run_state(state_path, state)


def _dry_run_and_read_config(*, mod, run_id: str, hierarchy_output_root: Path) -> dict[str, object]:
    _cleanup_run_id(run_id)
    _seed_run_state(run_id=run_id, hierarchy_output_root=hierarchy_output_root)

    args = mod.argparse.Namespace(
        repo_root=str(REPO_ROOT),
        stage_id=STAGE_ID,
        run_id=run_id,
        dry_run=True,
        dependency_job_id=None,
    )
    rc = mod.run_stage(args)
    check(f"{run_id}: run_stage() dry-run exits 0", rc == 0)

    run_dir = get_operator_layout(REPO_ROOT).pipeline_runs_root / run_id / STAGE_ID
    rendered_config_path = run_dir / f"{run_id}_step_05p_config.json"
    check(f"{run_id}: rendered config exists", rendered_config_path.exists())
    return json.loads(rendered_config_path.read_text(encoding="utf-8"))


def main() -> int:
    check("real historical sentence_corpus.jsonl fixture exists", REAL_SENTENCE_CORPUS_JSONL.exists())
    for path in (HIERARCHY_OUTPUT_ROOT_A, HIERARCHY_OUTPUT_ROOT_B):
        check(f"fixture exists: {path}", path.exists())

    _build_step45_stand_in()

    original_spec = stage_registry_mod.STAGE_SPECS[STAGE_ID]
    stage_registry_mod.STAGE_SPECS[STAGE_ID] = replace(original_spec, run_stage_wired=True)
    try:
        mod = _load_orchestrator_module()
        cfg_a = _dry_run_and_read_config(
            mod=mod,
            run_id="verify_step05p_hierarchy_overlay_a",
            hierarchy_output_root=HIERARCHY_OUTPUT_ROOT_A,
        )
        cfg_b = _dry_run_and_read_config(
            mod=mod,
            run_id="verify_step05p_hierarchy_overlay_b",
            hierarchy_output_root=HIERARCHY_OUTPUT_ROOT_B,
        )
    finally:
        stage_registry_mod.STAGE_SPECS[STAGE_ID] = original_spec

    registry_a = str((cfg_a.get("inputs") or {}).get("registry_jsonl") or "")
    registry_b = str((cfg_b.get("inputs") or {}).get("registry_jsonl") or "")
    source_overlay_a = str((cfg_a.get("inputs") or {}).get("source_overlay_jsonl") or "")
    source_overlay_b = str((cfg_b.get("inputs") or {}).get("source_overlay_jsonl") or "")

    expected_registry_a = str(HIERARCHY_OUTPUT_ROOT_A / "hierarchy_overlay.jsonl")
    expected_registry_b = str(HIERARCHY_OUTPUT_ROOT_B / "hierarchy_overlay.jsonl")
    expected_source_overlay = str(REAL_SENTENCE_CORPUS_JSONL)

    check("run A picked hierarchy output A", registry_a == expected_registry_a)
    check("run B picked hierarchy output B", registry_b == expected_registry_b)
    check("registry_jsonl differs across the two dry-runs", registry_a != registry_b)
    check("run A kept the expected sentence overlay path", source_overlay_a == expected_source_overlay)
    check("run B kept the expected sentence overlay path", source_overlay_b == expected_source_overlay)

    print(f"RUN_A_REGISTRY_JSONL={registry_a}")
    print(f"RUN_B_REGISTRY_JSONL={registry_b}")
    print(f"SOURCE_OVERLAY_JSONL={expected_source_overlay}")
    print("VERIFICATION_NOTE=historical hierarchy outputs used here are verification-only stand-ins for current-run upstream outputs")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        _cleanup_run_id("verify_step05p_hierarchy_overlay_a")
        _cleanup_run_id("verify_step05p_hierarchy_overlay_b")
        if STEP45_OUTPUT_ROOT.exists():
            shutil.rmtree(STEP45_OUTPUT_ROOT)
