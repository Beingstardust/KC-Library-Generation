from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from kc_l.audit.manifests import env_snapshot, pip_freeze, try_cmd_version
from kc_l.utils.fs import ensure_dir, safe_relpath
from kc_l.utils.time import now_ts, run_id as mk_run_id


@dataclass
class RunAudit:
    run_dir: Path
    step_name: str
    tz_name: str

    logs_dir: Path
    tools_dir: Path
    env_dir: Path

    _kv_path: Path

    @staticmethod
    def from_config(cfg: Dict[str, Any], step_name: str, config_path: Path) -> "RunAudit":
        tz_name = cfg.get("project", {}).get("timezone", "Europe/Amsterdam")
        runs_dir = Path(cfg["output"]["runs_dir"])
        ensure_dir(runs_dir)

        ts = now_ts(tz_name)
        rid = mk_run_id(ts, step_name=step_name)

        run_dir = runs_dir / rid
        ensure_dir(run_dir)

        logs_dir = run_dir / "logs"
        tools_dir = run_dir / "tools"
        env_dir = run_dir / "env"
        ensure_dir(logs_dir)
        ensure_dir(tools_dir)
        ensure_dir(env_dir)

        # Snapshot config file exactly as used
        cfg_snapshot_path = run_dir / "config.snapshot.yaml"
        cfg_snapshot_path.write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")

        # Invocation capture (best effort)
        inv = {
            "argv": list(os.sys.argv),
            "cwd": os.getcwd(),
        }
        (run_dir / "invocation.json").write_text(json.dumps(inv, indent=2), encoding="utf-8")

        # Env snapshot
        (env_dir / "env_snapshot.json").write_text(json.dumps(env_snapshot(), indent=2), encoding="utf-8")
        pf = pip_freeze()
        (env_dir / "pip_freeze.txt").write_text(pf.get("text", json.dumps(pf, indent=2)), encoding="utf-8")

        # Tool versions (best effort)
        mineru_v = try_cmd_version(["mineru", "--version"])
        docling_v = try_cmd_version(["docling", "--version"])
        (tools_dir / "mineru_version.json").write_text(json.dumps(mineru_v, indent=2), encoding="utf-8")
        (tools_dir / "docling_version.json").write_text(json.dumps(docling_v, indent=2), encoding="utf-8")

        kv_path = run_dir / "kv.jsonl"
        return RunAudit(run_dir=run_dir, step_name=step_name, tz_name=tz_name, logs_dir=logs_dir, tools_dir=tools_dir, env_dir=env_dir, _kv_path=kv_path)

    def __enter__(self) -> "RunAudit":
        self.log_kv("status", "RUNNING")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc is None:
            self.log_kv("status", "SUCCESS")
        else:
            self.log_kv("status", "FAILED")
            self.log_kv("error", repr(exc))

    def log_kv(self, k: str, v: Any) -> None:
        rec = {"k": k, "v": v}
        with self._kv_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")