"""Run the frozen reference-based judge over the full ablation set (KC x arm).

Same judge, same prompts, same schemas, same decoding as the frozen instrument — every one of
those is imported from the frozen modules and none is redefined here. Two things differ from
`run_selene_on_calibration.py`, both mechanical rather than semantic:

  1. CONCURRENCY. Rows are dispatched in parallel. Sequentially the full set is ~93 GPU-hours,
     which does not fit a scheduler allocation; concurrency makes it tractable. Within a row the
     call order is unchanged (decompose -> M1 -> M2 -> TARGET -> M3) — only different ROWS overlap.
     Concurrency is nevertheless treated as an instrument change and must be proven equivalent
     before use: run this script on the 36 calibration rows and diff against the sequential
     predictions. Batch composition can in principle perturb floating-point reduction order and
     therefore an argmax on a near-tie, so this is verified empirically, not assumed.

  2. RESUMABILITY. Results append to JSONL and completed ids are skipped on restart, so a job that
     hits a wall-clock limit resumes instead of restarting.

Full validated responses are retained (labels AND missing_defining_components / rationale /
per-claim verdicts), so any later disagreement can be interrogated rather than guessed at.

An empty candidate draft is a genuine abstention: M1/M2/TARGET are not judgeable without claims and
are recorded as None, while M3 still runs, exactly as the calibration and sentinel harnesses do.
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

import reference_judge_prompts as P  # noqa: E402
import reference_judge_schema as S   # noqa: E402
from run_reference_judge import call_and_validate  # noqa: E402

_write_lock = threading.Lock()
_print_lock = threading.Lock()


def derive_m1(labels):
    return "PASS" if all(l == "SUPPORTED" for l in labels) else "FAIL"


def derive_m2(labels):
    return "PASS" if all(l in S.M2_MATERIALLY_CORRECT for l in labels) else "FAIL"


def judge_row(row, base_url, model, authority, id_field, instrument="unspecified"):
    rid = row[id_field]
    kc_id = row["unit_id"]
    canonical = row["canonical_name"]
    hierarchy = " > ".join(row.get("hierarchy_path") or [])
    draft = (row.get("candidate_draft") or "").strip()
    ref_text = (row.get("expert_reference") or "").strip()

    out = {id_field: rid, "unit_id": kc_id, "instrument": instrument, "calls": {}, "responses": {}}
    if "arm" in row:
        out["arm"] = row["arm"]
        out["family"] = row.get("family")

    sys_items = [{"native_id": e["id"], "text": e["text"]}
                 for e in row.get("candidate_system_evidence") or []]
    sys_block, _ = P.render_evidence(sys_items, "SRC")
    auth_items = [{"native_id": a["auth_id"], "text": a["text"]} for a in authority.get(kc_id, [])]
    auth_block, _ = P.render_evidence(auth_items, "SRC")
    ref_block, _ = P.render_evidence([{"native_id": "ref", "text": ref_text}] if ref_text else [], "REF")

    if not draft:
        out["M1_faithfulness_per_claim"] = None
        out["M2_correctness_per_claim"] = None
        out["TARGET_ALIGNMENT"] = None
        out["abstained"] = True
    else:
        out["abstained"] = False
        dec = call_and_validate(
            base_url, model, f"{rid}:DECOMPOSE", P.build_decomposition_prompt(draft, "candidate_draft"),
            S.decomposition_schema(),
            lambda r: r.get("task") == "CLAIM_DECOMPOSITION" or (_ for _ in ()).throw(
                S.JudgeSchemaError(f"expected CLAIM_DECOMPOSITION, got {r.get('task')!r}")),
            max_tokens=4000)
        out["calls"]["decompose"] = {"status": dec["status"]}
        claims = [{"text": c["text"]} for c in dec["response"]["claims"]] if dec.get("contract_valid") else []

        if claims:
            m1 = call_and_validate(base_url, model, f"{rid}:M1", P.build_m1_prompt(claims, sys_block),
                                   S.m1_faithfulness_schema(len(claims)),
                                   lambda r: S.validate_per_claim_response(
                                       r, "M1_EVIDENCE_FAITHFULNESS", S.M1_FAITHFULNESS_LABELS, len(claims)))
            out["calls"]["m1"] = {"status": m1["status"]}
            if m1.get("contract_valid"):
                out["responses"]["m1"] = m1["response"]
            out["M1_faithfulness_per_claim"] = (
                derive_m1([v["label"] for v in m1["response"]["verdicts"]]) if m1.get("contract_valid") else None)

            if ref_text:
                m2 = call_and_validate(base_url, model, f"{rid}:M2",
                                       P.build_m2_prompt(claims, ref_block, auth_block),
                                       S.m2_correctness_schema(len(claims)),
                                       lambda r: S.validate_m2_response(r, len(claims)))
                out["calls"]["m2"] = {"status": m2["status"]}
                if m2.get("contract_valid"):
                    out["responses"]["m2"] = m2["response"]
                out["M2_correctness_per_claim"] = (
                    derive_m2([v["label"] for v in m2["response"]["verdicts"]]) if m2.get("contract_valid") else None)
            else:
                out["M2_correctness_per_claim"] = None
        else:
            out["M1_faithfulness_per_claim"] = None
            out["M2_correctness_per_claim"] = None

        if ref_text:
            tgt = call_and_validate(base_url, model, f"{rid}:TARGET",
                                    P.build_target_alignment_prompt(canonical, hierarchy, ref_block, draft, auth_block),
                                    S.target_alignment_schema(), S.validate_target_alignment_response)
            out["calls"]["target"] = {"status": tgt["status"]}
            if tgt.get("contract_valid"):
                out["responses"]["target"] = tgt["response"]
            out["TARGET_ALIGNMENT"] = tgt["response"]["label"] if tgt.get("contract_valid") else None
        else:
            out["TARGET_ALIGNMENT"] = None

    if ref_text:
        m3 = call_and_validate(base_url, model, f"{rid}:M3",
                               P.build_m3_holistic_prompt(canonical, hierarchy, ref_block, draft),
                               S.m3_holistic_schema(),
                               lambda r: S.validate_holistic_response(
                                   r, "M3_CORE_COMPLETENESS", S.M3_HOLISTIC_LABELS, "missing_defining_components"))
        out["calls"]["m3"] = {"status": m3["status"]}
        if m3.get("contract_valid"):
            out["responses"]["m3"] = m3["response"]
        out["M3_core_completeness"] = m3["response"]["label"] if m3.get("contract_valid") else None
    else:
        out["M3_core_completeness"] = None
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--rows", type=Path, required=True)
    ap.add_argument("--authority", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True, help="JSONL, appended, resumable")
    ap.add_argument("--id-field", default="eval_row_id",
                    help="eval_row_id for ablation rows, review_case_id for calibration rows")
    ap.add_argument("--concurrency", type=int, default=1,
                    help="MUST be 1 for production runs: concurrency was measured to change "
                         "verdicts (see CONCURRENCY_NOT_VERDICT_NEUTRAL.md). >1 is for "
                         "diagnostics only.")
    ap.add_argument("--instrument", default="unspecified",
                    help="tag recorded on every row, e.g. cluster_b_cu124_a100_tp2 or ants_tp4_h100")
    ap.add_argument("--shard-index", type=int, default=0)
    ap.add_argument("--shard-count", type=int, default=1,
                    help="split rows across instruments; shards are disjoint by row index")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    if args.concurrency != 1:
        print(f"WARNING: concurrency={args.concurrency}. Concurrency is NOT verdict-neutral on "
              f"this stack (measured). Production runs must use --concurrency 1.", flush=True)

    rows = [json.loads(l) for l in open(args.rows, encoding="utf-8") if l.strip()]
    if args.shard_count > 1:
        rows = [r for i, r in enumerate(rows) if i % args.shard_count == args.shard_index]
        print(f"shard {args.shard_index}/{args.shard_count}: {len(rows)} rows", flush=True)
    if args.limit:
        rows = rows[: args.limit]
    authority = {r["kc_id"]: r["authority_items"]
                 for r in json.loads(args.authority.read_text(encoding="utf-8"))}

    done = set()
    if args.out.exists():
        for l in open(args.out, encoding="utf-8"):
            if l.strip():
                try:
                    done.add(json.loads(l)[args.id_field])
                except Exception:
                    pass
    todo = [r for r in rows if r[args.id_field] not in done]
    print(f"rows={len(rows)} already_done={len(done)} todo={len(todo)} concurrency={args.concurrency}",
          flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    n_done = 0
    with open(args.out, "a", encoding="utf-8") as fh, \
            ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = {ex.submit(judge_row, r, args.base_url, args.model, authority, args.id_field, args.instrument): r
                for r in todo}
        for fut in as_completed(futs):
            r = futs[fut]
            try:
                res = fut.result()
            except Exception as e:  # a row failing must not abort the campaign
                res = {args.id_field: r[args.id_field], "unit_id": r.get("unit_id"),
                       "arm": r.get("arm"), "error": f"{type(e).__name__}: {e}"}
            with _write_lock:
                fh.write(json.dumps(res, ensure_ascii=False) + "\n")
                fh.flush()
            n_done += 1
            with _print_lock:
                if "error" in res:
                    print(f"[{n_done}/{len(todo)}] ERROR {res[args.id_field]}: {res['error']}", flush=True)
                else:
                    print(f"[{n_done}/{len(todo)}] {res[args.id_field]} "
                          f"M1={res.get('M1_faithfulness_per_claim')} M2={res.get('M2_correctness_per_claim')} "
                          f"M3={res.get('M3_core_completeness')} T={res.get('TARGET_ALIGNMENT')}", flush=True)

    print(f"\ncomplete: {n_done} rows written to {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
