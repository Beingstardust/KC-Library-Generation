#!/usr/bin/env python3
"""Verify scripts/kc_l_orchestrator.py's run-stage wiring for the Milestone 4
steps-2-through-4.5 architectural-fork resolution: step_02_pdf_ingest (multi-invocation,
serially chained), step_03_doctree_index, step_03_5_blockstore_cleanup, step_03_6_math_salvage
(single-invocation, self-contained ACTIVE-pointer stages), step_04_patches (single invocation
but with a chained in-job freeze-script command discovering run_step4.py's own internal
timestamp run_id via a bash-level glob), and the follow-up step_04_3 embedding fix (dynamic
Ollama host passed through to the real script invocation plus the chained index-freeze command).

Covers:
- step_02: real 3-document course_materials (the actual course-material PDFs in this
  checkout) seeded into RUN_STATE.json renders 3 correctly-ordered, doc_id-correct SLURM
  scripts, each bash -n clean; refuses cleanly when course_materials is empty.
- step_03/3.5/3.6: dry-run renders correctly against a seeded (schema-accurate, since no real
  historical fixture for these stages exists in this local checkout - unlike step_02, which
  does have one) predecessor state, bash -n clean, refuses cleanly without a completed
  predecessor.
- step_04_patches: dry-run renders correctly, including the glob-discovery + freeze-script
  extra_commands block, bash -n clean (this is the important check - it validates the
  hand-written bash snippet is syntactically valid, not just that Python built a string),
  refuses cleanly without course_materials or without a completed predecessor.
- step_04_3_embedding_index: dry-run renders correctly against seeded current-run predecessor
  state, the SLURM script includes render_ollama_job()'s dynamic --ollama-host wiring plus the
  chained freeze_step4_index_set_actual_corpus.py command, bash -n clean. step_04_5_sentence_
  overlay is now wired too (its own runner bugs fixed separately) - see the dedicated
  scripts/maintenance/verify_orchestrator_run_stage_step_04_5.py, not covered in this file.

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
TEST_RUN_ID = "verify_steps_02_04_patches_test"

REAL_COURSE_MATERIALS = [
    "data/input/course_materials/data-preprocessing-book-Chapter 3n4.pdf",
    "data/input/course_materials/data-preprocessing-book-Chapter 7.pdf",
    "data/input/course_materials/introduction-to-data-mining-.pdf",
]
EXPECTED_DOC_IDS = [
    "DOC_data_preprocessing_book_Chapter_3n4",
    "DOC_data_preprocessing_book_Chapter_7",
    "DOC_introduction_to_data_mining",
]


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


def _bash_n(path: Path) -> None:
    if shutil.which("bash") is None:
        print(f"[SKIP] {path.name} bash -n skipped: bash is not installed on this Windows machine")
        return
    proc = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
    check(f"{path.name} passes bash -n ({proc.stderr.strip()})", proc.returncode == 0)


def verify_step_02_real_course_materials() -> None:
    print("\n=== step_02_pdf_ingest (real 3-document course_materials, dry-run) ===")
    for rel in REAL_COURSE_MATERIALS:
        check(f"real course material exists: {rel}", (REPO_ROOT / rel).exists())

    layout = get_operator_layout(REPO_ROOT)
    state_path = run_state_mod.run_state_path(layout.pipeline_runs_root, TEST_RUN_ID)
    state = run_state_mod.new_run_state(TEST_RUN_ID, course_materials=REAL_COURSE_MATERIALS)
    run_state_mod.write_run_state(state_path, state)

    proc = _run_cli("run-stage", "step_02_pdf_ingest", "--run-id", TEST_RUN_ID, "--dry-run")
    check(f"step_02 dry-run exits 0 (stderr: {proc.stderr[-1500:]})", proc.returncode == 0)
    check("reports STEP_02_DOC_COUNT=3", "STEP_02_DOC_COUNT=3" in proc.stdout)

    run_dir = layout.pipeline_runs_root / TEST_RUN_ID / "step_02_pdf_ingest"
    for doc_id, rel in zip(EXPECTED_DOC_IDS, REAL_COURSE_MATERIALS):
        script_path = run_dir / f"step_02_pdf_ingest_{doc_id}.slurm"
        check(f"SLURM script rendered for {doc_id}", script_path.exists())
        text = script_path.read_text(encoding="utf-8")
        check(f"{doc_id} script references its own real PDF, not another doc's", str(REPO_ROOT / rel) in text)
        check(f"{doc_id} script passes --doc-id {doc_id}", f"--doc-id {doc_id}" in text or f"'{doc_id}'" in text)
        check(
            f"{doc_id} script sets the correct LD_LIBRARY_PATH",
            "/path/to/software/python/python-3.11.3/lib" in text,
        )
        _bash_n(script_path)

    # Refusal: fresh run_id with no course_materials recorded must refuse, not default to any
    # historical document list.
    fresh_run_id = TEST_RUN_ID + "_no_course_materials"
    proc2 = _run_cli("run-stage", "step_02_pdf_ingest", "--run-id", fresh_run_id, "--dry-run")
    check("refuses cleanly when course_materials is empty", proc2.returncode == 3)
    check("refusal names the STAGE_NOT_WIRED error", "ERROR_STAGE_NOT_WIRED" in proc2.stdout)
    check("refusal message names course_materials", "course_materials" in proc2.stdout)
    _cleanup_run_id(fresh_run_id)


def _seed_step02_output(run_id: str) -> Path:
    layout = get_operator_layout(REPO_ROOT)
    output_root = REPO_ROOT / "data/processed/blockstore" / run_id
    sets_root = output_root / "_sets"
    sets_root.mkdir(parents=True, exist_ok=True)
    set_path = sets_root / f"{run_id}_step2_set.json"
    set_path.write_text(
        json.dumps(
            {
                "set_id": f"{run_id}_step2_set",
                "step": "step2",
                "doc_count": 3,
                "docs": [{"doc_id": did, "processed_out_dir": str(output_root / did / "seed")} for did in EXPECTED_DOC_IDS],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (sets_root / "ACTIVE_STEP2_SET.txt").write_text(set_path.name, encoding="utf-8")

    state_path = run_state_mod.run_state_path(layout.pipeline_runs_root, run_id)
    state = run_state_mod.new_run_state(run_id, course_materials=REAL_COURSE_MATERIALS)
    run_state_mod.set_stage_completed(
        state, "step_02_pdf_ingest", output_root=str(output_root), set_manifest_path=str(set_path), run_folder_symlink=None
    )
    run_state_mod.write_run_state(state_path, state)
    return output_root


def verify_step_03_chain() -> None:
    print("\n=== step_03_doctree_index / step_03_5 / step_03_6 (seeded predecessor state) ===")
    layout = get_operator_layout(REPO_ROOT)
    step2_output_root = _seed_step02_output(TEST_RUN_ID)

    proc = _run_cli("run-stage", "step_03_doctree_index", "--run-id", TEST_RUN_ID, "--dry-run")
    check(f"step_03 dry-run exits 0 (stderr: {proc.stderr[-1500:]})", proc.returncode == 0)
    run_dir = layout.pipeline_runs_root / TEST_RUN_ID / "step_03_doctree_index"
    rendered_config = json.loads((run_dir / f"{TEST_RUN_ID}_step_03_config.json").read_text(encoding="utf-8"))
    check(
        "rendered config references the real step_02 current-run ACTIVE_STEP2_SET.txt",
        rendered_config["input"]["step2_active_set_file"] == str(step2_output_root / "_sets" / "ACTIVE_STEP2_SET.txt"),
    )
    script_path = run_dir / "step_03_doctree_index.slurm"
    check("step_03 SLURM script rendered", script_path.exists())
    check("SLURM script references the rendered config", str(run_dir / f"{TEST_RUN_ID}_step_03_config.json") in script_path.read_text(encoding="utf-8"))
    _bash_n(script_path)

    # Seed step_03's own output (synthetic but schema-accurate) and step_03_5.
    step3_output_root = REPO_ROOT / "data/processed/doctree" / TEST_RUN_ID
    step3_sets = step3_output_root / "_sets"
    step3_sets.mkdir(parents=True, exist_ok=True)
    (step3_sets / f"{TEST_RUN_ID}_step3_set.json").write_text(json.dumps({"docs": []}), encoding="utf-8")
    (step3_sets / "ACTIVE_STEP3_SET.txt").write_text(f"{TEST_RUN_ID}_step3_set.json", encoding="utf-8")

    state_path = run_state_mod.run_state_path(layout.pipeline_runs_root, TEST_RUN_ID)
    state = run_state_mod.load_run_state(state_path)
    run_state_mod.set_stage_completed(
        state, "step_03_doctree_index", output_root=str(step3_output_root),
        set_manifest_path=str(step3_sets / f"{TEST_RUN_ID}_step3_set.json"), run_folder_symlink=None,
    )
    run_state_mod.write_run_state(state_path, state)

    proc = _run_cli("run-stage", "step_03_5_blockstore_cleanup", "--run-id", TEST_RUN_ID, "--dry-run")
    check(f"step_03_5 dry-run exits 0 (stderr: {proc.stderr[-1500:]})", proc.returncode == 0)
    step3_5_run_dir = layout.pipeline_runs_root / TEST_RUN_ID / "step_03_5_blockstore_cleanup"
    rendered_config = json.loads((step3_5_run_dir / f"{TEST_RUN_ID}_step_03_5_config.json").read_text(encoding="utf-8"))
    check(
        "rendered config references the real step_03 current-run ACTIVE_STEP3_SET.txt",
        rendered_config["input"]["step3_active_set_file"] == str(step3_sets / "ACTIVE_STEP3_SET.txt"),
    )
    script_path = step3_5_run_dir / "step_03_5_blockstore_cleanup.slurm"
    check("step_03_5 SLURM script rendered", script_path.exists())
    _bash_n(script_path)

    step3_5_output_root = REPO_ROOT / "data/processed/blockstore_enriched" / TEST_RUN_ID
    step3_5_sets = step3_5_output_root / "_sets"
    step3_5_sets.mkdir(parents=True, exist_ok=True)
    (step3_5_sets / f"{TEST_RUN_ID}_step3_5_set.json").write_text(json.dumps({"docs": []}), encoding="utf-8")
    (step3_5_sets / "ACTIVE_STEP3_5_SET.txt").write_text(f"{TEST_RUN_ID}_step3_5_set.json", encoding="utf-8")

    state = run_state_mod.load_run_state(state_path)
    run_state_mod.set_stage_completed(
        state, "step_03_5_blockstore_cleanup", output_root=str(step3_5_output_root),
        set_manifest_path=str(step3_5_sets / f"{TEST_RUN_ID}_step3_5_set.json"), run_folder_symlink=None,
    )
    run_state_mod.write_run_state(state_path, state)

    proc = _run_cli("run-stage", "step_03_6_math_salvage", "--run-id", TEST_RUN_ID, "--dry-run")
    check(f"step_03_6 dry-run exits 0 (stderr: {proc.stderr[-1500:]})", proc.returncode == 0)
    step3_6_run_dir = layout.pipeline_runs_root / TEST_RUN_ID / "step_03_6_math_salvage"
    rendered_config = json.loads((step3_6_run_dir / f"{TEST_RUN_ID}_step_03_6_config.json").read_text(encoding="utf-8"))
    check(
        "rendered config references the real step_03_5 current-run ACTIVE_STEP3_5_SET.txt",
        rendered_config["input"]["step3_5_active_set_file"] == str(step3_5_sets / "ACTIVE_STEP3_5_SET.txt"),
    )
    script_path = step3_6_run_dir / "step_03_6_math_salvage.slurm"
    check("step_03_6 SLURM script rendered", script_path.exists())
    _bash_n(script_path)

    step3_6_output_root = REPO_ROOT / "data/processed/blockstore_math_salvaged" / TEST_RUN_ID
    step3_6_sets = step3_6_output_root / "_sets"
    step3_6_sets.mkdir(parents=True, exist_ok=True)
    (step3_6_sets / f"{TEST_RUN_ID}_step3_6_set.json").write_text(json.dumps({"docs": []}), encoding="utf-8")
    (step3_6_sets / "ACTIVE_STEP3_6_SET.txt").write_text(f"{TEST_RUN_ID}_step3_6_set.json", encoding="utf-8")

    state = run_state_mod.load_run_state(state_path)
    run_state_mod.set_stage_completed(
        state, "step_03_6_math_salvage", output_root=str(step3_6_output_root),
        set_manifest_path=str(step3_6_sets / f"{TEST_RUN_ID}_step3_6_set.json"), run_folder_symlink=None,
    )
    run_state_mod.write_run_state(state_path, state)

    # Refusal: step_03 without a completed step_02 must refuse.
    fresh_run_id = TEST_RUN_ID + "_no_predecessor"
    state_path2 = run_state_mod.run_state_path(layout.pipeline_runs_root, fresh_run_id)
    run_state_mod.write_run_state(state_path2, run_state_mod.new_run_state(fresh_run_id))
    proc2 = _run_cli("run-stage", "step_03_doctree_index", "--run-id", fresh_run_id, "--dry-run")
    check("step_03 refuses cleanly when step_02 has not completed", proc2.returncode == 3)
    check("refusal names the STAGE_NOT_WIRED error", "ERROR_STAGE_NOT_WIRED" in proc2.stdout)
    _cleanup_run_id(fresh_run_id)


def verify_step_04_patches() -> None:
    print("\n=== step_04_patches (glob-discovery + chained freeze command) ===")
    layout = get_operator_layout(REPO_ROOT)

    proc = _run_cli("run-stage", "step_04_patches", "--run-id", TEST_RUN_ID, "--dry-run")
    check(f"step_04_patches dry-run exits 0 (stderr: {proc.stderr[-2000:]})", proc.returncode == 0)

    run_dir = layout.pipeline_runs_root / TEST_RUN_ID / "step_04_patches"
    script_path = run_dir / "step_04_patches.slurm"
    check("step_04_patches SLURM script rendered", script_path.exists())
    text = script_path.read_text(encoding="utf-8")

    check("script references freeze_step4_patches_set.py", "freeze_step4_patches_set.py" in text)
    check("script glob-discovers the internal step4 run_id", "STEP4_PATCHES_MATCHES" in text)
    check("script refuses if the glob doesn't match exactly one run", "ERROR_STEP4_PATCHES_RUN_ID_AMBIGUOUS" in text)
    check("script refuses if the glob matches zero runs", "ERROR_STEP4_PATCHES_RUN_ID_NOT_FOUND" in text)
    check(
        "freeze command passes --run-id via raw shell-variable expansion, not single-quoted literal",
        '--run-id "$STEP4_PATCHES_RUN_ID"' in text,
    )
    check(
        "script references real step_03/step_03_6 current-run ACTIVE pointers",
        "ACTIVE_STEP3_SET.txt" in text and "ACTIVE_STEP3_6_SET.txt" in text,
    )
    _bash_n(script_path)

    # Refusal: fresh run_id with course_materials but no completed step_03/step_03_6 predecessors.
    fresh_run_id = TEST_RUN_ID + "_no_predecessor2"
    state_path = run_state_mod.run_state_path(layout.pipeline_runs_root, fresh_run_id)
    run_state_mod.write_run_state(state_path, run_state_mod.new_run_state(fresh_run_id, course_materials=REAL_COURSE_MATERIALS))
    proc2 = _run_cli("run-stage", "step_04_patches", "--run-id", fresh_run_id, "--dry-run")
    check("step_04_patches refuses cleanly when step_03/step_03_6 have not completed", proc2.returncode == 3)
    check("refusal names the STAGE_NOT_WIRED error", "ERROR_STAGE_NOT_WIRED" in proc2.stdout)
    _cleanup_run_id(fresh_run_id)


def _seed_step_04_patches_output() -> Path:
    layout = get_operator_layout(REPO_ROOT)
    output_root = REPO_ROOT / "data/processed/retrieval_index" / TEST_RUN_ID
    sets_root = output_root / "_sets"
    sets_root.mkdir(parents=True, exist_ok=True)
    set_path = sets_root / f"{TEST_RUN_ID}_step4_patches_set.json"
    set_path.write_text(json.dumps({"docs": []}, indent=2), encoding="utf-8")
    (sets_root / "ACTIVE_STEP4_PATCHES_SET.txt").write_text(set_path.name, encoding="utf-8")

    state_path = run_state_mod.run_state_path(layout.pipeline_runs_root, TEST_RUN_ID)
    state = run_state_mod.load_run_state(state_path)
    run_state_mod.set_stage_completed(
        state,
        "step_04_patches",
        output_root=str(output_root),
        set_manifest_path=str(set_path),
        run_folder_symlink=None,
    )
    run_state_mod.write_run_state(state_path, state)
    return output_root


def verify_step_04_3() -> None:
    print("\n=== step_04_3_embedding_index (dynamic Ollama host + chained freeze command) ===")
    from kc_l.runtime.stage_registry import STAGE_SPECS

    step4_output_root = _seed_step_04_patches_output()

    proc = _run_cli("run-stage", "step_04_3_embedding_index", "--run-id", TEST_RUN_ID, "--dry-run")
    check(f"step_04_3 dry-run exits 0 (stderr: {proc.stderr[-2000:]})", proc.returncode == 0)

    layout = get_operator_layout(REPO_ROOT)
    run_dir = layout.pipeline_runs_root / TEST_RUN_ID / "step_04_3_embedding_index"
    rendered_config_path = run_dir / f"{TEST_RUN_ID}_step_04_3_config.json"
    rendered_config = json.loads(rendered_config_path.read_text(encoding="utf-8"))
    check(
        "rendered config references the real step_04_patches current-run ACTIVE_STEP4_PATCHES_SET.txt",
        rendered_config["inputs"]["step4_patches_set_active"] == str(step4_output_root / "_sets" / "ACTIVE_STEP4_PATCHES_SET.txt"),
    )
    check(
        "rendered config keeps the real step_03/step_03_6 current-run ACTIVE pointers",
        rendered_config["inputs"]["step3_set_active"].endswith("ACTIVE_STEP3_SET.txt")
        and rendered_config["inputs"]["step3_6_set_active"].endswith("ACTIVE_STEP3_6_SET.txt"),
    )

    script_path = run_dir / "step_04_3_embedding_index.slurm"
    check("step_04_3 SLURM script rendered", script_path.exists())
    text = script_path.read_text(encoding="utf-8")
    check("rendered script computes a dynamic per-job Ollama port", "PORT=$((25000 + (${SLURM_JOB_ID:-0} % 10000)))" in text)
    check("rendered script passes --ollama-host to the real step_04_3 invocation", '--ollama-host "$OLLAMA_HOST"' in text)
    check("rendered script runs freeze_step4_index_set_actual_corpus.py afterward", "freeze_step4_index_set_actual_corpus.py" in text)
    check(
        "freeze command points at the real step4.3 audit run dir",
        "--run-dir-step4-3" in text and str(REPO_ROOT / "data/runs" / TEST_RUN_ID) in text,
    )
    _bash_n(script_path)

    check("step_04_3_embedding_index.run_stage_wired is True", STAGE_SPECS["step_04_3_embedding_index"].run_stage_wired is True)
    # step_04_5_sentence_overlay is now wired too (its own runner bugs fixed separately) - see
    # the dedicated scripts/maintenance/verify_orchestrator_run_stage_step_04_5.py for its
    # coverage, not duplicated here.


def main() -> int:
    try:
        verify_step_02_real_course_materials()
        verify_step_03_chain()
        verify_step_04_patches()
        verify_step_04_3()
    finally:
        _cleanup_run_id(TEST_RUN_ID)

    print("\nALL STEP_02-THROUGH-STEP_04_3 RUN-STAGE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
