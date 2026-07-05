from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from kc_l.hierarchy.loader import KCLeafRaw


@dataclass(frozen=True)
class ValidationIssue:
    level: str  # "ERROR" or "WARN"
    code: str
    message: str
    kc_id: str | None = None
    kc_path: list[str] | None = None


def validate_kc_leaves(kcs: Iterable[KCLeafRaw]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    seen_ids: set[str] = set()
    name_to_ids: dict[str, list[str]] = {}

    for kc in kcs:
        if not kc.kc_id:
            issues.append(
                ValidationIssue(
                    level="ERROR",
                    code="MISSING_KC_ID",
                    message="KC leaf missing kc_id.",
                    kc_path=kc.kc_path,
                )
            )
        else:
            if kc.kc_id in seen_ids:
                issues.append(
                    ValidationIssue(
                        level="ERROR",
                        code="DUPLICATE_KC_ID",
                        message=f"Duplicate kc_id: {kc.kc_id}",
                        kc_id=kc.kc_id,
                        kc_path=kc.kc_path,
                    )
                )
            seen_ids.add(kc.kc_id)

        if not kc.seed_definition:
            issues.append(
                ValidationIssue(
                    level="WARN",
                    code="MISSING_SEED_DEFINITION",
                    message="Seed definition is empty (input 'definition').",
                    kc_id=kc.kc_id or None,
                    kc_path=kc.kc_path,
                )
            )

        name_to_ids.setdefault(kc.canonical_name, []).append(kc.kc_id)

    for name, ids in name_to_ids.items():
        if len(ids) > 1:
            issues.append(
                ValidationIssue(
                    level="WARN",
                    code="DUPLICATE_CANONICAL_NAME",
                    message=f"Canonical name appears multiple times: '{name}' with kc_ids={ids}",
                )
            )

    return issues


def has_errors(issues: list[ValidationIssue]) -> bool:
    return any(i.level == "ERROR" for i in issues)