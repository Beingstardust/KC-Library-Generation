"""Compute human-human agreement, Selene-human qualification, and the seed-bias audit against the
FROZEN qualification protocol.

REFUSES TO RUN without real human labels. It never invents, imputes, or defaults a label - an
absent annotation is absent, and a qualification decision computed from fabricated labels would be
worse than no decision at all.

Order enforced (protocol anti-contamination clauses):
  1. human-human agreement FIRST, before any judge comparison
  2. human gold frozen (agreement -> use it; disagreement -> adjudicated label required)
  3. judge predictions loaded and hashed
  4. only then, judge-human agreement
  5. arm identities restored only for the post-hoc bias audit

Usage:
  python run_judge_qualification.py --annotations <a.jsonl> [--annotations-b <b.jsonl>]
                                    --predictions <selene_calibration_predictions.json>
                                    [--adjudications <adj.jsonl>]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE.parent))
from statistics import cohens_kappa, gwet_ac1, wilson_interval  # noqa: E402

CAL = BASE / "output" / "human_calibration"
MAP = CAL / "reference_human_calibration_blinded_mapping.jsonl"
PROTOCOL = BASE / "locks" / "JUDGE_QUALIFICATION_PROTOCOL_FROZEN.json"
OUT = BASE / "output" / "qualification"

PASS_LIKE = {"PASS", "TARGET_ALIGNED", "CORE_COMPLETE", "SUPPORTED_BY_RETRIEVAL", "SUPPORTED"}
FAIL_LIKE = {"FAIL", "WRONG_TARGET", "MATERIAL_OMISSION", "NOT_SUPPORTED_BY_RETRIEVAL"}

TASKS = {
    "M1_EVIDENCE_FAITHFULNESS": "M1_faithfulness_per_claim",
    "M2_REFERENCE_SOURCE_CORRECTNESS": "M2_correctness_per_claim",
    "M3_CORE_COMPLETENESS": "M3_core_completeness",
    "TARGET_ALIGNMENT": "TARGET_ALIGNMENT",
    "M4A_RETRIEVAL_CLAIM_SUPPORT": "M4A_retrieval_claim_support",
}
MIN_CLASS = 10


def sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def canon(x):
    if x in PASS_LIKE:
        return "PASS"
    if x in FAIL_LIKE:
        return "FAIL"
    return x


def load_jsonl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def prf(exp, act, pos, neg):
    tp = sum(1 for e, a in zip(exp, act) if e == pos and a == pos)
    fp = sum(1 for e, a in zip(exp, act) if e == neg and a == pos)
    fn = sum(1 for e, a in zip(exp, act) if e == pos and a == neg)
    return {"precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None, "tp": tp, "fp": fp, "fn": fn}


def agreement_block(a_labels, b_labels):
    pairs = [(x, y) for x, y in zip(a_labels, b_labels) if x is not None and y is not None]
    if not pairs:
        return {"n": 0, "note": "no overlapping labels"}
    xa = [canon(x) for x, _ in pairs]
    xb = [canon(y) for _, y in pairs]
    raw = sum(1 for x, y in zip(xa, xb) if x == y) / len(pairs)
    return {
        "n": len(pairs),
        "class_distribution_a": dict(Counter(xa)),
        "class_distribution_b": dict(Counter(xb)),
        "raw_agreement": raw,
        "gwet_ac1": gwet_ac1(xa, xb),
        "cohens_kappa_SECONDARY_ONLY": cohens_kappa(xa, xb),
        "confusion_matrix": {f"{x}|{y}": c for (x, y), c in sorted(Counter(zip(xa, xb)).items())},
    }


def evaluate_task(task, human, judge, thresholds):
    """human/judge are aligned label lists (already canonicalised upstream)."""
    pairs = [(h, j) for h, j in zip(human, judge) if h is not None and j is not None]
    n = len(pairs)
    if n == 0:
        return {"decision": "INSUFFICIENT_VALIDATION_SUPPORT", "reason": "no comparable labels", "n": 0}

    he = [canon(h) for h, _ in pairs]
    ja = [canon(j) for _, j in pairs]
    n_pass, n_fail = he.count("PASS"), he.count("FAIL")
    raw = sum(1 for h, j in zip(he, ja) if h == j) / n
    ac1 = gwet_ac1(he, ja)
    pm, fm = prf(he, ja, "PASS", "FAIL"), prf(he, ja, "FAIL", "PASS")
    false_pass = sum(1 for h, j in zip(he, ja) if h == "FAIL" and j == "PASS")
    false_fail = sum(1 for h, j in zip(he, ja) if h == "PASS" and j == "FAIL")
    fp_rate = false_pass / n_fail if n_fail else None
    ff_rate = false_fail / n_pass if n_pass else None

    res = {
        "n": n, "human_pass_n": n_pass, "human_fail_n": n_fail,
        "raw_agreement": raw,
        "gwet_ac1": ac1,
        "cohens_kappa_SECONDARY_ONLY": cohens_kappa(he, ja),
        "pass_precision": pm["precision"], "pass_recall": pm["recall"],
        "fail_precision": fm["precision"], "fail_recall": fm["recall"],
        "false_pass_count": false_pass, "false_pass_rate": fp_rate,
        "false_fail_count": false_fail, "false_fail_rate": ff_rate,
        "confusion_matrix": {f"{h}->{j}": c for (h, j), c in sorted(Counter(zip(he, ja)).items())},
        "wilson_pass_recall": list(wilson_interval(pm["tp"], pm["tp"] + pm["fn"])) if (pm["tp"] + pm["fn"]) else None,
        "wilson_fail_recall": list(wilson_interval(fm["tp"], fm["tp"] + fm["fn"])) if (fm["tp"] + fm["fn"]) else None,
        "thresholds": thresholds,
    }

    flags = []
    if n_pass < MIN_CLASS:
        flags.append(f"SMALL_DENOMINATOR: human PASS n={n_pass} (<{MIN_CLASS})")
    if n_fail < MIN_CLASS:
        flags.append(f"SMALL_DENOMINATOR: human FAIL n={n_fail} (<{MIN_CLASS})")
    res["flags"] = flags

    # gate evaluation - every required threshold must be present AND met
    checks, unmet = {}, []
    ac1v = ac1.get("ac1") if isinstance(ac1, dict) else ac1
    mapping = {
        "raw_agreement_min": ("raw_agreement", raw),
        "gwet_ac1_min": ("gwet_ac1", ac1v),
        "fail_recall_min": ("fail_recall", fm["recall"]),
        "pass_recall_min": ("pass_recall", pm["recall"]),
        "supported_recall_min": ("pass_recall", pm["recall"]),
        "not_supported_recall_min": ("fail_recall", fm["recall"]),
    }
    for key, threshold in (thresholds or {}).items():
        if key == "false_pass_rate_max":
            checks[key] = {"observed": fp_rate, "threshold": threshold,
                           "met": (fp_rate is not None and fp_rate <= threshold)}
        elif key in mapping:
            name, val = mapping[key]
            checks[key] = {"observed": val, "threshold": threshold,
                           "met": (val is not None and val >= threshold)}
        else:
            continue
        if not checks[key]["met"]:
            unmet.append(key)
    res["gate_checks"] = checks

    # a gate that cannot be tested is not a pass
    untestable = [k for k, v in checks.items() if v["observed"] is None]
    if untestable or (flags and any("SMALL_DENOMINATOR" in f for f in flags) and unmet):
        res["decision"] = "INSUFFICIENT_VALIDATION_SUPPORT"
        res["reason"] = (f"untestable gates {untestable}; " if untestable else "") + \
                        (f"small denominators with unmet gates {unmet}" if unmet else "")
    elif unmet:
        res["decision"] = "NOT_QUALIFIED"
        res["reason"] = f"unmet gates: {unmet}"
    else:
        res["decision"] = "QUALIFIED"
        res["reason"] = "all frozen thresholds met"
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--annotations", required=True, type=Path, help="annotator A labels (jsonl)")
    ap.add_argument("--annotations-b", type=Path, default=None, help="annotator B labels (jsonl)")
    ap.add_argument("--adjudications", type=Path, default=None)
    ap.add_argument("--predictions", required=True, type=Path, help="frozen Selene calibration predictions")
    args = ap.parse_args()

    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    gates = protocol["task_gates"]

    for p in (args.annotations, args.predictions):
        if not p.exists():
            print(f"REFUSED: {p} does not exist. Qualification cannot be computed without real "
                  f"human labels and real judge predictions. No label is ever imputed.")
            return 1

    A = {r["review_case_id"]: r for r in load_jsonl(args.annotations)}
    B = {r["review_case_id"]: r for r in load_jsonl(args.annotations_b)} if args.annotations_b else {}
    ADJ = {r["review_case_id"]: r for r in load_jsonl(args.adjudications)} if args.adjudications else {}
    preds = json.loads(args.predictions.read_text(encoding="utf-8"))
    P = {r["review_case_id"]: r for r in preds.get("results", preds)}
    mapping = {r["review_case_id"]: r for r in load_jsonl(MAP)}

    # refuse on an empty annotation set rather than reporting a vacuous pass
    total_labels = sum(1 for r in A.values() for t in TASKS.values() if r.get(t) not in (None, "", []))
    if total_labels == 0:
        print("REFUSED: the annotation file contains zero labels across all primary tasks.")
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    report = {
        "protocol_sha256": protocol["protocol_sha256"],
        "annotations_sha256": sha(args.annotations),
        "annotations_b_sha256": sha(args.annotations_b) if args.annotations_b else None,
        "predictions_sha256": sha(args.predictions),
        "n_rows_annotated": len(A),
        "human_human": {},
        "qualification": {},
    }

    # ---- 1. human-human FIRST ----
    if B:
        for task, field in TASKS.items():
            ids = [i for i in A if i in B]
            report["human_human"][task] = agreement_block(
                [A[i].get(field) for i in ids], [B[i].get(field) for i in ids])

    # ---- 2. freeze human gold ----
    gold = {}
    unresolved = []
    for task, field in TASKS.items():
        gold[task] = {}
        for cid in A:
            a = A[cid].get(field)
            b = B.get(cid, {}).get(field) if B else None
            if b is None or a == b:
                gold[task][cid] = a
            elif cid in ADJ and ADJ[cid].get(field) is not None:
                gold[task][cid] = ADJ[cid][field]
            else:
                unresolved.append((task, cid))
    if unresolved:
        print(f"REFUSED: {len(unresolved)} annotator disagreements are unadjudicated. "
              f"Protocol requires adjudication BEFORE judge qualification. e.g. {unresolved[:5]}")
        return 1

    # ---- 3/4. judge comparison ----
    for task, field in TASKS.items():
        ids = [i for i in gold[task] if i in P]
        human = [gold[task][i] for i in ids]
        judge = [P[i].get(field) for i in ids]
        report["qualification"][task] = evaluate_task(task, human, judge, gates.get(task, {}))

    required = ["M1_EVIDENCE_FAITHFULNESS", "M2_REFERENCE_SOURCE_CORRECTNESS",
                "M3_CORE_COMPLETENESS", "TARGET_ALIGNMENT"]
    decisions = {t: report["qualification"][t]["decision"] for t in report["qualification"]}
    overall = all(decisions.get(t) == "QUALIFIED" for t in required)
    report["decisions"] = decisions
    report["JUDGE_QUALIFIED"] = overall
    report["decision_note"] = (
        "Criterion-wise. No averaging across tasks. M4A failing alone does NOT invalidate "
        "M1/M2/M3/TARGET - it means automated retrieval-reference recall is unvalidated."
    )

    # ---- 5. seed-bias / differential audit (arm identity restored ONLY here) ----
    by_arm = defaultdict(lambda: defaultdict(Counter))
    for task, field in TASKS.items():
        for cid in gold[task]:
            if cid not in P or cid not in mapping:
                continue
            arm = mapping[cid]["arm_true_identity"]
            h, j = canon(gold[task][cid]), canon(P[cid].get(field))
            if h is None or j is None:
                continue
            by_arm[task][arm]["n"] += 1
            if h != j:
                by_arm[task][arm]["disagree"] += 1
            if h == "FAIL" and j == "PASS":
                by_arm[task][arm]["false_pass"] += 1
            if h == "PASS" and j == "FAIL":
                by_arm[task][arm]["false_fail"] += 1
    audit_flags = defaultdict(Counter)
    for cid, r in A.items():
        arm = mapping.get(cid, {}).get("arm_true_identity", "?")
        for f in ("VALID_SOURCE_SUPPORTED_ALTERNATIVE_BEYOND_REFERENCE", "POSSIBLE_REFERENCE_DEFECT"):
            if r.get(f) is not None:
                audit_flags[arm][f"{f}={r[f]}"] += 1
    report["seed_bias_audit"] = {
        "by_arm": {t: {a: dict(c) for a, c in d.items()} for t, d in by_arm.items()},
        "audit_flags_by_arm": {a: dict(c) for a, c in audit_flags.items()},
        "interpretation_guard": "Absence of bias may NOT be inferred from a nonsignificant "
                                 "difference. This is a disclosed threat-to-validity diagnostic.",
    }

    (OUT / "qualification_decision.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    with open(OUT / "judge_human_metrics.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["task", "n", "human_pass_n", "human_fail_n", "raw_agreement", "gwet_ac1",
                    "pass_precision", "pass_recall", "fail_precision", "fail_recall",
                    "false_pass_n", "false_pass_rate", "false_fail_n", "false_fail_rate",
                    "flags", "decision"])
        for t, r in report["qualification"].items():
            if r.get("n"):
                ac1 = r["gwet_ac1"].get("ac1") if isinstance(r["gwet_ac1"], dict) else r["gwet_ac1"]
                w.writerow([t, r["n"], r["human_pass_n"], r["human_fail_n"], r["raw_agreement"], ac1,
                            r["pass_precision"], r["pass_recall"], r["fail_precision"], r["fail_recall"],
                            r["false_pass_count"], r["false_pass_rate"], r["false_fail_count"],
                            r["false_fail_rate"], "; ".join(r["flags"]), r["decision"]])

    with open(OUT / "judge_human_confusions.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["task", "human", "judge", "count"])
        for t, r in report["qualification"].items():
            for cell, c in (r.get("confusion_matrix") or {}).items():
                h, j = cell.split("->")
                w.writerow([t, h, j, c])

    print(json.dumps(decisions, indent=2))
    print(f"\nJUDGE_QUALIFIED = {overall}")
    print(f"wrote {OUT}/qualification_decision.json, judge_human_metrics.csv, judge_human_confusions.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
