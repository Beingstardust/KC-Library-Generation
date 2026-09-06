#!/usr/bin/env python3
"""Short-lived poller for ui_state/fresh_run_requests/.

Meant to be invoked periodically (e.g. via cron) or manually - NOT a long-lived process. This
matches the explicit Milestone 4 design decision: SLURM's own scheduler (driven by run-stage's
self-chaining trailer, see advance_run.py) is what stays alive between pipeline stages, not
this poller. This script's only job is to notice a new request and kick off stage 1; every
stage after that advances itself.

Each invocation: scans for status=pending request files, and for each one - mints a run_id,
writes the initial RUN_STATE.json (carrying the request's course_materials/hierarchy_path/
overrides forward, never a hardcoded historical default), submits stage 1 via the same
run_stage() this orchestrator's CLI uses (which for step_02_pdf_ingest already handles
per-document submission internally - see Milestone 4 Part A), and marks the request
running/failed accordingly.

ui_state/fresh_run_requests/ lives in the standalone Streamlit console's OWN project tree
(kc_l_v2_streamlit_console/ui_state/, confirmed via that app's own ui_root()==
Path(__file__).parent and the real 20260531T162139Z freeze run's console log - see
ORCHESTRATOR_BUILD_STATE.md's "Streamlit-console-vs-CLI-chain investigation") - a genuinely
separate filesystem location from this pipeline repo, not a subdirectory of it. Never assume
it's reachable at a path relative to this repo; DEFAULT_UI_STATE_ROOT is the confirmed real
location on the primary compute cluster, overridable via --ui-state-root for local testing.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
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

DEFAULT_UI_STATE_ROOT = "/path/to/projects/kc_l_v2_streamlit_console/ui_state"

REQUEST_REQUIRED_KEYS = ("request_id", "course_materials")


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_request(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_request(path: Path, obj: dict[str, Any]) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def mint_run_id(request_id: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    short_id = (request_id or "").replace("-", "")[:8] or uuid.uuid4().hex[:8]
    return f"{stamp}_{short_id}"


def process_request(
    repo_root: Path,
    request_path: Path,
    request: dict[str, Any],
    *,
    dry_run: bool,
) -> dict[str, Any]:
    """Never raises for expected/handleable failures - marks the request 'failed' with a
    reason instead, so one bad request doesn't stop the poller from processing the rest.
    """
    missing = [k for k in REQUEST_REQUIRED_KEYS if not request.get(k)]
    if missing:
        request["status"] = "failed"
        request["failure_reason"] = f"missing required fields: {missing}"
        request["failed_utc"] = _now_utc_iso()
        if not dry_run:
            _write_request(request_path, request)
        return {"request_path": str(request_path), "status": "failed", "reason": request["failure_reason"]}

    run_id = mint_run_id(request["request_id"])
    state = run_state_mod.new_run_state(
        run_id,
        course_materials=request.get("course_materials") or [],
        hierarchy_path=request.get("hierarchy_path"),
        overrides=request.get("overrides") or {},
        request_id=request.get("request_id"),
    )

    if dry_run:
        # Bootstrap = every zero-dependency stage (currently step_02_pdf_ingest and, since it's
        # not yet run_stage_wired, hierarchy_registry too - see resolve_ready_stages' own
        # docstring for why this is a full graph scan rather than a hardcoded "stage 1").
        return {
            "request_path": str(request_path),
            "status": "would_run",
            "run_id": run_id,
            "bootstrap_ready_stage_ids": resolve_ready_stages(state),
        }

    layout = get_operator_layout(repo_root)
    state_path = run_state_mod.run_state_path(layout.pipeline_runs_root, run_id)
    # submit_ready_stages reloads RUN_STATE.json from disk itself (see its own docstring) -
    # this initial state (with course_materials/hierarchy_path/overrides/request_id) must be
    # written before calling it, or run_stage() would see a blank state with no course_materials.
    run_state_mod.write_run_state(state_path, state)
    result = submit_ready_stages(orch, repo_root, run_id, state_path, dry_run=False)

    submission_failures = result.get("submission_failures") or {}
    if submission_failures:
        # A genuine submission failure at bootstrap (e.g. step_02_pdf_ingest refusing for a
        # reason other than run_stage_wired) means this run never actually got off the ground -
        # unlike blocked_unwired_stage below, this IS a request-processing failure worth
        # surfacing back on the request itself, not just buried in RUN_STATE.json.
        request["status"] = "failed"
        request["run_id"] = run_id
        request["failure_reason"] = f"stage submission failed: {submission_failures}"
        request["failed_utc"] = _now_utc_iso()
        _write_request(request_path, request)
        return {"request_path": str(request_path), "status": "failed", "run_id": run_id, **result}

    # blocked_unwired_stage is a legitimate RUN state (visible in RUN_STATE.json itself), not a
    # request-processing failure - the request is marked running as soon as the run genuinely
    # exists and this poller successfully handed it off, regardless of whether every
    # zero-dependency stage happened to be wired yet.
    request["status"] = "running"
    request["run_id"] = run_id
    request["started_utc"] = _now_utc_iso()
    _write_request(request_path, request)
    return {"request_path": str(request_path), "status": "running", "run_id": run_id, **result}


def poll(repo_root: Path, ui_state_root: Path, *, dry_run: bool) -> list[dict[str, Any]]:
    requests_dir = ui_state_root / "fresh_run_requests"
    if not requests_dir.exists():
        return []

    results: list[dict[str, Any]] = []
    for path in sorted(requests_dir.glob("*.json")):
        try:
            request = _load_request(path)
        except Exception as exc:
            results.append({"request_path": str(path), "status": "error", "reason": f"unreadable JSON: {exc!r}"})
            continue

        if request.get("status") != "pending":
            continue

        # Claim immediately (before doing the real work) so a concurrent poller invocation
        # sees status != "pending" and skips it. This is a best-effort, non-atomic guard, not
        # a real lock - matches this project's existing risk-acceptance level (no file locking
        # exists anywhere else in this orchestrator either; see step_02_pdf_ingest's own
        # documented ACTIVE_STEP2_SET.txt race, resolved by avoiding concurrency at the source
        # rather than adding a lock). This poller is only ever expected to run as a single cron
        # invocation at a time, not multiple concurrent instances.
        if not dry_run:
            request["status"] = "claimed"
            _write_request(path, request)

        result = process_request(repo_root, path, request, dry_run=dry_run)
        results.append(result)

    return results


def main() -> int:
    ap = argparse.ArgumentParser(description="Short-lived poller for ui_state/fresh_run_requests/.")
    ap.add_argument("--repo-root", default=str(_SCRIPTS_DIR.parent))
    ap.add_argument("--ui-state-root", default=DEFAULT_UI_STATE_ROOT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    ui_state_root = Path(args.ui_state_root)

    print("KC_L_POLL_FRESH_RUN_REQUESTS=1")
    print(f"REPO_ROOT={repo_root}")
    print(f"UI_STATE_ROOT={ui_state_root}")

    results = poll(repo_root, ui_state_root, dry_run=args.dry_run)
    print(f"REQUEST_COUNT={len(results)}")
    for r in results:
        print(f"REQUEST\t{r.get('status')}\t{r.get('run_id', '')}\t{r['request_path']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
