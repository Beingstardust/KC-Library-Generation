from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from kc_l.runtime.layout import REPO_ROOT, get_operator_layout


DEFAULT_ACTIVE_LIBRARY_POINTER = get_operator_layout(REPO_ROOT).active_library_pointer


@dataclass(frozen=True)
class ActiveKnowledgeLibraryPointer:
    state: str
    release_id: str | None
    release_root: str | None
    release_manifest_path: str | None
    updated_utc: str
    notes: str | None = None

    @property
    def has_active_release(self) -> bool:
        return self.state == "active"

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


def default_pointer_payload() -> dict[str, Any]:
    return {
        "pointer_version": "kc_library.active_pointer.v1",
        "state": "none",
        "release_id": None,
        "release_root": None,
        "release_manifest_path": None,
        "updated_utc": "1970-01-01T00:00:00Z",
        "notes": None,
    }


def _resolve_pointer_path(pointer_path: str | Path | None = None) -> Path:
    raw = Path(pointer_path) if pointer_path is not None else DEFAULT_ACTIVE_LIBRARY_POINTER
    return raw if raw.is_absolute() else (REPO_ROOT / raw).resolve()


def _resolve_repo_path(raw_path: str | Path | None) -> Path | None:
    if raw_path in (None, ""):
        return None
    path = Path(raw_path)
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def load_pointer_payload(pointer_path: str | Path | None = None) -> dict[str, Any]:
    path = _resolve_pointer_path(pointer_path)
    if not path.exists():
        return default_pointer_payload()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"Active library pointer must be a JSON object: {path}")
    merged = default_pointer_payload()
    merged.update(dict(payload))
    return merged


def load_active_library_pointer(pointer_path: str | Path | None = None) -> ActiveKnowledgeLibraryPointer:
    payload = load_pointer_payload(pointer_path)
    return ActiveKnowledgeLibraryPointer(
        state=str(payload.get("state") or "none"),
        release_id=str(payload.get("release_id")) if payload.get("release_id") is not None else None,
        release_root=str(payload.get("release_root")) if payload.get("release_root") is not None else None,
        release_manifest_path=(
            str(payload.get("release_manifest_path")) if payload.get("release_manifest_path") is not None else None
        ),
        updated_utc=str(payload.get("updated_utc") or ""),
        notes=str(payload.get("notes")) if payload.get("notes") is not None else None,
    )


def write_active_library_pointer(
    payload: ActiveKnowledgeLibraryPointer | Mapping[str, Any],
    pointer_path: str | Path | None = None,
) -> Path:
    path = _resolve_pointer_path(pointer_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = payload.to_row() if isinstance(payload, ActiveKnowledgeLibraryPointer) else dict(payload)
    path.write_text(json.dumps(row, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return path


def resolve_active_release_manifest_path(pointer_path: str | Path | None = None) -> Path:
    pointer = load_active_library_pointer(pointer_path)
    if not pointer.has_active_release or not pointer.release_manifest_path:
        raise FileNotFoundError(
            "No active frozen Knowledge Library release is set. "
            "Freeze a library first, then update data/library/active/knowledge_library_release_pointer.json."
        )
    manifest_path = _resolve_repo_path(pointer.release_manifest_path)
    if manifest_path is None or not manifest_path.exists():
        raise FileNotFoundError(f"Active release manifest not found: {pointer.release_manifest_path}")
    return manifest_path
