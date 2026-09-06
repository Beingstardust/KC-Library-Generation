"""Does evidence-set size depress per-claim FAITHFULNESS as it does context recall (F-45)?

F-45 showed the context-recall judge loses content placed late in a 123-passage set. Faithfulness is
judged against the same evidence sets, so the same failure would depress any arm with a large
retrieval budget - and BaseDense (123.1 passages) is exactly that arm. The reported
"DOS-RAG more faithful than BaseDense" result (Holm p = 0.0006) would then be an artifact.

Controlled paired design: decompose each draft's claims ONCE, then judge those same claims twice -
against the arm's own evidence, and against that same evidence padded to 123 passages with
topically-separated distractors. Only the padding differs, so any change is the set-size effect.
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

import reference_judge_prompts as P   # noqa: E402
import reference_judge_schema as S    # noqa: E402
from run_reference_judge import call_and_validate  # noqa: E402

_lock = threading.Lock()
SEED = 20260831
TARGET_PASSAGES = 123   # BaseDense's mean evidence size
ARM = "intrinsic_P-Q"   # 17.2 passages, F-45 ceiling 1.0000 -> clean starting point


def cluster_of(unit_id: str) -> str:
    parts = unit_id.split("_")
    return "_".join(parts[:2]) if len(parts) >= 2 else unit_id


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--rows", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--concurrency", type=int, default=1)
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.rows, encoding="utf-8") if l.strip()]

    pool = {}
    for r in rows:
        cl = cluster_of(r["unit_id"])
        for e in r.get("candidate_system_evidence") or []:
            t = (e.get("text") or "").strip()
            if len(t) > 100:
                pool.setdefault(cl, {})[t] = True
    pool = {k: sorted(v) for k, v in pool.items()}

    targets = [r for r in rows if r["arm"] == ARM
               and (r.get("candidate_draft") or "").strip()
               and (r.get("candidate_system_evidence") or [])]

    done = set()
    if args.out.exists():
        for l in open(args.out, encoding="utf-8"):
            if l.strip():
                try:
                    done.add(json.loads(l)["key"])
                except Exception:
                    pass
    todo = [r for r in targets if r["unit_id"] not in done]
    print(f"faith-dilution: {len(targets)} {ARM} rows, {len(todo)} todo", flush=True)

    def work(row):
        kc = row["unit_id"]
        rec = {"key": kc, "unit_id": kc, "arm": ARM}
        draft = row["candidate_draft"].strip()
        dec = call_and_validate(
            args.base_url, args.model, f"{kc}:FD_DECOMPOSE",
            P.build_decomposition_prompt(draft, "candidate_draft"), S.decomposition_schema(),
            lambda r: r.get("task") == "CLAIM_DECOMPOSITION" or (_ for _ in ()).throw(
                S.JudgeSchemaError(f"expected CLAIM_DECOMPOSITION, got {r.get('task')!r}")),
            max_tokens=4000)
        if not dec.get("contract_valid"):
            rec["status"] = f"DECOMPOSE_{dec['status']}"
            return rec
        claims = [{"text": c["text"]} for c in dec["response"]["claims"]]
        if not claims:
            rec["status"] = "NO_CLAIMS"
            return rec
        rec["n_claims"] = len(claims)

        own = [{"native_id": e["id"], "text": e["text"]}
               for e in row.get("candidate_system_evidence") or []]
        rng = random.Random(f"{SEED}|{kc}|faith")
        mine = cluster_of(kc)
        cand = [t for cl, ts in pool.items() if cl != mine for t in ts]
        rng.shuffle(cand)
        need = max(0, TARGET_PASSAGES - len(own))
        distract = [{"native_id": f"D{i+1}", "text": t} for i, t in enumerate(cand[:need])]
        # interleave at seeded random positions so the real evidence is not all at the front
        padded = list(distract)
        for it in own:
            padded.insert(rng.randrange(len(padded) + 1), it)

        for label, items in (("own", own), ("padded", padded)):
            blk, _ = P.render_evidence(items, "SRC")
            m1 = call_and_validate(
                args.base_url, args.model, f"{kc}:FD_M1_{label}",
                P.build_m1_prompt(claims, blk), S.m1_faithfulness_schema(len(claims)),
                lambda r: S.validate_per_claim_response(
                    r, "M1_EVIDENCE_FAITHFULNESS", S.M1_FAITHFULNESS_LABELS, len(claims)))
            rec[f"{label}_status"] = m1["status"]
            rec[f"{label}_n_passages"] = len(items)
            if m1.get("contract_valid"):
                rec[f"{label}_verdicts"] = m1["response"]["verdicts"]
        rec["status"] = "OK"
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
                rec = {"key": futs[fut]["unit_id"], "error": f"{type(e).__name__}: {e}"}
            with _lock:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
            n += 1
            if "CALL_FAILED" in str(rec.get("status", "")) or "error" in rec:
                fails += 1
            else:
                fails = 0
            if fails >= 15:
                print(f"ABORTING: {fails} consecutive failures. {n}/{len(todo)} done.", flush=True)
                for f in futs:
                    f.cancel()
                break
            if n % 20 == 0:
                print(f"[{n}/{len(todo)}] {rec.get('key')}", flush=True)
    print(f"\nfaith-dilution complete: {n} records -> {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
