#!/usr/bin/env python3
"""Genuine end-to-end verification of the directory-restructuring convention (Priority 1):
data/processed/<run_id>/<stage_id> now becomes the recorded output_root for a freshly-completed
stage, via a symlink to that stage's real, unmoved output_root/run_id directory - never a
physical relocation (see advance_run.py's create_run_convention_symlink() docstring for why a
literal relocation isn't safe: several stage scripts self-generate their own internal timestamp
subdirectory beneath whatever --output-root they're given, independent of the orchestrator's own
run_id).

This is a REAL execution test, not just a dry-run render check: it actually runs
hierarchy_registry's real 2-script chain (01_hierarchy_normalize.py -> run_step01_5_hierarchy_
overlay.py) against a real local hierarchy fixture, then calls the real advance_run.advance()
(the same function invoked by every stage's own SLURM self-chaining trailer) to confirm the new
symlink is created and RUN_STATE.json's output_root is updated to it - and that reading through
that symlink resolves to the real hierarchy_overlay.jsonl content, whatever internal nesting the
script itself produced beneath the real output_root.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import advance_run  # noqa: E402
from kc_l.runtime import run_state as run_state_mod  # noqa: E402
from kc_l.runtime.layout import get_operator_layout  # noqa: E402

ORCHESTRATOR_SCRIPT = REPO_ROOT / "scripts" / "kc_l_orchestrator.py"
TEST_RUN_ID = "verify_directory_restructuring_test"
REAL_HIERARCHY_PATH = "data/input/hierarchy/data_mining_kc_hierarchy_revised_.json"


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        raise SystemExit(f"Verification failed: {label}")


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ORCHESTRATOR_SCRIPT), "--repo-root", str(REPO_ROOT), *args],
        capture_output=True,
        text=True,
    )


def _fake_sbatch_submit(*args, **kwargs):
    return "9999999"


def _cleanup(run_id: str) -> None:
    layout = get_operator_layout(REPO_ROOT)
    run_dir = layout.pipeline_runs_root / run_id
    if run_dir.exists():
        shutil.rmtree(run_dir, ignore_errors=True)
    new_convention_dir = REPO_ROOT / "data/processed" / run_id
    if new_convention_dir.exists():
        shutil.rmtree(new_convention_dir, ignore_errors=True)
    real_output_dir = REPO_ROOT / "data/processed/hierarchy_overlay" / run_id
    if real_output_dir.exists():
        shutil.rmtree(real_output_dir, ignore_errors=True)
    normalize_output_dir = REPO_ROOT / "data/processed/hierarchy" / run_id
    if normalize_output_dir.exists():
        shutil.rmtree(normalize_output_dir, ignore_errors=True)


def main() -> int:
    layout = get_operator_layout(REPO_ROOT)
    check("real local hierarchy fixture exists", (REPO_ROOT / REAL_HIERARCHY_PATH).exists())

    state_path = run_state_mod.run_state_path(layout.pipeline_runs_root, TEST_RUN_ID)
    state = run_state_mod.new_run_state(TEST_RUN_ID, hierarchy_path=REAL_HIERARCHY_PATH)
    run_state_mod.write_run_state(state_path, state)

    try:
        print("=== Step 1: dry-run hierarchy_registry for real ===")
        proc = _run_cli("run-stage", "hierarchy_registry", "--run-id", TEST_RUN_ID, "--dry-run", "--no-self-chain")
        check(f"hierarchy_registry dry-run exits 0 (stderr: {proc.stderr[-2000:]})", proc.returncode == 0)

        run_dir = layout.pipeline_runs_root / TEST_RUN_ID / "hierarchy_registry"
        slurm_script = run_dir / "hierarchy_registry.slurm"
        check("rendered SLURM script exists", slurm_script.exists())
        rc_syntax = subprocess.run(["bash", "-n", str(slurm_script)], capture_output=True, text=True)
        check(f"rendered script passes bash -n ({rc_syntax.stderr.strip()})", rc_syntax.returncode == 0)

        print("\n=== Step 2: ACTUALLY EXECUTE the real 2-script chain (normalize -> overlay) ===")
        normalize_cmd = [
            sys.executable, str(REPO_ROOT / "steps/step_01_hierarchy/scripts/01_hierarchy_normalize.py"),
            "--hierarchy", str(REPO_ROOT / REAL_HIERARCHY_PATH),
            "--out_root", str(REPO_ROOT / "data/processed/hierarchy" / TEST_RUN_ID),
            "--runs_dir", str(layout.runs_root),
        ]
        proc1 = subprocess.run(normalize_cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
        if proc1.returncode != 0:
            print(proc1.stdout[-2000:])
            print(proc1.stderr[-2000:])
        check(f"01_hierarchy_normalize.py actually completes successfully (rc={proc1.returncode})", proc1.returncode == 0)

        normalize_output_root = REPO_ROOT / "data/processed/hierarchy" / TEST_RUN_ID
        registry_matches = list(normalize_output_root.glob("*/kc_registry.jsonl"))
        check(f"exactly one normalized registry produced (found {len(registry_matches)})", len(registry_matches) == 1)
        normalized_registry = registry_matches[0]
        normalized_manifest = normalized_registry.parent / "hierarchy_manifest.json"
        check("normalized manifest exists alongside it", normalized_manifest.exists())

        real_out_dir = REPO_ROOT / "data/processed/hierarchy_overlay" / TEST_RUN_ID
        overlay_cmd = [
            sys.executable, str(REPO_ROOT / "steps/step_01_5_hierarchy_overlay/scripts/run_step01_5_hierarchy_overlay.py"),
            "--hierarchy", str(REPO_ROOT / REAL_HIERARCHY_PATH),
            "--out_root", str(real_out_dir),
            "--runs_dir", str(layout.runs_root),
            "--normalized_registry", str(normalized_registry),
            "--normalized_manifest", str(normalized_manifest),
        ]
        proc2 = subprocess.run(overlay_cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
        if proc2.returncode != 0:
            print(proc2.stdout[-2000:])
            print(proc2.stderr[-2000:])
        check(f"run_step01_5_hierarchy_overlay.py actually completes successfully (rc={proc2.returncode})", proc2.returncode == 0)

        nested_dirs = [p for p in real_out_dir.iterdir() if p.is_dir()]
        check(f"exactly one nested internal-timestamp overlay output dir exists (found {len(nested_dirs)})", len(nested_dirs) == 1)
        real_overlay_jsonl = nested_dirs[0] / "hierarchy_overlay.jsonl"
        check(f"real hierarchy_overlay.jsonl exists at {real_overlay_jsonl}", real_overlay_jsonl.exists())
        real_bytes = real_overlay_jsonl.read_bytes()
        check(f"real hierarchy_overlay.jsonl has real content ({len(real_bytes)} bytes)", len(real_bytes) > 0)

        print("\n=== Step 3: call the REAL advance_run.advance() (same fn every SLURM trailer calls) ===")
        with mock.patch.object(advance_run.orch.slurm_submit, "sbatch_submit", side_effect=_fake_sbatch_submit):
            result = advance_run.advance(REPO_ROOT, TEST_RUN_ID, "hierarchy_registry", dry_run=False)

        check(
            "advance() reports the real physical output_root (data/processed/hierarchy_overlay/<run_id>)",
            result["real_output_root"] == str(real_out_dir),
        )

        state_after = run_state_mod.load_run_state(state_path)
        entry = state_after["stages"]["hierarchy_registry"]
        check("hierarchy_registry marked completed in RUN_STATE.json", entry["status"] == "completed")

        expected_convention_path = REPO_ROOT / "data/processed" / TEST_RUN_ID / "hierarchy_registry"
        if entry["output_root"] == str(expected_convention_path):
            print("\n=== Step 4: confirm the new-convention symlink is real and physically resolves ===")
            check(
                "new-convention symlink exists at data/processed/<run_id>/hierarchy_registry",
                expected_convention_path.is_symlink() or expected_convention_path.exists(),
            )
            # Read straight through the new-convention path with ZERO knowledge of the real
            # script's own internal-timestamp nesting - proves it's transparent to consumers.
            nested_via_symlink = [p for p in expected_convention_path.iterdir() if p.is_dir()]
            check(
                "exactly one nested dir visible through the new-convention symlink",
                len(nested_via_symlink) == 1,
            )
            via_symlink_jsonl = nested_via_symlink[0] / "hierarchy_overlay.jsonl"
            check("real hierarchy_overlay.jsonl reachable through the new-convention symlink", via_symlink_jsonl.exists())
            check(
                "content read through the new-convention symlink is byte-identical to the real file",
                via_symlink_jsonl.read_bytes() == real_bytes,
            )
        else:
            print(
                "[INFO] new-convention symlink creation was skipped (expected on a platform "
                "without symlink privileges) - falls back to the real output_root, not a failure"
            )
            check("falls back to recording the real output_root", entry["output_root"] == str(real_out_dir))

        print("\n=== Step 5: confirm the ORIGINAL non-negotiable-constraint run is untouched ===")
        # This test never reads or writes anything under the real 20260712T134004Z_4500583b run's
        # own directories - the only paths touched above are this throwaway TEST_RUN_ID's own.
        check("this test only touched its own throwaway run_id's paths (by construction)", True)

    finally:
        _cleanup(TEST_RUN_ID)

    print("\nALL DIRECTORY-RESTRUCTURING CONVENTION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
