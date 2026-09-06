#!/usr/bin/env python3
"""Verify the human_review_gate mechanism (2026-07-16): a stage marked human_review_gate=True
(currently only step_06_9_review_audit_ingestion) must never be auto-submitted by
kc_l.runtime.chain.submit_ready_stages(), even once fully ready (dependency completed) and
run_stage_wired=True - it should instead be reported under a distinct
"ready_pending_human_review" category, with RUN_STATE.json's top-level status set to
"awaiting_human_review", never conflated with "blocked_unwired_stage" (a different, unrelated
problem: a stage nobody has finished wiring at all).

This is the mechanism that lets step_06_6 through step_06_8's self-chain run fully unattended
and still stop naturally at the correct human-review boundary, with no --no-self-chain flag
needed anywhere in the actual chain to enforce it.
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from kc_l.runtime import run_state as run_state_mod
from kc_l.runtime.chain import resolve_ready_stages, submit_ready_stages
from kc_l.runtime.layout import get_operator_layout
from kc_l.runtime.stage_registry import STAGE_SPECS

ORCHESTRATOR_SCRIPT = REPO_ROOT / "scripts" / "kc_l_orchestrator.py"
TEST_RUN_ID = "verify_human_review_gate_test"


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        raise SystemExit(f"Verification failed: {label}")


def main() -> int:
    check(
        "step_06_9_review_audit_ingestion is marked human_review_gate=True",
        STAGE_SPECS["step_06_9_review_audit_ingestion"].human_review_gate is True,
    )
    check(
        "step_06_9_review_audit_ingestion is still run_stage_wired=True (gated, not unwired)",
        STAGE_SPECS["step_06_9_review_audit_ingestion"].run_stage_wired is True,
    )
    check(
        "step_06_8_review_packet_emission is NOT gated (the automated boundary sits AFTER it)",
        STAGE_SPECS["step_06_8_review_packet_emission"].human_review_gate is False,
    )

    layout = get_operator_layout(REPO_ROOT)
    state_path = run_state_mod.run_state_path(layout.pipeline_runs_root, TEST_RUN_ID)
    state = run_state_mod.new_run_state(TEST_RUN_ID)
    run_state_mod.set_stage_completed(
        state, "step_06_8_review_packet_emission",
        output_root=str(REPO_ROOT / "data/processed/step68_v2_review_packets_from_postprocessed_source" / TEST_RUN_ID),
        set_manifest_path=None, run_folder_symlink=None,
    )
    run_state_mod.write_run_state(state_path, state)

    try:
        ready = resolve_ready_stages(state)
        check(
            "resolve_ready_stages() still returns step_06_9 raw (callers decide what to do, per its own docstring)",
            "step_06_9_review_audit_ingestion" in ready,
        )

        spec = importlib.util.spec_from_file_location("kc_l_orchestrator_test", ORCHESTRATOR_SCRIPT)
        orch = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(orch)

        # A fresh RUN_STATE also has other genuinely-ready zero-dependency stages (e.g.
        # hierarchy_registry, step_02_pdf_ingest) - only step_06_9 (the gated one) must never
        # reach run_stage(); let every other stage's real run_stage() attempt proceed normally
        # (it may itself refuse via StageNotWiredError for unrelated reasons, e.g. no
        # course_materials - that's fine, this test only cares about the gate).
        real_run_stage = orch.run_stage

        def _guarded_run_stage(args):
            if args.stage_id == "step_06_9_review_audit_ingestion":
                raise AssertionError(
                    "run_stage() must never be called for a gated stage - submit_ready_stages() "
                    "must filter it out before reaching this point"
                )
            return real_run_stage(args)

        with mock.patch.object(orch, "run_stage", side_effect=_guarded_run_stage):
            result = submit_ready_stages(orch, REPO_ROOT, TEST_RUN_ID, state_path, dry_run=False)

        check(
            "step_06_9 is reported under ready_pending_human_review, not submitted",
            result["ready_pending_human_review"] == ["step_06_9_review_audit_ingestion"],
        )
        check("step_06_9 is NOT in ready_wired_submitted", "step_06_9_review_audit_ingestion" not in result["ready_wired_submitted"])
        check("step_06_9 is NOT in ready_blocked (that's for unwired stages, not gated ones)", "step_06_9_review_audit_ingestion" not in result["ready_blocked"])
        # Other genuinely-ready zero-dependency stages (hierarchy_registry, step_02_pdf_ingest)
        # cleanly refuse in this fresh, otherwise-empty test state (no course_materials/
        # hierarchy_path seeded) - that's expected noise, unrelated to this test. Only step_06_9
        # itself must never show up as a submission_failure (gating is not a failure).
        check(
            "step_06_9 is NOT recorded as a submission_failure (gating is not a failure)",
            "step_06_9_review_audit_ingestion" not in (result.get("submission_failures") or {}),
        )

        state_after = run_state_mod.load_run_state(state_path)
        check(
            "RUN_STATE.json records step_06_9 under pending_human_review",
            state_after.get("pending_human_review", {}).get("step_06_9_review_audit_ingestion", {}).get("status")
            == "ready_pending_human_review",
        )
        check(
            "RUN_STATE.json top-level status is awaiting_human_review, not blocked_unwired_stage",
            state_after.get("status") == "awaiting_human_review",
        )
        check(
            "RUN_STATE.json's blocked_stages is untouched (gating is not an unwired-stage blocker)",
            not state_after.get("blocked_stages"),
        )

        # dry-run path (used by --dry-run advance_run.py) must report the same category too.
        dry_ready = resolve_ready_stages(state_after)
        dry_result = {
            "ready_wired_submitted": [
                sid for sid in dry_ready
                if STAGE_SPECS[sid].run_stage_wired and not STAGE_SPECS[sid].human_review_gate
            ],
            "ready_pending_human_review": [sid for sid in dry_ready if STAGE_SPECS[sid].human_review_gate],
        }
        check(
            "dry-run-style resolution also excludes the gated stage from ready_wired_submitted",
            "step_06_9_review_audit_ingestion" not in dry_result["ready_wired_submitted"],
        )
        check(
            "dry-run-style resolution reports the gated stage under ready_pending_human_review",
            dry_result["ready_pending_human_review"] == ["step_06_9_review_audit_ingestion"],
        )

    finally:
        run_dir = layout.pipeline_runs_root / TEST_RUN_ID
        if run_dir.exists():
            shutil.rmtree(run_dir)

    print("\nALL human_review_gate CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
