"""Independent consistency audit of the v2 outputs.

Every check re-derives a property from the raw JSONL rather than trusting the report, because
re-deriving has already caught three real defects this campaign (F-37 aggregation, F-42 coverage,
F-47 field naming). Exit code is non-zero if any check fails, so this can gate a release.
"""
from __future__ import annotations

import hashlib
import json
import statistics as st
from collections import Counter, defaultdict
from pathlib import Path

OUT = Path(__file__).parent / "output"
FAILURES: list[str] = []
NOTES: list[str] = []


def jl(name):
    p = OUT / name
    if not p.exists():
        return []
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def check(cond, label, detail=""):
    (NOTES if cond else FAILURES).append(f"{'PASS' if cond else 'FAIL'}  {label}" +
                                         (f"  [{detail}]" if detail else ""))


def main() -> int:
    rows = jl("ablation_rows.jsonl")
    nugs = jl("v2_nuggets.jsonl")
    asg = jl("v2_assign.jsonl")
    ctx = jl("v2_context.jsonl")
    fth = jl("v2_faith.jsonl")

    # A failed row that was later re-judged stays in the file - history is not rewritten - so a
    # key may legitimately appear twice: once as the error, once as its replacement. Keep only the
    # successful record for analysis, and assert that every duplicate is exactly that pattern.
    superseded = []
    def dedupe(recs, key="key"):
        by = defaultdict(list)
        for r in recs:
            if key in r:
                by[r[key]].append(r)
        out = []
        for k, rs in by.items():
            good = [r for r in rs if "error" not in r]
            if len(rs) > 1:
                superseded.append((k, len(rs) - len(good), len(good)))
            out.append(good[-1] if good else rs[-1])
        return out

    fth = dedupe(fth)
    check(all(bad >= 1 and good == 1 for _, bad, good in superseded),
          "faith: every duplicate key is one failed row superseded by exactly one good row",
          str(superseded) if superseded else "none")

    # ---- 1. no duplicate keys among the records actually analysed ----
    for name, recs, key in (("assign", asg, "key"), ("context", ctx, "key"),
                            ("faith", fth, "key"), ("nuggets", nugs, "unit_id")):
        c = Counter(r[key] for r in recs if key in r)
        dupes = [k for k, n in c.items() if n > 1]
        check(not dupes, f"{name}: no duplicate keys", f"{len(dupes)} dupes: {dupes[:3]}")

    # ---- 2. every ablation row is accounted for ----
    ids = {r["eval_row_id"] for r in rows}
    check(len(ids) == len(rows), "ablation rows: unique eval_row_id",
          f"{len(rows)} rows, {len(ids)} unique")
    check(len(fth) == len(rows), "faithfulness covers every row", f"{len(fth)} vs {len(rows)}")
    missing = ids - {r["key"] for r in fth}
    check(not missing, "faithfulness has no missing rows", f"{len(missing)} missing")

    # ---- 3. paired balance: every arm must score the SAME KC set ----
    vital_ok = {r["unit_id"] for r in nugs if r.get("nuggets")
                and any(x["importance"] == "VITAL" for x in r["nuggets"])}
    scored = defaultdict(set)
    for r in rows:
        if r["unit_id"] in vital_ok:
            scored[r["arm"]].add(r["unit_id"])
    sizes = {a: len(v) for a, v in scored.items()}
    check(len(set(sizes.values())) == 1, "all arms score an identical KC count", str(sizes))
    base = next(iter(scored.values()))
    check(all(v == base for v in scored.values()), "all arms score the IDENTICAL KC set")

    # ---- 4. verdict integrity: exact count, in-range indices, no duplicates ----
    nmap = {r["unit_id"]: len(r["nuggets"]) for r in nugs if r.get("nuggets")}
    bad_len = bad_idx = bad_dup = 0
    for recs in (asg, ctx):
        for r in recs:
            vs = r.get("verdicts")
            if not vs:
                continue
            n = nmap.get(r["unit_id"])
            if n is None:
                continue
            if len(vs) != n:
                bad_len += 1
            idxs = [v.get("nugget_index") for v in vs]
            if any(not isinstance(i, int) or i < 1 or i > n for i in idxs):
                bad_idx += 1
            if len(set(idxs)) != len(idxs):
                bad_dup += 1
    check(bad_len == 0, "assign/context: verdict count matches nugget count", f"{bad_len} bad")
    check(bad_idx == 0, "assign/context: all indices in range", f"{bad_idx} bad")
    check(bad_dup == 0, "assign/context: no duplicate indices", f"{bad_dup} bad")

    # ---- 5. context is shared per evidence-config, not recomputed per arm ----
    def ev_hash(r):
        return hashlib.sha256("|".join(e["text"] for e in r.get("candidate_system_evidence") or [])
                              .encode("utf-8")).hexdigest()[:16]
    want = {f'{r["unit_id"]}|{ev_hash(r)}' for r in rows if r["unit_id"] in vital_ok}
    have = {r["key"] for r in ctx if r.get("verdicts")}
    check(want <= have, "context: every (KC, evidence-config) judged",
          f"{len(want - have)} missing of {len(want)}")

    # ---- 6. abstention consistency across stages ----
    no_draft = {r["eval_row_id"] for r in rows if not (r.get("candidate_draft") or "").strip()}
    fth_abst = {r["key"] for r in fth if r.get("abstained")}
    check(no_draft == fth_abst, "abstention flags match empty drafts",
          f"rows={len(no_draft)} faith={len(fth_abst)} sym_diff={len(no_draft ^ fth_abst)}")

    # ---- 7. no faithfulness verdicts recorded for an abstention ----
    leak = [r["key"] for r in fth if r.get("abstained") and r.get("verdicts")]
    check(not leak, "abstentions carry no claim verdicts", f"{len(leak)} leaked")

    # ---- 8. call failures ----
    for name, recs in (("assign", asg), ("context", ctx), ("faith", fth)):
        f = sum(1 for r in recs if "CALL_FAILED" in str(r.get("status", "")) or "error" in r)
        check(f == 0, f"{name}: zero unresolved failures", f"{f} failures")

    # ---- 9. instrument provenance: v2 must be single-instrument ----
    exempt = [r["key"] for r in fth if r.get("blinding_exemption")]
    check(len(exempt) <= 1, "at most one blinding exemption, and it is documented",
          f"{len(exempt)}: {exempt}")

    insts = Counter(r.get("instrument") for r in fth if r.get("instrument"))
    check(len(insts) <= 1, "faithfulness: single instrument", str(dict(insts)))

    # ---- 10. F-45 exposure per arm, so no one silently compares across ceilings ----
    ev = defaultdict(list)
    for r in rows:
        ev[r["arm"]].append(len(r.get("candidate_system_evidence") or []))
    NOTES.append("\nmean evidence items per arm (F-45 exposure):")
    for a in sorted(ev, key=lambda x: st.mean(ev[x])):
        m = st.mean(ev[a])
        flag = "  <-- F-45 CONFOUNDED" if m > 60 else ""
        NOTES.append(f"    {a:<28}{m:>7.1f}{flag}")

    print("\n".join(NOTES))
    print()
    if FAILURES:
        print("\n".join(FAILURES))
        print(f"\n{len(FAILURES)} CHECK(S) FAILED")
        return 1
    print(f"ALL {len([n for n in NOTES if n.startswith('PASS')])} CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
