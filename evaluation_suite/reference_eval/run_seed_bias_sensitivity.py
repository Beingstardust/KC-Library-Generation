"""Seed-bias sensitivity analysis (partial substitute for the un-run control 6).

The expert reference library was SEEDED from the frozen Qwen drafts: the manifest's own string
comparison identifies `intrinsic_P-Q` as the seed arm (159/159 exact match; next closest arm 17/159),
and 117 of 159 references were accepted from the machine draft unchanged. `ANTI_ANCHORING_PROTOCOL.md`
control 6 specifies a seed-blind reconstruction audit to quantify the resulting bias; that audit was
NOT run (`05_seed_bias_audit/` is empty), and the protocol states that in its absence seed bias must
be reported as an unquantified limitation.

This provides a partial, purely observational substitute that needs no new annotation. The expert's
own adjudication stratifies the references by how much they still owe to the machine seed:

    ACCEPT   (117)  reference is the Qwen draft, unchanged
    CHANGED   (35)  MINOR_EDIT / MAJOR_EDIT / REPLACE - expert altered the content
    NO_REF     (7)  corpus-unsupported, excluded from scoring anyway

If Qwen's measured advantage is an artifact of the reference being derived from Qwen, that advantage
should be materially SMALLER on the CHANGED stratum, where the expert moved the reference away from
Qwen's text. If the advantage is stable across strata, seed provenance is a weaker explanation.

This does not rule seed bias in or out - a stratified comparison on 35 KCs cannot do that, and the
strata are not randomly assigned (the expert chose what to edit, plausibly editing worse drafts). It
is reported as evidence, with that non-randomness stated.
"""
from __future__ import annotations

import json
import random
import statistics as st
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).parent
OUT = BASE / "output"
LIB = BASE.parent / "reference_library" / "04_gold" / "expert_adjudicated_reference_kc_library.jsonl"
BOOT, SEED = 10000, 20260901
SEED_ARM = "intrinsic_P-Q"
COMPARATORS = ["intrinsic_P-G", "intrinsic_P-D", "extrinsic_B-Q", "extrinsic_DOS-Q"]
# extrinsic_P-Q is a different Qwen build (0.32 lexical overlap vs the seed arm's 0.81) but
# shares drafter AND retrieval with the seed, so it inherits the same CONTENT selection.
SEED_LINEAGE = ["intrinsic_P-Q", "extrinsic_P-Q"]
FAITH_PAIRS = [("extrinsic_DOS-Q", "extrinsic_B-Q"), ("extrinsic_DOS-Q", "extrinsic_P-Q"),
               ("intrinsic_P-G", "intrinsic_P-D"), ("intrinsic_P-Q", "intrinsic_P-D")]


def jl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def main() -> int:
    lib = {r["knowledge_unit_id"]: r for r in jl(LIB)}
    nug = {r["unit_id"]: r["nuggets"] for r in jl(OUT / "v2_nuggets.jsonl") if r.get("nuggets")}
    asg = {r["key"]: r for r in jl(OUT / "v2_assign.jsonl") if r.get("verdicts")}
    rows = {r["eval_row_id"]: r for r in jl(OUT / "ablation_rows.jsonl")}

    # vital-nugget recall per (arm, KC)
    per = defaultdict(dict)
    for rid, row in rows.items():
        kc, arm = row["unit_id"], row["arm"]
        ng = nug.get(kc)
        if not ng:
            continue
        vital = {i + 1 for i, x in enumerate(ng) if x["importance"] == "VITAL"}
        a = asg.get(rid)
        if not vital or not a:
            continue
        sup = sum(1 for v in a["verdicts"] if v["nugget_index"] in vital and v["label"] == "SUPPORTED")
        per[arm][kc] = sup / len(vital)

    strat = {}
    for kc in nug:
        act = (lib.get(kc) or {}).get("review_action")
        if act == "ACCEPT":
            strat[kc] = "ACCEPT"
        elif act in ("MINOR_EDIT", "MAJOR_EDIT", "REPLACE"):
            strat[kc] = "CHANGED"
    counts = {s: sum(1 for v in strat.values() if v == s) for s in ("ACCEPT", "CHANGED")}
    print(f"scored KCs by adjudication stratum: {counts}\n")

    rng = random.Random(SEED)

    def paired(a1, a2, keys):
        ks = [k for k in keys if k in per[a1] and k in per[a2]]
        if len(ks) < 8:
            return None
        d = [per[a1][k] - per[a2][k] for k in ks]
        boot = sorted(st.mean([d[rng.randrange(len(d))] for _ in range(len(d))]) for _ in range(BOOT))
        return {"n": len(ks), "diff": st.mean(d),
                "ci": [boot[int(.025 * BOOT)], boot[int(.975 * BOOT) - 1]]}

    print(f"Vital-nugget recall advantage of {SEED_ARM} (the SEED arm) over each comparator,\n"
          f"split by whether the expert left the reference as Qwen wrote it.\n")
    print(f"{'comparator':<20}{'ACCEPT (seeded)':>26}{'CHANGED (edited)':>26}{'shrinkage':>12}")
    results = {}
    for c in COMPARATORS:
        acc = paired(SEED_ARM, c, [k for k, s in strat.items() if s == "ACCEPT"])
        chg = paired(SEED_ARM, c, [k for k, s in strat.items() if s == "CHANGED"])
        if not acc or not chg:
            continue
        shrink = acc["diff"] - chg["diff"]
        results[c] = {"accept": acc, "changed": chg, "shrinkage": shrink}
        a = f"{acc['diff']:+.4f} [{acc['ci'][0]:+.3f},{acc['ci'][1]:+.3f}] n={acc['n']}"
        b = f"{chg['diff']:+.4f} [{chg['ci'][0]:+.3f},{chg['ci'][1]:+.3f}] n={chg['n']}"
        print(f"{c:<20}{a:>26}{b:>26}{shrink:>+12.4f}")

    # absolute level of the seed arm in each stratum, which is the more direct signal
    print()
    for arm in [SEED_ARM] + COMPARATORS:
        acc = [v for k, v in per[arm].items() if strat.get(k) == "ACCEPT"]
        chg = [v for k, v in per[arm].items() if strat.get(k) == "CHANGED"]
        if acc and chg:
            print(f"  {arm:<20} ACCEPT {st.mean(acc):.4f} (n={len(acc)})   "
                  f"CHANGED {st.mean(chg):.4f} (n={len(chg)})   drop {st.mean(acc)-st.mean(chg):+.4f}")

    # ---- the falsification test: a metric judged against EVIDENCE should be stratum-stable ----
    fth = {r["key"]: r for r in jl(OUT / "v2_faith.jsonl") if "error" not in r}
    fper = defaultdict(dict)
    for rid, row in rows.items():
        f = fth.get(rid)
        if not f or f.get("abstained"):
            continue
        vs = f.get("verdicts") or []
        if vs:
            fper[row["arm"]][row["unit_id"]] = sum(
                1 for x in vs if x["label"] == "SUPPORTED") / len(vs)

    def fpaired(a1, a2, keys):
        ks = [k for k in keys if k in fper[a1] and k in fper[a2]]
        if len(ks) < 8:
            return None
        d = [fper[a1][k] - fper[a2][k] for k in ks]
        b = sorted(st.mean([d[rng.randrange(len(d))] for _ in range(len(d))]) for _ in range(BOOT))
        return {"n": len(ks), "diff": round(st.mean(d), 4),
                "ci": [round(b[int(.025 * BOOT)], 4), round(b[int(.975 * BOOT) - 1], 4)]}

    print("\n\nFALSIFICATION TEST - per-claim faithfulness is judged against RETRIEVED EVIDENCE and")
    print("never against the reference, so if seed provenance is what drives the reversal above,")
    print("faithfulness comparisons should stay STABLE across the same two strata.\n")
    faith = {}
    for a1, a2 in FAITH_PAIRS:
        acc = fpaired(a1, a2, [k for k, s_ in strat.items() if s_ == "ACCEPT"])
        chg = fpaired(a1, a2, [k for k, s_ in strat.items() if s_ == "CHANGED"])
        if not acc or not chg:
            continue
        stable = (acc["diff"] > 0) == (chg["diff"] > 0)
        faith[f"{a1} vs {a2}"] = {"accept": acc, "changed": chg, "sign_stable": stable}
        print(f"  {a1} vs {a2}")
        print(f"      ACCEPT  {acc['diff']:+.4f} [{acc['ci'][0]:+.3f},{acc['ci'][1]:+.3f}] n={acc['n']}")
        print(f"      CHANGED {chg['diff']:+.4f} [{chg['ci'][0]:+.3f},{chg['ci'][1]:+.3f}] n={chg['n']}"
              f"   {'STABLE' if stable else 'REVERSES'}")

    (OUT / "seed_bias_sensitivity.json").write_text(
        json.dumps({"seed_arm": SEED_ARM, "seed_lineage": SEED_LINEAGE,
                    "strata_counts": counts, "nugget_recall_comparisons": results,
                    "faithfulness_stratum_stability": faith,
                    "caveat": "Strata are NOT randomly assigned - the expert chose which drafts to "
                              "edit, plausibly editing the weaker ones, which would depress the "
                              "seed arm's CHANGED-stratum score for reasons unrelated to seeding. "
                              "This analysis is evidence, not a substitute for the un-run "
                              "seed-blind reconstruction audit (control 6)."},
                   indent=2), encoding="utf-8")
    print(f"\nwrote {OUT / 'seed_bias_sensitivity.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
