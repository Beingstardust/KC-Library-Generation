"""Execute the v2 metrics defined in locks/OVERHAUL_PROTOCOL_v2.md.

Three stages, run in order because each depends on the previous:

  decompose  159 references -> nuggets labelled VITAL / OKAY. ARM-INDEPENDENT and DRAFT-INDEPENDENT,
             so every arm is scored against an identical nugget set and no arm can be advantaged by
             a different decomposition.
  assign     1113 (KC, arm) drafts -> SUPPORTED / PARTIAL / NOT_SUPPORTED per nugget.
             Gives vital-nugget recall (generation recall).
  context    4 evidence configurations x 159 KCs -> PRESENT / PARTIAL / ABSENT per nugget, judged
             against the RETRIEVED EVIDENCE with NO draft and NO generator involved.
             Gives context recall (retrieval recall).

Only 4 evidence configurations exist across the 7 arms, so `context` costs 636 judgements rather
than 1113 - and, being generator-free, it is the metric that answers "is this retrieval better?"
without the confound that a single fixed drafter introduces.

Same frozen judge, decoding, and blinding enforcement as v1. Resumable: results append to JSONL and
completed keys are skipped.
"""
from __future__ import annotations

import argparse
import hashlib
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


def ev_config_id(row) -> str:
    """Stable id for an arm's evidence set on a KC: identical evidence -> identical id."""
    txt = "|".join(e["text"] for e in row.get("candidate_system_evidence") or [])
    return hashlib.sha256(txt.encode("utf-8")).hexdigest()[:16]


def stage_decompose(args, rows, done):
    """One decomposition per KC. Reference text is identical across arms, so take the first."""
    by_kc = {}
    for r in rows:
        if r["unit_id"] not in by_kc and (r.get("expert_reference") or "").strip():
            by_kc[r["unit_id"]] = r
    todo = [r for k, r in by_kc.items() if k not in done]
    print(f"decompose: {len(by_kc)} KCs, {len(todo)} todo", flush=True)

    def work(row):
        ref_block, _ = P.render_evidence(
            [{"native_id": "ref", "text": row["expert_reference"]}], "REF")
        hierarchy = " > ".join(row.get("hierarchy_path") or [])
        out = call_and_validate(
            args.base_url, args.model, f'{row["unit_id"]}:NUGGETS',
            NS.build_nugget_decomposition_prompt(row["canonical_name"], hierarchy, ref_block),
            NS.nugget_decomposition_schema(), NS.validate_decomposition, max_tokens=3000)
        rec = {"key": row["unit_id"], "stage": "decompose", "unit_id": row["unit_id"],
               "status": out["status"]}
        if out.get("contract_valid"):
            rec["nuggets"] = out["response"]["nuggets"]
        return rec
    return todo, work


def stage_assign(args, rows, done, nuggets):
    todo = [r for r in rows
            if r["eval_row_id"] not in done and r["unit_id"] in nuggets]
    print(f"assign: {len(todo)} todo", flush=True)

    def work(row):
        ng = nuggets[row["unit_id"]]
        draft = (row.get("candidate_draft") or "").strip()
        rec = {"key": row["eval_row_id"], "stage": "assign", "unit_id": row["unit_id"],
               "arm": row["arm"], "n_nuggets": len(ng)}
        if not draft:
            # genuine abstention: nothing is conveyed, so every nugget is NOT_SUPPORTED.
            # Recorded explicitly rather than skipped, because declining to draft is a real
            # behaviour and must score, not vanish.
            rec["verdicts"] = [{"nugget_index": i + 1, "label": "NOT_SUPPORTED"}
                               for i in range(len(ng))]
            rec["status"] = "ABSTENTION_NO_DRAFT"
            return rec
        out = call_and_validate(
            args.base_url, args.model, f'{row["eval_row_id"]}:ASSIGN',
            NS.build_nugget_assignment_prompt(ng, draft),
            NS.nugget_assignment_schema(len(ng)),
            lambda r: NS.validate_assignment(r, "NUGGET_ASSIGNMENT", NS.NUGGET_SUPPORT, len(ng)),
            max_tokens=4000)
        rec["status"] = out["status"]
        if out.get("contract_valid"):
            rec["verdicts"] = out["response"]["verdicts"]
        return rec
    return todo, work


def stage_context(args, rows, done, nuggets):
    """One judgement per (evidence configuration, KC) - not per arm."""
    seen, todo = set(), []
    for r in rows:
        if r["unit_id"] not in nuggets:
            continue
        key = f'{r["unit_id"]}|{ev_config_id(r)}'
        if key in seen or key in done:
            continue
        seen.add(key)
        todo.append((key, r))
    print(f"context: {len(todo)} todo (evidence-config x KC, generator-free)", flush=True)

    def work(item):
        key, row = item
        ng = nuggets[row["unit_id"]]
        items = [{"native_id": e["id"], "text": e["text"]}
                 for e in row.get("candidate_system_evidence") or []]
        ev_block, _ = P.render_evidence(items, "SRC")
        rec = {"key": key, "stage": "context", "unit_id": row["unit_id"],
               "ev_config": ev_config_id(row), "arm_example": row["arm"],
               "n_nuggets": len(ng), "n_evidence": len(items)}
        if not items:
            rec["verdicts"] = [{"nugget_index": i + 1, "label": "ABSENT"} for i in range(len(ng))]
            rec["status"] = "NO_EVIDENCE"
            return rec
        out = call_and_validate(
            args.base_url, args.model, f"{key}:CONTEXT",
            NS.build_context_recall_prompt(ng, ev_block),
            NS.context_recall_schema(len(ng)),
            lambda r: NS.validate_assignment(r, "CONTEXT_RECALL", NS.CONTEXT_PRESENCE, len(ng)),
            max_tokens=4000)
        rec["status"] = out["status"]
        if out.get("contract_valid"):
            rec["verdicts"] = out["response"]["verdicts"]
        return rec
    return todo, work


def stage_faithfulness(args, rows, done, _nuggets):
    """Claim decomposition + per-claim faithfulness only.

    v2 demotes M2, TARGET and holistic M3, so re-running the full v1 chain would spend ~60% of its
    calls on metrics we no longer report. This stage runs just the two calls that feed the primary
    faithfulness measure, so the metric can be produced on a SINGLE instrument rather than inherited
    from the mixed-instrument v1 campaign.
    """
    import reference_judge_schema as S
    todo = [r for r in rows if r["eval_row_id"] not in done]
    print(f"faithfulness: {len(todo)} todo", flush=True)

    def work(row):
        rid = row["eval_row_id"]
        draft = (row.get("candidate_draft") or "").strip()
        rec = {"key": rid, "stage": "faithfulness", "unit_id": row["unit_id"], "arm": row["arm"]}
        if not draft:
            # abstention: no claims exist, so faithfulness is undefined rather than zero.
            rec["status"] = "ABSTENTION_NO_DRAFT"
            rec["abstained"] = True
            return rec
        rec["abstained"] = False
        dec = call_and_validate(
            args.base_url, args.model, f"{rid}:DECOMPOSE",
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
        items = [{"native_id": e["id"], "text": e["text"]}
                 for e in row.get("candidate_system_evidence") or []]
        sys_block, _ = P.render_evidence(items, "SRC")
        m1 = call_and_validate(
            args.base_url, args.model, f"{rid}:M1", P.build_m1_prompt(claims, sys_block),
            S.m1_faithfulness_schema(len(claims)),
            lambda r: S.validate_per_claim_response(
                r, "M1_EVIDENCE_FAITHFULNESS", S.M1_FAITHFULNESS_LABELS, len(claims)))
        rec["status"] = m1["status"]
        rec["n_claims"] = len(claims)
        if m1.get("contract_valid"):
            rec["verdicts"] = m1["response"]["verdicts"]
        return rec
    return todo, work

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--rows", type=Path, required=True)
    ap.add_argument("--stage", choices=["decompose", "assign", "context", "faithfulness"], required=True)
    ap.add_argument("--nuggets", type=Path, help="decompose output, required for assign/context")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--limit", type=int, default=None)
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

    nuggets = {}
    if args.stage in ("assign", "context"):
        if not args.nuggets or not args.nuggets.exists():
            print("REFUSED: --nuggets is required for this stage")
            return 1
        for l in open(args.nuggets, encoding="utf-8"):
            if l.strip():
                r = json.loads(l)
                if r.get("nuggets"):
                    nuggets[r["unit_id"]] = r["nuggets"]
        print(f"loaded nuggets for {len(nuggets)} KCs", flush=True)

    if args.stage == "decompose":
        todo, work = stage_decompose(args, rows, done)
    elif args.stage == "assign":
        todo, work = stage_assign(args, rows, done, nuggets)
    elif args.stage == "faithfulness":
        todo, work = stage_faithfulness(args, rows, done, nuggets)
    else:
        todo, work = stage_context(args, rows, done, nuggets)

    if args.limit:
        todo = todo[: args.limit]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    consecutive_failures = 0
    with open(args.out, "a", encoding="utf-8") as fh, \
            ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = {ex.submit(work, t): t for t in todo}
        for fut in as_completed(futs):
            try:
                rec = fut.result()
            except Exception as e:
                t = futs[fut]
                k = t[0] if isinstance(t, tuple) else (t.get("eval_row_id") or t.get("unit_id"))
                rec = {"key": k, "stage": args.stage, "error": f"{type(e).__name__}: {e}"}
            with _lock:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
            n += 1
            # Abort on a run of consecutive call failures. A dead server (e.g. the SLURM job hit
            # its time limit) otherwise looks like "work completing very fast": every remaining row
            # records CALL_FAILED and the stage reports success having judged nothing. That happened
            # once and cost 538 rows of silent garbage, so it is now a hard stop.
            st = str(rec.get("status", ""))
            if "CALL_FAILED" in st or "error" in rec:
                consecutive_failures += 1
            else:
                consecutive_failures = 0
            if consecutive_failures >= 15:
                print(f"ABORTING: {consecutive_failures} consecutive call failures - the server is "
                      f"probably gone. {n}/{len(todo)} processed. Re-run after restarting it; "
                      f"completed keys are skipped.", flush=True)
                for f in futs:
                    f.cancel()
                break
            if n % 10 == 0 or "error" in rec:
                print(f"[{n}/{len(todo)}] {rec.get('key')} {rec.get('error','')}", flush=True)
    print(f"\n{args.stage} complete: {n} records -> {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
