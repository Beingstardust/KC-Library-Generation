"""Deterministic per-KC metric derivation and paired system comparison for the reference-based
evaluation (spec sections 19-21, 25).

Everything here is computed in Python from per-claim labels. No metric is ever taken from a
model's own aggregate statement - that is the central lesson carried over from the Selene v3
development work.

PRIMARY aggregation is KC-macro, not pooled claims: a KC with 30 claims must not outweigh a KC
with 4. Micro totals are reported alongside as secondary diagnostics only.

Reuses the already-tested primitives in evaluation_suite/final_pipeline/statistics.py
(wilson_interval, cochrans_q, mcnemar_exact, paired_bootstrap_ci, gwet_ac1). Only Holm correction,
which that module does not provide, is implemented here.
"""
from __future__ import annotations

import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import numpy as np  # noqa: E402
from statistics import (  # noqa: E402
    cochrans_q, mcnemar_exact, paired_bootstrap_ci, wilson_interval,
)

sys.path.insert(0, str(Path(__file__).parent))
from reference_judge_schema import M2_MATERIALLY_CORRECT  # noqa: E402


# ---------------------------------------------------------------------------
# Holm-Bonferroni step-down correction (not present in statistics.py)
# ---------------------------------------------------------------------------
def holm_correction(pvalues: dict[str, float], alpha: float = 0.05) -> dict[str, dict]:
    """Holm step-down: sort ascending, compare p_(i) against alpha/(m-i), and once a comparison
    fails every later (larger-p) hypothesis is retained regardless of its own threshold. The
    monotonicity enforcement on adjusted p-values is what makes the reported adjusted values
    coherent with the reject/retain decisions."""
    items = sorted(pvalues.items(), key=lambda kv: kv[1])
    m = len(items)
    out: dict[str, dict] = {}
    prev_adj = 0.0
    still_rejecting = True
    for i, (name, p) in enumerate(items):
        threshold = alpha / (m - i)
        adj = min(1.0, max(prev_adj, p * (m - i)))  # enforce monotone non-decreasing adjusted p
        prev_adj = adj
        if still_rejecting and p > threshold:
            still_rejecting = False
        out[name] = {
            "p_raw": p, "p_adjusted": adj, "threshold": threshold,
            "reject_at_alpha": bool(still_rejecting), "rank": i + 1, "n_hypotheses": m,
        }
    return out


# ---------------------------------------------------------------------------
# Per-KC metric record
# ---------------------------------------------------------------------------
@dataclass
class PerKCMetrics:
    kc_id: str
    arm_id: str
    support_state: str
    draft_exists: bool

    # continuous (None when not computable, never silently 0.0)
    faithfulness_precision: float | None = None
    authority_correctness_precision: float | None = None
    reference_claim_coverage: float | None = None
    retrieval_reference_recall: float | None = None

    # holistic binaries (None when NOT_JUDGEABLE)
    target_aligned: bool | None = None
    core_complete: bool | None = None
    # EXPLORATORY ONLY - demoted 2026-08-25 (EVALUATION_SCOPE_AMENDMENT_v2). Retained on the record
    # for the audit trail and optional research annotation. It is deliberately NOT referenced by
    # materially_sound, unsafe_draft, safe_curriculum_outcome, or any qualification gate. See
    # reference_judge_schema.METRIC_SCOPE["EXPLORATORY_HOLISTIC_EVIDENCE_ADEQUACY"].
    exploratory_holistic_evidence_adequacy: bool | None = None

    # derived
    materially_sound: bool = False
    unsafe_draft: bool = False

    # counts for micro-aggregation / auditing
    n_candidate_claims: int = 0
    n_reference_claims: int = 0
    n_faithful_supported: int = 0
    n_materially_correct: int = 0
    n_reference_claims_covered: int = 0
    n_reference_claims_retrieved: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def _precision(numerator: int, denominator: int) -> float | None:
    """None, not 0.0, when there is nothing to divide by - an abstention has no precision, and
    scoring it 0.0 would silently punish safe abstention as if it were maximally wrong."""
    if denominator <= 0:
        return None
    return numerator / denominator


def derive_per_kc(
    kc_id: str,
    arm_id: str,
    support_state: str,
    draft_exists: bool,
    m1_labels: list[str] | None = None,
    m2_labels: list[str] | None = None,
    m3_coverage_labels: list[str] | None = None,
    m3_holistic: str | None = None,
    m4_labels: list[str] | None = None,
    m4_holistic: str | None = None,   # exploratory only; recorded, never used in a derivation
    target_label: str | None = None,
) -> PerKCMetrics:
    """Single deterministic derivation point for one KC x one arm. Every field is computed from
    the label lists; nothing is inferred from a model-stated aggregate."""
    m1_labels = m1_labels or []
    m2_labels = m2_labels or []
    m3_coverage_labels = m3_coverage_labels or []
    m4_labels = m4_labels or []

    n_cand = len(m1_labels) or len(m2_labels)
    n_ref = len(m3_coverage_labels) or len(m4_labels)

    n_faithful = sum(1 for l in m1_labels if l == "SUPPORTED")
    n_correct = sum(1 for l in m2_labels if l in M2_MATERIALLY_CORRECT)
    # PARTIALLY_PRESENT counts as half: it is a descriptive coverage measure, and treating a
    # partially conveyed claim as fully present or fully absent both misstate it.
    n_covered_weighted = sum(1.0 for l in m3_coverage_labels if l == "PRESENT") + \
                          sum(0.5 for l in m3_coverage_labels if l == "PARTIALLY_PRESENT")
    n_retrieved = sum(1 for l in m4_labels if l == "SUPPORTED_BY_RETRIEVAL")

    faith = _precision(n_faithful, len(m1_labels))
    corr = _precision(n_correct, len(m2_labels))
    cover = (n_covered_weighted / len(m3_coverage_labels)) if m3_coverage_labels else None
    recall = _precision(n_retrieved, len(m4_labels))

    target_aligned = {"TARGET_ALIGNED": True, "WRONG_TARGET": False}.get(target_label)  # None if NOT_JUDGEABLE
    core_complete = {"CORE_COMPLETE": True, "MATERIAL_OMISSION": False}.get(m3_holistic)
    exploratory_adequacy = {"EVIDENCE_ADEQUATE": True, "MATERIAL_EVIDENCE_GAP": False}.get(m4_holistic)

    # Exact derivation. Deliberately does NOT require reference_claim_coverage == 1.0, and
    # deliberately excludes BOTH M4 outputs: retrieval_reference_recall is an upstream explanatory
    # metric and holistic adequacy is demoted to exploratory. materially_sound measures the final
    # KC DRAFT; retrieval coverage explains that outcome rather than defining it.
    materially_sound = bool(
        draft_exists
        and target_aligned is True
        and faith == 1.0
        and corr == 1.0
        and core_complete is True
    )
    unsafe_draft = bool(
        draft_exists
        and (
            target_aligned is False
            or (corr is not None and corr < 1.0)
            or (faith is not None and faith < 1.0)
        )
    )

    return PerKCMetrics(
        kc_id=kc_id, arm_id=arm_id, support_state=support_state, draft_exists=draft_exists,
        faithfulness_precision=faith, authority_correctness_precision=corr,
        reference_claim_coverage=cover, retrieval_reference_recall=recall,
        target_aligned=target_aligned, core_complete=core_complete,
        exploratory_holistic_evidence_adequacy=exploratory_adequacy,
        materially_sound=materially_sound, unsafe_draft=unsafe_draft,
        n_candidate_claims=n_cand, n_reference_claims=n_ref,
        n_faithful_supported=n_faithful, n_materially_correct=n_correct,
        n_reference_claims_covered=int(n_covered_weighted), n_reference_claims_retrieved=n_retrieved,
    )


# ---------------------------------------------------------------------------
# Source-boundary outcomes (spec section 21)
# ---------------------------------------------------------------------------
def safe_gap_handling(draft_exists: bool, draft_text: str, target_label: str | None = None) -> bool:
    """For an expert-adjudicated corpus gap: producing no substantive definition is the safe
    outcome. A clean abstention (no draft, or an explicitly empty one) is safe."""
    if not draft_exists:
        return True
    return not (draft_text or "").strip()


def safe_partial_behavior(m1_precision: float | None, m2_precision: float | None) -> bool | None:
    """For PARTIALLY_SUPPORTED KCs there is no complete gold definition, so completeness is not
    assessed. Safe behavior = what the draft does say is faithful and authority-correct; it is not
    penalized for omitting content the expert reference itself does not establish."""
    if m1_precision is None and m2_precision is None:
        return None
    return (m1_precision in (None, 1.0)) and (m2_precision in (None, 1.0))


def safe_curriculum_outcome(m: PerKCMetrics, draft_text: str = "") -> bool | None:
    """All-159 secondary outcome. Deterministic and documented BEFORE results are opened, per the
    spec's requirement. Deliberately kept separate from the primary 150-KC content measure."""
    if m.support_state == "SUPPORTED":
        return m.materially_sound
    if m.support_state == "PARTIALLY_SUPPORTED":
        return safe_partial_behavior(m.faithfulness_precision, m.authority_correctness_precision)
    if m.support_state == "UNSUPPORTED":
        return safe_gap_handling(m.draft_exists, draft_text, m.target_aligned)
    raise ValueError(f"unknown support_state {m.support_state!r}")


# ---------------------------------------------------------------------------
# KC-macro aggregation
# ---------------------------------------------------------------------------
def macro_average(values: list[float | None]) -> dict:
    """KC-macro mean over the KCs where the metric is defined. KCs where it is None are excluded
    and counted, never coerced to 0."""
    present = [v for v in values if v is not None]
    return {
        "macro_mean": (sum(present) / len(present)) if present else None,
        "n_defined": len(present),
        "n_undefined": len(values) - len(present),
        "n_total": len(values),
    }


def binary_rate(flags: list[bool | None]) -> dict:
    present = [f for f in flags if f is not None]
    k = sum(1 for f in present if f)
    lo, hi = wilson_interval(k, len(present)) if present else (None, None)
    return {
        "rate": (k / len(present)) if present else None,
        "successes": k, "n_defined": len(present),
        "n_undefined": len(flags) - len(present), "n_total": len(flags),
        "wilson_95_ci": [lo, hi],
    }


# ---------------------------------------------------------------------------
# Paired system comparison (spec section 25)
# ---------------------------------------------------------------------------
def compare_binary_across_arms(per_arm: dict[str, list[bool]], kc_order: list[str],
                                alpha: float = 0.05) -> dict:
    """Cochran Q omnibus over >=3 paired arms, then exact McNemar pairwise with Holm correction
    within this comparison family. Pairing is by KC index - callers must supply arms whose lists
    are aligned to kc_order (verified here rather than trusted)."""
    arms = sorted(per_arm)
    for a in arms:
        if len(per_arm[a]) != len(kc_order):
            raise ValueError(f"arm {a} has {len(per_arm[a])} values but kc_order has {len(kc_order)}")

    matrix = np.array([[1 if per_arm[a][i] else 0 for a in arms] for i in range(len(kc_order))])

    result: dict = {"arms": arms, "n_kc": len(kc_order),
                     "per_arm_successes": {a: int(sum(per_arm[a])) for a in arms}}

    if len(arms) >= 3:
        q, p = cochrans_q(matrix)
        result["cochrans_q"] = {"Q": q, "p_value": p}
    else:
        result["cochrans_q"] = None

    pvals, details = {}, {}
    for i in range(len(arms)):
        for j in range(i + 1, len(arms)):
            a, b = arms[i], arms[j]
            av = np.array([1 if x else 0 for x in per_arm[a]])
            bv = np.array([1 if x else 0 for x in per_arm[b]])
            n_disc, p = mcnemar_exact(av, bv)
            key = f"{a}_vs_{b}"
            pvals[key] = p
            details[key] = {
                "n_discordant": int(n_disc), "p_value": p,
                "a_only": int(np.sum((av == 1) & (bv == 0))),
                "b_only": int(np.sum((av == 0) & (bv == 1))),
                "both": int(np.sum((av == 1) & (bv == 1))),
                "neither": int(np.sum((av == 0) & (bv == 0))),
            }
    holm = holm_correction(pvals, alpha=alpha) if pvals else {}
    for key in details:
        details[key].update(holm.get(key, {}))
    result["pairwise_mcnemar_holm"] = details
    return result


def compare_continuous_across_arms(per_arm: dict[str, list[float | None]], kc_order: list[str],
                                    replicates: int = 5000, seed: int = 20260825) -> dict:
    """Paired bootstrap on per-KC continuous metrics. Only KCs where BOTH arms have a defined
    value enter a given pairwise comparison; how many were dropped is reported rather than hidden,
    because dropping differs by pair and silently changes the denominator."""
    arms = sorted(per_arm)
    out: dict = {"arms": arms, "n_kc": len(kc_order), "pairwise": {}}
    for i in range(len(arms)):
        for j in range(i + 1, len(arms)):
            a, b = arms[i], arms[j]
            pairs = [(x, y) for x, y in zip(per_arm[a], per_arm[b]) if x is not None and y is not None]
            key = f"{a}_vs_{b}"
            if not pairs:
                out["pairwise"][key] = {"n_paired": 0, "note": "no KC has both values defined"}
                continue
            av = [p[0] for p in pairs]
            bv = [p[1] for p in pairs]
            boot = paired_bootstrap_ci(av, bv, replicates=replicates, seed=seed)
            wins = sum(1 for x, y in pairs if x > y)
            losses = sum(1 for x, y in pairs if x < y)
            ties = sum(1 for x, y in pairs if x == y)
            out["pairwise"][key] = {
                "n_paired": len(pairs), "n_dropped_undefined": len(kc_order) - len(pairs),
                "mean_difference": boot.get("observed"), "bootstrap": boot,
                "win": wins, "tie": ties, "loss": losses,
            }
    return out
