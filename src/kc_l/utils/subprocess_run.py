from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

_IS_POSIX = os.name == "posix"


def run_cmd(
    cmd: List[str],
    cwd: Optional[Path],
    stdout_path: Path,
    stderr_path: Path,
    timeout_s: Optional[int] = None,
) -> Tuple[int, str, str]:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)

    # stdout/stderr are passed as real file handles (not subprocess.PIPE) so the child
    # writes directly to disk as it produces output - a live `tail -f` on these paths shows
    # progress in real time. The previous PIPE + communicate approach buffered everything
    # in memory until the process exited, which made a stalled subprocess indistinguishable
    # from a healthy long-running one from the log files alone.
    with open(stdout_path, "w", encoding="utf-8", errors="replace") as stdout_f, open(
        stderr_path, "w", encoding="utf-8", errors="replace"
    ) as stderr_f:
        p = subprocess.Popen(
            cmd,
            cwd=str(cwd) if cwd else None,
            stdout=stdout_f,
            stderr=stderr_f,
            shell=False,
            # start_new_session (POSIX only, no-op elsewhere): makes the child its own process
            # group leader, so a timeout kill can take out the whole tree - not just the direct
            # child. Confirmed necessary for MinerU specifically: its CLI spawns a separate
            # `mineru.cli.fast_api` server as a child subprocess, which is NOT automatically
            # killed when only the parent PID is signaled, and would otherwise survive a
            # timeout-triggered kill and hold its port/GPU memory into the next retry attempt.
            start_new_session=_IS_POSIX,
        )
        try:
            rc = p.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            if _IS_POSIX:
                try:
                    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                p.kill()
            p.wait()
            stderr_f.write("\nTIMEOUT")
            rc = 124

    return rc, "", ""