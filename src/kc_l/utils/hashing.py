from __future__ import annotations

from pathlib import Path
import hashlib


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def sha256_text(s: str) -> str:
    return sha256_bytes(s.encode("utf-8"))