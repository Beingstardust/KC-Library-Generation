"""Hardware/parallelism equivalence check: frozen ant2 tensor_parallel_size=4 (the pinned
instrument) vs the ant1 tensor_parallel_size=2 deviation, on the IDENTICAL 36-sentinel suite,
IDENTICAL decoding config, IDENTICAL prompts/schemas. The only difference is GPU count and
tensor_parallel_size.

This is an infrastructure equivalence check, not a rubric-tuning exercise: it exists to decide
whether ant1/TP2 predictions may be trusted as "the same instrument" before they are used for
judge qualification, per the disclosed, user-approved deviation from FINAL_JUDGE_DECODING_MANIFEST.json
(2026-08-28, forced by ant2 queue contention with no ETA).

Emits tp_equivalence_comparison.csv with one row per case whose primary verdict differs, and
prints a verdict: EQUIVALENT (zero differences) or DIVERGENT (report to user before use).
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
from reference_judge_schema import M2_MATERIALLY_CORRECT  # noqa: E402

OUT = BASE / "output" / "tp_equivalence_comparison.csv"

RUNS = [
    ("ant2_tp4_frozen", BASE / "output" / "selene_penalty_free_raw.json"),
    ("ant1_tp2_deviation", BASE / "output" / "selene_ant1_tp2_sentinel_raw.json"),
]

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
    return resp.get("label")


def main() -> int:
    loaded = {}
    for name, path in RUNS:
        if not path.exists():
            print(f"REFUSED: {name} missing ({path.name} not present)")
            return 1
        loaded[name] = {r["sentinel_id"]: r for r in json.loads(path.read_text(encoding="utf-8"))["results"]}

    names = [n for n, _ in RUNS]
    sids = sorted(set(loaded[names[0]]) & set(loaded[names[1]]))
    missing_a = set(loaded[names[0]]) - set(loaded[names[1]])
    missing_b = set(loaded[names[1]]) - set(loaded[names[0]])
    if missing_a or missing_b:
        print(f"WARNING: sentinel id sets differ. only in {names[0]}: {sorted(missing_a)}; "
              f"only in {names[1]}: {sorted(missing_b)}")

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
                })

    import csv
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["sentinel_id", "task"] + names)
        w.writeheader()
        w.writerows(rows)

    print(f"runs compared: {names}")
    print(f"sentinels compared: {len(sids)}")
    n_diff = sum(changed.values())
    print(f"\ncases whose primary verdict differs between ant2/TP4 and ant1/TP2: {n_diff}")
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
    if n_diff == 0:
        print("\nVERDICT: EQUIVALENT. Zero primary-verdict differences across all 36 sentinels and "
              "all tasks between ant2/TP4 (frozen) and ant1/TP2 (deviation). The ant1/TP2 calibration "
              "predictions may be used for qualification with this equivalence evidence attached.")
    else:
        print(f"\nVERDICT: DIVERGENT ({n_diff} differing verdicts). Do NOT use the ant1/TP2 calibration "
              "predictions for qualification without reporting this divergence to the user first — "
              "tensor_parallel_size is measurably not a safe deviation here.")
    return 0 if n_diff == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
