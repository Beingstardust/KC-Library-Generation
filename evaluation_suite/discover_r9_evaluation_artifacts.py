"""Artifact discovery/hashing for the R9 final judge campaign (FINAL R9 KC CONTENT QUALITY
EVALUATION spec, section 3: "For every selected artifact record: absolute path, size, SHA-256,
row count, KC ID set, run ID, model, timestamp, source manifest").

Deliberately generic: takes a small JSON config mapping labels to absolute JSONL paths (produced
by hand or by a caller script that knows the real HPC layout) rather than hardcoding any
cluster-specific path here, so this module stays testable against tiny local fixtures and reusable
if artifact locations change (which they already have once this campaign: e3944aa -> current
HEAD). Cluster-specific paths belong in the config file passed at the command line, not in code.

Usage:
    python discover_r9_evaluation_artifacts.py --config artifact_paths.json --out source_artifact_manifest.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Iterable


def sha256_file(path: str | Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def kc_id_of(row: dict[str, Any]) -> str | None:
    return row.get("kc_id") or row.get("knowledge_unit_id")


def kc_id_set(rows: Iterable[dict[str, Any]]) -> set[str]:
    return {kc_id_of(r) for r in rows if kc_id_of(r) is not None}


def artifact_stats(path: str | Path) -> dict[str, Any]:
    """One artifact's full discovery record: path, size, mtime, sha256, row count, KC-ID count.
    Raises FileNotFoundError (not silently) if the artifact does not exist - a missing artifact
    must stop discovery, never be recorded as an empty/placeholder entry.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"artifact not found: {path}")
    st = path.stat()
    rows = load_jsonl(path)
    ids = kc_id_set(rows)
    return {
        "absolute_path": str(path),
        "size_bytes": st.st_size,
        "mtime_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime)),
        "sha256": sha256_file(path),
        "row_count": len(rows),
        "unique_kc_id_count": len(ids),
        "kc_ids": sorted(x for x in ids if x is not None),
    }


def build_manifest(config: dict[str, Any]) -> dict[str, Any]:
    """config is {label: path_string, ...} at arbitrary nesting - every string value that looks
    like a path ending in .jsonl is resolved to an artifact_stats record; every other value
    (strings, numbers, nested dicts without a .jsonl leaf) is carried through unchanged so the
    caller's own structure (intrinsic/extrinsic/sensitivity groupings, condition labels, commit
    hashes, run IDs) survives into the output manifest.
    """

    def walk(node: Any) -> Any:
        if isinstance(node, str) and node.endswith(".jsonl"):
            return artifact_stats(node)
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(config)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    manifest = build_manifest(config)
    manifest["_generated_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    args.out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
