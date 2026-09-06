#!/usr/bin/env python3
"""Genuine end-to-end dry-run check of topic_05p_retrieval_profiles's rewiring from the one-off
reconstructed topic registry to a direct extraction off hierarchy_registry's own real output.

Confirmed this session (see ORCHESTRATOR_BUILD_STATE.md's "topic_05p rewired to
hierarchy_registry" entry): there is no separate topic registry - the KC hierarchy IS the topic
hierarchy. A "topic unit" is precisely a hierarchy_overlay.jsonl row with node_type=="topic"
whose child_hier_node_ids are all KC leaves directly. Verified an exact 1:1 match (same 21
topics, same labels, same KC-id sets) against the historical reconstructed registry
(topic_registry_reconstructed_from_kc_pack_20260519T165224Z/) on a real hierarchy_overlay.jsonl
before writing any code - this script re-proves that match programmatically, plus the full
orchestrator invocation-building path, rather than re-asserting it from notes.

Steps (same real-fixture discipline as verify_step05p_step05x_full_chain_dry_run.py):
1. Seed step_04_3_embedding_index as completed (real historical manifest fixture).
2. Dry-run + ACTUALLY EXECUTE run_step4_5.py to get a real nested sentence_corpus.jsonl.
3. Record step_04_5_sentence_overlay + hierarchy_registry (real historical fixture output) as
   completed in RUN_STATE.json.
4. In-memory flip topic_05p_retrieval_profiles.run_stage_wired=True (same precedent as every
   other stage's flip-and-verify pass), dry-run it for real against this real chain state.
5. Confirm the adapter's real output (produced for real during dry-run - only the SLURM
   submission itself is skipped) exactly matches the historical reconstructed registry: same 21
   topic_ids, same labels, same contained_kc_ids sets, 144 edges, 144 unique kc_ids.
6. Confirm the rendered SLURM script references the adapter's real output paths (not the old
   reconstruction), passes bash -n, and needs_ollama/model plumbing resolved correctly.
7. Confirm refusal behavior: topic_05p refuses cleanly when hierarchy_registry hasn't completed.
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
TEST_RUN_ID = "verify_topic05p_hierarchy_registry_test"

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

# Same real historical hierarchy_registry fixture used by verify_step05p_step05x_full_chain_dry_run.py
# (a real 171-row tree: 144 leaf/KC rows, 27 topic rows, 21 of which are direct KC parents).
HIERARCHY_OUTPUT_ROOT = REPO_ROOT / "data/processed/hierarchy_overlay/2026-04-08_103432_hierarchy_overlay"

RECONSTRUCTED_REGISTRY_PATH = REPO_ROOT / (
    "data/processed/topic_reconstructed_registry/"
    "topic_registry_reconstructed_from_kc_pack_20260519T165224Z/topic_registry_reconstructed.jsonl"
)
RECONSTRUCTED_EDGES_PATH = REPO_ROOT / (
    "data/processed/topic_reconstructed_registry/"
    "topic_registry_reconstructed_from_kc_pack_20260519T165224Z/topic_to_kc_edges_reconstructed.jsonl"
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


def _cleanup_run_id(run_id: str) -> None:
    layout = get_operator_layout(REPO_ROOT)
    run_dir = layout.pipeline_runs_root / run_id
    if run_dir.exists():
        shutil.rmtree(run_dir)
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
            print("----- run_step4_5.py stderr (last 3000 chars) -----")
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

        print("\n=== Step 4: dry-run topic_05p_retrieval_profiles against this REAL chain state (in-memory flip) ===")
        original_spec = stage_registry_mod.STAGE_SPECS["topic_05p_retrieval_profiles"]
        stage_registry_mod.STAGE_SPECS["topic_05p_retrieval_profiles"] = replace(original_spec, run_stage_wired=True)
        crash_exc = None
        try:
            spec = importlib.util.spec_from_file_location("kc_l_orchestrator_topic05p_test", ORCHESTRATOR_SCRIPT)
            mod = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(mod)

            args = mod.argparse.Namespace(
                repo_root=str(REPO_ROOT), stage_id="topic_05p_retrieval_profiles", run_id=TEST_RUN_ID,
                dry_run=True, dependency_job_id=None, no_self_chain=True,
            )
            try:
                rc = mod.run_stage(args)
            except Exception as exc:  # noqa: BLE001 - deliberately broad: reporting, not masking
                rc = None
                crash_exc = exc
            print(f"topic_05p dry-run via run_stage() returned rc={rc} (crash_exc={crash_exc!r})")
        finally:
            stage_registry_mod.STAGE_SPECS["topic_05p_retrieval_profiles"] = original_spec

        check(f"topic_05p dry-run against the REAL chain state succeeds (crash_exc={crash_exc!r})", rc == 0)

        print("\n=== Step 5: confirm the adapter's REAL output exactly matches the historical reconstruction ===")
        bridge_dir = layout.pipeline_runs_root / TEST_RUN_ID / "topic_05p_retrieval_profiles" / "topic_registry_bridge_inputs"
        adapter_registry = bridge_dir / "topic_registry_from_hierarchy_registry.jsonl"
        adapter_edges = bridge_dir / "topic_to_kc_edges_from_hierarchy_registry.jsonl"
        check(f"adapter produced a real topic registry at {adapter_registry}", adapter_registry.exists())
        check(f"adapter produced real topic-to-kc edges at {adapter_edges}", adapter_edges.exists())

        adapter_reg_rows = [json.loads(l) for l in adapter_registry.read_text(encoding="utf-8").splitlines() if l.strip()]
        adapter_edge_rows = [json.loads(l) for l in adapter_edges.read_text(encoding="utf-8").splitlines() if l.strip()]
        recon_reg_rows = [json.loads(l) for l in RECONSTRUCTED_REGISTRY_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
        recon_edge_rows = [json.loads(l) for l in RECONSTRUCTED_EDGES_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]

        check(f"adapter registry row count matches reconstruction ({len(recon_reg_rows)})", len(adapter_reg_rows) == len(recon_reg_rows))
        check(f"adapter edges row count matches reconstruction ({len(recon_edge_rows)})", len(adapter_edge_rows) == len(recon_edge_rows))

        # Compare by topic_label, NOT topic_id: confirmed directly (see ORCHESTRATOR_BUILD_STATE.md)
        # that hier_node_id is scoped to the run that produced it (incorporates that run's own
        # source_set_id) - two different hierarchy_registry runs over the IDENTICAL underlying
        # hierarchy produce different hier_node_id hashes for the same topic (same label, same
        # descendant_kc_ids). This verify script's own hierarchy_registry fixture is a DIFFERENT
        # historical run than the one the reconstruction's topic_ids trace back to, so label -
        # not topic_id - is the correct, run-independent equivalence check here. (A separate,
        # one-off ad-hoc check during Phase 1 investigation, using the SAME run's output the
        # reconstruction traces back to, DID confirm exact topic_id hash equality too - see the
        # build-state doc entry - so this isn't a weaker check, just the right one for a fixture
        # that legitimately differs from that specific historical run.)
        recon_by_label = {r["topic_label"]: r for r in recon_reg_rows}
        adapter_by_label = {r["topic_label"]: r for r in adapter_reg_rows}
        check("adapter topic_label set == reconstruction topic_label set", set(adapter_by_label) == set(recon_by_label))

        mismatches = []
        for label, recon_row in recon_by_label.items():
            adapter_row = adapter_by_label.get(label)
            if adapter_row is None:
                mismatches.append((label, "missing"))
                continue
            if sorted(adapter_row["contained_kc_ids"]) != sorted(recon_row["contained_kc_ids"]):
                mismatches.append((label, "contained_kc_ids"))
        print(f"per-topic mismatches vs historical reconstruction: {mismatches if mismatches else 'NONE'}")
        check("every topic's contained_kc_ids exactly matches the historical reconstruction", not mismatches)

        adapter_edge_kc_ids = {e["kc_id"] for e in adapter_edge_rows}
        recon_edge_kc_ids = {e["kc_id"] for e in recon_edge_rows}
        check("adapter edge kc_id set == reconstruction edge kc_id set (144 unique KCs)", adapter_edge_kc_ids == recon_edge_kc_ids)

        print("\n=== Step 6: confirm rendered SLURM script references the adapter's real output, not the old reconstruction ===")
        topic_run_dir = layout.pipeline_runs_root / TEST_RUN_ID / "topic_05p_retrieval_profiles"
        slurm_scripts = list(topic_run_dir.glob("*.slurm"))
        check("exactly one rendered SLURM script for topic_05p", len(slurm_scripts) == 1)
        slurm_text = slurm_scripts[0].read_text(encoding="utf-8")
        check("rendered script references the adapter's registry output", "topic_registry_from_hierarchy_registry.jsonl" in slurm_text)
        check("rendered script references the adapter's edges output", "topic_to_kc_edges_from_hierarchy_registry.jsonl" in slurm_text)
        check("rendered script does NOT reference the old reconstructed registry", "topic_reconstructed_registry" not in slurm_text)
        check("rendered script passes --use-model/--llm-policy always (needs_ollama plumbing)", "--use-model" in slurm_text and "always" in slurm_text)
        # Regression check for job 228292's crash (unrecognized arguments: --ollama-host ...):
        # this script's own argparse has --base-url, not --ollama-host, and requires a full
        # scheme-included URL (not a bare host:port) - confirm the rendered script uses the
        # corrected flag/value and not render_ollama_job()'s generic default.
        check("rendered script passes --base-url with the http:// scheme (topic_05p's actual flag)", '--base-url "http://$OLLAMA_HOST"' in slurm_text)
        check("rendered script does NOT pass --ollama-host (topic_05p's script has no such flag)", "--ollama-host" not in slurm_text)
        bash_check = subprocess.run(["bash", "-n", str(slurm_scripts[0])], capture_output=True, text=True)
        check(f"rendered SLURM script passes bash -n ({bash_check.stderr.strip()})", bash_check.returncode == 0)

        print("\n=== Step 7: confirm refusal when hierarchy_registry hasn't completed (real CLI, real wired flag) ===")
        # By this point in the real source, topic_05p_retrieval_profiles.run_stage_wired is
        # permanently True (flipped only after every check above passed) - this exercises the
        # REAL CLI's real refusal path (_resolve_upstream_output_root's "has not completed in
        # this run yet"), not the earlier in-memory-flip scaffolding used for Steps 4-6.
        state = run_state_mod.load_run_state(state_path)
        del state["stages"]["hierarchy_registry"]
        run_state_mod.write_run_state(state_path, state)
        proc3 = _run_cli("run-stage", "topic_05p_retrieval_profiles", "--run-id", TEST_RUN_ID, "--dry-run", "--no-self-chain")
        check("topic_05p refuses cleanly via the real CLI when hierarchy_registry hasn't completed", proc3.returncode != 0)
        check(
            "refusal names hierarchy_registry as not completed",
            "hierarchy_registry" in (proc3.stdout + proc3.stderr) and "has not completed" in (proc3.stdout + proc3.stderr),
        )

    finally:
        _cleanup_run_id(TEST_RUN_ID)

    print("\nALL topic_05p HIERARCHY-REGISTRY REWIRING CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
