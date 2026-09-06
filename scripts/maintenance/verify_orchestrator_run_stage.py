#!/usr/bin/env python3
"""Verify scripts/kc_l_orchestrator.py's run-stage and plan commands.

Covers:
- step_06_7_postprocessed_review_source and step_06_8_review_packet_emission dry-run via the
  real CLI (subprocess), with a throwaway RUN_STATE.json simulating a completed predecessor -
  these two don't depend on BEST-pointer cross-host resolution.
- step_06_6_drafting_input_overlay via direct in-process call with
  build_step6_6_run_config monkeypatched (its own pointer-resolution logic is already fully
  verified separately in verify_step6_6_evidence_bridge.py against local fixtures; this only
  proves the orchestrator wires its result into a real SLURM script correctly).
- run-stage refuses cleanly (does not guess) for a stage marked run_stage_wired=False, and for
  an unconfirmed stage.
- plan --dry-run resolves the right stage_id range without submitting anything.

Uses a throwaway run_id under the REAL repo's data/processed/runs/ (cleaned up at the end),
since --repo-root must point at a real checkout for script_path/base_config_path resolution.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from kc_l.runtime import run_state as run_state_mod
from kc_l.runtime.layout import get_operator_layout

ORCHESTRATOR_SCRIPT = REPO_ROOT / "scripts" / "kc_l_orchestrator.py"
TEST_RUN_ID = "verify_orchestrator_run_stage_test"


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        raise SystemExit(f"Verification failed: {label}")


def _cleanup_test_run() -> None:
    layout = get_operator_layout(REPO_ROOT)
    test_run_dir = layout.pipeline_runs_root / TEST_RUN_ID
    if test_run_dir.exists():
        shutil.rmtree(test_run_dir)


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ORCHESTRATOR_SCRIPT), "--repo-root", str(REPO_ROOT), *args],
        capture_output=True,
        text=True,
    )


def verify_step_06_6_via_direct_call() -> None:
    print("\n=== step_06_6_drafting_input_overlay (direct call, pointer-resolution stubbed) ===")
    spec = importlib.util.spec_from_file_location("kc_l_orchestrator_test", ORCHESTRATOR_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    def _fake_build_step6_6_run_config(*, run_id, repo_root, run_dir, step5_3_active_set_pointer=None):
        run_dir.mkdir(parents=True, exist_ok=True)
        fake_config = run_dir / f"{run_id}_step6_6_config.json"
        fake_config.write_text(json.dumps({"stub": True}), encoding="utf-8")
        return fake_config, ["--step6-input-assembly-manifest", str(run_dir / "stub_manifest.json")]

    mod.build_step6_6_run_config = _fake_build_step6_6_run_config

    layout = get_operator_layout(REPO_ROOT)
    run_dir = layout.pipeline_runs_root / TEST_RUN_ID / "step_06_6_drafting_input_overlay"

    # step_06_6_drafting_input_overlay now also depends on step_05_3_evidence_recalibrated
    # (2026-07-16 fix) - fake-complete it so _resolve_upstream_output_root() doesn't refuse
    # before ever reaching the monkeypatched build_step6_6_run_config() stub above, which is
    # what this test is actually about (SLURM rendering, not upstream resolution).
    state_path = run_state_mod.run_state_path(layout.pipeline_runs_root, TEST_RUN_ID)
    state = run_state_mod.new_run_state(TEST_RUN_ID)
    run_state_mod.set_stage_completed(
        state, "step_05_3_evidence_recalibrated",
        output_root=str(REPO_ROOT / "data/processed/kc_evidence_recalibrated" / TEST_RUN_ID),
        set_manifest_path=None, run_folder_symlink=None,
    )
    run_state_mod.write_run_state(state_path, state)

    args = mod.argparse.Namespace(
        repo_root=str(REPO_ROOT),
        stage_id="step_06_6_drafting_input_overlay",
        run_id=TEST_RUN_ID,
        dry_run=True,
        dependency_job_id=None,
    )
    rc = mod.run_stage(args)
    check("run_stage() returns 0 for step_06_6 dry-run", rc == 0)
    slurm_script = run_dir / "step_06_6_drafting_input_overlay.slurm"
    check("SLURM script was rendered to disk", slurm_script.exists())
    text = slurm_script.read_text(encoding="utf-8")
    check("rendered script references the stubbed config path", str(run_dir) in text)
    check("rendered script includes --step6-input-assembly-manifest", "--step6-input-assembly-manifest" in text)
    check("rendered script sets the correct LD_LIBRARY_PATH", "/path/to/software/python/python-3.11.3/lib" in text)
    proc = subprocess.run(["bash", "-n", str(slurm_script)], capture_output=True, text=True)
    check(f"rendered script passes bash -n ({proc.stderr.strip()})", proc.returncode == 0)


def verify_cli_arg_stages_via_real_cli() -> None:
    print("\n=== step_06_7_postprocessed_review_source / step_06_8_review_packet_emission (real CLI) ===")
    layout = get_operator_layout(REPO_ROOT)
    state_path = run_state_mod.run_state_path(layout.pipeline_runs_root, TEST_RUN_ID)

    state = run_state_mod.new_run_state(TEST_RUN_ID)
    run_state_mod.set_stage_completed(
        state,
        "step_06_7_kc_draft_generation",
        output_root=str(
            REPO_ROOT
            / "data/processed/step67_v2_tiny_smoke_drafts/step67_v2_full165_kc_topic_policy_marker_fix_20260520T195051Z"
        ),
        set_manifest_path=None,
        run_folder_symlink=None,
    )
    run_state_mod.write_run_state(state_path, state)

    proc = _run_cli("run-stage", "step_06_7_postprocessed_review_source", "--run-id", TEST_RUN_ID, "--dry-run")
    check(f"step_06_7_postprocessed_review_source dry-run exits 0 (stderr: {proc.stderr[-500:]})", proc.returncode == 0)
    check("references the predecessor's real drafts.jsonl", "step67_v2_tiny_smoke_drafts.jsonl" in proc.stdout)
    check("rendered script sets the correct LD_LIBRARY_PATH", "/path/to/software/python/python-3.11.3/lib" in proc.stdout)

    # Now mark step_06_7_postprocessed_review_source itself completed, so step_06_8 can resolve it.
    state = run_state_mod.load_run_state(state_path)
    run_state_mod.set_stage_completed(
        state,
        "step_06_7_postprocessed_review_source",
        output_root=str(REPO_ROOT / "data/processed/step67_v2_postprocessed_review_source/20260520T233415Z"),
        set_manifest_path=None,
        run_folder_symlink=None,
    )
    run_state_mod.write_run_state(state_path, state)

    proc = _run_cli("run-stage", "step_06_8_review_packet_emission", "--run-id", TEST_RUN_ID, "--dry-run")
    check(f"step_06_8_review_packet_emission dry-run exits 0 (stderr: {proc.stderr[-500:]})", proc.returncode == 0)
    check("references the predecessor's real postprocessed jsonl", "step67_v2_postprocessed_review_source.jsonl" in proc.stdout)

    # Without a completed predecessor recorded, step_06_8 must refuse, not guess.
    fresh_run_id = TEST_RUN_ID + "_no_predecessor"
    proc = _run_cli("run-stage", "step_06_8_review_packet_emission", "--run-id", fresh_run_id, "--dry-run")
    check("step_06_8 refuses cleanly when its predecessor has not completed", proc.returncode == 3)
    check("refusal message names the missing upstream stage", "step_06_7_postprocessed_review_source" in proc.stdout)
    _cleanup_run_id(fresh_run_id)


def verify_refusals() -> None:
    print("\n=== refusal behavior for not-wired / unconfirmed stages ===")
    proc = _run_cli("run-stage", "step_06_7_kc_draft_generation", "--run-id", TEST_RUN_ID + "_refuse1", "--dry-run")
    check("step_06_7_kc_draft_generation (not wired) refuses rather than guesses", proc.returncode == 3)
    check("refusal is the STAGE_NOT_WIRED error, not a crash", "ERROR_STAGE_NOT_WIRED" in proc.stdout)
    _cleanup_run_id(TEST_RUN_ID + "_refuse1")

    proc = _run_cli("run-stage", "downstream_segmentation_evaluation", "--run-id", TEST_RUN_ID + "_refuse2", "--dry-run")
    check("downstream_segmentation_evaluation (unconfirmed mapping) refuses", proc.returncode == 2)
    check("refusal is the STAGE_NOT_CONFIRMED error", "ERROR_STAGE_NOT_CONFIRMED" in proc.stdout)
    _cleanup_run_id(TEST_RUN_ID + "_refuse2")

    proc = _run_cli("run-stage", "not_a_real_stage_id", "--run-id", TEST_RUN_ID + "_refuse3", "--dry-run")
    check("unknown stage_id refuses cleanly", proc.returncode == 2)
    check("refusal names it as an unknown stage", "ERROR_UNKNOWN_STAGE_ID" in proc.stdout)
    _cleanup_run_id(TEST_RUN_ID + "_refuse3")


def _cleanup_run_id(run_id: str) -> None:
    layout = get_operator_layout(REPO_ROOT)
    run_dir = layout.pipeline_runs_root / run_id
    if run_dir.exists():
        shutil.rmtree(run_dir)


def verify_plan_dry_run() -> None:
    print("\n=== plan --dry-run ===")
    proc = _run_cli(
        "plan",
        "--from", "step_06_7_postprocessed_review_source",
        "--to", "step_06_8_review_packet_emission",
        "--run-id", TEST_RUN_ID + "_plan",
        "--dry-run",
    )
    check(f"plan --dry-run exits 0 (stderr: {proc.stderr[-500:]})", proc.returncode == 0)
    check("plan lists exactly 2 stages", "STAGE_COUNT=2" in proc.stdout)
    check("plan includes step_06_7_postprocessed_review_source", "step_06_7_postprocessed_review_source" in proc.stdout)
    check("plan includes step_06_8_review_packet_emission", "step_06_8_review_packet_emission" in proc.stdout)
    check("plan --dry-run does not submit anything", "JOB_ID=" not in proc.stdout)
    _cleanup_run_id(TEST_RUN_ID + "_plan")


def main() -> int:
    try:
        verify_step_06_6_via_direct_call()
        verify_cli_arg_stages_via_real_cli()
        verify_refusals()
        verify_plan_dry_run()
    finally:
        _cleanup_test_run()

    print("\nALL ORCHESTRATOR RUN-STAGE/PLAN CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
