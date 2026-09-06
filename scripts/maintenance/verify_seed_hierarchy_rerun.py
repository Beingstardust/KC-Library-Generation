#!/usr/bin/env python3
"""Genuine verification of scripts/seed_hierarchy_rerun.py (Priority 2: rerun only
hierarchy-dependent stages against a new hierarchy input, reusing a source run's already-
completed hierarchy-independent stages by reference, never by copy).

Covers:
- Seeding a fresh run_id from a fake-but-real source run (7 hierarchy-independent stages marked
  completed with real, existing marker-file output directories) correctly marks all 7 stages
  completed in the NEW run's RUN_STATE.json, referencing the SOURCE's real output (via the
  directory-restructuring convention symlink where creation succeeds).
- The source run's own RUN_STATE.json is byte-for-byte unchanged after seeding (read-only
  guarantee - the core non-negotiable safety property here).
- hierarchy_registry then correctly refuses (via the SAME existing validation, not a new one)
  when given a dummy/nonexistent hierarchy path, proving the seeded early-stage entries don't
  interfere with reaching that stage's own real validation cleanly.
- hierarchy_registry's dry-run render succeeds against a REAL local hierarchy fixture on this
  freshly-seeded run, proving the seeded state is genuinely launch-ready - without executing
  the real chain (no new hierarchy file exists yet for Priority 3, per the task brief).
- Refuses cleanly if the new run_id already exists, or if the source run hasn't completed all 7
  hierarchy-independent stages.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import seed_hierarchy_rerun as seeder  # noqa: E402
from kc_l.runtime import run_state as run_state_mod  # noqa: E402
from kc_l.runtime.layout import get_operator_layout  # noqa: E402

ORCHESTRATOR_SCRIPT = REPO_ROOT / "scripts" / "kc_l_orchestrator.py"
SOURCE_RUN_ID = "verify_seed_hierarchy_rerun_source"
NEW_RUN_ID = "verify_seed_hierarchy_rerun_new"
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


def _fake_stage_output_dirs() -> dict[str, Path]:
    mapping = {
        "step_02_pdf_ingest": REPO_ROOT / "data/processed/blockstore" / SOURCE_RUN_ID,
        "step_03_doctree_index": REPO_ROOT / "data/processed/doctree" / SOURCE_RUN_ID,
        "step_03_5_blockstore_cleanup": REPO_ROOT / "data/processed/blockstore_enriched" / SOURCE_RUN_ID,
        "step_03_6_math_salvage": REPO_ROOT / "data/processed/blockstore_math_salvaged" / SOURCE_RUN_ID,
        "step_04_patches": REPO_ROOT / "data/processed/retrieval_index" / SOURCE_RUN_ID,
        "step_04_3_embedding_index": REPO_ROOT / "data/processed/retrieval_index" / SOURCE_RUN_ID,
        "step_04_5_sentence_overlay": REPO_ROOT / "data/processed/retrieval_sentence_overlay" / SOURCE_RUN_ID,
    }
    return mapping


def _cleanup() -> None:
    layout = get_operator_layout(REPO_ROOT)
    for run_id in (SOURCE_RUN_ID, NEW_RUN_ID):
        run_dir = layout.pipeline_runs_root / run_id
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)
        new_convention_dir = REPO_ROOT / "data/processed" / run_id
        if new_convention_dir.exists():
            shutil.rmtree(new_convention_dir, ignore_errors=True)
    for output_dir in set(_fake_stage_output_dirs().values()):
        if output_dir.exists():
            shutil.rmtree(output_dir, ignore_errors=True)


def main() -> int:
    layout = get_operator_layout(REPO_ROOT)
    check("real local hierarchy fixture exists", (REPO_ROOT / REAL_HIERARCHY_PATH).exists())

    try:
        print("=== Step 1: build a fake-but-real source run (7 hierarchy-independent stages completed) ===")
        source_state_path = run_state_mod.run_state_path(layout.pipeline_runs_root, SOURCE_RUN_ID)
        source_state = run_state_mod.new_run_state(
            SOURCE_RUN_ID,
            course_materials=["DOC_fake_a", "DOC_fake_b"],
            hierarchy_path="data/input/hierarchy/original_hierarchy_used_by_source_run.json",
        )
        # step_04_patches and step_04_3_embedding_index genuinely share the same real
        # output_root in the live system (both = "data/processed/retrieval_index" per
        # stage_registry.py) - use a stage-specific marker filename within that shared
        # directory, matching how the two stages' real outputs coexist there without
        # overwriting each other.
        stage_dirs = _fake_stage_output_dirs()
        for stage_id, output_dir in stage_dirs.items():
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / f"{stage_id}_marker.txt").write_text(f"real content for {stage_id}", encoding="utf-8")
            run_state_mod.set_stage_completed(
                source_state, stage_id,
                output_root=str(output_dir), set_manifest_path=f"{stage_id}_set_manifest.json",
                run_folder_symlink=None,
            )
        run_state_mod.write_run_state(source_state_path, source_state)
        source_state_bytes_before = source_state_path.read_bytes()

        print("\n=== Step 2: refuses when a required stage isn't completed yet ===")
        incomplete_state_path = run_state_mod.run_state_path(layout.pipeline_runs_root, SOURCE_RUN_ID + "_incomplete")
        incomplete_state = run_state_mod.new_run_state(SOURCE_RUN_ID + "_incomplete")
        run_state_mod.write_run_state(incomplete_state_path, incomplete_state)
        try:
            seeder.seed(REPO_ROOT, SOURCE_RUN_ID + "_incomplete", NEW_RUN_ID + "_should_not_exist", "x.json", dry_run=True)
            check("refuses cleanly when source stages incomplete", False)
        except RuntimeError as exc:
            check(f"refuses cleanly when source stages incomplete ({exc})", "has not completed" in str(exc))
        finally:
            shutil.rmtree(incomplete_state_path.parent, ignore_errors=True)

        print("\n=== Step 3: ACTUALLY SEED the new run for real (not dry-run) ===")
        result = seeder.seed(REPO_ROOT, SOURCE_RUN_ID, NEW_RUN_ID, REAL_HIERARCHY_PATH, dry_run=False)
        check("seed() reports all 7 stages seeded", result["seeded_stages"] == list(seeder.HIERARCHY_INDEPENDENT_STAGES_IN_ORDER))

        print("\n=== Step 4: confirm the SOURCE run's own RUN_STATE.json is byte-unchanged (read-only guarantee) ===")
        source_state_bytes_after = source_state_path.read_bytes()
        check("source RUN_STATE.json is byte-for-byte unchanged after seeding", source_state_bytes_before == source_state_bytes_after)

        print("\n=== Step 5: confirm the NEW run's RUN_STATE.json is correct ===")
        new_state_path = run_state_mod.run_state_path(layout.pipeline_runs_root, NEW_RUN_ID)
        new_state = run_state_mod.load_run_state(new_state_path)
        check("new run's hierarchy_path is the NEW one, not the source's", new_state["hierarchy_path"] == REAL_HIERARCHY_PATH)
        check("new run's course_materials carried through from source", new_state["course_materials"] == ["DOC_fake_a", "DOC_fake_b"])
        for stage_id, output_dir in stage_dirs.items():
            entry = new_state["stages"].get(stage_id)
            check(f"{stage_id} marked completed in new run", entry is not None and entry["status"] == "completed")
            recorded_root = Path(entry["output_root"])
            marker = recorded_root / f"{stage_id}_marker.txt"
            check(f"{stage_id}'s recorded output_root resolves to the source's real marker file", marker.exists())
            check(f"{stage_id}'s output resolves to the exact same real content (referenced, not copied)", marker.read_text(encoding="utf-8") == f"real content for {stage_id}")
        check("hierarchy_registry NOT marked completed in the new run (must run fresh)", "hierarchy_registry" not in new_state["stages"])

        print("\n=== Step 6: refuses cleanly if the new run_id already exists ===")
        try:
            seeder.seed(REPO_ROOT, SOURCE_RUN_ID, NEW_RUN_ID, REAL_HIERARCHY_PATH, dry_run=False)
            check("refuses cleanly when new_run_id already has RUN_STATE.json", False)
        except RuntimeError as exc:
            check(f"refuses cleanly when new_run_id already has RUN_STATE.json ({exc})", "already exists" in str(exc))

        print("\n=== Step 7: hierarchy_registry refuses cleanly against a dummy/nonexistent hierarchy path ===")
        state_for_dummy = run_state_mod.load_run_state(new_state_path)
        state_for_dummy["hierarchy_path"] = "data/input/hierarchy/DOES_NOT_EXIST_placeholder.json"
        run_state_mod.write_run_state(new_state_path, state_for_dummy)
        proc_dummy = _run_cli("run-stage", "hierarchy_registry", "--run-id", NEW_RUN_ID, "--dry-run", "--no-self-chain")
        check("hierarchy_registry refuses cleanly against a dummy path", proc_dummy.returncode == 3)
        check(
            "refusal is the real existing validation (input hierarchy not found), not a new/different one",
            "hierarchy_registry input hierarchy not found" in (proc_dummy.stdout + proc_dummy.stderr),
        )

        print("\n=== Step 8: hierarchy_registry dry-run SUCCEEDS against a real hierarchy fixture on this seeded run ===")
        state_for_real = run_state_mod.load_run_state(new_state_path)
        state_for_real["hierarchy_path"] = REAL_HIERARCHY_PATH
        run_state_mod.write_run_state(new_state_path, state_for_real)
        proc_real = _run_cli("run-stage", "hierarchy_registry", "--run-id", NEW_RUN_ID, "--dry-run", "--no-self-chain")
        check(f"hierarchy_registry dry-run succeeds on the seeded run (stderr: {proc_real.stderr[-1500:]})", proc_real.returncode == 0)
        rendered_slurm = layout.pipeline_runs_root / NEW_RUN_ID / "hierarchy_registry" / "hierarchy_registry.slurm"
        check("rendered SLURM script exists", rendered_slurm.exists())
        rc_syntax = subprocess.run(["bash", "-n", str(rendered_slurm)], capture_output=True, text=True)
        check(f"rendered script passes bash -n ({rc_syntax.stderr.strip()})", rc_syntax.returncode == 0)

    finally:
        _cleanup()

    print("\nALL seed_hierarchy_rerun.py VERIFICATION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
