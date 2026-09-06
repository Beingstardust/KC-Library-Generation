"""Test whether evidence-set SIZE depresses context recall (PREREG_F45_dilution.md).

Each synthetic evidence set provably contains every nugget - it holds the KC's own expert reference
- so ground truth is 1.0 at every dilution level. Any shortfall is the judge losing the content
among distractors, which is the confound that would make BaseDense's low context recall an artifact
of having 123 passages rather than of retrieving worse.

Distractors come from a DIFFERENT top-level cluster so they cannot accidentally supply the nuggets,
and the reference sits at a seeded random position so the result averages over serial position.
"""
from __future__ import annotations

import argparse
import json
import random
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
SEED = 20260831
LEVELS = [16, 32, 122]


def cluster_of(unit_id: str) -> str:
    """Top-level cluster, e.g. KC_CLF_NB_009 -> KC_CLF."""
    parts = unit_id.split("_")
    return "_".join(parts[:2]) if len(parts) >= 2 else unit_id


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

    by_kc = {}
    for r in rows:
        kc = r["unit_id"]
        if kc not in by_kc and kc in nuggets and (r.get("expert_reference") or "").strip():
            by_kc[kc] = r

    # distractor pool, indexed by the cluster the passage came from
    pool = {}
    for r in rows:
        cl = cluster_of(r["unit_id"])
        for e in r.get("candidate_system_evidence") or []:
            t = (e.get("text") or "").strip()
            if len(t) > 100:
                pool.setdefault(cl, {})[t] = True
    pool = {k: sorted(v) for k, v in pool.items()}
    print("distractor pool per cluster: "
          f"{ {k: len(v) for k, v in pool.items()} }", flush=True)

    done = set()
    if args.out.exists():
        for l in open(args.out, encoding="utf-8"):
            if l.strip():
                try:
                    done.add(json.loads(l)["key"])
                except Exception:
                    pass

    todo = [(f"{kc}|K{k}", kc, row, k)
            for kc, row in sorted(by_kc.items()) for k in LEVELS
            if f"{kc}|K{k}" not in done]
    print(f"dilution: {len(by_kc)} KCs x {len(LEVELS)} levels, {len(todo)} todo", flush=True)

    def work(item):
        key, kc, row, k = item
        ng = nuggets[kc]
        ref = row["expert_reference"].strip()
        rng = random.Random(f"{SEED}|{key}")
        # distractors from every cluster except this KC's own
        mine = cluster_of(kc)
        cand = [t for cl, ts in pool.items() if cl != mine for t in ts]
        rng.shuffle(cand)
        picked = cand[:k]
        pos = rng.randrange(len(picked) + 1)
        texts = picked[:pos] + [ref] + picked[pos:]
        items = [{"native_id": f"P{i+1}", "text": t} for i, t in enumerate(texts)]
        ev_block, _ = P.render_evidence(items, "SRC")
        rec = {"key": key, "unit_id": kc, "k_distractors": k, "n_passages": len(items),
               "ref_position": pos, "n_nuggets": len(ng)}
        out = call_and_validate(
            args.base_url, args.model, f"{key}:DILUTE",
            NS.build_context_recall_prompt(ng, ev_block), NS.context_recall_schema(len(ng)),
            lambda r: NS.validate_assignment(r, "CONTEXT_RECALL", NS.CONTEXT_PRESENCE, len(ng)),
            max_tokens=4000)
        rec["status"] = out["status"]
        if out.get("contract_valid"):
            rec["verdicts"] = out["response"]["verdicts"]
        return rec

    args.out.parent.mkdir(parents=True, exist_ok=True)
    n, fails = 0, 0
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
            if "CALL_FAILED" in str(rec.get("status", "")) or "error" in rec:
                fails += 1
            else:
                fails = 0
            if fails >= 15:
                print(f"ABORTING: {fails} consecutive failures - server likely gone. "
                      f"{n}/{len(todo)} done; re-run to resume.", flush=True)
                for f in futs:
                    f.cancel()
                break
            if n % 20 == 0:
                print(f"[{n}/{len(todo)}] {rec.get('key')}", flush=True)
    print(f"\ndilution complete: {n} records -> {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
