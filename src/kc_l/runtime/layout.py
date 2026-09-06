from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class OperatorLayout:
    repo_root: Path
    docs_root: Path
    configs_root: Path
    data_root: Path
    input_root: Path
    course_materials_root: Path
    hierarchy_root: Path
    work_root: Path
    cache_root: Path
    staging_root: Path
    runs_root: Path
    pipeline_runs_root: Path
    library_root: Path
    active_library_root: Path
    active_library_pointer: Path
    frozen_library_root: Path
    exports_root: Path


def get_operator_layout(repo_root: Path | None = None) -> OperatorLayout:
    root = (repo_root or REPO_ROOT).resolve()
    data_root = root / "data"
    input_root = data_root / "input"
    work_root = data_root / "work"
    library_root = data_root / "library"
    return OperatorLayout(
        repo_root=root,
        docs_root=root / "docs",
        configs_root=root / "configs",
        data_root=data_root,
        input_root=input_root,
        course_materials_root=input_root / "course_materials",
        hierarchy_root=input_root / "hierarchy",
        work_root=work_root,
        cache_root=work_root / "cache",
        staging_root=work_root / "staging",
        runs_root=data_root / "runs",
        pipeline_runs_root=data_root / "processed" / "runs",
        library_root=library_root,
        active_library_root=library_root / "active",
        active_library_pointer=library_root / "active" / "knowledge_library_release_pointer.json",
        frozen_library_root=library_root / "frozen",
        exports_root=data_root / "exports",
    )


def ensure_operator_layout(layout: OperatorLayout | None = None) -> OperatorLayout:
    active_layout = layout or get_operator_layout()
    for path in (
        active_layout.course_materials_root,
        active_layout.hierarchy_root,
        active_layout.cache_root,
        active_layout.staging_root,
        active_layout.runs_root,
        active_layout.active_library_root,
        active_layout.frozen_library_root,
        active_layout.exports_root,
    ):
        path.mkdir(parents=True, exist_ok=True)
    return active_layout


def repo_relative(path: Path, repo_root: Path | None = None) -> str:
    root = (repo_root or REPO_ROOT).resolve()
    try:
        return path.resolve().relative_to(root).as_posix()
    except Exception:
        return path.resolve().as_posix()


def list_visible_children(path: Path, *, allowed_names: Iterable[str] = ()) -> list[str]:
    allowed = set(allowed_names)
    if not path.exists():
        return []
    return sorted(
        entry.name
        for entry in path.iterdir()
        if entry.name not in allowed
    )


def is_effectively_empty(path: Path, *, allowed_names: Iterable[str] = ()) -> bool:
    return not list_visible_children(path, allowed_names=allowed_names)
