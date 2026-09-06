#!/usr/bin/env python3
"""Self-chaining advance step: called as a trailer inside a wired stage's own rendered SLURM
script, AFTER that stage's runner has exited 0 (see slurm_render.render_cpu_job/
render_ollama_job's extra_commands, appended generically by run_stage() for every stage it
renders unless --no-self-chain is passed - see kc_l_orchestrator.py's
_chain_advance_extra_commands()). The one exception: step_02_pdf_ingest's own per-document
jobs only carry this trailer on the LAST document's job - the stage as a whole isn't done
until every document has merged into ACTIVE_STEP2_SET.txt (see _prepare_step_02_invocations'
docstring in kc_l_orchestrator.py).

Usage: advance_run.py <run_id> <just_completed_stage_id> [--repo-root ...] [--dry-run]

Does 4 things, matching the Milestone 4 self-chaining design:
1. Resolves the just-completed stage's real output_root
   (repo_root/stage_spec.output_root/run_id - the same formula every _prepare_stage_invocation
   branch already renders into, confirmed consistent across every wired stage) and creates a
   symlink at data/processed/runs/<run_id>/<stage>/output -> that real output_root (the
   run-folder convention from Section A of this project's plan - previously an open gap, see
   ORCHESTRATOR_BUILD_STATE.md's "known open gaps" list).
2. Marks the stage completed in RUN_STATE.json.
3. Resolves the full "ready set" of next stages via kc_l.runtime.chain.resolve_ready_stages -
   a full graph scan, not just this stage's own direct dependents (see that function's
   docstring for why: multi-parent fan-in, and zero-dependency stages like hierarchy_registry
   that must become ready independent of any specific predecessor).
4. For each ready stage: if run_stage_wired, submits it for real via the same run_stage() this
   orchestrator's CLI uses (no --dependency needed - by the time this runs, the predecessor(s)
   have already genuinely completed). If NOT run_stage_wired, does NOT submit and does NOT
   silently skip it either - records it under RUN_STATE.json's blocked_stages and sets the
   run's overall status to "blocked_unwired_stage", so a human/UI can see exactly where and why
   the chain stopped. A run stopping cleanly here, with everything upstream of the blocker
   already having run, is a legitimate, expected outcome right now - not a bug to route around.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
_REPO_SRC = _SCRIPTS_DIR.parent / "src"
if str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

import kc_l_orchestrator as orch  # noqa: E402
from kc_l.runtime import run_state as run_state_mod  # noqa: E402
from kc_l.runtime.chain import resolve_ready_stages, submit_ready_stages  # noqa: E402
from kc_l.runtime.layout import get_operator_layout  # noqa: E402
from kc_l.runtime.stage_registry import STAGE_SPECS, get_stage  # noqa: E402


def stage_output_root(repo_root: Path, stage_id: str, run_id: str) -> Path | None:
    spec = get_stage(stage_id)
    if not spec.output_root:
        return None
    return repo_root / spec.output_root / run_id


def create_run_folder_symlink(repo_root: Path, run_id: str, stage_id: str, output_root: Path | None) -> str | None:
    if output_root is None or not output_root.exists():
        return None
    layout = get_operator_layout(repo_root)
    run_dir = layout.pipeline_runs_root / run_id / stage_id
    run_dir.mkdir(parents=True, exist_ok=True)
    symlink_path = run_dir / "output"
    if symlink_path.is_symlink() or symlink_path.exists():
        return str(symlink_path)
    try:
        os.symlink(str(output_root), str(symlink_path), target_is_directory=True)
    except OSError:
        # Symlink creation can fail on a dev machine without the right privileges (e.g.
        # Windows without admin/Developer Mode) - the real HPC target is Linux, where this
        # always works. Not fatal: run_folder_symlink simply stays None if creation genuinely
        # fails here, same spirit as other confirmed cross-host limitations already documented
        # in this project (BEST-pointer resolution across HPC-absolute paths, etc).
        return None
    return str(symlink_path)


def create_run_convention_symlink(repo_root: Path, run_id: str, stage_id: str, output_root: Path | None) -> Path | None:
    """Directory-restructuring convention (confirmed real physical relocation is unsafe - see
    ORCHESTRATOR_BUILD_STATE.md's directory-restructuring investigation entry): several stage
    scripts self-generate their own internal timestamp subdirectory beneath whatever
    --output-root they're given (hierarchy_registry, step_04_5, the config_yaml stages),
    completely independent of this orchestrator's own run_id - real output can land one or two
    directories deeper than RUN_STATE.json's own output_root formula
    (repo_root/spec.output_root/run_id) would suggest. Rewriting every such script to accept a
    literal target directory would be invasive and touches provenance-labeling code the real
    scripts already rely on their own run_id argument for - out of scope for a "new code path,
    not a rewrite" change.

    Instead, this creates a symlink at data/processed/<run_id>/<stage_id> -> output_root (the
    stage's real, existing, un-moved output_root/run_id directory, whatever nesting quirks its
    own script produces beneath it) - transparent to every downstream consumer, since directory
    symlinks are followed transparently by Path.exists()/open()/iterdir() on POSIX (the real
    HPC target). Never moves, renames, copies, or deletes anything.
    """
    if output_root is None or not output_root.exists():
        return None
    new_run_dir = repo_root / "data/processed" / run_id
    new_run_dir.mkdir(parents=True, exist_ok=True)
    symlink_path = new_run_dir / stage_id
    if symlink_path.is_symlink() or symlink_path.exists():
        return symlink_path
    try:
        os.symlink(str(output_root), str(symlink_path), target_is_directory=True)
    except OSError:
        # Same cross-host limitation as create_run_folder_symlink() above - not fatal, the
        # caller falls back to recording the real output_root when this returns None.
        return None
    return symlink_path


def advance(repo_root: Path, run_id: str, just_completed_stage_id: str, *, dry_run: bool) -> dict[str, Any]:
    layout = get_operator_layout(repo_root)
    state_path = run_state_mod.run_state_path(layout.pipeline_runs_root, run_id)
    state = run_state_mod.load_run_state(state_path)

    output_root = stage_output_root(repo_root, just_completed_stage_id, run_id)
    symlink_path = None if dry_run else create_run_folder_symlink(repo_root, run_id, just_completed_stage_id, output_root)
    # Directory-restructuring convention: record the new data/processed/<run_id>/<stage_id>
    # symlink as this stage's output_root going forward when creation succeeds, falling back to
    # the real path otherwise (e.g. symlink privileges unavailable) - never leaves output_root
    # null just because the new-convention symlink couldn't be created.
    convention_symlink = None if dry_run else create_run_convention_symlink(repo_root, run_id, just_completed_stage_id, output_root)
    recorded_output_root = convention_symlink if convention_symlink is not None else output_root

    if dry_run:
        # Simulate the completion in memory only, to report what the ready-set WOULD become -
        # deliberately does not touch RUN_STATE.json on disk or submit anything real.
        simulated = run_state_mod.load_run_state(state_path)
        run_state_mod.set_stage_completed(
            simulated, just_completed_stage_id,
            output_root=str(output_root) if output_root else None, set_manifest_path=None, run_folder_symlink=None,
        )
        ready_stage_ids = resolve_ready_stages(simulated)
        result = {
            "ready_wired_submitted": [
                sid for sid in ready_stage_ids
                if STAGE_SPECS[sid].run_stage_wired and not STAGE_SPECS[sid].human_review_gate
            ],
            "ready_blocked": [
                sid for sid in ready_stage_ids
                if not STAGE_SPECS[sid].run_stage_wired and not STAGE_SPECS[sid].human_review_gate
            ],
            "ready_pending_human_review": [sid for sid in ready_stage_ids if STAGE_SPECS[sid].human_review_gate],
            "submission_failures": {},
        }
    else:
        # set_stage_completed must be written to disk BEFORE submit_ready_stages runs - it
        # reloads RUN_STATE.json from disk itself (see its own docstring for why), so this
        # stage's completion must already be persisted for the ready-set resolution to see it.
        run_state_mod.set_stage_completed(
            state, just_completed_stage_id,
            output_root=str(recorded_output_root) if recorded_output_root else None,
            set_manifest_path=None, run_folder_symlink=symlink_path,
        )
        run_state_mod.write_run_state(state_path, state)
        result = submit_ready_stages(orch, repo_root, run_id, state_path, dry_run=False)

    return {
        "just_completed_stage_id": just_completed_stage_id,
        "output_root": str(recorded_output_root) if recorded_output_root else None,
        "real_output_root": str(output_root) if output_root else None,
        "run_folder_symlink": symlink_path,
        **result,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Self-chaining advance step for one completed pipeline stage.")
    ap.add_argument("run_id")
    ap.add_argument("just_completed_stage_id")
    ap.add_argument("--repo-root", default=str(_SCRIPTS_DIR.parent))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()

    print("KC_L_ADVANCE_RUN=1")
    print(f"RUN_ID={args.run_id}")
    print(f"JUST_COMPLETED_STAGE_ID={args.just_completed_stage_id}")

    result = advance(repo_root, args.run_id, args.just_completed_stage_id, dry_run=args.dry_run)

    print(f"OUTPUT_ROOT={result['output_root']}")
    print(f"REAL_OUTPUT_ROOT={result['real_output_root']}")
    print(f"RUN_FOLDER_SYMLINK={result['run_folder_symlink']}")
    print(f"READY_WIRED_SUBMITTED={','.join(result['ready_wired_submitted']) or '(none)'}")
    print(f"READY_BLOCKED={','.join(result['ready_blocked']) or '(none)'}")
    print(f"READY_PENDING_HUMAN_REVIEW={','.join(result.get('ready_pending_human_review') or []) or '(none)'}")

    submission_failures = result.get("submission_failures") or {}
    if submission_failures:
        for sid, reason in submission_failures.items():
            print(f"SUBMISSION_FAILURE\t{sid}\t{reason}")
        # A ready-and-wired stage that still failed to actually submit is a real problem worth
        # surfacing loudly - this makes the SLURM job carrying this trailer show as FAILED in
        # sacct, rather than silently reporting success while a stage never got queued.
        return 12

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
