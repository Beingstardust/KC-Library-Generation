"""Three-way decoding comparison across the runs that differ ONLY in decoding configuration.

    penalty_free_previous : run 6's predecessor lineage, frequency_penalty absent
    penalty_0.2           : the run that carried frequency_penalty = 0.2
    penalty_free_final    : the frozen final configuration

DIAGNOSTIC ONLY. The final configuration is penalty-free because a nonzero frequency penalty acts
on generation logits and is therefore a demonstrated semantic confound - NOT because it produced
the highest sentinel accuracy. Nothing in this file may be used to select a configuration.

Emits penalty_decision_comparison.csv with one row per case whose primary verdict changed.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
from reference_judge_schema import M2_MATERIALLY_CORRECT  # noqa: E402

OUT = BASE / "output" / "penalty_decision_comparison.csv"

# Only ONE of these pairs isolates decoding. Stated explicitly so the comparison is not read as
# cleaner than it is:
#   penalty_0.2  vs  penalty_free_final   -> CLEAN. Identical schema (verdict-first, rationale
#                                            optional), identical prompts, identical sentinels.
#                                            The ONLY difference is frequency_penalty 0.2 -> 0.0.
#   penalty_free_previous                 -> CONFOUNDED. Penalty-free, but it predates the
#                                            rationale-optional change, so it differs in schema
#                                            shape as well. Included as lineage context only; do
#                                            not read a difference against it as a decoding effect.
RUNS = [
    ("penalty_free_previous", BASE / "output" / "selene_reference_sentinel_raw.PRE_FIELDORDER_FIX.json"),
    ("penalty_0.2", BASE / "output" / "selene_reference_sentinel_raw.json"),
    ("penalty_free_final", BASE / "output" / "selene_penalty_free_raw.json"),
]

CLEAN_PAIR = ("penalty_0.2", "penalty_free_final")
CONFOUNDED = {"penalty_free_previous": "predates the rationale-optional schema change; differs in "
                                        "schema shape as well as decoding"}

TASKS = {
    "M1": "m1", "M2": "m2", "M3": "m3_holistic",
    "TARGET": "target", "M4B_exploratory": "m4_holistic",
}


def derive(task_key, call):
    if not call or not call.get("contract_valid"):
        return None
    resp = call["response"]
    if task_key == "m1":
        return "PASS" if all(v["label"] == "SUPPORTED" for v in resp["verdicts"]) else "FAIL"
    if task_key == "m2":
        return "PASS" if all(v["label"] in M2_MATERIALLY_CORRECT for v in resp["verdicts"]) else "FAIL"
    if task_key == "m4_coverage":
        labs = [v["label"] for v in resp["verdicts"]]
        return round(sum(1 for l in labs if l == "SUPPORTED_BY_RETRIEVAL") / len(labs), 4) if labs else None
    return resp.get("label")


def main() -> int:
    loaded = {}
    for name, path in RUNS:
        if not path.exists():
            print(f"  (skipping {name}: {path.name} not present)")
            continue
        loaded[name] = {r["sentinel_id"]: r for r in json.loads(path.read_text(encoding="utf-8"))["results"]}

    if "penalty_free_final" not in loaded:
        print("REFUSED: the final penalty-free run is not present yet.")
        return 1

    names = [n for n, _ in RUNS if n in loaded]
    sids = sorted(loaded["penalty_free_final"])

    rows = []
    changed = Counter()
    totals = {n: Counter() for n in names}

    for task_label, task_key in TASKS.items():
        for sid in sids:
            verdicts = {}
            for n in names:
                r = loaded[n].get(sid)
                verdicts[n] = derive(task_key, r["calls"].get(task_key)) if r else None
            for n in names:
                if verdicts[n] is not None:
                    totals[n][f"{task_label}:{verdicts[n]}"] += 1
            distinct = {v for v in verdicts.values() if v is not None}
            if len(distinct) > 1:
                changed[task_label] += 1
                rows.append({
                    "sentinel_id": sid, "task": task_label,
                    **{n: (verdicts[n] if verdicts[n] is not None else "") for n in names},
                    "changed_between_penalty_and_final": (
                        "YES" if verdicts.get("penalty_0.2") != verdicts.get("penalty_free_final") else "no"
                    ),
                })

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["sentinel_id", "task"] + names + ["changed_between_penalty_and_final"])
        w.writeheader()
        w.writerows(rows)

    print(f"runs compared: {names}")
    print(f"CLEAN decoding-only pair: {CLEAN_PAIR[0]} vs {CLEAN_PAIR[1]}")
    for n, why in CONFOUNDED.items():
        if n in names:
            print(f"CONFOUNDED: {n} - {why}")
    print(f"\ncases whose primary verdict differs across configurations: {sum(changed.values())}")
    for t, c in changed.most_common():
        print(f"  {t}: {c}")

    print("\nverdict distribution per configuration:")
    for task_label in TASKS:
        line = f"  {task_label:<18}"
        for n in names:
            d = {k.split(':', 1)[1]: v for k, v in totals[n].items() if k.startswith(task_label + ":")}
            line += f" | {n}: {d}"
        print(line)

    print(f"\nwrote {OUT.name} ({len(rows)} changed rows)")
    print("\nDIAGNOSTIC ONLY - the penalty-free configuration was chosen because a nonzero frequency")
    print("penalty acts on generation logits and is a demonstrated semantic confound, not because")
    print("of its sentinel accuracy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
