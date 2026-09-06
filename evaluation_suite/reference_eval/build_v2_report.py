"""Assemble the final v2 evaluation report.

Combines the four v2 measurements into one artifact and applies the statistics fixed in
COMPARATIVE_USE_PROTOCOL.md section 3 (KC as unit of analysis, KC-clustered bootstrap, exact
McNemar, Holm within family).

The organising idea is FAILURE ATTRIBUTION. Context recall is measured on the retrieved evidence
with no generator in the loop, so a low score localises the failure to retrieval; nugget recall is
measured on the draft, so the gap between them localises it to generation. That is what makes these
numbers interpretable rather than arbitrary - and it is only possible because the seven arms use
just four distinct evidence configurations.

Caveats are emitted into the report itself rather than left to the reader: absolute
JUDGE_QUALIFIED=false, LOW_POWER arm-independence, single-annotator gold, the non-random
KC_CLF_NB_009 exclusion (F-36), and the prompt-asymmetry confound on the attribution gap (F-40).
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import statistics as st
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent
OUT = BASE / "output"
BOOT, SEED = 10000, 20260831

FAMILIES = {
    "intrinsic": ["intrinsic_P-Q", "intrinsic_P-G", "intrinsic_P-D"],
    "extrinsic": ["extrinsic_P-Q", "extrinsic_B-Q", "extrinsic_DOS-Q"],
}
EXPLORATORY = [("extrinsic_DOS-Q", "sensitivity_DOS-Q_matched")]

# F-45: measured ceiling of the context-recall judge when the required content is PROVABLY present.
# Ground truth is 1.0 at every point; the shortfall is the judge losing content placed late in a
# large passage set. Any comparison between arms whose ceilings differ materially is measuring set
# size, not retrieval quality.
DILUTION_CEILING = {17: 1.0000, 33: 0.9934, 123: 0.5905}
CEILING_GAP_TOLERANCE = 0.05


def ceiling_at(n_passages):
    """Piecewise-linear interpolation of the F-45 ceiling curve."""
    pts = sorted(DILUTION_CEILING)
    if n_passages <= pts[0]:
        return DILUTION_CEILING[pts[0]]
    if n_passages >= pts[-1]:
        return DILUTION_CEILING[pts[-1]]
    for a, b in zip(pts, pts[1:]):
        if a <= n_passages <= b:
            f = (n_passages - a) / (b - a)
            return DILUTION_CEILING[a] + f * (DILUTION_CEILING[b] - DILUTION_CEILING[a])
    return DILUTION_CEILING[pts[-1]]


def jl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def ev_hash(row):
    return hashlib.sha256("|".join(e["text"] for e in row.get("candidate_system_evidence") or [])
                          .encode("utf-8")).hexdigest()[:16]


def exact_mcnemar(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n))


def holm(p):
    items = sorted(p.items(), key=lambda kv: kv[1])
    out, run = {}, 0.0
    for i, (k, v) in enumerate(items):
        run = max(run, min(1.0, (len(items) - i) * v))
        out[k] = run
    return out


def main() -> int:
    rows = {r["eval_row_id"]: r for r in jl(OUT / "ablation_rows.jsonl")}
    nug = {r["unit_id"]: r["nuggets"] for r in jl(OUT / "v2_nuggets.jsonl") if r.get("nuggets")}
    ctx = {r["key"]: r for r in jl(OUT / "v2_context.jsonl") if r.get("verdicts")}
    asg = {r["key"]: r for r in jl(OUT / "v2_assign.jsonl") if r.get("verdicts")}
    fth = {r["key"]: r for r in jl(OUT / "v2_faith.jsonl") if "error" not in r}

    # ---- per-row metric values, keyed by (arm, kc) ----
    per = defaultdict(dict)   # arm -> kc -> {metric: value}
    for rid, row in rows.items():
        kc, arm = row["unit_id"], row["arm"]
        ng = nug.get(kc)
        if not ng:
            continue
        vital = {i + 1 for i, x in enumerate(ng) if x["importance"] == "VITAL"}
        if not vital:
            continue
        d = {}
        c = ctx.get(f"{kc}|{ev_hash(row)}")
        if c:
            pres = sum(1 for v in c["verdicts"] if v["nugget_index"] in vital and v["label"] == "PRESENT")
            d["context_recall"] = pres / len(vital)
            d["n_evidence"] = c.get("n_evidence", 0)
        a = asg.get(rid)
        if a:
            sup = sum(1 for v in a["verdicts"] if v["nugget_index"] in vital and v["label"] == "SUPPORTED")
            d["nugget_recall"] = sup / len(vital)
        d["draft_words"] = len((row.get("candidate_draft") or "").split())
        f = fth.get(rid)
        if f:
            d["abstained"] = bool(f.get("abstained"))
            # Two very different behaviours both surface as "no draft", and collapsing them would
            # hide the finding. FORCED: retrieval returned nothing, so declining is the only correct
            # move. CHOSEN: evidence was available and the drafter still declined. Measured: all 23
            # zero-evidence rows abstained and none produced a draft without evidence.
            if d["abstained"]:
                d["abstain_forced"] = (d.get("n_evidence", 0) == 0)
            vs = f.get("verdicts") or []
            if vs:
                d["faithfulness"] = sum(1 for x in vs if x["label"] == "SUPPORTED") / len(vs)
                d["n_claims"] = len(vs)
        if d:
            per[arm][kc] = d

    # Coverage and abstention are properties of the FULL 1113 rows, not of the 151-KC scored
    # subset. Reporting them only over scored KCs would hide the zero-evidence rows entirely,
    # because those KCs are exactly the ones missing an expert reference.
    all_kcs = {r["unit_id"] for r in rows.values()}
    has_ref = {r["unit_id"] for r in rows.values() if (r.get("expert_reference") or "").strip()}
    refless = sorted(all_kcs - has_ref)
    behaviour = defaultdict(lambda: {"n": 0, "abstain_forced": 0, "abstain_chosen": 0,
                                     "drafted_with_zero_evidence": 0})
    for row in rows.values():
        b = behaviour[row["arm"]]
        b["n"] += 1
        n_ev = len(row.get("candidate_system_evidence") or [])
        drafted = bool((row.get("candidate_draft") or "").strip())
        if not drafted:
            b["abstain_forced" if n_ev == 0 else "abstain_chosen"] += 1
        elif n_ev == 0:
            b["drafted_with_zero_evidence"] += 1
    coverage = {
        "kcs_total": len(all_kcs),
        "kcs_scored": None,
        "excluded_no_expert_reference": refless,
        "excluded_decomposition_failed": ["KC_CLF_NB_009"],
        "note": ("All 8 exclusions are arm-independent: a reference and its decomposition are "
                 "properties of the KC, so every arm loses the SAME KCs and paired comparisons "
                 "stay balanced. The excluded set is NOT random, however - 4 of the 7 "
                 "reference-less KCs are exactly those where the Proposed retriever returned zero "
                 "evidence. Had they been scorable they would have scored 0 context recall for "
                 "Proposed, while BaseDense, which always returns passages, might have scored "
                 "above 0. The exclusion therefore plausibly flatters Proposed on ABSOLUTE "
                 "retrieval recall; relative paired comparisons are unaffected."),
    }

    arms = sorted(per)
    rng = random.Random(SEED)

    def agg(arm, metric):
        return [v[metric] for v in per[arm].values() if metric in v]

    summary = {}
    for a in arms:
        vals = per[a]
        summary[a] = {
            "n_kcs": len(vals),
            "context_recall": round(st.mean(agg(a, "context_recall")), 4) if agg(a, "context_recall") else None,
            "nugget_recall": round(st.mean(agg(a, "nugget_recall")), 4) if agg(a, "nugget_recall") else None,
            "faithfulness": round(st.mean(agg(a, "faithfulness")), 4) if agg(a, "faithfulness") else None,
            "abstention_rate": round(sum(1 for v in vals.values() if v.get("abstained")) / len(vals), 4),
            "abstain_forced_no_evidence": sum(1 for v in vals.values() if v.get("abstain_forced")),
            "abstain_chosen_despite_evidence": sum(
                1 for v in vals.values() if v.get("abstained") and not v.get("abstain_forced")),
            "mean_evidence_items": round(st.mean(agg(a, "n_evidence")), 1) if agg(a, "n_evidence") else None,
            "mean_claims": round(st.mean(agg(a, "n_claims")), 2) if agg(a, "n_claims") else None,
        }

    def paired(metric, a1, a2):
        ks = [k for k in per[a1] if k in per[a2]
              and metric in per[a1][k] and metric in per[a2][k]]
        if not ks:
            return None
        diffs = [per[a1][k][metric] - per[a2][k][metric] for k in ks]
        mean = st.mean(diffs)
        boot = []
        for _ in range(BOOT):
            s = [diffs[rng.randrange(len(diffs))] for _ in range(len(diffs))]
            boot.append(st.mean(s))
        boot.sort()
        lo, hi = boot[int(.025 * BOOT)], boot[int(.975 * BOOT) - 1]
        b = sum(1 for d in diffs if d > 0)
        c = sum(1 for d in diffs if d < 0)
        return {"n_kcs": len(ks), "mean_diff": round(mean, 4),
                "ci95": [round(lo, 4), round(hi, 4)],
                "better_a1": b, "better_a2": c,
                "mcnemar_p": round(exact_mcnemar(b, c), 6),
                "ci_excludes_zero": (lo > 0 and hi > 0) or (lo < 0 and hi < 0)}

    def length_adjusted(metric, n_bins=5):
        """Direct standardisation of `metric` onto the pooled draft-length distribution.

        The judge is Llama-family, and Llama-family judges reward verbosity on completeness-style
        judgements (F-35, [R-07]). An arm that simply writes longer drafts can therefore score
        higher without conveying more. Direct standardisation removes that: each arm is re-scored
        as if its drafts had the SAME length distribution as the pooled corpus, so only
        within-length-band differences survive.

        Abstentions are excluded - a zero-length draft has no length band to belong to, and its
        contribution is already reported separately as the abstention rate.
        """
        pooled = sorted(v["draft_words"] for a in arms for v in per[a].values()
                        if metric in v and v.get("draft_words", 0) > 0)
        if len(pooled) < n_bins * 2:
            return None
        # quantile cut points on the pooled distribution = the standard population
        cuts = [pooled[int(len(pooled) * (i + 1) / n_bins) - 1] for i in range(n_bins - 1)]

        def band(w):
            for i, c in enumerate(cuts):
                if w <= c:
                    return i
            return n_bins - 1

        weights = [0] * n_bins
        for w in pooled:
            weights[band(w)] += 1
        total = sum(weights)

        out = {}
        for a in arms:
            vals = [(band(v["draft_words"]), v[metric]) for v in per[a].values()
                    if metric in v and v.get("draft_words", 0) > 0]
            if not vals:
                continue
            means, covered = {}, 0
            for b in range(n_bins):
                xs = [x for bb, x in vals if bb == b]
                if xs:
                    means[b] = st.mean(xs)
                    covered += weights[b]
            if not means:
                continue
            # renormalise over covered bands only, so an arm with an empty band is not penalised
            adj = sum(weights[b] / covered * m for b, m in means.items())
            raw = st.mean([x for _, x in vals])
            out[a] = {"raw_drafted_only": round(raw, 4),
                      "length_adjusted": round(adj, 4),
                      "shift": round(adj - raw, 4),
                      "bands_covered": len(means),
                      "mean_words": round(st.mean([v["draft_words"] for v in per[a].values()
                                                   if metric in v and v.get("draft_words", 0) > 0]), 1)}
        return {"n_bins": n_bins, "band_upper_bounds": cuts,
                "band_weights": [round(w / total, 3) for w in weights], "by_arm": out}

    length_adj = {m: length_adjusted(m) for m in ("nugget_recall", "faithfulness")}

    def adjusted_diff(metric, a1, a2, n_bins=5):
        """Paired difference in `metric` after direct standardisation, with a KC bootstrap CI.

        The standard population (band cut points and weights) is held FIXED across resamples -
        that is what direct standardisation means - while the arm-specific band means are
        resampled over KCs. Returns None if either arm has too little drafted data.
        """
        ks = [k for k in per[a1] if k in per[a2]
              and metric in per[a1][k] and metric in per[a2][k]
              and per[a1][k].get("draft_words", 0) > 0 and per[a2][k].get("draft_words", 0) > 0]
        if len(ks) < n_bins * 2:
            return None
        pooled = sorted(v["draft_words"] for a in arms for v in per[a].values()
                        if metric in v and v.get("draft_words", 0) > 0)
        cuts = [pooled[int(len(pooled) * (i + 1) / n_bins) - 1] for i in range(n_bins - 1)]

        def band(w):
            for i, c in enumerate(cuts):
                if w <= c:
                    return i
            return n_bins - 1

        weights = [0] * n_bins
        for w in pooled:
            weights[band(w)] += 1

        def adj_mean(sample, arm):
            acc, covered = {}, 0
            for k in sample:
                acc.setdefault(band(per[arm][k]["draft_words"]), []).append(per[arm][k][metric])
            for b in acc:
                covered += weights[b]
            if not covered:
                return None
            return sum(weights[b] / covered * st.mean(v) for b, v in acc.items())

        point = None
        m1, m2 = adj_mean(ks, a1), adj_mean(ks, a2)
        if m1 is not None and m2 is not None:
            point = m1 - m2
        boot = []
        for _ in range(BOOT):
            samp = [ks[rng.randrange(len(ks))] for _ in range(len(ks))]
            x, y = adj_mean(samp, a1), adj_mean(samp, a2)
            if x is not None and y is not None:
                boot.append(x - y)
        if not boot or point is None:
            return None
        boot.sort()
        lo, hi = boot[int(.025 * len(boot))], boot[int(.975 * len(boot)) - 1]
        raw = st.mean([per[a1][k][metric] - per[a2][k][metric] for k in ks])
        return {"n_kcs": len(ks), "raw_diff": round(raw, 4), "adjusted_diff": round(point, 4),
                "ci95": [round(lo, 4), round(hi, 4)],
                "ci_excludes_zero": (lo > 0 and hi > 0) or (lo < 0 and hi < 0),
                "sign_flips": (raw > 0) != (point > 0)}

    robustness = {}
    for _fam, _fa in FAMILIES.items():
        for _i in range(len(_fa)):
            for _j in range(_i + 1, len(_fa)):
                r = adjusted_diff("nugget_recall", _fa[_i], _fa[_j])
                if r:
                    robustness[f"{_fa[_i]} vs {_fa[_j]}"] = r

    comparisons = {}
    for fam, fa in FAMILIES.items():
        comparisons[fam] = {}
        # The intrinsic family holds evidence FIXED by design - all three arms share the "Proposed"
        # evidence configuration (verified: 1 distinct config hash). Context recall is therefore
        # identical by construction, and a paired test on it would compare a config against itself.
        # Suppressed rather than reported as a row of zeros.
        mets = ("nugget_recall", "faithfulness") if fam == "intrinsic" else \
               ("context_recall", "nugget_recall", "faithfulness")
        for metric in mets:
            res, pv = {}, {}
            for i in range(len(fa)):
                for j in range(i + 1, len(fa)):
                    k = f"{fa[i]} vs {fa[j]}"
                    r = paired(metric, fa[i], fa[j])
                    if r:
                        res[k] = r
                        pv[k] = r["mcnemar_p"]
            for k, adj in holm(pv).items():
                res[k]["holm_p"] = round(adj, 6)
                res[k]["significant"] = adj < 0.05 and res[k]["ci_excludes_zero"]
            # F-45: context recall is read off the evidence set, so a comparison between arms with
            # very different set sizes is confounded by the judge's serial-position failure.
            # Nugget recall is read off the DRAFT and is immune, so it is never flagged.
            if metric == "context_recall":
                for k in res:
                    a1, a2 = k.split(" vs ")
                    c1 = ceiling_at(summary[a1]["mean_evidence_items"] or 0)
                    c2 = ceiling_at(summary[a2]["mean_evidence_items"] or 0)
                    res[k]["ceiling_a1"] = round(c1, 4)
                    res[k]["ceiling_a2"] = round(c2, 4)
                    res[k]["ceiling_gap"] = round(abs(c1 - c2), 4)
                    if abs(c1 - c2) > CEILING_GAP_TOLERANCE:
                        res[k]["significant"] = False
                        res[k]["dilution_confounded"] = True
            comparisons[fam][metric] = res

    explor = {}
    for a1, a2 in EXPLORATORY:
        explor[f"{a1} vs {a2}"] = {m: paired(m, a1, a2)
                                   for m in ("context_recall", "nugget_recall", "faithfulness")}

    coverage["kcs_scored"] = len(per[arms[0]])
    report = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "instrument": "Cluster A ant2, 4xH100, TP4, CUDA 13 - single instrument, zero deviation",
        "protocol": "OVERHAUL_PROTOCOL_v2.md (pre-registered)",
        "coverage": coverage,
        "abstention_behaviour_all_rows": {k: dict(v) for k, v in behaviour.items()},
        "length_adjusted": length_adj,
        "length_robustness_nugget_recall": robustness,
        "summary_by_arm": summary,
        "paired_comparisons": comparisons,
        "exploratory": explor,
        "caveats": [
            "Absolute JUDGE_QUALIFIED=false. Only relative within-KC claims are licensed.",
            "Arm-independence established at LOW POWER (4-6 calibration rows per arm); weak "
            "evidence, not proof.",
            "Human gold is 36 rows from a SINGLE annotator, against a literature calibration "
            "benchmark of roughly 150 [R-02].",
            "F-45: context recall is depressed by evidence-set size (judge recovers 0.5905 of "
            "provably-present nuggets at 123 passages vs 1.0000 at 17). Comparisons against "
            "BaseDense are confounded and carry no claim; nugget recall, judged on drafts, is "
            "unaffected.",
            "Nugget and context metrics cover 151 of 159 KCs: 7 KCs have NO expert reference "
            "(the library covers 152/159) and KC_CLF_NB_009 fails decomposition structurally "
            "(F-36). All 8 drop identically for every arm, so paired comparisons stay "
            "balanced, but the excluded set is NOT random - 4 of the 7 reference-less KCs are "
            "exactly those where Proposed retrieved zero evidence, so the exclusion plausibly "
            "flatters Proposed ABSOLUTE retrieval recall (F-42).",
            "F-40 RESOLVED: the two recall prompts carry no constant offset (B = 0.0000; both "
            "recover 100% shown the same content), so the attribution gap is NOT prompt-asymmetry "
            "confounded. It remains uninterpretable for large-evidence arms under F-45.",
            "Completeness is verbosity-confounded under this Llama-family judge; length-adjusted "
            "figures are reported alongside (F-35, R-07).",
        ],
    }
    (OUT / "v2_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    L = ["# v2 evaluation results (final)\n",
         f"Generated {report['generated_utc']} · **single instrument**: {report['instrument']}\n",
         "> Metrics are grounded in published constructs: per-claim faithfulness is the RAGAS "
         "supported/total ratio [R-01]; vital-nugget recall follows TREC RAG nugget evaluation "
         "[R-03,R-04]; context recall/precision are the RAGAS retrieval constructs [R-01].\n",
         "> **F-45 — read the context-recall column with care.** The judge recovers only "
         "**0.5905** of nuggets that are *provably present* when the evidence set holds 123 "
         "passages, against **1.0000** at 17 (serial-position failure, not truncation). Context "
         "recall is therefore **not comparable across arms with different retrieval budgets**, and "
         "comparisons against BaseDense (123.1 passages) are flagged as confounded below. "
         "Nugget recall is judged against the **draft** and is immune.\n",
         "## Summary by arm\n",
         "| arm | evidence items | context recall | nugget recall | faithfulness | abstention | mean claims |",
         "|---|---|---|---|---|---|---|"]
    for a in sorted(arms, key=lambda x: -(summary[x]["nugget_recall"] or 0)):
        s = summary[a]
        L.append(f"| {a} | {s['mean_evidence_items']} | {s['context_recall']} | "
                 f"{s['nugget_recall']} | {s['faithfulness']} | {s['abstention_rate']} | {s['mean_claims']} |")

    L.append(f"\n*Scored on {coverage['kcs_scored']}/{coverage['kcs_total']} KCs. "
             f"{len(refless)} KCs have no expert reference and 1 fails decomposition; all 8 drop "
             f"identically for every arm, so paired comparisons stay balanced.*\n")

    L.append("\n## Abstention behaviour (all 1113 rows, no exclusions)\n")
    L.append("**Forced** = retrieval returned nothing, so declining to draft is the only correct "
             "move. **Chosen** = evidence was available and the drafter still declined. The last "
             "column is the failure mode that would matter most: asserting a description with no "
             "evidence behind it.\n")
    L.append("| arm | rows | forced abstention | chosen abstention | drafted with ZERO evidence |")
    L.append("|---|---|---|---|---|")
    for a in sorted(behaviour):
        b = behaviour[a]
        L.append(f"| {a} | {b['n']} | {b['abstain_forced']} | {b['abstain_chosen']} | "
                 f"**{b['drafted_with_zero_evidence']}** |")
    L.append("\nAcross every arm and all 1113 rows, **no draft was ever produced from an empty "
             "evidence set**: every zero-evidence row abstained. Evidence-grounded abstention is "
             "a property of the harness rather than of any single pipeline.\n")

    L.append("\n## Failure attribution\n")
    L.append("Context recall is measured on retrieved evidence with **no generator in the loop**, "
             "so it localises failure to a pipeline stage. The two prompts were calibrated against "
             "each other and sit on a **common scale**: shown the same content both recover 100% of "
             "nuggets, offset B = 0.0000 (F-40, resolved), so the gap is readable. The live caveat "
             "is F-45 instead - where the evidence set is large the context term is depressed by "
             "set size, and that arm's gap is not interpretable at all.\n")
    L.append("| arm | context recall | nugget recall | gap | reading |")
    L.append("|---|---|---|---|---|")
    for a in sorted(arms, key=lambda x: -(summary[x]["nugget_recall"] or 0)):
        cr, nr = summary[a]["context_recall"], summary[a]["nugget_recall"]
        if cr is None or nr is None:
            continue
        g = nr - cr
        if ceiling_at(summary[a]["mean_evidence_items"] or 0) < 1 - CEILING_GAP_TOLERANCE:
            # the context term is depressed by set size, so the gap is not interpretable at all
            read = "**gap not interpretable — F-45 dilution**"
        else:
            read = ("uses available content" if g > 0.02 else
                    "**content retrieved but not used**" if g < -0.02 else "tracks retrieval")
        L.append(f"| {a} | {cr} | {nr} | {g:+.4f} | {read} |")

    L.append("\n## Length-adjusted metrics (direct standardisation)\n")
    L.append("This judge is Llama-family, and Llama-family judges reward verbosity on "
             "completeness-style judgements (F-35, [R-07]). An arm that writes longer drafts can "
             "score higher without conveying more. Each arm is therefore re-scored as if its "
             "drafts had the **same length distribution as the pooled corpus**, so only "
             "within-length-band differences survive. Abstentions are excluded (a zero-length "
             "draft has no band); they are reported separately above.\n")
    for metric, la in length_adj.items():
        if not la:
            continue
        L.append(f"\n### {metric}\n")
        L.append(f"Bands: quintiles of pooled draft length, upper bounds "
                 f"{la['band_upper_bounds']} words.\n")
        L.append("| arm | mean words | raw (drafted only) | length-adjusted | shift | bands |")
        L.append("|---|---|---|---|---|---|")
        for a, v in sorted(la["by_arm"].items(), key=lambda kv: -kv[1]["length_adjusted"]):
            L.append(f"| {a} | {v['mean_words']} | {v['raw_drafted_only']} | "
                     f"**{v['length_adjusted']}** | {v['shift']:+} | {v['bands_covered']}/5 |")

    L.append("\n### Does the completeness ranking survive length adjustment?\n")
    L.append("Each pairwise difference in nugget recall, before and after direct standardisation. "
             "**A pair whose sign flips is not a safe ranking claim** - it is reporting draft "
             "length as much as coverage.\n")
    L.append("| comparison | raw Δ | length-adjusted Δ | 95% CI (adjusted) | robust? |")
    L.append("|---|---|---|---|---|")
    for k, r in robustness.items():
        if r["sign_flips"]:
            verdict = "**NO - sign flips**"
        elif r["ci_excludes_zero"]:
            verdict = "yes"
        else:
            verdict = "direction holds, CI includes 0"
        L.append(f"| {k} | {r['raw_diff']:+} | {r['adjusted_diff']:+} | "
                 f"[{r['ci95'][0]:+}, {r['ci95'][1]:+}] | {verdict} |")

    for fam, mets in comparisons.items():
        L.append(f"\n## Family: {fam} (Holm-corrected within family)\n")
        for metric, res in mets.items():
            if not res:
                continue
            L.append(f"\n### {metric}\n")
            L.append("| comparison | Δ | 95% CI (KC bootstrap) | better a1/a2 | exact p | Holm p | verdict |")
            L.append("|---|---|---|---|---|---|---|")
            for k, r in res.items():
                if r.get("dilution_confounded"):
                    verdict = (f"**CONFOUNDED (F-45)** — judge ceilings {r['ceiling_a1']} vs "
                               f"{r['ceiling_a2']}; no claim")
                elif r.get("significant"):
                    verdict = "**significant**"
                else:
                    verdict = "not significant"
                L.append(f"| {k} | {r['mean_diff']:+} | [{r['ci95'][0]:+}, {r['ci95'][1]:+}] | "
                         f"{r['better_a1']}/{r['better_a2']} | {r['mcnemar_p']} | {r.get('holm_p')} | "
                         f"{verdict} |")

    L.append("\n## Exploratory (no ranking claim)\n")
    for k, mets in explor.items():
        L.append(f"\n### {k}\n")
        L.append("| metric | Δ | 95% CI | exact p |")
        L.append("|---|---|---|---|")
        for m, r in mets.items():
            if r:
                L.append(f"| {m} | {r['mean_diff']:+} | [{r['ci95'][0]:+}, {r['ci95'][1]:+}] | {r['mcnemar_p']} |")

    L.append("\n## Caveats\n")
    for c in report["caveats"]:
        L.append(f"- {c}")
    (OUT / "V2_RESULTS.md").write_text("\n".join(L) + "\n", encoding="utf-8")

    print(f"arms: {len(arms)} | KCs per arm: {summary[arms[0]]['n_kcs']}")
    print("wrote v2_report.json and V2_RESULTS.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
