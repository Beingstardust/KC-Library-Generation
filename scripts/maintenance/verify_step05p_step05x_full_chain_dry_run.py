#!/usr/bin/env python3
"""Genuine end-to-end dry-run check of step_05p_kc_retrieval_profiles's wiring (and an explicit
investigation of step_05x_kc_evidence_stage_v3's own separate status), run with the
orchestrator's CURRENT state (steps 2 through 4.5 fully wired ahead of them).

This is the fix-verification follow-up to the bug confirmed in commit d4fe332:
step5p_hierarchy_registry_bridge.py's resolve_sentence_overlay_jsonl_from_output_root() assumed
step_04_5's real output was flat; it is not (run_step4_5.py's own choose_run_paths() nests it
under an internal timestamp run_id). The fix reads the stage's own self-written
ACTIVE_STEP4_5_SET.txt pointer + its set manifest's artifacts.sentence_corpus_jsonl field
instead of assuming a layout.

Unlike the earlier verify_step5p_dynamic_hierarchy_registry_resolution.py (which used a hand-
picked FLAT historical fixture directory for step_04_5's "sentence_overlay_output_root" stand-
in - the reason this bug was invisible for so long), this script produces REAL step_04_5 output
via the orchestrator's own real dynamic resolution + the real (bug-fixed) run_step4_5.py runner,
then checks whether step_05p's resolution helper actually finds it at the real location
run-stage's own bookkeeping would record - not a location chosen to make the resolver happy.

Steps:
1. Seed step_04_3_embedding_index as completed, using the real historical Step 4.3 manifest
   (localized to this checkout, same fixture already used for step_04_5's own bugfix/wiring
   verification).
2. Dry-run step_04_5_sentence_overlay via the real CLI to get its REAL rendered config (exact
   same dynamic-resolution code path a real run would use).
3. Actually EXECUTE run_step4_5.py against that rendered config (not via sbatch - just
   directly, since we're not on the HPC cluster - this is exactly what the SLURM job would run).
4. Record step_04_5_sentence_overlay as completed in RUN_STATE.json with output_root set to
   EXACTLY what advance_run.py's stage_output_root() would record for a real chained run
   (repo_root/spec.output_root/run_id) - not the deeper internal-timestamp subdirectory
   run_step4_5.py's own choose_run_paths() actually writes into.
5. Dry-run step_05p_kc_retrieval_profiles for real against this real chain state and confirm it
   NOW succeeds, resolving the real (nested) sentence_corpus.jsonl path via the fixed pointer-
   based resolution - not the old flat-path guess.
6. Investigate step_05x_kc_evidence_stage_v3 explicitly rather than assuming it's fine by
   extension of step_05p's fix - see the dedicated section below for what was found.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from kc_l.runtime import run_state as run_state_mod
from kc_l.runtime.layout import get_operator_layout
import kc_l.runtime.stage_registry as stage_registry_mod

ORCHESTRATOR_SCRIPT = REPO_ROOT / "scripts" / "kc_l_orchestrator.py"
TEST_RUN_ID = "verify_step05p_full_chain_test"

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

# Verification-only stand-in for hierarchy_registry's current-run output (that stage remains
# deliberately unwired - out of scope for this task - so a real historical output is used here
# purely so step_05p's OTHER real input (hierarchy_registry) resolves; only step_04_5's
# resolution is under test in this script).
HIERARCHY_OUTPUT_ROOT = REPO_ROOT / "data/processed/hierarchy_overlay/2026-04-08_103432_hierarchy_overlay"


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
    # Also clean up the REAL stage output directories this script actually writes real data
    # into (not just the runs/ bookkeeping dir) - otherwise a second run finds leftover
    # internal-timestamp subdirectories from the previous run and misreports "more than one".
    for real_output_dir in (
        REPO_ROOT / "data/processed/retrieval_index" / run_id,
        REPO_ROOT / "data/processed/retrieval_sentence_overlay" / run_id,
    ):
        if real_output_dir.exists():
            shutil.rmtree(real_output_dir)


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
    layout = get_operator_layout(REPO_ROOT)

    try:
        print("=== Step 1: seed real step_04_3_embedding_index output ===")
        _seed_step_04_3_output(TEST_RUN_ID)

        print("\n=== Step 2: dry-run step_04_5_sentence_overlay to get its REAL rendered config ===")
        proc = _run_cli("run-stage", "step_04_5_sentence_overlay", "--run-id", TEST_RUN_ID, "--dry-run", "--no-self-chain")
        check(f"step_04_5 dry-run exits 0 (stderr: {proc.stderr[-2000:]})", proc.returncode == 0)

        step_04_5_run_dir = layout.pipeline_runs_root / TEST_RUN_ID / "step_04_5_sentence_overlay"
        rendered_config_path = step_04_5_run_dir / f"{TEST_RUN_ID}_step_04_5_config.json"
        check("step_04_5 rendered config exists", rendered_config_path.exists())
        rendered_config = json.loads(rendered_config_path.read_text(encoding="utf-8"))
        step_04_5_out_dir = REPO_ROOT / "data/processed/retrieval_sentence_overlay" / TEST_RUN_ID
        check(
            "rendered config's outputs.processed_root is the orchestrator-scoped out_dir (what advance_run.py records)",
            rendered_config["outputs"]["processed_root"] == str(step_04_5_out_dir),
        )

        print("\n=== Step 3: ACTUALLY EXECUTE run_step4_5.py against that real rendered config ===")
        proc2 = subprocess.run(
            [sys.executable, str(REPO_ROOT / "steps/step_04_5_sentence_overlay/scripts/run_step4_5.py"),
             "--config", str(rendered_config_path)],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        print("----- run_step4_5.py stdout -----")
        print(proc2.stdout)
        if proc2.returncode != 0:
            print("----- run_step4_5.py stderr (last 3000 chars) -----")
            print(proc2.stderr[-3000:])
        check(f"run_step4_5.py actually completes successfully (rc={proc2.returncode})", proc2.returncode == 0)

        print(f"\nCONFIRMED REAL OUTPUT LAYOUT: sentence_corpus.jsonl does NOT live flat at {step_04_5_out_dir}")
        flat_candidate = step_04_5_out_dir / "sentence_corpus.jsonl"
        check(
            "sentence_corpus.jsonl is NOT flat at the orchestrator-scoped output_root (confirms the nested-internal-timestamp layout)",
            not flat_candidate.exists(),
        )
        # _sets is a sibling directory (outputs.sets_dir was overridden to out_dir/_sets, not
        # nested inside the internal-timestamp dir) - exclude it explicitly rather than assume
        # "the only subdirectory" is the internal-timestamp one.
        nested_dirs = [p for p in step_04_5_out_dir.iterdir() if p.is_dir() and p.name != "_sets"] if step_04_5_out_dir.exists() else []
        check("exactly one nested internal-timestamp subdirectory exists under the orchestrator output_root", len(nested_dirs) == 1)
        nested_corpus = nested_dirs[0] / "sentence_corpus.jsonl"
        check(f"the real sentence_corpus.jsonl actually lives nested at {nested_corpus}", nested_corpus.exists())

        print("\n=== Step 4: record step_04_5 completed in RUN_STATE.json, output_root = orchestrator-scoped dir ===")
        state_path = run_state_mod.run_state_path(layout.pipeline_runs_root, TEST_RUN_ID)
        state = run_state_mod.load_run_state(state_path)
        run_state_mod.set_stage_completed(
            state, "step_04_5_sentence_overlay",
            output_root=str(step_04_5_out_dir), set_manifest_path=None, run_folder_symlink=None,
        )
        run_state_mod.set_stage_completed(
            state, "hierarchy_registry",
            output_root=str(HIERARCHY_OUTPUT_ROOT), set_manifest_path=None, run_folder_symlink=None,
        )
        run_state_mod.write_run_state(state_path, state)

        print("\n=== Step 5: dry-run step_05p_kc_retrieval_profiles against this REAL chain state ===")
        # This verification runs BEFORE stage_registry.py's real run_stage_wired flag is
        # flipped (that only happens after this check passes) - temporarily flip it in-memory
        # for this process only, same precedent as the original
        # verify_step5p_dynamic_hierarchy_registry_resolution.py.
        original_spec = stage_registry_mod.STAGE_SPECS["step_05p_kc_retrieval_profiles"]
        stage_registry_mod.STAGE_SPECS["step_05p_kc_retrieval_profiles"] = replace(original_spec, run_stage_wired=True)
        try:
            spec = importlib.util.spec_from_file_location("kc_l_orchestrator_step05p_chain_test", ORCHESTRATOR_SCRIPT)
            mod = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(mod)

            args = mod.argparse.Namespace(
                repo_root=str(REPO_ROOT), stage_id="step_05p_kc_retrieval_profiles", run_id=TEST_RUN_ID,
                dry_run=True, dependency_job_id=None, no_self_chain=True,
            )
            try:
                rc = mod.run_stage(args)
                crash_exc = None
            except Exception as exc:  # noqa: BLE001 - deliberately broad: reporting, not masking
                rc = None
                crash_exc = exc
            print(f"step_05p dry-run via run_stage() returned rc={rc} (crash_exc={crash_exc!r})")
        finally:
            stage_registry_mod.STAGE_SPECS["step_05p_kc_retrieval_profiles"] = original_spec

        check(f"step_05p dry-run against the REAL chain state succeeds (crash_exc={crash_exc!r})", rc == 0)

        step_05p_run_dir = layout.pipeline_runs_root / TEST_RUN_ID / "step_05p_kc_retrieval_profiles"
        step_05p_rendered_config = step_05p_run_dir / f"{TEST_RUN_ID}_step_05p_config.json"
        check("step_05p rendered config exists", step_05p_rendered_config.exists())
        cfg = json.loads(step_05p_rendered_config.read_text(encoding="utf-8"))
        resolved_source_overlay = cfg.get("inputs", {}).get("source_overlay_jsonl")
        resolved_registry = cfg.get("inputs", {}).get("registry_jsonl")
        print(f"RESOLVED source_overlay_jsonl = {resolved_source_overlay}")
        print(f"RESOLVED registry_jsonl = {resolved_registry}")
        check(
            "resolved source_overlay_jsonl is the REAL nested file (not the old flat guess)",
            resolved_source_overlay == str(nested_corpus),
        )
        check(
            "resolved source_overlay_jsonl is NOT the old flat (wrong) path",
            resolved_source_overlay != str(flat_candidate),
        )

        print("\n=== Step 6: confirm step_05x_kc_evidence_stage_v3 is now wired (3-script chain) ===")
        # UPDATED (step_05x 3-script chain wiring pass): this used to assert step_05x had NO
        # _prepare_stage_invocation branch at all (a materially different, larger gap than
        # step_05p's resolution-path bug - see ORCHESTRATOR_BUILD_STATE.md). That gap is now
        # closed: run_step5x_v3_candidate_bank.py -> run_step5x_v3_scored_candidates.py ->
        # run_step5x_v3_pack_composition.py are chained within one SLURM job via
        # render_cpu_job's extra_commands. Full real end-to-end execution of all 3 scripts
        # (real 1262/1262/119 row counts) is separately covered by
        # verify_step05x_v3_chain_dry_run.py - this script's own remaining value is confirming
        # the branch + wired flag are both genuinely in place, not re-proving the whole chain.
        text = (REPO_ROOT / "scripts" / "kc_l_orchestrator.py").read_text(encoding="utf-8")
        has_branch = 'stage_id == "step_05x_kc_evidence_stage_v3"' in text
        print(f"_prepare_stage_invocation() has a step_05x branch: {has_branch}")
        check("step_05x_kc_evidence_stage_v3 now has a _prepare_stage_invocation branch", has_branch is True)
        step_05x_spec = stage_registry_mod.STAGE_SPECS["step_05x_kc_evidence_stage_v3"]
        check("step_05x_kc_evidence_stage_v3.run_stage_wired is now True", step_05x_spec.run_stage_wired is True)

    finally:
        _cleanup_run_id(TEST_RUN_ID)

    print("\nALL step_05p FIX-VERIFICATION + step_05x INVESTIGATION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
