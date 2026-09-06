"""Schema for the later claim-level, reference-based evaluation (RAGChecker/RAGAS-style).
Infrastructure only - see 07_methods/EVALUATION_METHOD_PLAN.md. Not wired to any judge model
yet, and not run against real data: 04_gold/expert_reference_kc_library.jsonl does not exist
until the reference freezes.

Four relations, all claim-level and semantic (never lexical - see EVALUATION_METHOD_PLAN.md
"No lexical reference metrics"):

  FAITHFULNESS          : candidate claim -> system evidence supplied to that drafter
  REFERENCE_CORRECTNESS : candidate claim -> expert reference / its source authority
  REFERENCE_COMPLETENESS: reference substantive-content item -> candidate draft
  RETRIEVAL_COVERAGE    : reference substantive-content item -> system evidence
"""
from __future__ import annotations

from dataclasses import dataclass, field

RELATIONS = ("FAITHFULNESS", "REFERENCE_CORRECTNESS", "REFERENCE_COMPLETENESS", "RETRIEVAL_COVERAGE")

# FAITHFULNESS / RETRIEVAL_COVERAGE outcomes - a claim is or isn't in the evidence, no ambiguity band needed
SUPPORT_OUTCOMES = ("SUPPORTED", "NOT_SUPPORTED")

# REFERENCE_CORRECTNESS outcomes - includes the escalation state for claims absent from reference
# wording but potentially still corpus-supported (see EVALUATION_METHOD_PLAN.md relation B)
CORRECTNESS_OUTCOMES = ("SUPPORTED", "CONTRADICTED", "REFERENCE_SILENT_SOURCE_CHECK_REQUIRED")

# REFERENCE_COMPLETENESS outcomes - did the candidate recover this reference content item
COMPLETENESS_OUTCOMES = ("RECOVERED", "MISSING", "PARTIALLY_RECOVERED")


@dataclass
class Claim:
    claim_id: str  # f"{draft_or_reference_id}:claim:{index}" - stable within one frozen decomposition
    text: str
    source_kc_id: str
    origin: str  # "candidate_draft" | "reference"
    requirement_type: str = "GENERAL"  # reuse FORMULA/DEFINITION/PROCEDURE/CONDITION/DISTINCTION/AGGREGATION
                                        # from rubric_selene_architecture3.py's REQUIREMENT_TYPES where applicable


@dataclass
class ClaimDecomposition:
    """One frozen decomposition, reused across relations that share the same claim set
    (candidate decomposition reused for FAITHFULNESS and REFERENCE_CORRECTNESS; reference
    decomposition reused for REFERENCE_COMPLETENESS and RETRIEVAL_COVERAGE)."""
    subject_id: str  # kc_id + arm identifier for a draft, or kc_id alone for a reference
    origin: str
    claims: list[Claim]
    decomposed_at: str = ""
    decomposer_model: str = ""

    def validate(self) -> None:
        if self.origin not in ("candidate_draft", "reference"):
            raise ValueError(f"origin must be candidate_draft or reference, got {self.origin!r}")
        ids = [c.claim_id for c in self.claims]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate claim_id in decomposition for {self.subject_id}")


@dataclass
class ClaimRelationRow:
    """One judged unit: a single claim evaluated against a single target (evidence or reference)."""
    relation: str
    kc_id: str
    arm_id: str  # which candidate system/drafter arm this row belongs to
    claim_id: str
    claim_text: str
    target_kind: str  # "system_evidence" | "reference" | "candidate_draft"
    target_ref: str  # opaque pointer into the relevant store (evidence id, reference kc_id, draft id)
    outcome: str = None  # filled in by the judge call, not by this scaffold
    evidence_ids: list = field(default_factory=list)

    def validate_outcome_domain(self) -> None:
        allowed = {
            "FAITHFULNESS": SUPPORT_OUTCOMES,
            "RETRIEVAL_COVERAGE": SUPPORT_OUTCOMES,
            "REFERENCE_CORRECTNESS": CORRECTNESS_OUTCOMES,
            "REFERENCE_COMPLETENESS": COMPLETENESS_OUTCOMES,
        }[self.relation]
        if self.outcome is not None and self.outcome not in allowed:
            raise ValueError(f"{self.relation} outcome {self.outcome!r} not in {allowed}")
