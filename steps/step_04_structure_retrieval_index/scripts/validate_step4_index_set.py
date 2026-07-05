from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


SCRIPT_PATH = Path(__file__).resolve()
DEFAULT_REPO_ROOT = SCRIPT_PATH.parents[3]
SRC_DIR = DEFAULT_REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from kc_l.audit.manifests import try_cmd_version  # noqa: E402


STEP_NAME = "step4_4_validate"
RUNS_DIR = Path("data/runs")

REQUIRED_FILE_ARTIFACTS = [
    "block_text_corpus.jsonl",
    "index_rows.jsonl",
    "index_summary.json",
    "retrieval_eval.json",
    "embeddings/embeddings.f32.npy",
    "embeddings/meta.json",
    "vector_index/faiss.index",
    "vector_index/meta.json",
    "lexical/meta.json",
    "lexical/vocab.json",
    "lexical/idf.f32.npy",
    "lexical/postings_docids.i32.npy",
    "lexical/postings_tfs.i16.npy",
    "lexical/postings_offsets.i64.npy",
]
OPTIONAL_FILE_ARTIFACTS = [
    "retrieval_diagnostics.json",
    "retrieval_eval_diagnostics.json",
]
REQUIRED_DIR_ARTIFACTS = [
    "retrieval_traces",
]


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _rel_path(path: Path, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def _mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, obj: Any) -> None:
    _mkdir(path.parent)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    _mkdir(path.parent)
    path.write_text(text, encoding="utf-8")


def _tool_versions() -> Dict[str, Any]:
    return {
        "python": {
            "version": platform.python_version(),
            "executable": sys.executable,
        },
        "git": try_cmd_version(["git", "--version"]),
        "ollama": try_cmd_version(["ollama", "--version"]),
    }


def _environment_snapshot(repo_root: Path) -> Dict[str, Any]:
    git_info: Dict[str, Any] = {}
    for name, cmd in {
        "git_head": ["git", "rev-parse", "HEAD"],
        "git_status_porcelain": ["git", "status", "--porcelain"],
    }.items():
        try:
            proc = subprocess.run(
                cmd,
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            git_info[name] = {
                "returncode": proc.returncode,
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip(),
            }
        except Exception as exc:
            git_info[name] = {"error": repr(exc)}
    return {
        "created_utc": _now_utc(),
        "platform": platform.platform(),
        "python_executable": sys.executable,
        "python_version": sys.version,
        "cwd": os.getcwd(),
        "repo_root": str(repo_root),
        "git": git_info,
    }


class AuditLogger:
    def __init__(self, run_dir: Path) -> None:
        self.logs_dir = run_dir / "logs"
        _mkdir(self.logs_dir)
        self.stdout_log = self.logs_dir / "stdout.log"
        self.stderr_log = self.logs_dir / "stderr.log"
        self.stdout_log.write_text("", encoding="utf-8")
        self.stderr_log.write_text("", encoding="utf-8")

    def info(self, message: str) -> None:
        print(message)
        with self.stdout_log.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")

    def error(self, message: str) -> None:
        print(message, file=sys.stderr)
        with self.stderr_log.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")

    def exception(self, exc: BaseException) -> None:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        self.error(tb.rstrip())


def _run_id() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H%M%S") + f"_{STEP_NAME}"


def _load_docs(data: Dict[str, Any]) -> Iterable[Tuple[str, Dict[str, Any]]]:
    docs = data.get("docs")
    if isinstance(docs, dict):
        for doc_id, entry in docs.items():
            yield str(doc_id), entry
        return
    if isinstance(docs, list):
        for entry in docs:
            if not isinstance(entry, dict):
                raise RuntimeError("docs list contains a non-object entry.")
            doc_id = entry.get("doc_id")
            if not isinstance(doc_id, str) or not doc_id:
                raise RuntimeError("docs list contains an entry without doc_id.")
            yield doc_id, entry
        return
    raise RuntimeError("Set manifest is missing a docs container.")


def _artifact_exists(repo_root: Path, doc_entry: Dict[str, Any], artifact_name: str, is_dir: bool) -> bool:
    artifacts = doc_entry.get("artifacts")
    if not isinstance(artifacts, dict):
        return False
    artifact = artifacts.get(artifact_name)
    if not isinstance(artifact, dict):
        return False
    rel_path = artifact.get("path")
    if not isinstance(rel_path, str) or not rel_path:
        return False
    path = (repo_root / rel_path).resolve()
    return path.is_dir() if is_dir else path.is_file()


def run() -> int:
    parser = argparse.ArgumentParser(description="Validate a Step 4 retrieval index set manifest.")
    parser.add_argument("set_json", help="Path to the set manifest JSON.")
    parser.add_argument("--repo-root", default=None, help="Repository root. Default: workspace root.")
    args = parser.parse_args()

    repo_root = Path(args.repo_root or DEFAULT_REPO_ROOT).resolve()
    set_json_path = Path(args.set_json)
    if not set_json_path.is_absolute():
        set_json_path = (repo_root / set_json_path).resolve()

    validator_run_id = _run_id()
    run_dir = (repo_root / RUNS_DIR / validator_run_id).resolve()
    _mkdir(run_dir)
    logger = AuditLogger(run_dir)
    started = time.perf_counter()

    _write_json(
        run_dir / "config.snapshot.json",
        {
            "schema_version": "1.0",
            "step": STEP_NAME,
            "repo_root": str(repo_root),
            "set_json": str(set_json_path),
        },
    )
    _write_json(
        run_dir / "invocation.json",
        {
            "argv": sys.argv,
            "cwd": os.getcwd(),
            "repo_root": str(repo_root),
        },
    )
    _write_json(run_dir / "environment_snapshot.json", _environment_snapshot(repo_root))
    _write_json(run_dir / "tool_versions.json", _tool_versions())
    _write_json(
        run_dir / "input_manifest.json",
        {
            "created_utc": _now_utc(),
            "inputs": [
                {
                    "path": _rel_path(set_json_path, repo_root) if set_json_path.exists() else str(set_json_path),
                    "exists": set_json_path.exists(),
                }
            ],
        },
    )

    try:
        if not set_json_path.exists():
            raise FileNotFoundError(f"Set manifest not found: {set_json_path}")

        data = json.loads(set_json_path.read_text(encoding="utf-8"))
        rows: List[Dict[str, Any]] = []
        failures = 0

        header = "doc_id | ok | missing_required_count | missing_optional_count"
        lines = [header]
        logger.info(f"Validating set manifest: {_rel_path(set_json_path, repo_root)}")

        for doc_id, entry in _load_docs(data):
            missing_required = 0
            missing_optional = 0

            for artifact_name in REQUIRED_FILE_ARTIFACTS:
                if not _artifact_exists(repo_root, entry, artifact_name, is_dir=False):
                    missing_required += 1
            for artifact_name in REQUIRED_DIR_ARTIFACTS:
                if not _artifact_exists(repo_root, entry, artifact_name, is_dir=True):
                    missing_required += 1
            for artifact_name in OPTIONAL_FILE_ARTIFACTS:
                if not _artifact_exists(repo_root, entry, artifact_name, is_dir=False):
                    missing_optional += 1

            ok = missing_required == 0
            if not ok:
                failures += 1

            row = {
                "doc_id": doc_id,
                "ok": ok,
                "missing_required_count": missing_required,
                "missing_optional_count": missing_optional,
            }
            rows.append(row)
            lines.append(
                f"{doc_id} | {'ok' if ok else 'fail'} | {missing_required} | {missing_optional}"
            )

        table_text = "\n".join(lines) + "\n"
        print(table_text, end="")
        _write_text(run_dir / "report.txt", table_text)

        summary = {
            "run_id": validator_run_id,
            "step": STEP_NAME,
            "status": "success" if failures == 0 else "failed",
            "created_utc": _now_utc(),
            "set_json": _rel_path(set_json_path, repo_root),
            "n_docs": len(rows),
            "rows": rows,
            "failures": failures,
        }
        _write_json(run_dir / "summary.json", summary)
        _write_json(
            run_dir / "output_manifest.json",
            {
                "created_utc": _now_utc(),
                "outputs": [
                    {"path": _rel_path(run_dir / "report.txt", repo_root), "exists": True},
                    {"path": _rel_path(run_dir / "summary.json", repo_root), "exists": True},
                ],
            },
        )
        _write_json(
            run_dir / "timings.json",
            {"elapsed_seconds": round(time.perf_counter() - started, 3)},
        )
        return 0 if failures == 0 else 2
    except Exception as exc:
        logger.exception(exc)
        _write_json(
            run_dir / "summary.json",
            {
                "run_id": validator_run_id,
                "step": STEP_NAME,
                "status": "failed",
                "created_utc": _now_utc(),
                "error": repr(exc),
            },
        )
        _write_json(
            run_dir / "timings.json",
            {"elapsed_seconds": round(time.perf_counter() - started, 3)},
        )
        raise


if __name__ == "__main__":
    raise SystemExit(run())
