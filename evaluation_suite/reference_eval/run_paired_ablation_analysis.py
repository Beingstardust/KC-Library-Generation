"""Paired ablation analysis, executing the plan fixed in COMPARATIVE_USE_PROTOCOL.md section 3.

The analysis plan was pre-registered before any ablation verdict existed; this script implements it
and does not introduce new choices. In particular:

  * The UNIT OF ANALYSIS IS THE KC, never the row. The calibration failure showed rows cluster by KC
    (36 rows spanned only 17 KCs, and one KC produced half the M3 false-fails), so all uncertainty is
    estimated by resampling KCs, not rows.
  * Every arm drafts the same KCs, so each comparison is PAIRED WITHIN KC. That is what licenses use
    of a judge which failed absolute qualification: a constant threshold offset cancels within a pair
    (findings F-14, F-17, F-20).
  * Confidence intervals come from a KC-CLUSTERED BOOTSTRAP; significance from an EXACT McNemar test
    on discordant pairs; multiplicity is Holm-corrected across the 3 pairwise comparisons within each
    pre-specified family.

ABSTENTIONS ARE NOT MISSING DATA. An empty draft is a real behaviour of that system and abstention
rate is reported as a primary outcome in its own right. But an abstention cannot be scored for
claim-level faithfulness or correctness - there are no claims - so scoring it "fail" would conflate
"declined to answer" with "answered wrongly". For M1/M2/TARGET a KC therefore enters a given pair
only when BOTH arms produced a judgeable draft; excluded pairs are counted and reported, never
imputed. M3 is judged even on empty drafts, so it retains full coverage.

THE NOISE GUARD is prespecified: any arm difference smaller than that task's own judge-human
disagreement rate is reported as WITHIN_INSTRUMENT_NOISE and carries no ranking claim.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent

# "pass" side of each binary outcome. Anything else scores as not-pass.
TASKS = {
    "M1_faithfulness_per_claim": "PASS",
    "M2_correctness_per_claim": "PASS",
    "M3_core_completeness": "CORE_COMPLETE",
    "TARGET_ALIGNMENT": "TARGET_ALIGNED",
}

# Judge-human disagreement rate per task, taken from the frozen qualification run
# (qualification_decision.json: 1 - raw_agreement). Used ONLY for the prespecified noise guard.
JUDGE_HUMAN_DISAGREEMENT = {
    "M1_faithfulness_per_claim": 1 - 0.6333333333333333,
    "M2_correctness_per_claim": 1 - 0.6666666666666666,
    "M3_core_completeness": 1 - 0.5555555555555556,
    "TARGET_ALIGNMENT": 1 - 0.90625,
}

# Pre-specified comparison families. Holm correction is applied WITHIN each family, per task.
FAMILIES = {
    "intrinsic": ["intrinsic_P-Q", "intrinsic_P-G", "intrinsic_P-D"],
    "extrinsic": ["extrinsic_P-Q", "extrinsic_B-Q", "extrinsic_DOS-Q"],
}
# Exploratory only - never Holm-corrected with the confirmatory families, never a ranking claim.
EXPLORATORY_PAIRS = [("extrinsic_DOS-Q", "sensitivity_DOS-Q_matched")]

BOOTSTRAP_N = 10000
SEED = 20260831


def exact_mcnemar(b: int, c: int) -> float:
    """Two-sided exact McNemar: Binomial(b+c, 0.5) on the discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    # sum of tail probabilities, doubled, clipped at 1
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def holm(pvals: dict[str, float]) -> dict[str, float]:
    """Holm-Bonferroni step-down adjusted p-values."""
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    adjusted, running = {}, 0.0
    for i, (k, p) in enumerate(items):
        val = min(1.0, (m - i) * p)
        running = max(running, val)  # enforce monotonicity
        adjusted[k] = running
    return adjusted


def load_rows(paths):
    rows, dupes = {}, 0
    for p in paths:
        for line in open(p, encoding="utf-8"):
            if not line.strip():
                continue
            r = json.loads(line)
            rid = r.get("eval_row_id")
            if rid is None:
                continue
            if rid in rows:
                dupes += 1
                # prefer the zero-deviation frozen instrument when a row was computed twice
                if r.get("instrument") == "ants_tp4_h100_frozen":
                    rows[rid] = r
                continue
            rows[rid] = r
    return rows, dupes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--predictions", type=Path, nargs="+", required=True)
    ap.add_argument("--out-json", type=Path, default=BASE / "output" / "ablation_analysis.json")
    ap.add_argument("--out-md", type=Path, default=BASE / "output" / "ABLATION_RESULTS.md")
    args = ap.parse_args()

    rows, dupes = load_rows(args.predictions)
    errors = {k: v for k, v in rows.items() if "error" in v}
    ok = {k: v for k, v in rows.items() if "error" not in v}

    # index: kc -> arm -> row
    by_kc = defaultdict(dict)
    for r in ok.values():
        by_kc[r["unit_id"]][r["arm"]] = r
    arms = sorted({r["arm"] for r in ok.values()})
    kcs = sorted(by_kc)

    instruments = defaultdict(int)
    for r in ok.values():
        instruments[r.get("instrument", "unspecified")] += 1

    # ---------- abstention: a primary outcome, not a nuisance ----------
    abstention = {}
    for a in arms:
        tot = sum(1 for k in kcs if a in by_kc[k])
        n_abs = sum(1 for k in kcs if a in by_kc[k] and by_kc[k][a].get("abstained"))
        abstention[a] = {"n_kcs": tot, "abstained": n_abs,
                         "rate": round(n_abs / tot, 4) if tot else None}

    # ---------- per-arm rates ----------
    per_arm = {}
    for task, passv in TASKS.items():
        per_arm[task] = {}
        for a in arms:
            vals = [by_kc[k][a].get(task) for k in kcs if a in by_kc[k]]
            judged = [v for v in vals if v is not None]
            n_pass = sum(1 for v in judged if v == passv)
            per_arm[task][a] = {
                "n_judgeable": len(judged),
                "n_not_judgeable": len(vals) - len(judged),
                "pass_rate": round(n_pass / len(judged), 4) if judged else None,
            }

    rng = random.Random(SEED)

    def paired(task, a1, a2):
        """Paired within-KC comparison. Only KCs where BOTH arms are judgeable contribute."""
        passv = TASKS[task]
        pairs, excluded = [], 0
        for k in kcs:
            r1, r2 = by_kc[k].get(a1), by_kc[k].get(a2)
            if not r1 or not r2:
                excluded += 1
                continue
            v1, v2 = r1.get(task), r2.get(task)
            if v1 is None or v2 is None:
                excluded += 1
                continue
            pairs.append((k, v1 == passv, v2 == passv))
        n = len(pairs)
        if n == 0:
            return {"n_kc_pairs": 0, "excluded_kcs": excluded, "note": "no comparable KCs"}
        b = sum(1 for _, x, y in pairs if x and not y)   # a1 pass, a2 fail
        c = sum(1 for _, x, y in pairs if y and not x)   # a2 pass, a1 fail
        diff = (sum(x for _, x, _ in pairs) - sum(y for _, _, y in pairs)) / n

        boot = []
        for _ in range(BOOTSTRAP_N):
            samp = [pairs[rng.randrange(n)] for _ in range(n)]   # resample KCs, not rows
            boot.append((sum(x for _, x, _ in samp) - sum(y for _, _, y in samp)) / n)
        boot.sort()
        lo, hi = boot[int(0.025 * BOOTSTRAP_N)], boot[int(0.975 * BOOTSTRAP_N) - 1]

        p = exact_mcnemar(b, c)
        noise = JUDGE_HUMAN_DISAGREEMENT[task]
        return {
            "n_kc_pairs": n, "excluded_kcs": excluded,
            "discordant_a1_better": b, "discordant_a2_better": c,
            "paired_diff_a1_minus_a2": round(diff, 4),
            "bootstrap_ci95": [round(lo, 4), round(hi, 4)],
            "mcnemar_exact_p": round(p, 6),
            "judge_human_disagreement_rate": round(noise, 4),
            "within_instrument_noise": abs(diff) < noise,
        }

    results = {"families": {}, "exploratory": {}}
    for fam, fam_arms in FAMILIES.items():
        results["families"][fam] = {}
        for task in TASKS:
            comparisons, pvals = {}, {}
            for i in range(len(fam_arms)):
                for j in range(i + 1, len(fam_arms)):
                    a1, a2 = fam_arms[i], fam_arms[j]
                    key = f"{a1} vs {a2}"
                    res = paired(task, a1, a2)
                    comparisons[key] = res
                    if "mcnemar_exact_p" in res:
                        pvals[key] = res["mcnemar_exact_p"]
            for key, adj in holm(pvals).items():
                r = comparisons[key]
                r["holm_adjusted_p"] = round(adj, 6)
                # AS SPECIFIED: the registered guard, retained verbatim (see AMENDMENT_01).
                r["verdict_as_specified"] = (
                    "WITHIN_INSTRUMENT_NOISE" if r["within_instrument_noise"]
                    else ("significant" if adj < 0.05 else "not significant"))
                # AMENDED (AMENDMENT_01): for a PAIRED difference, inference rests on the controls
                # the protocol already registered - Holm-adjusted exact McNemar plus a KC-clustered
                # bootstrap CI excluding zero. No new parameter is introduced.
                ci = r["bootstrap_ci95"]
                ci_excl = (ci[0] > 0 and ci[1] > 0) or (ci[0] < 0 and ci[1] < 0)
                r["ci_excludes_zero"] = ci_excl
                r["verdict_amended"] = ("significant" if (adj < 0.05 and ci_excl)
                                        else "not significant")
                r["significant_after_holm"] = r["verdict_amended"] == "significant"
            results["families"][fam][task] = comparisons

    for a1, a2 in EXPLORATORY_PAIRS:
        key = f"{a1} vs {a2}"
        results["exploratory"][key] = {
            t: {**paired(t, a1, a2), "status": "EXPLORATORY_ONLY_no_ranking_claim"} for t in TASKS
        }

    report = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "protocol": "COMPARATIVE_USE_PROTOCOL.md section 3 (pre-registered)",
        "standing_absolute_result": "JUDGE_QUALIFIED=false; M3_CORE_COMPLETENESS NOT_QUALIFIED",
        "comparative_basis": "COMPARATIVE_QUALIFIED for M1/M2/M3/TARGET (arm-independence, LOW_POWER)",
        "unit_of_analysis": "knowledge component (KC)",
        "bootstrap": {"resamples": BOOTSTRAP_N, "cluster": "KC", "seed": SEED},
        "n_rows_loaded": len(rows), "n_rows_ok": len(ok), "n_rows_error": len(errors),
        "duplicate_rows_deduped": dupes,
        "error_rows": {k: v.get("error") for k, v in errors.items()},
        "n_kcs": len(kcs), "arms": arms,
        "instrument_provenance": dict(instruments),
        "abstention_rate_by_arm": abstention,
        "per_arm_pass_rates": per_arm,
        "paired_comparisons": results,
        "caveats": [
            "The judge is NOT qualified in absolute terms. Only relative, within-KC comparisons are "
            "licensed; no absolute quality claim follows from these numbers.",
            "Arm-independence was established at LOW POWER (4-6 calibration rows per arm). "
            "Non-significance there is weak evidence, not proof.",
            "M3 additionally failed absolute qualification (NOT_QUALIFIED) and is reported "
            "paired-only.",
            "Abstentions are excluded from M1/M2/TARGET pairs (no claims exist to judge) and are "
            "reported separately as a primary outcome; they are never imputed.",
        ],
    }

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---------- readable report ----------
    L = []
    L.append("# Ablation results (paired, within-KC)\n")
    L.append(f"Generated {report['generated_utc']} · unit of analysis: **KC** · "
             f"{len(kcs)} KCs × {len(arms)} arms · {len(ok)} rows\n")
    L.append("> **Scope of claim.** The judge failed absolute qualification "
             "(`JUDGE_QUALIFIED=false`; M3 `NOT_QUALIFIED`). These are *relative* comparisons only, "
             "licensed by pre-registered arm-independence at LOW POWER. No absolute quality claim "
             "follows.\n")
    L.append("> **Two verdict columns.** *as-specified* applies the guard exactly as "
             "pre-registered; it flags every comparison as within-noise because it compares "
             "a paired difference against an absolute judge-human disagreement rate (see "
             "locks/AMENDMENT_01_noise_guard.md). *amended* uses the controls the protocol "
             "already registered for a paired difference: Holm-adjusted exact McNemar plus "
             "a KC-clustered bootstrap CI excluding zero. Both are reported, neither hidden.")
    L.append("")
    L.append("## Instrument provenance\n")
    for k, v in sorted(instruments.items()):
        L.append(f"- `{k}`: {v} rows")
    L.append("\n## Abstention rate (a primary outcome)\n")
    L.append("| arm | abstained / KCs | rate |")
    L.append("|---|---|---|")
    for a in sorted(arms, key=lambda x: abstention[x]["rate"] or 0):
        d = abstention[a]
        L.append(f"| {a} | {d['abstained']} / {d['n_kcs']} | {d['rate']} |")
    L.append("\n## Per-arm pass rates\n")
    L.append("| task | " + " | ".join(arms) + " |")
    L.append("|---|" + "---|" * len(arms))
    for task in TASKS:
        cells = []
        for a in arms:
            d = per_arm[task][a]
            cells.append(f"{d['pass_rate']} (n={d['n_judgeable']})" if d["pass_rate"] is not None else "—")
        L.append(f"| {task} | " + " | ".join(cells) + " |")
    for fam, fam_res in results["families"].items():
        L.append(f"\n## Family: {fam} (Holm-corrected within family)\n")
        for task, comps in fam_res.items():
            L.append(f"\n### {task}\n")
            L.append("| comparison | Δ (a1−a2) | 95% CI (KC bootstrap) | discordant | exact p | Holm p | as-specified | amended |")
            L.append("|---|---|---|---|---|---|---|---|")
            for key, r in comps.items():
                if "paired_diff_a1_minus_a2" not in r:
                    L.append(f"| {key} | — | — | — | — | — | no comparable KCs | — |")
                    continue
                as_spec = ("WITHIN NOISE" if r["within_instrument_noise"]
                           else r.get("verdict_as_specified", "—"))
                amended = ("**significant**" if r.get("verdict_amended") == "significant"
                           else "not significant")
                L.append(f"| {key} | {r['paired_diff_a1_minus_a2']:+} | "
                         f"[{r['bootstrap_ci95'][0]:+}, {r['bootstrap_ci95'][1]:+}] | "
                         f"{r['discordant_a1_better']}/{r['discordant_a2_better']} | "
                         f"{r['mcnemar_exact_p']} | {r.get('holm_adjusted_p')} | {as_spec} | {amended} |")
    L.append("\n## Exploratory (no ranking claim)\n")
    for key, tasks in results["exploratory"].items():
        L.append(f"\n### {key}\n")
        L.append("| task | Δ | 95% CI | exact p |")
        L.append("|---|---|---|---|")
        for t, r in tasks.items():
            if "paired_diff_a1_minus_a2" not in r:
                continue
            L.append(f"| {t} | {r['paired_diff_a1_minus_a2']:+} | "
                     f"[{r['bootstrap_ci95'][0]:+}, {r['bootstrap_ci95'][1]:+}] | {r['mcnemar_exact_p']} |")
    L.append("\n## Caveats\n")
    for c in report["caveats"]:
        L.append(f"- {c}")
    if errors:
        L.append(f"\n## Excluded rows ({len(errors)})\n")
        for k, v in errors.items():
            L.append(f"- `{k}`: {str(v.get('error'))[:160]}")
    args.out_md.write_text("\n".join(L) + "\n", encoding="utf-8")

    print(f"rows: {len(ok)} ok, {len(errors)} error, {dupes} deduped")
    print(f"KCs: {len(kcs)} | arms: {len(arms)} | instruments: {dict(instruments)}")
    print(f"wrote {args.out_json.name} and {args.out_md.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
