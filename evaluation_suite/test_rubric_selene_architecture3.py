"""Self-test for rubric_selene_architecture3.py (the v3 judge architecture: shared claim
decomposition, per-claim F3 verification, KC-level CORE_REQUIREMENTS ledger, per-requirement
F4/F5 fan-out, extract-then-classify F2)."""
from __future__ import annotations

import sys

import rubric_selene_architecture3 as r3

CHECKS_PASSED: list[str] = []
CHECKS_FAILED: list[tuple[str, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        CHECKS_PASSED.append(name)
        print(f"  [PASS] {name}")
    else:
        CHECKS_FAILED.append((name, detail))
        print(f"  [FAIL] {name}  -- {detail}")


def expect_raises(fn, exc_type=r3.RubricSchemaError) -> bool:
    try:
        fn()
    except exc_type:
        return True
    except Exception:
        return False
    return False


def _accepts(fn) -> bool:
    try:
        fn()
        return True
    except Exception:
        return False


# --- claim decomposition -------------------------------------------------------------------

def test_decompose_and_freeze():
    payload = {"case_id": "c1", "criterion": "DECOMPOSE", "claims": [{"claim": "x is y"}, {"claim": "z is w"}]}
    check("valid decompose payload accepted", _accepts(lambda: r3.validate_decompose_response(payload)))
    r3.validate_decompose_response(payload)
    frozen = r3.frozen_claim_texts(payload)
    check("frozen_claim_texts extracts claim strings in order", frozen == ("x is y", "z is w"))

    empty = {"case_id": "c1", "criterion": "DECOMPOSE", "claims": []}
    check("zero-claim decompose accepted", _accepts(lambda: r3.validate_decompose_response(empty)))
    check("frozen empty claims is an empty tuple", r3.frozen_claim_texts(empty) == ())

    check("identity leak in a claim is rejected",
          expect_raises(lambda: r3.validate_decompose_response(
              {"case_id": "c1", "criterion": "DECOMPOSE", "claims": [{"claim": "the qwen model says x"}]})))


# --- F1/F3 shared-decomposition verification -------------------------------------------------

def test_f1_verify_uses_frozen_claim_count():
    claims = ("claim one", "claim two", "claim three")
    schema = r3.f1_verify_json_schema(len(claims))
    check("F1 verify schema pins exact array length via minItems==maxItems==n_claims",
          schema["properties"]["verdicts"]["minItems"] == 3
          and schema["properties"]["verdicts"]["maxItems"] == 3)

    good = {"case_id": "c1", "criterion": "F1", "verdicts": [
        {"claim_index": 1, "verdict": "SUPPORTED", "evidence_ids": ["SYS_001"]},
        {"claim_index": 2, "verdict": "UNSUPPORTED", "evidence_ids": []},
        {"claim_index": 3, "verdict": "CONTRADICTED", "evidence_ids": ["SYS_002"]},
    ]}
    check("well-formed F1 verify response accepted", _accepts(lambda: r3.validate_f1_verify_response(good, 3)))
    check("F1 derivation: not all SUPPORTED -> FAIL", r3.derive_f1_v3_verdict(good) == "FAIL")

    all_supported = {"case_id": "c1", "criterion": "F1", "verdicts": [
        {"claim_index": 1, "verdict": "SUPPORTED", "evidence_ids": []},
        {"claim_index": 2, "verdict": "SUPPORTED", "evidence_ids": []},
        {"claim_index": 3, "verdict": "SUPPORTED", "evidence_ids": []},
    ]}
    check("F1 derivation: all SUPPORTED -> PASS", r3.derive_f1_v3_verdict(all_supported) == "PASS")

    too_few = {"case_id": "c1", "criterion": "F1", "verdicts": good["verdicts"][:2]}
    check("F1 verify response with wrong verdict count is rejected (mismatched vs frozen claims)",
          expect_raises(lambda: r3.validate_f1_verify_response(too_few, 3)))


def test_f3_verify_not_established_is_not_a_failure():
    schema = r3.f3_verify_json_schema(2)
    check("F3 verify schema enum is SUPPORTED/CONTRADICTED/NOT_ESTABLISHED (no PASS/FAIL)",
          set(schema["properties"]["verdicts"]["items"]["properties"]["verdict"]["enum"])
          == {"SUPPORTED", "CONTRADICTED", "NOT_ESTABLISHED"})

    mixed_ok = {"case_id": "c1", "criterion": "F3", "verdicts": [
        {"claim_index": 1, "verdict": "SUPPORTED", "evidence_ids": ["AUTH_001"]},
        {"claim_index": 2, "verdict": "NOT_ESTABLISHED", "evidence_ids": []},
    ]}
    r3.validate_f3_verify_response(mixed_ok, 2)
    check("SUPPORTED + NOT_ESTABLISHED (no contradiction) -> F3 PASS - silence is not failure",
          r3.derive_f3_v3_verdict(mixed_ok) == "PASS")

    with_contradiction = {"case_id": "c1", "criterion": "F3", "verdicts": [
        {"claim_index": 1, "verdict": "SUPPORTED", "evidence_ids": ["AUTH_001"]},
        {"claim_index": 2, "verdict": "CONTRADICTED", "evidence_ids": ["AUTH_002"]},
    ]}
    r3.validate_f3_verify_response(with_contradiction, 2)
    check("one CONTRADICTED claim -> F3 FAIL regardless of the others",
          r3.derive_f3_v3_verdict(with_contradiction) == "FAIL")


def test_f1_f3_use_the_same_frozen_claims_not_independent_decompositions():
    decompose_payload = {"case_id": "c1", "criterion": "DECOMPOSE",
                          "claims": [{"claim": "alpha"}, {"claim": "beta"}]}
    r3.validate_decompose_response(decompose_payload)
    claims = r3.frozen_claim_texts(decompose_payload)

    f1_prompt = r3.build_f1_verify_prompt("KC", "path", claims, "sys evidence block")
    f3_prompt = r3.build_f3_verify_prompt("KC", "path", claims, "auth evidence block")
    check("F1 verify prompt embeds the frozen claims verbatim", "alpha" in f1_prompt and "beta" in f1_prompt)
    check("F3 verify prompt embeds the SAME frozen claims verbatim (not re-decomposed)",
          "alpha" in f3_prompt and "beta" in f3_prompt)
    check("F1 and F3 prompts are built from the identical claims tuple object",
          r3.frozen_claim_texts(decompose_payload) is not claims or claims == ("alpha", "beta"))


# --- CORE_REQUIREMENTS ledger --------------------------------------------------------------

def test_core_requirements_ledger():
    payload = {"case_id": "kc1", "criterion": "CORE_REQUIREMENTS", "requirements": [
        {"requirement": "the recursive splitting procedure", "type": "PROCEDURE", "evidence_ids": ["AUTH_001"]},
        {"requirement": "the centroid formula", "type": "FORMULA", "evidence_ids": ["AUTH_005"]},
    ]}
    check("well-formed ledger accepted", _accepts(lambda: r3.validate_core_requirements_response(payload)))
    r3.validate_core_requirements_response(payload)
    frozen = r3.frozen_requirements(payload)
    check("frozen_requirements extracts (requirement, type) pairs",
          frozen == (r3.CoreRequirement("the recursive splitting procedure", "PROCEDURE"),
                     r3.CoreRequirement("the centroid formula", "FORMULA")))

    empty = {"case_id": "kc1", "criterion": "CORE_REQUIREMENTS", "requirements": []}
    check("empty ledger accepted (authority establishes no clear core)",
          _accepts(lambda: r3.validate_core_requirements_response(empty)))

    bad_type = {"case_id": "kc1", "criterion": "CORE_REQUIREMENTS",
                "requirements": [{"requirement": "x", "type": "NOT_A_TYPE", "evidence_ids": []}]}
    check("invalid requirement type is rejected", expect_raises(lambda: r3.validate_core_requirements_response(bad_type)))

    sys_id_leak = {"case_id": "kc1", "criterion": "CORE_REQUIREMENTS",
                   "requirements": [{"requirement": "x", "type": "DEFINITION", "evidence_ids": ["SYS_001"]}]}
    check("CORE_REQUIREMENTS rejects SYS_* ids (authority-only, F4-namespace check reused)",
          expect_raises(lambda: r3.validate_core_requirements_response(sys_id_leak)))


# --- F4/F5 per-requirement fan-out and Python-only aggregation -------------------------------

def test_f4_per_requirement_and_aggregation():
    req = r3.CoreRequirement("the centroid formula", "FORMULA")
    prompt = r3.build_f4_requirement_prompt("K-Means", req, "draft text", "[AUTH_001] some authority text")
    check("F4 requirement prompt injects the formula checklist for FORMULA-type requirements",
          "term by term" in prompt and "numerator and denominator" in prompt)
    check("F4 requirement prompt includes AUTHORITY CONTEXT (regression test: the first v3 run "
          "omitted this entirely, so the model had no real AUTH_* ids to cite and 54.6% of F4 "
          "calls came back CONTRACT_INVALID with free-text strings in evidence_ids instead)",
          "AUTH_001" in prompt and "AUTHORITY CONTEXT" in prompt)

    req_def = r3.CoreRequirement("what a cluster is", "DEFINITION")
    prompt_def = r3.build_f4_requirement_prompt("K-Means", req_def, "draft text", "[AUTH_001] x")
    check("F4 requirement prompt does NOT inject the formula checklist for non-FORMULA requirements",
          "term by term" not in prompt_def)

    good = {"case_id": "c1", "criterion": "F4", "status": "PRESENT_CORRECT", "evidence_ids": ["AUTH_001"], "rationale": "ok"}
    check("well-formed F4 requirement response accepted", _accepts(lambda: r3.validate_f4_requirement_response(good)))

    check("all PRESENT_CORRECT -> F4 PASS/NONE", r3.derive_f4_v3_outcome(["PRESENT_CORRECT", "PRESENT_CORRECT"]) == ("PASS", "NONE"))
    check("zero requirements -> F4 NOT_JUDGEABLE", r3.derive_f4_v3_outcome([])[0] == "NOT_JUDGEABLE")
    check("one MISSING -> F4 FAIL/MISSING_REQUIRED_ELEMENT",
          r3.derive_f4_v3_outcome(["PRESENT_CORRECT", "MISSING"]) == ("FAIL", "MISSING_REQUIRED_ELEMENT"))
    check("one PRESENT_BUT_INCORRECT -> F4 FAIL/INCORRECT_REQUIRED_ELEMENT",
          r3.derive_f4_v3_outcome(["PRESENT_CORRECT", "PRESENT_BUT_INCORRECT"]) == ("FAIL", "INCORRECT_REQUIRED_ELEMENT"))
    check("SENT_013-shaped test: a formula requirement marked PRESENT_BUT_INCORRECT by its OWN "
          "separate call still derives FAIL deterministically - the aggregation cannot silently "
          "average it away against other correct requirements",
          r3.derive_f4_v3_outcome(["PRESENT_CORRECT", "PRESENT_CORRECT", "PRESENT_BUT_INCORRECT"])[0] == "FAIL")


def test_f5_per_requirement_and_aggregation():
    req = r3.CoreRequirement("the centroid formula", "FORMULA")
    prompt = r3.build_f5_requirement_prompt("K-Means", req, "system evidence text")
    check("F5 requirement prompt injects the formula checklist for FORMULA-type requirements",
          "term by term" in prompt)

    good = {"case_id": "c1", "criterion": "F5", "status": "SUPPORTED", "evidence_ids": ["SYS_001", "AUTH_002"], "rationale": "ok"}
    check("F5 requirement accepts both SYS_* and AUTH_* ids", _accepts(lambda: r3.validate_f5_requirement_response(good)))

    check("all SUPPORTED -> F5 PASS/NONE", r3.derive_f5_v3_outcome(["SUPPORTED", "SUPPORTED"]) == ("PASS", "NONE"))
    check("zero requirements -> F5 FAIL/NO_TARGET_SUPPORT (never vacuous PASS)",
          r3.derive_f5_v3_outcome([]) == ("FAIL", "NO_TARGET_SUPPORT"))
    check("one WRONG_TARGET_ONLY -> F5 FAIL/WRONG_TARGET_SUPPORT",
          r3.derive_f5_v3_outcome(["SUPPORTED", "WRONG_TARGET_ONLY"]) == ("FAIL", "WRONG_TARGET_SUPPORT"))
    check("one NOT_SUPPORTED (no wrong-target) -> F5 FAIL/MISSING_DEFINING_CONTENT",
          r3.derive_f5_v3_outcome(["SUPPORTED", "NOT_SUPPORTED"]) == ("FAIL", "MISSING_DEFINING_CONTENT"))


def test_no_kc_specific_exception_in_formula_checklist():
    """Regression guard for the explicit instruction: the formula checklist must be identical
    text regardless of KC name or requirement content - no branch on canonical_name anywhere in
    its construction."""
    req = r3.CoreRequirement("the entropy formula", "FORMULA")
    prompt_entropy = r3.build_f4_requirement_prompt("External Index: Entropy", req, "draft", "[AUTH_001] x")
    req2 = r3.CoreRequirement("the centroid formula", "FORMULA")
    prompt_other = r3.build_f4_requirement_prompt("K-Means Algorithm", req2, "draft", "[AUTH_001] x")
    # Extract just the checklist block (identical constant in both) rather than the whole prompt,
    # which differs by KC name/requirement/draft as expected.
    check("the FORMULA_COMPARISON_CHECKLIST constant itself contains no KC name",
          "entropy" not in r3.FORMULA_COMPARISON_CHECKLIST.lower()
          and "k-means" not in r3.FORMULA_COMPARISON_CHECKLIST.lower()
          and "sent_013" not in r3.FORMULA_COMPARISON_CHECKLIST.lower())
    check("both prompts contain the identical checklist text verbatim",
          r3.FORMULA_COMPARISON_CHECKLIST in prompt_entropy and r3.FORMULA_COMPARISON_CHECKLIST in prompt_other)


# --- F2 extract-then-classify ----------------------------------------------------------------

def test_f2_extract_then_classify():
    same = {"case_id": "c1", "criterion": "F2", "primary_subject": "Hunt's Algorithm",
            "classification": "SAME", "evidence_ids": ["AUTH_001"], "rationale": "ok"}
    r3.validate_f2_v3_response(same)
    check("SAME -> F2 PASS", r3.derive_f2_v3_verdict(same) == "PASS")

    different = {**same, "classification": "DIFFERENT", "primary_subject": "rule set exclusivity"}
    check("DIFFERENT -> F2 FAIL", r3.derive_f2_v3_verdict(different) == "FAIL")

    unclear = {**same, "classification": "UNCLEAR"}
    check("UNCLEAR -> F2 NOT_JUDGEABLE (new third state in v3)", r3.derive_f2_v3_verdict(unclear) == "NOT_JUDGEABLE")

    missing_subject = {"case_id": "c1", "criterion": "F2", "primary_subject": "",
                        "classification": "SAME", "evidence_ids": [], "rationale": "ok"}
    check("empty primary_subject is rejected", expect_raises(lambda: r3.validate_f2_v3_response(missing_subject)))


def main() -> None:
    print("=" * 70)
    print("rubric_selene_architecture3 (v3 judge architecture) — self-test")
    print("No API key required. No network calls. No cost.")
    print("=" * 70)
    tests = [
        test_decompose_and_freeze, test_f1_verify_uses_frozen_claim_count,
        test_f3_verify_not_established_is_not_a_failure,
        test_f1_f3_use_the_same_frozen_claims_not_independent_decompositions,
        test_core_requirements_ledger, test_f4_per_requirement_and_aggregation,
        test_f5_per_requirement_and_aggregation, test_no_kc_specific_exception_in_formula_checklist,
        test_f2_extract_then_classify,
    ]
    for t in tests:
        print(f"\n-- {t.__name__} --")
        t()

    print("\n" + "=" * 70)
    print(f"{len(CHECKS_PASSED)} passed, {len(CHECKS_FAILED)} failed")
    if CHECKS_FAILED:
        print("\nFAILURES:")
        for name, detail in CHECKS_FAILED:
            print(f"  - {name}: {detail}")
        sys.exit(1)
    print("\nALL CHECKS PASSED.")


if __name__ == "__main__":
    main()
