from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


REQUIRED_PATCH_FILES = [
    "page_patch_index.jsonl",
    "page_reveal_groups.jsonl",
    "patch_summary.json",
]


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def resolve_active_manifest(pointer_path: Path) -> Path:
    name = read_text(pointer_path)
    if not name:
        raise RuntimeError(f"ACTIVE pointer is empty: {pointer_path}")
    p = Path(name)
    if p.is_absolute():
        return p
    return (pointer_path.parent / p).resolve()


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Validate ACTIVE Step4 patches set.")
    ap.add_argument("--active-pointer", required=True, type=str)
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    active_pointer = Path(args.active_pointer).resolve()

    if not active_pointer.exists():
        raise FileNotFoundError(f"Missing ACTIVE pointer: {active_pointer}")

    set_path = resolve_active_manifest(active_pointer)
    if not set_path.exists():
        raise FileNotFoundError(f"ACTIVE pointer target missing: {set_path}")

    set_obj = read_json(set_path)
    docs = set_obj.get("docs", [])
    if not isinstance(docs, list) or not docs:
        raise RuntimeError("Patch set manifest has no docs[] entries.")

    failures: List[Dict[str, Any]] = []

    for row in docs:
        doc_id = row.get("doc_id")
        patch_dir_raw = row.get("patch_out_dir") or row.get("processed_out_dir")
        if not patch_dir_raw:
            failures.append({"doc_id": doc_id, "error": "missing patch_out_dir/processed_out_dir"})
            continue

        patch_dir = Path(str(patch_dir_raw))
        missing = [str(patch_dir / fn) for fn in REQUIRED_PATCH_FILES if not (patch_dir / fn).exists()]
        if missing:
            failures.append({"doc_id": doc_id, "missing": missing})

    if failures:
        print(json.dumps({"status": "fail", "failures": failures}, indent=2))
        sys.exit(1)

    print(json.dumps(
        {
            "status": "ok",
            "active_pointer": str(active_pointer),
            "set_path": str(set_path),
            "doc_count": len(docs),
        },
        indent=2,
    ))


if __name__ == "__main__":
    main()
