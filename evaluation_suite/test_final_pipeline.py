"""Self-test for the final-pipeline evaluation suite modules (statistics, schema,
system_accounting, provenance). Zero API key, zero network calls, zero cost - matches the
existing dry_run_self_test.py convention in evaluation_suite/.

Run: python test_final_pipeline.py
Must print "ALL CHECKS PASSED" before any of these modules are trusted with real data.

Covers section 14's items that are implemented so far:
  1. Evidence relevance precision formula
  2. Claim-level faithfulness formula
  3. Empty evidence behavior
  4. Empty/non-substantive draft behavior
  5. Derived draft adequacy
  6. Justified abstention derivation
  7. Avoidable abstention derivation
  8. Provenance pointer resolution
  10. Judge schema validation
  11. No drafter/system identity in judge payload
  14. Raw count -> percentage consistency
Not yet covered here (need the not-yet-built modules): 9 (baseline/proposed token-budget parity),
12 (calibration sampler reproducibility), 13 (statistical test input pairing end-to-end),
15/16 (ACTIVE pointer / production artifact guards - belong to whatever runner script actually
touches the HPC side, not these pure-Python modules).
"""
from __future__ import annotations

import sys

from schema import (
    JudgeSchemaError, build_judge_payload, compute_derived_scores, validate_judge_response,
)
from system_accounting import (
    AbstentionRow, attempt_coverage_rate, classify_abstention, compute_abstention_rates,
    conditional_success_rate, end_to_end_usable_yield,
)
from provenance import summarize_provenance, validate_draft_provenance
from statistics import cohens_kappa, gwet_ac1, paired_bootstrap_ci

CHECKS_PASSED: list[str] = []
CHECKS_FAILED: list[tuple[str, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        CHECKS_PASSED.append(name)
        print(f"  [PASS] {name}")
    else:
        CHECKS_FAILED.append((name, detail))
        print(f"  [FAIL] {name}  -- {detail}")


def expect_raises(fn, exc_type) -> bool:
    try:
        fn()
    except exc_type:
        return True
    except Exception:  # wrong exception type is still a failure
        return False
    return False


# --- 1. evidence relevance precision -----------------------------------------------------------

def test_evidence_relevance_precision():
    payload = {
        "kc_id": "KC_TEST_001",
        "evidence_relevance": {"passages": [
            {"passage_id": "p1", "relevant": True},
            {"passage_id": "p2", "relevant": True},
            {"passage_id": "p3", "relevant": False, "reason_if_irrelevant": "sibling concept, not this KC"},
        ]},
        "evidence_sufficiency": {"sufficient": True},
        "draft_groundedness": {"claims": [{"claim": "x", "supported": True, "supporting_passage_ids": ["p1"]}]},
        "draft_adequacy": {"interpretable_definition": True, "captures_core_supported_content": True},
    }
    validate_judge_response(payload)
    scores = compute_derived_scores(payload)
    check("evidence_relevance_precision = 2/3", abs(scores.evidence_relevance_precision - (2 / 3)) < 1e-5,
          str(scores.evidence_relevance_precision))
    check("relevant_passage_count == 2", scores.relevant_passage_count == 2)
    check("selected_passage_count == 3", scores.selected_passage_count == 3)


# --- 2. claim-level faithfulness -----------------------------------------------------------------

def test_faithfulness_ratio():
    payload = _base_payload(claims=[
        {"claim": "a", "supported": True, "supporting_passage_ids": ["p1"]},
        {"claim": "b", "supported": True, "supporting_passage_ids": ["p2"]},
        {"claim": "c", "supported": False, "supporting_passage_ids": []},
        {"claim": "d", "supported": False, "supporting_passage_ids": []},
    ])
    validate_judge_response(payload)
    scores = compute_derived_scores(payload)
    check("faithfulness_ratio = 2/4", abs(scores.faithfulness_ratio - 0.5) < 1e-9, str(scores.faithfulness_ratio))
    check("categorical_faithfulness = partially_faithful", scores.categorical_faithfulness == "partially_faithful")

    all_supported = _base_payload(claims=[{"claim": "a", "supported": True, "supporting_passage_ids": ["p1"]}])
    validate_judge_response(all_supported)
    check("categorical_faithfulness = faithful when all supported",
          compute_derived_scores(all_supported).categorical_faithfulness == "faithful")

    none_supported = _base_payload(claims=[{"claim": "a", "supported": False, "supporting_passage_ids": []}])
    validate_judge_response(none_supported)
    check("categorical_faithfulness = unfaithful when none supported",
          compute_derived_scores(none_supported).categorical_faithfulness == "unfaithful")


# --- 3. empty evidence (no passages selected) -----------------------------------------------------

def test_empty_evidence():
    payload = _base_payload(claims=[{"claim": "a", "supported": True, "supporting_passage_ids": ["p1"]}])
    payload["evidence_relevance"] = {"passages": []}
    validate_judge_response(payload)  # empty passages list is structurally valid
    scores = compute_derived_scores(payload)
    check("evidence_relevance_precision is None (NA) when no passages selected",
          scores.evidence_relevance_precision is None)
    check("selected_passage_count == 0", scores.selected_passage_count == 0)


# --- 4. empty / non-substantive draft ---------------------------------------------------------

def test_empty_draft():
    payload = _base_payload(claims=[])
    payload["draft_groundedness"]["empty_or_non_substantive_draft"] = True
    validate_judge_response(payload)
    scores = compute_derived_scores(payload)
    check("faithfulness_ratio is None for empty draft", scores.faithfulness_ratio is None)
    check("categorical_faithfulness = not_applicable for empty draft",
          scores.categorical_faithfulness == "not_applicable")

    bad_payload = _base_payload(claims=[])  # no empty_or_non_substantive_draft flag set
    check("empty claims without the flag is rejected by schema validation",
          expect_raises(lambda: validate_judge_response(bad_payload), JudgeSchemaError))


# --- 5. derived draft adequacy -------------------------------------------------------------------

def test_draft_adequacy():
    both_true = _base_payload()
    both_true["draft_adequacy"] = {"interpretable_definition": True, "captures_core_supported_content": True}
    validate_judge_response(both_true)
    check("draft_adequate True when both checks True", compute_derived_scores(both_true).draft_adequate is True)

    one_false = _base_payload()
    one_false["draft_adequacy"] = {
        "interpretable_definition": True, "captures_core_supported_content": False,
        "failure_reason": "omits the core supported mechanism",
    }
    validate_judge_response(one_false)
    check("draft_adequate False when one check is False", compute_derived_scores(one_false).draft_adequate is False)

    missing_reason = _base_payload()
    missing_reason["draft_adequacy"] = {"interpretable_definition": False, "captures_core_supported_content": True}
    check("adequacy False without failure_reason is rejected",
          expect_raises(lambda: validate_judge_response(missing_reason), JudgeSchemaError))


# --- 6/7. abstention validity derivation ------------------------------------------------------

def test_abstention_classification():
    check("sufficient+drafted -> supported_attempt", classify_abstention(True, "drafted") == "supported_attempt")
    check("sufficient+abstained -> avoidable_abstention", classify_abstention(True, "abstained") == "avoidable_abstention")
    check("insufficient+abstained -> justified_abstention", classify_abstention(False, "abstained") == "justified_abstention")
    check("insufficient+drafted -> risky_attempt", classify_abstention(False, "drafted") == "risky_attempt")

    rows = [
        AbstentionRow("k1", True, "drafted"),
        AbstentionRow("k2", True, "drafted"),
        AbstentionRow("k3", True, "abstained"),   # avoidable
        AbstentionRow("k4", False, "abstained"),  # justified
        AbstentionRow("k5", False, "abstained"),  # justified
        AbstentionRow("k6", False, "drafted"),    # risky
    ]
    rates = compute_abstention_rates(rows)
    check("n_justified_abstention == 2", rates.n_justified_abstention == 2)
    check("n_avoidable_abstention == 1", rates.n_avoidable_abstention == 1)
    check("abstention_precision = 2/3", abs(rates.abstention_precision - (2 / 3)) < 1e-5)
    check("avoidable_abstention_rate = 1/3 (of 3 sufficient-evidence cases)",
          abs(rates.avoidable_abstention_rate - (1 / 3)) < 1e-5)
    check("unsupported_attempt_rate = 1/3 (of 3 insufficient-evidence cases)",
          abs(rates.unsupported_attempt_rate - (1 / 3)) < 1e-5)


# --- 8. provenance pointer resolution ----------------------------------------------------------

def test_provenance_resolution():
    packet = {
        "evidence_for_synthesis": [
            {"evidence_id": "e1", "doc_id": "DOC_x", "text": "real passage text"},
            {"evidence_id": "e2", "doc_id": "", "text": "text but no doc_id"},  # resolved_but_incomplete
        ]
    }
    draft_record = {
        "draft": {
            "contextual_kc_draft": {"supporting_evidence_ids": ["e1", "e_missing"]},
            "evidence_map": [{"supporting_passage_ids": [], "supporting_evidence_ids": ["e2"]}],
        }
    }
    links = validate_draft_provenance("KC_TEST", draft_record, packet)
    check("3 citations found", len(links) == 3, str(len(links)))
    report = summarize_provenance(links)
    check("1 of 3 links resolved (e1 only)", report.resolved_links == 1, str(report.resolved_links))
    check("provenance_resolution_rate = 1/3", abs(report.provenance_resolution_rate - (1 / 3)) < 1e-5)
    reasons = {l.evidence_id: l.failure_reason for l in report.invalid_links}
    check("e_missing reported as not-present", "not present" in reasons.get("e_missing", ""))
    check("e2 reported as resolved-but-incomplete", "missing required field" in reasons.get("e2", ""))


# --- 10. judge schema validation (general malformed-input coverage) -----------------------------

def test_schema_validation_rejects_malformed():
    check("non-dict payload rejected", expect_raises(lambda: validate_judge_response([]), JudgeSchemaError))
    check("missing top-level key rejected",
          expect_raises(lambda: validate_judge_response({"kc_id": "x"}), JudgeSchemaError))
    irrelevant_no_reason = _base_payload()
    irrelevant_no_reason["evidence_relevance"] = {"passages": [{"passage_id": "p1", "relevant": False}]}
    check("irrelevant passage without reason rejected",
          expect_raises(lambda: validate_judge_response(irrelevant_no_reason), JudgeSchemaError))
    insufficient_no_reason = _base_payload()
    insufficient_no_reason["evidence_sufficiency"] = {"sufficient": False}
    check("insufficient evidence without missing_information rejected",
          expect_raises(lambda: validate_judge_response(insufficient_no_reason), JudgeSchemaError))
    supported_no_ids = _base_payload(claims=[{"claim": "a", "supported": True, "supporting_passage_ids": []}])
    check("supported claim without supporting_passage_ids rejected",
          expect_raises(lambda: validate_judge_response(supported_no_ids), JudgeSchemaError))


# --- 11. no drafter/system identity in judge payload --------------------------------------------

def test_no_identity_leak():
    payload = build_judge_payload(
        kc_id="KC_1", kc_name="Some KC", hierarchy_context="Topic > Sub",
        passages=[{"passage_id": "p1", "text": "clean passage text"}],
        draft_text="a clean draft with no identity markers",
    )
    check("clean payload builds without error", "kc_id" in payload)
    check("no system_behavior key when not passed", "system_behavior" not in payload)

    leaked = lambda: build_judge_payload(
        kc_id="KC_1", kc_name="Some KC", hierarchy_context="Topic > Sub",
        passages=[{"passage_id": "p1", "text": "this passage mentions Qwen by name"}],
        draft_text="a draft",
    )
    check("passage text leaking a model name is caught", expect_raises(leaked, JudgeSchemaError))

    with_behavior = build_judge_payload(
        kc_id="KC_1", kc_name="Some KC", hierarchy_context="Topic > Sub",
        passages=[], draft_text=None, system_behavior="abstained",
    )
    check("system_behavior passed through when explicitly requested", with_behavior["system_behavior"] == "abstained")


# --- 14. raw count -> percentage consistency ----------------------------------------------------

def test_rate_reports_carry_raw_counts():
    r = attempt_coverage_rate(attempted_drafts=140, intended_kcs=159)
    d = r.as_dict()
    check("attempt_coverage_rate carries numerator/denominator/percentage",
          d["numerator"] == 140 and d["denominator"] == 159 and d["percentage"] is not None)
    check("percentage matches numerator/denominator", abs(d["percentage"] - 100 * 140 / 159) < 0.01)

    zero_denom = conditional_success_rate(successful_acceptable_drafts=0, attempted_drafts=0)
    check("zero-denominator rate is None, not a crash or fake 0", zero_denom.rate is None)

    yld = end_to_end_usable_yield(successful_acceptable_drafts=100, intended_kcs=159)
    check("end_to_end_usable_yield rate correct", abs(yld.rate - 100 / 159) < 1e-5)


# --- Gwet AC1 stability under the documented kappa-paradox scenario ------------------------------

def test_gwet_ac1_kappa_paradox_reference_case():
    """Hand-verified: 20 items, 90% raw agreement, one rater's marginal is degenerate.
    Confirmed numerically (sklearn.cohen_kappa_score) before this test was written:
    Cohen's kappa collapses to exactly 0.0 despite 90% raw agreement. Gwet's AC1 stays ~0.8895 -
    this is the exact documented property [GWET2008] motivates AC1 for.
    """
    r1 = ["not_relevant"] * 18 + ["relevant"] * 2
    r2 = ["not_relevant"] * 20
    kappa = cohens_kappa(r1, r2)
    ac1 = gwet_ac1(r1, r2)
    check("kappa is exactly 0.0 on the paradox case (reference, not this module's own code)",
          abs(kappa - 0.0) < 1e-9, str(kappa))
    check("Gwet AC1 stays ~0.8895 on the same data", abs(ac1["ac1"] - 0.889503) < 1e-4, str(ac1))
    check("AC1 > kappa by a wide margin on this exact case (the property AC1 exists for)",
          ac1["ac1"] - kappa > 0.5)

    perfect = gwet_ac1(["a", "b", "a", "a"], ["a", "b", "a", "a"])
    check("AC1 = 1.0 exactly under perfect agreement", perfect["ac1"] == 1.0)

    degenerate = gwet_ac1(["a", "a", "a"], ["a", "a", "a"])
    check("AC1 undefined (None) when fewer than 2 categories present, not a fake 1.0",
          degenerate["ac1"] is None and degenerate["undefined_reason"] is not None)


def test_paired_bootstrap_ci_smoke():
    ci = paired_bootstrap_ci([0.9, 0.85, 0.95, 0.88, 0.92], [0.6, 0.55, 0.65, 0.58, 0.62], replicates=3000)
    check("bootstrap point estimate matches raw mean difference",
          abs(ci["point_estimate"] - 0.3) < 1e-9, str(ci["point_estimate"]))
    check("bootstrap CI excludes zero for a clearly separated paired sample", ci["excludes_zero"] is True)
    identical = paired_bootstrap_ci([0.5, 0.5, 0.5], [0.5, 0.5, 0.5], replicates=500)
    check("bootstrap CI does not exclude zero when conditions are identical", identical["excludes_zero"] is False)


# --- helpers --------------------------------------------------------------------------------------

def _base_payload(claims=None):
    if claims is None:
        claims = [{"claim": "a material claim", "supported": True, "supporting_passage_ids": ["p1"]}]
    return {
        "kc_id": "KC_TEST_BASE",
        "evidence_relevance": {"passages": [{"passage_id": "p1", "relevant": True}]},
        "evidence_sufficiency": {"sufficient": True},
        "draft_groundedness": {"claims": claims},
        "draft_adequacy": {"interpretable_definition": True, "captures_core_supported_content": True},
    }


def main() -> None:
    print("=" * 70)
    print("FINAL-PIPELINE EVALUATION SUITE — self-test")
    print("No API key required. No network calls. No cost.")
    print("=" * 70)
    tests = [
        test_evidence_relevance_precision, test_faithfulness_ratio, test_empty_evidence,
        test_empty_draft, test_draft_adequacy, test_abstention_classification,
        test_provenance_resolution, test_schema_validation_rejects_malformed,
        test_no_identity_leak, test_rate_reports_carry_raw_counts,
        test_gwet_ac1_kappa_paradox_reference_case, test_paired_bootstrap_ci_smoke,
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
