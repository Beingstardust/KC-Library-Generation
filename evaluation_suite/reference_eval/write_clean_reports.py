"""Render the clean-rerun markdown reports from reference_based_sentinel_results_clean.json.

Produces:
    reference_based_sentinel_report_clean.md
    target_clean_report.md

Both keep DEVELOPMENT SENTINEL PERFORMANCE strictly separate from FORMAL HUMAN JUDGE
QUALIFICATION. The sentinel run is never described as a qualification pass.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
from reference_judge_schema import METRIC_SCOPE  # noqa: E402

RESULTS = BASE / "output" / "penalty_free_sentinel_results.json"
OUT_MAIN = BASE / "output" / "penalty_free_sentinel_report.md"
OUT_TARGET = BASE / "output" / "target_clean_report.md"

PRETTY = {
    "M1_EVIDENCE_FAITHFULNESS": "M1 — evidence faithfulness",
    "M2_REFERENCE_SOURCE_CORRECTNESS": "M2 — reference/source correctness",
    "M3_CORE_COMPLETENESS": "M3 — holistic core completeness",
    "M4_RETRIEVAL_REFERENCE_COVERAGE": "M4A — reference-claim retrieval recall",
    "EXPLORATORY_HOLISTIC_EVIDENCE_ADEQUACY": "M4B — holistic evidence adequacy (EXPLORATORY)",
    "TARGET_ALIGNMENT": "TARGET — alignment",
}


def pct(x):
    return "n/a" if x is None else f"{x:.1%}"


def num(x, nd=3):
    return "n/a" if x is None else f"{x:.{nd}f}"


def main() -> int:
    r = json.loads(RESULTS.read_text(encoding="utf-8"))
    struct, sem = r["structural"], r["semantic"]

    L = []
    L.append("# Reference-Based Sentinel Run — Clean Results\n")
    L.append("> **DEVELOPMENT SENTINEL PERFORMANCE.** This is not a judge qualification pass. "
             "The 36 sentinels are development unit tests that check whether the evaluator measures "
             "the intended construct. Formal qualification happens only against human-labelled "
             "calibration data — see `../../paper_methods/LLM_JUDGE_VALIDATION_METHOD.md`.\n")
    L.append(f"- **Judge model:** `{r['model']}`")
    L.append(f"- **Sentinels:** {r['n_sentinels']}  ({', '.join(f'{k} {v}' for k, v in r['case_types'].items())})")
    L.append(f"- **Gold source:** `{r['gold_source']}`   **Predictions:** `{r['predictions_source']}`")
    L.append(f"- Gold and predictions are read from separate files, so a gold revision recomputes "
             f"aggregates **without rerunning inference**.\n")

    # ---- structural ----
    L.append("## Structural and contract validity\n")
    L.append("| Task | Calls | Structural | Contract | Truncated | Invalid | Call failed |")
    L.append("|---|---|---|---|---|---|---|")
    for k, v in struct.items():
        if not v.get("n_calls"):
            continue
        L.append(f"| {PRETTY.get(k, k)} | {v['n_calls']} | {pct(v['structural_validity_rate'])} | "
                 f"{pct(v['contract_validity_rate'])} | {v['truncation_count']} | "
                 f"{v['invalid_output_count']} | {v['call_failed_count']} |")
    L.append("")

    # ---- semantic: binary tasks ----
    L.append("## Semantic agreement — primary binary tasks\n")
    L.append("Agreement is computed on **resolved gold only**; `GOLD_PENDING` cases are excluded "
             "from agreement and reported separately rather than guessed.\n")
    L.append("| Task | Scope | n valid | Agreement | PASS prec | PASS rec | FAIL prec | FAIL rec | false PASS | false FAIL | NOT_JUDGEABLE | gold pending |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for k, v in sem.items():
        if v["kind"] != "binary":
            continue
        scope = "primary" if METRIC_SCOPE[k]["primary_use"] else "**exploratory**"
        pm, fm = v["pass_metrics"], v["fail_metrics"]
        L.append(f"| {PRETTY.get(k, k)} | {scope} | {v['n_valid_semantic']} | "
                 f"{pct(v['agreement_resolved_only'])} | {pct(pm['precision'])} | {pct(pm['recall'])} | "
                 f"{pct(fm['precision'])} | {pct(fm['recall'])} | {v['n_false_pass']} | "
                 f"{v['n_false_fail']} | {v['not_judgeable_predictions']} | {v['n_gold_pending']} |")
    L.append("")

    # ---- M4A continuous ----
    m4a = sem.get("M4_RETRIEVAL_REFERENCE_COVERAGE")
    if m4a and m4a["kind"] == "continuous":
        L.append("## M4A — reference-claim retrieval recall (primary retrieval diagnostic)\n")
        L.append(f"- **n computable:** {m4a['n_computable']}")
        L.append(f"- **mean recall:** {num(m4a['mean'])}   **median:** {num(m4a['median'])}")
        L.append(f"- **range:** {num(m4a['min'])} – {num(m4a['max'])}")
        L.append(f"- **at 1.0:** {m4a['n_at_1.0']}   **below 1.0:** {m4a['n_below_1.0']}\n")
        L.append(f"> {m4a['interpretation_guard']}\n")

    # ---- confusion matrices ----
    L.append("## Confusion matrices\n")
    for k, v in sem.items():
        if v["kind"] != "binary" or not v["confusion_matrix"]:
            continue
        L.append(f"**{PRETTY.get(k, k)}**\n")
        L.append("| expected → actual | count |")
        L.append("|---|---|")
        for cell, c in v["confusion_matrix"].items():
            L.append(f"| {cell} | {c} |")
        L.append("")

    # ---- mismatches ----
    L.append("## Mismatches\n")
    for k, v in sem.items():
        if v["kind"] != "binary" or not v["mismatches"]:
            continue
        L.append(f"**{PRETTY.get(k, k)}** ({len(v['mismatches'])})\n")
        for m in v["mismatches"]:
            L.append(f"- `{m['sentinel_id']}` expected **{m['expected']}**, got **{m['actual']}**")
        L.append("")

    # ---- pending ----
    pend = sorted({s for v in sem.values() if v["kind"] == "binary" for s in v.get("gold_pending_ids", [])})
    L.append("## Gold-pending cases\n")
    if pend:
        L.append(f"{len(pend)} sentinel(s) carry a disputed criterion awaiting project-owner "
                 f"adjudication: {', '.join(f'`{s}`' for s in pend)}.\n")
        L.append("They remain in the 36-case suite and their other criteria score normally; only the "
                 "disputed criterion is held as `GOLD_PENDING` and excluded from agreement. "
                 "Full case packages: `pending_sentinel_adjudication.json`.\n")
        L.append("No aggregate in this report was computed from a guessed label.\n")
    else:
        L.append("None.\n")

    # ---- decomposition ----
    dq, cc = r["decomposition_quality"], r["claim_counts"]
    L.append("## Claim decomposition\n")
    L.append(f"- candidate claims: **{cc['candidate_total']}**   reference claims: **{cc['reference_total']}**")
    L.append(f"- structural problems: candidate {dq['candidate_problems']}, reference {dq['reference_problems']}")
    L.append("- Structural checks only (parent_span must be a literal substring; formula relations must "
             "survive splitting; gross under-coverage flagged). Bounded **human** validation of the "
             "decomposition is still required before final results are opened.\n")

    # ---- scope ----
    L.append("## Metric scope\n")
    L.append("| Task | primary_use | qualification_gate | derived_metric_dependency |")
    L.append("|---|---|---|---|")
    for k in sem:
        sc = METRIC_SCOPE[k]
        L.append(f"| {PRETTY.get(k, k)} | {sc['primary_use']} | {sc['qualification_gate']} | {sc['derived_metric_dependency']} |")
    L.append("")
    L.append("`materially_sound` excludes **both** M4 outputs. It measures the final KC draft; retrieval "
             "coverage explains that outcome rather than defining it.\n")
    L.append("---\n")
    L.append("**Next step is human calibration, not system evaluation.** No intrinsic or extrinsic "
             "comparison has been run and no candidate ranking has been inspected.")

    OUT_MAIN.write_text("\n".join(L), encoding="utf-8")

    # ---------------- TARGET-specific report ----------------
    t = sem["TARGET_ALIGNMENT"]
    ts = struct["TARGET_ALIGNMENT"]
    T = []
    T.append("# TARGET Alignment — First Clean Estimate\n")
    T.append("> The previous TARGET figure was computed on a truncation-reduced subset and must not be "
             "interpreted. This is the first estimate from a run in which the structured-output defect "
             "was fixed, and it supersedes it entirely.\n")
    T.append("## Task (frozen)\n")
    T.append("*Does the candidate's central defining content describe the same KC represented by the "
             "expert-adjudicated reference?*\n")
    T.append("Labels: `TARGET_ALIGNED` / `WRONG_TARGET` / `NOT_JUDGEABLE`. Inputs: target KC, hierarchy, "
             "expert reference, relevant expert authority, candidate draft.\n")
    T.append("The retired v3 extract-subject → SAME/DIFFERENT mechanism is **not** reinstated, and "
             "lexical overlap is explicitly not the basis for the judgment.\n")
    T.append("## Structural\n")
    T.append(f"- calls: **{ts['n_calls']}**")
    T.append(f"- structural validity: **{pct(ts['structural_validity_rate'])}**")
    T.append(f"- contract validity: **{pct(ts['contract_validity_rate'])}**")
    T.append(f"- truncated: **{ts['truncation_count']}**   invalid: **{ts['invalid_output_count']}**\n")
    T.append("## Semantic\n")
    pm, fm = t["pass_metrics"], t["fail_metrics"]
    T.append(f"- valid semantic cases: **{t['n_valid_semantic']}**")
    T.append(f"- agreement (resolved gold only): **{pct(t['agreement_resolved_only'])}**")
    T.append(f"- ALIGNED precision / recall: **{pct(pm['precision'])}** / **{pct(pm['recall'])}**")
    T.append(f"- WRONG_TARGET precision / recall: **{pct(fm['precision'])}** / **{pct(fm['recall'])}**")
    T.append(f"- false PASS (wrong target accepted as aligned): **{t['n_false_pass']}** {t['false_pass']}")
    T.append(f"- false FAIL (aligned rejected as wrong target): **{t['n_false_fail']}** {t['false_fail']}")
    T.append(f"- NOT_JUDGEABLE predictions: **{t['not_judgeable_predictions']}**\n")
    T.append("### Confusion matrix\n")
    T.append("| expected → actual | count |")
    T.append("|---|---|")
    for cell, c in t["confusion_matrix"].items():
        T.append(f"| {cell} | {c} |")
    T.append("")
    if t["mismatches"]:
        T.append("### Mismatches\n")
        for m in t["mismatches"]:
            T.append(f"- `{m['sentinel_id']}` expected **{m['expected']}**, got **{m['actual']}**")
        T.append("")
    T.append("## Readiness\n")
    T.append("The decisive quantity for a target-alignment task is **false PASS** — a wrong-target draft "
             "accepted as aligned — because being correct about the wrong concept is the failure this "
             "task exists to catch.\n")
    T.append(f"Observed false PASS: **{t['n_false_pass']}**; WRONG_TARGET recall: **{pct(fm['recall'])}**.\n")
    T.append("No tuning was applied to this task, and none may be applied against `SENT_032`/`SENT_033` "
             "while their gold status is unresolved. If a genuinely severe generic failure is present, "
             "the correct response is to stop and revisit the task definition — not to prompt-tune it.\n")
    T.append("This remains development evidence. TARGET is qualified only against human labels.")

    OUT_TARGET.write_text("\n".join(T), encoding="utf-8")

    print(f"wrote {OUT_MAIN.name}")
    print(f"wrote {OUT_TARGET.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
