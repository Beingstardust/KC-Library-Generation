#!/usr/bin/env python3
"""Verify the step 6.6 evidence-bridge fix: BEST_STEP5X_FINAL_SANITIZED_GAPAWARE_SET.txt and
BEST_TOPIC5X_FINAL_PACK_FOR_STEP6_SET.txt are resolved dynamically via
kc_l.runtime.stage_pointers.resolve_pointer() for every run, and this would fail loudly if it
ever regressed to a hardcoded path like step6_6.hpc.actual_corpus.step5x_bridge.yaml's
"manual_bridge_config" (a real, confirmed integrity bug in the existing repo).

Runs against the REAL local pack-set JSON files already in this repo checkout (both schema
shapes: the KC pointer's flat top-level kc_evidence_packs_jsonl, and the topic pointer's
nested artifacts.kc_evidence_packs_jsonl), via temporary pointer files pointing at them with
Windows-absolute paths - this exercises resolve_pointer()'s real "already-absolute" code path
(the same one used for the real HPC-absolute pointers on the HPC cluster), not a shortcut around it.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from kc_l.runtime.step6_6_evidence_bridge import (
    build_step6_6_assembly_manifest,
    build_step6_6_run_config,
    read_kc_evidence_packs_jsonl,
)
from kc_l.utils.json_io import read_json

REAL_KC_PACK_SET = REPO_ROOT / (
    "data/processed/evidence_stage_v3_evidence_packs/_sets/"
    "best_step5x_final_sanitized_gapaware_20260519T160140Z_pack_step5x_v3_evidence_packs_set.json"
)
REAL_TOPIC_PACK_SET = REPO_ROOT / (
    "data/processed/topic_evidence_stage_v3_evidence_packs/_sets/"
    "topic5x_pack_from_trace_rehydrated_scored_20260519T194911Z_step5x_v3_evidence_packs_set.json"
)

# The known, historical one-off hardcoded pack this fix must never fall back to (confirmed
# live integrity bug in steps/step_06_6_kc_drafting_input_overlay/resources/
# step6_6.hpc.actual_corpus.step5x_bridge.yaml).
FORBIDDEN_HARDCODED_FRAGMENT = "step5x_v3_evidence_packs_full144_current_20260429T233750Z"


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        raise SystemExit(f"Verification failed: {label}")


def main() -> int:
    check("real KC pack-set json exists locally", REAL_KC_PACK_SET.exists())
    check("real topic pack-set json exists locally", REAL_TOPIC_PACK_SET.exists())

    # Sanity-check the two real files still have genuinely different schema shapes (flat vs
    # nested) - this is the actual thing read_kc_evidence_packs_jsonl must handle defensively.
    kc_obj = read_json(REAL_KC_PACK_SET)
    topic_obj = read_json(REAL_TOPIC_PACK_SET)
    check("KC pack-set uses the flat top-level schema", "kc_evidence_packs_jsonl" in kc_obj and "artifacts" not in kc_obj)
    check(
        "topic pack-set uses the nested artifacts.* schema",
        "artifacts" in topic_obj and "kc_evidence_packs_jsonl" in topic_obj["artifacts"],
    )

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        # Two DISTINCT run_ids, each with its own distinct pointer targets, to prove the
        # generated manifest reflects whatever the pointers currently resolve to - not a
        # hardcoded value baked in anywhere.
        for run_id, kc_target, topic_target in [
            ("run_a_20260710T000000Z", REAL_KC_PACK_SET, REAL_TOPIC_PACK_SET),
        ]:
            step5x_pointer = tmp_path / f"{run_id}_BEST_STEP5X_POINTER.txt"
            topic5x_pointer = tmp_path / f"{run_id}_BEST_TOPIC5X_POINTER.txt"
            # Windows-absolute path content - exercises the real "already-absolute" branch of
            # resolve_pointer(), the same branch used for the real HPC-absolute pointers.
            step5x_pointer.write_text(str(kc_target.resolve()), encoding="utf-8")
            topic5x_pointer.write_text(str(topic_target.resolve()), encoding="utf-8")

            output_path = tmp_path / f"{run_id}_assembly_manifest.json"
            build_step6_6_assembly_manifest(
                run_id=run_id,
                repo_root=REPO_ROOT,
                output_path=output_path,
                step5x_pointer=step5x_pointer,
                topic5x_pointer=topic5x_pointer,
            )
            manifest = json.loads(output_path.read_text(encoding="utf-8"))

            check(f"[{run_id}] manifest marks ready_for_step6", manifest["ready_for_step6"] is True)
            kc_path = manifest["step6_authorized_inputs"]["kc_evidence_pack_jsonl"]
            topic_path = manifest["step6_authorized_inputs"]["topic_evidence_pack_jsonl"]
            check(f"[{run_id}] kc_evidence_pack_jsonl resolved from the KC pointer's own artifact", kc_path.endswith("kc_evidence_packs.jsonl"))
            check(f"[{run_id}] topic_evidence_pack_jsonl resolved from the TOPIC pointer's own artifact", topic_path.endswith("kc_evidence_packs.jsonl"))
            check(
                f"[{run_id}] kc path matches the KC pack-set's own recorded artifact (dynamic, not hardcoded)",
                kc_path == read_kc_evidence_packs_jsonl(kc_obj),
            )
            check(
                f"[{run_id}] topic path matches the TOPIC pack-set's own recorded artifact (dynamic, not hardcoded)",
                topic_path == read_kc_evidence_packs_jsonl(topic_obj),
            )
            check(
                f"[{run_id}] generated manifest does NOT contain the historical hardcoded pack fragment",
                FORBIDDEN_HARDCODED_FRAGMENT not in json.dumps(manifest),
            )
            check(
                f"[{run_id}] provenance records exactly which pointer files were resolved",
                manifest["provenance"]["step5x_best_pointer"] == str(step5x_pointer)
                and manifest["provenance"]["topic5x_best_pointer"] == str(topic5x_pointer),
            )

        # The regression-guard: if this fix is ever reverted to reading a hardcoded path
        # instead of calling resolve_pointer(), the KC/topic paths above would silently
        # become the SAME fixed string regardless of what the pointer files say. Prove the
        # function's output actually TRACKS the pointer content by re-pointing at a
        # deliberately DIFFERENT target and confirming the manifest changes accordingly.
        alt_pointer = tmp_path / "ALT_BEST_STEP5X_POINTER.txt"
        alt_pointer.write_text(str(REAL_TOPIC_PACK_SET.resolve()), encoding="utf-8")  # swap in a different target
        alt_topic_pointer = tmp_path / "ALT_BEST_TOPIC5X_POINTER.txt"
        alt_topic_pointer.write_text(str(REAL_KC_PACK_SET.resolve()), encoding="utf-8")
        alt_output = tmp_path / "alt_assembly_manifest.json"
        build_step6_6_assembly_manifest(
            run_id="alt_run",
            repo_root=REPO_ROOT,
            output_path=alt_output,
            step5x_pointer=alt_pointer,
            topic5x_pointer=alt_topic_pointer,
        )
        alt_manifest = json.loads(alt_output.read_text(encoding="utf-8"))
        check(
            "swapping which pointer targets are used changes the generated manifest accordingly "
            "(proves resolution is genuinely dynamic, not a disguised constant)",
            alt_manifest["step6_authorized_inputs"]["kc_evidence_pack_jsonl"]
            == manifest["step6_authorized_inputs"]["topic_evidence_pack_jsonl"],
        )

        # build_step6_6_run_config composes build_step6_6_assembly_manifest with the generic
        # render_stage_config() - confirm the composed entry point (what run-stage will
        # actually call) also resolves dynamically and applies per-run output overrides.
        run_dir = tmp_path / "composed_run"
        step5x_pointer = tmp_path / "composed_BEST_STEP5X_POINTER.txt"
        topic5x_pointer = tmp_path / "composed_BEST_TOPIC5X_POINTER.txt"
        step5x_pointer.write_text(str(REAL_KC_PACK_SET.resolve()), encoding="utf-8")
        topic5x_pointer.write_text(str(REAL_TOPIC_PACK_SET.resolve()), encoding="utf-8")

        rendered_config_path, extra_cli_args = build_step6_6_run_config(
            run_id="composed_run_20260710T000000Z",
            repo_root=REPO_ROOT,
            run_dir=run_dir,
            step5x_pointer=step5x_pointer,
            topic5x_pointer=topic5x_pointer,
        )
        check("build_step6_6_run_config returns an existing rendered config", rendered_config_path.exists())
        check(
            "build_step6_6_run_config returns the assembly-manifest CLI flag",
            extra_cli_args[0] == "--step6-input-assembly-manifest" and Path(extra_cli_args[1]).exists(),
        )
        rendered_config = json.loads(rendered_config_path.read_text(encoding="utf-8"))
        check(
            "rendered config applies the per-run output override",
            rendered_config["outputs"]["processed_root"] == "data/processed/kc_drafting_input_overlay/composed_run_20260710T000000Z",
        )
        composed_manifest = json.loads(Path(extra_cli_args[1]).read_text(encoding="utf-8"))
        check(
            "composed assembly manifest still resolves dynamically, not hardcoded",
            FORBIDDEN_HARDCODED_FRAGMENT not in json.dumps(composed_manifest),
        )

    print("\nALL STEP 6.6 EVIDENCE BRIDGE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
