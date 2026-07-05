from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Optional, Tuple

PUNCT_FOLD_MAP = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u2032": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u2033": '"',
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u2212": "-",
    }
)
MULTISPACE_RE = re.compile(r"\s+")


def normalize_ws(text: str) -> str:
    return " ".join(str(text or "").split())


def _fold_piece(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or ""))
    return value.translate(PUNCT_FOLD_MAP)


def match_normalize(text: str) -> str:
    value = _fold_piece(text)
    value = MULTISPACE_RE.sub(" ", value).strip()
    return value.casefold()


def build_text_views(text: str) -> Dict[str, str]:
    raw = str(text or "")
    return {"raw": raw, "match_norm": match_normalize(raw)}


def verify_quote_in_raw_source(quote: str, source_text: str) -> bool:
    quote_raw = str(quote or "")
    source_raw = str(source_text or "")
    return bool(quote_raw and source_raw and quote_raw in source_raw)


def _normalized_char_map(raw_text: str) -> Tuple[str, List[int]]:
    out_chars: List[str] = []
    out_to_raw: List[int] = []
    for raw_idx, raw_char in enumerate(str(raw_text or "")):
        piece = _fold_piece(raw_char)
        if not piece:
            continue
        for char in piece:
            if char.isspace():
                if not out_chars or out_chars[-1] == " ":
                    continue
                out_chars.append(" ")
                out_to_raw.append(raw_idx)
                continue
            out_chars.append(char.casefold())
            out_to_raw.append(raw_idx)
    while out_chars and out_chars[-1] == " ":
        out_chars.pop()
        out_to_raw.pop()
    return "".join(out_chars), out_to_raw


def find_normalized_substring_span(source_text: str, needle_text: str) -> Optional[Tuple[int, int]]:
    source_raw = str(source_text or "")
    needle_norm = match_normalize(needle_text)
    if not source_raw or not needle_norm:
        return None
    source_norm, norm_to_raw = _normalized_char_map(source_raw)
    if not source_norm:
        return None
    start = source_norm.find(needle_norm)
    while start >= 0:
        end = start + len(needle_norm)
        raw_start = norm_to_raw[start]
        raw_end = norm_to_raw[end - 1] + 1
        raw_substring = source_raw[raw_start:raw_end]
        if match_normalize(raw_substring) == needle_norm:
            return raw_start, raw_end
        start = source_norm.find(needle_norm, start + 1)
    return None


def rebind_quote_to_raw_source(
    *,
    quote_raw: str,
    quote_match_norm: str,
    source_text: str,
) -> Optional[str]:
    source_raw = str(source_text or "")
    if not source_raw:
        return None
    raw_quote = str(quote_raw or "")
    if raw_quote and raw_quote in source_raw:
        return raw_quote
    needle_norm = str(quote_match_norm or match_normalize(raw_quote))
    if not needle_norm:
        return None
    span = find_normalized_substring_span(source_raw, needle_norm)
    if span is None:
        return None
    rebound = source_raw[span[0] : span[1]]
    if not verify_quote_in_raw_source(rebound, source_raw):
        return None
    return rebound
