from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


def now_ts(tz_name: str) -> datetime:
    return datetime.now(tz=ZoneInfo(tz_name))


def run_id(ts: datetime, step_name: str) -> str:
    # Windows-safe: avoid ":" and other illegal chars
    return ts.strftime(f"%Y-%m-%d_%H%M%S_{step_name}")