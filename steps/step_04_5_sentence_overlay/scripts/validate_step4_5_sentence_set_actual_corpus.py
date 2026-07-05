from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict


REQUIRED_TOP_LEVEL = [
    "sentence_corpus_path",
    "sentence_stats_path",
]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_active_manifest(pointer_path: Path) -> Path:
    pointer_path = pointer_path.resolve()
    target_name = read_text(pointer_path)
    if not target_name:
        raise RuntimeError(f"ACTIVE pointer is empty: {pointer_path}")
    target = Path(target_name)
    if target.is_absolute():
        return target.resolve()
    return (pointer_path.parent / target).resolve()


def normalize_docs_map(docs_obj: Any) -> Dict[str, Dict[str, Any]]:
    if isinstance(docs_obj, dict):
        return {str(k): v for k, v in docs_obj.items() if isinstance(v, dict)}
    if isinstance(docs_obj, list):
        out: Dict[str, Dict[str, Any]] = {}
        for row in docs_obj:
            if not isinstance(row, dict):
                raise TypeError(f"docs entry is not a dict: {type(row).__name__}")
            doc_id = row.get("doc_id")
            if not doc_id:
                raise KeyError("docs entry missing doc_id")
            out[str(doc_id)] = row
        return out
    raise TypeError(f"Unsupported docs container: {type(docs_obj).__name__}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate actual-corpus Step 4.5 sentence overlay set.")
    ap.add_argument("--active-pointer", required=True, type=str)
    args = ap.parse_args()

    active_pointer = Path(args.active_pointer).resolve()
    if not active_pointer.exists():
        raise FileNotFoundError(f"Missing ACTIVE pointer: {active_pointer}")

    set_path = resolve_active_manifest(active_pointer)
    if not set_path.exists():
        raise FileNotFoundError(f"ACTIVE pointer target missing: {set_path}")

    set_obj = read_json(set_path)
    docs = normalize_docs_map(set_obj.get("docs"))
    if not docs:
        raise RuntimeError("Step 4.5 sentence set has no docs entries.")

    failures = []

    for key in REQUIRED_TOP_LEVEL:
        raw = set_obj.get(key)
        if not raw:
            failures.append({"scope": "top_level", "missing_key": key})
            continue
        p = Path(str(raw))
        if not p.exists():
            failures.append({"scope": "top_level", "missing_path": str(p)})

    for doc_id, row in docs.items():
        for key in ["sentence_corpus_path", "sentence_stats_path"]:
            raw = row.get(key)
            if not raw:
                failures.append({"doc_id": doc_id, "missing_key": key})
                continue
            p = Path(str(raw))
            if not p.exists():
                failures.append({"doc_id": doc_id, "missing_path": str(p)})

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
