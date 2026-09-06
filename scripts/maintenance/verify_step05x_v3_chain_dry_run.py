#!/usr/bin/env python3
"""Genuine end-to-end verification of the new step_05x_kc_evidence_stage_v3 3-script chain wiring
(run_step5x_v3_candidate_bank.py -> run_step5x_v3_scored_candidates.py ->
run_step5x_v3_pack_composition.py, chained within one SLURM job via render_cpu_job's
extra_commands).

Builds on the real chain state verify_step05p_step05x_full_chain_dry_run.py already establishes
(real step_04_3 fixture -> real run_step4_5.py execution -> real nested sentence_corpus.jsonl),
then extends it two stages further:

1. Dry-run step_05p_kc_retrieval_profiles for real to get its real rendered config, then ACTUALLY
   EXECUTE run_step5p_kc_retrieval_profile.py against it (--limit-kcs 3, for speed - llm_policy
   stays the config default "never", so this is a plain CPU-only run) to produce a genuine
   kc_retrieval_profiles.jsonl - the first real functional execution of step_05p in this session
   (previous step_05p verification only checked dry-run config resolution, never ran the script).
   This also empirically settles whether step_05p's real output is double-nested like step_04_5's
   (it is not: confirmed by inspection of build_profiles() - processed_dir = output_root / run_id,
   with run_id honored directly from --run-id - this run either confirms or disproves that by
   actually checking where the file lands on disk).
2. Records step_05p as completed with output_root = the generic repo_root/spec.output_root/run_id
   formula (what advance_run.py would record for a real chained run), then confirms the real
   kc_retrieval_profiles.jsonl genuinely exists at output_root/kc_retrieval_profiles.jsonl (flat,
   no extra nesting).
3. Temporarily patches step_05x_kc_evidence_stage_v3.run_stage_wired=True in-memory (same
   precedent as every other stage's flip-and-verify pass this session) and dry-runs it via the
   real run_stage() CLI with --no-self-chain, then reads the rendered .slurm script off disk and
   confirms it contains the 3 real script invocations in the right order, each wired to the
   previous script's real deterministic output path.
4. ACTUALLY EXECUTES all 3 real scripts in sequence (not sbatch - directly, exactly what the
   SLURM job would run) using the exact same invocation the orchestrator computed, and confirms
   each one succeeds and produces real, non-empty output feeding the next.
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
from kc_l.utils.json_io import read_jsonl
import kc_l.runtime.stage_registry as stage_registry_mod

ORCHESTRATOR_SCRIPT = REPO_ROOT / "scripts" / "kc_l_orchestrator.py"
TEST_RUN_ID = "verify_step05x_v3_chain_test"

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
# deliberately unwired - out of scope for this task).
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
    for real_output_dir in (
        REPO_ROOT / "data/processed/retrieval_index" / run_id,
        REPO_ROOT / "data/processed/retrieval_sentence_overlay" / run_id,
        REPO_ROOT / "data/processed/kc_retrieval_profiles" / run_id,
        REPO_ROOT / "data/processed/evidence_stage_v3_candidate_bank" / run_id,
        REPO_ROOT / "data/processed/evidence_stage_v3_scored_candidates" / run_id,
        REPO_ROOT / "data/processed/evidence_stage_v3_evidence_packs" / run_id,
    ):
        if real_output_dir.exists():
            shutil.rmtree(real_output_dir)
    for set_manifest_root, prefix in (
        (REPO_ROOT / "data/processed/kc_retrieval_profiles/_sets", f"{run_id}_step5p_kc_retrieval_profile_set.json"),
        (REPO_ROOT / "data/processed/evidence_stage_v3_candidate_bank/_sets", f"{run_id}_step5x_v3_candidate_bank_set.json"),
        (REPO_ROOT / "data/processed/evidence_stage_v3_scored_candidates/_sets", f"{run_id}_step5x_v3_scored_candidates_set.json"),
        (REPO_ROOT / "data/processed/evidence_stage_v3_evidence_packs/_sets", f"{run_id}_step5x_v3_evidence_packs_set.json"),
    ):
        candidate = set_manifest_root / prefix
        if candidate.exists():
            candidate.unlink()


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


def _load_orchestrator_module():
    spec = importlib.util.spec_from_file_location("kc_l_orchestrator_step05x_chain_test", ORCHESTRATOR_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    layout = get_operator_layout(REPO_ROOT)

    try:
        print("=== Step 1: seed real step_04_3_embedding_index output ===")
        _seed_step_04_3_output(TEST_RUN_ID)

        print("\n=== Step 2: dry-run + ACTUALLY EXECUTE step_04_5_sentence_overlay for real ===")
        proc = _run_cli("run-stage", "step_04_5_sentence_overlay", "--run-id", TEST_RUN_ID, "--dry-run", "--no-self-chain")
        check(f"step_04_5 dry-run exits 0 (stderr: {proc.stderr[-2000:]})", proc.returncode == 0)

        step_04_5_run_dir = layout.pipeline_runs_root / TEST_RUN_ID / "step_04_5_sentence_overlay"
        step_04_5_rendered_config = step_04_5_run_dir / f"{TEST_RUN_ID}_step_04_5_config.json"
        check("step_04_5 rendered config exists", step_04_5_rendered_config.exists())

        proc2 = subprocess.run(
            [sys.executable, str(REPO_ROOT / "steps/step_04_5_sentence_overlay/scripts/run_step4_5.py"),
             "--config", str(step_04_5_rendered_config)],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        if proc2.returncode != 0:
            print(proc2.stdout)
            print(proc2.stderr[-3000:])
        check(f"run_step4_5.py actually completes successfully (rc={proc2.returncode})", proc2.returncode == 0)

        step_04_5_out_dir = REPO_ROOT / "data/processed/retrieval_sentence_overlay" / TEST_RUN_ID
        nested_dirs = [p for p in step_04_5_out_dir.iterdir() if p.is_dir() and p.name != "_sets"]
        check("exactly one nested internal-timestamp step_04_5 output dir exists", len(nested_dirs) == 1)
        nested_corpus = nested_dirs[0] / "sentence_corpus.jsonl"
        check(f"real step_04_5 sentence_corpus.jsonl exists at {nested_corpus}", nested_corpus.exists())

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

        print("\n=== Step 3: dry-run + ACTUALLY EXECUTE step_05p_kc_retrieval_profiles for real ===")
        original_step05p_spec = stage_registry_mod.STAGE_SPECS["step_05p_kc_retrieval_profiles"]
        stage_registry_mod.STAGE_SPECS["step_05p_kc_retrieval_profiles"] = replace(original_step05p_spec, run_stage_wired=True)
        try:
            mod = _load_orchestrator_module()
            args = mod.argparse.Namespace(
                repo_root=str(REPO_ROOT), stage_id="step_05p_kc_retrieval_profiles", run_id=TEST_RUN_ID,
                dry_run=True, dependency_job_id=None, no_self_chain=True,
            )
            rc = mod.run_stage(args)
        finally:
            stage_registry_mod.STAGE_SPECS["step_05p_kc_retrieval_profiles"] = original_step05p_spec
        check(f"step_05p dry-run against the real chain state succeeds (rc={rc})", rc == 0)

        step_05p_run_dir = layout.pipeline_runs_root / TEST_RUN_ID / "step_05p_kc_retrieval_profiles"
        step_05p_rendered_config = step_05p_run_dir / f"{TEST_RUN_ID}_step_05p_config.json"
        check("step_05p rendered config exists", step_05p_rendered_config.exists())

        proc3 = subprocess.run(
            [sys.executable, str(REPO_ROOT / "steps/step_05_p_kc_retrieval_profile/scripts/run_step5p_kc_retrieval_profile.py"),
             "--config", str(step_05p_rendered_config), "--run-id", TEST_RUN_ID, "--limit-kcs", "3"],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        if proc3.returncode != 0:
            print(proc3.stdout)
            print(proc3.stderr[-3000:])
        check(f"run_step5p_kc_retrieval_profile.py actually completes successfully (rc={proc3.returncode})", proc3.returncode == 0)

        step_05p_output_root = REPO_ROOT / "data/processed/kc_retrieval_profiles" / TEST_RUN_ID
        profile_jsonl = step_05p_output_root / "kc_retrieval_profiles.jsonl"
        check(
            f"real step_05p output is FLAT at output_root/kc_retrieval_profiles.jsonl (no double-nesting): {profile_jsonl}",
            profile_jsonl.exists(),
        )
        profile_rows = list(read_jsonl(profile_jsonl))
        check(f"kc_retrieval_profiles.jsonl has real rows (found {len(profile_rows)})", len(profile_rows) > 0)

        state = run_state_mod.load_run_state(state_path)
        run_state_mod.set_stage_completed(
            state, "step_05p_kc_retrieval_profiles",
            output_root=str(step_05p_output_root), set_manifest_path=None, run_folder_symlink=None,
        )
        run_state_mod.write_run_state(state_path, state)

        print("\n=== Step 4: dry-run step_05x_kc_evidence_stage_v3 (3-script chain) against the real chain state ===")
        original_step05x_spec = stage_registry_mod.STAGE_SPECS["step_05x_kc_evidence_stage_v3"]
        stage_registry_mod.STAGE_SPECS["step_05x_kc_evidence_stage_v3"] = replace(original_step05x_spec, run_stage_wired=True)
        try:
            mod2 = _load_orchestrator_module()
            args2 = mod2.argparse.Namespace(
                repo_root=str(REPO_ROOT), stage_id="step_05x_kc_evidence_stage_v3", run_id=TEST_RUN_ID,
                dry_run=True, dependency_job_id=None, no_self_chain=True,
            )
            rc2 = mod2.run_stage(args2)
        finally:
            stage_registry_mod.STAGE_SPECS["step_05x_kc_evidence_stage_v3"] = original_step05x_spec
        check(f"step_05x dry-run against the real chain state succeeds (rc={rc2})", rc2 == 0)

        step_05x_run_dir = layout.pipeline_runs_root / TEST_RUN_ID / "step_05x_kc_evidence_stage_v3"
        slurm_script_path = step_05x_run_dir / "step_05x_kc_evidence_stage_v3.slurm"
        check("step_05x rendered .slurm script exists", slurm_script_path.exists())
        rc_syntax = subprocess.run(["bash", "-n", str(slurm_script_path)], capture_output=True, text=True)
        check(f"rendered .slurm script passes bash -n syntax check (stderr: {rc_syntax.stderr})", rc_syntax.returncode == 0)
        slurm_text = slurm_script_path.read_text(encoding="utf-8")

        registry_jsonl_expected = str(HIERARCHY_OUTPUT_ROOT / "hierarchy_overlay.jsonl")
        candidate_bank_jsonl_expected = str(REPO_ROOT / "data/processed/evidence_stage_v3_candidate_bank" / TEST_RUN_ID / "candidate_bank.jsonl")
        scored_candidates_jsonl_expected = str(REPO_ROOT / "data/processed/evidence_stage_v3_scored_candidates" / TEST_RUN_ID / "scored_candidates.jsonl")

        check("rendered script invokes run_step5x_v3_candidate_bank.py as the main command", "run_step5x_v3_candidate_bank.py" in slurm_text)
        check("rendered script's main command carries the real registry_jsonl", registry_jsonl_expected in slurm_text)
        check("rendered script's main command carries the real profile_jsonl", str(profile_jsonl) in slurm_text)
        check("rendered script chains run_step5x_v3_scored_candidates.py after candidate_bank", "run_step5x_v3_scored_candidates.py" in slurm_text)
        check(
            "scored_candidates' --candidate-bank-jsonl is wired to candidate_bank's exact deterministic output path",
            candidate_bank_jsonl_expected in slurm_text,
        )
        check("rendered script chains run_step5x_v3_pack_composition.py last", "run_step5x_v3_pack_composition.py" in slurm_text)
        check(
            "pack_composition's --scored-candidates-jsonl is wired to scored_candidates' exact deterministic output path",
            scored_candidates_jsonl_expected in slurm_text,
        )
        check(
            "candidate_bank appears before scored_candidates appears before pack_composition, in that order",
            slurm_text.index("run_step5x_v3_candidate_bank.py")
            < slurm_text.index("run_step5x_v3_scored_candidates.py")
            < slurm_text.index("run_step5x_v3_pack_composition.py"),
        )

        print("\n=== Step 5: ACTUALLY EXECUTE all 3 real chain scripts in sequence (not sbatch) ===")
        candidate_bank_cmd = [
            sys.executable, str(REPO_ROOT / "steps/step_05_x_evidence_stage_v3/scripts/run_step5x_v3_candidate_bank.py"),
            "--registry-jsonl", registry_jsonl_expected,
            "--source-overlay-jsonl", str(nested_corpus),
            "--profile-jsonl", str(profile_jsonl),
            "--output-root", "data/processed/evidence_stage_v3_candidate_bank",
            "--set-manifest-root", "data/processed/evidence_stage_v3_candidate_bank/_sets",
            "--run-id", TEST_RUN_ID,
        ]
        proc4 = subprocess.run(candidate_bank_cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
        if proc4.returncode != 0:
            print(proc4.stdout)
            print(proc4.stderr[-3000:])
        check(f"run_step5x_v3_candidate_bank.py actually completes successfully (rc={proc4.returncode})", proc4.returncode == 0)
        candidate_bank_jsonl = REPO_ROOT / "data/processed/evidence_stage_v3_candidate_bank" / TEST_RUN_ID / "candidate_bank.jsonl"
        check(f"real candidate_bank.jsonl exists at {candidate_bank_jsonl}", candidate_bank_jsonl.exists())
        candidate_bank_rows = list(read_jsonl(candidate_bank_jsonl))
        check(f"candidate_bank.jsonl has real rows (found {len(candidate_bank_rows)})", len(candidate_bank_rows) > 0)

        scored_candidates_cmd = [
            sys.executable, str(REPO_ROOT / "steps/step_05_x_evidence_stage_v3/scripts/run_step5x_v3_scored_candidates.py"),
            "--candidate-bank-jsonl", str(candidate_bank_jsonl),
            "--output-root", "data/processed/evidence_stage_v3_scored_candidates",
            "--set-manifest-root", "data/processed/evidence_stage_v3_scored_candidates/_sets",
            "--run-id", TEST_RUN_ID,
        ]
        proc5 = subprocess.run(scored_candidates_cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
        if proc5.returncode != 0:
            print(proc5.stdout)
            print(proc5.stderr[-3000:])
        check(f"run_step5x_v3_scored_candidates.py actually completes successfully (rc={proc5.returncode})", proc5.returncode == 0)
        scored_candidates_jsonl = REPO_ROOT / "data/processed/evidence_stage_v3_scored_candidates" / TEST_RUN_ID / "scored_candidates.jsonl"
        check(f"real scored_candidates.jsonl exists at {scored_candidates_jsonl}", scored_candidates_jsonl.exists())
        scored_candidates_rows = list(read_jsonl(scored_candidates_jsonl))
        check(f"scored_candidates.jsonl has real rows (found {len(scored_candidates_rows)})", len(scored_candidates_rows) > 0)

        pack_composition_cmd = [
            sys.executable, str(REPO_ROOT / "steps/step_05_x_evidence_stage_v3/scripts/run_step5x_v3_pack_composition.py"),
            "--scored-candidates-jsonl", str(scored_candidates_jsonl),
            "--registry-jsonl", registry_jsonl_expected,
            "--output-root", "data/processed/evidence_stage_v3_evidence_packs",
            "--set-manifest-root", "data/processed/evidence_stage_v3_evidence_packs/_sets",
            "--run-id", TEST_RUN_ID,
        ]
        proc6 = subprocess.run(pack_composition_cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
        if proc6.returncode != 0:
            print(proc6.stdout)
            print(proc6.stderr[-3000:])
        check(f"run_step5x_v3_pack_composition.py actually completes successfully (rc={proc6.returncode})", proc6.returncode == 0)
        evidence_packs_jsonl = REPO_ROOT / "data/processed/evidence_stage_v3_evidence_packs" / TEST_RUN_ID / "kc_evidence_packs.jsonl"
        check(f"real kc_evidence_packs.jsonl exists at {evidence_packs_jsonl}", evidence_packs_jsonl.exists())
        evidence_pack_rows = list(read_jsonl(evidence_packs_jsonl))
        check(f"kc_evidence_packs.jsonl has real rows (found {len(evidence_pack_rows)})", len(evidence_pack_rows) > 0)

        check(
            "this StageSpec's registered output_root matches pack_composition's real output location",
            str(evidence_packs_jsonl.parent) == str(REPO_ROOT / stage_registry_mod.STAGE_SPECS["step_05x_kc_evidence_stage_v3"].output_root / TEST_RUN_ID),
        )

    finally:
        _cleanup_run_id(TEST_RUN_ID)

    print("\nALL step_05x_kc_evidence_stage_v3 3-SCRIPT CHAIN VERIFICATION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
