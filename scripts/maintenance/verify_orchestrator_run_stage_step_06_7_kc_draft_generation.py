#!/usr/bin/env python3
"""Verify scripts/kc_l_orchestrator.py's run-stage wiring for step_06_7_kc_draft_generation.

Covers:
- --selected-packets-jsonl and --plan-json are resolved/generated from a real seeded
  step_06_7_hierarchy_aware_synthesis_packets output (fixed filenames, no glob needed for
  this stage).
- --plan-json is populated from the real packet builder's own stats.json (packet_source,
  row_count, unit_type_counter), not a hardcoded stub.
- --base-runner is the confirmed real fixed path.
- needs_ollama SLURM rendering includes model/num_ctx/num_predict env vars.
- refuses cleanly when step_06_7_hierarchy_aware_synthesis_packets has not completed.

Uses a throwaway run_id under the real repo's data/processed/runs/ (cleaned up at the end).
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
TEST_RUN_ID = "verify_step_06_7_kc_draft_generation_test"

REAL_PACKET_BUILDER_OUTPUT_DIR = REPO_ROOT / (
    "data/processed/step67_v2_hierarchy_aware_synthesis_packets/20260520T151731Z_policy_repair_replay"
)


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


def main() -> int:
    check("real packet-builder output dir exists", REAL_PACKET_BUILDER_OUTPUT_DIR.exists())
    check(
        "real packet-builder stats.json exists",
        (REAL_PACKET_BUILDER_OUTPUT_DIR / "step67_v2_hierarchy_aware_synthesis_packet_stats.json").exists(),
    )
    check(
        "real base-runner script exists",
        (REPO_ROOT / "scripts/experimental/run_step67_v2_tiny_smoke.py").exists(),
    )

    layout = get_operator_layout(REPO_ROOT)
    packets_output_root = REPO_ROOT / "data/processed/step67_v2_hierarchy_aware_synthesis_packets" / TEST_RUN_ID
    packets_output_root.mkdir(parents=True, exist_ok=True)
    for name in (
        "step67_v2_hierarchy_aware_synthesis_packets.jsonl",
        "step67_v2_hierarchy_aware_synthesis_packet_stats.json",
    ):
        shutil.copy2(REAL_PACKET_BUILDER_OUTPUT_DIR / name, packets_output_root / name)

    state_path = run_state_mod.run_state_path(layout.pipeline_runs_root, TEST_RUN_ID)
    state = run_state_mod.new_run_state(TEST_RUN_ID)
    run_state_mod.set_stage_completed(
        state,
        "step_06_7_hierarchy_aware_synthesis_packets",
        output_root=str(packets_output_root),
        set_manifest_path=None,
        run_folder_symlink=None,
    )
    run_state_mod.write_run_state(state_path, state)

    try:
        proc = _run_cli("run-stage", "step_06_7_kc_draft_generation", "--run-id", TEST_RUN_ID, "--dry-run")
        check(f"run-stage exits 0 (stderr: {proc.stderr[-1500:]})", proc.returncode == 0)

        run_dir = layout.pipeline_runs_root / TEST_RUN_ID / "step_06_7_kc_draft_generation"
        slurm_script = run_dir / "step_06_7_kc_draft_generation.slurm"
        check("SLURM script was rendered to disk", slurm_script.exists())
        text = slurm_script.read_text(encoding="utf-8")

        check(
            "rendered script references the real selected-packets-jsonl (not a placeholder)",
            str(packets_output_root / "step67_v2_hierarchy_aware_synthesis_packets.jsonl") in text,
        )
        check(
            "rendered script references the real base-runner path",
            "scripts/experimental/run_step67_v2_tiny_smoke.py" in text.replace("\\", "/"),
        )
        check("rendered script sets model=gemma4:31b", "gemma4:31b" in text)
        check("rendered script sets num_ctx=65536", "65536" in text)
        check("rendered script sets num_predict=16000", "16000" in text)
        check("rendered script sets --timeout-s 1200", "1200" in text)
        check(
            "rendered script sets the correct LD_LIBRARY_PATH",
            "/path/to/software/python/python-3.11.3/lib" in text,
        )
        # Regression check for job 228481's crash (KeyError: 'KC_L_FINAL_SCHEMA_RUNNER'): this
        # stage's real script_path reads both these env vars at module import time - confirm the
        # rendered script now exports both, pointing at the resurrected v2_chain/ scripts'
        # confirmed real stable location (same paths scripts/maintenance/
        # verify_step67_v2_chain_resurrection.py already exercises).
        normalized_text = text.replace("\\", "/")
        check(
            "rendered script exports KC_L_FINAL_SCHEMA_RUNNER pointing at run_step67_v2_topic_schema_dict_aligned.py",
            "KC_L_FINAL_SCHEMA_RUNNER=" in text
            and "steps/step_06_7_kc_draft_generation/scripts/v2_chain/run_step67_v2_topic_schema_dict_aligned.py" in normalized_text,
        )
        check(
            "rendered script exports KC_L_SOURCE_SCHEMA_RUNNER pointing at run_step67_v2_schema_contract_probe.py",
            "KC_L_SOURCE_SCHEMA_RUNNER=" in text
            and "steps/step_06_7_kc_draft_generation/scripts/v2_chain/run_step67_v2_schema_contract_probe.py" in normalized_text,
        )

        # Find and validate the generated --plan-json placeholder content.
        plan_json_path = run_dir / f"{TEST_RUN_ID}_step67_v2_plan.json"
        check("generated --plan-json placeholder file exists", plan_json_path.exists())
        plan = json.loads(plan_json_path.read_text(encoding="utf-8"))
        real_stats = json.loads(
            (REAL_PACKET_BUILDER_OUTPUT_DIR / "step67_v2_hierarchy_aware_synthesis_packet_stats.json").read_text(encoding="utf-8")
        )
        check("plan-json row_count matches real packet builder's all_packet_count (165)", plan["row_count"] == 165)
        check(
            "plan-json unit_type_counter matches real packet builder's kc/topic counts",
            plan["unit_type_counter"] == {
                "kc": real_stats["metrics"]["kc_packet_count"],
                "topic": real_stats["metrics"]["topic_packet_count"],
            },
        )
        check(
            "plan-json packet_source references the real selected-packets-jsonl",
            plan["packet_source"] == str(packets_output_root / "step67_v2_hierarchy_aware_synthesis_packets.jsonl"),
        )

        proc = subprocess.run(["bash", "-n", str(slurm_script)], capture_output=True, text=True)
        check(f"rendered script passes bash -n ({proc.stderr.strip()})", proc.returncode == 0)

        # Refusal check: a fresh run_id with no completed packet-builder stage must refuse.
        fresh_run_id = TEST_RUN_ID + "_no_predecessor"
        proc2 = _run_cli("run-stage", "step_06_7_kc_draft_generation", "--run-id", fresh_run_id, "--dry-run")
        check("refuses cleanly when packet builder has not completed", proc2.returncode == 3)
        check("refusal names the STAGE_NOT_WIRED error", "ERROR_STAGE_NOT_WIRED" in proc2.stdout)
        fresh_run_dir = layout.pipeline_runs_root / fresh_run_id
        if fresh_run_dir.exists():
            shutil.rmtree(fresh_run_dir)

    finally:
        test_run_dir = layout.pipeline_runs_root / TEST_RUN_ID
        if test_run_dir.exists():
            shutil.rmtree(test_run_dir)
        if packets_output_root.exists():
            shutil.rmtree(packets_output_root)

    print("\nALL step_06_7_kc_draft_generation RUN-STAGE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
