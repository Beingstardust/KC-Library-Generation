#!/usr/bin/env python3
"""Verify scripts/poll_fresh_run_requests.py.

Covers:
- --dry-run reports what WOULD happen (run_id, first_stage_id) without touching the request
  file or RUN_STATE.json.
- A real (non-dry-run) poll of a pending request: mints a run_id, writes RUN_STATE.json with
  the request's course_materials/hierarchy_path/overrides carried through, submits stage 1
  (step_02_pdf_ingest, monkeypatched sbatch_submit - no real SLURM dependency), marks the
  request status=running with the minted run_id recorded.
- A request missing required fields (course_materials) is marked failed with a reason, not
  silently skipped or crashed past.
- A request already in a non-pending status is left untouched (not reprocessed).
- Two pending requests in the same poll() call each get processed independently with distinct
  run_ids.

Uses a throwaway ui_state_root under the scratchpad-equivalent temp area (never touches the
real ui_state/fresh_run_requests/ path) and a throwaway run_id namespace under the real repo's
data/processed/runs/ (cleaned up at the end).
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

import poll_fresh_run_requests as poller  # noqa: E402
from kc_l.runtime import run_state as run_state_mod  # noqa: E402
from kc_l.runtime.layout import get_operator_layout  # noqa: E402

REAL_COURSE_MATERIALS = [
    "data/input/course_materials/data-preprocessing-book-Chapter 3n4.pdf",
    "data/input/course_materials/data-preprocessing-book-Chapter 7.pdf",
    "data/input/course_materials/introduction-to-data-mining-.pdf",
]
REAL_HIERARCHY_PATH = "data/input/hierarchy/data_mining_kc_hierarchy_revised_.json"

_FAKE_JOB_COUNTER = [1000]


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        raise SystemExit(f"Verification failed: {label}")


def _fake_sbatch_submit(script_path, *, dependency_job_id=None):
    _FAKE_JOB_COUNTER[0] += 1
    return str(_FAKE_JOB_COUNTER[0])


def _write_request(requests_dir: Path, name: str, obj: dict) -> Path:
    requests_dir.mkdir(parents=True, exist_ok=True)
    path = requests_dir / name
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    return path


def _cleanup_run_id(run_id: str) -> None:
    layout = get_operator_layout(REPO_ROOT)
    run_dir = layout.pipeline_runs_root / run_id
    if run_dir.exists():
        shutil.rmtree(run_dir)


def main() -> int:
    tmp_root = Path(tempfile.mkdtemp(prefix="kc_l_poll_verify_"))
    ui_state_root = tmp_root / "ui_state"
    requests_dir = ui_state_root / "fresh_run_requests"
    minted_run_ids: list[str] = []

    try:
        print("\n=== --dry-run: reports what would happen, touches nothing ===")
        req_path = _write_request(
            requests_dir,
            "req_dry_run.json",
            {
                "request_id": "11111111-aaaa-bbbb-cccc-111111111111",
                "created_utc": "2026-07-11T00:00:00Z",
                "course_materials": REAL_COURSE_MATERIALS,
                "hierarchy_path": REAL_HIERARCHY_PATH,
                "overrides": {},
                "status": "pending",
            },
        )
        results = poller.poll(REPO_ROOT, ui_state_root, dry_run=True)
        check("dry-run processed exactly 1 request", len(results) == 1)
        check("dry-run reports status=would_run", results[0]["status"] == "would_run")
        check("dry-run reports a minted run_id", bool(results[0].get("run_id")))
        check(
            "dry-run reports both zero-dependency bootstrap stages as ready",
            set(results[0]["bootstrap_ready_stage_ids"]) == {"step_02_pdf_ingest", "hierarchy_registry"},
        )
        on_disk = json.loads(req_path.read_text(encoding="utf-8"))
        check("dry-run left the request file's status untouched (still pending)", on_disk["status"] == "pending")
        check("dry-run did not write RUN_STATE.json", not run_state_mod.run_state_path(
            get_operator_layout(REPO_ROOT).pipeline_runs_root, results[0]["run_id"]
        ).exists())
        req_path.unlink()  # dry-run never claims it, so it would otherwise be picked up below

        print("\n=== real poll: mints run_id, writes RUN_STATE.json, submits stage 1, marks running ===")
        req_path2 = _write_request(
            requests_dir,
            "req_real.json",
            {
                "request_id": "22222222-aaaa-bbbb-cccc-222222222222",
                "created_utc": "2026-07-11T00:01:00Z",
                "course_materials": REAL_COURSE_MATERIALS,
                "hierarchy_path": REAL_HIERARCHY_PATH,
                "overrides": {"step_06_7_kc_draft_generation": {"model": "gemma4:31b"}},
                "status": "pending",
            },
        )
        with mock.patch.object(poller.orch.slurm_submit, "sbatch_submit", side_effect=_fake_sbatch_submit):
            results2 = poller.poll(REPO_ROOT, ui_state_root, dry_run=False)
        check("real poll processed exactly 1 request", len(results2) == 1)
        check("real poll reports status=running", results2[0]["status"] == "running")
        run_id = results2[0]["run_id"]
        minted_run_ids.append(run_id)

        on_disk2 = json.loads(req_path2.read_text(encoding="utf-8"))
        check("request file status flipped to running", on_disk2["status"] == "running")
        check("request file records the minted run_id", on_disk2["run_id"] == run_id)
        check("request file records started_utc", bool(on_disk2.get("started_utc")))

        layout = get_operator_layout(REPO_ROOT)
        state_path = run_state_mod.run_state_path(layout.pipeline_runs_root, run_id)
        check("RUN_STATE.json was written", state_path.exists())
        state = run_state_mod.load_run_state(state_path)
        check("RUN_STATE.json carries course_materials through", state["course_materials"] == REAL_COURSE_MATERIALS)
        check("RUN_STATE.json carries hierarchy_path through", state["hierarchy_path"] == REAL_HIERARCHY_PATH)
        check("RUN_STATE.json carries overrides through", state["overrides"] == {"step_06_7_kc_draft_generation": {"model": "gemma4:31b"}})
        check("RUN_STATE.json carries request_id through", state["request_id"] == "22222222-aaaa-bbbb-cccc-222222222222")
        check("step_02_pdf_ingest submitted (job_id recorded)", "step_02_pdf_ingest" in state["stages"])
        check("hierarchy_registry submitted too", "hierarchy_registry" in state["stages"])
        check(
            "step_02_pdf_ingest recorded 3 chained job_ids (one per document)",
            len(state["stages"]["step_02_pdf_ingest"].get("job_ids", [])) == 3,
        )
        check("run status stays running when both zero-dependency stages submit cleanly", state["status"] == "running")

        print("\n=== a request missing course_materials is marked failed, not crashed past ===")
        req_path3 = _write_request(
            requests_dir,
            "req_missing_fields.json",
            {
                "request_id": "33333333-aaaa-bbbb-cccc-333333333333",
                "created_utc": "2026-07-11T00:02:00Z",
                "status": "pending",
            },
        )
        with mock.patch.object(poller.orch.slurm_submit, "sbatch_submit", side_effect=_fake_sbatch_submit):
            results3 = poller.poll(REPO_ROOT, ui_state_root, dry_run=False)
        check("bad-request poll processed exactly 1 request", len(results3) == 1)
        check("bad request marked failed", results3[0]["status"] == "failed")
        on_disk3 = json.loads(req_path3.read_text(encoding="utf-8"))
        check("bad request file status is failed", on_disk3["status"] == "failed")
        check("bad request file names the missing field", "course_materials" in on_disk3["failure_reason"])

        print("\n=== a non-pending request is left untouched ===")
        already_running_path = _write_request(
            requests_dir,
            "req_already_running.json",
            {
                "request_id": "44444444-aaaa-bbbb-cccc-444444444444",
                "created_utc": "2026-07-11T00:03:00Z",
                "course_materials": REAL_COURSE_MATERIALS,
                "status": "running",
                "run_id": "some_earlier_run",
            },
        )
        with mock.patch.object(poller.orch.slurm_submit, "sbatch_submit", side_effect=_fake_sbatch_submit):
            results4 = poller.poll(REPO_ROOT, ui_state_root, dry_run=False)
        check("already-running request is not in this poll's results", len(results4) == 0)
        on_disk4 = json.loads(already_running_path.read_text(encoding="utf-8"))
        check("already-running request's run_id is untouched", on_disk4["run_id"] == "some_earlier_run")

        print("\n=== two fresh pending requests in one poll() call each get a distinct run_id ===")
        _write_request(
            requests_dir,
            "req_batch_a.json",
            {
                "request_id": "55555555-aaaa-bbbb-cccc-555555555555",
                "created_utc": "2026-07-11T00:04:00Z",
                "course_materials": REAL_COURSE_MATERIALS,
                "hierarchy_path": REAL_HIERARCHY_PATH,
                "status": "pending",
            },
        )
        _write_request(
            requests_dir,
            "req_batch_b.json",
            {
                "request_id": "66666666-aaaa-bbbb-cccc-666666666666",
                "created_utc": "2026-07-11T00:05:00Z",
                "course_materials": REAL_COURSE_MATERIALS,
                "hierarchy_path": REAL_HIERARCHY_PATH,
                "status": "pending",
            },
        )
        with mock.patch.object(poller.orch.slurm_submit, "sbatch_submit", side_effect=_fake_sbatch_submit):
            results5 = poller.poll(REPO_ROOT, ui_state_root, dry_run=False)
        check("batch poll processed exactly 2 requests", len(results5) == 2)
        run_ids5 = [r["run_id"] for r in results5]
        check("batch poll's two requests got distinct run_ids", len(set(run_ids5)) == 2)
        minted_run_ids.extend(run_ids5)
        for r in results5:
            check(f"batch request {r['request_path']} status=running", r["status"] == "running")

    finally:
        for rid in minted_run_ids:
            _cleanup_run_id(rid)
        shutil.rmtree(tmp_root, ignore_errors=True)

    print("\nALL poll_fresh_run_requests CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
