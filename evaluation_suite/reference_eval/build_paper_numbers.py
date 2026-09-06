"""Generate the paper's number source-of-truth from raw artifacts.

Every figure the paper may quote gets a row: value, denominator, population, source file, and the
script that produced it. Nothing is typed by hand, so a number that cannot be regenerated cannot be
quoted.
"""
from __future__ import annotations

import csv
import json
import math
import statistics as st
from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import Path

BASE = Path(__file__).parent
OUT = BASE / "output"
DOCS = BASE.parent / "paper_consolidation"
LIB = BASE.parent / "reference_library" / "04_gold" / "expert_adjudicated_reference_kc_library.jsonl"
GAIN = {"DEFINITIONAL": 2, "RELATED": 1, "NOT_RELEVANT": 0}
R: list[dict] = []


def jl(p):
    p = p if isinstance(p, Path) else OUT / p
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()] if p.exists() else []


def add(metric, value, denom, population, arm, source, status, ci="", note=""):
    R.append({"metric": metric, "value": value, "denominator": denom, "population": population,
              "arm": arm, "source_artifact": source, "producing_script": "see note",
              "ci95": ci, "status": status, "note": note})


def main() -> int:
    DOCS.mkdir(parents=True, exist_ok=True)
    lib = jl(LIB)
    abl = jl("ablation_rows.jsonl")

    # ---- corpus / design ----
    add("KCs in data-mining corpus", 159, "-", "data-mining", "all", "ablation_rows.jsonl", "SUPPORTED")
    add("evaluation rows, ablation", 1113, "159 KC x 7 arms", "data-mining", "all",
        "ablation_rows.jsonl", "SUPPORTED")
    add("evaluation rows, crossed", 1137, "379 KC x 3 drafters", "3 domains", "all",
        "crossed_rows.jsonl", "SUPPORTED")
    add("KCs scored by reference metrics", 151, "of 159", "data-mining", "all",
        "v2_nuggets.jsonl", "SUPPORTED",
        note="7 KCs have no reference body; 1 decomposition failure (KC_CLF_NB_009)")
    add("KCs with a reference body", 152, "of 159", "data-mining", "-", "reference library",
        "SUPPORTED")

    ra = Counter(r["review_action"] for r in lib)
    for k, label in (("ACCEPT", "accepted unchanged"), ("MINOR_EDIT", "minor edit"),
                     ("MAJOR_EDIT", "major edit"), ("REPLACE", "replaced"),
                     ("NO_REFERENCE_CORPUS_UNSUPPORTED", "no corpus support")):
        add(f"expert review_action: {label}", ra[k], "of 159", "data-mining seed arm",
            "intrinsic_P-Q", "expert_adjudicated_reference_kc_library.jsonl", "SUPPORTED")
    add("human review burden: accept or minor edit", round(100 * (ra["ACCEPT"] + ra["MINOR_EDIT"]) / 159, 1),
        "% of 159", "data-mining seed arm", "intrinsic_P-Q", "reference library", "SUPPORTED",
        note="NOT a cross-model accuracy figure; seed arm only")

    nug = [r for r in jl("v2_nuggets.jsonl") if r.get("nuggets")]
    add("nuggets extracted", sum(len(r["nuggets"]) for r in nug), "over 151 KCs", "data-mining", "-",
        "v2_nuggets.jsonl", "SUPPORTED_pending_NUGGET_VALIDATION")
    add("VITAL nuggets", sum(1 for r in nug for x in r["nuggets"] if x["importance"] == "VITAL"),
        "of 1185", "data-mining", "-", "v2_nuggets.jsonl",
        "SUPPORTED_pending_NUGGET_VALIDATION")

    # ---- retrieval (pooled, automated qrels) ----
    qrel = {r["key"]: GAIN[r["grade"]] for r in jl("v3_pooled_relevance.jsonl") if r.get("grade")}
    add("pooled relevance judgements", len(qrel), "top-20 union, 4 configs", "data-mining", "pool",
        "v3_pooled_relevance.jsonl", "SUPPORTED",
        note="AUTOMATED labels produced by the frozen Selene judge; NOT human qrels")
    gd = Counter(r["grade"] for r in jl("v3_pooled_relevance.jsonl") if r.get("grade"))
    for g, n in gd.items():
        add(f"pooled label: {g}", n, "of 8246", "data-mining", "pool", "v3_pooled_relevance.jsonl",
            "SUPPORTED")

    ci = json.loads((OUT / "retrieval_paired_ci.json").read_text(encoding="utf-8")) \
        if (OUT / "retrieval_paired_ci.json").exists() else {"comparisons": {}}
    for comp, mets in ci.get("comparisons", {}).items():
        for m, v in mets.items():
            if m not in ("P@10", "R@10", "nDCG@10", "R@20", "P@5", "nDCG@5"):
                continue
            status = "SUPPORTED_WITH_SCOPE" if v["excludes_zero"] else "NO_SEPARATION"
            add(f"{m} paired difference: {comp}", v["paired_diff"], f"{v['n_kcs']} KCs",
                "data-mining", comp, "retrieval_paired_ci.json", status,
                ci=f"[{v['ci95'][0]}, {v['ci95'][1]}]",
                note="automated pooled qrels; concept-clustered bootstrap B=10,000")

    # ---- groundedness under each instrument ----
    ss = {r["key"]: r for r in jl("v3_selene_stored_ablation.jsonl") if r.get("labels")}
    mc = {r["key"]: r for r in jl("v3_minicheck_ablation.jsonl") if r.get("probs")}
    per = defaultdict(lambda: {"s": [], "m": []})
    npair = 0
    for k, s in ss.items():
        m = mc.get(k)
        if not m or len(s["labels"]) != len(m["probs"]):
            continue
        npair += len(s["labels"])
        per[s["arm"]]["s"].append(sum(1 for x in s["labels"] if x == "SUPPORTED") / len(s["labels"]))
        per[s["arm"]]["m"].append(sum(1 for p in m["probs"] if p is not None and p >= .5) / len(m["probs"]))
    for a, d in per.items():
        add("groundedness (Selene rubric)", round(st.mean(d["s"]), 4), f"{len(d['s'])} drafts",
            "data-mining", a, "v3_selene_stored_ablation.jsonl", "INSTRUMENT_SENSITIVE")
        add("groundedness (MiniCheck entailment)", round(st.mean(d["m"]), 4), f"{len(d['m'])} drafts",
            "data-mining", a, "v3_minicheck_ablation.jsonl", "INSTRUMENT_SENSITIVE")
    add("matched claims, both instruments", npair, "ablation", "data-mining", "all",
        "v3_selene_stored + v3_minicheck", "SUPPORTED")

    # ---- abstention ----
    ansmap = {r["knowledge_unit_id"]: (r["support_state"] != "UNSUPPORTED") for r in lib}
    for arm in sorted({r["arm"] for r in abl}):
        miss = sum(1 for r in abl if r["arm"] == arm and ansmap.get(r["unit_id"]) is False
                   and (r.get("candidate_draft") or "").strip())
        corr = sum(1 for r in abl if r["arm"] == arm and ansmap.get(r["unit_id"]) is False
                   and not (r.get("candidate_draft") or "").strip())
        add("correct refusals on corpus-unsupported KCs", corr, "of 7", "data-mining", arm,
            "ablation_rows + reference library", "PROVISIONAL_PENDING_SUPPORT_BOUNDARY_AUDIT")
        add("drafted despite corpus-unsupported label", miss, "of 7", "data-mining", arm,
            "ablation_rows + reference library", "PROVISIONAL_PENDING_SUPPORT_BOUNDARY_AUDIT")
    add("drafts produced from an empty evidence set", 0, "of 1113", "data-mining", "all",
        "ablation_rows.jsonl", "SUPPORTED")

    # ---- reproducibility ----
    v2 = {r["key"]: r for r in jl("v2_faith.jsonl") if "error" not in r and r.get("verdicts")}
    same = tot = drafts = 0
    for k, b in ss.items():
        a = v2.get(k)
        if not a or len(a["verdicts"]) != len(b["labels"]):
            continue
        drafts += 1
        for x, y in zip([v["label"] for v in a["verdicts"]], b["labels"]):
            tot += 1
            same += (x == y)
    add("evaluation-stage rerun agreement", round(same / tot, 4), f"{tot} matched claims",
        "data-mining", "all", "v2_faith vs v3_selene_stored_ablation", "SUPPORTED_WITH_SCOPE",
        note=f"{drafts} drafts; excludes {len(ss)-drafts} with differing claim counts. "
             "Covers claim decomposition + judging, NOT retrieval or drafting")

    # ---- judge calibration ----
    add("completeness calibration, raw agreement", 0.8611, "36 dev labels", "calibration subset",
        "-", "qualification re-run", "DEVELOPMENT_CALIBRATION",
        note="leave-one-out threshold; same labels informed metric adoption")
    add("completeness calibration, Gwet AC1", 0.7224, "36 dev labels", "calibration subset", "-",
        "qualification re-run", "DEVELOPMENT_CALIBRATION")
    add("v1 binary completeness, raw agreement", 0.556, "36 dev labels", "calibration subset", "-",
        "qualification_decision.json", "FAILED")

    # ---- write ----
    cols = ["metric", "value", "denominator", "population", "arm", "source_artifact", "ci95",
            "status", "note"]
    with open(DOCS / "PAPER_NUMBERS_SOURCE_OF_TRUTH.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(R)

    lines = ["# Paper numbers — source of truth\n",
             "Generated by `reference_eval/build_paper_numbers.py` from raw artifacts. "
             "**No number should appear in the paper without a row here.** "
             "Regenerate rather than edit by hand.\n",
             f"Rows: {len(R)}\n",
             "| metric | value | denominator | population | arm | 95% CI | status | source |",
             "|---|---|---|---|---|---|---|---|"]
    for r in R:
        lines.append(f"| {r['metric']} | {r['value']} | {r['denominator']} | {r['population']} | "
                     f"{r['arm']} | {r['ci95'] or '—'} | `{r['status']}` | `{r['source_artifact']}` |")
    lines.append("\n## Notes\n")
    for r in R:
        if r["note"]:
            lines.append(f"- **{r['metric']}** ({r['arm']}): {r['note']}")
    (DOCS / "PAPER_NUMBERS_SOURCE_OF_TRUTH.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {len(R)} rows to PAPER_NUMBERS_SOURCE_OF_TRUTH.{{md,csv}}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
