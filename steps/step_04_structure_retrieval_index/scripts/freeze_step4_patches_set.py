from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
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


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def resolve_active_manifest(pointer_path: Path) -> Path:
    name = read_text(pointer_path)
    if not name:
        raise RuntimeError(f"ACTIVE pointer is empty: {pointer_path}")
    p = Path(name)
    if p.is_absolute():
        return p
    return (pointer_path.parent / p).resolve()


def load_active_manifest(pointer_path: Path) -> tuple[Path, Dict[str, Any]]:
    manifest_path = resolve_active_manifest(pointer_path)
    if not manifest_path.exists():
        raise FileNotFoundError(f"ACTIVE pointer target missing: {manifest_path}")
    return manifest_path, read_json(manifest_path)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Freeze Step4 patches set for the actual corpus.")
    ap.add_argument("--repo-root", type=str, default=".")
    ap.add_argument("--run-id", type=str, required=True)
    ap.add_argument("--processed-root", type=str, required=True)
    ap.add_argument("--sets-dir", type=str, required=True)
    ap.add_argument("--active-step3", type=str, required=True)
    ap.add_argument("--active-step3-6", type=str, required=True)
    ap.add_argument("--timezone", type=str, default="Europe/Amsterdam")
    return ap.parse_args()


def main() -> None:
    args = parse_args()

    processed_root = Path(args.processed_root).resolve()
    sets_dir = Path(args.sets_dir).resolve()
    active_step3 = Path(args.active_step3).resolve()
    active_step3_6 = Path(args.active_step3_6).resolve()
    run_id = args.run_id.strip()

    ensure_dir(sets_dir)

    step3_manifest_path, step3_set = load_active_manifest(active_step3)
    step3_6_manifest_path, step3_6_set = load_active_manifest(active_step3_6)

    step3_docs = {
        d["doc_id"]: d
        for d in step3_set.get("docs", [])
        if isinstance(d, dict) and "doc_id" in d
    }
    step3_6_docs = {
        d["doc_id"]: d
        for d in step3_6_set.get("docs", [])
        if isinstance(d, dict) and "doc_id" in d
    }

    doc_ids = sorted(set(step3_docs.keys()) & set(step3_6_docs.keys()))
    if not doc_ids:
        raise RuntimeError("No overlapping doc_ids between ACTIVE Step3 and Step3.6 sets.")

    rows: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []

    for doc_id in doc_ids:
        patch_dir = processed_root / doc_id / run_id
        missing = [str(patch_dir / fn) for fn in REQUIRED_PATCH_FILES if not (patch_dir / fn).exists()]
        if missing:
            failures.append({"doc_id": doc_id, "missing": missing})
            continue

        step3_row = step3_docs[doc_id]
        step3_6_row = step3_6_docs[doc_id]
        patch_summary = read_json(patch_dir / "patch_summary.json")

        rows.append(
            {
                "doc_id": doc_id,
                "run_id_step4": run_id,
                "patch_out_dir": str(patch_dir),
                "processed_out_dir": str(patch_dir),
                "page_patch_index_path": str(patch_dir / "page_patch_index.jsonl"),
                "page_reveal_groups_path": str(patch_dir / "page_reveal_groups.jsonl"),
                "patch_summary_path": str(patch_dir / "patch_summary.json"),
                "step3_out_dir": str(Path(step3_row.get("doctree_out_dir", ""))),
                "step3_6_out_dir": str(Path(step3_6_row.get("math_out_dir", ""))),
                "input_step3_dir": str(Path(step3_row.get("doctree_out_dir", ""))),
                "input_step3_6_dir": str(Path(step3_6_row.get("math_out_dir", ""))),
                "summary": patch_summary,
            }
        )

    if failures:
        raise RuntimeError(json.dumps({"freeze_failures": failures}, indent=2))

    set_id = f"{run_id}_step4_patches_set"
    set_path = sets_dir / f"{set_id}.json"

    set_obj = {
        "set_id": set_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "timezone": args.timezone,
        "step": "step4_patches",
        "input_step3_set": step3_manifest_path.name,
        "input_step3_6_set": step3_6_manifest_path.name,
        "run_id_step4": run_id,
        "doc_count": len(rows),
        "docs": rows,
    }

    set_path.write_text(json.dumps(set_obj, indent=2, ensure_ascii=False), encoding="utf-8")
    (sets_dir / "ACTIVE_STEP4_PATCHES_SET.txt").write_text(set_path.name, encoding="utf-8")

    print(json.dumps(
        {
            "status": "ok",
            "set_path": str(set_path),
            "active_pointer": str(sets_dir / "ACTIVE_STEP4_PATCHES_SET.txt"),
            "doc_count": len(rows),
        },
        indent=2,
    ))


if __name__ == "__main__":
    main()
