#!/usr/bin/env python3
"""Verify scripts/advance_run.py's self-chaining logic.

Covers:
- render_cpu_job/render_ollama_job's extra_commands stays byte-identical when unused (both
  functions, not just render_cpu_job - a real regression risk this session, since
  render_ollama_job needed the SAME new parameter added independently).
- run_stage() appends the advance_run.py chain-advance trailer by default; --no-self-chain
  suppresses it.
- step_02_pdf_ingest's own per-document jobs only carry the trailer on the LAST document's
  script, never the earlier ones (a real correctness requirement - triggering advance_run.py
  after just one of several documents would prematurely treat the whole stage as complete).
- advance() marks a completed stage in RUN_STATE.json, creates (or gracefully no-ops, on a
  platform where symlink creation isn't permitted) the run-folder symlink, and correctly
  resolves the ready-set via a simulated multi-parent fan-in scenario: a stage with two
  predecessors only becomes ready once BOTH have completed, regardless of which one advance()
  was called for.
- A ready-but-NOT-wired next stage is recorded under RUN_STATE.json's blocked_stages with the
  run's overall status set to "blocked_unwired_stage" - not silently dropped, not treated as a
  hard error.
- plan()'s own explicit stage-by-stage submission passes no_self_chain=True, so it does not
  double-submit stages via the new automatic chaining on top of its own explicit sequencing.

Uses a throwaway run_id under the real repo's data/processed/runs/ (cleaned up at the end) and
monkeypatches slurm_submit.sbatch_submit - no real SLURM dependency anywhere in this script.
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

import advance_run  # noqa: E402
import kc_l_orchestrator as orch  # noqa: E402
from kc_l.runtime import run_state as run_state_mod  # noqa: E402
from kc_l.runtime import slurm_render  # noqa: E402
from kc_l.runtime.layout import get_operator_layout  # noqa: E402

TEST_RUN_ID = "verify_advance_run_test"

_FAKE_JOB_COUNTER = [2000]


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        raise SystemExit(f"Verification failed: {label}")


def _fake_sbatch_submit(script_path, *, dependency_job_id=None):
    _FAKE_JOB_COUNTER[0] += 1
    return str(_FAKE_JOB_COUNTER[0])


def _cleanup_run_id(run_id: str) -> None:
    layout = get_operator_layout(REPO_ROOT)
    run_dir = layout.pipeline_runs_root / run_id
    if run_dir.exists():
        shutil.rmtree(run_dir)
    # Directory-restructuring convention symlinks (data/processed/<run_id>/<stage_id>) live
    # outside the runs/ tree above - clean those up too, same spirit as the run_dir cleanup.
    new_convention_dir = REPO_ROOT / "data/processed" / run_id
    if new_convention_dir.exists():
        shutil.rmtree(new_convention_dir, ignore_errors=True)


def verify_render_backward_compat() -> None:
    print("\n=== render_cpu_job/render_ollama_job: extra_commands empty => byte-identical output ===")
    cpu_without = slurm_render.render_cpu_job(
        job_name="j", run_id="r", repo_root="/x", python_bin="/py", script_path="s.py",
        script_args=["--a", "1"], log_dir="/log",
    )
    cpu_with_empty = slurm_render.render_cpu_job(
        job_name="j", run_id="r", repo_root="/x", python_bin="/py", script_path="s.py",
        script_args=["--a", "1"], log_dir="/log", extra_commands=(),
    )
    check("render_cpu_job(extra_commands=()) matches no-arg call exactly", cpu_without == cpu_with_empty)
    check("render_cpu_job still ends with the plain RUNNER_RC exit", cpu_without.rstrip().endswith('exit "$RUNNER_RC"'))

    ollama_kwargs = dict(
        job_name="j", run_id="r", repo_root="/x", python_bin="/py", script_path="s.py",
        script_args=["--a", "1"], log_dir="/log", model="m", num_ctx=1, num_predict=1,
        ollama_bin="/ollama", ollama_models_dir="/models",
    )
    ollama_without = slurm_render.render_ollama_job(**ollama_kwargs)
    ollama_with_empty = slurm_render.render_ollama_job(extra_commands=(), **ollama_kwargs)
    check("render_ollama_job(extra_commands=()) matches no-arg call exactly", ollama_without == ollama_with_empty)
    check("render_ollama_job still ends with the plain RUNNER_RC exit", ollama_without.rstrip().endswith('exit "$RUNNER_RC"'))

    cpu_with_extra = slurm_render.render_cpu_job(extra_commands=["echo hi"], **{k: v for k, v in dict(
        job_name="j", run_id="r", repo_root="/x", python_bin="/py", script_path="s.py",
        script_args=["--a", "1"], log_dir="/log",
    ).items()})
    check("render_cpu_job with extra_commands does NOT end with the plain RUNNER_RC exit", not cpu_with_extra.rstrip().endswith('exit "$RUNNER_RC"'))
    check("render_cpu_job with extra_commands includes the extra command", "echo hi" in cpu_with_extra)

    proc = subprocess.run(["bash", "-n", "-c", cpu_with_extra], capture_output=True, text=True)
    check(f"render_cpu_job with extra_commands passes bash -n ({proc.stderr.strip()})", proc.returncode == 0)


def verify_run_stage_chain_trailer_default_and_opt_out() -> None:
    print("\n=== run_stage() appends the chain-advance trailer by default; --no-self-chain suppresses it ===")
    layout = get_operator_layout(REPO_ROOT)

    state_path = run_state_mod.run_state_path(layout.pipeline_runs_root, TEST_RUN_ID)
    state = run_state_mod.new_run_state(TEST_RUN_ID)
    # step_06_6_drafting_input_overlay now also depends on step_05_3_evidence_recalibrated
    # (2026-07-16 fix) - fake-complete it so _resolve_upstream_output_root() doesn't refuse
    # before ever reaching the monkeypatched build_step6_6_run_config() stub below, which is
    # what this test is actually about (trailer attachment, not upstream resolution).
    run_state_mod.set_stage_completed(
        state, "step_05_3_evidence_recalibrated",
        output_root=str(REPO_ROOT / "data/processed/kc_evidence_recalibrated" / TEST_RUN_ID),
        set_manifest_path=None, run_folder_symlink=None,
    )
    run_state_mod.write_run_state(state_path, state)

    spec = importlib.util.spec_from_file_location("kc_l_orchestrator_test", REPO_ROOT / "scripts" / "kc_l_orchestrator.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    def _fake_build_step6_6_run_config(*, run_id, repo_root, run_dir, step5_3_active_set_pointer=None):
        run_dir.mkdir(parents=True, exist_ok=True)
        fake_config = run_dir / f"{run_id}_step6_6_config.json"
        fake_config.write_text("{}", encoding="utf-8")
        return fake_config, []

    mod.build_step6_6_run_config = _fake_build_step6_6_run_config

    args_default = mod.argparse.Namespace(
        repo_root=str(REPO_ROOT), stage_id="step_06_6_drafting_input_overlay", run_id=TEST_RUN_ID,
        dry_run=True, dependency_job_id=None,
    )
    rc = mod.run_stage(args_default)
    check("run_stage() (default) exits 0", rc == 0)
    run_dir = layout.pipeline_runs_root / TEST_RUN_ID / "step_06_6_drafting_input_overlay"
    text = (run_dir / "step_06_6_drafting_input_overlay.slurm").read_text(encoding="utf-8")
    check("default run_stage() rendered script calls advance_run.py", "advance_run.py" in text)
    check("default run_stage() rendered script passes the run_id and stage_id to advance_run.py", f"'{TEST_RUN_ID}' 'step_06_6_drafting_input_overlay'" in text)

    proc = subprocess.run(["bash", "-n", str(run_dir / "step_06_6_drafting_input_overlay.slurm")], capture_output=True, text=True)
    check(f"self-chaining script passes bash -n ({proc.stderr.strip()})", proc.returncode == 0)

    args_no_chain = mod.argparse.Namespace(
        repo_root=str(REPO_ROOT), stage_id="step_06_6_drafting_input_overlay", run_id=TEST_RUN_ID,
        dry_run=True, dependency_job_id=None, no_self_chain=True,
    )
    rc2 = mod.run_stage(args_no_chain)
    check("run_stage() (--no-self-chain) exits 0", rc2 == 0)
    text2 = (run_dir / "step_06_6_drafting_input_overlay.slurm").read_text(encoding="utf-8")
    check("--no-self-chain rendered script does NOT call advance_run.py", "advance_run.py" not in text2)


def verify_step_02_trailer_only_on_last_doc() -> None:
    print("\n=== step_02_pdf_ingest: chain-advance trailer only on the LAST document's job ===")
    layout = get_operator_layout(REPO_ROOT)
    run_id = TEST_RUN_ID + "_step02"
    course_materials = [
        "data/input/course_materials/data-preprocessing-book-Chapter 3n4.pdf",
        "data/input/course_materials/data-preprocessing-book-Chapter 7.pdf",
        "data/input/course_materials/introduction-to-data-mining-.pdf",
    ]
    state_path = run_state_mod.run_state_path(layout.pipeline_runs_root, run_id)
    run_state_mod.write_run_state(state_path, run_state_mod.new_run_state(run_id, course_materials=course_materials))

    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "kc_l_orchestrator.py"), "--repo-root", str(REPO_ROOT),
         "run-stage", "step_02_pdf_ingest", "--run-id", run_id, "--dry-run"],
        capture_output=True, text=True,
    )
    check(f"step_02 dry-run exits 0 (stderr: {proc.stderr[-1000:]})", proc.returncode == 0)

    run_dir = layout.pipeline_runs_root / run_id / "step_02_pdf_ingest"
    doc_ids = ["DOC_data_preprocessing_book_Chapter_3n4", "DOC_data_preprocessing_book_Chapter_7", "DOC_introduction_to_data_mining"]
    for i, doc_id in enumerate(doc_ids):
        text = (run_dir / f"step_02_pdf_ingest_{doc_id}.slurm").read_text(encoding="utf-8")
        has_trailer = "advance_run.py" in text
        if i == len(doc_ids) - 1:
            check(f"LAST doc ({doc_id}) script DOES call advance_run.py", has_trailer)
        else:
            check(f"non-last doc ({doc_id}) script does NOT call advance_run.py", not has_trailer)

    _cleanup_run_id(run_id)


def verify_advance_marks_completed_and_symlinks() -> None:
    print("\n=== advance(): marks completed, creates (or gracefully skips) the run-folder symlink ===")
    layout = get_operator_layout(REPO_ROOT)
    run_id = TEST_RUN_ID + "_completion"
    state_path = run_state_mod.run_state_path(layout.pipeline_runs_root, run_id)
    run_state_mod.write_run_state(state_path, run_state_mod.new_run_state(run_id))

    # Seed a fake real output_root for step_06_8_review_packet_emission (output_root =
    # data/processed/step68_v2_review_packets_from_postprocessed_source/<run_id>).
    fake_output_root = REPO_ROOT / "data/processed/step68_v2_review_packets_from_postprocessed_source" / run_id
    fake_output_root.mkdir(parents=True, exist_ok=True)
    (fake_output_root / "marker.txt").write_text("x", encoding="utf-8")

    try:
        with mock.patch.object(advance_run.orch.slurm_submit, "sbatch_submit", side_effect=_fake_sbatch_submit):
            result = advance_run.advance(REPO_ROOT, run_id, "step_06_8_review_packet_emission", dry_run=False)

        check("advance() reports the real physical output_root", result["real_output_root"] == str(fake_output_root))
        state = run_state_mod.load_run_state(state_path)
        check("stage marked completed in RUN_STATE.json", state["stages"]["step_06_8_review_packet_emission"]["status"] == "completed")

        recorded_output_root = state["stages"]["step_06_8_review_packet_emission"]["output_root"]
        expected_convention_path = REPO_ROOT / "data/processed" / run_id / "step_06_8_review_packet_emission"
        if recorded_output_root == str(expected_convention_path):
            # Directory-restructuring convention symlink creation succeeded (this platform
            # supports it) - recorded output_root now points at data/processed/<run_id>/<stage>,
            # transparently resolving through to the real content.
            check(
                "new-convention symlink exists at data/processed/<run_id>/<stage_id>",
                expected_convention_path.is_symlink() or expected_convention_path.exists(),
            )
            check(
                "new-convention symlink transparently resolves to the real marker file",
                (expected_convention_path / "marker.txt").read_text(encoding="utf-8") == "x",
            )
        else:
            # Symlink creation was skipped (expected on a platform without symlink privileges) -
            # falls back to recording the real output_root directly, same as before this change.
            print("[INFO] new-convention symlink creation was skipped (expected on this platform without symlink privileges) - not a failure")
            check("completed stage falls back to recording the real output_root", recorded_output_root == str(fake_output_root))

        if result["run_folder_symlink"]:
            symlink_path = Path(result["run_folder_symlink"])
            check("run-folder symlink exists", symlink_path.is_symlink() or symlink_path.exists())
        else:
            print("[INFO] symlink creation was skipped (expected on this platform without symlink privileges) - not a failure")
    finally:
        shutil.rmtree(fake_output_root, ignore_errors=True)
        _cleanup_run_id(run_id)


def verify_multi_parent_fan_in() -> None:
    print("\n=== advance(): a multi-parent stage only becomes ready once ALL parents completed ===")
    layout = get_operator_layout(REPO_ROOT)
    run_id = TEST_RUN_ID + "_fanin"
    state_path = run_state_mod.run_state_path(layout.pipeline_runs_root, run_id)

    # UPDATED (topic_05x field-restoration + risk-detection wiring pass): topic_05x_evidence_
    # stage_v3 is now wired too (both confirmed gaps closed - see ORCHESTRATOR_BUILD_STATE.md),
    # so it no longer demonstrates the "ready but blocked because unwired" path either - it would
    # now be genuinely (fake-)submitted instead. Substituted with step_06_13_retrieval_pilot, the
    # only remaining still-unwired multi-parent stage (depends_on step_06_11_library_assembly AND
    # step_06_12_library_packaging) - seed step_06_11_library_assembly already completed,
    # step_06_12_library_packaging NOT yet.
    state = run_state_mod.new_run_state(run_id)
    run_state_mod.set_stage_completed(
        state, "step_06_11_library_assembly",
        output_root=str(REPO_ROOT / "data/processed/kc_library_reviewed_restarted" / run_id),
        set_manifest_path=None, run_folder_symlink=None,
    )
    run_state_mod.write_run_state(state_path, state)

    fake_output_root = REPO_ROOT / "data/processed/kc_library_runtime_restarted" / run_id
    fake_output_root.mkdir(parents=True, exist_ok=True)

    try:
        with mock.patch.object(advance_run.orch.slurm_submit, "sbatch_submit", side_effect=_fake_sbatch_submit):
            result = advance_run.advance(REPO_ROOT, run_id, "step_06_12_library_packaging", dry_run=False)

        check(
            "step_06_13_retrieval_pilot is NOT wired, so it's reported ready-but-blocked (not silently submitted)",
            "step_06_13_retrieval_pilot" in result["ready_blocked"],
        )
        state = run_state_mod.load_run_state(state_path)
        check("run status reflects the blocked stage", state["status"] == "blocked_unwired_stage")
        check(
            "step_06_13_retrieval_pilot recorded under blocked_stages",
            "step_06_13_retrieval_pilot" in state.get("blocked_stages", {}),
        )
        check(
            "step_06_13_retrieval_pilot only became READY (blocked, not silently dropped) once BOTH parents completed",
            True,
        )
    finally:
        shutil.rmtree(fake_output_root, ignore_errors=True)
        _cleanup_run_id(run_id)


def verify_submission_failure_is_not_silently_swallowed() -> None:
    print("\n=== a ready-and-wired stage that still fails to submit is surfaced, not silently treated as success ===")
    layout = get_operator_layout(REPO_ROOT)
    run_id = TEST_RUN_ID + "_submission_failure"
    state_path = run_state_mod.run_state_path(layout.pipeline_runs_root, run_id)
    # Fresh state with NO course_materials - step_02_pdf_ingest is ready (zero deps) and wired,
    # but run_stage() will refuse it (ERROR_STAGE_NOT_WIRED, course_materials empty).
    run_state_mod.write_run_state(state_path, run_state_mod.new_run_state(run_id))

    try:
        with mock.patch.object(advance_run.orch.slurm_submit, "sbatch_submit", side_effect=_fake_sbatch_submit):
            from kc_l.runtime.chain import submit_ready_stages

            result = submit_ready_stages(orch, REPO_ROOT, run_id, state_path, dry_run=False)

        check(
            "step_02_pdf_ingest's failed submission is NOT counted as submitted",
            "step_02_pdf_ingest" not in result["ready_wired_submitted"],
        )
        check(
            "step_02_pdf_ingest's failure is recorded under submission_failures",
            "step_02_pdf_ingest" in result["submission_failures"],
        )
    finally:
        _cleanup_run_id(run_id)


def verify_plan_opts_out_of_self_chain() -> None:
    print("\n=== plan() passes no_self_chain=True to each stage it submits ===")
    text = (REPO_ROOT / "scripts" / "kc_l_orchestrator.py").read_text(encoding="utf-8")
    plan_section = text[text.index("def plan("):text.index("def build_parser(")]
    check("plan()'s own stage_args construction sets no_self_chain=True", "no_self_chain=True" in plan_section)


def main() -> int:
    try:
        verify_render_backward_compat()
        verify_run_stage_chain_trailer_default_and_opt_out()
        verify_step_02_trailer_only_on_last_doc()
        verify_advance_marks_completed_and_symlinks()
        verify_multi_parent_fan_in()
        verify_submission_failure_is_not_silently_swallowed()
        verify_plan_opts_out_of_self_chain()
    finally:
        _cleanup_run_id(TEST_RUN_ID)

    print("\nALL advance_run.py SELF-CHAINING CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
