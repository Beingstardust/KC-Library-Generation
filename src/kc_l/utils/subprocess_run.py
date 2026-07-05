from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional, Tuple


def run_cmd(
    cmd: List[str],
    cwd: Optional[Path],
    stdout_path: Path,
    stderr_path: Path,
    timeout_s: Optional[int] = None,
) -> Tuple[int, str, str]:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)

    p = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
    )
    try:
        out, err = p.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate()
        err = (err or "") + "\nTIMEOUT"
        rc = 124
    else:
        rc = p.returncode

    stdout_path.write_text(out or "", encoding="utf-8", errors="replace")
    stderr_path.write_text(err or "", encoding="utf-8", errors="replace")
    return rc, out or "", err or ""