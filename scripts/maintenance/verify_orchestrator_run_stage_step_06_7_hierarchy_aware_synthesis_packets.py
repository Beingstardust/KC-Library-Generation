#!/usr/bin/env python3
"""Verify scripts/kc_l_orchestrator.py's run-stage wiring for
step_06_7_hierarchy_aware_synthesis_packets.

Covers:
- --step66-set is resolved by globbing step 6.6's own per-run _sets/ directory for the single
  matching set-manifest file (proves the glob-based resolution, not a hardcoded/predicted
  timestamp) - uses a real historical step 6.6 set-manifest fixture, copied into the expected
  per-run location.
- --topic5x-pack resolves via the real read_kc_evidence_packs_jsonl() mechanism (already
  independently verified in verify_step6_6_evidence_bridge.py) against THIS test run's own
  run-scoped set-manifest path (run_scoped_pack_set_path() - 2026-07-15 fix, replacing the old
  BEST_TOPIC5X_FINAL_PACK_FOR_STEP6_SET.txt pointer resolution, confirmed stale/never-updated).
  A real historical pack-set JSON fixture is copied into that exact per-run location, same
  seeding pattern as step 6.6's own set-manifest fixture below.
- --child-kc-drafts uses the fixed historical path and it must actually exist in this checkout.
- run-stage refuses cleanly when step_06_6 has not completed in this run.

Uses a throwaway run_id under the real repo's data/processed/runs/ (cleaned up at the end).
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from kc_l.runtime import run_state as run_state_mod
from kc_l.runtime.layout import get_operator_layout
from kc_l.runtime.step6_6_evidence_bridge import TOPIC5X_V3_OUTPUT_ROOT, run_scoped_pack_set_path

ORCHESTRATOR_SCRIPT = REPO_ROOT / "scripts" / "kc_l_orchestrator.py"
TEST_RUN_ID = "verify_step_06_7_hierarchy_aware_synthesis_packets_test"

REAL_STEP66_SET_FIXTURE = REPO_ROOT / (
    "_archive/repo_cleanup_candidates/local_audits/package_raw_complete_5p_5x_66_67_lineage_20260520T230942Z/"
    "stage/data/processed/kc_drafting_input_overlay/_sets/"
    "2026-05-19_213641_step6_6_kc_drafting_input_overlay_set.json"
)
REAL_TOPIC5X_PACK_SET_JSON = REPO_ROOT / (
    "data/processed/topic_evidence_stage_v3_evidence_packs/_sets/"
    "topic5x_pack_from_trace_rehydrated_scored_20260519T194911Z_step5x_v3_evidence_packs_set.json"
)


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


def main() -> int:
    check("real step 6.6 set-manifest fixture exists", REAL_STEP66_SET_FIXTURE.exists())
    check("real topic5x pack-set JSON exists locally", REAL_TOPIC5X_PACK_SET_JSON.exists())
    child_kc_drafts_path = REPO_ROOT / (
        "data/processed/kc_drafts_quality_overlays/"
        "step67_short_definition_repair_proposal_207434_20260520T114433Z/kc_draft_bundles.jsonl"
    )
    check("fixed historical child_kc_drafts path exists", child_kc_drafts_path.exists())

    spec = importlib.util.spec_from_file_location("kc_l_orchestrator_test", ORCHESTRATOR_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    layout = get_operator_layout(REPO_ROOT)
    run_dir = layout.pipeline_runs_root / TEST_RUN_ID / "step_06_7_hierarchy_aware_synthesis_packets"

    # Seed a fake-completed step_06_6 with a real historical set-manifest fixture copied into
    # the exact per-run _sets/ location the glob resolver expects.
    step6_6_output_root = REPO_ROOT / "data/processed/kc_drafting_input_overlay" / TEST_RUN_ID
    step6_6_sets_root = step6_6_output_root / "_sets"
    step6_6_sets_root.mkdir(parents=True, exist_ok=True)
    seeded_set_manifest = step6_6_sets_root / "2026-05-19_213641_step6_6_kc_drafting_input_overlay_set.json"
    shutil.copy2(REAL_STEP66_SET_FIXTURE, seeded_set_manifest)

    # Seed this test run_id's own topic5x_v3 set-manifest at the exact run-scoped path
    # run_scoped_pack_set_path() now resolves by default (2026-07-15 fix) - a real historical
    # pack-set JSON fixture, copied into that location rather than left at its own real run_id's
    # path, same seeding pattern as step 6.6's set-manifest above.
    topic5x_seeded_path = REPO_ROOT / run_scoped_pack_set_path(TOPIC5X_V3_OUTPUT_ROOT, TEST_RUN_ID)
    topic5x_seeded_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REAL_TOPIC5X_PACK_SET_JSON, topic5x_seeded_path)

    state_path = run_state_mod.run_state_path(layout.pipeline_runs_root, TEST_RUN_ID)
    state = run_state_mod.new_run_state(TEST_RUN_ID)
    run_state_mod.set_stage_completed(
        state,
        "step_06_6_drafting_input_overlay",
        output_root=str(step6_6_output_root),
        set_manifest_path=str(seeded_set_manifest),
        run_folder_symlink=None,
    )
    run_state_mod.write_run_state(state_path, state)

    try:
        args = mod.argparse.Namespace(
            repo_root=str(REPO_ROOT),
            stage_id="step_06_7_hierarchy_aware_synthesis_packets",
            run_id=TEST_RUN_ID,
            dry_run=True,
            dependency_job_id=None,
        )
        rc = mod.run_stage(args)
        check("run_stage() returns 0 for step_06_7_hierarchy_aware_synthesis_packets dry-run", rc == 0)

        slurm_script = run_dir / "step_06_7_hierarchy_aware_synthesis_packets.slurm"
        check("SLURM script was rendered to disk", slurm_script.exists())
        text = slurm_script.read_text(encoding="utf-8")

        check(
            "rendered script references the real glob-resolved step66-set (not a placeholder)",
            str(seeded_set_manifest) in text,
        )
        check(
            "rendered script references the real topic5x_pack kc_evidence_packs.jsonl path",
            "topic5x_pack_from_trace_rehydrated_scored_20260519T194911Z" in text
            and "kc_evidence_packs.jsonl" in text,
        )
        check(
            "rendered script references the fixed historical child_kc_drafts path",
            "step67_short_definition_repair_proposal_207434_20260520T114433Z" in text,
        )
        check(
            "rendered script sets the correct LD_LIBRARY_PATH",
            "/path/to/software/python/python-3.11.3/lib" in text,
        )

        import subprocess

        proc = subprocess.run(["bash", "-n", str(slurm_script)], capture_output=True, text=True)
        check(f"rendered script passes bash -n ({proc.stderr.strip()})", proc.returncode == 0)

        # Refusal check: a fresh run_id with no completed step_06_6 must refuse, not guess.
        fresh_run_id = TEST_RUN_ID + "_no_predecessor"
        proc2 = subprocess.run(
            [sys.executable, str(ORCHESTRATOR_SCRIPT), "--repo-root", str(REPO_ROOT),
             "run-stage", "step_06_7_hierarchy_aware_synthesis_packets", "--run-id", fresh_run_id, "--dry-run"],
            capture_output=True, text=True,
        )
        check("refuses cleanly when step_06_6 has not completed", proc2.returncode == 3)
        check("refusal names the STAGE_NOT_WIRED error", "ERROR_STAGE_NOT_WIRED" in proc2.stdout)
        fresh_run_dir = layout.pipeline_runs_root / fresh_run_id
        if fresh_run_dir.exists():
            shutil.rmtree(fresh_run_dir)

    finally:
        _cleanup_test_run()
        if step6_6_output_root.exists():
            shutil.rmtree(step6_6_output_root)
        if topic5x_seeded_path.exists():
            topic5x_seeded_path.unlink()

    print("\nALL step_06_7_hierarchy_aware_synthesis_packets RUN-STAGE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
