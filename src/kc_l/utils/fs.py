from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterable, List, Tuple


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def list_files_recursive(root: Path) -> List[Path]:
    out: List[Path] = []
    if not root.exists():
        return out
    for p in root.rglob("*"):
        if p.is_file():
            out.append(p)
    return out


def copy_file(src: Path, dst: Path) -> None:
    ensure_dir(dst.parent)
    shutil.copy2(str(src), str(dst))


def safe_relpath(path: Path, start: Path) -> str:
    try:
        return str(path.relative_to(start)).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def is_windows() -> bool:
    return os.name == "nt"