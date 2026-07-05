from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
DEFAULT_INPUT_DIR = Path("data/input/course_materials")
DEFAULT_STEP2_CONFIG = Path("steps/step_02_pdf_ingest_blockstore/resources/step2.default.yaml")
STEP2_RUNNER = Path("steps/step_02_pdf_ingest_blockstore/scripts/run_step2.py")
STEP3_RUNNER = Path("steps/step_03_doctree_index/scripts/run_step3.py")
STEP3_CONFIG = Path("steps/step_03_doctree_index/resources/step3.default.yaml")


def _resolve_from_repo(path_text: str | Path) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def _repo_relative_text(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise RuntimeError(f"Config did not load as a mapping: {path}")
    return data


def _convert_to_safe_doc_id(stem: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]", "_", stem)
    safe = re.sub(r"_{2,}", "_", safe).strip("_")
    return safe or "DOC"


def _doc_id_assignments(pdf_paths: list[Path]) -> dict[Path, str]:
    files = sorted(pdf_paths, key=lambda path: (path.name.lower(), path.as_posix().lower()))
    groups: dict[str, list[Path]] = {}
    for pdf_path in files:
        base_doc_id = f"DM2_{_convert_to_safe_doc_id(pdf_path.stem)}"
        groups.setdefault(base_doc_id, []).append(pdf_path)

    doc_ids: dict[Path, str] = {}
    for base_doc_id in sorted(groups):
        grouped_files = sorted(groups[base_doc_id], key=lambda path: (path.name.lower(), path.as_posix().lower()))
        if len(grouped_files) == 1:
            doc_ids[grouped_files[0]] = base_doc_id
            continue
        for pdf_path in grouped_files:
            suffix = hashlib.sha1(pdf_path.name.encode("utf-8")).hexdigest().upper()[:8]
            doc_ids[pdf_path] = f"{base_doc_id}_{suffix}"
    return doc_ids


def _discover_pdfs(input_dir: Path) -> list[Path]:
    return sorted(
        [path for path in input_dir.iterdir() if path.is_file() and path.suffix.lower() == ".pdf"],
        key=lambda path: (path.name.lower(), path.as_posix().lower()),
    )


def _step2_active_pointer_path(cfg: dict[str, Any]) -> Path:
    processed_root = _resolve_from_repo(cfg["output"]["processed_blockstore_dir"])
    return processed_root / "_sets" / "ACTIVE_STEP2_SET.txt"


def _runtime_env() -> dict[str, str]:
    env = dict(os.environ)
    env["MINERU_TOOLS_CONFIG_JSON"] = str(REPO_ROOT / "data" / "cache" / "mineru" / "mineru.json")
    env["MINERU_MODEL_SOURCE"] = "local"
    env["HF_HOME"] = str(REPO_ROOT / "data" / "cache" / "hf_home")
    env["HF_HUB_CACHE"] = str(REPO_ROOT / "data" / "cache" / "hf_home" / "hub")
    env["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    env["YOLO_CONFIG_DIR"] = str(REPO_ROOT / "data" / "cache" / "ultralytics")

    src_text = str(SRC_ROOT)
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src_text if not existing_pythonpath else src_text + os.pathsep + existing_pythonpath
    return env


def _format_shell_command(argv: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Cross-platform corpus-level Step 2 intake for every PDF in data/input/course_materials."
    )
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR), help="Folder containing top-level input PDFs.")
    parser.add_argument("--config", default=str(DEFAULT_STEP2_CONFIG), help="Step 2 YAML config path.")
    parser.add_argument("--dry-run", action="store_true", help="Discover PDFs and planned doc IDs without running Step 2.")
    return parser


def _emit_summary(summary: dict[str, Any]) -> None:
    print("\nCORPUS INTAKE SUMMARY")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


def main() -> int:
    args = _build_parser().parse_args()

    input_dir = _resolve_from_repo(args.input_dir)
    config_path = _resolve_from_repo(args.config)
    step2_runner_path = _resolve_from_repo(STEP2_RUNNER)
    step3_runner_path = _resolve_from_repo(STEP3_RUNNER)
    step3_config_path = _resolve_from_repo(STEP3_CONFIG)

    step3_command = _format_shell_command(
        [
            sys.executable,
            _repo_relative_text(step3_runner_path),
            "--config",
            _repo_relative_text(step3_config_path),
        ]
    )

    summary: dict[str, Any] = {
        "mode": "dry_run" if args.dry_run else "execute",
        "input_dir": _repo_relative_text(input_dir),
        "step2_runner": _repo_relative_text(step2_runner_path),
        "step2_config": _repo_relative_text(config_path),
        "pdfs_discovered": 0,
        "discovered_docs": [],
        "pdfs_successfully_ingested": 0,
        "successful_docs": [],
        "failures": [],
        "active_step2_pointer": None,
        "next_step3_command": step3_command,
    }

    if not config_path.exists():
        summary["failures"].append({"error": f"Step 2 config not found: {_repo_relative_text(config_path)}"})
        _emit_summary(summary)
        return 1
    if not step2_runner_path.exists():
        summary["failures"].append({"error": f"Step 2 runner not found: {_repo_relative_text(step2_runner_path)}"})
        _emit_summary(summary)
        return 1
    if not input_dir.exists() or not input_dir.is_dir():
        summary["failures"].append({"error": f"Input directory not found: {_repo_relative_text(input_dir)}"})
        _emit_summary(summary)
        return 1

    try:
        cfg = _load_yaml(config_path)
    except Exception as exc:
        summary["failures"].append({"error": f"Failed to load Step 2 config: {exc}"})
        _emit_summary(summary)
        return 1

    active_pointer_path = _step2_active_pointer_path(cfg)
    summary["active_step2_pointer"] = _repo_relative_text(active_pointer_path)

    pdf_paths = _discover_pdfs(input_dir)
    doc_ids = _doc_id_assignments(pdf_paths)
    summary["pdfs_discovered"] = len(pdf_paths)
    summary["discovered_docs"] = [
        {"pdf": _repo_relative_text(pdf_path), "doc_id": doc_ids[pdf_path]}
        for pdf_path in pdf_paths
    ]

    if not pdf_paths:
        summary["failures"].append({"error": f"No PDFs found in {_repo_relative_text(input_dir)}"})
        _emit_summary(summary)
        return 1

    env = _runtime_env()
    exit_code = 0

    for index, pdf_path in enumerate(pdf_paths, start=1):
        doc_id = doc_ids[pdf_path]
        print(f"[{index}/{len(pdf_paths)}] {pdf_path.name} -> {doc_id}")
        if args.dry_run:
            continue

        cmd = [
            sys.executable,
            str(step2_runner_path),
            "--config",
            str(config_path),
            "--pdf",
            str(pdf_path),
            "--doc-id",
            doc_id,
        ]
        result = subprocess.run(cmd, cwd=REPO_ROOT, env=env, check=False)
        if result.returncode != 0:
            summary["failures"].append(
                {
                    "pdf": _repo_relative_text(pdf_path),
                    "doc_id": doc_id,
                    "returncode": result.returncode,
                }
            )
            exit_code = result.returncode
            break

        summary["successful_docs"].append({"pdf": _repo_relative_text(pdf_path), "doc_id": doc_id})
        summary["pdfs_successfully_ingested"] = len(summary["successful_docs"])

    _emit_summary(summary)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
