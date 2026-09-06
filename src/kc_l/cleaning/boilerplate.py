from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

_WS = re.compile(r"\s+")
_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_EMAIL = re.compile(r"\b[\w\.-]+@[\w\.-]+\.\w+\b")
_PAGE = re.compile(r"^(page\s*)?\d+\s*(/|of)?\s*\d*\s*$", re.IGNORECASE)
_COPYRIGHT = re.compile(r"(copyright|©|\(c\))", re.IGNORECASE)

_MATH_CHARS = re.compile(r"[∑∏√∫≈≠≤≥±×÷∞∂∇∈∉⊂⊆⊄⊇∪∩→←↔⇒⇔αβγδεζηθικλμνξοπρστυφχψω]")

def _norm_line(s: str) -> str:
    s = (s or "").strip()
    s = _WS.sub(" ", s)
    return s.lower()

def _split_lines(text: str) -> List[str]:
    if not text:
        return []
    return [ln.rstrip() for ln in text.splitlines() if ln.strip()]

def math_symbol_ratio(text: str) -> float:
    if not text:
        return 0.0
    chars = len(text)
    if chars == 0:
        return 0.0
    k = len(_MATH_CHARS.findall(text))
    return k / chars

@dataclass
class LineStat:
    norm: str
    raw_examples: List[str]
    n_pages: int
    n_occurrences: int
    bottom_frac: float  # fraction of occurrences in footer zone

def build_line_stats(
    mineru_text_blocks: List[Dict[str, Any]],
    page_heights: Dict[int, float],
    bottom_y_frac: float,
    max_line_len: int,
) -> Dict[str, LineStat]:
    """
    mineru_text_blocks must have: page_index, text_raw, bbox_pt
    """
    # norm_line -> counts
    pages_seen: Dict[str, set[int]] = {}
    occ: Dict[str, int] = {}
    bottom: Dict[str, int] = {}
    examples: Dict[str, List[str]] = {}

    for b in mineru_text_blocks:
        pi = int(b.get("page_index", -1))
        txt = (b.get("text_raw") or "").strip()
        if not txt:
            continue

        bbox = b.get("bbox_pt")
        y0 = None
        if isinstance(bbox, list) and len(bbox) == 4:
            try:
                y0 = float(bbox[1])
            except Exception:
                y0 = None

        H = page_heights.get(pi)
        y_frac = None
        if y0 is not None and H and H > 0:
            y_frac = y0 / H

        for ln in _split_lines(txt):
            if len(ln) > max_line_len:
                continue
            n = _norm_line(ln)
            if not n:
                continue

            pages_seen.setdefault(n, set()).add(pi)
            occ[n] = occ.get(n, 0) + 1
            if y_frac is not None and y_frac >= bottom_y_frac:
                bottom[n] = bottom.get(n, 0) + 1
            examples.setdefault(n, [])
            if len(examples[n]) < 4 and ln not in examples[n]:
                examples[n].append(ln)

    out: Dict[str, LineStat] = {}
    for n, pgset in pages_seen.items():
        n_occ = occ.get(n, 0)
        b_occ = bottom.get(n, 0)
        out[n] = LineStat(
            norm=n,
            raw_examples=examples.get(n, []),
            n_pages=len(pgset),
            n_occurrences=n_occ,
            bottom_frac=(b_occ / max(1, n_occ)),
        )
    return out

def is_boilerplate_line(
    stat: LineStat,
    cfg: Dict[str, Any],
    n_pages_total: int,
) -> Tuple[bool, List[str]]:
    reasons: List[str] = []

    min_page_frac = float(cfg["min_page_frac"])
    min_pages_abs = int(cfg["min_pages_abs"])
    bottom_majority = float(cfg["bottom_majority_frac"])

    page_frac = stat.n_pages / max(1, n_pages_total)

    repeated = (page_frac >= min_page_frac) or (stat.n_pages >= min_pages_abs)
    if repeated:
        reasons.append("repeat_across_pages")

    if stat.bottom_frac >= bottom_majority:
        reasons.append("footer_position_majority")

    # pattern-based high precision flags
    pat = cfg.get("patterns", {})
    ex0 = stat.raw_examples[0] if stat.raw_examples else stat.norm

    if pat.get("page_number", True) and _PAGE.match(ex0.strip()):
        reasons.append("page_number_pattern")
    if pat.get("url_email", True) and (_URL.search(ex0) or _EMAIL.search(ex0)):
        reasons.append("url_or_email_pattern")
    if pat.get("copyright", True) and _COPYRIGHT.search(ex0):
        reasons.append("copyright_pattern")

    # Decision rule: require repetition AND (footer majority OR hard pattern)
    hard = any(r.endswith("_pattern") for r in reasons)
    ok = repeated and (("footer_position_majority" in reasons) or hard)

    return ok, reasons

def clean_block_text(
    text_raw: str,
    line_stats: Dict[str, LineStat],
    is_bp: Dict[str, Tuple[bool, List[str]]],
    protect_lines_norm: set[str],
) -> Dict[str, Any]:
    lines = _split_lines(text_raw)
    removed: List[Dict[str, Any]] = []
    kept: List[str] = []

    for ln in lines:
        n = _norm_line(ln)
        if not n:
            continue
        if n in protect_lines_norm:
            kept.append(ln)
            continue

        flag, reasons = is_bp.get(n, (False, []))
        if flag:
            st = line_stats.get(n)
            removed.append({
                "line": ln,
                "norm": n,
                "reasons": reasons,
                "n_pages": (st.n_pages if st else None),
                "bottom_frac": (st.bottom_frac if st else None),
            })
        else:
            kept.append(ln)

    text_clean = "\n".join(kept).strip()
    is_boilerplate_block = (len(kept) == 0 and len(removed) > 0)

    return {
        "text_clean": text_clean,
        "is_boilerplate_block": is_boilerplate_block,
        "removed_lines": removed,
        "kept_lines_n": len(kept),
        "removed_lines_n": len(removed),
    }