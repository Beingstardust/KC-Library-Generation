"""Metrics for human/automated-judge calibration on the later claim-level evaluation task.
Reuses the already-validated agreement statistics from evaluation_suite/final_pipeline/statistics.py
(gwet_ac1, cohens_kappa) rather than reimplementing them; adds only the confusion-matrix /
false-PASS / false-FAIL / failure-recall helpers that module doesn't already have - the same
shape of computation used throughout the Selene/RootSignals development-stage qualification
(evaluation_suite/final_pipeline/output/r9_final/analyze_v3_results.py), generalized here so
the later human-calibration and judge-requalification passes don't reimplement it a third time.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).parent.parent.parent))  # -> evaluation_suite/final_pipeline/
from statistics import cohens_kappa, gwet_ac1  # noqa: E402


def confusion_matrix(expected: Sequence[str], actual: Sequence[str]) -> dict[str, int]:
    if len(expected) != len(actual):
        raise ValueError("expected and actual must be the same length")
    counts = Counter(zip(expected, actual))
    return {f"{e}->{a}": c for (e, a), c in sorted(counts.items())}


def raw_agreement(expected: Sequence[str], actual: Sequence[str]) -> float | None:
    if not expected:
        return None
    return sum(1 for e, a in zip(expected, actual) if e == a) / len(expected)


def failure_recall(expected: Sequence[str], actual: Sequence[str], fail_label: str = "FAIL") -> dict:
    """Of the cases the reference/human says should FAIL, how many did the judge under test also FAIL."""
    pairs = list(zip(expected, actual))
    expected_fail = [(e, a) for e, a in pairs if e == fail_label]
    if not expected_fail:
        return {"recall": None, "n_expected_fail": 0, "n_caught": 0}
    caught = sum(1 for e, a in expected_fail if a == fail_label)
    return {"recall": caught / len(expected_fail), "n_expected_fail": len(expected_fail), "n_caught": caught}


def false_pass_rate(expected: Sequence[str], actual: Sequence[str], pass_label: str = "PASS", fail_label: str = "FAIL") -> dict:
    """Of the cases that should FAIL, how many did the judge wrongly PASS - the safety-critical direction."""
    pairs = list(zip(expected, actual))
    expected_fail = [(e, a) for e, a in pairs if e == fail_label]
    if not expected_fail:
        return {"rate": None, "n": 0, "ids": []}
    false_passes = [i for i, (e, a) in enumerate(expected_fail) if a == pass_label]
    return {"rate": len(false_passes) / len(expected_fail), "n": len(false_passes)}


def false_fail_rate(expected: Sequence[str], actual: Sequence[str], pass_label: str = "PASS", fail_label: str = "FAIL") -> dict:
    """Of the cases that should PASS, how many did the judge wrongly FAIL - the over-strictness direction
    that the Selene/RootSignals v3 F4/F5 development runs showed can dominate agreement loss even when
    false-PASS is driven to zero (see source_artifact_manifest.json v3_architecture_2026-08-24)."""
    pairs = list(zip(expected, actual))
    expected_pass = [(e, a) for e, a in pairs if e == pass_label]
    if not expected_pass:
        return {"rate": None, "n": 0}
    false_fails = [i for i, (e, a) in enumerate(expected_pass) if a == fail_label]
    return {"rate": len(false_fails) / len(expected_pass), "n": len(false_fails)}


def full_report(expected: Sequence[str], actual: Sequence[str]) -> dict:
    return {
        "n": len(expected),
        "raw_agreement": raw_agreement(expected, actual),
        "cohens_kappa": cohens_kappa(expected, actual),
        "gwet_ac1": gwet_ac1(expected, actual),
        "confusion_matrix": confusion_matrix(expected, actual),
        "failure_recall": failure_recall(expected, actual),
        "false_pass_rate": false_pass_rate(expected, actual),
        "false_fail_rate": false_fail_rate(expected, actual),
    }


if __name__ == "__main__":
    expected = ["PASS"] * 9 + ["FAIL"]
    actual = ["PASS"] * 9 + ["PASS"]  # one missed FAIL -> false pass
    report = full_report(expected, actual)
    assert report["n"] == 10
    assert report["failure_recall"]["recall"] == 0.0
    assert report["false_pass_rate"]["n"] == 1
    assert report["false_fail_rate"]["n"] == 0
    assert report["confusion_matrix"] == {"FAIL->PASS": 1, "PASS->PASS": 9}
    print("OK - derived_metrics self-test passed on synthetic fixture")
    print(report)
