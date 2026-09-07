from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
import traceback
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    import yaml  # type: ignore
except Exception:
    yaml = None


SCRIPT_PATH = Path(__file__).resolve()
DEFAULT_REPO_ROOT = SCRIPT_PATH.parents[3]
SRC_DIR = DEFAULT_REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from kc_l.audit.manifests import try_cmd_version  # noqa: E402
from kc_l.utils.hash import file_stat, sha256_file  # noqa: E402


DEFAULT_INPUT_RUN_ID = "2026-03-06_002046_step4_3_1"
STEP_NAME = "step4_4_freeze"
EXPECTED_DOC_COUNT = 8
ACTIVE_STEP3 = Path("data/processed/doctree/_sets/ACTIVE_STEP3_SET.txt")
ACTIVE_STEP3_6 = Path("data/processed/blockstore_math_salvaged/_sets/ACTIVE_STEP3_6_SET.txt")
ACTIVE_STEP4_PATCHES = Path("data/processed/retrieval_index/_sets/ACTIVE_STEP4_PATCHES_SET.txt")
ACTIVE_STEP4_SET = Path("data/processed/retrieval_index/_sets/ACTIVE_STEP4_SET.txt")
RETRIEVAL_SETS_DIR = Path("data/processed/retrieval_index/_sets")
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


def _load_yaml(path: Path) -> Dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required when using --config.")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise RuntimeError(f"Config must be a YAML mapping: {path}")
    return data


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _ts_local(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d_%H%M%S")


def _rel_path(path: Path, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def _resolve_active_pointer(repo_root: Path, rel_path: Path) -> Tuple[Path, Path, str]:
    pointer_path = (repo_root / rel_path).resolve()
    if not pointer_path.exists():
        raise FileNotFoundError(f"Missing ACTIVE pointer: {rel_path.as_posix()}")
    target_name = pointer_path.read_text(encoding="utf-8").strip()
    if not target_name:
        raise RuntimeError(f"ACTIVE pointer is empty: {rel_path.as_posix()}")
    target_path = (pointer_path.parent / target_name).resolve()
    if not target_path.exists():
        raise FileNotFoundError(
            f"ACTIVE pointer target missing: {target_name} (from {rel_path.as_posix()})"
        )
    return pointer_path, target_path, target_name


def _describe_path(path: Path, repo_root: Path) -> Dict[str, Any]:
    exists = path.exists()
    kind = "directory" if exists and path.is_dir() else "file"
    item: Dict[str, Any] = {
        "path": _rel_path(path, repo_root),
        "exists": exists,
        "kind": kind,
    }
    if not exists:
        return item
    stat = file_stat(path)
    item["stat"] = stat
    mtime_utc = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    if path.is_file():
        item["sha256"] = sha256_file(path)
        item["size_bytes"] = stat["size"]
        item["mtime_utc"] = mtime_utc
    else:
        item["mtime_utc"] = mtime_utc
        with suppress(Exception):
            item["child_count"] = sum(1 for _ in path.iterdir())
    return item


def _mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, obj: Any) -> None:
    _mkdir(path.parent)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    _mkdir(path.parent)
    path.write_text(text, encoding="utf-8")


def _write_json_exclusive(path: Path, obj: Any) -> None:
    _mkdir(path.parent)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def _git_snapshot(repo_root: Path) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    commands = {
        "git_head": ["git", "rev-parse", "HEAD"],
        "git_status_porcelain": ["git", "status", "--porcelain"],
        "git_branch": ["git", "branch", "--show-current"],
    }
    for key, cmd in commands.items():
        try:
            proc = subprocess.run(
                cmd,
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            out[key] = {
                "returncode": proc.returncode,
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip(),
            }
        except Exception as exc:
            out[key] = {"error": repr(exc)}
    return out


def _environment_snapshot(repo_root: Path) -> Dict[str, Any]:
    return {
        "created_utc": _now_utc(),
        "platform": platform.platform(),
        "python_executable": sys.executable,
        "python_version": sys.version,
        "cwd": os.getcwd(),
        "repo_root": str(repo_root),
        "git": _git_snapshot(repo_root),
    }


def _tool_versions() -> Dict[str, Any]:
    versions = {
        "python": {
            "version": platform.python_version(),
            "executable": sys.executable,
        },
        "git": try_cmd_version(["git", "--version"]),
        "ollama": try_cmd_version(["ollama", "--version"]),
    }
    with suppress(Exception):
        import numpy as np  # type: ignore

        versions["numpy"] = {"version": np.__version__}
    if yaml is not None:
        versions["pyyaml"] = {"version": getattr(yaml, "__version__", "unknown")}
    return versions


class AuditLogger:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.logs_dir = run_dir / "logs"
        _mkdir(self.logs_dir)
        self.stdout_log = self.logs_dir / "stdout.log"
        self.stderr_log = self.logs_dir / "stderr.log"
        self.stdout_log.write_text("", encoding="utf-8")
        self.stderr_log.write_text("", encoding="utf-8")

    def info(self, message: str) -> None:
        line = f"{message}\n"
        print(message)
        with self.stdout_log.open("a", encoding="utf-8") as handle:
            handle.write(line)

    def error(self, message: str) -> None:
        line = f"{message}\n"
        print(message, file=sys.stderr)
        with self.stderr_log.open("a", encoding="utf-8") as handle:
            handle.write(line)

    def exception(self, exc: BaseException) -> None:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        self.error(tb.rstrip())


def _choose_output_ids(repo_root: Path) -> Tuple[str, str, Path]:
    stamp_dt = datetime.now()
    while True:
        stamp = _ts_local(stamp_dt)
        freeze_run_id = f"{stamp}_{STEP_NAME}"
        set_path = (repo_root / RETRIEVAL_SETS_DIR / f"{stamp}_step4_index_set.json").resolve()
        run_dir = (repo_root / RUNS_DIR / freeze_run_id).resolve()
        if not set_path.exists() and not run_dir.exists():
            return stamp, freeze_run_id, set_path
        stamp_dt = stamp_dt + timedelta(seconds=1)


def _load_run_summary(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"Expected JSON object: {path}")
    return data


def _expected_doc_entries(repo_root: Path, retrieval_run_id: str) -> List[Dict[str, Any]]:
    run_summary_path = (repo_root / RUNS_DIR / retrieval_run_id / "summary.json").resolve()
    if not run_summary_path.exists():
        raise FileNotFoundError(f"Missing retrieval run summary: {_rel_path(run_summary_path, repo_root)}")
    summary = _load_run_summary(run_summary_path)
    rows_summary = summary.get("rows_summary")
    if not isinstance(rows_summary, list):
        raise RuntimeError("Retrieval run summary.json is missing rows_summary.")
    if len(rows_summary) != EXPECTED_DOC_COUNT:
        raise RuntimeError(
            f"Expected {EXPECTED_DOC_COUNT} docs in retrieval summary, found {len(rows_summary)}."
        )
    return rows_summary


def _artifact_entry(
    repo_root: Path,
    doc_root: Path,
    rel_artifact: str,
    required: bool,
    directory: bool = False,
) -> Dict[str, Any]:
    artifact_path = (doc_root / rel_artifact).resolve()
    entry = _describe_path(artifact_path, repo_root)
    entry["required"] = required
    if directory and entry["kind"] != "directory":
        entry["kind"] = "directory"
    return entry


def _build_doc_entry(
    repo_root: Path,
    doc_id: str,
    retrieval_run_id: str,
    doc_root: Path,
) -> Tuple[Dict[str, Any], List[str], List[str]]:
    missing_required: List[str] = []
    missing_optional: List[str] = []
    artifacts: Dict[str, Dict[str, Any]] = {}

    for rel_artifact in REQUIRED_FILE_ARTIFACTS:
        entry = _artifact_entry(repo_root, doc_root, rel_artifact, required=True)
        if not entry["exists"] or entry["kind"] != "file":
            missing_required.append(rel_artifact)
        artifacts[rel_artifact] = entry

    for rel_artifact in REQUIRED_DIR_ARTIFACTS:
        entry = _artifact_entry(repo_root, doc_root, rel_artifact, required=True, directory=True)
        if not entry["exists"] or entry["kind"] != "directory":
            missing_required.append(rel_artifact)
        artifacts[rel_artifact] = entry

    for rel_artifact in OPTIONAL_FILE_ARTIFACTS:
        entry = _artifact_entry(repo_root, doc_root, rel_artifact, required=False)
        if not entry["exists"]:
            entry["missing_optional"] = True
            missing_optional.append(rel_artifact)
        artifacts[rel_artifact] = entry

    return (
        {
            "doc_id": doc_id,
            "retrieval_run_id": retrieval_run_id,
            "retrieval_out_dir": _rel_path(doc_root, repo_root),
            "artifacts": artifacts,
            "missing_optional": missing_optional,
        },
        missing_required,
        missing_optional,
    )


def _input_manifest(
    repo_root: Path,
    retrieval_run_id: str,
    pointer_info: Dict[str, Dict[str, Any]],
    docs: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    run_dir = (repo_root / RUNS_DIR / retrieval_run_id).resolve()
    manifest_docs: Dict[str, Any] = {}
    total_artifacts = 0
    for doc_id, entry in docs.items():
        doc_manifest = {
            "retrieval_out_dir": entry["retrieval_out_dir"],
            "artifacts": {},
        }
        for name, artifact in entry["artifacts"].items():
            doc_manifest["artifacts"][name] = artifact
            total_artifacts += 1
        manifest_docs[doc_id] = doc_manifest
    return {
        "created_utc": _now_utc(),
        "retrieval_run_id": retrieval_run_id,
        "retrieval_run_audit_dir": _rel_path(run_dir, repo_root),
        "retrieval_run_summary": _describe_path(run_dir / "summary.json", repo_root),
        "active_pointers": pointer_info,
        "docs": manifest_docs,
        "counts": {
            "n_docs": len(manifest_docs),
            "n_artifact_entries": total_artifacts,
        },
    }


def _output_manifest(
    repo_root: Path,
    set_path: Path,
    active_pointer_path: Path,
) -> Dict[str, Any]:
    return {
        "created_utc": _now_utc(),
        "outputs": [
            _describe_path(set_path, repo_root),
            _describe_path(active_pointer_path, repo_root),
        ],
    }


def _provenance(
    repo_root: Path,
    retrieval_run_id: str,
    pointer_info: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    patches_target_rel = Path(pointer_info["step4_patches_set_active"]["target_path"])
    patches_set = json.loads((repo_root / patches_target_rel).read_text(encoding="utf-8"))
    return {
        "retrieval_run_id": retrieval_run_id,
        "retrieval_run_audit_dir": f"data/runs/{retrieval_run_id}",
        "active_pointers": {
            key: {
                "pointer_path": value["pointer_path"],
                "target_name": value["target_name"],
                "target_path": value["target_path"],
            }
            for key, value in pointer_info.items()
        },
        "step4_patches_set": {
            "set_id": patches_set.get("set_id"),
            "kind": patches_set.get("kind"),
            "target_path": pointer_info["step4_patches_set_active"]["target_path"],
        },
    }


def run() -> int:
    parser = argparse.ArgumentParser(description="STEP 4.4: Freeze retrieval index set.")
    parser.add_argument("--run-id", default=None, help=f"Retrieval build run id. Default: {DEFAULT_INPUT_RUN_ID}")
    parser.add_argument("--config", default=None, help="Optional YAML config with plain top-level keys.")
    parser.add_argument("--repo-root", default=None, help="Repository root. Default: current workspace.")
    args = parser.parse_args()

    raw_cfg: Dict[str, Any] = {}
    if args.config:
        raw_cfg = _load_yaml(Path(args.config).resolve())

    repo_root = Path(args.repo_root or raw_cfg.get("repo_root") or DEFAULT_REPO_ROOT).resolve()
    retrieval_run_id = args.run_id or raw_cfg.get("run_id") or DEFAULT_INPUT_RUN_ID

    stamp, freeze_run_id, set_path = _choose_output_ids(repo_root)
    run_dir = (repo_root / RUNS_DIR / freeze_run_id).resolve()
    _mkdir(run_dir)
    logger = AuditLogger(run_dir)
    started = time.perf_counter()

    config_snapshot = {
        "schema_version": "1.0",
        "step": STEP_NAME,
        "retrieval_run_id": retrieval_run_id,
        "repo_root": str(repo_root),
        "config_path": str(Path(args.config).resolve()) if args.config else None,
        "raw_config": raw_cfg,
        "effective": {
            "run_id": retrieval_run_id,
            "repo_root": str(repo_root),
            "set_manifest_name": set_path.name,
            "active_pointer": ACTIVE_STEP4_SET.as_posix(),
        },
    }
    _write_json(run_dir / "config.snapshot.json", config_snapshot)
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

    active_pointer_path = (repo_root / ACTIVE_STEP4_SET).resolve()

    try:
        logger.info(f"Freezing retrieval index set for run_id={retrieval_run_id}")

        pointer_specs = {
            "step3_set_active": ACTIVE_STEP3,
            "step3_6_set_active": ACTIVE_STEP3_6,
            "step4_patches_set_active": ACTIVE_STEP4_PATCHES,
        }
        pointer_info: Dict[str, Dict[str, Any]] = {}
        for key, rel_path in pointer_specs.items():
            pointer_path, target_path, target_name = _resolve_active_pointer(repo_root, rel_path)
            pointer_info[key] = {
                "pointer_path": _rel_path(pointer_path, repo_root),
                "target_name": target_name,
                "target_path": _rel_path(target_path, repo_root),
            }

        doc_rows = _expected_doc_entries(repo_root, retrieval_run_id)
        docs_payload: Dict[str, Dict[str, Any]] = {}
        validation_rows: List[Dict[str, Any]] = []
        missing_required_total = 0
        missing_optional_total = 0

        for row in doc_rows:
            doc_id = row.get("doc_id")
            if not isinstance(doc_id, str) or not doc_id:
                raise RuntimeError("rows_summary contains a doc entry without doc_id.")
            doc_root = (repo_root / "data/processed/retrieval_index" / doc_id / retrieval_run_id).resolve()
            if not doc_root.exists():
                raise FileNotFoundError(
                    f"Missing retrieval output directory: {_rel_path(doc_root, repo_root)}"
                )
            doc_entry, missing_required, missing_optional = _build_doc_entry(
                repo_root=repo_root,
                doc_id=doc_id,
                retrieval_run_id=retrieval_run_id,
                doc_root=doc_root,
            )
            docs_payload[doc_id] = doc_entry
            missing_required_total += len(missing_required)
            missing_optional_total += len(missing_optional)
            validation_rows.append(
                {
                    "doc_id": doc_id,
                    "ok": len(missing_required) == 0,
                    "missing_required": missing_required,
                    "missing_optional": missing_optional,
                }
            )

        _write_json(
            run_dir / "input_manifest.json",
            _input_manifest(
                repo_root=repo_root,
                retrieval_run_id=retrieval_run_id,
                pointer_info=pointer_info,
                docs=docs_payload,
            ),
        )

        failures = [row for row in validation_rows if not row["ok"]]
        if failures:
            raise RuntimeError(
                "Missing required Step 4.3.1 artifacts: "
                + json.dumps(failures, ensure_ascii=False)
            )

        set_payload = {
            "schema_version": "1.0",
            "kind": "step4_index_set",
            "set_id": f"{stamp}_step4_index_set",
            "created_utc": _now_utc(),
            "freeze_run_id": freeze_run_id,
            "retrieval_run_id": retrieval_run_id,
            "retrieval_root": "data/processed/retrieval_index",
            "provenance": _provenance(repo_root, retrieval_run_id, pointer_info),
            "docs": docs_payload,
            "counts": {
                "n_docs": len(docs_payload),
                "missing_required_total": missing_required_total,
                "missing_optional_total": missing_optional_total,
            },
        }
        _write_json_exclusive(set_path, set_payload)
        _write_text(active_pointer_path, set_path.name)

        _write_json(run_dir / "output_manifest.json", _output_manifest(repo_root, set_path, active_pointer_path))

        elapsed = round(time.perf_counter() - started, 3)
        timings = {
            "elapsed_seconds": elapsed,
            "retrieval_run_id": retrieval_run_id,
            "n_docs": len(docs_payload),
        }
        _write_json(run_dir / "timings.json", timings)

        summary = {
            "run_id": freeze_run_id,
            "step": STEP_NAME,
            "status": "success",
            "created_utc": _now_utc(),
            "retrieval_run_id": retrieval_run_id,
            "set_manifest": _rel_path(set_path, repo_root),
            "active_pointer": ACTIVE_STEP4_SET.as_posix(),
            "n_docs": len(docs_payload),
            "missing_required_total": missing_required_total,
            "missing_optional_total": missing_optional_total,
            "docs": validation_rows,
        }
        _write_json(run_dir / "summary.json", summary)

        logger.info(f"Wrote set manifest: {_rel_path(set_path, repo_root)}")
        logger.info(f"Updated ACTIVE pointer: {ACTIVE_STEP4_SET.as_posix()} -> {set_path.name}")
        logger.info(f"Freeze audit dir: {_rel_path(run_dir, repo_root)}")
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        logger.exception(exc)
        elapsed = round(time.perf_counter() - started, 3)
        _write_json(
            run_dir / "timings.json",
            {
                "elapsed_seconds": elapsed,
                "retrieval_run_id": retrieval_run_id,
                "status": "failed",
            },
        )
        _write_json(
            run_dir / "summary.json",
            {
                "run_id": freeze_run_id,
                "step": STEP_NAME,
                "status": "failed",
                "created_utc": _now_utc(),
                "retrieval_run_id": retrieval_run_id,
                "error": repr(exc),
            },
        )
        raise


if __name__ == "__main__":
    raise SystemExit(run())
