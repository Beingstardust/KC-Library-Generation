"""Test condition C2 of COMPARATIVE_USE_PROTOCOL.md: is judge-vs-human disagreement
arm-dependent?

This decides whether the judge may be used for ABLATION RANKING despite failing absolute
qualification. The logic: a judge with a constant threshold offset still ranks arms correctly,
because every arm drafts the same KCs and a constant offset cancels in a paired comparison. What
would break ranking is arm-DEPENDENT behaviour - the judge treating one system's drafts
differently. That is what this script tests.

Written and committed BEFORE being run (see the protocol's pre-registration note). Thresholds come
from the protocol and are not tunable here.

Refuses to run if inputs are missing. Reports per-arm rates, signed bias, exact tests, and LOW_POWER
flags unconditionally - a non-significant result at n~5-6 per arm is weak evidence, and is labelled
as such rather than presented as proof of arm-independence.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent
OUT_DIR = BASE / "output" / "qualification"

# schema-key -> gold field name, mirroring run_judge_qualification.py
TASKS = {
    "M1_EVIDENCE_FAITHFULNESS": "M1_faithfulness_per_claim",
    "M2_REFERENCE_SOURCE_CORRECTNESS": "M2_correctness_per_claim",
    "M3_CORE_COMPLETENESS": "M3_core_completeness",
    "TARGET_ALIGNMENT": "TARGET_ALIGNMENT",
    "M4A_RETRIEVAL_CLAIM_SUPPORT": "M4A_retrieval_claim_support",
}

# Which label counts as the "negative"/flagged class, for signed-bias reporting.
NEGATIVE = {
    "M1_EVIDENCE_FAITHFULNESS": "FAIL",
    "M2_REFERENCE_SOURCE_CORRECTNESS": "FAIL",
    "M3_CORE_COMPLETENESS": "MATERIAL_OMISSION",
    "TARGET_ALIGNMENT": "WRONG_TARGET",
    "M4A_RETRIEVAL_CLAIM_SUPPORT": "UNSUPPORTED",
}

ALPHA = 0.05          # protocol C2
MIN_ROWS_PER_ARM = 10  # below this -> LOW_POWER flag


def wilson(k: int, n: int):
    if n == 0:
        return [None, None]
    z = 1.959963984540054
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def _logfact_table(n: int):
    t = [0.0] * (n + 1)
    for i in range(2, n + 1):
        t[i] = t[i - 1] + math.log(i)
    return t


def freeman_halton_p(table):
    """Exact Fisher-Freeman-Halton p for an R x 2 table by full enumeration of the first column.

    Rows are arms, columns are [disagree, agree]. Conditions on both margins and sums the
    probability of every table at most as probable as the observed one. Exact, no chi-square
    approximation - appropriate at the small per-arm counts here.
    """
    rows = [(a + b) for a, b in table]
    col0 = sum(a for a, _ in table)
    total = sum(rows)
    if total == 0 or col0 == 0 or col0 == total:
        return 1.0, "degenerate (a margin is zero)"
    lf = _logfact_table(total)

    def logp(cells):
        # multivariate hypergeometric probability of the R x 2 table given fixed margins
        s = sum(lf[r] for r in rows) + lf[col0] + lf[total - col0] - lf[total]
        for (a, _), r in zip(cells, rows):
            s -= lf[a] + lf[r - a]
        return s

    observed = logp(table)
    tol = 1e-9
    total_p = 0.0

    def rec(i, remaining, acc):
        nonlocal total_p
        if i == len(rows):
            if remaining == 0:
                lp = logp(acc)
                if lp <= observed + tol:
                    total_p += math.exp(lp)
            return
        lo = max(0, remaining - sum(rows[i + 1:]))
        hi = min(rows[i], remaining)
        for a in range(lo, hi + 1):
            rec(i + 1, remaining - a, acc + [(a, rows[i] - a)])

    rec(0, col0, [])
    return min(1.0, total_p), None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--annotations", type=Path, required=True)
    ap.add_argument("--predictions", type=Path, required=True)
    ap.add_argument("--mapping", type=Path, required=True,
                    help="reference_human_calibration_blinded_mapping.jsonl (arm identity)")
    ap.add_argument("--out", type=Path, default=OUT_DIR / "comparative_qualification.json")
    args = ap.parse_args()

    for p in (args.annotations, args.predictions, args.mapping):
        if not p.exists():
            print(f"REFUSED: missing input {p}")
            return 1

    ann = [json.loads(l) for l in open(args.annotations, encoding="utf-8") if l.strip()]
    if not ann:
        print("REFUSED: annotation file is empty")
        return 1
    preds_raw = json.loads(args.predictions.read_text(encoding="utf-8"))
    P = {r["review_case_id"]: r for r in preds_raw.get("results", preds_raw)}
    arm_of = {}
    for l in open(args.mapping, encoding="utf-8"):
        if l.strip():
            m = json.loads(l)
            arm_of[m["review_case_id"]] = m["arm_true_identity"]

    report = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "protocol": "COMPARATIVE_USE_PROTOCOL.md",
        "condition_tested": "C2 - no detectable arm-dependent disagreement",
        "alpha": ALPHA,
        "note": ("Absolute qualification (JUDGE_QUALIFIED=false) is NOT revisited here. This tests "
                 "only whether judge-vs-human disagreement depends on which arm produced the draft."),
        "tasks": {},
    }

    for task, field in TASKS.items():
        neg = NEGATIVE[task]
        per_arm = defaultdict(lambda: {"n": 0, "disagree": 0, "false_neg": 0, "false_pos": 0})
        for a in ann:
            cid = a["review_case_id"]
            h = a.get(field)
            j = (P.get(cid) or {}).get(field)
            if h in (None, "") or j in (None, ""):
                continue
            arm = arm_of.get(cid, "UNKNOWN")
            d = per_arm[arm]
            d["n"] += 1
            if h != j:
                d["disagree"] += 1
                # false_pos = judge flagged (negative) when human did not
                if j == neg and h != neg:
                    d["false_pos"] += 1
                elif h == neg and j != neg:
                    d["false_neg"] += 1

        arms = sorted(per_arm)
        if not arms or sum(per_arm[a]["n"] for a in arms) == 0:
            report["tasks"][task] = {
                "decision": "INSUFFICIENT_COMPARATIVE_SUPPORT",
                "reason": "no comparable labels for this task",
                "n": 0,
            }
            continue

        table = [(per_arm[a]["disagree"], per_arm[a]["n"] - per_arm[a]["disagree"]) for a in arms]
        p_value, degenerate = freeman_halton_p(table)

        by_arm = {}
        for a in arms:
            d = per_arm[a]
            by_arm[a] = {
                "n": d["n"],
                "disagree": d["disagree"],
                "disagree_rate": round(d["disagree"] / d["n"], 4) if d["n"] else None,
                "wilson_disagree_rate": wilson(d["disagree"], d["n"]),
                "judge_over_flags": d["false_pos"],
                "judge_under_flags": d["false_neg"],
                "signed_bias_over_minus_under": d["false_pos"] - d["false_neg"],
            }

        flags = []
        thin = [a for a in arms if per_arm[a]["n"] < MIN_ROWS_PER_ARM]
        if thin:
            flags.append(f"LOW_POWER: arms with <{MIN_ROWS_PER_ARM} labelled rows: {thin}")
        if degenerate:
            flags.append(f"DEGENERATE_TABLE: {degenerate}")

        arm_dependent = (p_value < ALPHA)
        decision = "NOT_COMPARATIVE_QUALIFIED" if arm_dependent else "COMPARATIVE_QUALIFIED"

        report["tasks"][task] = {
            "n": sum(per_arm[a]["n"] for a in arms),
            "by_arm": by_arm,
            "exact_test": "Fisher-Freeman-Halton, arm x {disagree, agree}",
            "p_value": round(p_value, 6),
            "alpha": ALPHA,
            "arm_dependent_detected": arm_dependent,
            "flags": flags,
            "decision": decision,
            "interpretation": (
                "Arm-dependent disagreement detected: the judge does not treat arms alike, so paired "
                "ranking is not licensed for this task."
                if arm_dependent else
                "No arm-dependent disagreement detected. NOTE: with these per-arm counts the test has "
                "low power, so this is weak evidence of arm-independence, not proof of it."
            ),
        }

    decisions = {t: v["decision"] for t, v in report["tasks"].items()}
    report["decisions"] = decisions
    report["COMPARATIVE_USE_LICENSED_FOR"] = [t for t, d in decisions.items()
                                              if d == "COMPARATIVE_QUALIFIED"]
    report["standing_absolute_result"] = "JUDGE_QUALIFIED=false (unchanged, see qualification_decision.json)"

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(decisions, indent=2))
    print()
    for t, v in report["tasks"].items():
        if "by_arm" not in v:
            print(f"{t}: {v['decision']} ({v.get('reason','')})")
            continue
        print(f"=== {t}  n={v['n']}  p={v['p_value']}  -> {v['decision']}")
        for a, d in sorted(v["by_arm"].items()):
            print(f"    {a:<20} n={d['n']:<3} disagree={d['disagree']:<3} "
                  f"rate={d['disagree_rate']:<7} signed_bias={d['signed_bias_over_minus_under']:+d}")
        for f in v["flags"]:
            print(f"    [flag] {f}")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
