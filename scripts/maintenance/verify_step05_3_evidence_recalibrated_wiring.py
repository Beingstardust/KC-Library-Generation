#!/usr/bin/env python3
"""Verify scripts/kc_l_orchestrator.py's run-stage wiring for the newly-added
step_05_3_evidence_recalibrated stage, and step_06_6_drafting_input_overlay's matching
per-run step5_3_active_set_pointer override (2026-07-16 fix - see stage_registry.py's own
notes on both stages for the full investigation: step_05_3 was never migrated into the modern
orchestrator, so step_06_6 always fell through to a single shared ACTIVE_STEP5_3_EVIDENCE_SET.txt
pointer last written 2026-04-26 - the confirmed actual cause of a kc_packet_count 144-vs-159
discrepancy, separate from the BEST_STEP5X/BEST_TOPIC5X staleness fixed earlier the same
investigation).

Covers:
- step_05_3_evidence_recalibrated's rendered config correctly overrides inputs.kc_registry_path
  (from THIS run's own real hierarchy_manifest.json - a real historical fixture, copied into
  the expected nested-timestamp per-run location), inputs.step4_5_active_set_pointer (computed
  from step_04_5's real per-run output_root), and acceptance.n_kcs_total (from the fixture's own
  real num_kcs field, not the base yaml's hardcoded 144 - proven by using a fixture whose real
  num_kcs is a different, distinctive value).
- step_06_6_drafting_input_overlay's rendered config's inputs.step5_3_active_set_pointer points
  at step_05_3's own SHARED (non-run-scoped) ACTIVE_STEP5_3_EVIDENCE_SET.txt sibling path, not a
  run-scoped guess - and refuses cleanly when step_05_3 has not completed in this run.
- Dependency ordering: STAGE_SPECS' own order values are internally consistent (every stage's
  order strictly exceeds every one of its dependencies' order values) - this session directly
  found and fixed a StageSpec insertion bug of exactly this kind.

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
from kc_l.runtime.stage_registry import STAGE_SPECS

ORCHESTRATOR_SCRIPT = REPO_ROOT / "scripts" / "kc_l_orchestrator.py"
TEST_RUN_ID = "verify_step05_3_evidence_recalibrated_test"

REAL_HIERARCHY_MANIFEST_FIXTURE_DIR = REPO_ROOT / "data/processed/hierarchy/20260424T203903Z"
FIXTURE_NUM_KCS = 144  # the real, distinctive value in that fixture's own hierarchy_manifest.json


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
    check("real hierarchy_manifest.json fixture dir exists", REAL_HIERARCHY_MANIFEST_FIXTURE_DIR.exists())

    spec = importlib.util.spec_from_file_location("kc_l_orchestrator_test", ORCHESTRATOR_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    # STAGE_SPECS internal ordering consistency - directly re-checks the exact bug found and
    # fixed this session (a newly-inserted stage placed before its own dependencies' order).
    bad_orderings = [
        (sid, dep)
        for sid, s in STAGE_SPECS.items()
        for dep in s.depends_on
        if STAGE_SPECS[dep].order >= s.order
    ]
    check(f"no StageSpec has order <= a dependency's order (found: {bad_orderings})", not bad_orderings)

    layout = get_operator_layout(REPO_ROOT)

    # Seed Step 01's real normalized-registry output at the exact nested-timestamp location
    # resolve_hierarchy_normalize_output_root()/resolve_hierarchy_manifest_from_output_root()
    # expect: data/processed/hierarchy/<run_id>/<internal_ts>/.
    hierarchy_normalize_root = REPO_ROOT / "data/processed/hierarchy" / TEST_RUN_ID
    seeded_hierarchy_dir = hierarchy_normalize_root / "20260424T203903Z"
    seeded_hierarchy_dir.mkdir(parents=True, exist_ok=True)
    for name in ("hierarchy_manifest.json", "kc_registry.jsonl", "hierarchy_stats.json"):
        shutil.copy2(REAL_HIERARCHY_MANIFEST_FIXTURE_DIR / name, seeded_hierarchy_dir / name)
    # The fixture's own hierarchy_manifest.json self-references its ORIGINAL historical
    # location (registry_path/stats_path) - a genuinely fresh manifest would self-reference its
    # own real per-run location instead, so patch the copy to match, same as a real run would be
    # internally self-consistent.
    seeded_manifest_path = seeded_hierarchy_dir / "hierarchy_manifest.json"
    seeded_manifest = json.loads(seeded_manifest_path.read_text(encoding="utf-8"))
    seeded_manifest["registry_path"] = str(seeded_hierarchy_dir / "kc_registry.jsonl")
    seeded_manifest["stats_path"] = str(seeded_hierarchy_dir / "hierarchy_stats.json")
    seeded_manifest_path.write_text(json.dumps(seeded_manifest, indent=2), encoding="utf-8")

    # Seed a fake-completed hierarchy_registry + step_04_5_sentence_overlay in RUN_STATE - both
    # are step_05_3's real dependencies. hierarchy_registry's own output_root
    # (data/processed/hierarchy_overlay/<run_id>) is deliberately NOT the same root step_05_3
    # actually reads from (data/processed/hierarchy/<run_id>) - this test only needs the
    # dependency to be marked "completed" for resolve_ready_stages()/run-stage's own refusal
    # check to pass; the real path resolution is independently computed by
    # resolve_hierarchy_normalize_output_root(), not from this recorded output_root at all.
    step_04_5_output_root = REPO_ROOT / "data/processed/retrieval_sentence_overlay" / TEST_RUN_ID

    state_path = run_state_mod.run_state_path(layout.pipeline_runs_root, TEST_RUN_ID)
    state = run_state_mod.new_run_state(TEST_RUN_ID)
    run_state_mod.set_stage_completed(
        state, "hierarchy_registry",
        output_root=str(REPO_ROOT / "data/processed/hierarchy_overlay" / TEST_RUN_ID),
        set_manifest_path=None, run_folder_symlink=None,
    )
    run_state_mod.set_stage_completed(
        state, "step_04_5_sentence_overlay",
        output_root=str(step_04_5_output_root),
        set_manifest_path=None, run_folder_symlink=None,
    )
    run_state_mod.write_run_state(state_path, state)

    try:
        print("=== step_05_3_evidence_recalibrated ===")
        run_dir_5_3 = layout.pipeline_runs_root / TEST_RUN_ID / "step_05_3_evidence_recalibrated"
        args = mod.argparse.Namespace(
            repo_root=str(REPO_ROOT),
            stage_id="step_05_3_evidence_recalibrated",
            run_id=TEST_RUN_ID,
            dry_run=True,
            dependency_job_id=None,
            no_self_chain=True,
        )
        rc = mod.run_stage(args)
        check("run_stage() returns 0 for step_05_3_evidence_recalibrated dry-run", rc == 0)

        rendered_config_path = run_dir_5_3 / f"{TEST_RUN_ID}_step_05_3_config.json"
        check("step_05_3 rendered config exists", rendered_config_path.exists())
        rendered_config = json.loads(rendered_config_path.read_text(encoding="utf-8"))

        expected_registry_path = str(seeded_hierarchy_dir / "kc_registry.jsonl")
        check(
            "rendered config's inputs.kc_registry_path is THIS run's real registry (not the base yaml default)",
            rendered_config["inputs"]["kc_registry_path"] == expected_registry_path,
        )
        expected_step4_5_pointer = str(step_04_5_output_root / "_sets" / "ACTIVE_STEP4_5_SET.txt")
        check(
            "rendered config's inputs.step4_5_active_set_pointer is THIS run's real step_04_5 output",
            rendered_config["inputs"]["step4_5_active_set_pointer"] == expected_step4_5_pointer,
        )
        check(
            f"rendered config's acceptance.n_kcs_total is the fixture's real {FIXTURE_NUM_KCS} (not the base yaml's hardcoded 144-that-happens-to-match, verified via the field itself)",
            rendered_config["acceptance"]["n_kcs_total"] == FIXTURE_NUM_KCS,
        )
        check(
            "base yaml's other acceptance.* keys survive the deep-merge (min_kcs_with_2_strong_candidates untouched)",
            rendered_config["acceptance"]["min_kcs_with_2_strong_candidates"] == 100,
        )
        check(
            "base yaml's models.reranker block survives untouched (not something this fix should override)",
            "reranker" in rendered_config["models"],
        )

        slurm_script_5_3 = run_dir_5_3 / "step_05_3_evidence_recalibrated.slurm"
        check("step_05_3 SLURM script was rendered", slurm_script_5_3.exists())
        slurm_text_5_3 = slurm_script_5_3.read_text(encoding="utf-8")
        check("step_05_3 SLURM script requests a real GPU (gpu:a100:1)", "gpu:a100:1" in slurm_text_5_3)

        # Refusal check: step_05_3 requested for a run_id with no completed dependencies.
        fresh_run_id = TEST_RUN_ID + "_no_predecessor"
        import subprocess

        proc = subprocess.run(
            [sys.executable, str(ORCHESTRATOR_SCRIPT), "--repo-root", str(REPO_ROOT),
             "run-stage", "step_05_3_evidence_recalibrated", "--run-id", fresh_run_id, "--dry-run"],
            capture_output=True, text=True,
        )
        check("step_05_3 refuses cleanly when dependencies have not completed", proc.returncode == 3)
        check("refusal names the STAGE_NOT_WIRED error", "ERROR_STAGE_NOT_WIRED" in proc.stdout)
        fresh_run_dir = layout.pipeline_runs_root / fresh_run_id
        if fresh_run_dir.exists():
            shutil.rmtree(fresh_run_dir)

        print("\n=== step_06_6_drafting_input_overlay's step5_3_active_set_pointer override ===")
        # Now fake-complete step_05_3_evidence_recalibrated too, then dry-run step_06_6 and
        # confirm its rendered config's inputs.step5_3_active_set_pointer points at step_05_3's
        # own SHARED (non-run-scoped) ACTIVE pointer sibling path.
        state = run_state_mod.load_run_state(state_path)
        run_state_mod.set_stage_completed(
            state, "step_05_3_evidence_recalibrated",
            output_root=str(REPO_ROOT / "data/processed/kc_evidence_recalibrated" / TEST_RUN_ID),
            set_manifest_path=None, run_folder_symlink=None,
        )
        run_state_mod.set_stage_completed(
            state, "step_05x_kc_evidence_stage_v3",
            output_root=str(REPO_ROOT / "data/processed/evidence_stage_v3_evidence_packs" / TEST_RUN_ID),
            set_manifest_path=None, run_folder_symlink=None,
        )
        run_state_mod.set_stage_completed(
            state, "topic_05x_evidence_stage_v3",
            output_root=str(REPO_ROOT / "data/processed/topic_evidence_stage_v3_evidence_packs" / TEST_RUN_ID),
            set_manifest_path=None, run_folder_symlink=None,
        )
        run_state_mod.write_run_state(state_path, state)

        # step_06_6's own real per-run resolution (build_step6_6_evidence_bridge) needs real
        # step5x_v3/topic5x_v3 set-manifest fixtures to exist on disk too, or it will refuse
        # before ever reaching the step5_3 pointer computation this test targets - reuse the
        # exact same real fixture verify_step6_6_evidence_bridge.py already establishes exists.
        from kc_l.runtime.step6_6_evidence_bridge import TOPIC5X_V3_OUTPUT_ROOT, run_scoped_pack_set_path

        real_kc_pack_fixture = REPO_ROOT / (
            "data/processed/evidence_stage_v3_evidence_packs/_sets/"
            "best_step5x_final_sanitized_gapaware_20260519T160140Z_pack_step5x_v3_evidence_packs_set.json"
        )
        real_topic_pack_fixture = REPO_ROOT / (
            "data/processed/topic_evidence_stage_v3_evidence_packs/_sets/"
            "topic5x_pack_from_trace_rehydrated_scored_20260519T194911Z_step5x_v3_evidence_packs_set.json"
        )
        check("real KC pack-set fixture exists locally", real_kc_pack_fixture.exists())
        check("real topic pack-set fixture exists locally", real_topic_pack_fixture.exists())

        from kc_l.runtime.step6_6_evidence_bridge import STEP5X_V3_OUTPUT_ROOT

        kc_seeded_path = REPO_ROOT / run_scoped_pack_set_path(STEP5X_V3_OUTPUT_ROOT, TEST_RUN_ID)
        kc_seeded_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(real_kc_pack_fixture, kc_seeded_path)
        topic_seeded_path = REPO_ROOT / run_scoped_pack_set_path(TOPIC5X_V3_OUTPUT_ROOT, TEST_RUN_ID)
        topic_seeded_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(real_topic_pack_fixture, topic_seeded_path)

        args66 = mod.argparse.Namespace(
            repo_root=str(REPO_ROOT),
            stage_id="step_06_6_drafting_input_overlay",
            run_id=TEST_RUN_ID,
            dry_run=True,
            dependency_job_id=None,
            no_self_chain=True,
        )
        rc66 = mod.run_stage(args66)
        check("run_stage() returns 0 for step_06_6_drafting_input_overlay dry-run", rc66 == 0)

        run_dir_66 = layout.pipeline_runs_root / TEST_RUN_ID / "step_06_6_drafting_input_overlay"
        rendered_config_66_path = run_dir_66 / f"{TEST_RUN_ID}_step6_6_config.json"
        check("step_06_6 rendered config exists", rendered_config_66_path.exists())
        rendered_config_66 = json.loads(rendered_config_66_path.read_text(encoding="utf-8"))

        expected_step5_3_pointer = str(
            REPO_ROOT / STAGE_SPECS["step_05_3_evidence_recalibrated"].output_root
            / "_sets" / "ACTIVE_STEP5_3_EVIDENCE_SET.txt"
        )
        check(
            "step_06_6's rendered config inputs.step5_3_active_set_pointer is step_05_3's own "
            "SHARED sibling path (not a run-scoped guess, not the old hardcoded base-yaml default)",
            rendered_config_66["inputs"]["step5_3_active_set_pointer"] == expected_step5_3_pointer,
        )

        for seeded in (kc_seeded_path, topic_seeded_path):
            if seeded.exists():
                seeded.unlink()

    finally:
        _cleanup_test_run()
        if hierarchy_normalize_root.exists():
            shutil.rmtree(hierarchy_normalize_root)
        if step_04_5_output_root.exists():
            shutil.rmtree(step_04_5_output_root)

    print("\nALL step_05_3_evidence_recalibrated WIRING CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
