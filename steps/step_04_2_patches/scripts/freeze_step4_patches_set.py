from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple


def utc_ts() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d_%H%M%S")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_write_text(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def safe_write_json(p: Path, obj: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def pip_freeze() -> str:
    try:
        out = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], stderr=subprocess.STDOUT)
        return out.decode("utf-8", errors="replace")
    except Exception as e:
        return f"<<pip freeze failed: {type(e).__name__}: {e}>>\n"


@dataclass(frozen=True)
class ArtifactRec:
    relpath: str
    sha256: str
    size_bytes: int
    mtime_iso: str


def file_record(repo_root: Path, p: Path) -> ArtifactRec:
    st = p.stat()
    mtime_iso = datetime.utcfromtimestamp(st.st_mtime).isoformat() + "Z"
    return ArtifactRec(
        relpath=str(p.relative_to(repo_root)).replace("\\", "/"),
        sha256=sha256_file(p),
        size_bytes=int(st.st_size),
        mtime_iso=mtime_iso,
    )


def list_doc_ids(retrieval_root: Path) -> List[str]:
    doc_ids: List[str] = []
    for child in retrieval_root.iterdir():
        if not child.is_dir():
            continue
        if child.name == "_sets":
            continue
        doc_ids.append(child.name)
    doc_ids.sort()
    return doc_ids


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=".", help="Repo root (default: .)")
    ap.add_argument("--patches-run-id", default="2026-03-04_150415_step4", help="Accepted Step 4.2 run id")
    ap.add_argument("--retrieval-root", default="data/processed/retrieval_index", help="Retrieval index root")
    ap.add_argument("--sets-dir", default="data/processed/retrieval_index/_sets", help="Where to write set manifests")
    ap.add_argument("--active-pointer", default="data/processed/retrieval_index/_sets/ACTIVE_STEP4_PATCHES_SET.txt")
    ap.add_argument("--require-n-docs", type=int, default=8, help="Fail unless exactly this many docs are found")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    retrieval_root = (repo_root / Path(args.retrieval_root)).resolve()
    sets_dir = (repo_root / Path(args.sets_dir)).resolve()
    active_ptr = (repo_root / Path(args.active_pointer)).resolve()

    run_id = f"{utc_ts()}_step4_2_freeze"
    run_dir = (repo_root / Path("data/runs") / run_id).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

    log_path = run_dir / "logs.txt"
    def log(msg: str) -> None:
        print(msg)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")

    t0 = time.time()
    log(f"[freeze] run_id={run_id}")
    log(f"[freeze] repo_root={repo_root}")
    log(f"[freeze] retrieval_root={retrieval_root}")
    log(f"[freeze] patches_run_id={args.patches_run_id}")
    log(f"[freeze] sets_dir={sets_dir}")
    log(f"[freeze] active_pointer={active_ptr}")

    if not retrieval_root.exists():
        log(f"[ERROR] retrieval_root does not exist: {retrieval_root}")
        return 2

    doc_ids = list_doc_ids(retrieval_root)
    log(f"[freeze] discovered_docs={len(doc_ids)} -> {doc_ids}")

    if args.require_n_docs is not None and len(doc_ids) != args.require_n_docs:
        log(f"[ERROR] expected {args.require_n_docs} docs under {retrieval_root}, found {len(doc_ids)}")
        log("[HINT] If this is intentional, rerun with --require-n-docs <correct_count>.")
        return 3

    required_files = [
        "page_patch_index.jsonl",
        "page_reveal_groups.jsonl",
        "patch_summary.json",
    ]

    docs_obj: Dict[str, Any] = {}
    input_recs: List[ArtifactRec] = []

    missing: List[Tuple[str, str]] = []
    for doc_id in doc_ids:
        out_dir = retrieval_root / doc_id / args.patches_run_id
        if not out_dir.exists():
            missing.append((doc_id, str(out_dir)))
            continue

        artifacts: Dict[str, Any] = {}
        for fn in required_files:
            p = out_dir / fn
            if not p.exists():
                missing.append((doc_id, str(p)))
                continue
            rec = file_record(repo_root, p)
            input_recs.append(rec)
            artifacts[fn] = {
                "path": rec.relpath,
                "sha256": rec.sha256,
                "size_bytes": rec.size_bytes,
                "mtime_utc": rec.mtime_iso,
            }

        docs_obj[doc_id] = {
            "doc_id": doc_id,
            "patches_run_id": args.patches_run_id,
            "patches_out_dir": str(out_dir.relative_to(repo_root)).replace("\\", "/"),
            "artifacts": artifacts,
        }

    if missing:
        log("[ERROR] Missing required patch artifacts (strict mode).")
        for doc_id, path in missing:
            log(f"  - {doc_id}: {path}")
        return 4

    sets_dir.mkdir(parents=True, exist_ok=True)
    set_filename = f"{utc_ts()}_step4_patches_set.json"
    set_path = sets_dir / set_filename

    set_obj = {
        "schema_version": "1.0",
        "kind": "step4_patches_set",
        "created_utc": datetime.utcnow().isoformat() + "Z",
        "patches_run_id": args.patches_run_id,
        "retrieval_root": str(retrieval_root.relative_to(repo_root)).replace("\\", "/"),
        "docs": docs_obj,
        "counts": {
            "n_docs": len(docs_obj),
            "n_inputs": len(input_recs),
        },
    }

    safe_write_json(set_path, set_obj)
    safe_write_text(active_ptr, set_filename + "\n")

    # Audit artifacts
    safe_write_text(run_dir / "invocation.txt", " ".join([sys.executable] + sys.argv) + "\n")
    env_obj = {
        "platform": platform.platform(),
        "python": sys.version,
        "executable": sys.executable,
        "cwd": str(Path.cwd()),
    }
    safe_write_json(run_dir / "env.json", env_obj)
    safe_write_text(run_dir / "pip_freeze.txt", pip_freeze())

    # Input manifest
    inputs_manifest = {
        "patch_artifacts": [rec.__dict__ for rec in input_recs],
    }
    safe_write_json(run_dir / "input_manifest.json", inputs_manifest)

    # Output manifest
    out_recs = [
        file_record(repo_root, set_path),
        file_record(repo_root, active_ptr),
    ]
    outputs_manifest = {
        "outputs": [rec.__dict__ for rec in out_recs],
    }
    safe_write_json(run_dir / "output_manifest.json", outputs_manifest)

    dt = time.time() - t0
    summary = {
        "run_id": run_id,
        "patches_run_id": args.patches_run_id,
        "set_path": str(set_path.relative_to(repo_root)).replace("\\", "/"),
        "active_pointer": str(active_ptr.relative_to(repo_root)).replace("\\", "/"),
        "n_docs": len(docs_obj),
        "seconds": round(dt, 3),
    }
    safe_write_json(run_dir / "summary.json", summary)

    # Acceptance prints
    log("")
    log("[ACCEPTANCE] ACTIVE pointer exists: " + str(active_ptr.exists()))
    log("[ACCEPTANCE] Set json exists: " + str(set_path.exists()))
    log("[ACCEPTANCE] Set doc count: " + str(len(docs_obj)))
    log("[ACCEPTANCE] ACTIVE -> " + set_filename)
    log("[DONE] Freeze complete.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())