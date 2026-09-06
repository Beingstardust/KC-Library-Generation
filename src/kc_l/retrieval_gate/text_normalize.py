"""Compatibility wrapper for shared text-normalization utilities.

Generic text-normalization and quote-rebinding logic is owned by
kc_l.retrieval_windowing.text_normalize (the copy live step5x candidate generation
depends on, transitively via kc_l.retrieval_windowing.semantic). This module exists
only to preserve older retrieval_gate import paths (drafting_input_overlay.py/step_06_6
and others) while Step 5x/6.6 share one implementation instead of two independently
maintained, previously byte-identical copies.

Phase 3.5 rank #13 / Phase 4 Finding 3 / audit codebase-audit-20260805 item 13.
"""

from __future__ import annotations

from kc_l.retrieval_windowing.text_normalize import (
    build_text_views,
    find_normalized_substring_span,
    match_normalize,
    normalize_ws,
    rebind_quote_to_raw_source,
    verify_quote_in_raw_source,
)

__all__ = [
    "build_text_views",
    "find_normalized_substring_span",
    "match_normalize",
    "normalize_ws",
    "rebind_quote_to_raw_source",
    "verify_quote_in_raw_source",
]
