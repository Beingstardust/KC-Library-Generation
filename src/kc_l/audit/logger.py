from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import orjson


@dataclass
class JsonlLogger:
    path: Path

    def log(self, level: str, event: str, **fields: Any) -> None:
        rec = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "event": event,
            **fields,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("ab") as f:
            f.write(orjson.dumps(rec))
            f.write(b"\n")