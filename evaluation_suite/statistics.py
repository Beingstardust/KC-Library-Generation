"""Statistics for the final-pipeline evaluation suite.

Reuses proven, already-tested functions from the authority-v2 significance module
(mcnemar_exact, cochrans_q) rather than duplicating them - same formulas, same edge-case
handling, imported directly. Adds what authority-v2 does not have:

- Gwet's AC1 (gwet_ac1): the primary chance-corrected agreement statistic for this suite's
  categorical judgments, per [GWET2008]. Cohen's kappa (still computed alongside, for
  continuity/comparison) is known to collapse toward zero - or go undefined/negative - on
  high-agreement, high-prevalence-imbalance data, exactly the shape evidence_relevance labels
  are expected to have (most selected passages ARE relevant; the judge's job is catching the
  minority that aren't). See test_statistics.py's kappa_paradox_reference_case for a real,
  hand-verified demonstration: 90% raw agreement, Cohen's kappa = 0.0, Gwet's AC1 ~= 0.89.
- paired_bootstrap_ci: percentile bootstrap CI for a paired mean/median difference between two
  conditions on a continuous/proportion metric (e.g. evidence_relevance_precision,
  faithfulness ratio) - for section 10's "paired continuous/proportion metrics" requirement,
  parallel to authority_agreement_metrics.cluster_bootstrap_intervals's existing KC-cluster
  bootstrap for categorical agreement.
- wilson_interval is reused as-is from authority_agreement_metrics (already correct, already
  tested) - import directly, do not duplicate.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Sequence

import numpy as np

import sys
from pathlib import Path

_PARENT = Path(__file__).resolve().parent.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

from authority_agreement_metrics import wilson_interval  # noqa: E402  (reused, not duplicated)
from compute_authority_significance import cochrans_q, mcnemar_exact  # noqa: E402  (reused, not duplicated)

__all__ = [
    "gwet_ac1",
    "paired_bootstrap_ci",
    "wilson_interval",
    "cochrans_q",
    "mcnemar_exact",
    "cohens_kappa",
]


def cohens_kappa(rater1: Sequence[Any], rater2: Sequence[Any]) -> float | None:
    """Thin wrapper kept local to this module so callers don't need a separate sklearn import
    just to report kappa alongside AC1 for comparison. Returns None (not a crash) when either
    rater shows zero variance - matches authority_agreement_metrics.safe_kappa's convention.
    """
    from sklearn.metrics import cohen_kappa_score

    if len(set(rater1) | set(rater2)) < 2:
        return None
    value = float(cohen_kappa_score(list(rater1), list(rater2)))
    return value if math.isfinite(value) else None


def gwet_ac1(
    rater1: Sequence[Any],
    rater2: Sequence[Any],
    categories: Sequence[Any] | None = None,
) -> dict[str, Any]:
    """Gwet's AC1 chance-corrected agreement statistic [GWET2008].

    For n paired judgments across q categories:
        p_a  = observed proportion agreement
        p_k  = (count_rater1==k + count_rater2==k) / (2n), for each category k
        e_gwet = sum_k[ p_k * (1 - p_k) ] / (q - 1)
        AC1  = (p_a - e_gwet) / (1 - e_gwet)

    Unlike Cohen's kappa, e_gwet is NOT the product of each rater's own marginal probability
    for category k (which is what makes kappa's chance-correction blow up when one rater's
    marginal is near-degenerate) - it uses the POOLED marginal from both raters together, which
    is what keeps AC1 well-behaved under high prevalence imbalance. This is Gwet's own stated
    motivation for AC1 in [GWET2008]: kappa can behave paradoxically (near-zero or negative)
    even when raw agreement is high, specifically because of this per-rater-marginal-product
    chance model.

    Returns a dict (not a bare float) so degenerate cases are self-documenting rather than
    silently returning a number that looks fine: {"ac1": float|None, "p_a": float,
    "e_gwet": float, "n": int, "q_categories": int, "undefined_reason": str|None}.
    """
    r1 = list(rater1)
    r2 = list(rater2)
    if len(r1) != len(r2):
        raise ValueError(f"rater1/rater2 length mismatch: {len(r1)} vs {len(r2)}")
    n = len(r1)
    if n == 0:
        return {"ac1": None, "p_a": None, "e_gwet": None, "n": 0, "q_categories": 0,
                "undefined_reason": "no paired judgments"}

    cats = list(categories) if categories is not None else sorted(set(r1) | set(r2), key=str)
    q = len(cats)
    if q < 2:
        return {"ac1": None, "p_a": 1.0, "e_gwet": None, "n": n, "q_categories": q,
                "undefined_reason": "fewer than 2 categories present - agreement is trivial/undefined"}

    p_a = sum(1 for a, b in zip(r1, r2) if a == b) / n

    e_terms = []
    for k in cats:
        n_k1 = sum(1 for a in r1 if a == k)
        n_k2 = sum(1 for b in r2 if b == k)
        p_k = (n_k1 + n_k2) / (2 * n)
        e_terms.append(p_k * (1 - p_k))
    e_gwet = sum(e_terms) / (q - 1)

    if math.isclose(1 - e_gwet, 0.0, abs_tol=1e-12):
        return {"ac1": None, "p_a": round(p_a, 6), "e_gwet": round(e_gwet, 6), "n": n,
                "q_categories": q,
                "undefined_reason": "chance-expected agreement is 1.0 - AC1 denominator is zero"}

    ac1 = (p_a - e_gwet) / (1 - e_gwet)
    return {
        "ac1": round(float(ac1), 6),
        "p_a": round(float(p_a), 6),
        "e_gwet": round(float(e_gwet), 6),
        "n": n,
        "q_categories": q,
        "undefined_reason": None,
    }


def paired_bootstrap_ci(
    condition_a: Sequence[float],
    condition_b: Sequence[float],
    *,
    statistic: Callable[[np.ndarray], float] = np.mean,
    replicates: int = 5000,
    seed: int = 20260816,
    interval_level: float = 0.95,
) -> dict[str, Any]:
    """Percentile bootstrap CI for the paired difference (condition_a - condition_b) of a
    continuous/proportion metric, per section 10's requirement for paired continuous metrics
    (evidence_relevance_precision, faithfulness ratio). Resamples PAIRS (same unit index in both
    conditions), not each condition independently - correct for a paired design, parallel in
    spirit to authority_agreement_metrics.cluster_bootstrap_intervals's KC-cluster resampling for
    the categorical/agreement case.

    statistic defaults to the mean difference; pass np.median for a median-difference CI.
    """
    a = np.asarray(condition_a, dtype=float)
    b = np.asarray(condition_b, dtype=float)
    if a.shape != b.shape:
        raise ValueError(f"condition_a/condition_b shape mismatch: {a.shape} vs {b.shape}")
    n = a.shape[0]
    if n == 0:
        return {"low": None, "high": None, "point_estimate": None, "n_pairs": 0,
                "replicates": replicates, "seed": seed}

    diff = a - b
    point_estimate = float(statistic(diff))

    rng = np.random.default_rng(seed)
    boot_values = np.empty(replicates, dtype=float)
    for i in range(replicates):
        idx = rng.integers(0, n, size=n)
        boot_values[i] = statistic(diff[idx])

    tail = (1 - interval_level) / 2
    low = float(np.quantile(boot_values, tail))
    high = float(np.quantile(boot_values, 1 - tail))
    return {
        "low": round(low, 6),
        "high": round(high, 6),
        "point_estimate": round(point_estimate, 6),
        "n_pairs": n,
        "replicates": replicates,
        "seed": seed,
        "interval_level": interval_level,
        "excludes_zero": not (low <= 0.0 <= high),
    }
