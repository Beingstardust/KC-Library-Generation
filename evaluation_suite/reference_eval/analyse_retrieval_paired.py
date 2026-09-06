"""Paired, KC-clustered uncertainty for the retrieval metrics, from the EXISTING pooled judgements.

This adds no experiment. It computes what the aggregate means alone cannot support: paired per-KC
differences with concept-clustered bootstrap intervals, using the same B = 10,000 and the same
KC-as-unit convention as the rest of the campaign.

Deliberately does NOT perform an equivalence test on retrieval. No retrieval equivalence margin was
pre-registered, and inventing one after seeing that P@10 differs by 0.0035 would be exactly the
post-hoc choice the protocol forbids. Descriptive similarity plus an interval is what the design
supports.
"""
from __future__ import annotations

import json
import math
import random
import statistics as st
from collections import defaultdict
from hashlib import sha256
from pathlib import Path

OUT = Path(__file__).parent / "output"
BOOT, SEED = 10000, 20260902
GAIN = {"DEFINITIONAL": 2, "RELATED": 1, "NOT_RELEVANT": 0}
KS = (5, 10, 20)
# one arm per distinct retrieval configuration; the four Proposed-lineage arms share evidence
CONFIGS = {
    "Proposed": "intrinsic_P-Q",
    "DOS-RAG": "extrinsic_DOS-Q",
    "DOS-RAG budget-matched": "sensitivity_DOS-Q_matched",
    "BaseDense": "extrinsic_B-Q",
}


def jl(p):
    return [json.loads(l) for l in open(OUT / p, encoding="utf-8") if l.strip()]


def pid(t):
    return sha256(t.strip().encode("utf-8")).hexdigest()[:16]


def main() -> int:
    qrel = {r["key"]: GAIN[r["grade"]] for r in jl("v3_pooled_relevance.jsonl") if r.get("grade")}
    kc_gains = defaultdict(list)
    for k, g in qrel.items():
        kc_gains[k.split("|")[0]].append(g)
    n_rel = {k: sum(1 for g in v if g > 0) for k, v in kc_gains.items()}

    rows = jl("ablation_rows.jsonl")
    by_arm = {}
    for r in rows:
        by_arm.setdefault(r["arm"], {})[r["unit_id"]] = r

    # per-KC metric values for each retrieval configuration
    per = {name: defaultdict(dict) for name in CONFIGS}
    for name, arm in CONFIGS.items():
        for kc, r in by_arm[arm].items():
            if n_rel.get(kc, 0) == 0:
                continue
            ev = r.get("candidate_system_evidence") or []
            gains = [qrel.get(f"{kc}|{pid(e['text'])}") for e in ev]
            gains = [g for g in gains if g is not None]
            if not gains:
                continue
            ideal = sorted(kc_gains[kc], reverse=True)
            for k in KS:
                top = gains[:k]
                nrel = sum(1 for g in top if g > 0)
                per[name][f"P@{k}"][kc] = nrel / k
                per[name][f"R@{k}"][kc] = nrel / n_rel[kc]
                dcg = sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(top))
                idcg = sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(ideal[:k]))
                per[name][f"nDCG@{k}"][kc] = dcg / idcg if idcg else 0.0

    rng = random.Random(SEED)

    def paired(a, b, metric):
        ka, kb = per[a][metric], per[b][metric]
        ks = sorted(set(ka) & set(kb))
        if len(ks) < 10:
            return None
        d = [ka[k] - kb[k] for k in ks]
        boot = sorted(st.mean([d[rng.randrange(len(d))] for _ in range(len(d))])
                      for _ in range(BOOT))
        lo, hi = boot[int(.025 * BOOT)], boot[int(.975 * BOOT) - 1]
        return {"n_kcs": len(ks), "mean_a": round(st.mean(ka[k] for k in ks), 4),
                "mean_b": round(st.mean(kb[k] for k in ks), 4),
                "paired_diff": round(st.mean(d), 4), "ci95": [round(lo, 4), round(hi, 4)],
                "excludes_zero": (lo > 0 and hi > 0) or (lo < 0 and hi < 0)}

    metrics = [f"{m}@{k}" for k in KS for m in ("P", "R", "nDCG")]
    report = {"bootstrap": BOOT, "seed": SEED, "unit": "knowledge component",
              "note": ("Descriptive difference with paired uncertainty. No equivalence test is "
                       "reported: no retrieval equivalence margin was pre-registered, and choosing "
                       "one after seeing the differences would be post hoc."),
              "comparisons": {}}

    print("PAIRED RETRIEVAL DIFFERENCES, concept-clustered bootstrap (B=10,000)")
    print("Positive favours the first-named configuration.\n")
    for a, b in (("Proposed", "DOS-RAG"), ("Proposed", "BaseDense"),
                 ("DOS-RAG", "BaseDense"), ("DOS-RAG", "DOS-RAG budget-matched")):
        print(f"=== {a} vs {b} ===")
        print(f"{'metric':<10}{'A':>9}{'B':>9}{'paired d':>11}{'95% CI':>22}{'excl. 0':>9}")
        for m in metrics:
            r = paired(a, b, m)
            if not r:
                continue
            report["comparisons"].setdefault(f"{a} vs {b}", {})[m] = r
            print(f"{m:<10}{r['mean_a']:>9.4f}{r['mean_b']:>9.4f}{r['paired_diff']:>+11.4f}"
                  f"   [{r['ci95'][0]:>+7.4f},{r['ci95'][1]:>+7.4f}]{str(r['excludes_zero']):>9}")
        print()

    (OUT / "retrieval_paired_ci.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {OUT / 'retrieval_paired_ci.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
