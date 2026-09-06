"""Extract atomic claims from each draft and STORE THE CLAIM TEXTS.

The v2 faithfulness stage decomposed drafts into claims and then discarded the claim texts, keeping
only the verdicts. That made the groundedness judgements impossible to re-verify with a second
instrument without re-running decomposition, which is the whole reason this script exists.

Decomposition is deterministic (temperature 0, fixed seed, sequential), so the claims recovered here
are the same ones the original verdicts were made on. Storing them makes the campaign auditable by
any external verifier.
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

# genuine domain text that trips the blinding guard; see locks/AMENDMENT_02
EXEMPT = (r"\b(system|arm|pipeline|architecture|retrieval|evidence\s+pack\w*|packet|condition|variant|configuration)\s+proposed\b",)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--rows", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--concurrency", type=int, default=1)
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.rows, encoding="utf-8") if l.strip()]
    done = set()
    if args.out.exists():
        for l in open(args.out, encoding="utf-8"):
            if l.strip():
                try:
                    done.add(json.loads(l)["key"])
                except Exception:
                    pass
    todo = [r for r in rows if r["eval_row_id"] not in done]
    print(f"claim extraction: {len(todo)} todo", flush=True)

    def work(row):
        rid = row["eval_row_id"]
        rec = {"key": rid, "unit_id": row["unit_id"], "arm": row["arm"]}
        draft = (row.get("candidate_draft") or "").strip()
        if not draft:
            rec["status"] = "ABSTENTION_NO_DRAFT"
            rec["claims"] = []
            return rec
        out = call_and_validate(
            args.base_url, args.model, f"{rid}:CLAIMS",
            P.build_decomposition_prompt(draft, "candidate_draft", allow=EXEMPT),
            S.decomposition_schema(),
            lambda r: r.get("task") == "CLAIM_DECOMPOSITION" or (_ for _ in ()).throw(
                S.JudgeSchemaError(f"expected CLAIM_DECOMPOSITION, got {r.get('task')!r}")),
            max_tokens=4000)
        rec["status"] = out["status"]
        if out.get("contract_valid"):
            rec["claims"] = [c["text"] for c in out["response"]["claims"]]
            rec["n_claims"] = len(rec["claims"])
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
                rec = {"key": futs[fut]["eval_row_id"], "error": f"{type(e).__name__}: {e}"}
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
    print(f"\nclaim extraction complete: {n} records -> {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
