from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from kc_l.runtime import run_state as run_state_mod
from kc_l.runtime.stage_registry import STAGE_SPECS


def resolve_ready_stages(state: dict[str, Any]) -> list[str]:
    """Full graph scan (not just one stage's own direct dependents) for stages ready to
    submit next: not already running/completed in this run, and every stage named in its own
    depends_on is marked "completed". Used by both poll_fresh_run_requests.py (to bootstrap a
    fresh run) and advance_run.py (to advance after a stage completes) - a full scan, rather
    than each caller walking dependents_of(just_completed_stage_id) itself, because a stage can
    have multiple parents that complete in either order (e.g. step_05x_kc_evidence_stage_v3
    depends on both step_05p_kc_retrieval_profiles and step_04_5_sentence_overlay), and a
    zero-dependency stage (hierarchy_registry) must become ready on its own, independent of any
    specific predecessor's completion - not just "whatever stage_id was just advanced from".

    Deliberately returns stages regardless of run_stage_wired status - callers must decide what
    to do with a ready-but-unwired stage (submit it if wired, or record it as a clean stopping
    point if not - see advance_run.py's blocked_stages handling) rather than this function
    silently filtering unwired stages out, which would make a genuine blocker indistinguishable
    from "nothing more to do right now".
    """
    stages_state = state.get("stages", {})
    ready: list[str] = []
    for stage_id, spec in STAGE_SPECS.items():
        entry = stages_state.get(stage_id)
        if entry is not None and entry.get("status") in {"running", "completed"}:
            continue
        if all(stages_state.get(dep, {}).get("status") == "completed" for dep in spec.depends_on):
            ready.append(stage_id)
    return ready


def submit_ready_stages(
    orch_module: Any,
    repo_root: Path,
    run_id: str,
    state_path: Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Shared by poll_fresh_run_requests.py (bootstrapping a fresh run) and advance_run.py
    (advancing after a stage completes) - both need the exact same "submit what's ready, block
    cleanly on what's ready-but-unwired" behavior, so it lives here once rather than being
    reimplemented per caller.

    Takes state_path, not an in-memory state dict, and reads RUN_STATE.json itself -
    orch_module.run_stage() ALSO reloads RUN_STATE.json from disk and rewrites its own updates
    (job_id, etc) each time it's called below, so operating on a caller-held in-memory copy here
    would silently lose those writes (confirmed the hard way: an earlier version of this
    function took an in-memory state dict, and step_02_pdf_ingest's course_materials never
    reached run_stage() because the caller hadn't written RUN_STATE.json to disk yet at that
    point - callers MUST write the current state to state_path themselves before calling this).

    Submits every run_stage_wired ready stage for real via orch_module.run_stage() (no
    --dependency needed - by the time a caller has a stage's dependencies marked "completed",
    that stage has already genuinely finished). run_stage()'s own return code is checked - a
    "ready and wired" stage can still fail to actually submit (e.g. a stage-specific refusal
    for a reason unrelated to run_stage_wired, like step_02_pdf_ingest refusing when
    course_materials is empty); such failures are NOT counted as submitted and are returned
    under submission_failures, so callers can surface them (e.g. as a nonzero advance_run.py
    exit code, visible via sacct) rather than silently treating a failed submission as success.

    Ready-but-NOT-wired stages are never silently skipped either: they're recorded into
    RUN_STATE.json's blocked_stages and its top-level status is set to "blocked_unwired_stage"
    - a legitimate, expected stopping point right now, not an error. That write happens AFTER
    any run_stage() calls above (re-reading state_path fresh at that point), so it layers on
    top of whatever run_stage() itself already persisted, rather than risking overwriting it
    with a stale copy.

    Ready-but-human_review_gate stages (2026-07-16) are handled the same honest way, under
    their own distinct category (never silently merged into ready_blocked, which specifically
    means "unwired" - a gated stage can be fully wired and still correctly not auto-submitted):
    recorded into RUN_STATE.json's pending_human_review, never submitted automatically
    regardless of dry_run. This is the mechanism that makes a fresh run's self-chain naturally
    stop at the true human-review boundary (e.g. step_06_8_review_packet_emission ->
    step_06_9_review_audit_ingestion) without any caller needing to pass --no-self-chain to
    enforce it.
    """
    state = run_state_mod.load_run_state(state_path)
    ready_stage_ids = resolve_ready_stages(state)
    ready_gated = [sid for sid in ready_stage_ids if STAGE_SPECS[sid].human_review_gate]
    ready_wired = [
        sid for sid in ready_stage_ids
        if STAGE_SPECS[sid].run_stage_wired and not STAGE_SPECS[sid].human_review_gate
    ]
    ready_blocked = [
        sid for sid in ready_stage_ids
        if not STAGE_SPECS[sid].run_stage_wired and not STAGE_SPECS[sid].human_review_gate
    ]

    submitted: list[str] = []
    submission_failures: dict[str, str] = {}
    for sid in ready_wired:
        if dry_run:
            submitted.append(sid)
            continue
        stage_args = argparse.Namespace(
            repo_root=str(repo_root),
            stage_id=sid,
            run_id=run_id,
            dry_run=False,
            dependency_job_id=None,
            no_self_chain=False,
        )
        try:
            rc = orch_module.run_stage(stage_args)
        except Exception as exc:  # noqa: BLE001 - see docstring: one stage's uncaught exception
            # must never take down every other ready stage's submission in the same pass.
            # Confirmed real incident (2026-07-26, run 20260725T225807Z_9e856df6): after
            # step_05p completed, resolve_ready_stages' full graph scan correctly found BOTH
            # step_05_3_evidence_recalibrated and step_05x_kc_evidence_stage_v3 ready at once;
            # step_05_3's own _prepare_stage_invocation raised an unrelated FileNotFoundError
            # (a hierarchy_manifest.json path bug), which was NOT caught here before this fix -
            # the whole "for sid in ready_wired" loop died immediately, so step_05x (fully
            # healthy, unrelated to the bug) never got submitted either, and the entire run sat
            # silently stuck exactly like the failure this file's own docstring already
            # documents for the "ready but unwired" and "submission returned nonzero" cases -
            # just via an uncaught exception instead of a clean nonzero return, which this
            # try/except now treats identically (recorded in submission_failures, loop
            # continues to the next ready stage).
            rc = None
            submission_failures[sid] = f"run_stage() raised {exc.__class__.__name__}: {exc}"
        if rc == 0:
            submitted.append(sid)
        elif rc is not None:
            submission_failures[sid] = f"run_stage() exited {rc}"

    if ready_blocked and not dry_run:
        state = run_state_mod.load_run_state(state_path)
        blocked_stages = state.setdefault("blocked_stages", {})
        for sid in ready_blocked:
            blocked_stages[sid] = {
                "status": "blocked_unwired_stage",
                "reason": f"{sid}: run_stage_wired is False (see stage_registry.py notes)",
            }
        state["status"] = "blocked_unwired_stage"
        run_state_mod.write_run_state(state_path, state)

    if ready_gated and not dry_run:
        state = run_state_mod.load_run_state(state_path)
        pending_human_review = state.setdefault("pending_human_review", {})
        for sid in ready_gated:
            pending_human_review[sid] = {
                "status": "ready_pending_human_review",
                "reason": f"{sid}: human_review_gate is True (see stage_registry.py notes) - "
                "requires a completed human review action outside this pipeline before it can run",
            }
        # Only overwrite top-level status if nothing else already claimed it (an unwired
        # blocker found in the same pass is the more actionable signal) - a run that's stopped
        # ONLY because it's waiting on a human is a clean, expected state, not an error.
        if state.get("status") != "blocked_unwired_stage":
            state["status"] = "awaiting_human_review"
        run_state_mod.write_run_state(state_path, state)

    return {
        "ready_wired_submitted": submitted,
        "ready_blocked": ready_blocked,
        "ready_pending_human_review": ready_gated,
        "submission_failures": submission_failures,
    }
