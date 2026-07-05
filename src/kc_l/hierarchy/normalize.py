from __future__ import annotations

from typing import Any
from kc_l.hierarchy.loader import KCLeafRaw


def to_registry_rows(kcs: list[KCLeafRaw]) -> list[dict[str, Any]]:
    return [
        {
            "kc_id": kc.kc_id,
            "kc_path": kc.kc_path,
            "canonical_name": kc.canonical_name,
            "seed_definition": kc.seed_definition,
            "aliases": kc.aliases,
        }
        for kc in kcs
    ]