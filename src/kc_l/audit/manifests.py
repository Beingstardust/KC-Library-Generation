from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from kc_l.utils.hash import sha256_file, file_stat
from kc_l.utils.fs import list_files_recursive, safe_relpath


def build_input_manifest(paths: List[Path]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for p in paths:
        if not p.exists():
            out.append({"path": str(p), "exists": False})
            continue
        out.append(
            {
                "path": str(p),
                "exists": True,
                "sha256": sha256_file(p),
                "stat": file_stat(p),
            }
        )
    return out


def build_output_manifest(root: Path) -> List[Dict[str, Any]]:
    files = list_files_recursive(root)
    out: List[Dict[str, Any]] = []
    for f in files:
        out.append(
            {
                "relpath": safe_relpath(f, root),
                "sha256": sha256_file(f),
                "stat": file_stat(f),
            }
        )
    return sorted(out, key=lambda x: x["relpath"])


def try_cmd_version(cmd: List[str]) -> Dict[str, Any]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return {
            "cmd": cmd,
            "returncode": p.returncode,
            "stdout": (p.stdout or "").strip(),
            "stderr": (p.stderr or "").strip(),
        }
    except Exception as e:
        return {"cmd": cmd, "error": repr(e)}


def env_snapshot() -> Dict[str, Any]:
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
    }


def pip_freeze() -> Dict[str, Any]:
    try:
        p = subprocess.run([sys.executable, "-m", "pip", "freeze"], capture_output=True, text=True, timeout=60)
        return {"returncode": p.returncode, "text": p.stdout}
    except Exception as e:
        return {"error": repr(e)}
