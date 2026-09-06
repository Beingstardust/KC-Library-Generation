"""Compare Selene against MiniCheck on groundedness: agreement, and ranking stability.

The question this answers is NOT "which judge is right" - neither is ground truth. It is whether the
groundedness conclusions, which are what survived the v2/v3 campaign, depend on the choice of judge.
If an architecturally independent verifier reproduces the arm ordering, that is the strongest
reliability evidence available here. If it does not, the ordering was judge-specific and must be
reported as such.

Alignment is verified, not assumed: claim texts were re-extracted after the fact, so before comparing
anything the per-draft claim COUNT must match the count the original verdicts were recorded against.
Any mismatch means the indices do not line up and the row is excluded and reported.
"""
from __future__ import annotations

import json
import math
import statistics as st
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).parent
OUT = BASE / "output"
MC = BASE / "output"          # minicheck outputs are copied here
THRESH = 0.5                  # MiniCheck's own support/no-support decision point


def jl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()] if p.exists() else []


def main() -> int:
    selene = {r["key"]: r for r in jl(OUT / "v2_faith.jsonl") if "error" not in r}
    claims = {r["key"]: r for r in jl(OUT / "v3_claims_ablation.jsonl") if r.get("claims")}
    mc = {r["key"]: r for r in jl(MC / "v3_minicheck_ablation.jsonl") if r.get("probs")}

    print(f"selene rows {len(selene)} | claim rows {len(claims)} | minicheck rows {len(mc)}")

    aligned, misaligned = [], 0
    for k, m in mc.items():
        s = selene.get(k)
        c = claims.get(k)
        if not s or not c or s.get("abstained"):
            continue
        sv = s.get("verdicts") or []
        if not sv:
            continue
        # the alignment check that makes this comparison legitimate
        if len(sv) != len(c["claims"]) or len(m["probs"]) != len(sv):
            misaligned += 1
            continue
        for i, v in enumerate(sv):
            p = m["probs"][i]
            if p is None:
                continue
            aligned.append((k, m["arm"], v["label"] == "SUPPORTED", p >= THRESH, p))

    print(f"aligned claims: {len(aligned)} | drafts excluded for claim-count mismatch: {misaligned}")
    if not aligned:
        print("nothing to compare yet")
        return 0

    # ---- per-claim agreement ----
    tp = sum(1 for *_, s, m, _ in [(a[0], a[1], a[2], a[3], a[4]) for a in aligned] if s and m)
    both_sup = sum(1 for a in aligned if a[2] and a[3])
    both_not = sum(1 for a in aligned if not a[2] and not a[3])
    s_only = sum(1 for a in aligned if a[2] and not a[3])
    m_only = sum(1 for a in aligned if not a[2] and a[3])
    n = len(aligned)
    raw = (both_sup + both_not) / n
    # Gwet AC1
    pi = ((both_sup + s_only) / n + (both_sup + m_only) / n) / 2
    pe = 2 * pi * (1 - pi)
    ac1 = (raw - pe) / (1 - pe) if pe < 1 else 0.0
    # Cohen kappa
    ps = (both_sup + s_only) / n
    pm = (both_sup + m_only) / n
    pe_k = ps * pm + (1 - ps) * (1 - pm)
    kappa = (raw - pe_k) / (1 - pe_k) if pe_k < 1 else 0.0

    print()
    print("PER-CLAIM AGREEMENT, Selene vs MiniCheck")
    print(f"  both SUPPORTED      {both_sup}")
    print(f"  both NOT_SUPPORTED  {both_not}")
    print(f"  Selene only         {s_only}")
    print(f"  MiniCheck only      {m_only}")
    print(f"  raw agreement       {raw:.4f}")
    print(f"  Gwet AC1            {ac1:.4f}")
    print(f"  Cohen kappa         {kappa:.4f}")
    print(f"  Selene support rate    {(both_sup+s_only)/n:.4f}")
    print(f"  MiniCheck support rate {(both_sup+m_only)/n:.4f}")

    # ---- arm-level groundedness under each judge ----
    by = defaultdict(lambda: {"s": [0, 0], "m": [0, 0]})
    for _, arm, s, m, _ in aligned:
        by[arm]["s"][0] += int(s); by[arm]["s"][1] += 1
        by[arm]["m"][0] += int(m); by[arm]["m"][1] += 1
    print()
    print("ARM-LEVEL GROUNDEDNESS - does the ordering reproduce?")
    print(f"{'arm':<28}{'Selene':>9}{'MiniCheck':>11}{'delta':>9}")
    rows = []
    for a, d in by.items():
        sv = d["s"][0] / d["s"][1]; mv = d["m"][0] / d["m"][1]
        rows.append((a, sv, mv))
    for a, sv, mv in sorted(rows, key=lambda x: -x[1]):
        print(f"{a:<28}{sv:>9.4f}{mv:>11.4f}{mv-sv:>+9.4f}")

    # Spearman on the arm ordering
    if len(rows) > 2:
        def rank(vals):
            order = sorted(range(len(vals)), key=lambda i: vals[i])
            r = [0] * len(vals)
            for pos, i in enumerate(order):
                r[i] = pos
            return r
        rs = rank([x[1] for x in rows]); rm = rank([x[2] for x in rows])
        d2 = sum((a - b) ** 2 for a, b in zip(rs, rm))
        nn = len(rows)
        rho = 1 - 6 * d2 / (nn * (nn * nn - 1))
        print(f"\n  Spearman rank correlation of arm ordering: rho = {rho:+.4f}  (n={nn} arms)")
        agree_order = [x[0] for x in sorted(rows, key=lambda y: -y[1])] == \
                      [x[0] for x in sorted(rows, key=lambda y: -y[2])]
        print(f"  identical ordering: {agree_order}")

    json.dump({
        "n_aligned_claims": n, "misaligned_drafts": misaligned,
        "raw_agreement": round(raw, 4), "gwet_ac1": round(ac1, 4), "cohen_kappa": round(kappa, 4),
        "selene_support_rate": round((both_sup + s_only) / n, 4),
        "minicheck_support_rate": round((both_sup + m_only) / n, 4),
        "by_arm": {a: {"selene": round(s, 4), "minicheck": round(m, 4)} for a, s, m in rows},
    }, open(OUT / "second_judge_agreement.json", "w"), indent=2)
    print(f"\nwrote {OUT / 'second_judge_agreement.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
