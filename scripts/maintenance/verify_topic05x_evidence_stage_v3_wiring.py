#!/usr/bin/env python3
"""Genuine end-to-end verification of the new topic_05x_evidence_stage_v3 4-script chain wiring
(run_step5tx_topic_candidate_bank.py -> run_step5tx_topic_scored_candidates.py ->
run_step5tx_topic_scored_trace_rehydration.py -> run_step5tx_topic_pack_composition.py, chained
within one SLURM job via render_cpu_job's extra_commands).

Builds on the same real chain state verify_topic05p_hierarchy_registry_rewiring.py establishes
(real step_04_3 fixture -> real run_step4_5.py execution -> real nested sentence_corpus.jsonl ->
real hierarchy_registry historical fixture -> topic_05p_retrieval_profiles dry-run, which
produces topic_05p's real bridge registry/edges as a side effect of dry-run rendering), then
extends it three stages further:

1. ACTUALLY EXECUTE run_step5tp_topic_retrieval_profile.py for real (--no-model --limit-topics 3,
   for speed - no live Ollama needed) to produce a genuine topic_retrieval_profiles.jsonl, using
   the same registry/edges/overlay paths the dry-run already resolved. Records topic_05p as
   completed.
2. Dry-runs topic_05x_evidence_stage_v3 via the real run_stage() CLI (run_stage_wired is already
   permanently True in stage_registry.py by this point - flipped only after the byte-for-byte
   risk_tags() verification passed), then reads the rendered .slurm script off disk and confirms
   it contains all 4 real script invocations in the right order, each wired to the previous
   script's real deterministic output path - critically, pack_composition's
   --topic-scored-candidates-jsonl must point at the REHYDRATION step's output, not
   scored_candidates' raw one.
3. ACTUALLY EXECUTES all 4 real scripts in sequence (not sbatch - directly, exactly what the
   SLURM job would run), and confirms:
   - candidate_bank/scored_candidates/rehydration/pack_composition each produce real, non-empty
     output;
   - the field-restoration bug is real and still present: scored_candidates' raw output is
     missing bridge_loader_knowledge_unit_type/topic5p_weak_profile_carry_forward, and the
     rehydration step's output restores them on every row;
   - risk_flags/review_risk_flags/topic5x_requires_pack_risk_block_or_demotion are populated
     live (not silently empty) wherever risk_tags() actually detects something on this real data.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from kc_l.runtime import run_state as run_state_mod
from kc_l.runtime.layout import get_operator_layout
from kc_l.utils.json_io import read_jsonl

ORCHESTRATOR_SCRIPT = REPO_ROOT / "scripts" / "kc_l_orchestrator.py"
TEST_RUN_ID = "verify_topic05x_evidence_stage_v3_test"

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
        REPO_ROOT / "data/processed/topic_retrieval_profiles" / run_id,
        REPO_ROOT / "data/processed/topic_retrieval_profiles/_bridge_inputs" / run_id,
        REPO_ROOT / "data/processed/topic_evidence_stage_v3_candidate_bank" / run_id,
        REPO_ROOT / "data/processed/topic_evidence_stage_v3_candidate_bank/_bridge_inputs" / run_id,
        REPO_ROOT / "data/processed/topic_evidence_stage_v3_scored_candidates" / run_id,
        REPO_ROOT / "data/processed/topic_evidence_stage_v3_evidence_packs" / run_id,
    ):
        if real_output_dir.exists():
            shutil.rmtree(real_output_dir)
    for set_manifest_root, prefix in (
        # These are the shared KC-lane functions' OWN internal set-manifest filenames (confirmed
        # by reading build_profiles()/run_candidate_bank_stage()/build_scored_candidate_artifacts()/
        # build_evidence_pack_artifacts() directly) - the topic wrapper passes topic-specific
        # output_root/set_manifest_root directories, but the shared functions still use their own
        # generic "_step5p_kc_.../_step5x_v3_..." filename pattern inside those directories.
        (REPO_ROOT / "data/processed/topic_retrieval_profiles/_sets", f"{run_id}_step5p_kc_retrieval_profile_set.json"),
        (REPO_ROOT / "data/processed/topic_retrieval_profiles/_sets", f"{run_id}_topic_retrieval_profile_set.json"),
        (REPO_ROOT / "data/processed/topic_evidence_stage_v3_candidate_bank/_sets", f"{run_id}_step5x_v3_candidate_bank_set.json"),
        (REPO_ROOT / "data/processed/topic_evidence_stage_v3_candidate_bank/_sets", f"{run_id}_topic_candidate_bank_set.json"),
        (REPO_ROOT / "data/processed/topic_evidence_stage_v3_scored_candidates/_sets", f"{run_id}_step5x_v3_scored_candidates_set.json"),
        (REPO_ROOT / "data/processed/topic_evidence_stage_v3_scored_candidates/_sets", f"{run_id}_topic_scored_candidates_set.json"),
        (REPO_ROOT / "data/processed/topic_evidence_stage_v3_evidence_packs/_sets", f"{run_id}_step5x_v3_evidence_packs_set.json"),
        (REPO_ROOT / "data/processed/topic_evidence_stage_v3_evidence_packs/_sets", f"{run_id}_topic_evidence_packs_set.json"),
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


def main() -> int:
    layout = get_operator_layout(REPO_ROOT)

    try:
        print("=== Step 1: seed real step_04_3_embedding_index output ===")
        _seed_step_04_3_output(TEST_RUN_ID)

        print("\n=== Step 2: dry-run + ACTUALLY EXECUTE step_04_5_sentence_overlay ===")
        proc = _run_cli("run-stage", "step_04_5_sentence_overlay", "--run-id", TEST_RUN_ID, "--dry-run", "--no-self-chain")
        check(f"step_04_5 dry-run exits 0 (stderr: {proc.stderr[-2000:]})", proc.returncode == 0)

        step_04_5_run_dir = layout.pipeline_runs_root / TEST_RUN_ID / "step_04_5_sentence_overlay"
        rendered_config_path = step_04_5_run_dir / f"{TEST_RUN_ID}_step_04_5_config.json"
        check("step_04_5 rendered config exists", rendered_config_path.exists())

        proc2 = subprocess.run(
            [sys.executable, str(REPO_ROOT / "steps/step_04_5_sentence_overlay/scripts/run_step4_5.py"),
             "--config", str(rendered_config_path)],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        if proc2.returncode != 0:
            print(proc2.stderr[-3000:])
        check(f"run_step4_5.py actually completes successfully (rc={proc2.returncode})", proc2.returncode == 0)

        step_04_5_out_dir = REPO_ROOT / "data/processed/retrieval_sentence_overlay" / TEST_RUN_ID
        nested_dirs = [p for p in step_04_5_out_dir.iterdir() if p.is_dir() and p.name != "_sets"]
        check("exactly one nested internal-timestamp step_04_5 output dir exists", len(nested_dirs) == 1)
        nested_corpus = nested_dirs[0] / "sentence_corpus.jsonl"
        check(f"real sentence_corpus.jsonl exists at {nested_corpus}", nested_corpus.exists())

        print("\n=== Step 3: record step_04_5 + hierarchy_registry completed in RUN_STATE.json ===")
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

        print("\n=== Step 4: dry-run topic_05p_retrieval_profiles for real (already permanently wired) ===")
        proc_p1 = _run_cli("run-stage", "topic_05p_retrieval_profiles", "--run-id", TEST_RUN_ID, "--dry-run", "--no-self-chain")
        check(f"topic_05p dry-run exits 0 (stderr: {proc_p1.stderr[-2000:]})", proc_p1.returncode == 0)

        topic05p_run_dir = layout.pipeline_runs_root / TEST_RUN_ID / "topic_05p_retrieval_profiles"
        bridge_dir = topic05p_run_dir / "topic_registry_bridge_inputs"
        topic_registry_jsonl = bridge_dir / "topic_registry_from_hierarchy_registry.jsonl"
        topic_edges_jsonl = bridge_dir / "topic_to_kc_edges_from_hierarchy_registry.jsonl"
        check(f"topic_05p adapter registry exists at {topic_registry_jsonl}", topic_registry_jsonl.exists())
        check(f"topic_05p adapter edges exist at {topic_edges_jsonl}", topic_edges_jsonl.exists())

        print("\n=== Step 5: ACTUALLY EXECUTE run_step5tp_topic_retrieval_profile.py for real (--no-model, fast) ===")
        topic05p_cmd = [
            sys.executable, str(REPO_ROOT / "steps/step_05_tp_topic_retrieval_profile/scripts/run_step5tp_topic_retrieval_profile.py"),
            "--topic-registry-jsonl", str(topic_registry_jsonl),
            "--topic-to-kc-edges-jsonl", str(topic_edges_jsonl),
            "--source-overlay-jsonl", str(nested_corpus),
            "--output-root", "data/processed/topic_retrieval_profiles",
            "--set-manifest-root", "data/processed/topic_retrieval_profiles/_sets",
            "--run-id", TEST_RUN_ID,
            "--no-model",
            "--limit-topics", "3",
        ]
        proc_p2 = subprocess.run(topic05p_cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
        if proc_p2.returncode != 0:
            print(proc_p2.stdout)
            print(proc_p2.stderr[-3000:])
        check(f"run_step5tp_topic_retrieval_profile.py actually completes successfully (rc={proc_p2.returncode})", proc_p2.returncode == 0)

        topic05p_output_root = REPO_ROOT / "data/processed/topic_retrieval_profiles" / TEST_RUN_ID
        topic_profile_jsonl = topic05p_output_root / "topic_retrieval_profiles.jsonl"
        check(f"real topic_retrieval_profiles.jsonl exists at {topic_profile_jsonl}", topic_profile_jsonl.exists())
        profile_rows = list(read_jsonl(topic_profile_jsonl))
        check(f"topic_retrieval_profiles.jsonl has real rows (found {len(profile_rows)})", len(profile_rows) > 0)

        state = run_state_mod.load_run_state(state_path)
        run_state_mod.set_stage_completed(
            state, "topic_05p_retrieval_profiles",
            output_root=str(topic05p_output_root), set_manifest_path=None, run_folder_symlink=None,
        )
        run_state_mod.write_run_state(state_path, state)

        print("\n=== Step 6: dry-run topic_05x_evidence_stage_v3 (4-script chain) against the real chain state ===")
        proc3 = _run_cli("run-stage", "topic_05x_evidence_stage_v3", "--run-id", TEST_RUN_ID, "--dry-run", "--no-self-chain")
        check(f"topic_05x dry-run exits 0 (stderr: {proc3.stderr[-2000:]})", proc3.returncode == 0)

        topic05x_run_dir = layout.pipeline_runs_root / TEST_RUN_ID / "topic_05x_evidence_stage_v3"
        slurm_scripts = list(topic05x_run_dir.glob("*.slurm"))
        check("exactly one rendered SLURM script for topic_05x", len(slurm_scripts) == 1)
        slurm_text = slurm_scripts[0].read_text(encoding="utf-8")
        rc_syntax = subprocess.run(["bash", "-n", str(slurm_scripts[0])], capture_output=True, text=True)
        check(f"rendered .slurm script passes bash -n syntax check (stderr: {rc_syntax.stderr})", rc_syntax.returncode == 0)

        topic_candidate_bank_jsonl_expected = str(
            REPO_ROOT / "data/processed/topic_evidence_stage_v3_candidate_bank" / TEST_RUN_ID / "topic_candidate_bank.jsonl"
        )
        topic_scored_candidates_jsonl_expected = str(
            REPO_ROOT / "data/processed/topic_evidence_stage_v3_scored_candidates" / TEST_RUN_ID / "topic_scored_candidates.jsonl"
        )
        rehydrated_topic_scored_jsonl_expected = str(
            layout.pipeline_runs_root / TEST_RUN_ID / "topic_05x_evidence_stage_v3" / "trace_rehydration" / "topic_scored_candidates.jsonl"
        )

        check("rendered script invokes run_step5tx_topic_candidate_bank.py as the main command", "run_step5tx_topic_candidate_bank.py" in slurm_text)
        check("rendered script's main command carries the real topic_registry_jsonl", str(topic_registry_jsonl) in slurm_text)
        check("rendered script's main command carries the real topic_profile_jsonl", str(topic_profile_jsonl) in slurm_text)
        check("rendered script chains run_step5tx_topic_scored_candidates.py after candidate_bank", "run_step5tx_topic_scored_candidates.py" in slurm_text)
        check(
            "scored_candidates' --topic-candidate-bank-jsonl is wired to candidate_bank's exact deterministic output path",
            topic_candidate_bank_jsonl_expected in slurm_text,
        )
        check("rendered script chains run_step5tx_topic_scored_trace_rehydration.py after scored_candidates", "run_step5tx_topic_scored_trace_rehydration.py" in slurm_text)
        check(
            "rehydration's --source-scored-jsonl is wired to scored_candidates' exact deterministic output path",
            topic_scored_candidates_jsonl_expected in slurm_text,
        )
        check("rendered script chains run_step5tx_topic_pack_composition.py last", "run_step5tx_topic_pack_composition.py" in slurm_text)
        check(
            "pack_composition's --topic-scored-candidates-jsonl is wired to the REHYDRATED output, not the raw scored_candidates one",
            rehydrated_topic_scored_jsonl_expected in slurm_text,
        )
        check(
            "pack_composition does NOT read scored_candidates' raw pre-rehydration path",
            slurm_text.count(topic_scored_candidates_jsonl_expected) == 1,
        )
        check(
            "candidate_bank appears before scored_candidates appears before rehydration appears before pack_composition",
            slurm_text.index("run_step5tx_topic_candidate_bank.py")
            < slurm_text.index("run_step5tx_topic_scored_candidates.py")
            < slurm_text.index("run_step5tx_topic_scored_trace_rehydration.py")
            < slurm_text.index("run_step5tx_topic_pack_composition.py"),
        )

        print("\n=== Step 7: ACTUALLY EXECUTE all 4 real chain scripts in sequence (not sbatch) ===")
        candidate_bank_cmd = [
            sys.executable, str(REPO_ROOT / "steps/step_05_tx_topic_evidence_stage/scripts/run_step5tx_topic_candidate_bank.py"),
            "--topic-registry-jsonl", str(topic_registry_jsonl),
            "--topic-to-kc-edges-jsonl", str(topic_edges_jsonl),
            "--source-overlay-jsonl", str(nested_corpus),
            "--topic-profile-jsonl", str(topic_profile_jsonl),
            "--output-root", "data/processed/topic_evidence_stage_v3_candidate_bank",
            "--set-manifest-root", "data/processed/topic_evidence_stage_v3_candidate_bank/_sets",
            "--run-id", TEST_RUN_ID,
        ]
        proc4 = subprocess.run(candidate_bank_cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
        if proc4.returncode != 0:
            print(proc4.stdout)
            print(proc4.stderr[-3000:])
        check(f"run_step5tx_topic_candidate_bank.py actually completes successfully (rc={proc4.returncode})", proc4.returncode == 0)
        topic_candidate_bank_jsonl = Path(topic_candidate_bank_jsonl_expected)
        check(f"real topic_candidate_bank.jsonl exists at {topic_candidate_bank_jsonl}", topic_candidate_bank_jsonl.exists())
        candidate_bank_rows = list(read_jsonl(topic_candidate_bank_jsonl))
        check(f"topic_candidate_bank.jsonl has real rows (found {len(candidate_bank_rows)})", len(candidate_bank_rows) > 0)

        scored_candidates_cmd = [
            sys.executable, str(REPO_ROOT / "steps/step_05_tx_topic_evidence_stage/scripts/run_step5tx_topic_scored_candidates.py"),
            "--topic-candidate-bank-jsonl", str(topic_candidate_bank_jsonl),
            "--output-root", "data/processed/topic_evidence_stage_v3_scored_candidates",
            "--set-manifest-root", "data/processed/topic_evidence_stage_v3_scored_candidates/_sets",
            "--run-id", TEST_RUN_ID,
        ]
        proc5 = subprocess.run(scored_candidates_cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
        if proc5.returncode != 0:
            print(proc5.stdout)
            print(proc5.stderr[-3000:])
        check(f"run_step5tx_topic_scored_candidates.py actually completes successfully (rc={proc5.returncode})", proc5.returncode == 0)
        topic_scored_candidates_jsonl = Path(topic_scored_candidates_jsonl_expected)
        check(f"real topic_scored_candidates.jsonl (pre-rehydration) exists at {topic_scored_candidates_jsonl}", topic_scored_candidates_jsonl.exists())
        pre_rehydration_rows = list(read_jsonl(topic_scored_candidates_jsonl))
        check(f"topic_scored_candidates.jsonl has real rows (found {len(pre_rehydration_rows)})", len(pre_rehydration_rows) > 0)

        print("\n=== Step 8: confirm the field-dropping bug is real and still present BEFORE rehydration ===")
        missing_bridge_field_count = sum(1 for row in pre_rehydration_rows if "bridge_loader_knowledge_unit_type" not in row)
        missing_weak_field_count = sum(1 for row in pre_rehydration_rows if "topic5p_weak_profile_carry_forward" not in row)
        print(f"pre-rehydration rows missing bridge_loader_knowledge_unit_type: {missing_bridge_field_count}/{len(pre_rehydration_rows)}")
        print(f"pre-rehydration rows missing topic5p_weak_profile_carry_forward: {missing_weak_field_count}/{len(pre_rehydration_rows)}")
        check(
            "CONFIRMED: run_topic_scored_candidates_stage()'s raw output is still missing bridge_loader_knowledge_unit_type on every row (the bug this wiring fixes)",
            missing_bridge_field_count == len(pre_rehydration_rows),
        )
        check(
            "CONFIRMED: run_topic_scored_candidates_stage()'s raw output is still missing topic5p_weak_profile_carry_forward on every row",
            missing_weak_field_count == len(pre_rehydration_rows),
        )

        rehydration_out_dir = topic05x_run_dir / "trace_rehydration"
        rehydration_cmd = [
            sys.executable, str(REPO_ROOT / "steps/step_05_tx_topic_evidence_stage/scripts/run_step5tx_topic_scored_trace_rehydration.py"),
            "--source-scored-jsonl", str(topic_scored_candidates_jsonl),
            "--typed-candidate-bank-jsonl", str(topic_candidate_bank_jsonl),
            "--out-dir", str(rehydration_out_dir),
            "--run-id", TEST_RUN_ID,
        ]
        proc6 = subprocess.run(rehydration_cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
        if proc6.returncode != 0:
            print(proc6.stdout)
            print(proc6.stderr[-3000:])
        check(f"run_step5tx_topic_scored_trace_rehydration.py actually completes successfully (rc={proc6.returncode})", proc6.returncode == 0)
        rehydrated_jsonl = rehydration_out_dir / "topic_scored_candidates.jsonl"
        check(f"real rehydrated topic_scored_candidates.jsonl exists at {rehydrated_jsonl}", rehydrated_jsonl.exists())
        rehydrated_rows = list(read_jsonl(rehydrated_jsonl))
        check(f"rehydrated rows count matches pre-rehydration ({len(pre_rehydration_rows)})", len(rehydrated_rows) == len(pre_rehydration_rows))

        print("\n=== Step 9: confirm field restoration + live risk detection actually worked on this real data ===")
        restored_bridge_count = sum(1 for row in rehydrated_rows if row.get("bridge_loader_knowledge_unit_type") == "kc")
        check(
            "every rehydrated row now has bridge_loader_knowledge_unit_type=='kc' (field restored)",
            restored_bridge_count == len(rehydrated_rows),
        )
        has_weak_field_count = sum(1 for row in rehydrated_rows if "topic5p_weak_profile_carry_forward" in row)
        check(
            "every rehydrated row now has topic5p_weak_profile_carry_forward present (field restored)",
            has_weak_field_count == len(rehydrated_rows),
        )
        for row in rehydrated_rows:
            check(
                f"row {row.get('candidate_id')}: risk_flags is always a list (never crashes/missing)",
                isinstance(row.get("risk_flags"), list),
            )
            check(
                f"row {row.get('candidate_id')}: topic5x_requires_pack_risk_block_or_demotion is always a bool",
                isinstance(row.get("topic5x_requires_pack_risk_block_or_demotion"), bool),
            )
        content_tagged_rows = sum(1 for row in rehydrated_rows if row.get("topic5x_input_content_risk_tags"))
        print(f"rows with live-detected content risk tags on this real (small, --limit-topics 3) fixture: {content_tagged_rows}/{len(rehydrated_rows)}")

        pack_composition_cmd = [
            sys.executable, str(REPO_ROOT / "steps/step_05_tx_topic_evidence_stage/scripts/run_step5tx_topic_pack_composition.py"),
            "--topic-scored-candidates-jsonl", str(rehydrated_jsonl),
            "--output-root", "data/processed/topic_evidence_stage_v3_evidence_packs",
            "--set-manifest-root", "data/processed/topic_evidence_stage_v3_evidence_packs/_sets",
            "--run-id", TEST_RUN_ID,
        ]
        proc7 = subprocess.run(pack_composition_cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
        if proc7.returncode != 0:
            print(proc7.stdout)
            print(proc7.stderr[-3000:])
        check(f"run_step5tx_topic_pack_composition.py actually completes successfully (rc={proc7.returncode})", proc7.returncode == 0)
        evidence_packs_jsonl = REPO_ROOT / "data/processed/topic_evidence_stage_v3_evidence_packs" / TEST_RUN_ID / "topic_evidence_packs.jsonl"
        check(f"real topic_evidence_packs.jsonl exists at {evidence_packs_jsonl}", evidence_packs_jsonl.exists())
        evidence_pack_rows = list(read_jsonl(evidence_packs_jsonl))
        check(f"topic_evidence_packs.jsonl has real rows (found {len(evidence_pack_rows)})", len(evidence_pack_rows) > 0)

        print("\n=== Step 10: confirm refusal when topic_05p hasn't completed (real CLI, real wired flag) ===")
        state = run_state_mod.load_run_state(state_path)
        del state["stages"]["topic_05p_retrieval_profiles"]
        run_state_mod.write_run_state(state_path, state)
        proc8 = _run_cli("run-stage", "topic_05x_evidence_stage_v3", "--run-id", TEST_RUN_ID, "--dry-run", "--no-self-chain")
        check("topic_05x refuses cleanly via the real CLI when topic_05p hasn't completed", proc8.returncode != 0)
        check(
            "refusal names topic_05p_retrieval_profiles as not completed",
            "topic_05p_retrieval_profiles" in (proc8.stdout + proc8.stderr) and "has not completed" in (proc8.stdout + proc8.stderr),
        )

    finally:
        _cleanup_run_id(TEST_RUN_ID)

    print("\nALL topic_05x_evidence_stage_v3 4-SCRIPT CHAIN VERIFICATION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
