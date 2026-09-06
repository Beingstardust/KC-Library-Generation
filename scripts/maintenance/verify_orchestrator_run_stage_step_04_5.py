#!/usr/bin/env python3
"""Verify scripts/kc_l_orchestrator.py's run-stage wiring for step_04_5_sentence_overlay.

Covers:
- inputs.step4_active_set_pointer AND inputs.active_step4_set are BOTH set to the current run's
  real step_04_3 output (step4_5.default.yaml sets step4_active_set_pointer, which main()'s own
  lookup checks FIRST - confirmed the hard way while fixing/verifying the two runner bugs this
  stage's wiring depends on; overriding only one key would silently be shadowed).
- inputs.active_step4_5_set_pointer and outputs.processed_root/sets_dir are run-id-scoped.
- rendered SLURM script references the rendered config, bash -n passes.
- refuses cleanly when step_04_3_embedding_index has not completed.

Reuses the same real historical Step 4.3 manifest (localized to this Windows checkout's real
mirror paths) as verify_step4_5_bugfix_functional.py, seeded at the exact per-run location
_prepare_stage_invocation() expects a completed step_04_3's output to live.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from kc_l.runtime import run_state as run_state_mod
from kc_l.runtime.layout import get_operator_layout

ORCHESTRATOR_SCRIPT = REPO_ROOT / "scripts" / "kc_l_orchestrator.py"
TEST_RUN_ID = "verify_step_04_5_test"

REAL_MANIFEST_MIRROR_ROOT = REPO_ROOT / (
    "_archive/repo_cleanup_candidates/local_audits/"
    "package_raw_complete_5p_5x_66_67_lineage_20260520T230942Z/stage/_absolute/"
    "path/to/scratch/kc_l"
)
REAL_MANIFEST_PATH = (
    REAL_MANIFEST_MIRROR_ROOT
    / "data/processed/retrieval_index/_sets/2026-04-07_000855_step4_3_1_step4_index_set.json"
)
REAL_SCRATCH_PREFIX = "/path/to/scratch/kc_l/"


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


def _cleanup_run_id(run_id: str) -> None:
    layout = get_operator_layout(REPO_ROOT)
    run_dir = layout.pipeline_runs_root / run_id
    if run_dir.exists():
        shutil.rmtree(run_dir)


def _bash_n(path: Path) -> None:
    if shutil.which("bash") is None:
        print(f"[SKIP] {path.name} bash -n skipped: bash is not installed on this Windows machine")
        return
    proc = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
    check(f"{path.name} passes bash -n ({proc.stderr.strip()})", proc.returncode == 0)


def _seed_step_04_3_output(run_id: str) -> Path:
    check("real historical step4.3 manifest exists", REAL_MANIFEST_PATH.exists())
    step4_3_output_root = REPO_ROOT / "data/processed/retrieval_index" / run_id
    sets_dir = step4_3_output_root / "_sets"
    sets_dir.mkdir(parents=True, exist_ok=True)

    raw_text = REAL_MANIFEST_PATH.read_text(encoding="utf-8")
    local_prefix = REAL_MANIFEST_MIRROR_ROOT.as_posix() + "/"
    localized_text = raw_text.replace(REAL_SCRATCH_PREFIX, local_prefix)
    manifest_path = sets_dir / "2026-04-07_000855_step4_3_1_step4_index_set.json"
    manifest_path.write_text(localized_text, encoding="utf-8")
    (sets_dir / "ACTIVE_STEP4_SET.txt").write_text(manifest_path.name, encoding="utf-8")

    layout = get_operator_layout(REPO_ROOT)
    state_path = run_state_mod.run_state_path(layout.pipeline_runs_root, run_id)
    state = run_state_mod.new_run_state(run_id)
    run_state_mod.set_stage_completed(
        state, "step_04_3_embedding_index",
        output_root=str(step4_3_output_root), set_manifest_path=str(manifest_path), run_folder_symlink=None,
    )
    run_state_mod.write_run_state(state_path, state)
    return step4_3_output_root


def main() -> int:
    try:
        step4_3_output_root = _seed_step_04_3_output(TEST_RUN_ID)
        expected_active_step4_set = str(step4_3_output_root / "_sets" / "ACTIVE_STEP4_SET.txt")

        proc = _run_cli("run-stage", "step_04_5_sentence_overlay", "--run-id", TEST_RUN_ID, "--dry-run")
        check(f"step_04_5 dry-run exits 0 (stderr: {proc.stderr[-2000:]})", proc.returncode == 0)

        layout = get_operator_layout(REPO_ROOT)
        run_dir = layout.pipeline_runs_root / TEST_RUN_ID / "step_04_5_sentence_overlay"
        rendered_config_path = run_dir / f"{TEST_RUN_ID}_step_04_5_config.json"
        check("rendered config exists", rendered_config_path.exists())
        rendered_config = json.loads(rendered_config_path.read_text(encoding="utf-8"))

        check(
            "rendered config's step4_active_set_pointer references the real current-run step_04_3 output",
            rendered_config["inputs"]["step4_active_set_pointer"] == expected_active_step4_set,
        )
        check(
            "rendered config's active_step4_set ALSO references it (both keys overridden, not just one)",
            rendered_config["inputs"]["active_step4_set"] == expected_active_step4_set,
        )
        check(
            "rendered config's active_step4_5_set_pointer is run-id-scoped",
            f"/{TEST_RUN_ID}/" in rendered_config["inputs"]["active_step4_5_set_pointer"].replace("\\", "/"),
        )
        check(
            "rendered config's outputs.processed_root is run-id-scoped",
            rendered_config["outputs"]["processed_root"]
            == str(REPO_ROOT / "data/processed/retrieval_sentence_overlay" / TEST_RUN_ID),
        )

        script_path = run_dir / "step_04_5_sentence_overlay.slurm"
        check("SLURM script rendered", script_path.exists())
        text = script_path.read_text(encoding="utf-8")
        check("SLURM script references the rendered config", str(rendered_config_path) in text)
        check("rendered script sets the correct LD_LIBRARY_PATH", "/path/to/software/python/python-3.11.3/lib" in text)
        _bash_n(script_path)

        fresh_run_id = TEST_RUN_ID + "_no_predecessor"
        proc2 = _run_cli("run-stage", "step_04_5_sentence_overlay", "--run-id", fresh_run_id, "--dry-run")
        check("refuses cleanly when step_04_3 has not completed", proc2.returncode == 3)
        check("refusal names the STAGE_NOT_WIRED error", "ERROR_STAGE_NOT_WIRED" in proc2.stdout)
        _cleanup_run_id(fresh_run_id)

    finally:
        _cleanup_run_id(TEST_RUN_ID)

    print("\nALL step_04_5_sentence_overlay RUN-STAGE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
