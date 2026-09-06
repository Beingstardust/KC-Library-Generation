"""Pure data wiring: given frozen claim decompositions for a candidate draft and a reference,
build the unjudged ClaimRelationRow list for all 4 relations. No judge calls happen here - this
only assembles what needs to be judged. See 07_methods/EVALUATION_METHOD_PLAN.md.

NOT executed against real data anywhere in this repo yet - 04_gold/expert_reference_kc_library.jsonl
does not exist until the reference freezes. The __main__ block below runs only against synthetic
fixtures to prove the wiring is correct.

Claim decomposition validation requirement (EVALUATION_METHOD_PLAN.md): because an LLM-generated
claim decomposition can itself introduce measurement error, any real ClaimDecomposition used here
must first pass a bounded human validation workflow before being trusted as gold. That workflow is
not yet built (only needed once claim decomposition actually runs against real drafts) - this
module assumes it has already been validated by the time it receives a ClaimDecomposition.
"""
from __future__ import annotations

from claim_schema import ClaimDecomposition, ClaimRelationRow


def build_faithfulness_rows(kc_id: str, arm_id: str, draft_claims: ClaimDecomposition, evidence_ref: str) -> list[ClaimRelationRow]:
    draft_claims.validate()
    return [
        ClaimRelationRow(relation="FAITHFULNESS", kc_id=kc_id, arm_id=arm_id, claim_id=c.claim_id,
                          claim_text=c.text, target_kind="system_evidence", target_ref=evidence_ref)
        for c in draft_claims.claims
    ]


def build_reference_correctness_rows(kc_id: str, arm_id: str, draft_claims: ClaimDecomposition, reference_ref: str) -> list[ClaimRelationRow]:
    draft_claims.validate()
    return [
        ClaimRelationRow(relation="REFERENCE_CORRECTNESS", kc_id=kc_id, arm_id=arm_id, claim_id=c.claim_id,
                          claim_text=c.text, target_kind="reference", target_ref=reference_ref)
        for c in draft_claims.claims
    ]


def build_reference_completeness_rows(kc_id: str, arm_id: str, reference_claims: ClaimDecomposition, draft_ref: str) -> list[ClaimRelationRow]:
    reference_claims.validate()
    if reference_claims.origin != "reference":
        raise ValueError("build_reference_completeness_rows requires a reference-origin decomposition")
    return [
        ClaimRelationRow(relation="REFERENCE_COMPLETENESS", kc_id=kc_id, arm_id=arm_id, claim_id=c.claim_id,
                          claim_text=c.text, target_kind="candidate_draft", target_ref=draft_ref)
        for c in reference_claims.claims
    ]


def build_retrieval_coverage_rows(kc_id: str, arm_id: str, reference_claims: ClaimDecomposition, evidence_ref: str) -> list[ClaimRelationRow]:
    reference_claims.validate()
    if reference_claims.origin != "reference":
        raise ValueError("build_retrieval_coverage_rows requires a reference-origin decomposition")
    return [
        ClaimRelationRow(relation="RETRIEVAL_COVERAGE", kc_id=kc_id, arm_id=arm_id, claim_id=c.claim_id,
                          claim_text=c.text, target_kind="system_evidence", target_ref=evidence_ref)
        for c in reference_claims.claims
    ]


def build_all_rows(kc_id: str, arm_id: str, draft_claims: ClaimDecomposition, reference_claims: ClaimDecomposition,
                    evidence_ref: str, reference_ref: str, draft_ref: str) -> dict[str, list[ClaimRelationRow]]:
    return {
        "FAITHFULNESS": build_faithfulness_rows(kc_id, arm_id, draft_claims, evidence_ref),
        "REFERENCE_CORRECTNESS": build_reference_correctness_rows(kc_id, arm_id, draft_claims, reference_ref),
        "REFERENCE_COMPLETENESS": build_reference_completeness_rows(kc_id, arm_id, reference_claims, draft_ref),
        "RETRIEVAL_COVERAGE": build_retrieval_coverage_rows(kc_id, arm_id, reference_claims, evidence_ref),
    }


if __name__ == "__main__":
    from claim_schema import Claim

    draft_claims = ClaimDecomposition(subject_id="KC_TEST_001:P-Q", origin="candidate_draft", claims=[
        Claim(claim_id="KC_TEST_001:P-Q:claim:0", text="X is defined as Y.", source_kc_id="KC_TEST_001", origin="candidate_draft"),
        Claim(claim_id="KC_TEST_001:P-Q:claim:1", text="The formula for X is a/b.", source_kc_id="KC_TEST_001", origin="candidate_draft", requirement_type="FORMULA"),
    ])
    reference_claims = ClaimDecomposition(subject_id="KC_TEST_001:reference", origin="reference", claims=[
        Claim(claim_id="KC_TEST_001:reference:claim:0", text="X is defined as Y in the context of Z.", source_kc_id="KC_TEST_001", origin="reference"),
    ])
    rows = build_all_rows("KC_TEST_001", "P-Q", draft_claims, reference_claims,
                           evidence_ref="evidence://KC_TEST_001/P-Q", reference_ref="reference://KC_TEST_001",
                           draft_ref="draft://KC_TEST_001/P-Q")
    for relation, r in rows.items():
        print(f"{relation}: {len(r)} unjudged rows")
        for row in r:
            row.validate_outcome_domain()  # outcome is None, always valid - proves the schema accepts unjudged rows
    print("OK - synthetic fixture wiring validated (no real data touched)")
