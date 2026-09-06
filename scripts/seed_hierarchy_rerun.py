#!/usr/bin/env python3
"""Seed a new run's RUN_STATE.json from a source run's already-completed hierarchy-independent
stages, so a new run can start fresh at hierarchy_registry against a different hierarchy input
without redoing Step 2 through Step 4.5 (PDF extraction, doctree, blockstore cleanup/salvage,
embedding index, sentence overlay - confirmed by direct code inspection of scripts/
kc_l_orchestrator.py's own per-stage _prepare_stage_invocation branches: zero references to
hierarchy_path/hierarchy_registry anywhere in these 7 stages' own code, not just their declared
depends_on tuples).

References the source run's real, unmoved output_root for each seeded stage - never copies any
data (multi-GB blockstore/embedding artifacts stay exactly where they are). Read-only against
the source run: only ever calls run_state.load_run_state() on it, never writes back, so the
source run's own RUN_STATE.json and ongoing usability are completely unaffected.

Integrates with the directory-restructuring convention (data/processed/<run_id>/<stage_id> ->
real output, see advance_run.py's create_run_convention_symlink()): each seeded stage also gets
that symlink under the NEW run_id, pointing at the SOURCE run's real output, so a human browsing
data/processed/<new_run_id>/ sees every stage uniformly - both the ones referenced from the
source run and the ones that will run fresh.

Usage: seed_hierarchy_rerun.py <source_run_id> <new_run_id> <new_hierarchy_path>
       [--repo-root ...] [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
_REPO_SRC = _SCRIPTS_DIR.parent / "src"
if str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

from advance_run import create_run_convention_symlink  # noqa: E402
from kc_l.runtime import run_state as run_state_mod  # noqa: E402
from kc_l.runtime.layout import get_operator_layout  # noqa: E402

# Confirmed by direct code inspection (grep across scripts/kc_l_orchestrator.py's own per-stage
# _prepare_stage_invocation branches, lines 1384-2029): zero references to hierarchy_path or
# hierarchy_registry anywhere in these 7 stages' own code.
HIERARCHY_INDEPENDENT_STAGES_IN_ORDER: tuple[str, ...] = (
    "step_02_pdf_ingest",
    "step_03_doctree_index",
    "step_03_5_blockstore_cleanup",
    "step_03_6_math_salvage",
    "step_04_patches",
    "step_04_3_embedding_index",
    "step_04_5_sentence_overlay",
)


def seed(
    repo_root: Path,
    source_run_id: str,
    new_run_id: str,
    new_hierarchy_path: str,
    *,
    dry_run: bool,
) -> dict:
    layout = get_operator_layout(repo_root)
    source_state_path = run_state_mod.run_state_path(layout.pipeline_runs_root, source_run_id)
    source_state = run_state_mod.load_run_state(source_state_path)  # read-only, never written back

    new_state_path = run_state_mod.run_state_path(layout.pipeline_runs_root, new_run_id)
    if new_state_path.exists():
        raise RuntimeError(f"refusing to seed: RUN_STATE.json already exists for run_id {new_run_id!r}")

    missing_or_incomplete = [
        sid for sid in HIERARCHY_INDEPENDENT_STAGES_IN_ORDER
        if (source_state.get("stages", {}).get(sid) or {}).get("status") != "completed"
    ]
    if missing_or_incomplete:
        raise RuntimeError(
            f"source run {source_run_id!r} has not completed these hierarchy-independent "
            f"stages, cannot seed from it: {missing_or_incomplete}"
        )

    new_state = run_state_mod.new_run_state(
        new_run_id,
        course_materials=list(source_state.get("course_materials") or []),
        hierarchy_path=new_hierarchy_path,
        overrides=dict(source_state.get("overrides") or {}),
    )

    seeded_output_roots: dict[str, str | None] = {}
    seeded_symlinks: dict[str, str | None] = {}
    for stage_id in HIERARCHY_INDEPENDENT_STAGES_IN_ORDER:
        source_entry = source_state["stages"][stage_id]
        real_output_root = Path(source_entry["output_root"]) if source_entry.get("output_root") else None
        convention_symlink = (
            None if dry_run or real_output_root is None
            else create_run_convention_symlink(repo_root, new_run_id, stage_id, real_output_root)
        )
        recorded_output_root = convention_symlink if convention_symlink is not None else real_output_root
        seeded_output_roots[stage_id] = str(recorded_output_root) if recorded_output_root else None
        seeded_symlinks[stage_id] = str(convention_symlink) if convention_symlink else None
        if not dry_run:
            run_state_mod.set_stage_completed(
                new_state, stage_id,
                output_root=str(recorded_output_root) if recorded_output_root else None,
                set_manifest_path=source_entry.get("set_manifest_path"),
                run_folder_symlink=None,
            )

    if not dry_run:
        run_state_mod.write_run_state(new_state_path, new_state)

    return {
        "source_run_id": source_run_id,
        "new_run_id": new_run_id,
        "seeded_stages": list(HIERARCHY_INDEPENDENT_STAGES_IN_ORDER),
        "seeded_output_roots": seeded_output_roots,
        "seeded_symlinks": seeded_symlinks,
        "new_state_path": str(new_state_path),
        "dry_run": dry_run,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Seed a new run's RUN_STATE.json from a source run's completed "
        "hierarchy-independent stages (step_02 through step_04_5), referencing its real, "
        "unmoved output - never copying data - so only hierarchy_registry onward needs to run "
        "fresh against a new hierarchy file."
    )
    ap.add_argument("source_run_id")
    ap.add_argument("new_run_id")
    ap.add_argument("new_hierarchy_path", help="Repo-relative path to the new hierarchy input file")
    ap.add_argument("--repo-root", default=str(_SCRIPTS_DIR.parent))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()

    print("KC_L_SEED_HIERARCHY_RERUN=1")
    print(f"SOURCE_RUN_ID={args.source_run_id}")
    print(f"NEW_RUN_ID={args.new_run_id}")
    print(f"NEW_HIERARCHY_PATH={args.new_hierarchy_path}")
    print(f"DRY_RUN={int(args.dry_run)}")

    result = seed(repo_root, args.source_run_id, args.new_run_id, args.new_hierarchy_path, dry_run=args.dry_run)

    print(f"SEEDED_STAGES={','.join(result['seeded_stages'])}")
    for sid in result["seeded_stages"]:
        print(f"SEEDED_OUTPUT_ROOT\t{sid}\t{result['seeded_output_roots'][sid]}")
        print(f"SEEDED_SYMLINK\t{sid}\t{result['seeded_symlinks'][sid]}")
    print(f"NEW_STATE_PATH={result['new_state_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
