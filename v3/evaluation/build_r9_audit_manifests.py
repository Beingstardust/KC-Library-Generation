#!/usr/bin/env python3
"""Create small reproducibility manifests for R9 evaluation experiments."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
import time
from typing import Any


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_pair(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("expected key=value")
    key, val = value.split("=", 1)
    key = key.strip()
    if not key:
        raise argparse.ArgumentTypeError("empty key")
    return key, val


def git_head(repo: pathlib.Path) -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        return out.strip() or None
    except Exception:
        return None


def build_path_rows(pairs: list[tuple[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for label, raw_path in pairs:
        path = pathlib.Path(raw_path)
        exists = path.exists()
        row: dict[str, Any] = {
            "label": label,
            "path": str(path),
            "exists": exists,
        }
        if exists and path.is_file():
            row.update({
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            })
        rows.append(row)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", required=True, type=pathlib.Path)
    ap.add_argument("--repo-root", required=True, type=pathlib.Path)
    ap.add_argument("--run-prefix", required=True)
    ap.add_argument("--path", action="append", default=[], type=parse_pair,
                    help="label=/absolute/or/relative/path; repeatable")
    ap.add_argument("--metadata", action="append", default=[], type=parse_pair,
                    help="key=value metadata string; repeatable")
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    created_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    metadata = dict(args.metadata)
    metadata.update({
        "run_prefix": args.run_prefix,
        "repo_root": str(args.repo_root),
        "repo_head": git_head(args.repo_root),
        "created_utc": created_utc,
    })
    rows = build_path_rows(args.path)

    hash_manifest = {
        "created_utc": created_utc,
        "run_prefix": args.run_prefix,
        "files": rows,
    }
    code_manifest = {
        "created_utc": created_utc,
        "run_prefix": args.run_prefix,
        "repo_root": str(args.repo_root),
        "repo_head": metadata["repo_head"],
        "code_files": [
            row for row in rows
            if row["label"].startswith(("code:", "job:", "prompt:", "dos_code:", "profile:"))
        ],
    }
    environment_manifest = {
        "created_utc": created_utc,
        "run_prefix": args.run_prefix,
        "metadata": metadata,
    }

    (args.out_dir / "hash_manifest.json").write_text(
        json.dumps(hash_manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    (args.out_dir / "code_manifest.json").write_text(
        json.dumps(code_manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    (args.out_dir / "environment_manifest.json").write_text(
        json.dumps(environment_manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(f"manifests -> {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
