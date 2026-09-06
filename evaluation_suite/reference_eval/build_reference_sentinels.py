"""PHASE 7: translate the frozen 36-case sentinel suite into the reference-based tasks.

The sentinels' SUBSTANTIVE TRUTH is not changed - each case still tests exactly the defect it was
built to test. What changes is which task expresses that defect, because the expert reference now
exists and several things the old F1-F5 rubric had to infer can now be checked directly.

Translation map (old holistic rubric -> new reference-based tasks):

  old F1 Evidence Faithfulness  -> M1  candidate claims vs the SAME system evidence.
                                       Same relationship, same truth; carried over directly.
  old F2 Exact KC Alignment     -> TARGET_ALIGNMENT, now decided against the expert reference's
                                       description of the intended KC instead of the v3
                                       extract-subject-and-compare mechanism (retired per spec 9).
  old F3 Material Correctness   -> M2  claims vs expert reference + source authority. Same truth
                                       (is the content right?), but with the mandatory
                                       REFERENCE_SILENT_BUT_SOURCE_SUPPORTED escape path, so a
                                       claim absent from the reference is no longer automatically
                                       wrong.
  old F4 Core Completeness      -> M3 holistic CORE_COMPLETE / MATERIAL_OMISSION.
  old F5 Evidence Sufficiency   -> M4 holistic EVIDENCE_ADEQUATE / MATERIAL_EVIDENCE_GAP.

Three cases do NOT translate as reference-content tests, and are re-typed rather than forced:

  * A sentinel whose KC the expert adjudicated UNSUPPORTED has no gold reference text, so M2/M3
    have nothing to judge against. Those become SOURCE-BOUNDARY cases: the question is whether the
    system produced a substantive definition where the expert established a corpus gap.
  * A sentinel whose KC is PARTIALLY_SUPPORTED gets no completeness expectation (spec section 7B:
    do not require content beyond the expert-supported partial reference).
  * A sentinel with an empty draft_body has no claims to judge; only M4 (evidence-side) and the
    source-boundary question apply.

Nothing here is tuned per case. Every expectation is produced by the category/support-state rules
below, and any sentinel the rules cannot classify is emitted with a NEEDS_REVIEW flag rather than
being given a quietly invented label.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

BASE = Path(__file__).parent
SENTINELS = BASE.parent / "output" / "r9_final" / "rubric_sentinel_gold.jsonl"
REFERENCE = BASE.parent / "reference_library" / "04_gold" / "expert_adjudicated_reference_kc_library.jsonl"
OUT = BASE / "output" / "reference_sentinel_gold.jsonl"
OUT_REPORT = BASE / "output" / "reference_sentinel_translation_report.json"

# Categories whose defect is a wrong/incorrect assertion about the right target.
_CONTENT_ERROR_CATEGORIES = {
    "wrong_coefficients_or_formula",
    "malformed_metric_definition",
    "unnormalized_interpretation_error",
}

# 'complete_but_unsupported' is deliberately NOT a content-error category. Its injected claim is
# TRUE domain knowledge that is simply absent from the supplied evidence, which is why legacy F3
# (Material Correctness - "is the content correct?") passed while F1 failed.
#
# New M2 asks a DIFFERENT question: is the claim supported by the reference OR the source
# authority? A true-but-unsourced claim is NOT_SUPPORTED_BY_AUTHORITY, which the spec explicitly
# does NOT count as materially correct. So legacy F3=PASS cannot simply be carried over here - the
# answer now depends on whether the specific injected claim is present in the AUTHORITY corpus,
# not merely in the system evidence.
#
# Rather than guess, this resolves from what the frozen sentinel record itself already verified.
# Sentinels whose own rationale documents an explicit AUTHORITY-context search establishing the
# claim's absence are set to FAIL; sentinels whose rationale verified only SYSTEM-EVIDENCE absence
# leave M2 undetermined for expert resolution, because authority-absence was never established for
# them and a keyword probe is not a substitute for that judgment.
_UNSUPPORTED_INJECTION_CATEGORY = "complete_but_unsupported"

# A mere mention of "authority context" is NOT evidence of authority-absence - one sentinel's
# record mentions the authority context precisely to say the missing mechanism IS found there.
# The marker must therefore be a sentence that both refers to the authority context AND asserts
# absence from it.
_AUTHORITY_SENTENCE = re.compile(r"[^.]*authorit[^.]*\.", re.IGNORECASE)
_ABSENCE_ASSERTION = re.compile(
    r"\b(nowhere|does not appear|do not appear|not established|never (appears|stated|present)|"
    r"absent from|no .{0,30}(match|mention|occurrence)s? (in|within)|none (of )?(them |the )?(spell|state|mention))\b",
    re.IGNORECASE,
)


def _authority_absence_verified(sentinel: dict) -> tuple[bool, str]:
    """True only when the frozen record contains a sentence that refers to the authority context
    AND asserts the injected claim's absence from it."""
    blob = f"{sentinel.get('rationale', '')} {sentinel.get('provenance', '')}"
    for sent in _AUTHORITY_SENTENCE.findall(blob):
        if _ABSENCE_ASSERTION.search(sent):
            return True, sent.strip()[:300]
    return False, ""


# Categories whose defect is being about the wrong concept entirely.
_WRONG_TARGET_CATEGORIES = {"wrong_target_concept", "faithful_wrong_target", "taxonomy_confusion"}
# Categories whose defect is missing defining content.
_INCOMPLETENESS_CATEGORIES = {"faithful_but_incomplete", "missing_defining_mechanism"}


def _carry(old: str) -> str | None:
    """PASS/FAIL carry over; NOT_APPLICABLE becomes None (task does not apply)."""
    return None if old == "NOT_APPLICABLE" else old


def translate(sentinel: dict, ref: dict) -> dict:
    kc_support = ref["support_state"]
    has_draft = bool((sentinel.get("draft_body") or "").strip())
    cat = sentinel["category"]

    rec: dict = {
        "sentinel_id": sentinel["sentinel_id"],
        "kc_id": sentinel["kc_id"],
        "canonical_name": sentinel["canonical_name"],
        "category": cat,
        "reference_support_state": kc_support,
        "reference_review_action": ref["review_action"],
        "draft_present": has_draft,
        "case_type": None,
        "expected": {},
        "translation_notes": [],
        "needs_review": False,
        "legacy_expected": {
            "f1": sentinel["expected_f1"], "f2": sentinel["expected_f2"], "f3": sentinel["expected_f3"],
            "f4": sentinel["expected_f4"], "f5": sentinel["expected_f5"],
        },
    }

    # ---- source-boundary cases: the expert established a corpus gap for this KC -------------
    if kc_support == "UNSUPPORTED":
        rec["case_type"] = "SOURCE_BOUNDARY"
        rec["expected"] = {
            "safe_gap_handling": not has_draft,
            "M1_faithfulness": _carry(sentinel["expected_f1"]),
            "M4_evidence_adequacy": "MATERIAL_EVIDENCE_GAP",
            "M2_correctness": None,
            "M3_core_completeness": None,
            "TARGET_ALIGNMENT": None,
        }
        rec["translation_notes"].append(
            "The expert adjudicated this KC as a corpus gap (UNSUPPORTED, no gold reference text), so "
            "M2 correctness and M3 completeness have no reference to judge against and are not asked. "
            "The evaluable question is whether the system respected the source boundary."
        )
        if has_draft:
            rec["translation_notes"].append(
                "This case produces a substantive definition for a KC the expert determined the corpus "
                "does not establish, so safe_gap_handling is expected FALSE - an unsafe attempt. Under the "
                "old rubric the same defect had to be caught indirectly as an F2 subject mismatch; the "
                "expert reference now makes it a direct source-boundary violation."
            )
        return rec

    # ---- abstention cases: no draft, so no claim-level candidate task applies ---------------
    if not has_draft:
        rec["case_type"] = "ABSTENTION"
        rec["expected"] = {
            "M1_faithfulness": None, "M2_correctness": None, "M3_core_completeness": None,
            "TARGET_ALIGNMENT": None,
            "M4_evidence_adequacy": "MATERIAL_EVIDENCE_GAP" if sentinel["expected_f5"] == "FAIL" else "EVIDENCE_ADEQUATE",
            "safe_gap_handling": None,
        }
        rec["translation_notes"].append(
            "Empty draft: there are no candidate claims, so M1/M2/M3/target are not asked. Only the "
            "evidence-side question (was adequate evidence available?) is evaluable, which is exactly "
            "what distinguishes a justified abstention from an avoidable one."
        )
        return rec

    # ---- normal reference-content cases ----------------------------------------------------
    rec["case_type"] = "REFERENCE_CONTENT"

    target = "WRONG_TARGET" if (cat in _WRONG_TARGET_CATEGORIES or sentinel["expected_f2"] == "FAIL") else "TARGET_ALIGNED"

    m2 = _carry(sentinel["expected_f3"])
    if cat in _CONTENT_ERROR_CATEGORIES and m2 != "FAIL":
        rec["needs_review"] = True
        rec["translation_notes"].append(
            f"category {cat} implies a content error but legacy F3 was {sentinel['expected_f3']!r} - flagged rather than overridden"
        )

    if cat == _UNSUPPORTED_INJECTION_CATEGORY:
        authority_absence_verified, evidence_sentence = _authority_absence_verified(sentinel)
        if authority_absence_verified:
            rec["m2_basis_quote"] = evidence_sentence
            m2 = "FAIL"
            rec["m2_basis"] = "AUTHORITY_ABSENCE_VERIFIED_IN_FROZEN_SENTINEL_RECORD"
            rec["translation_notes"].append(
                "Injected claim: this sentinel's own frozen rationale/provenance documents an explicit search of "
                "the AUTHORITY context establishing the claim is absent from it. Under new M2 semantics that is "
                "NOT_SUPPORTED_BY_AUTHORITY, which the spec does not count as materially correct, so M2 is FAIL. "
                "This deliberately differs from legacy F3=PASS: old F3 asked whether the content was correct, new "
                "M2 asks whether it is supported by the reference or the source authority. A true but unsourced "
                "claim passes the first test and fails the second."
            )
        else:
            # GOLD_PENDING, not None: an undetermined gold label must be visibly distinct from a
            # task that legitimately does not apply, so it can be excluded from agreement while
            # still being counted and reported (spec section 6).
            m2 = "GOLD_PENDING"
            rec["needs_expert_determination"] = ["M2_correctness"]
            rec["needs_review"] = True
            rec["m2_basis"] = "ONLY_SYSTEM_EVIDENCE_ABSENCE_VERIFIED"
            rec["translation_notes"].append(
                "Injected claim: this sentinel's frozen record verifies only that the claim is absent from the "
                "SYSTEM EVIDENCE, never that it is absent from the AUTHORITY corpus. New M2 turns on exactly that "
                "unverified question, so M2 is left undetermined for expert resolution rather than guessed. The "
                "case still tests M1 fully, which is what it was built for."
            )

    m3 = _carry(sentinel["expected_f4"])
    if kc_support == "PARTIALLY_SUPPORTED":
        m3 = None
        rec["translation_notes"].append(
            "KC is PARTIALLY_SUPPORTED: the expert reference does not establish a complete definition, so "
            "no completeness expectation is set (spec 7B - do not require content beyond the supported portion)."
        )
    elif cat in _INCOMPLETENESS_CATEGORIES and m3 != "FAIL":
        rec["needs_review"] = True
        rec["translation_notes"].append(
            f"category {cat} implies missing defining content but legacy F4 was {sentinel['expected_f4']!r} - flagged rather than overridden"
        )

    rec["expected"] = {
        "M1_faithfulness": _carry(sentinel["expected_f1"]),
        "M2_correctness": m2,
        "M3_core_completeness": ("MATERIAL_OMISSION" if m3 == "FAIL" else "CORE_COMPLETE") if m3 else None,
        "M4_evidence_adequacy": "MATERIAL_EVIDENCE_GAP" if sentinel["expected_f5"] == "FAIL" else "EVIDENCE_ADEQUATE",
        "TARGET_ALIGNMENT": target,
        "safe_gap_handling": None,
    }

    # orthogonality note required by spec 14 - these tasks are deliberately independent
    if cat == "wrong_coefficients_or_formula":
        rec["translation_notes"].append(
            "Wrong-formula case: M2 must FAIL on the formula claim. Target normally stays ALIGNED (the draft is "
            "about the right concept), and M1 depends on what the supplied evidence itself contains - a wrong "
            "formula can still be faithful to wrong evidence. This orthogonality is intentional."
        )
    elif cat in _WRONG_TARGET_CATEGORIES:
        rec["translation_notes"].append(
            "Wrong-target case: TARGET_ALIGNMENT must be WRONG_TARGET and M2 must FAIL for the intended KC, "
            "while M1 may legitimately PASS if the retrieved evidence itself supported the wrong concept."
        )
    elif cat == "complete_but_unsupported":
        rec["translation_notes"].append(
            "Unsupported-content case: the defect is in M1 (claims not backed by the supplied evidence). M2 may "
            "still pass if the content happens to be correct for the KC - correctness and groundedness are "
            "separate questions."
        )
    return rec


def main() -> int:
    sentinels = [json.loads(l) for l in open(SENTINELS, encoding="utf-8") if l.strip()]
    reference = {json.loads(l)["knowledge_unit_id"]: json.loads(l)
                 for l in open(REFERENCE, encoding="utf-8") if l.strip()}

    missing = [s["kc_id"] for s in sentinels if s["kc_id"] not in reference]
    if missing:
        print(f"REFUSED: {len(missing)} sentinel KC ids are absent from the frozen reference: {sorted(set(missing))}")
        return 1

    out = [translate(s, reference[s["kc_id"]]) for s in sentinels]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    report = {
        "n_sentinels": len(out),
        "source_suite": str(SENTINELS.name),
        "reference": str(REFERENCE.name),
        "case_types": dict(Counter(r["case_type"] for r in out)),
        "needs_review": [r["sentinel_id"] for r in out if r["needs_review"]],
        "expected_label_distributions": {
            task: dict(Counter(r["expected"].get(task) for r in out))
            for task in ("M1_faithfulness", "M2_correctness", "M3_core_completeness",
                          "M4_evidence_adequacy", "TARGET_ALIGNMENT", "safe_gap_handling")
        },
        "reference_support_state_of_sentinel_kcs": dict(Counter(r["reference_support_state"] for r in out)),
        "note": "Substantive truth of every sentinel is unchanged; only the task expressing it changed. "
                "Cases whose KC the expert adjudicated UNSUPPORTED were re-typed as SOURCE_BOUNDARY rather "
                "than forced into a reference-content comparison that has no reference to compare against.",
    }
    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(json.dumps(report, indent=2))
    print(f"\nwrote {OUT.name} ({len(out)} cases) and {OUT_REPORT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
