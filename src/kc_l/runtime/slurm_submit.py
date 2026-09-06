from __future__ import annotations

import subprocess
from pathlib import Path

# States sacct/squeue can report that mean the job is done and will never change again.
TERMINAL_STATES = frozenset({"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "OUT_OF_MEMORY", "NODE_FAIL", "BOOT_FAIL"})
SUCCESS_STATES = frozenset({"COMPLETED"})


class SlurmSubmitError(RuntimeError):
    pass


def sbatch_submit(script_path: str | Path, *, dependency_job_id: str | None = None) -> str:
    """Submit a rendered .slurm script via sbatch and return its job id (as a string).

    dependency_job_id, if given, submits with --dependency=afterok:<job_id> so this job only
    starts once the given job completes successfully - used to chain a multi-stage pipeline
    run without needing a long-lived process to stay alive between stages.
    """
    path = Path(script_path)
    if not path.exists():
        raise FileNotFoundError(f"SLURM script not found: {path}")

    cmd = ["sbatch"]
    if dependency_job_id:
        cmd.append(f"--dependency=afterok:{dependency_job_id}")
    cmd.append(str(path))

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise SlurmSubmitError(f"sbatch failed (rc={proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}")

    # Standard sbatch success output: "Submitted batch job 123456"
    stdout = proc.stdout.strip()
    tokens = stdout.split()
    if len(tokens) < 4 or not tokens[-1].isdigit():
        raise SlurmSubmitError(f"Could not parse job id from sbatch output: {stdout!r}")
    return tokens[-1]


def sacct_state(job_id: str) -> str | None:
    """Return the current State for job_id via sacct, or None if sacct has no record yet.

    Explicitly passes --format=JobID,State rather than relying on this cluster's default
    sacct format, which is known to hard-fail here ("ReqGRES is deprecated, please use
    ReqTRES") when invoked with no --format at all (confirmed via a captured diagnostic
    session on this cluster).
    """
    proc = subprocess.run(
        ["sacct", "-j", str(job_id), "--format=JobID,State", "--noheader", "--parsable2"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise SlurmSubmitError(f"sacct failed (rc={proc.returncode}): {proc.stderr.strip()}")

    # sacct emits one line per job step (e.g. "123456", "123456.batch", "123456.extern");
    # the bare job id (no ".suffix") is the overall job's own state.
    for line in proc.stdout.splitlines():
        parts = line.split("|")
        if len(parts) != 2:
            continue
        raw_job_id, state = parts
        if raw_job_id.strip() == str(job_id):
            return state.strip().split()[0] if state.strip() else None
    return None


def is_terminal(state: str | None) -> bool:
    return state is not None and state in TERMINAL_STATES


def is_success(state: str | None) -> bool:
    return state is not None and state in SUCCESS_STATES
