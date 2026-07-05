from __future__ import annotations

from kc_l.kc_drafting import packetization as _packetization


# Legacy compatibility surface: the authoritative restarted Step 6.8 packetization
# implementation now lives in `kc_l.kc_drafting.packetization`.
globals().update(
    {
        name: getattr(_packetization, name)
        for name in dir(_packetization)
        if not name.startswith("__")
    }
)

__all__ = [name for name in globals() if not name.startswith("__")]
