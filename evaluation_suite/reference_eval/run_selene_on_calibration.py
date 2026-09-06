"""Run the FROZEN penalty-free Selene judge on the 36-row focused calibration subset.

Uses the exact same DECODING config, prompts, and schemas as the frozen production sentinel run
(imported from run_reference_judge.py / reference_judge_prompts.py / reference_judge_schema.py -
nothing is redefined here). Only the input source differs: calibration rows instead of sentinels.

Produces exactly the four qualification-gated tasks: M1, M2, M3 (holistic), TARGET.
M4A is skipped - no frozen reference-claim decomposition exists for these KCs, exactly as already
disclosed in the focused-subset build (a row-level proxy would not be the atomic quantity the
protocol qualifies).

Output format matches what run_judge_qualification.py expects: {"results": [{"review_case_id":...,
"M1_faithfulness_per_claim":..., "M2_correctness_per_claim":..., "M3_core_completeness":...,
"TARGET_ALIGNMENT":...}, ...]}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

import reference_claim_schema as C   # noqa: E402
import reference_judge_prompts as P  # noqa: E402
import reference_judge_schema as S   # noqa: E402
from run_reference_judge import call_and_validate  # noqa: E402


def derive_m1(labels):
    return "PASS" if all(l == "SUPPORTED" for l in labels) else "FAIL"


def derive_m2(labels):
    return "PASS" if all(l in S.M2_MATERIALLY_CORRECT for l in labels) else "FAIL"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--calibration-rows", type=Path, required=True,
                    help="focused_calibration_subset.jsonl")
    ap.add_argument("--authority", type=Path, required=True, help="cal36_authority.json")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.calibration_rows, encoding="utf-8") if l.strip()]
    authority = {r["kc_id"]: r["authority_items"] for r in json.loads(args.authority.read_text(encoding="utf-8"))}
    if args.limit:
        rows = rows[: args.limit]

    print(f"running {len(rows)} calibration rows")
    results = []
    for row in rows:
        cid = row["review_case_id"]
        kc_id = row["unit_id"]
        canonical = row["canonical_name"]
        hierarchy = " > ".join(row.get("hierarchy_path") or [])
        draft = (row.get("candidate_draft") or "").strip()
        ref_text = (row.get("expert_reference") or "").strip()

        print(f"{cid} ({kc_id}) ...")
        # `responses` retains each task's FULL validated response (labels plus
        # missing_defining_components / rationale / per-claim verdicts). Only the derived scalar
        # label was kept originally, which made it impossible to ask WHY a verdict was reached -
        # e.g. which defining component M3 considered missing. That diagnostic is needed to tell a
        # judge error apart from a rubric-boundary disagreement, so it is recorded here.
        out_row = {"review_case_id": cid, "unit_id": kc_id, "calls": {}, "responses": {}}

        sys_items = [{"native_id": e["id"], "text": e["text"]} for e in row.get("candidate_system_evidence") or []]
        sys_block, _ = P.render_evidence(sys_items, "SRC")

        auth_native = authority.get(kc_id, [])
        auth_items = [{"native_id": a["auth_id"], "text": a["text"]} for a in auth_native]
        auth_block, _ = P.render_evidence(auth_items, "SRC")
        ref_block, _ = P.render_evidence([{"native_id": "ref", "text": ref_text}] if ref_text else [], "REF")

        if not draft:
            # abstention: no claims, so M1/M2/TARGET cannot be judged; M3 is judged directly (empty
            # draft -> the model itself must classify it, exactly as the sentinel harness does)
            out_row["M1_faithfulness_per_claim"] = None
            out_row["M2_correctness_per_claim"] = None
            out_row["TARGET_ALIGNMENT"] = None
        else:
            dec = call_and_validate(
                args.base_url, args.model, f"{cid}:DECOMPOSE", P.build_decomposition_prompt(draft, "candidate_draft"),
                S.decomposition_schema(),
                lambda r: r.get("task") == "CLAIM_DECOMPOSITION" or (_ for _ in ()).throw(
                    S.JudgeSchemaError(f"expected CLAIM_DECOMPOSITION, got {r.get('task')!r}")),
                max_tokens=4000)
            out_row["calls"]["decompose"] = {"status": dec["status"]}
            claims = [{"text": c["text"]} for c in dec["response"]["claims"]] if dec.get("contract_valid") else []

            if claims:
                m1 = call_and_validate(args.base_url, args.model, f"{cid}:M1", P.build_m1_prompt(claims, sys_block),
                                       S.m1_faithfulness_schema(len(claims)),
                                       lambda r: S.validate_per_claim_response(r, "M1_EVIDENCE_FAITHFULNESS", S.M1_FAITHFULNESS_LABELS, len(claims)))
                out_row["calls"]["m1"] = {"status": m1["status"]}
                if m1.get("contract_valid"):
                    out_row["responses"]["m1"] = m1["response"]
                out_row["M1_faithfulness_per_claim"] = (
                    derive_m1([v["label"] for v in m1["response"]["verdicts"]]) if m1.get("contract_valid") else None)

                if ref_text:
                    m2 = call_and_validate(args.base_url, args.model, f"{cid}:M2", P.build_m2_prompt(claims, ref_block, auth_block),
                                           S.m2_correctness_schema(len(claims)),
                                           lambda r: S.validate_m2_response(r, len(claims)))
                    out_row["calls"]["m2"] = {"status": m2["status"]}
                    if m2.get("contract_valid"):
                        out_row["responses"]["m2"] = m2["response"]
                    out_row["M2_correctness_per_claim"] = (
                        derive_m2([v["label"] for v in m2["response"]["verdicts"]]) if m2.get("contract_valid") else None)
                else:
                    out_row["M2_correctness_per_claim"] = None
            else:
                out_row["M1_faithfulness_per_claim"] = None
                out_row["M2_correctness_per_claim"] = None

            if ref_text:
                tgt = call_and_validate(args.base_url, args.model, f"{cid}:TARGET",
                                        P.build_target_alignment_prompt(canonical, hierarchy, ref_block, draft, auth_block),
                                        S.target_alignment_schema(), S.validate_target_alignment_response)
                out_row["calls"]["target"] = {"status": tgt["status"]}
                if tgt.get("contract_valid"):
                    out_row["responses"]["target"] = tgt["response"]
                out_row["TARGET_ALIGNMENT"] = tgt["response"]["label"] if tgt.get("contract_valid") else None
            else:
                out_row["TARGET_ALIGNMENT"] = None

        if ref_text:
            m3 = call_and_validate(args.base_url, args.model, f"{cid}:M3",
                                   P.build_m3_holistic_prompt(canonical, hierarchy, ref_block, draft),
                                   S.m3_holistic_schema(),
                                   lambda r: S.validate_holistic_response(r, "M3_CORE_COMPLETENESS", S.M3_HOLISTIC_LABELS, "missing_defining_components"))
            out_row["calls"]["m3"] = {"status": m3["status"]}
            if m3.get("contract_valid"):
                out_row["responses"]["m3"] = m3["response"]
            out_row["M3_core_completeness"] = m3["response"]["label"] if m3.get("contract_valid") else None
        else:
            out_row["M3_core_completeness"] = None

        print(f"   M1={out_row.get('M1_faithfulness_per_claim')} M2={out_row.get('M2_correctness_per_claim')} "
              f"M3={out_row.get('M3_core_completeness')} TARGET={out_row.get('TARGET_ALIGNMENT')}")
        results.append(out_row)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"model": args.model, "n_rows": len(results), "results": results}, f, indent=2, ensure_ascii=False)
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
