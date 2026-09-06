#!/usr/bin/env python3
"""Functional (not just import/signature-level) verification of the two run_step4_5.py bug
fixes: the missing resolve_step4_block_corpus_path() helper, and the stray repo_root= keyword
passed to resolve_step4_patch_paths() (which only accepts step4_doc/step4_patch_doc).

Runs the REAL run_step4_5.py main() end to end against a real historical Step 4.3 index
manifest (found fully mirrored locally under _archive/.../stage/_absolute/path/to/scratch/... for all
3 real course-material documents - the manifest itself plus every block_text_corpus.jsonl and
page_patch_index.jsonl/page_reveal_groups.jsonl/patch_summary.json file it references).

The manifest's own path values are real HPC-absolute POSIX paths
(/path/to/scratch/kc_l/...) that don't exist as literal paths on this Windows dev
machine - this script builds a LOCALIZED copy (string-substituting that prefix for the real
local mirror directory) purely so the real code can resolve real files on this machine; this
does not touch or paper over the actual bug fix, which is exercised exactly as written. No
patches-set manifest is available locally (only the individual patch files under Step 4.3's own
step4_patch_out_dir), so this run exercises resolve_step4_patch_paths' documented FALLBACK path
(deriving patch paths from step4_doc's own step4_patch_out_dir) - a real, intentionally-supported
code path in the original script, not a workaround.

Confirms: the per-document loop actually completes (no TypeError/NameError), real sentence rows
get produced for all 3 real documents, and the stage's own acceptance gate passes.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from kc_l.runtime.stage_config import render_stage_config  # noqa: E402

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

TEST_ROOT = REPO_ROOT / "data/processed/_verify_step4_5_bugfix_functional_test"


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        raise SystemExit(f"Verification failed: {label}")


def main() -> int:
    if TEST_ROOT.exists():
        shutil.rmtree(TEST_ROOT)
    TEST_ROOT.mkdir(parents=True, exist_ok=True)

    try:
        check("real historical step4.3 manifest exists", REAL_MANIFEST_PATH.exists())

        for doc_id in (
            "DOC_data_preprocessing_book_Chapter_3n4",
            "DOC_data_preprocessing_book_Chapter_7",
            "DOC_introduction_to_data_mining",
        ):
            block_corpus = REAL_MANIFEST_MIRROR_ROOT / (
                f"data/processed/retrieval_index/{doc_id}/2026-04-07_000855_step4_3_1/block_text_corpus.jsonl"
            )
            patch_summary = REAL_MANIFEST_MIRROR_ROOT / (
                f"data/processed/retrieval_index/{doc_id}/2026-04-06_220031_step4/patch_summary.json"
            )
            check(f"real block_text_corpus.jsonl exists for {doc_id}", block_corpus.exists())
            check(f"real patch_summary.json exists for {doc_id}", patch_summary.exists())

        # Localize the real manifest's /path/to/scratch/... paths to the real local mirror directory,
        # so the real, unmodified run_step4_5.py code can resolve genuine files on this machine.
        localized_dir = TEST_ROOT / "localized_step4_3_set"
        localized_dir.mkdir(parents=True, exist_ok=True)
        raw_text = REAL_MANIFEST_PATH.read_text(encoding="utf-8")
        local_prefix = REAL_MANIFEST_MIRROR_ROOT.as_posix() + "/"
        localized_text = raw_text.replace(REAL_SCRATCH_PREFIX, local_prefix)
        check(
            "localization actually replaced something (manifest really contained the real prefix)",
            localized_text != raw_text,
        )
        localized_manifest_path = localized_dir / "2026-04-07_000855_step4_3_1_step4_index_set.json"
        localized_manifest_path.write_text(localized_text, encoding="utf-8")
        (localized_dir / "ACTIVE_STEP4_SET.txt").write_text(localized_manifest_path.name, encoding="utf-8")

        # Render a real step_04_5 config (same render_stage_config() mechanism the orchestrator
        # itself uses) pointing at the localized manifest, with relative (not absolute) test
        # output paths so repo_root-joining behaves correctly on this Windows machine too.
        processed_root_rel = "data/processed/_verify_step4_5_bugfix_functional_test/processed"
        sets_dir_rel = "data/processed/_verify_step4_5_bugfix_functional_test/processed/_sets"
        runs_dir_rel = "data/processed/_verify_step4_5_bugfix_functional_test/runs"
        overrides = {
            "inputs": {
                # step4_5.default.yaml sets inputs.step4_active_set_pointer (a DIFFERENT key
                # name than the hpc.actual_corpus.yaml base's inputs.active_step4_set), and
                # main()'s own lookup checks step4_active_set_pointer FIRST
                # (cfg["inputs"].get("step4_active_set_pointer") or .get("active_step4_set")) -
                # confirmed the hard way: overriding only active_step4_set left the default's
                # step4_active_set_pointer value in effect. Override both so this holds
                # regardless of which key a given base config happens to set.
                "step4_active_set_pointer": str((localized_dir / "ACTIVE_STEP4_SET.txt").relative_to(REPO_ROOT)).replace("\\", "/"),
                "active_step4_set": str((localized_dir / "ACTIVE_STEP4_SET.txt").relative_to(REPO_ROOT)).replace("\\", "/"),
                "active_step4_5_set_pointer": f"{sets_dir_rel}/ACTIVE_STEP4_5_SET.txt",
            },
            "outputs": {
                "processed_root": processed_root_rel,
                "sets_dir": sets_dir_rel,
            },
            "audit": {"runs_dir": runs_dir_rel},
        }
        rendered_config_path = TEST_ROOT / "step4_5_config.json"
        render_stage_config(
            REPO_ROOT / "steps/step_04_5_sentence_overlay/resources/step4_5.hpc.actual_corpus.yaml",
            overrides,
            rendered_config_path,
        )

        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "steps/step_04_5_sentence_overlay/scripts/run_step4_5.py"),
             "--config", str(rendered_config_path)],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        print("----- run_step4_5.py stdout -----")
        print(proc.stdout)
        print("----- run_step4_5.py stderr (last 3000 chars) -----")
        print(proc.stderr[-3000:])

        check(
            f"run_step4_5.py completes successfully (rc={proc.returncode}) - no TypeError/NameError from the two bugs",
            proc.returncode == 0,
        )
        check("no leftover reference to the missing helper crashing", "NameError" not in proc.stderr)
        check("no leftover TypeError from the stray repo_root kwarg", "TypeError" not in proc.stderr)
        check("stdout reports all 3 real documents processed", "docs_with_sentences=3" in proc.stdout)

        active_pointer = REPO_ROOT / sets_dir_rel / "ACTIVE_STEP4_5_SET.txt"
        check("ACTIVE_STEP4_5_SET.txt was self-written (acceptance gate passed)", active_pointer.exists())
        set_manifest_name = active_pointer.read_text(encoding="utf-8").strip()
        set_manifest_path = active_pointer.parent / set_manifest_name
        check("the set manifest ACTIVE_STEP4_5_SET.txt points at exists", set_manifest_path.exists())
        set_manifest = json.loads(set_manifest_path.read_text(encoding="utf-8"))
        corpus_path = REPO_ROOT / set_manifest["artifacts"]["sentence_corpus_jsonl"]
        check("real sentence_corpus.jsonl was written", corpus_path.exists())
        sentence_rows = [json.loads(line) for line in corpus_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        check("sentence_corpus.jsonl has real rows for all 3 documents", len(sentence_rows) > 0)
        doc_ids_seen = {row.get("doc_id") for row in sentence_rows}
        check(
            "sentences were produced for all 3 real documents, not just one",
            doc_ids_seen
            == {
                "DOC_data_preprocessing_book_Chapter_3n4",
                "DOC_data_preprocessing_book_Chapter_7",
                "DOC_introduction_to_data_mining",
            },
        )

    finally:
        if TEST_ROOT.exists():
            shutil.rmtree(TEST_ROOT)

    print("\nALL step_04_5 BUGFIX FUNCTIONAL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
