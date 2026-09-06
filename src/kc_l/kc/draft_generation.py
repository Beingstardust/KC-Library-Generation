from __future__ import annotations

from kc_l.kc_drafting import heuristic_core as _heuristic_core


# Legacy compatibility surface: the authoritative heuristic drafting implementation
# now lives in `kc_l.kc_drafting.heuristic_core`.
globals().update(
    {
        name: getattr(_heuristic_core, name)
        for name in dir(_heuristic_core)
        if not name.startswith("__")
    }
)

__all__ = [name for name in globals() if not name.startswith("__")]
