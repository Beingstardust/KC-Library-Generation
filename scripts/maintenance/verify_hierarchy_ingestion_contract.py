#!/usr/bin/env python3
"""Verify the hierarchy-ingestion structural/semantic contract (see ORCHESTRATOR_BUILD_STATE.md's
hierarchy-ingestion-robustness entry): a node with no "children" is a KC leaf, structurally -
"kc": true is no longer a gating signal - and the only genuinely required field is a KC
identifier (kc_id, aliased to id).

Runs the REAL production scripts (01_hierarchy_normalize.py, run_step01_5_hierarchy_overlay.py)
end to end against three real files, not just the underlying library functions in isolation:

1. The known-good data_mining_kc_hierarchy_revised_.json (real, already-committed asset, used
   all week) - must still produce exactly 144 KC leaves / 171 total nodes / has_errors=False,
   unchanged from before this fix.
2. The real data_mining_kc_hierarchy_v2.json that originally triggered this investigation
   (confirmed real leaves, "kc": true never set) - must now produce 159 KC leaves / 188 total
   nodes / has_errors=False, where it previously silently produced zero KCs.
3. A deliberately broken fixture (one leaf missing kc_id entirely) - must fail LOUDLY at
   normalize time (exit 1, has_errors=True) with a specific, actionable MISSING_KC_ID error
   naming the exact node path - not a downstream symptom one stage removed.

Also exercises scripts/validate_hierarchy_input.py (the standalone author-facing validator)
against all three, confirming it agrees with the real production scripts exactly.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from kc_l.utils.json_io import read_json, read_jsonl  # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
KNOWN_GOOD_HIERARCHY = REPO_ROOT / "data/input/hierarchy/data_mining_kc_hierarchy_revised_.json"
V2_HIERARCHY = FIXTURES_DIR / "data_mining_kc_hierarchy_v2.json"
BROKEN_HIERARCHY = FIXTURES_DIR / "hierarchy_missing_kc_id_broken.json"

NORMALIZE_SCRIPT = REPO_ROOT / "steps/step_01_hierarchy/scripts/01_hierarchy_normalize.py"
OVERLAY_SCRIPT = REPO_ROOT / "steps/step_01_5_hierarchy_overlay/scripts/run_step01_5_hierarchy_overlay.py"
VALIDATE_SCRIPT = REPO_ROOT / "scripts/validate_hierarchy_input.py"


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        raise SystemExit(f"Verification failed: {label}")


def _run_normalize(hierarchy_path: Path, out_root: Path, runs_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable, str(NORMALIZE_SCRIPT),
            "--hierarchy", str(hierarchy_path),
            "--out_root", str(out_root),
            "--runs_dir", str(runs_dir),
        ],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )


def _run_overlay(
    hierarchy_path: Path, normalized_registry: Path, normalized_manifest: Path, out_root: Path, runs_dir: Path
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable, str(OVERLAY_SCRIPT),
            "--hierarchy", str(hierarchy_path),
            "--normalized_registry", str(normalized_registry),
            "--normalized_manifest", str(normalized_manifest),
            "--out_root", str(out_root),
            "--runs_dir", str(runs_dir),
        ],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )


def _run_validate(hierarchy_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATE_SCRIPT), "--hierarchy", str(hierarchy_path)],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )


def _run_end_to_end(label: str, hierarchy_path: Path, work_dir: Path) -> tuple[int, int, dict, int]:
    """Returns (normalize_rc, overlay_rc, overlay_manifest, num_kcs_in_registry)."""
    norm_root = work_dir / "norm"
    runs_dir = work_dir / "runs"
    overlay_root = work_dir / "overlay"

    proc1 = _run_normalize(hierarchy_path, norm_root, runs_dir)
    if proc1.returncode not in (0, 1):
        print(proc1.stdout[-2000:])
        print(proc1.stderr[-2000:])
    registry_matches = list(norm_root.glob("*/kc_registry.jsonl"))
    check(f"[{label}] exactly one normalize run dir produced", len(registry_matches) == 1)
    registry_path = registry_matches[0]
    manifest_path = registry_path.parent / "hierarchy_manifest.json"
    num_kcs = len(list(read_jsonl(registry_path)))

    proc2 = _run_overlay(hierarchy_path, registry_path, manifest_path, overlay_root, runs_dir)
    overlay_manifest_matches = list(overlay_root.glob("*/overlay_manifest.json"))
    check(f"[{label}] exactly one overlay run dir produced", len(overlay_manifest_matches) == 1)
    overlay_manifest = read_json(overlay_manifest_matches[0])

    return proc1.returncode, proc2.returncode, overlay_manifest, num_kcs


def main() -> int:
    check("known-good hierarchy fixture exists", KNOWN_GOOD_HIERARCHY.exists())
    check("v2 hierarchy fixture exists", V2_HIERARCHY.exists())
    check("broken hierarchy fixture exists", BROKEN_HIERARCHY.exists())

    work_root = Path(__file__).resolve().parent / "_tmp_hierarchy_contract_test"
    if work_root.exists():
        shutil.rmtree(work_root, ignore_errors=True)

    try:
        print("\n=== File 1/3: known-good data_mining_kc_hierarchy_revised_.json (must be UNCHANGED) ===")
        norm_rc, overlay_rc, overlay_manifest, num_kcs = _run_end_to_end(
            "known-good", KNOWN_GOOD_HIERARCHY, work_root / "good"
        )
        check(f"normalize exits 0 (rc={norm_rc})", norm_rc == 0)
        check(f"overlay exits 0 (rc={overlay_rc})", overlay_rc == 0)
        check(f"exactly 144 KC leaves in registry (found {num_kcs})", num_kcs == 144)
        check(f"overlay has_errors is False", overlay_manifest["has_errors"] is False)
        check(f"overlay_total_nodes is 171 (found {overlay_manifest['overlay_total_nodes']})", overlay_manifest["overlay_total_nodes"] == 171)

        proc_validate = _run_validate(KNOWN_GOOD_HIERARCHY)
        check("standalone validator agrees: PASS", proc_validate.returncode == 0 and "PASS:" in proc_validate.stdout)
        check("standalone validator reports 144 KC leaves", "KC leaves found: 144" in proc_validate.stdout)

        print("\n=== File 2/3: real data_mining_kc_hierarchy_v2.json (previously silently produced ZERO KCs) ===")
        norm_rc, overlay_rc, overlay_manifest, num_kcs = _run_end_to_end("v2", V2_HIERARCHY, work_root / "v2")
        check(f"normalize exits 0 (rc={norm_rc})", norm_rc == 0)
        check(f"overlay exits 0 (rc={overlay_rc})", overlay_rc == 0)
        check(f"exactly 159 KC leaves in registry (found {num_kcs}) - was 0 before this fix", num_kcs == 159)
        check(f"overlay has_errors is False", overlay_manifest["has_errors"] is False)
        check(f"overlay_total_nodes is 188 (found {overlay_manifest['overlay_total_nodes']})", overlay_manifest["overlay_total_nodes"] == 188)

        proc_validate = _run_validate(V2_HIERARCHY)
        check("standalone validator agrees: PASS", proc_validate.returncode == 0 and "PASS:" in proc_validate.stdout)
        check("standalone validator reports 159 KC leaves", "KC leaves found: 159" in proc_validate.stdout)

        print("\n=== File 3/3: deliberately broken fixture (one leaf missing kc_id) - must FAIL LOUDLY ===")
        norm_rc, overlay_rc, overlay_manifest, num_kcs = _run_end_to_end("broken", BROKEN_HIERARCHY, work_root / "broken")
        check(f"normalize exits 1, fails at the earliest possible point (rc={norm_rc})", norm_rc == 1)
        check(f"overlay ALSO independently catches it (defense-in-depth, rc={overlay_rc})", overlay_rc == 1)
        check("overlay has_errors is True", overlay_manifest["has_errors"] is True)

        proc_validate = _run_validate(BROKEN_HIERARCHY)
        check("standalone validator agrees: FAIL", proc_validate.returncode == 1)
        check(
            "standalone validator names the exact broken node and missing field",
            "MISSING_KC_ID" in proc_validate.stdout
            and "Topic B > Broken Leaf Missing KC Id" in proc_validate.stdout,
        )

    finally:
        shutil.rmtree(work_root, ignore_errors=True)

    print("\nALL HIERARCHY INGESTION CONTRACT CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
