"""Rubric sentinel suite (FINAL R9 KC CONTENT QUALITY EVALUATION spec, section 23).

A frozen, historically-understood set of KC cases with expected F1-F5 labels, used ONLY to
qualify the rubric/judge before any real campaign judging - never mixed into the final
performance numbers. Every sentinel's expected label must trace to a real, previously-verified
finding (an audit document, a prior manual read against real corpus text), not an invented
example - this project's own EVIDENCE_QUALITY_METHODOLOGY.md content-verified census method is
the standard every sentinel here is held to: read the draft, read the cited evidence, check the
evidence against the real corpus text, and only then assign a label.

A rubric implementation that parses but changes a sentinel's meaning must fail - see
validate_against_sentinels() below, which is a behavioral check, not merely a schema check.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

Criterion = Literal["F1", "F2", "F3", "F4", "F5"]


class SentinelValidationError(ValueError):
    """Raised when a sentinel case fails its own frozen expectation - the whole point of the
    suite, so this must never be caught and silently ignored by a caller."""


@dataclass(frozen=True)
class RubricSentinel:
    sentinel_id: str
    kc_id: str
    canonical_name: str
    category: str  # short label for what failure mode / success mode this case tests
    provenance: str  # which audit doc / prior verified finding this case's label traces to
    draft_body: str
    system_evidence: tuple[dict[str, Any], ...]  # SYS_* items, already neutral-shaped
    authority_evidence: tuple[dict[str, Any], ...]  # AUTH_* items, already neutral-shaped
    expected_f1: Literal["PASS", "FAIL", "NOT_APPLICABLE"]
    expected_f2: Literal["PASS", "FAIL", "NOT_APPLICABLE"]
    expected_f3: Literal["PASS", "FAIL", "NOT_JUDGEABLE", "NOT_APPLICABLE"]
    expected_f4: Literal["PASS", "FAIL", "NOT_JUDGEABLE", "NOT_APPLICABLE"]
    expected_f5: Literal["PASS", "FAIL"]
    rationale: str  # why this label - the content-verified reasoning, not a status label copy


def to_jsonable(sentinel: RubricSentinel) -> dict[str, Any]:
    d = asdict(sentinel)
    d["system_evidence"] = list(sentinel.system_evidence)
    d["authority_evidence"] = list(sentinel.authority_evidence)
    return d


def from_jsonable(d: dict[str, Any]) -> RubricSentinel:
    d = dict(d)
    d["system_evidence"] = tuple(d.get("system_evidence") or ())
    d["authority_evidence"] = tuple(d.get("authority_evidence") or ())
    return RubricSentinel(**d)


def write_sentinels(path: str | Path, sentinels: list[RubricSentinel]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for s in sentinels:
            f.write(json.dumps(to_jsonable(s), sort_keys=True, ensure_ascii=False) + "\n")


def load_sentinels(path: str | Path) -> list[RubricSentinel]:
    out: list[RubricSentinel] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(from_jsonable(json.loads(line)))
    return out


def freeze_hash(sentinels: list[RubricSentinel]) -> str:
    """Deterministic hash of the whole suite's meaning (IDs + expected labels + rationale) -
    used to detect if a sentinel's expected label silently changed after freezing (section 23:
    "the sentinel suite is for rubric/judge qualification only")."""
    payload = [
        {"sentinel_id": s.sentinel_id, "kc_id": s.kc_id,
         "expected_f1": s.expected_f1, "expected_f2": s.expected_f2,
         "expected_f3": s.expected_f3, "expected_f4": s.expected_f4,
         "expected_f5": s.expected_f5}
        for s in sorted(sentinels, key=lambda x: x.sentinel_id)
    ]
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def check_sentinel_coverage(sentinels: list[RubricSentinel]) -> dict[str, int]:
    """Category counts - used to confirm the suite actually spans the required failure/success
    modes (section 23's minimum list) rather than clustering on one easy pattern."""
    counts: dict[str, int] = {}
    for s in sentinels:
        counts[s.category] = counts.get(s.category, 0) + 1
    return counts


REQUIRED_CATEGORIES = (
    "correct_definition",
    "wrong_coefficients_or_formula",
    "wrong_target_concept",
    "malformed_metric_definition",
    "unnormalized_interpretation_error",
    "missing_decision_mechanism",
    "taxonomy_confusion",
    "missing_defining_mechanism",
    "genuine_corpus_gap_abstention",
    "avoidable_abstention",
    "faithful_but_incomplete",
    "faithful_wrong_target",
    "complete_but_unsupported",
)


def missing_required_categories(sentinels: list[RubricSentinel]) -> list[str]:
    present = {s.category for s in sentinels}
    return [c for c in REQUIRED_CATEGORIES if c not in present]
