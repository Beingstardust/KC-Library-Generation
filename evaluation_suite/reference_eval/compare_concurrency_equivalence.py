"""Gate: does running the judge CONCURRENTLY change any verdict?

Compares the concurrent re-run of the 36 human-calibration rows against the sequential predictions
already produced from the same rows on the same server, same model, same decoding. The only
difference between the two runs is that concurrent execution lets different rows overlap in a batch.

Why this is not paranoia: vLLM batches whatever requests are in flight, and batch composition can
change matrix shapes and therefore floating-point reduction order. Under greedy decoding a
sufficiently near tie can then resolve differently. This project has already been bitten once by a
generation-time confound (frequency_penalty), so concurrency is verified rather than assumed.

Exit code 0 == EQUIVALENT (zero verdict differences), safe to run the ablation campaign
concurrently. Non-zero == DIVERGENT: do NOT use concurrency; fall back to sequential.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

TASKS = ["M1_faithfulness_per_claim", "M2_correctness_per_claim",
         "M3_core_completeness", "TARGET_ALIGNMENT"]


def load_any(p: Path, id_field: str):
    """Accepts either the {'results': [...]} JSON form or the resumable JSONL form."""
    txt = p.read_text(encoding="utf-8").strip()
    rows = []
    if txt.startswith("{") and '"results"' in txt[:200]:
        rows = json.loads(txt)["results"]
    else:
        for line in txt.splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return {r[id_field]: r for r in rows if id_field in r}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sequential", type=Path, required=True)
    ap.add_argument("--concurrent", type=Path, required=True)
    ap.add_argument("--id-field", default="review_case_id")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    for p in (args.sequential, args.concurrent):
        if not p.exists():
            print(f"REFUSED: missing {p}")
            return 2

    A = load_any(args.sequential, args.id_field)
    B = load_any(args.concurrent, args.id_field)
    common = sorted(set(A) & set(B))
    only_a, only_b = sorted(set(A) - set(B)), sorted(set(B) - set(A))

    diffs = []
    for rid in common:
        for t in TASKS:
            va, vb = A[rid].get(t), B[rid].get(t)
            if va != vb:
                diffs.append({"id": rid, "task": t, "sequential": va, "concurrent": vb})

    verdict = "EQUIVALENT" if (not diffs and not only_a and not only_b) else "DIVERGENT"
    report = {
        "verdict": verdict,
        "n_compared": len(common),
        "n_differences": len(diffs),
        "only_in_sequential": only_a,
        "only_in_concurrent": only_b,
        "differences": diffs,
        "tasks_compared": TASKS,
        "meaning": ("Concurrency changed no verdict; the concurrent runner may be used for the "
                    "ablation campaign." if verdict == "EQUIVALENT" else
                    "Concurrency changed at least one verdict. Do NOT use it - run sequentially."),
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"compared {len(common)} rows x {len(TASKS)} tasks")
    if only_a or only_b:
        print(f"  MISMATCHED ROW SETS: only_sequential={only_a} only_concurrent={only_b}")
    for d in diffs[:20]:
        print(f"  DIFF {d['id']} {d['task']}: sequential={d['sequential']} concurrent={d['concurrent']}")
    print(f"\nVERDICT: {verdict} ({len(diffs)} differences)")
    return 0 if verdict == "EQUIVALENT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
