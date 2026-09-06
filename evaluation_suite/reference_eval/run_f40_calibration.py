"""Measure the prompt-asymmetry offset between the two recall prompts (PREREG_F40_calibration.md).

Both prompts are shown the SAME content - the expert reference the nuggets were extracted from - so
the correct answer is 1.0 for both by construction. Whatever shortfall appears is the instrument's,
not any pipeline's, and the difference between the two shortfalls is the offset that currently
confounds the report's attribution gap.

Same frozen judge, decoding and blinding enforcement as every other v2 stage. Resumable: results
append to JSONL and completed keys are skipped.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

import nugget_schema as NS            # noqa: E402
import reference_judge_prompts as P   # noqa: E402
from run_reference_judge import call_and_validate  # noqa: E402

_lock = threading.Lock()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--rows", type=Path, required=True)
    ap.add_argument("--nuggets", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--concurrency", type=int, default=1)
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.rows, encoding="utf-8") if l.strip()]
    nuggets = {}
    for l in open(args.nuggets, encoding="utf-8"):
        if l.strip():
            r = json.loads(l)
            if r.get("nuggets"):
                nuggets[r["unit_id"]] = r["nuggets"]

    # one row per KC; the reference is identical across arms so the first occurrence serves
    by_kc = {}
    for r in rows:
        kc = r["unit_id"]
        if kc not in by_kc and kc in nuggets and (r.get("expert_reference") or "").strip():
            by_kc[kc] = r

    done = set()
    if args.out.exists():
        for l in open(args.out, encoding="utf-8"):
            if l.strip():
                try:
                    done.add(json.loads(l)["key"])
                except Exception:
                    pass

    todo = [(f"{kc}|{mode}", kc, row, mode)
            for kc, row in sorted(by_kc.items())
            for mode in ("assign", "context")
            if f"{kc}|{mode}" not in done]
    print(f"calibration: {len(by_kc)} KCs x 2 prompts, {len(todo)} todo", flush=True)

    def work(item):
        key, kc, row, mode = item
        ng = nuggets[kc]
        ref = row["expert_reference"].strip()
        rec = {"key": key, "unit_id": kc, "mode": mode, "n_nuggets": len(ng)}
        if mode == "assign":
            # the reference presented as a candidate description
            prompt = NS.build_nugget_assignment_prompt(ng, ref)
            schema = NS.nugget_assignment_schema(len(ng))
            task, labels = "NUGGET_ASSIGNMENT", NS.NUGGET_SUPPORT
        else:
            # the same reference presented as a single retrieved passage
            ev_block, _ = P.render_evidence([{"native_id": "ref", "text": ref}], "SRC")
            prompt = NS.build_context_recall_prompt(ng, ev_block)
            schema = NS.context_recall_schema(len(ng))
            task, labels = "CONTEXT_RECALL", NS.CONTEXT_PRESENCE
        out = call_and_validate(
            args.base_url, args.model, f"{key}:CALIB", prompt, schema,
            lambda r: NS.validate_assignment(r, task, labels, len(ng)), max_tokens=4000)
        rec["status"] = out["status"]
        if out.get("contract_valid"):
            rec["verdicts"] = out["response"]["verdicts"]
        return rec

    args.out.parent.mkdir(parents=True, exist_ok=True)
    n, consecutive_failures = 0, 0
    with open(args.out, "a", encoding="utf-8") as fh, \
            ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = {ex.submit(work, t): t for t in todo}
        for fut in as_completed(futs):
            try:
                rec = fut.result()
            except Exception as e:
                rec = {"key": futs[fut][0], "error": f"{type(e).__name__}: {e}"}
            with _lock:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
            n += 1
            # same dead-server guard as run_v2_metrics (F-41): a server that hit its time limit
            # otherwise looks like work completing very fast.
            if "CALL_FAILED" in str(rec.get("status", "")) or "error" in rec:
                consecutive_failures += 1
            else:
                consecutive_failures = 0
            if consecutive_failures >= 15:
                print(f"ABORTING: {consecutive_failures} consecutive call failures - server likely "
                      f"gone. {n}/{len(todo)} processed; re-run to resume.", flush=True)
                for f in futs:
                    f.cancel()
                break
            if n % 20 == 0:
                print(f"[{n}/{len(todo)}] {rec.get('key')}", flush=True)
    print(f"\ncalibration complete: {n} records -> {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
