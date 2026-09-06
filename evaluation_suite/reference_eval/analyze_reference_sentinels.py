"""Analyze the reference-based sentinel run.

DEVELOPMENT SENTINEL PERFORMANCE - not a judge qualification pass. Formal qualification happens
only against human-labelled calibration data (paper_methods/LLM_JUDGE_VALIDATION_METHOD.md).

Two design properties matter here:

 1. GOLD AND PREDICTIONS ARE READ FROM SEPARATE FILES. Expected labels come from
    output/reference_sentinel_gold.jsonl, predictions from the raw run output. A gold label can
    therefore be revised (e.g. once SENT_032/SENT_033 are adjudicated) and the aggregates
    recomputed WITHOUT rerunning any model inference.

 2. GOLD_PENDING labels are excluded from agreement but counted and reported. No aggregate is
    ever computed by guessing a disputed label.

Per task it reports call count, structural validity, contract validity, truncation, invalid
output, valid semantic count, agreement, PASS/FAIL precision and recall, false PASS, false FAIL,
and NOT_JUDGEABLE - separately, never merged into one judge score.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
from reference_judge_schema import M2_MATERIALLY_CORRECT, METRIC_SCOPE  # noqa: E402

RAW = BASE / "output" / "selene_penalty_free_raw.json"
GOLD = BASE / "output" / "reference_sentinel_gold.jsonl"
OUT_JSON = BASE / "output" / "penalty_free_sentinel_results.json"
OUT_CSV = BASE / "output" / "penalty_free_sentinel_confusions.csv"

GOLD_PENDING = "GOLD_PENDING"

# task key in raw output -> (gold field, scope registry key)
TASKS = {
    "m1": ("M1_faithfulness", "M1_EVIDENCE_FAITHFULNESS"),
    "m2": ("M2_correctness", "M2_REFERENCE_SOURCE_CORRECTNESS"),
    "m3_holistic": ("M3_core_completeness", "M3_CORE_COMPLETENESS"),
    "m4_coverage": ("M4A_retrieval_reference_coverage", "M4_RETRIEVAL_REFERENCE_COVERAGE"),
    "m4_holistic": ("M4_evidence_adequacy", "EXPLORATORY_HOLISTIC_EVIDENCE_ADEQUACY"),
    "target": ("TARGET_ALIGNMENT", "TARGET_ALIGNMENT"),
}

FAIL_LIKE = {"FAIL", "WRONG_TARGET", "MATERIAL_OMISSION", "MATERIAL_EVIDENCE_GAP"}
PASS_LIKE = {"PASS", "TARGET_ALIGNED", "CORE_COMPLETE", "EVIDENCE_ADEQUATE"}


# ---------------------------------------------------------------------------
# derivations - all in Python, never asked of the model
# ---------------------------------------------------------------------------
def derive_m1(call):
    if not call or not call.get("contract_valid"):
        return None
    labels = [v["label"] for v in call["response"]["verdicts"]]
    return "PASS" if all(l == "SUPPORTED" for l in labels) else "FAIL"


def derive_m2(call):
    if not call or not call.get("contract_valid"):
        return None
    labels = [v["label"] for v in call["response"]["verdicts"]]
    return "PASS" if all(l in M2_MATERIALLY_CORRECT for l in labels) else "FAIL"


def derive_holistic(call):
    if not call or not call.get("contract_valid"):
        return None
    return call["response"]["label"]


def derive_m4a_recall(call):
    """M4A is continuous, not a PASS/FAIL verdict. Returns retrieval_reference_recall."""
    if not call or not call.get("contract_valid"):
        return None
    labels = [v["label"] for v in call["response"]["verdicts"]]
    if not labels:
        return None
    return sum(1 for l in labels if l == "SUPPORTED_BY_RETRIEVAL") / len(labels)


DERIVERS = {"m1": derive_m1, "m2": derive_m2, "m3_holistic": derive_holistic,
            "m4_holistic": derive_holistic, "target": derive_holistic,
            "m4_coverage": derive_m4a_recall}


def call_stats(rows, key):
    calls = [r["calls"].get(key) for r in rows if r["calls"].get(key)]
    n = len(calls)
    if not n:
        return {"n_calls": 0}
    st = Counter(c["status"] for c in calls)
    return {
        "n_calls": n,
        "structural_valid": sum(1 for c in calls if c.get("structural_valid")),
        "structural_validity_rate": sum(1 for c in calls if c.get("structural_valid")) / n,
        "contract_valid": sum(1 for c in calls if c.get("contract_valid")),
        "contract_validity_rate": sum(1 for c in calls if c.get("contract_valid")) / n,
        "truncation_count": st.get("TRUNCATED", 0),
        "invalid_output_count": st.get("STRUCTURAL_INVALID", 0) + st.get("CONTRACT_INVALID", 0),
        "call_failed_count": st.get("CALL_FAILED", 0),
        "retried": sum(1 for c in calls if c.get("retried")),
        "status_counts": dict(st),
    }


def prf(expected, actual, positive, negative):
    """Precision/recall for one class treated as positive."""
    tp = sum(1 for e, a in zip(expected, actual) if e == positive and a == positive)
    fp = sum(1 for e, a in zip(expected, actual) if e == negative and a == positive)
    fn = sum(1 for e, a in zip(expected, actual) if e == positive and a == negative)
    return {
        "precision": tp / (tp + fp) if (tp + fp) else None,
        "recall": tp / (tp + fn) if (tp + fn) else None,
        "tp": tp, "fp": fp, "fn": fn,
    }


def semantic_binary(rows, gold, task_key, gold_field):
    """Categorical PASS/FAIL-style task."""
    pending, applicable, unjudgeable = [], [], []
    pairs = []
    for r in rows:
        sid = r["sentinel_id"]
        exp = gold[sid]["expected"].get(gold_field)
        if exp is None:
            continue
        if exp == GOLD_PENDING:
            pending.append(sid)
            continue
        applicable.append(sid)
        act = DERIVERS[task_key](r["calls"].get(task_key))
        if act is None:
            unjudgeable.append(sid)
            continue
        pairs.append((sid, exp, act))

    exp_l = [e for _, e, _ in pairs]
    act_l = [a for _, _, a in pairs]

    # canonicalize to PASS/FAIL vocabulary for precision/recall
    def canon(x):
        return "PASS" if x in PASS_LIKE else ("FAIL" if x in FAIL_LIKE else x)

    ce, ca = [canon(x) for x in exp_l], [canon(x) for x in act_l]
    n_match = sum(1 for e, a in zip(exp_l, act_l) if e == a)
    false_pass = [s for s, e, a in pairs if canon(e) == "FAIL" and canon(a) == "PASS"]
    false_fail = [s for s, e, a in pairs if canon(e) == "PASS" and canon(a) == "FAIL"]

    return {
        "kind": "binary",
        "n_with_expectation": len(applicable) + len(pending),
        "n_gold_pending": len(pending),
        "gold_pending_ids": pending,
        "n_applicable_resolved_gold": len(applicable),
        "n_unjudgeable_invalid_call": len(unjudgeable),
        "unjudgeable_ids": unjudgeable,
        "n_valid_semantic": len(pairs),
        "agreement_resolved_only": (n_match / len(pairs)) if pairs else None,
        "n_match": n_match,
        "pass_metrics": prf(ce, ca, "PASS", "FAIL"),
        "fail_metrics": prf(ce, ca, "FAIL", "PASS"),
        "n_false_pass": len(false_pass), "false_pass": false_pass,
        "n_false_fail": len(false_fail), "false_fail": false_fail,
        "not_judgeable_predictions": sum(1 for a in act_l if a == "NOT_JUDGEABLE"),
        "confusion_matrix": {f"{e}->{a}": c for (e, a), c in sorted(Counter(zip(exp_l, act_l)).items())},
        "mismatches": [{"sentinel_id": s, "expected": e, "actual": a} for s, e, a in pairs if e != a],
    }


def semantic_continuous(rows, task_key):
    """M4A: continuous retrieval_reference_recall, deliberately NOT thresholded into a verdict."""
    vals = []
    for r in rows:
        v = DERIVERS[task_key](r["calls"].get(task_key))
        if v is not None:
            vals.append((r["sentinel_id"], v))
    xs = [v for _, v in vals]
    xs_sorted = sorted(xs)
    return {
        "kind": "continuous",
        "metric": "retrieval_reference_recall",
        "n_computable": len(xs),
        "mean": (sum(xs) / len(xs)) if xs else None,
        "median": (xs_sorted[len(xs_sorted) // 2] if xs_sorted else None),
        "min": min(xs) if xs else None,
        "max": max(xs) if xs else None,
        "n_at_1.0": sum(1 for x in xs if x == 1.0),
        "n_below_1.0": sum(1 for x in xs if x < 1.0),
        "per_sentinel": {s: round(v, 4) for s, v in vals},
        "interpretation_guard": "This is a continuous coverage diagnostic. A value below 1.0 must "
                                "NOT be read as 'insufficient evidence' - a concise evidence set can "
                                "omit reference detail and still support an adequate draft. Not a "
                                "condition of materially_sound.",
    }


def main() -> int:
    data = json.loads(RAW.read_text(encoding="utf-8"))
    rows = data["results"]
    gold = {json.loads(l)["sentinel_id"]: json.loads(l)
            for l in open(GOLD, encoding="utf-8") if l.strip()}

    report = {
        "run_kind": "DEVELOPMENT SENTINEL RUN - not a judge qualification pass",
        "model": data.get("model"),
        "n_sentinels": len(rows),
        "case_types": dict(Counter(r["case_type"] for r in rows)),
        "gold_source": GOLD.name,
        "predictions_source": RAW.name,
        "note": "Gold and predictions are read from separate files, so a gold revision recomputes "
                "aggregates without rerunning inference.",
        "structural": {},
        "semantic": {},
        "metric_scope": {},
    }

    for task_key, (gold_field, scope_key) in TASKS.items():
        report["structural"][scope_key] = call_stats(rows, task_key)
        report["metric_scope"][scope_key] = METRIC_SCOPE[scope_key]
        if task_key == "m4_coverage":
            report["semantic"][scope_key] = semantic_continuous(rows, task_key)
        else:
            report["semantic"][scope_key] = semantic_binary(rows, gold, task_key, gold_field)

    # decomposition structural checks
    report["decomposition_quality"] = {
        "candidate_problems": sum(len(r["calls"].get("decompose_candidate", {}).get("decomposition_problems", []) or []) for r in rows),
        "reference_problems": sum(len(r["calls"].get("decompose_reference", {}).get("decomposition_problems", []) or []) for r in rows),
        "details": [{"sentinel_id": r["sentinel_id"], "which": w,
                      "problems": r["calls"].get(w, {}).get("decomposition_problems", [])}
                     for r in rows for w in ("decompose_candidate", "decompose_reference")
                     if r["calls"].get(w, {}).get("decomposition_problems")],
    }
    report["claim_counts"] = {
        "candidate_total": sum(len(r["calls"].get("decompose_candidate", {}).get("frozen", {}).get("claims", []) or []) for r in rows),
        "reference_total": sum(len(r["calls"].get("decompose_reference", {}).get("frozen", {}).get("claims", []) or []) for r in rows),
    }

    OUT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    # confusion CSV
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["task", "primary_use", "expected", "actual", "count"])
        for scope_key, sem in report["semantic"].items():
            if sem["kind"] != "binary":
                continue
            for cell, c in sem["confusion_matrix"].items():
                e, a = cell.split("->")
                w.writerow([scope_key, METRIC_SCOPE[scope_key]["primary_use"], e, a, c])

    # ---- console summary ----
    print(f"{report['run_kind']}")
    print(f"model={report['model']}  sentinels={report['n_sentinels']}  {report['case_types']}\n")
    print("--- structural / contract validity ---")
    for k, v in report["structural"].items():
        if v.get("n_calls"):
            print(f"  {k:<42} n={v['n_calls']:<3} struct={v['structural_validity_rate']:.1%} "
                  f"contract={v['contract_validity_rate']:.1%} trunc={v['truncation_count']} "
                  f"invalid={v['invalid_output_count']}")
    print("\n--- semantic ---")
    for k, v in report["semantic"].items():
        primary = "PRIMARY" if METRIC_SCOPE[k]["primary_use"] else "EXPLORATORY"
        if v["kind"] == "continuous":
            print(f"  {k:<42} [{primary}] n={v['n_computable']} "
                  f"mean_recall={v['mean']:.3f} median={v['median']:.3f} "
                  f"at_1.0={v['n_at_1.0']} below_1.0={v['n_below_1.0']}")
            continue
        agr = f"{v['agreement_resolved_only']:.1%}" if v["agreement_resolved_only"] is not None else "n/a"
        fr = v["fail_metrics"]["recall"]
        pr = v["pass_metrics"]["recall"]
        print(f"  {k:<42} [{primary}] n_valid={v['n_valid_semantic']:<3} agree={agr} "
              f"PASS_rec={pr if pr is None else format(pr,'.1%')} FAIL_rec={fr if fr is None else format(fr,'.1%')} "
              f"fPASS={v['n_false_pass']} fFAIL={v['n_false_fail']} pending={v['n_gold_pending']}")
        if v["false_pass"]:
            print(f"       false_pass: {v['false_pass']}")
        if v["n_gold_pending"]:
            print(f"       GOLD_PENDING (excluded from agreement): {v['gold_pending_ids']}")

    dq = report["decomposition_quality"]
    print(f"\ndecomposition structural problems: candidate={dq['candidate_problems']} reference={dq['reference_problems']}")
    print(f"claims: candidate={report['claim_counts']['candidate_total']} reference={report['claim_counts']['reference_total']}")
    print(f"\nwrote {OUT_JSON.name} and {OUT_CSV.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
