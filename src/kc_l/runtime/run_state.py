from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kc_l.utils.json_io import read_json, write_json

RUN_STATE_SCHEMA_VERSION = "kc_l_run_state_v1"


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_state_path(pipeline_runs_root: Path, run_id: str) -> Path:
    return pipeline_runs_root / run_id / "RUN_STATE.json"


def load_run_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"RUN_STATE.json not found: {path}")
    return read_json(path)


def new_run_state(
    run_id: str,
    *,
    course_materials: list[str] | None = None,
    hierarchy_path: str | None = None,
    overrides: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """course_materials/hierarchy_path/overrides/request_id are the fresh-run request's own
    fields (see ui_state/fresh_run_requests/ schema), carried into RUN_STATE.json so stages
    that need per-run inputs not derivable from any upstream stage's own output (step_02's
    document list, in particular) can read them without re-deriving or guessing. All default
    to None/empty for run states created outside the request-queue flow (e.g. existing
    verify scripts using new_run_state(run_id) directly) - those stages simply refuse (as
    already established elsewhere in this orchestrator) rather than silently defaulting to a
    historical document list.
    """
    return {
        "schema_version": RUN_STATE_SCHEMA_VERSION,
        "run_id": run_id,
        "request_id": request_id,
        "status": "running",
        "created_utc": _now_utc_iso(),
        "updated_utc": _now_utc_iso(),
        "course_materials": list(course_materials) if course_materials is not None else [],
        "hierarchy_path": hierarchy_path,
        "overrides": dict(overrides) if overrides is not None else {},
        "stages": {},
    }


def write_run_state(path: Path, state: dict[str, Any]) -> Path:
    state["updated_utc"] = _now_utc_iso()
    write_json(path, state)
    return path


def set_stage_submitted(
    state: dict[str, Any],
    stage_id: str,
    *,
    job_id: str,
    slurm_script_path: str,
    job_ids: list[str] | None = None,
    slurm_script_paths: list[str] | None = None,
) -> None:
    """job_id is always the LAST job in this stage's submission chain - for multi-invocation
    stages (e.g. step_02_pdf_ingest submitting one job per document, chained via
    --dependency=afterok) that is sufficient to track completion: SLURM's afterok dependency
    guarantees the last job only reaches COMPLETED if every job before it in the chain also
    succeeded, so polling just the last job_id's sacct state is enough to know the whole stage
    finished successfully. job_ids/slurm_script_paths (plural) are recorded too, for audit
    purposes, only when there is more than one job - single-invocation stages leave them unset,
    matching every stage wired before this field existed.
    """
    entry: dict[str, Any] = {
        "status": "running",
        "job_id": job_id,
        "slurm_script_path": slurm_script_path,
        "started_utc": _now_utc_iso(),
        "finished_utc": None,
        "output_root": None,
        "set_manifest_path": None,
        "run_folder_symlink": None,
    }
    if job_ids:
        entry["job_ids"] = list(job_ids)
    if slurm_script_paths:
        entry["slurm_script_paths"] = list(slurm_script_paths)
    state["stages"][stage_id] = entry


def set_stage_completed(
    state: dict[str, Any],
    stage_id: str,
    *,
    output_root: str | None,
    set_manifest_path: str | None,
    run_folder_symlink: str | None,
) -> None:
    entry = state["stages"].setdefault(stage_id, {})
    entry["status"] = "completed"
    entry["finished_utc"] = _now_utc_iso()
    entry["output_root"] = output_root
    entry["set_manifest_path"] = set_manifest_path
    entry["run_folder_symlink"] = run_folder_symlink


def set_stage_failed(state: dict[str, Any], stage_id: str, *, reason: str) -> None:
    entry = state["stages"].setdefault(stage_id, {})
    entry["status"] = "failed"
    entry["finished_utc"] = _now_utc_iso()
    entry["failure_reason"] = reason
    state["status"] = "failed"


def get_stage_entry(state: dict[str, Any], stage_id: str) -> dict[str, Any] | None:
    return state.get("stages", {}).get(stage_id)
