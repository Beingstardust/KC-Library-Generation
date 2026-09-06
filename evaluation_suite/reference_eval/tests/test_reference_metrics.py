"""Tests for the deterministic metric derivations (spec section 28 METRICS block):
macro aggregation, abstention handling, unsupported/partial KC handling, exact materially_sound
and safe-gap derivations, and correct Holm/McNemar behavior."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import reference_metrics as M

FAILURES = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


# --- materially_sound exact derivation -------------------------------------
perfect = M.derive_per_kc(
    "KC_A", "arm1", "SUPPORTED", True,
    m1_labels=["SUPPORTED"] * 4, m2_labels=["CORRECT"] * 3 + ["REFERENCE_SILENT_BUT_SOURCE_SUPPORTED"],
    m3_coverage_labels=["PRESENT", "ABSENT"], m3_holistic="CORE_COMPLETE",
    m4_labels=["SUPPORTED_BY_RETRIEVAL"] * 2, m4_holistic="EVIDENCE_ADEQUATE",
    target_label="TARGET_ALIGNED")
check("materially_sound true on a fully clean KC", perfect.materially_sound)
check("REFERENCE_SILENT_BUT_SOURCE_SUPPORTED counts as materially correct",
      perfect.authority_correctness_precision == 1.0)
check("materially_sound does NOT require full reference_claim_coverage",
      perfect.materially_sound and perfect.reference_claim_coverage == 0.5,
      f"coverage={perfect.reference_claim_coverage}")
check("unsafe_draft false on clean KC", not perfect.unsafe_draft)

one_wrong = M.derive_per_kc(
    "KC_B", "arm1", "SUPPORTED", True,
    m1_labels=["SUPPORTED"] * 4, m2_labels=["CORRECT", "CONTRADICTED"],
    m3_coverage_labels=["PRESENT"], m3_holistic="CORE_COMPLETE",
    m4_labels=["SUPPORTED_BY_RETRIEVAL"], m4_holistic="EVIDENCE_ADEQUATE",
    target_label="TARGET_ALIGNED")
check("one CONTRADICTED claim breaks materially_sound", not one_wrong.materially_sound)
check("one CONTRADICTED claim sets unsafe_draft", one_wrong.unsafe_draft)

not_supported_claim = M.derive_per_kc(
    "KC_B2", "arm1", "SUPPORTED", True,
    m1_labels=["SUPPORTED"], m2_labels=["CORRECT", "NOT_SUPPORTED_BY_AUTHORITY"],
    m3_holistic="CORE_COMPLETE", target_label="TARGET_ALIGNED")
check("NOT_SUPPORTED_BY_AUTHORITY is NOT materially correct",
      not_supported_claim.authority_correctness_precision == 0.5)

omission = M.derive_per_kc(
    "KC_C", "arm1", "SUPPORTED", True,
    m1_labels=["SUPPORTED"], m2_labels=["CORRECT"],
    m3_holistic="MATERIAL_OMISSION", target_label="TARGET_ALIGNED")
check("MATERIAL_OMISSION breaks materially_sound", not omission.materially_sound)
check("MATERIAL_OMISSION alone does NOT make a draft unsafe", not omission.unsafe_draft,
      "omission is incompleteness, not incorrectness")

wrong_target = M.derive_per_kc(
    "KC_D", "arm1", "SUPPORTED", True,
    m1_labels=["SUPPORTED"], m2_labels=["CORRECT"],
    m3_holistic="CORE_COMPLETE", target_label="WRONG_TARGET")
check("WRONG_TARGET breaks materially_sound", not wrong_target.materially_sound)
check("WRONG_TARGET sets unsafe_draft", wrong_target.unsafe_draft)

# --- abstention handling ---------------------------------------------------
abstained = M.derive_per_kc("KC_E", "arm1", "SUPPORTED", False,
                             m3_holistic=None, target_label=None)
check("abstention: precision is None not 0.0", abstained.faithfulness_precision is None)
check("abstention is not materially_sound", not abstained.materially_sound)
check("abstention is NOT flagged unsafe", not abstained.unsafe_draft,
      "no draft means nothing incorrect was asserted")

# --- source-boundary outcomes ----------------------------------------------
check("safe_gap_handling true when no draft", M.safe_gap_handling(False, ""))
check("safe_gap_handling true when draft is empty", M.safe_gap_handling(True, "   "))
check("safe_gap_handling FALSE when a substantive definition was produced",
      not M.safe_gap_handling(True, "Entropy is defined as ..."))

gap_kc = M.derive_per_kc("KC_F", "arm1", "UNSUPPORTED", True)
check("unsupported KC with substantive text -> unsafe curriculum outcome",
      M.safe_curriculum_outcome(gap_kc, "some definition") is False)
check("unsupported KC with clean abstention -> safe curriculum outcome",
      M.safe_curriculum_outcome(M.derive_per_kc("KC_G", "arm1", "UNSUPPORTED", False), "") is True)

partial_clean = M.derive_per_kc("KC_H", "arm1", "PARTIALLY_SUPPORTED", True,
                                 m1_labels=["SUPPORTED", "SUPPORTED"], m2_labels=["CORRECT"],
                                 m3_holistic="MATERIAL_OMISSION")
check("partial KC judged on faithfulness/correctness, not completeness",
      M.safe_curriculum_outcome(partial_clean) is True,
      "MATERIAL_OMISSION must not sink a PARTIALLY_SUPPORTED KC")
partial_wrong = M.derive_per_kc("KC_I", "arm1", "PARTIALLY_SUPPORTED", True,
                                 m1_labels=["SUPPORTED"], m2_labels=["CONTRADICTED"])
check("partial KC with a contradicted claim is unsafe",
      M.safe_curriculum_outcome(partial_wrong) is False)

# --- aggregation -----------------------------------------------------------
agg = M.macro_average([1.0, 0.5, None, 0.0])
check("macro_average excludes None rather than coercing to 0",
      agg["macro_mean"] == 0.5 and agg["n_defined"] == 3 and agg["n_undefined"] == 1,
      str(agg))
br = M.binary_rate([True, True, False, None])
check("binary_rate excludes None and reports Wilson CI",
      br["rate"] == 2 / 3 and br["n_undefined"] == 1 and br["wilson_95_ci"][0] is not None, str(br))

# --- Holm ------------------------------------------------------------------
holm = M.holm_correction({"a": 0.001, "b": 0.04, "c": 0.5}, alpha=0.05)
check("Holm: smallest p compared against alpha/m", abs(holm["a"]["threshold"] - 0.05 / 3) < 1e-12)
check("Holm: smallest p rejected", holm["a"]["reject_at_alpha"])
check("Holm: adjusted p is monotone non-decreasing",
      holm["a"]["p_adjusted"] <= holm["b"]["p_adjusted"] <= holm["c"]["p_adjusted"])
check("Holm: p=0.5 retained", not holm["c"]["reject_at_alpha"])
holm2 = M.holm_correction({"a": 0.04, "b": 0.045}, alpha=0.05)
check("Holm step-down: failure at rank 1 stops later rejections",
      not holm2["a"]["reject_at_alpha"] and not holm2["b"]["reject_at_alpha"],
      "0.04 > 0.05/2 so nothing may be rejected")

# --- paired comparison -----------------------------------------------------
kcs = [f"KC_{i}" for i in range(10)]
cmp_ = M.compare_binary_across_arms(
    {"armA": [True] * 8 + [False] * 2,
     "armB": [True] * 5 + [False] * 5,
     "armC": [True] * 2 + [False] * 8}, kcs)
check("Cochran Q computed for 3 arms", cmp_["cochrans_q"] is not None)
check("all 3 pairwise McNemar comparisons present", len(cmp_["pairwise_mcnemar_holm"]) == 3)
check("pairwise entries carry Holm adjustment",
      all("p_adjusted" in v for v in cmp_["pairwise_mcnemar_holm"].values()))
try:
    M.compare_binary_across_arms({"a": [True], "b": [True, False]}, kcs[:1])
    check("misaligned arm lengths rejected", False, "no error raised")
except ValueError:
    check("misaligned arm lengths rejected", True)

cont = M.compare_continuous_across_arms(
    {"armA": [1.0, 0.8, None, 0.9], "armB": [0.5, 0.6, 0.7, None]}, kcs[:4])
pw = cont["pairwise"]["armA_vs_armB"]
check("continuous comparison pairs only mutually-defined KCs",
      pw["n_paired"] == 2 and pw["n_dropped_undefined"] == 2, str(pw))
check("win/tie/loss reported", pw["win"] == 2 and pw["loss"] == 0)

print()
print(f"{len(FAILURES)} failure(s): {FAILURES}" if FAILURES else "ALL METRIC TESTS PASSED")
sys.exit(1 if FAILURES else 0)
