from __future__ import annotations

"""Compatibility wrapper for shared source-surface fallback utilities.

Generic source-window and source-surface fallback logic is owned by
kc_l.retrieval_windowing. This module exists only to preserve older
retrieval_gate import paths while Step 5x migrates to the shared utility layer.
"""

from kc_l.retrieval_windowing.source_surface_fallback import (
    DEFAULT_DYNAMIC_BROAD_TOKEN_MIN_DOC_FREQUENCY,
    SOURCE_SURFACE_FALLBACK,
    SourceSurfaceFallbackConfig,
    build_source_surface_fallback_candidates,
    compute_dynamic_broad_tokens,
    fallback_config_from_mapping,
)

__all__ = [
    "DEFAULT_DYNAMIC_BROAD_TOKEN_MIN_DOC_FREQUENCY",
    "SOURCE_SURFACE_FALLBACK",
    "SourceSurfaceFallbackConfig",
    "build_source_surface_fallback_candidates",
    "compute_dynamic_broad_tokens",
    "fallback_config_from_mapping",
]
