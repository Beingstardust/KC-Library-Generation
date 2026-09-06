"""Self-test for rubric_v3.py (F1-F5 judge rubric), covering the 2026-08-24 hardening pass:
oneOf verdict/reason_code grammar binding for F2/F3, no rationale-length validity check, and the
F4/F5 required-elements redesign that eliminates the model-stated verdict for those two criteria.
"""
from __future__ import annotations

import sys

from rubric_v3 import (
    ALLOWED_REASON_CODES,
    RubricSchemaError,
    criterion_json_schema,
    derive_f1_verdict,
    derive_f4_outcome,
    derive_f5_outcome,
    f2_json_schema,
    f3_json_schema,
    validate_criterion_response,
    validate_f1_response,
    validate_f4_response,
    validate_f5_response,
)

CHECKS_PASSED: list[str] = []
CHECKS_FAILED: list[tuple[str, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        CHECKS_PASSED.append(name)
        print(f"  [PASS] {name}")
    else:
        CHECKS_FAILED.append((name, detail))
        print(f"  [FAIL] {name}  -- {detail}")


def expect_raises(fn, exc_type=RubricSchemaError) -> bool:
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


def _f1_payload(claims):
    return {"case_id": "c1", "criterion": "F1", "claims": claims,
            "reason_code": "NONE" if all(c["verdict"] == "SUPPORTED" for c in claims) else "UNSUPPORTED_FACT",
            "rationale": "short"}


def _criterion_payload(criterion, verdict, reason_code="NONE", evidence_ids=None):
    return {"case_id": "c1", "criterion": criterion, "verdict": verdict,
            "reason_code": reason_code, "evidence_ids": evidence_ids or [],
            "rationale": "short"}


def _element(element="an element", status="PRESENT_CORRECT", evidence_ids=None, rationale="ok"):
    return {"element": element, "status": status, "evidence_ids": evidence_ids or [], "rationale": rationale}


def _f4_payload(elements):
    return {"case_id": "c1", "criterion": "F4", "required_elements": elements, "overall_rationale": "ok"}


def _f5_payload(elements):
    return {"case_id": "c1", "criterion": "F5", "required_elements": elements, "overall_rationale": "ok"}


# --- F1 claim decomposition and deterministic aggregation ---------------------------------------

def test_f1_aggregate_derivation():
    all_supported = _f1_payload([
        {"claim": "x", "verdict": "SUPPORTED", "evidence_ids": ["SYS_001"]},
        {"claim": "y", "verdict": "SUPPORTED", "evidence_ids": ["SYS_002"]},
    ])
    validate_f1_response(all_supported)
    check("all-supported claims -> F1 PASS", derive_f1_verdict(all_supported) == "PASS")

    one_unsupported = _f1_payload([
        {"claim": "x", "verdict": "SUPPORTED", "evidence_ids": ["SYS_001"]},
        {"claim": "y", "verdict": "UNSUPPORTED", "evidence_ids": []},
    ])
    validate_f1_response(one_unsupported)
    check("one unsupported claim -> F1 FAIL", derive_f1_verdict(one_unsupported) == "FAIL")

    contradicted = _f1_payload([{"claim": "x", "verdict": "CONTRADICTED", "evidence_ids": ["SYS_001"]}])
    validate_f1_response(contradicted)
    check("contradicted claim -> F1 FAIL", derive_f1_verdict(contradicted) == "FAIL")

    zero_claims = _f1_payload([])
    validate_f1_response(zero_claims)
    check("zero material claims -> F1 PASS (vacuous)", derive_f1_verdict(zero_claims) == "PASS")

    check("F1 schema has no top-level verdict field for the model to state",
          "verdict" not in _f1_payload([]))


# --- F2/F3 oneOf grammar-shaped schema validation -------------------------------------------------

def test_f2_f3_schema_validation():
    check("F2 valid PASS payload accepted",
          _accepts(lambda: validate_criterion_response(_criterion_payload("F2", "PASS"), "F2")))
    check("F2 NOT_JUDGEABLE rejected (F2's own prompt never offers it)",
          expect_raises(lambda: validate_criterion_response(
              _criterion_payload("F2", "NOT_JUDGEABLE", "WRONG_SIBLING"), "F2")))
    check("F3 NOT_JUDGEABLE accepted (F3's prompt explicitly allows it)",
          _accepts(lambda: validate_criterion_response(
              _criterion_payload("F3", "NOT_JUDGEABLE", "NONE"), "F3")))
    check("PASS verdict with a non-NONE reason_code rejected",
          expect_raises(lambda: validate_criterion_response(
              _criterion_payload("F3", "PASS", "WRONG_FORMULA"), "F3")))
    check("FAIL verdict with reason_code NONE rejected",
          expect_raises(lambda: validate_criterion_response(
              _criterion_payload("F3", "FAIL", "NONE"), "F3")))
    check("unknown reason_code rejected",
          expect_raises(lambda: validate_criterion_response(
              _criterion_payload("F3", "FAIL", "TOTALLY_MADE_UP"), "F3")))
    check("calling validate_criterion_response on F4/F5 is rejected (use the dedicated functions)",
          expect_raises(lambda: validate_criterion_response(_criterion_payload("F4", "PASS"), "F4")))


def test_rationale_length_is_not_a_validity_criterion():
    long_rationale = " ".join(["word"] * 500)
    check("F2 with a 500-word rationale is still accepted (length is no longer checked)",
          _accepts(lambda: validate_criterion_response(
              _criterion_payload("F3", "PASS") | {"rationale": long_rationale}, "F3")))
    check("F1 with a 500-word rationale is still accepted",
          _accepts(lambda: validate_f1_response(_f1_payload([]) | {"rationale": long_rationale})))
    f4_long = _f4_payload([_element(rationale=long_rationale)]) | {"overall_rationale": long_rationale}
    check("F4 with long rationale/overall_rationale is still accepted",
          _accepts(lambda: validate_f4_response(f4_long)))


def test_oneof_grammar_compiles_and_structurally_binds():
    """Regression test for the empirical finding: if/then/else compiles under XGrammar but is
    silently ignored (no branching enforced); oneOf with fully self-contained branches compiles
    to a grammar that DOES enforce the verdict/reason_code pairing. This does not re-run XGrammar
    itself (no GPU/xgrammar dependency in this self-test) - it checks the SCHEMA SHAPE this
    module emits is the oneOf form the compile-test verified, not an if/then form that looked
    reasonable but was proven not to work."""
    schema = f2_json_schema()
    check("F2 schema is a oneOf (the verified-working construct), not an if/then", "oneOf" in schema)
    check("F2 schema has no top-level 'if' key (the verified-NOT-working construct)", "if" not in schema)
    for branch in schema["oneOf"]:
        check(f"F2 oneOf branch pins verdict to a const: {branch['properties']['verdict']}",
              "const" in branch["properties"]["verdict"])

    schema3 = f3_json_schema()
    check("F3 schema is also oneOf", "oneOf" in schema3)
    check("F3 schema has 3 branches (PASS, FAIL, NOT_JUDGEABLE)", len(schema3["oneOf"]) == 3)


# --- Section 30: no drafter/system identity ever reaches the judge or its output ----------------

def test_no_identity_leak():
    check("rationale containing a drafter name is rejected",
          expect_raises(lambda: validate_criterion_response(
              _criterion_payload("F3", "PASS") | {"rationale": "this draft from Qwen looks fine"}, "F3")))
    check("F1 claim text containing a system name is rejected",
          expect_raises(lambda: validate_f1_response(
              _f1_payload([{"claim": "the DOS-RAG evidence says x", "verdict": "SUPPORTED",
                             "evidence_ids": ["SYS_001"]}]))))
    check("F4 element text containing a system name is rejected",
          expect_raises(lambda: validate_f4_response(
              _f4_payload([_element(element="the qwen model's own formula")]))))
    check("the ordinary English word 'proposed' does NOT trigger a false-positive leak "
          "(regression test for a real false positive found in the 2026-08-24 sentinel "
          "expansion: 'originally proposed for regression problems' is not a system-identity leak)",
          _accepts(lambda: validate_criterion_response(
              _criterion_payload("F3", "PASS") | {"rationale": "this was originally proposed for regression"}, "F3")))
    check("a clean rationale with no identity tokens passes",
          _accepts(lambda: validate_criterion_response(_criterion_payload("F3", "PASS"), "F3")))


# --- evidence-id namespace shape -------------------------------------------------------------

def test_evidence_id_namespace():
    check("F2 accepts AUTH_* ids", _accepts(lambda: validate_criterion_response(
        _criterion_payload("F2", "PASS", evidence_ids=["AUTH_001", "AUTH_002"]), "F2")))
    check("F2 rejects SYS_* ids (F2 only ever sees AUTHORITY CONTEXT)",
          expect_raises(lambda: validate_criterion_response(
              _criterion_payload("F2", "PASS", evidence_ids=["SYS_001"]), "F2")))
    check("F5 element accepts both SYS_* and AUTH_* ids (it compares the two)",
          _accepts(lambda: validate_f5_response(
              _f5_payload([_element(status="SUPPORTED", evidence_ids=["SYS_001", "AUTH_003"])]))))
    check("F1 rejects AUTH_* ids (F1 only ever sees SYSTEM EVIDENCE)",
          expect_raises(lambda: validate_f1_response(
              _f1_payload([{"claim": "x", "verdict": "SUPPORTED", "evidence_ids": ["AUTH_001"]}]))))
    check("F4 element accepts AUTH_* ids",
          _accepts(lambda: validate_f4_response(_f4_payload([_element(evidence_ids=["AUTH_005"])]))))
    check("F4 element rejects SYS_* ids (F4 only ever sees AUTHORITY CONTEXT + DRAFT)",
          expect_raises(lambda: validate_f4_response(_f4_payload([_element(evidence_ids=["SYS_005"])]))))


# --- F4/F5 required-elements schema and deterministic derivation --------------------------------

def test_f4_schema_validation():
    check("F4 with a well-formed element list is accepted",
          _accepts(lambda: validate_f4_response(_f4_payload([_element()]))))
    check("F4 with an empty element list is accepted (the NOT_JUDGEABLE case)",
          _accepts(lambda: validate_f4_response(_f4_payload([]))))
    check("F4 element with an invalid status is rejected",
          expect_raises(lambda: validate_f4_response(_f4_payload([_element(status="SORT_OF")]))))
    check("F4 response with the wrong criterion field is rejected",
          expect_raises(lambda: validate_f4_response(_f4_payload([]) | {"criterion": "F5"})))
    check("F4 element missing a required key is rejected",
          expect_raises(lambda: validate_f4_response(
              {"case_id": "c1", "criterion": "F4",
               "required_elements": [{"element": "x", "status": "MISSING"}],
               "overall_rationale": "ok"})))


def test_f4_deterministic_derivation():
    all_correct = _f4_payload([_element(status="PRESENT_CORRECT"), _element(status="PRESENT_CORRECT")])
    verdict, reason = derive_f4_outcome(all_correct)
    check("all elements PRESENT_CORRECT -> F4 PASS/NONE", (verdict, reason) == ("PASS", "NONE"))

    zero_elements = _f4_payload([])
    verdict, reason = derive_f4_outcome(zero_elements)
    check("zero required elements -> F4 NOT_JUDGEABLE (authority has no clear core)",
          verdict == "NOT_JUDGEABLE")

    one_missing = _f4_payload([_element(status="PRESENT_CORRECT"), _element(status="MISSING")])
    verdict, reason = derive_f4_outcome(one_missing)
    check("one MISSING element -> F4 FAIL/MISSING_REQUIRED_ELEMENT",
          (verdict, reason) == ("FAIL", "MISSING_REQUIRED_ELEMENT"))

    one_incorrect = _f4_payload([_element(status="PRESENT_CORRECT"), _element(status="PRESENT_BUT_INCORRECT")])
    verdict, reason = derive_f4_outcome(one_incorrect)
    check("one PRESENT_BUT_INCORRECT element -> F4 FAIL/INCORRECT_REQUIRED_ELEMENT",
          (verdict, reason) == ("FAIL", "INCORRECT_REQUIRED_ELEMENT"))

    both = _f4_payload([_element(status="MISSING"), _element(status="PRESENT_BUT_INCORRECT")])
    verdict, reason = derive_f4_outcome(both)
    check("one MISSING + one PRESENT_BUT_INCORRECT -> F4 FAIL/MISSING_AND_INCORRECT_ELEMENTS",
          (verdict, reason) == ("FAIL", "MISSING_AND_INCORRECT_ELEMENTS"))

    check("SENT_013-shaped case: a formula-shaped element wrongly marked PRESENT_CORRECT would "
          "have passed the OLD holistic design too - this derivation only helps if the model "
          "actually marks it PRESENT_BUT_INCORRECT; verified here that IF it does, FAIL follows "
          "deterministically, closing the old 'a formula exists therefore PASS' gap at the "
          "aggregation layer",
          derive_f4_outcome(_f4_payload([_element(element="the correct per-cluster entropy formula",
                                                    status="PRESENT_BUT_INCORRECT")]))[0] == "FAIL")


def test_f5_schema_and_derivation():
    check("F5 with a well-formed element list is accepted",
          _accepts(lambda: validate_f5_response(_f5_payload([_element(status="SUPPORTED")]))))

    all_supported = _f5_payload([_element(status="SUPPORTED"), _element(status="SUPPORTED")])
    verdict, reason = derive_f5_outcome(all_supported)
    check("all elements SUPPORTED -> F5 PASS/NONE", (verdict, reason) == ("PASS", "NONE"))

    zero_elements = _f5_payload([])
    verdict, reason = derive_f5_outcome(zero_elements)
    check("zero required elements -> F5 FAIL/NO_TARGET_SUPPORT (never a vacuous PASS)",
          (verdict, reason) == ("FAIL", "NO_TARGET_SUPPORT"))

    not_supported = _f5_payload([_element(status="SUPPORTED"), _element(status="NOT_SUPPORTED")])
    verdict, reason = derive_f5_outcome(not_supported)
    check("one NOT_SUPPORTED element -> F5 FAIL/MISSING_DEFINING_CONTENT",
          (verdict, reason) == ("FAIL", "MISSING_DEFINING_CONTENT"))

    wrong_target = _f5_payload([_element(status="SUPPORTED"), _element(status="WRONG_TARGET_ONLY")])
    verdict, reason = derive_f5_outcome(wrong_target)
    check("one WRONG_TARGET_ONLY element -> F5 FAIL/WRONG_TARGET_SUPPORT",
          (verdict, reason) == ("FAIL", "WRONG_TARGET_SUPPORT"))


def test_json_schema_shape():
    for c in ("F2", "F3"):
        schema = criterion_json_schema(c)
        check(f"{c} json schema is oneOf-shaped", "oneOf" in schema)
    for c in ("F4", "F5"):
        schema = criterion_json_schema(c)
        check(f"{c} json schema requires required_elements/overall_rationale, has no verdict field",
              {"required_elements", "overall_rationale"} <= set(schema["required"])
              and "verdict" not in schema["properties"])


def test_reason_code_enums_are_disjoint_per_criterion_where_expected():
    for c, codes in ALLOWED_REASON_CODES.items():
        check(f"{c} reason codes include NONE", "NONE" in codes)


def main() -> None:
    print("=" * 70)
    print("RUBRIC_V3 (F1-F5 judge rubric, 2026-08-24 hardening pass) — self-test")
    print("No API key required. No network calls. No cost.")
    print("=" * 70)
    tests = [
        test_f1_aggregate_derivation, test_f2_f3_schema_validation,
        test_rationale_length_is_not_a_validity_criterion,
        test_oneof_grammar_compiles_and_structurally_binds,
        test_no_identity_leak, test_evidence_id_namespace,
        test_f4_schema_validation, test_f4_deterministic_derivation,
        test_f5_schema_and_derivation, test_json_schema_shape,
        test_reason_code_enums_are_disjoint_per_criterion_where_expected,
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
