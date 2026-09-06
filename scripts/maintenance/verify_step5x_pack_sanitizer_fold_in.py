#!/usr/bin/env python3
"""Verify the folded-in step5x pack sanitizer (dedup + exercise-prompt removal + noisy-item
flagging + gap-request creation) against the real historical BEST_STEP5X pack.

Runs the now-updated run_step5x_v3_pack_composition.py against the real historical
full_exercise_guard_gate_20260519T151416Z scored-candidates (the last purely-canonical-script
artifact before the ad-hoc finalizer used to run separately), and confirms the output now
matches BEST_STEP5X_FINAL_SANITIZED_GAPAWARE_SET.txt's target exactly - 0/144 KCs differing,
not the 5/144 that differed before this fold-in (see ORCHESTRATOR_BUILD_STATE.md).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

REAL_SCORED_CANDIDATES_JSONL = REPO_ROOT / (
    "data/processed/evidence_stage_v3_scored_candidates/"
    "full_exercise_guard_gate_20260519T151416Z_scored/scored_candidates.jsonl"
)
REAL_REGISTRY_JSONL = REPO_ROOT / (
    "_archive/repo_cleanup_candidates/local_audits/"
    "package_complete_raw_5p5x_assessment_bundle_20260516T134659Z/stage/files/"
    "0018_rehydrated_registry_jsonl/step5p_context_rehydrated_registry.jsonl"
)
REAL_BEST_PACK_JSONL = REPO_ROOT / (
    "data/processed/evidence_stage_v3_evidence_packs/"
    "best_step5x_final_sanitized_gapaware_20260519T160140Z_pack/kc_evidence_packs.jsonl"
)
REAL_BEST_GAP_JSONL = REPO_ROOT / (
    "data/processed/evidence_stage_v3_evidence_packs/"
    "best_step5x_final_sanitized_gapaware_20260519T160140Z_pack/retrieval_gap_requests.jsonl"
)

PACK_COMPOSITION_SCRIPT = REPO_ROOT / "steps/step_05_x_evidence_stage_v3/scripts/run_step5x_v3_pack_composition.py"
RUN_ID = "verify_step5x_pack_sanitizer_fold_in"


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        raise SystemExit(f"Verification failed: {label}")


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def item_signature(item) -> tuple:
    if not isinstance(item, dict):
        return (item,)
    return (
        item.get("text"),
        item.get("role"),
        tuple(sorted(item.get("selected_text_quality_flags") or [])),
    )


def main() -> int:
    check("real scored-candidates fixture exists", REAL_SCORED_CANDIDATES_JSONL.exists())
    check("real registry fixture exists", REAL_REGISTRY_JSONL.exists())
    check("real BEST_STEP5X pack exists", REAL_BEST_PACK_JSONL.exists())
    check("real BEST_STEP5X gap requests exist", REAL_BEST_GAP_JSONL.exists())

    with tempfile.TemporaryDirectory() as tmp:
        out_root = Path(tmp) / "pack"
        set_manifest_root = out_root / "_sets"

        proc = subprocess.run(
            [
                sys.executable,
                str(PACK_COMPOSITION_SCRIPT),
                "--scored-candidates-jsonl", str(REAL_SCORED_CANDIDATES_JSONL),
                "--registry-jsonl", str(REAL_REGISTRY_JSONL),
                "--run-id", RUN_ID,
                "--output-root", str(out_root),
                "--set-manifest-root", str(set_manifest_root),
            ],
            capture_output=True,
            text=True,
        )
        check(f"pack_composition (with fold-in) exits 0 (stderr: {proc.stderr[-1500:]})", proc.returncode == 0)
        result = json.loads(proc.stdout)

        sanitizer_stats = result["step5x_pack_sanitizer"]
        print("sanitizer stats:", json.dumps(sanitizer_stats, indent=2))
        check("removed_exercise_count == 1", sanitizer_stats["removed_exercise_count"] == 1)
        check("dropped_duplicate_count == 4", sanitizer_stats["dropped_duplicate_count"] == 4)
        check("newly_zero_kcs == ['KC_FSEL_GOOD_004']", sanitizer_stats["newly_zero_kcs"] == ["KC_FSEL_GOOD_004"])
        check("added_gap_count == 1", sanitizer_stats["added_gap_count"] == 1)

        generated_pack = read_jsonl(Path(result["kc_evidence_packs_jsonl"]))
        generated_gap = read_jsonl(Path(result["retrieval_gap_requests_jsonl"]))

    real_pack = read_jsonl(REAL_BEST_PACK_JSONL)
    real_gap = read_jsonl(REAL_BEST_GAP_JSONL)

    check("generated pack has 144 rows", len(generated_pack) == 144)
    check("real best pack has 144 rows", len(real_pack) == 144)

    gen_by_id = {r["kc_id"]: r for r in generated_pack}
    real_by_id = {r["kc_id"]: r for r in real_pack}
    check("kc_id sets match", set(gen_by_id) == set(real_by_id))

    identical = 0
    mismatches = []
    for kc_id in sorted(gen_by_id):
        gen_items = gen_by_id[kc_id].get("ordered_pack_for_drafting") or []
        real_items = real_by_id[kc_id].get("ordered_pack_for_drafting") or []
        gen_sig = [item_signature(it) for it in gen_items]
        real_sig = [item_signature(it) for it in real_items]
        if gen_sig == real_sig:
            identical += 1
        else:
            mismatches.append((kc_id, gen_sig, real_sig))

    print(f"\nKCs identical (text + role + quality_flags, order-sensitive): {identical}/144")
    print(f"KCs differing: {len(mismatches)}")
    if mismatches:
        kc_id, gen_sig, real_sig = mismatches[0]
        print(f"first mismatch: {kc_id}")
        print("generated:", gen_sig)
        print("real     :", real_sig)

    check("0/144 KCs differ from the real BEST_STEP5X pack", len(mismatches) == 0)

    gen_gap_kcs = sorted({r.get("kc_id") for r in generated_gap})
    real_gap_kcs = sorted({r.get("kc_id") for r in real_gap})
    check(f"gap-request KC sets match ({len(gen_gap_kcs)} vs {len(real_gap_kcs)})", gen_gap_kcs == real_gap_kcs)

    print("\nALL STEP5X PACK SANITIZER FOLD-IN CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
