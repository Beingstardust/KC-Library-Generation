from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_stat(path: Path) -> Dict[str, object]:
    st = path.stat()
    return {
        "size": st.st_size,
        "mtime": st.st_mtime,
    }