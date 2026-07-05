from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path


RUN_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}_(.+)$")
RUN_REF_RE = re.compile(r"data/runs/[A-Za-z0-9._/\-]+")
PATHLIKE_PREFIXES = ("data/", "/beegfs1/", "/beegfs2/", "./data/")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def looks_like_path(value: str) -> bool:
    return any(value.startswith(p) for p in PATHLIKE_PREFIXES)


def resolve_path(repo_root: Path, raw: str) -> Path:
    p = Path(raw)
    if not p.is_absolute():
        p = (repo_root / p).resolve()
    return p


def iter_strings(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from iter_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from iter_strings(v)
    elif isinstance(obj, str):
        yield obj


def protected_from_active_manifests(repo_root: Path) -> set[Path]:
    protected = set()
    for pointer in repo_root.glob("data/processed/**/_sets/ACTIVE*.txt"):
        if not pointer.is_file():
            continue
        try:
            target_name = pointer.read_text(encoding="utf-8").strip()
        except Exception:
            continue
        if not target_name:
            continue
        target = (pointer.parent / target_name).resolve()
        if not target.exists():
            continue

        protected.add(pointer.resolve())
        protected.add(target)

        try:
            manifest = load_json(target)
        except Exception:
            continue

        for s in iter_strings(manifest):
            if not looks_like_path(s):
                continue
            try:
                p = resolve_path(repo_root, s)
            except Exception:
                continue
            protected.add(p)

            parts = p.parts
            if "data" in parts and "runs" in parts:
                try:
                    idx = parts.index("runs")
                    run_dir = Path(*parts[: idx + 2])
                    protected.add(run_dir)
                except Exception:
                    pass

    return {p.resolve() for p in protected}


def protected_from_operator_notes(repo_root: Path) -> set[Path]:
    protected = set()
    notes_dir = repo_root / "docs" / "operator_notes"
    if not notes_dir.exists():
        return protected

    for md in notes_dir.glob("*.md"):
        text = md.read_text(encoding="utf-8", errors="ignore")
        for match in RUN_REF_RE.findall(text):
            p = resolve_path(repo_root, match)
            protected.add(p)
    return {p.resolve() for p in protected}


def latest_run_dirs_per_step(repo_root: Path, keep_latest: int) -> set[Path]:
    runs_root = repo_root / "data" / "runs"
    groups: dict[str, list[Path]] = defaultdict(list)
    if not runs_root.exists():
        return set()

    for d in runs_root.iterdir():
        if not d.is_dir():
            continue
        m = RUN_DIR_RE.match(d.name)
        if not m:
            continue
        step_name = m.group(1)
        groups[step_name].append(d.resolve())

    protected = set()
    for _, dirs in groups.items():
        for d in sorted(dirs)[-keep_latest:]:
            protected.add(d)
    return protected


def classify_status(run_dir: Path) -> str:
    summary = run_dir / "summary.json"
    if summary.exists():
        try:
            data = load_json(summary)
            status = str(data.get("status", "")).strip()
            if status:
                return status
        except Exception:
            pass
    return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--keep-latest-per-step", type=int, default=3)
    parser.add_argument("--only-failed", action="store_true")
    parser.add_argument("--move", action="store_true")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    runs_root = repo_root / "data" / "runs"
    trash_root = repo_root / "data" / "trash" / f"run_gc_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"

    protected = set()
    protected |= protected_from_active_manifests(repo_root)
    protected |= protected_from_operator_notes(repo_root)
    protected |= latest_run_dirs_per_step(repo_root, args.keep_latest_per_step)

    candidates = []
    for d in sorted(runs_root.iterdir()) if runs_root.exists() else []:
        if not d.is_dir():
            continue
        m = RUN_DIR_RE.match(d.name)
        if not m:
            continue
        d_res = d.resolve()
        if d_res in protected:
            continue

        status = classify_status(d)
        if args.only_failed and status not in {"failed", "acceptance_failed"}:
            continue

        candidates.append(
            {
                "run_dir": d_res,
                "status": status,
            }
        )

    print(json.dumps(
        {
            "repo_root": str(repo_root),
            "runs_root": str(runs_root),
            "trash_root": str(trash_root),
            "keep_latest_per_step": args.keep_latest_per_step,
            "only_failed": args.only_failed,
            "move": args.move,
            "candidate_count": len(candidates),
            "candidates": [
                {"run_dir": str(item["run_dir"]), "status": item["status"]}
                for item in candidates
            ],
        },
        indent=2,
    ))

    if args.move and candidates:
        trash_root.mkdir(parents=True, exist_ok=False)
        for item in candidates:
            src = item["run_dir"]
            dst = trash_root / src.name
            shutil.move(str(src), str(dst))
            print(f"MOVED {src} -> {dst}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
