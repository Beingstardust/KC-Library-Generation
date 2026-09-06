#!/usr/bin/env python3
"""Reconciliation watchdog for self-chaining pipeline runs.

Confirmed real gap (see ORCHESTRATOR_BUILD_STATE.md, "Live run 20260712T134004Z_4500583b"):
advance_run.py's self-chaining trailer only runs after a stage's own SLURM job reaches a real
exit 0. If the job is instead killed mid-script by a walltime timeout, OOM, or node failure, the
trailer never runs, RUN_STATE.json's stage entry is left at status="running" with
finished_utc=null forever, and nothing else in the system ever notices - the chain silently
stalls until a human (or Claude) happens to check `sacct` by hand and manually resubmits. That
is the exact "disconnected parts" failure mode this script closes.

On each poll: for every run under data/processed/runs/*/RUN_STATE.json, find stages with
status="running". For each, query `sacct` for the recorded job_id's real terminal state (sacct
is authoritative regardless of whether the job is still queued, still running, or long
finished/died). If sacct reports a genuinely terminal, non-COMPLETED state (FAILED, TIMEOUT,
CANCELLED, NODE_FAIL, OUT_OF_MEMORY, PREEMPTED) - i.e. the job is definitively dead and will
never call advance_run.py itself - mark the stage "failed" in RUN_STATE.json (visible, not
silent) and resubmit it exactly once via `kc_l_orchestrator.py run-stage` (self-chaining stays
on, so a successful retry continues the chain normally). A stage that fails again after its one
retry is left failed and NOT retried further, so a genuine deterministic bug surfaces clearly
instead of being masked behind an infinite retry loop. Retry count is tracked in RUN_STATE.json
under stages.<stage_id>.watchdog_retry_count so this is safe to run repeatedly / concurrently
with other advance_run.py-triggered resubmissions (idempotent: a stage no longer status="running"
by the time this checks it is simply skipped).

Usage:
    python3 reconcile_stalled_stages.py --repo-root . [--dry-run] [--once]
        [--poll-interval-seconds 180] [--max-retries 1]

Runs as a single long-lived loop by default (poll-interval-seconds between passes); pass --once
for a single pass (e.g. to run under cron/at instead of holding a walltime slot open).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TERMINAL_NON_SUCCESS_STATES = {
    "FAILED", "TIMEOUT", "CANCELLED", "NODE_FAIL", "OUT_OF_MEMORY", "PREEMPTED",
    "BOOT_FAIL", "DEADLINE", "REVOKED",
}
STILL_ALIVE_STATES = {"PENDING", "RUNNING", "COMPLETING", "CONFIGURING", "RESIZING", "SUSPENDED"}

# Confirmed (2026-07-26, reading src/kc_l/retrieval_gate/evidence_stage_v3_{candidate_bank,
# scored_candidates,pack_composition}.py directly): all 3 of these shared functions are pure,
# single-pass, in-memory batch transforms with no incremental per-item writes and no resume
# parameter (unlike step_05p) - there is nothing meaningful to "resume" from a partial run. Each
# unconditionally guards against re-running for a run_id whose output_root/run_id directory OR
# whose set_manifest file already exists ("Requested run_id already exists"), with no way to
# override. Both step_05x_kc_evidence_stage_v3 and topic_05x_evidence_stage_v3 (RUN_STATE's own
# stage_id granularity - see kc_l_orchestrator.py's per-stage script_args construction, lines
# ~1076-1258) wrap this exact same shared code via 3 chained sub-scripts each (KC-track and
# topic-track use separate, differently-prefixed output directories, confirmed against the
# orchestrator's own invocation-building code - not guessed).
#
# Because RUN_STATE.json only ever marks a stage "completed" AFTER its script exits 0 and the
# self-chain trailer runs, a stage still showing status="running" (which is exactly the
# condition that gets a stage into this watchdog's retry path at all) can never have a
# genuinely-finished, trustworthy output on disk yet - so it is always safe to move any existing
# output_root/run_id directory and any matching set_manifest file aside (never delete) before
# retrying. This closes the retry path for exactly these 2 known-vulnerable compound stages;
# it deliberately does NOT generalize to arbitrary future stages, since doing that safely would
# require confirming the same "running status == no trustworthy output yet" invariant holds for
# each one individually, which has only been verified here for these two.
KNOWN_BLOCKING_SUB_OUTPUTS: dict[str, list[tuple[str, str]]] = {
    "step_05x_kc_evidence_stage_v3": [
        ("data/processed/evidence_stage_v3_candidate_bank", "data/processed/evidence_stage_v3_candidate_bank/_sets"),
        ("data/processed/evidence_stage_v3_scored_candidates", "data/processed/evidence_stage_v3_scored_candidates/_sets"),
        ("data/processed/evidence_stage_v3_evidence_packs", "data/processed/evidence_stage_v3_evidence_packs/_sets"),
    ],
    "topic_05x_evidence_stage_v3": [
        ("data/processed/topic_evidence_stage_v3_candidate_bank", "data/processed/topic_evidence_stage_v3_candidate_bank/_sets"),
        ("data/processed/topic_evidence_stage_v3_scored_candidates", "data/processed/topic_evidence_stage_v3_scored_candidates/_sets"),
        ("data/processed/topic_evidence_stage_v3_evidence_packs", "data/processed/topic_evidence_stage_v3_evidence_packs/_sets"),
    ],
}


def clear_stale_blocking_outputs(repo_root: Path, stage_id: str, run_id: str, *, dry_run: bool) -> list[str]:
    """For the 2 known-vulnerable compound stages above only: move aside (never delete) any
    existing output_root/run_id directory and any set-manifest file mentioning this run_id, so a
    retry doesn't immediately re-hit the same unconditional 'already exists' guard. No-op
    (returns no events) for every other stage_id."""
    pairs = KNOWN_BLOCKING_SUB_OUTPUTS.get(stage_id)
    if not pairs:
        return []

    events: list[str] = []
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = repo_root / "_quarantine" / "watchdog_stale_retry" / stamp / stage_id
    for output_root_rel, set_manifest_root_rel in pairs:
        output_dir = repo_root / output_root_rel / run_id
        if output_dir.exists():
            dest = backup_root / output_root_rel.replace("/", "__") / run_id
            events.append(f"MOVE_STALE_OUTPUT stage={stage_id} run={run_id} {output_dir} -> {dest}")
            if not dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(output_dir), str(dest))

        set_manifest_dir = repo_root / set_manifest_root_rel
        if set_manifest_dir.exists():
            for candidate in set_manifest_dir.glob(f"*{run_id}*"):
                dest = backup_root / set_manifest_root_rel.replace("/", "__") / candidate.name
                events.append(f"MOVE_STALE_SET_MANIFEST stage={stage_id} run={run_id} {candidate} -> {dest}")
                if not dry_run:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(candidate), str(dest))

    return events


def sacct_state(job_id: str) -> str | None:
    """Returns the base state word (CANCELLED+ -> CANCELLED, TIMEOUT -> TIMEOUT, etc.) for the
    job's own top-level step (not .batch/.extern sub-steps) - None if sacct has no record at all
    (job_id malformed, or genuinely never submitted)."""
    try:
        out = subprocess.run(
            ["sacct", "-j", str(job_id), "--format=JobID,State", "--noheader", "--parsable2"],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in out.stdout.splitlines():
        parts = line.split("|")
        if len(parts) < 2:
            continue
        jid, state = parts[0].strip(), parts[1].strip()
        if jid == str(job_id):
            return state.split()[0].rstrip("+")
    return None


def find_run_state_files(repo_root: Path, *, run_id_filter: str | None) -> list[Path]:
    runs_root = repo_root / "data" / "processed" / "runs"
    if not runs_root.exists():
        return []
    if run_id_filter:
        candidate = runs_root / run_id_filter / "RUN_STATE.json"
        return [candidate] if candidate.exists() else []
    return sorted(runs_root.glob("*/RUN_STATE.json"))


def reconcile_one_run(state_path: Path, *, dry_run: bool, max_retries: int) -> list[str]:
    events: list[str] = []
    state = json.loads(state_path.read_text(encoding="utf-8"))
    run_id = state.get("run_id") or state_path.parent.name
    stages = state.get("stages") or {}
    changed = False

    for stage_id, entry in list(stages.items()):
        if not isinstance(entry, dict) or entry.get("status") != "running":
            continue
        job_id = entry.get("job_id")
        if not job_id:
            continue
        state_word = sacct_state(job_id)
        if state_word is None:
            events.append(f"NO_SACCT_RECORD run={run_id} stage={stage_id} job={job_id} (skipping - too new or purged)")
            continue
        if state_word in STILL_ALIVE_STATES:
            continue
        if state_word == "COMPLETED":
            events.append(
                f"ANOMALY run={run_id} stage={stage_id} job={job_id} sacct=COMPLETED but "
                f"RUN_STATE still status=running - advance_run.py trailer likely never ran "
                f"(e.g. --no-self-chain) or crashed after the main runner but before the "
                f"trailer; NOT auto-resubmitted (job genuinely finished), needs a human look."
            )
            continue

        # Genuinely dead, non-COMPLETED terminal state.
        retry_count = int(entry.get("watchdog_retry_count") or 0)
        events.append(f"STALLED run={run_id} stage={stage_id} job={job_id} sacct_state={state_word} retry_count={retry_count}")
        entry["status"] = "failed"
        entry["failure_reason"] = f"watchdog_detected_sacct_terminal_state:{state_word}"
        entry["finished_utc"] = entry.get("finished_utc") or None
        changed = True

        if retry_count >= max_retries:
            events.append(f"GIVING_UP run={run_id} stage={stage_id} - already retried {retry_count} time(s), leaving failed for a human to look at")
            continue

        repo_root = state_path.parents[2]

        if dry_run:
            events.extend(clear_stale_blocking_outputs(repo_root, stage_id, run_id, dry_run=True))
            events.append(f"WOULD_RESUBMIT run={run_id} stage={stage_id}")
            continue

        events.extend(clear_stale_blocking_outputs(repo_root, stage_id, run_id, dry_run=False))

        entry["watchdog_retry_count"] = retry_count + 1
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        changed = False  # already flushed

        result = subprocess.run(
            [sys.executable, str(repo_root / "scripts" / "kc_l_orchestrator.py"),
             "run-stage", stage_id, "--run-id", run_id],
            capture_output=True, text=True, timeout=120, check=False, cwd=str(repo_root),
        )
        events.append(f"RESUBMIT_RC={result.returncode} run={run_id} stage={stage_id}")
        for line in (result.stdout or "").splitlines():
            events.append(f"  {line}")
        for line in (result.stderr or "").splitlines():
            events.append(f"  STDERR: {line}")
        # Reload since resubmission (run_stage) also writes RUN_STATE.json for this stage.
        state = json.loads(state_path.read_text(encoding="utf-8"))
        stages = state.get("stages") or {}

    if changed and not dry_run:
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    return events


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--poll-interval-seconds", type=int, default=180)
    ap.add_argument("--max-retries", type=int, default=1)
    ap.add_argument(
        "--run-id", default=None,
        help="Only reconcile this one run_id, not every run under data/processed/runs/ - "
             "use this for an active, in-flight run so old abandoned/test runs are never "
             "touched or resurrected.",
    )
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()

    print("RECONCILE_WATCHDOG_START")
    print(f"REPO_ROOT={repo_root}")
    print(f"DRY_RUN={int(args.dry_run)}")
    print(f"ONCE={int(args.once)}")
    print(f"POLL_INTERVAL_SECONDS={args.poll_interval_seconds}")
    print(f"MAX_RETRIES={args.max_retries}")
    print(f"RUN_ID_FILTER={args.run_id or '(all runs)'}", flush=True)

    while True:
        pass_events: list[str] = []
        for state_path in find_run_state_files(repo_root, run_id_filter=args.run_id):
            try:
                pass_events.extend(reconcile_one_run(state_path, dry_run=args.dry_run, max_retries=args.max_retries))
            except Exception as exc:  # noqa: BLE001 - one bad run's state must not kill the watchdog
                pass_events.append(f"RECONCILE_ERROR path={state_path} error={exc!r}")

        if pass_events:
            for line in pass_events:
                print(line, flush=True)
        else:
            print("PASS_CLEAN=1 (no running stages found dead)", flush=True)

        if args.once:
            break
        time.sleep(args.poll_interval_seconds)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
