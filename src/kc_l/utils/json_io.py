from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

try:
    import orjson
except ModuleNotFoundError:  # pragma: no cover - exercised only in lean operator shells
    orjson = None


def read_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"JSON not found: {path}")
    if orjson is not None:
        return orjson.loads(path.read_bytes())
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if orjson is not None:
        path.write_bytes(orjson.dumps(obj, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS))
        return
    path.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if orjson is not None:
        with path.open("wb") as f:
            for row in rows:
                f.write(orjson.dumps(row))
                f.write(b"\n")
        return
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True))
            f.write("\n")


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"JSONL not found: {path}")
    rows: List[Dict[str, Any]] = []
    if orjson is not None:
        with path.open("rb") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rows.append(orjson.loads(line))
        return rows
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def read_jsonl_head(path: Path, n: int = 3) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for _ in range(n):
            line = f.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out
