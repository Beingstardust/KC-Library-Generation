"""Re-judge groundedness with Selene using the EXACT claims that were stored and given to MiniCheck.

Why this exists. The v2 faithfulness stage discarded its claim texts, so comparing MiniCheck against
those old verdicts would rely on index alignment to claims nobody can inspect. Measured, that
alignment is only 97.98%: re-extraction produces a different claim COUNT for ~2% of drafts, because
`VLLM_BATCH_INVARIANT` is not enabled on this server and decomposition is therefore not bit-
reproducible across runs (F-06/F-07). Even where counts agree, text identity is unverifiable.

Running Selene over the stored claims removes the assumption entirely: both judges then see the
same claim strings and the same evidence, so any disagreement is instrument difference and nothing
else.

Side benefit: comparing these verdicts against the v2 ones measures the instrument's own run-to-run
reproducibility on identical inputs, which is worth knowing given batch invariance is off.
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

import reference_judge_prompts as P   # noqa: E402
import reference_judge_schema as S    # noqa: E402
from run_reference_judge import call_and_validate  # noqa: E402

_lock = threading.Lock()
EXEMPT = (r"\b(system|arm|pipeline|architecture|retrieval|evidence\s+pack\w*|packet|condition|variant|configuration)\s+proposed\b",)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--rows", type=Path, required=True)
    ap.add_argument("--claims", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--concurrency", type=int, default=1)
    args = ap.parse_args()

    rows = {r["eval_row_id"]: r for r in
            (json.loads(l) for l in open(args.rows, encoding="utf-8") if l.strip())}
    claims = [json.loads(l) for l in open(args.claims, encoding="utf-8") if l.strip()]

    done = set()
    if args.out.exists():
        for l in open(args.out, encoding="utf-8"):
            if l.strip():
                try:
                    done.add(json.loads(l)["key"])
                except Exception:
                    pass
    todo = [c for c in claims if c.get("claims") and c["key"] not in done and c["key"] in rows]
    print(f"selene-on-stored-claims: {len(todo)} todo", flush=True)

    def work(c):
        rid = c["key"]
        row = rows[rid]
        rec = {"key": rid, "unit_id": c["unit_id"], "arm": c["arm"], "n_claims": len(c["claims"])}
        items = [{"native_id": e["id"], "text": e["text"]}
                 for e in row.get("candidate_system_evidence") or []]
        blk, _ = P.render_evidence(items, "SRC")
        cl = [{"text": t} for t in c["claims"]]
        out = call_and_validate(
            args.base_url, args.model, f"{rid}:M1STORED",
            P.build_m1_prompt(cl, blk, allow=EXEMPT), S.m1_faithfulness_schema(len(cl)),
            lambda r: S.validate_per_claim_response(
                r, "M1_EVIDENCE_FAITHFULNESS", S.M1_FAITHFULNESS_LABELS, len(cl)))
        rec["status"] = out["status"]
        if out.get("contract_valid"):
            rec["labels"] = [v["label"] for v in out["response"]["verdicts"]]
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
                rec = {"key": futs[fut]["key"], "error": f"{type(e).__name__}: {e}"}
            with _lock:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
            n += 1
            fails = fails + 1 if ("CALL_FAILED" in str(rec.get("status", "")) or "error" in rec) else 0
            if fails >= 15:
                print(f"ABORTING: {fails} consecutive failures. {n}/{len(todo)} done.", flush=True)
                for f in futs:
                    f.cancel()
                break
            if n % 100 == 0:
                print(f"[{n}/{len(todo)}]", flush=True)
    print(f"\ncomplete: {n} records -> {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
