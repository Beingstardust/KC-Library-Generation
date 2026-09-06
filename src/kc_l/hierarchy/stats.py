from __future__ import annotations

from dataclasses import asdict
from collections import Counter
from typing import Any

from kc_l.hierarchy.loader import KCLeafRaw
from kc_l.hierarchy.validators import ValidationIssue


def _counter_str_keys(values: list[Any]) -> dict[str, int]:
    c = Counter(values)
    return {str(k): int(v) for k, v in c.items()}


def compute_stats(kcs: list[KCLeafRaw], issues: list[ValidationIssue], source_set_id: str) -> dict[str, Any]:
    depths = [len(k.kc_path) for k in kcs]
    top_modules = [k.kc_path[1] if len(k.kc_path) > 1 else k.kc_path[0] for k in kcs]

    issues_dicts = [asdict(i) for i in issues]
    issue_codes = [d["code"] for d in issues_dicts]

    return {
        "source_set_id": source_set_id,
        "num_kcs": len(kcs),
        "depth": {
            "min": min(depths) if depths else 0,
            "max": max(depths) if depths else 0,
            "counts": _counter_str_keys(depths),
        },
        "top_modules_counts": _counter_str_keys(top_modules),
        "issue_counts": _counter_str_keys(issue_codes),
        "issues": issues_dicts,
    }