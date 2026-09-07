from __future__ import annotations

import re
from typing import Dict, Optional


_ALNUM_RE = re.compile(r"[A-Za-z0-9]")


def alnum_ratio(s: str) -> float:
    if not s:
        return 0.0
    n = len(s)
    k = len(_ALNUM_RE.findall(s))
    return k / max(1, n)


def clean_title(s: str, max_chars: int) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    if len(s) > max_chars:
        s = s[: max_chars].rstrip()
    return s


def score_title_candidate(
    text: str,
    y0: Optional[float],
    page_h: Optional[float],
    cfg: Dict[str, float],
) -> float:
    """
    Score based on being near top, reasonable length, and being alnum-heavy.
    """
    text = (text or "").strip()
    if not text:
        return 0.0

    min_len = int(cfg["min_len"])
    max_len = int(cfg["max_len"])
    top_y_frac = float(cfg["top_y_frac"])
    min_alnum_ratio = float(cfg["min_alnum_ratio"])

    L = len(text)
    if L < min_len or L > max_len:
        return 0.0

    ar = alnum_ratio(text)
    if ar < min_alnum_ratio:
        return 0.0

    y_score = 0.5
    if y0 is not None and page_h is not None and page_h > 0:
        frac = y0 / page_h
        if frac <= top_y_frac:
            y_score = 1.0 - (frac / max(1e-6, top_y_frac)) * 0.5
        else:
            y_score = 0.1

    len_score = 1.0
    if L > 120:
        len_score = 0.7
    if L > 160:
        len_score = 0.4

    return 0.6 * y_score + 0.4 * len_score