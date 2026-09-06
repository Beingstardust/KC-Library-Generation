#!/usr/bin/env python3
"""Verify scripts/kc_l_orchestrator.py's run-stage wiring for step_06_9_review_audit_ingestion.

Covers:
- inputs.review_packet_set_manifest is set to step 6.8's fixed (non-timestamped)
  STEP68_V2_REVIEW_PACKET_MANIFEST.json path, using a real historical v2-schema fixture.
- outputs.processed_root/sets_root are overridden to the per-run scoped directory.
- rendered config is valid JSON with the real (not placeholder) predecessor path.
- refuses cleanly when step 6.8 has not completed.

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

from kc_l.kc.restarted_review_audits import _resolve_review_packet_jsonl_path
from kc_l.runtime import run_state as run_state_mod
from kc_l.runtime.layout import get_operator_layout
from kc_l.utils.json_io import read_jsonl

ORCHESTRATOR_SCRIPT = REPO_ROOT / "scripts" / "kc_l_orchestrator.py"
TEST_RUN_ID = "verify_step_06_9_test"

REAL_STEP_06_8_OUTPUT_ROOT = REPO_ROOT / (
    "data/processed/step68_v2_review_packets_from_postprocessed_source/"
    "20260521T231531Z_current_postprocessed_source_runner_return_contract_fix"
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


LEGACY_REVIEW_PACKET_DIR = REPO_ROOT / "data/processed/kc_review_packets_restarted/2026-04-08_194540"


def main() -> int:
    manifest_path = REAL_STEP_06_8_OUTPUT_ROOT / "STEP68_V2_REVIEW_PACKET_MANIFEST.json"
    check("real v2-schema step 6.8 manifest fixture exists", manifest_path.exists())
    manifest_obj = json.loads(manifest_path.read_text(encoding="utf-8"))
    check(
        "fixture really is v2 schema (run_id + outputs, no artifacts key)",
        "run_id" in manifest_obj and "outputs" in manifest_obj and "artifacts" not in manifest_obj,
    )

    # Regression check for job 228522's crash (FileNotFoundError: review_packet.jsonl):
    # emit_restarted_review_audits() hardcoded the legacy Step 6.8 producer's filename instead
    # of the current v2 producer's real one. Verify _resolve_review_packet_jsonl_path() directly
    # against both a real v2 fixture (must use the manifest) and a real legacy fixture (must
    # still fall back correctly, since legacy dirs have no manifest sibling).
    print("\n=== _resolve_review_packet_jsonl_path(): real v2 fixture uses the manifest ===")
    v2_resolved = _resolve_review_packet_jsonl_path(REAL_STEP_06_8_OUTPUT_ROOT)
    check(
        f"resolves to the real v2 packets file (not the legacy name): {v2_resolved}",
        v2_resolved == REAL_STEP_06_8_OUTPUT_ROOT / "step68_v2_review_packets.jsonl",
    )
    check("resolved v2 packets file actually exists", v2_resolved.exists())
    v2_rows = list(read_jsonl(v2_resolved))
    check(f"resolved v2 packets file has real rows (found {len(v2_rows)})", len(v2_rows) > 0)
    check("real v2 packet rows use knowledge_unit_id (not kc_candidate_id)", "knowledge_unit_id" in v2_rows[0])

    print("\n=== _resolve_review_packet_jsonl_path(): legacy fixture (no manifest) falls back correctly ===")
    check("real legacy fixture dir exists", LEGACY_REVIEW_PACKET_DIR.exists())
    check(
        "legacy fixture dir genuinely has no v2 manifest sibling",
        not (LEGACY_REVIEW_PACKET_DIR / "STEP68_V2_REVIEW_PACKET_MANIFEST.json").exists(),
    )
    legacy_resolved = _resolve_review_packet_jsonl_path(LEGACY_REVIEW_PACKET_DIR)
    check(
        f"falls back to the legacy filename: {legacy_resolved}",
        legacy_resolved == LEGACY_REVIEW_PACKET_DIR / "review_packet.jsonl",
    )
    check("resolved legacy packets file actually exists", legacy_resolved.exists())
    legacy_rows = list(read_jsonl(legacy_resolved))
    check(f"resolved legacy packets file has real rows (found {len(legacy_rows)})", len(legacy_rows) > 0)
    check("real legacy packet rows use kc_candidate_id", "kc_candidate_id" in legacy_rows[0])

    layout = get_operator_layout(REPO_ROOT)
    state_path = run_state_mod.run_state_path(layout.pipeline_runs_root, TEST_RUN_ID)
    state = run_state_mod.new_run_state(TEST_RUN_ID)
    run_state_mod.set_stage_completed(
        state,
        "step_06_8_review_packet_emission",
        output_root=str(REAL_STEP_06_8_OUTPUT_ROOT),
        set_manifest_path=str(manifest_path),
        run_folder_symlink=None,
    )
    run_state_mod.write_run_state(state_path, state)

    try:
        proc = _run_cli("run-stage", "step_06_9_review_audit_ingestion", "--run-id", TEST_RUN_ID, "--dry-run")
        check(f"run-stage exits 0 (stderr: {proc.stderr[-1500:]})", proc.returncode == 0)

        run_dir = layout.pipeline_runs_root / TEST_RUN_ID / "step_06_9_review_audit_ingestion"
        slurm_script = run_dir / "step_06_9_review_audit_ingestion.slurm"
        check("SLURM script was rendered to disk", slurm_script.exists())
        text = slurm_script.read_text(encoding="utf-8")

        rendered_config_path = run_dir / f"{TEST_RUN_ID}_step_06_9_config.json"
        check("rendered config exists", rendered_config_path.exists())
        rendered_config = json.loads(rendered_config_path.read_text(encoding="utf-8"))
        check(
            "rendered config references the real (not placeholder) step 6.8 manifest",
            rendered_config["inputs"]["review_packet_set_manifest"] == str(manifest_path),
        )
        check(
            "rendered config's processed_root is run-id-scoped",
            rendered_config["outputs"]["processed_root"] == f"data/processed/kc_review_audits_restarted/{TEST_RUN_ID}",
        )
        check("rendered SLURM script references the rendered config", str(rendered_config_path) in text)
        check(
            "rendered script sets the correct LD_LIBRARY_PATH",
            "/path/to/software/python/python-3.11.3/lib" in text,
        )

        proc = subprocess.run(["bash", "-n", str(slurm_script)], capture_output=True, text=True)
        check(f"rendered script passes bash -n ({proc.stderr.strip()})", proc.returncode == 0)

        fresh_run_id = TEST_RUN_ID + "_no_predecessor"
        proc2 = _run_cli("run-stage", "step_06_9_review_audit_ingestion", "--run-id", fresh_run_id, "--dry-run")
        check("refuses cleanly when step 6.8 has not completed", proc2.returncode == 3)
        check("refusal names the STAGE_NOT_WIRED error", "ERROR_STAGE_NOT_WIRED" in proc2.stdout)
        fresh_run_dir = layout.pipeline_runs_root / fresh_run_id
        if fresh_run_dir.exists():
            shutil.rmtree(fresh_run_dir)

    finally:
        test_run_dir = layout.pipeline_runs_root / TEST_RUN_ID
        if test_run_dir.exists():
            shutil.rmtree(test_run_dir)

    print("\nALL step_06_9_review_audit_ingestion RUN-STAGE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
