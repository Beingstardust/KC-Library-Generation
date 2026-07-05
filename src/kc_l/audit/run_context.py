from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import os
import platform
import subprocess
import sys

from kc_l.utils.json_io import write_json
from kc_l.utils.hashing import sha256_file


def utc_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _safe_cmd(cmd: list[str], cwd: Path | None = None) -> str | None:
    try:
        out = subprocess.check_output(cmd, cwd=str(cwd) if cwd else None, stderr=subprocess.DEVNULL, text=True).strip()
        return out if out else None
    except Exception:
        return None


def capture_git_state(repo_root: Path) -> dict[str, Any]:
    commit = _safe_cmd(["git", "rev-parse", "HEAD"], cwd=repo_root)
    branch = _safe_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root)
    status = _safe_cmd(["git", "status", "--porcelain"], cwd=repo_root) or ""
    dirty = bool(status.strip())
    return {"commit": commit, "branch": branch, "dirty": dirty, "status_porcelain": status}


def capture_pip_freeze() -> str:
    out = _safe_cmd([sys.executable, "-m", "pip", "freeze"])
    return out or ""


def capture_system() -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "python_version": sys.version,
        "cwd": os.getcwd(),
    }


@dataclass(frozen=True)
class RunContext:
    run_id: str
    run_dir: Path
    repo_root: Path

    def init_dirs(self) -> None:
        (self.run_dir / "environment").mkdir(parents=True, exist_ok=True)
        (self.run_dir / "logs").mkdir(parents=True, exist_ok=True)
        (self.run_dir / "metrics").mkdir(parents=True, exist_ok=True)
        (self.run_dir / "errors").mkdir(parents=True, exist_ok=True)

    def write_environment(self) -> None:
        write_json(self.run_dir / "environment" / "system.json", capture_system())
        write_json(self.run_dir / "environment" / "git.json", capture_git_state(self.repo_root))
        (self.run_dir / "environment" / "pip_freeze.txt").write_text(capture_pip_freeze(), encoding="utf-8")

    def write_cli_invocation(self, argv: list[str]) -> None:
        write_json(self.run_dir / "cli_invocation.json", {"argv": argv})

    def write_config_used(self, config: dict[str, Any]) -> None:
        write_json(self.run_dir / "config_used.json", config)

    def write_inputs_manifest(self, inputs: dict[str, Path]) -> dict[str, Any]:
        manifest: dict[str, Any] = {}
        for k, p in inputs.items():
            manifest[k] = {
                "path": str(p),
                "sha256": sha256_file(p),
                "size_bytes": p.stat().st_size,
                "mtime": p.stat().st_mtime,
            }
        write_json(self.run_dir / "inputs_manifest.json", manifest)
        return manifest