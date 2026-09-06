#!/usr/bin/env python3
"""Plain-Python verification for Milestone 1 of the pipeline orchestrator (no pytest -
this must also be runnable on the HPC cluster, where pytest availability in the venv is unconfirmed).

Covers: stage_pointers (all 3 real pointer-file formats), slurm_render (bash -n syntax
validity for both templates, and the $OLLAMA_HOST quoting fix), and stage_registry
(internal consistency: every depends_on references a real stage_id, order is monotonic
with dependencies, no duplicate orders).

Does NOT touch slurm_submit (sbatch/sacct) - that module only makes sense against a real
SLURM scheduler and cannot be meaningfully verified on this dev checkout.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from kc_l.runtime import stage_pointers, stage_registry
from kc_l.runtime.slurm_render import render_cpu_job, render_ollama_job


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        raise SystemExit(f"Verification failed: {label}")


def verify_stage_pointers() -> None:
    print("\n=== stage_pointers ===")

    p1 = stage_pointers.resolve_pointer(REPO_ROOT / "data/processed/blockstore/_sets/ACTIVE_STEP2_SET.txt")
    check("format 1 (legacy filename-only) resolves and exists", p1.exists())
    check(
        "format 1 target name matches pointer content",
        p1.name == "2026-04-06_021401_step2_step2_set.json",
    )

    p2 = stage_pointers.resolve_pointer(
        REPO_ROOT / "data/processed/evidence_stage_v3_evidence_packs/_sets/"
        "BEST_STEP5X_FINAL_SANITIZED_GAPAWARE_SET.txt",
        require_exists=False,
    )
    check(
        "format 2 (absolute-path single-line) used verbatim, not joined with pointer dir",
        "evidence_stage_v3_evidence_packs" in str(p2) and "_sets" in str(p2),
    )

    p3 = stage_pointers.resolve_pointer(
        REPO_ROOT / "data/processed/step67_v2_postprocessed_review_source/_sets/"
        "BEST_STEP67_V2_POSTPROCESSED_REVIEW_SOURCE.txt",
        key="POSTPROCESSED_JSONL",
        require_exists=False,
    )
    check("format 3 (multi-line KEY=VALUE) extracts the requested key", p3.name == "step67_v2_postprocessed_review_source.jsonl")

    try:
        stage_pointers.resolve_pointer(
            REPO_ROOT / "data/processed/step67_v2_postprocessed_review_source/_sets/"
            "BEST_STEP67_V2_POSTPROCESSED_REVIEW_SOURCE.txt",
            require_exists=False,
        )
        check("format 3 without key= raises ValueError", False)
    except ValueError:
        check("format 3 without key= raises ValueError", True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        pointer_path = tmp_path / "_sets" / "ACTIVE_TEST_SET.txt"
        target_path = tmp_path / "some" / "real" / "target.json"
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text("{}", encoding="utf-8")

        written = stage_pointers.write_pointer(pointer_path, target_path)
        check("write_pointer creates the pointer file", written.exists())
        round_tripped = stage_pointers.resolve_pointer(pointer_path)
        check("write_pointer + resolve_pointer round-trips to the same target", round_tripped == target_path.resolve())


def verify_slurm_render() -> None:
    print("\n=== slurm_render ===")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        cpu_script = render_cpu_job(
            job_name="kc_verify_cpu",
            run_id="20260710T000000Z_verify",
            repo_root="/path/to/projects/kc_l_v2_clean",
            python_bin="/path/to/venvs/kc_l_v2/bin/python",
            script_path="steps/step_06_9_kc_review_audit_ingestion/scripts/run_step6_9_kc_review_audit_ingestion.py",
            script_args=["--config", "/some/generated/config.yaml"],
            log_dir="/path/to/projects/kc_l_v2_clean/data/processed/runs/x/step_06_9",
        )
        check(
            "cpu template sets the correct LD_LIBRARY_PATH",
            "/path/to/software/python/python-3.11.3/lib" in cpu_script,
        )
        cpu_path = tmp_path / "cpu.slurm"
        cpu_path.write_text(cpu_script, encoding="utf-8", newline="\n")
        proc = subprocess.run(["bash", "-n", str(cpu_path)], capture_output=True, text=True)
        check(f"cpu template passes bash -n ({proc.stderr.strip()})", proc.returncode == 0)

        ollama_script = render_ollama_job(
            job_name="kc_verify_ollama",
            run_id="20260710T000000Z_verify",
            repo_root="/path/to/projects/kc_l_v2_clean",
            python_bin="/path/to/venvs/kc_l_v2/bin/python",
            script_path="steps/step_06_7_kc_draft_generation/scripts/v2_chain/"
            "run_step67_v2_policy_segmentable_abstention_marker_fix.py",
            script_args=["--out-dir", "/some/out", "--run-id", "20260710T000000Z_verify"],
            log_dir="/path/to/projects/kc_l_v2_clean/data/processed/runs/x/step_06_7",
            model="gemma4:31b",
            num_ctx=65536,
            num_predict=16000,
            ollama_bin="/home/<YOUR_USERNAME>/apps/ollama_upgrade_clean_20260425_214752/bin/ollama",
            ollama_models_dir="/path/to/scratch/kc_l/ollama/models",
        )
        check(
            "ollama template sets the correct LD_LIBRARY_PATH",
            "/path/to/software/python/python-3.11.3/lib" in ollama_script,
        )
        check(
            "ollama template appends --ollama-host with double quotes (expands at runtime)",
            '--ollama-host "$OLLAMA_HOST"' in ollama_script,
        )
        check(
            "ollama template never single-quotes $OLLAMA_HOST (would break expansion)",
            "'$OLLAMA_HOST'" not in ollama_script,
        )
        ollama_path = tmp_path / "ollama.slurm"
        ollama_path.write_text(ollama_script, encoding="utf-8", newline="\n")
        proc = subprocess.run(["bash", "-n", str(ollama_path)], capture_output=True, text=True)
        check(f"ollama template passes bash -n ({proc.stderr.strip()})", proc.returncode == 0)


def verify_stage_registry() -> None:
    print("\n=== stage_registry ===")

    stage_ids = set(stage_registry.STAGE_SPECS.keys())
    check("stage_registry is non-empty", len(stage_ids) > 0)

    for stage_id, spec in stage_registry.STAGE_SPECS.items():
        for dep in spec.depends_on:
            check(f"{stage_id}: depends_on {dep!r} is a known stage_id", dep in stage_ids)
            dep_order = stage_registry.STAGE_SPECS[dep].order
            check(f"{stage_id}: depends_on {dep!r} has an earlier order ({dep_order} < {spec.order})", dep_order < spec.order)

    orders = [s.order for s in stage_registry.STAGE_SPECS.values()]
    check("stage_registry has no duplicate order values", len(orders) == len(set(orders)))

    ordered = stage_registry.ordered_stage_ids()
    check("ordered_stage_ids() returns every stage exactly once", set(ordered) == stage_ids and len(ordered) == len(stage_ids))

    unconfirmed = [s.stage_id for s in stage_registry.STAGE_SPECS.values() if not stage_registry.is_confirmed(s.stage_id)]
    print(f"  unconfirmed stages (expected, flagged deliberately): {unconfirmed}")
    # UPDATED (step_05x 3-script chain wiring pass): downstream_segmentation_evaluation is the
    # only stage left with invocation="unconfirmed" (no script at all). The step5p/5x +
    # topic5p/5x quartet this comment used to list here as cli_flags-unconfirmed is now stale -
    # is_confirmed() is about cli_flags_confirmed/invocation, a DIFFERENT axis from
    # run_stage_wired (whether upstream-input resolution is actually built): step_05p and
    # step_05x are now both cli_flags_confirmed=True AND run_stage_wired=True; topic_05p and
    # topic_05x are cli_flags_confirmed=True (their CLI contracts were confirmed via
    # src/kc_l/topic_5p5x/pipeline.py's parse_profile_args - see stage_registry.py's own notes)
    # but still run_stage_wired=False (topic-track wiring is separately out of scope for this
    # task) - is_confirmed() alone does not gate that. step_06_7_postprocessed_review_source was
    # resolved in Milestone 2 (new script written and empirically validated against the one real
    # historical run - see verify_step67_v2_postprocess_reconstruction.py) and is no longer
    # unconfirmed either.
    expected_unconfirmed = {
        "downstream_segmentation_evaluation",
    }
    check(
        "the known-unconfirmed stages are exactly the ones flagged this session",
        set(unconfirmed) == expected_unconfirmed,
    )


def main() -> int:
    verify_stage_pointers()
    verify_slurm_render()
    verify_stage_registry()
    print("\nALL MILESTONE 1 CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
