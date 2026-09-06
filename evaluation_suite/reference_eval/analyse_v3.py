"""v3 analysis: IR metrics for the extrinsic claim, TOST + variance components for the agnosticism claims.

Three separate questions, three appropriate statistical forms:

  extrinsic  -> a RANKING claim. Standard pooled-test-collection IR metrics (Recall@k, Precision@k,
                nDCG@k). Each pooled passage was judged individually, so the serial-position failure
                that made context recall uninterpretable (F-45) cannot arise here.
  intrinsic  -> an EQUIVALENCE claim (model-agnostic). TOST against a pre-registered margin, plus a
                variance decomposition. A non-significant difference test is NOT evidence of
                equivalence, which is the error v2 made.
  domain     -> an EQUIVALENCE claim (domain-agnostic), same machinery, now testable because all
                nine drafter x domain cells exist.

The variance decomposition is the number the paper actually wants: what share of quality variance is
attributable to the drafter versus the knowledge component itself.
"""
from __future__ import annotations

import json
import math
import random
import statistics as st
from collections import defaultdict
from hashlib import sha256
from pathlib import Path

BASE = Path(__file__).parent
OUT = BASE / "output"
BOOT, SEED = 10000, 20260901
DELTA = 0.05                      # pre-registered equivalence margin
DELTA_SENS = (0.03, 0.10)         # sensitivity
GAIN = {"DEFINITIONAL": 2, "RELATED": 1, "NOT_RELEVANT": 0}
KS = (5, 10, 20)


def jl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def pid(t):
    return sha256(t.strip().encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- IR metrics
def ir_metrics():
    rows = jl(OUT / "ablation_rows.jsonl")
    qrel = {}
    for r in jl(OUT / "v3_pooled_relevance.jsonl"):
        if r.get("grade"):
            qrel[r["key"]] = GAIN[r["grade"]]

    rel_per_kc = defaultdict(int)      # count of relevant (grade>0) in the pool, per KC
    for k, g in qrel.items():
        if g > 0:
            rel_per_kc[k.split("|")[0]] += 1

    res = defaultdict(lambda: defaultdict(list))
    for r in rows:
        kc, arm = r["unit_id"], r["arm"]
        ev = r.get("candidate_system_evidence") or []
        if not ev or rel_per_kc.get(kc, 0) == 0:
            continue
        gains = [qrel.get(f"{kc}|{pid(e['text'])}") for e in ev]
        gains = [g for g in gains if g is not None]   # only judged passages count
        if not gains:
            continue
        for k in KS:
            top = gains[:k]
            nrel = sum(1 for g in top if g > 0)
            res[arm][f"P@{k}"].append(nrel / k)
            res[arm][f"R@{k}"].append(nrel / rel_per_kc[kc])
            dcg = sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(top))
            ideal = sorted([g for g in qrel_kc_gains(qrel, kc)], reverse=True)[:k]
            idcg = sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(ideal))
            res[arm][f"nDCG@{k}"].append(dcg / idcg if idcg else 0.0)
    return {a: {m: round(st.mean(v), 4) for m, v in d.items()} for a, d in res.items()}


def qrel_kc_gains(qrel, kc):
    return [g for k, g in qrel.items() if k.startswith(kc + "|")]


# ---------------------------------------------------------------- equivalence
def tost(diffs, delta, rng):
    """Bootstrap TOST: equivalence declared if the 90% CI lies entirely inside +/- delta."""
    boot = sorted(st.mean([diffs[rng.randrange(len(diffs))] for _ in range(len(diffs))])
                  for _ in range(BOOT))
    lo, hi = boot[int(.05 * BOOT)], boot[int(.95 * BOOT) - 1]      # 90% CI for TOST
    return {"mean_diff": round(st.mean(diffs), 4), "ci90": [round(lo, 4), round(hi, 4)],
            "equivalent": (lo > -delta and hi < delta), "n": len(diffs)}


# ---------------------------------------------------------------- variance components
def variance_components(scores, facet_names=("kc", "drafter")):
    """Two-way crossed random-effects decomposition, one observation per cell.

    scores: {(kc, drafter): value}. Returns variance attributable to each facet plus residual.
    With one observation per cell the drafter x KC interaction is confounded with error, which is
    stated rather than hidden - it is the standard limitation of a single-observation design.
    """
    kcs = sorted({k for k, _ in scores})
    ds = sorted({d for _, d in scores})
    full = [(k, d) for k in kcs for d in ds if (k, d) in scores]
    if len(full) < len(kcs) * len(ds):          # keep it fully crossed
        kcs = [k for k in kcs if all((k, d) in scores for d in ds)]
    if len(kcs) < 3 or len(ds) < 2:
        return None
    grand = st.mean(scores[(k, d)] for k in kcs for d in ds)
    nk, nd = len(kcs), len(ds)
    mk = {k: st.mean(scores[(k, d)] for d in ds) for k in kcs}
    md = {d: st.mean(scores[(k, d)] for k in kcs) for d in ds}
    ss_k = nd * sum((mk[k] - grand) ** 2 for k in kcs)
    ss_d = nk * sum((md[d] - grand) ** 2 for d in ds)
    ss_e = sum((scores[(k, d)] - mk[k] - md[d] + grand) ** 2 for k in kcs for d in ds)
    ms_k, ms_d = ss_k / (nk - 1), ss_d / (nd - 1)
    ms_e = ss_e / ((nk - 1) * (nd - 1))
    v_k = max(0.0, (ms_k - ms_e) / nd)
    v_d = max(0.0, (ms_d - ms_e) / nk)
    tot = v_k + v_d + ms_e
    if tot <= 0:
        return None
    g_coef = v_k / (v_k + ms_e / nd) if (v_k + ms_e / nd) > 0 else 0.0
    return {
        "n_kcs": nk, "n_" + facet_names[1]: nd,
        "var_kc": round(v_k, 6), "var_" + facet_names[1]: round(v_d, 6),
        "var_residual": round(ms_e, 6),
        "pct_kc": round(100 * v_k / tot, 1),
        "pct_" + facet_names[1]: round(100 * v_d / tot, 1),
        "pct_residual": round(100 * ms_e / tot, 1),
        "g_coefficient": round(g_coef, 4),
    }


def main() -> int:
    rng = random.Random(SEED)
    report = {"delta": DELTA, "delta_sensitivity": list(DELTA_SENS)}

    # ---- extrinsic: IR metrics ----
    report["ir_metrics"] = ir_metrics()

    # ---- crossed groundedness ----
    rows = {r["eval_row_id"]: r for r in jl(OUT / "crossed_rows.jsonl")}
    per = {}                                   # (kc, domain, drafter) -> groundedness
    for r in jl(OUT / "v3_crossed_groundedness.jsonl"):
        if "error" in r or r.get("abstained"):
            continue
        vs = r.get("verdicts") or []
        if not vs:
            continue
        src = rows.get(r["key"])
        if not src:
            continue
        per[(src["unit_id"], src["domain"], src["drafter"])] = \
            sum(1 for v in vs if v["label"] == "SUPPORTED") / len(vs)

    cells = defaultdict(list)
    for (kc, dom, drf), v in per.items():
        cells[(dom, drf)].append(v)
    report["groundedness_by_cell"] = {
        f"{d}|{m}": {"n": len(v), "mean": round(st.mean(v), 4)}
        for (d, m), v in sorted(cells.items())}

    # ---- model-agnostic: TOST between drafters, within each domain ----
    drafters = sorted({m for _, _, m in per})
    ma = {}
    for dom in sorted({d for _, d, _ in per}):
        for i in range(len(drafters)):
            for j in range(i + 1, len(drafters)):
                a, b = drafters[i], drafters[j]
                ks = [k for (k, d, m) in per if d == dom and m == a
                      and (k, dom, b) in per]
                if len(ks) < 10:
                    continue
                diffs = [per[(k, dom, a)] - per[(k, dom, b)] for k in ks]
                r = tost(diffs, DELTA, rng)
                r["sensitivity"] = {str(s): tost(diffs, s, rng)["equivalent"] for s in DELTA_SENS}
                ma[f"{dom}: {a} vs {b}"] = r
    report["model_agnostic_tost"] = ma

    # ---- domain-agnostic: TOST between domains, within each drafter ----
    da = {}
    doms = sorted({d for _, d, _ in per})
    for drf in drafters:
        for i in range(len(doms)):
            for j in range(i + 1, len(doms)):
                x, y = doms[i], doms[j]
                # different KC sets, so unpaired: compare arm means via bootstrap of the difference
                va = [v for (k, d, m), v in per.items() if d == x and m == drf]
                vb = [v for (k, d, m), v in per.items() if d == y and m == drf]
                if len(va) < 10 or len(vb) < 10:
                    continue
                boot = sorted(
                    st.mean([va[rng.randrange(len(va))] for _ in range(len(va))]) -
                    st.mean([vb[rng.randrange(len(vb))] for _ in range(len(vb))])
                    for _ in range(BOOT))
                lo, hi = boot[int(.05 * BOOT)], boot[int(.95 * BOOT) - 1]
                da[f"{drf}: {x} vs {y}"] = {
                    "mean_diff": round(st.mean(va) - st.mean(vb), 4),
                    "ci90": [round(lo, 4), round(hi, 4)],
                    "equivalent": (lo > -DELTA and hi < DELTA),
                    "n_a": len(va), "n_b": len(vb)}
    report["domain_agnostic_tost"] = da

    # ---- variance decomposition, per domain (KC x drafter crossed) ----
    vc = {}
    for dom in doms:
        sc = {(k, m): v for (k, d, m), v in per.items() if d == dom}
        r = variance_components(sc)
        if r:
            vc[dom] = r
    report["variance_components"] = vc
    # excluding the reasoning-model outlier, per the pre-specified compliance criterion
    vc2 = {}
    for dom in doms:
        sc = {(k, m): v for (k, d, m), v in per.items() if d == dom and m != "D"}
        r = variance_components(sc)
        if r:
            vc2[dom] = r
    report["variance_components_excl_D"] = vc2

    (OUT / "v3_analysis.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    # ---------------- console summary ----------------
    print("=" * 78)
    print("EXTRINSIC - pooled test collection (each passage judged individually)")
    print("=" * 78)
    hdr = f"{'arm':<28}" + "".join(f"{m:>10}" for m in ("P@10", "R@10", "nDCG@10", "R@20"))
    print(hdr)
    for a, m in sorted(report["ir_metrics"].items(), key=lambda kv: -kv[1].get("nDCG@10", 0)):
        print(f"{a:<28}" + "".join(f"{m.get(x, 0):>10.4f}" for x in ("P@10", "R@10", "nDCG@10", "R@20")))

    print()
    print("=" * 78)
    print(f"MODEL-AGNOSTIC - TOST, equivalence margin delta = {DELTA}")
    print("=" * 78)
    for k, v in ma.items():
        verdict = "EQUIVALENT" if v["equivalent"] else "not equivalent"
        print(f"  {k:<34} d={v['mean_diff']:+.4f} CI90 [{v['ci90'][0]:+.4f},{v['ci90'][1]:+.4f}] "
              f"n={v['n']:<4} {verdict}")

    print()
    print("=" * 78)
    print(f"DOMAIN-AGNOSTIC - TOST, delta = {DELTA}")
    print("=" * 78)
    for k, v in da.items():
        verdict = "EQUIVALENT" if v["equivalent"] else "not equivalent"
        print(f"  {k:<34} d={v['mean_diff']:+.4f} CI90 [{v['ci90'][0]:+.4f},{v['ci90'][1]:+.4f}] "
              f"{verdict}")

    print()
    print("=" * 78)
    print("VARIANCE COMPONENTS - share of groundedness variance by facet")
    print("=" * 78)
    print(f"{'domain':<16}{'% KC':>8}{'% drafter':>12}{'% resid':>10}{'G-coef':>9}   (all 3 drafters)")
    for d, v in vc.items():
        print(f"{d:<16}{v['pct_kc']:>8.1f}{v['pct_drafter']:>12.1f}{v['pct_residual']:>10.1f}"
              f"{v['g_coefficient']:>9.3f}")
    print(f"{'domain':<16}{'% KC':>8}{'% drafter':>12}{'% resid':>10}{'G-coef':>9}   (Qwen+Gemma only)")
    for d, v in vc2.items():
        print(f"{d:<16}{v['pct_kc']:>8.1f}{v['pct_drafter']:>12.1f}{v['pct_residual']:>10.1f}"
              f"{v['g_coefficient']:>9.3f}")
    print(f"\nwrote {OUT / 'v3_analysis.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
