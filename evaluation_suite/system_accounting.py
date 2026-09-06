"""System-level accounting: abstention validity (derived, not judged - section 5.1) and
descriptive coverage/yield formulas (section 6).

Nothing here calls the LLM judge. Abstention validity is derived entirely from
evidence_sufficiency (a judge output, but already collected for evidence_sufficiency's own
sake - not a separate LLM call) crossed with the pipeline's own recorded status
(drafted/abstained), per the brief's explicit instruction not to ask the judge a separate vague
"abstention quality" question.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

SystemBehavior = Literal["drafted", "abstained"]

AbstentionCategory = Literal[
    "justified_abstention", "avoidable_abstention", "supported_attempt", "risky_attempt",
]


@dataclass(frozen=True)
class AbstentionRow:
    kc_id: str
    evidence_sufficient: bool
    system_behavior: SystemBehavior


def classify_abstention(evidence_sufficient: bool, system_behavior: SystemBehavior) -> AbstentionCategory:
    """The 2x2 matrix from section 5.1, as a pure function - one row in, one label out."""
    if evidence_sufficient and system_behavior == "drafted":
        return "supported_attempt"
    if evidence_sufficient and system_behavior == "abstained":
        return "avoidable_abstention"
    if not evidence_sufficient and system_behavior == "abstained":
        return "justified_abstention"
    return "risky_attempt"  # insufficient evidence, drafted anyway


@dataclass(frozen=True)
class AbstentionRates:
    n_total: int
    n_abstained: int
    n_drafted: int
    n_sufficient: int
    n_insufficient: int
    n_justified_abstention: int
    n_avoidable_abstention: int
    n_supported_attempt: int
    n_risky_attempt: int
    abstention_precision: float | None  # justified / all abstentions
    avoidable_abstention_rate: float | None  # avoidable / sufficient-evidence cases
    unsupported_attempt_rate: float | None  # risky drafts / insufficient-evidence cases


def compute_abstention_rates(rows: Iterable[AbstentionRow]) -> AbstentionRates:
    rows = list(rows)
    n_total = len(rows)
    n_abstained = sum(1 for r in rows if r.system_behavior == "abstained")
    n_drafted = sum(1 for r in rows if r.system_behavior == "drafted")
    n_sufficient = sum(1 for r in rows if r.evidence_sufficient)
    n_insufficient = n_total - n_sufficient

    categories = [classify_abstention(r.evidence_sufficient, r.system_behavior) for r in rows]
    n_justified = categories.count("justified_abstention")
    n_avoidable = categories.count("avoidable_abstention")
    n_supported = categories.count("supported_attempt")
    n_risky = categories.count("risky_attempt")

    return AbstentionRates(
        n_total=n_total,
        n_abstained=n_abstained,
        n_drafted=n_drafted,
        n_sufficient=n_sufficient,
        n_insufficient=n_insufficient,
        n_justified_abstention=n_justified,
        n_avoidable_abstention=n_avoidable,
        n_supported_attempt=n_supported,
        n_risky_attempt=n_risky,
        abstention_precision=round(n_justified / n_abstained, 6) if n_abstained else None,
        avoidable_abstention_rate=round(n_avoidable / n_sufficient, 6) if n_sufficient else None,
        unsupported_attempt_rate=round(n_risky / n_insufficient, 6) if n_insufficient else None,
    )


# ---------------------------------------------------------------------------------------------
# Section 6: system-level accounting. Every function returns (numerator, denominator, rate) -
# never a bare percentage - per the brief's "every output table must include raw numerator and
# denominator alongside the percentage" requirement.
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class RateReport:
    label: str
    formula: str
    numerator: int
    denominator: int
    rate: float | None

    def as_dict(self) -> dict:
        return {
            "label": self.label, "formula": self.formula,
            "numerator": self.numerator, "denominator": self.denominator,
            "rate": self.rate,
            "percentage": round(self.rate * 100, 2) if self.rate is not None else None,
        }


def _rate(label: str, formula: str, numerator: int, denominator: int) -> RateReport:
    rate = round(numerator / denominator, 6) if denominator else None
    return RateReport(label=label, formula=formula, numerator=numerator,
                       denominator=denominator, rate=rate)


def attempt_coverage_rate(attempted_drafts: int, intended_kcs: int) -> RateReport:
    """A. attempt / coverage rate = attempted_drafts / intended_KCs."""
    return _rate("Attempt Coverage", "attempted_drafts / intended_KCs", attempted_drafts, intended_kcs)


def conditional_success_rate(successful_acceptable_drafts: int, attempted_drafts: int) -> RateReport:
    """B. conditional success among attempts = successful_acceptable_drafts / attempted_drafts."""
    return _rate("Conditional Success Among Attempts",
                 "successful_acceptable_drafts / attempted_drafts",
                 successful_acceptable_drafts, attempted_drafts)


def end_to_end_usable_yield(successful_acceptable_drafts: int, intended_kcs: int) -> RateReport:
    """C. end-to-end usable yield = successful_acceptable_drafts / intended_KCs."""
    return _rate("End-to-End Usable Yield", "successful_acceptable_drafts / intended_KCs",
                 successful_acceptable_drafts, intended_kcs)


def structural_completeness(intended_kc_ids_preserved: int, intended_kc_ids: int) -> RateReport:
    """E. structural completeness = intended_KC_IDs_preserved / intended_KC_IDs.

    This should be 100% by construction for the current pipeline - every intended KC identity
    is meant to survive through the authoring pipeline (system contract item 1). A value below
    1.0 here is a real defect signal, not expected variance.
    """
    return _rate("Structural Completeness", "intended_KC_IDs_preserved / intended_KC_IDs",
                 intended_kc_ids_preserved, intended_kc_ids)


def semantic_completion(successfully_instantiated_kcs: int, intended_kcs: int) -> RateReport:
    """F. semantic completion = successfully_instantiated_KCs / intended_KCs."""
    return _rate("Semantic Completion", "successfully_instantiated_KCs / intended_KCs",
                 successfully_instantiated_kcs, intended_kcs)
