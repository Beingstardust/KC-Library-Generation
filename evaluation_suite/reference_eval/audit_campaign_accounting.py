"""Independently re-derive every count that appears in paper-facing documentation.

Written for the documentation-consolidation pass. Nothing here modifies an artifact; it reads raw
JSONL and reports expected vs observed so that any number quoted in the paper can be traced to a
file and a denominator. Discrepancies are printed, not silently reconciled.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

OUT = Path(__file__).parent / "output"
LIB = Path(__file__).parent.parent / "reference_library" / "04_gold" / "expert_adjudicated_reference_kc_library.jsonl"
rows_out: list[tuple] = []


def jl(p):
    p = OUT / p if not isinstance(p, Path) else p
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()] if p.exists() else []


def rec(label, expected, observed, note=""):
    ok = "OK" if (expected is None or expected == observed) else "MISMATCH"
    rows_out.append((label, expected if expected is not None else "-", observed, ok, note))


def main() -> int:
    abl = jl("ablation_rows.jsonl")
    crossed = jl("crossed_rows.jsonl")
    lib = jl(LIB)

    rec("ablation rows", 1113, len(abl))
    rec("ablation unique eval_row_id", 1113, len({r["eval_row_id"] for r in abl}))
    rec("ablation KCs", 159, len({r["unit_id"] for r in abl}))
    rec("ablation arms", 7, len({r["arm"] for r in abl}))
    rec("crossed rows", 1137, len(crossed))
    rec("crossed cells", 9, len({(r["domain"], r["drafter"]) for r in crossed}))

    # reference library
    rec("reference library KCs", 159, len(lib))
    ra = Counter(r["review_action"] for r in lib)
    rec("review_action ACCEPT", 117, ra["ACCEPT"])
    rec("review_action MINOR_EDIT", 10, ra["MINOR_EDIT"])
    rec("review_action MAJOR_EDIT", 15, ra["MAJOR_EDIT"])
    rec("review_action REPLACE", 10, ra["REPLACE"])
    rec("review_action NO_REFERENCE", 7, ra["NO_REFERENCE_CORPUS_UNSUPPORTED"])
    ss = Counter(r["support_state"] for r in lib)
    rec("support_state UNSUPPORTED", 7, ss["UNSUPPORTED"])
    rec("support_state PARTIALLY_SUPPORTED", 2, ss["PARTIALLY_SUPPORTED"])
    rec("support_state SUPPORTED", 150, ss["SUPPORTED"])
    withref = sum(1 for r in lib if (r.get("reference_text") or "").strip())
    rec("KCs with a reference body", 152, withref,
        "159 minus the 7 corpus-unsupported")

    # nuggets
    nug = jl("v2_nuggets.jsonl")
    withn = [r for r in nug if r.get("nuggets")]
    rec("nugget decomposition records", 152, len(nug))
    rec("KCs with nuggets (reference-scored)", 151, len(withn),
        "1 structural decomposition failure: KC_CLF_NB_009")
    tot = sum(len(r["nuggets"]) for r in withn)
    vit = sum(1 for r in withn for x in r["nuggets"] if x["importance"] == "VITAL")
    rec("total nuggets", 1185, tot)
    rec("VITAL nuggets", 475, vit)

    # judgement volumes
    rec("nugget assignment judgements", 1057, len(jl("v2_assign.jsonl")),
        "151 scored KCs x 7 arms; the 8 unscored KCs have no nuggets to assign")
    ctx = jl("v2_context.jsonl")
    rec("context judgements (KC x evidence-config)", 604, len(ctx))
    fth = jl("v2_faith.jsonl")
    fth_keys = {r["key"] for r in fth}
    rec("faithfulness records (incl. 1 superseded)", 1114, len(fth),
        "1 blinding-exempt row re-judged; both records retained")
    rec("faithfulness unique keys", 1113, len(fth_keys))
    rec("F-40 calibration calls", 302, len(jl("v2_f40_calib.jsonl")))
    rec("F-45 dilution calls", 453, len(jl("v2_f45_dilution.jsonl")))
    rec("F-46 faith-dilution records", 145, len(jl("v2_f46_faith_dilution.jsonl")))
    rec("pooled relevance judgements", 8246, len(jl("v3_pooled_relevance.jsonl")))
    rec("triage ablation", 1113, len(jl("v3_triage_ablation.jsonl")))
    rec("crossed groundedness", 1137, len(jl("v3_crossed_groundedness.jsonl")))

    # v3 claims and second judge
    ca = jl("v3_claims_ablation.jsonl")
    cc = jl("v3_claims_crossed.jsonl")
    rec("claim-extraction rows, ablation", 1113, len(ca))
    rec("claim-extraction rows, crossed", 1137, len(cc))
    n_abl_claims = sum(len(r["claims"]) for r in ca if r.get("claims"))
    n_cro_claims = sum(len(r["claims"]) for r in cc if r.get("claims"))
    rec("claims extracted, ablation", 7808, n_abl_claims)
    rec("claims extracted, crossed", None, n_cro_claims)

    mca = {r["key"]: r for r in jl("v3_minicheck_ablation.jsonl") if r.get("probs")}
    mcc = {r["key"]: r for r in jl("v3_minicheck_crossed.jsonl") if r.get("probs")}
    ssa = {r["key"]: r for r in jl("v3_selene_stored_ablation.jsonl") if r.get("labels")}
    ssc = {r["key"]: r for r in jl("v3_selene_stored_crossed.jsonl") if r.get("labels")}

    def matched(sel, mc):
        n = 0
        for k, s in sel.items():
            m = mc.get(k)
            if m and len(s["labels"]) == len(m["probs"]):
                n += len(s["labels"])
        return n

    rec("matched claims, ablation (both judges)", 7747, matched(ssa, mca))
    rec("matched claims, crossed (both judges)", 7914, matched(ssc, mcc))

    # rerun control denominator
    v2 = {r["key"]: r for r in fth if "error" not in r and r.get("verdicts")}
    same = 0
    drafts = 0
    skipped = 0
    for k, b in ssa.items():
        a = v2.get(k)
        if not a:
            skipped += 1
            continue
        if len(a["verdicts"]) != len(b["labels"]):
            skipped += 1
            continue
        drafts += 1
        same += len(b["labels"])
    rec("rerun-matched claims (denominator of 99.83%)", 7610, same,
        f"{drafts} drafts; {skipped} drafts excluded for claim-count mismatch")

    # scored-KC accounting
    vital_ok = {r["unit_id"] for r in withn
                if any(x["importance"] == "VITAL" for x in r["nuggets"])}
    rec("KCs scored by reference metrics", 151, len(vital_ok))

    print(f"{'quantity':<48}{'expected':>10}{'observed':>10}  {'status':<9} note")
    print("-" * 118)
    bad = 0
    for label, exp, obs, ok, note in rows_out:
        if ok == "MISMATCH":
            bad += 1
        print(f"{label:<48}{str(exp):>10}{obs:>10}  {ok:<9} {note}")
    print("-" * 118)
    print(f"{len(rows_out)} quantities checked, {bad} mismatch(es)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
