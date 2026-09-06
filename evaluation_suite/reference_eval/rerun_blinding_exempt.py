"""Re-judge the one row that tripped the blinding guard on genuine domain text.

See locks/AMENDMENT_02_blinding_exemption.md. The KC is Boosting and the offending phrase is
"Arcing, a variant proposed by Breiman" - a 1998 algorithm, not our pipeline. Exactly one pattern is
exempted, for exactly one row, and the exemption is written into the output record so it can never
be mistaken for an ordinary judgement.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

import reference_judge_prompts as P   # noqa: E402
import reference_judge_schema as S    # noqa: E402
from run_reference_judge import call_and_validate  # noqa: E402

ROW_ID = "KC_EVAL_ENS_004|sensitivity_DOS-Q_matched"
EXEMPT = r"\b(system|arm|pipeline|architecture|retrieval|evidence\s+pack\w*|packet|condition|variant|configuration)\s+proposed\b"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--rows", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.rows, encoding="utf-8") if l.strip()]
    row = next((r for r in rows if r["eval_row_id"] == ROW_ID), None)
    if row is None:
        print(f"REFUSED: {ROW_ID} not found")
        return 1

    # confirm the exemption is still needed and still narrow
    if EXEMPT not in {p.pattern for p in P._FORBIDDEN}:
        print("REFUSED: the exempted pattern is not in the guard's pattern set; "
              "the guard changed and this amendment must be re-reviewed")
        return 1

    draft = (row.get("candidate_draft") or "").strip()
    if not draft:
        print("REFUSED: row has no draft")
        return 1

    allow = (EXEMPT,)
    dec = call_and_validate(
        args.base_url, args.model, f"{ROW_ID}:DECOMPOSE",
        P.build_decomposition_prompt(draft, "candidate_draft", allow=allow),
        S.decomposition_schema(),
        lambda r: r.get("task") == "CLAIM_DECOMPOSITION" or (_ for _ in ()).throw(
            S.JudgeSchemaError(f"expected CLAIM_DECOMPOSITION, got {r.get('task')!r}")),
        max_tokens=4000)
    rec = {"key": ROW_ID, "stage": "faithfulness", "unit_id": row["unit_id"], "arm": row["arm"],
           "abstained": False, "blinding_exemption": EXEMPT,
           "amendment": "locks/AMENDMENT_02_blinding_exemption.md"}
    if not dec.get("contract_valid"):
        rec["status"] = f"DECOMPOSE_{dec['status']}"
        print(json.dumps(rec))
        return 1
    claims = [{"text": c["text"]} for c in dec["response"]["claims"]]
    items = [{"native_id": e["id"], "text": e["text"]}
             for e in row.get("candidate_system_evidence") or []]
    blk, _ = P.render_evidence(items, "SRC")
    m1 = call_and_validate(
        args.base_url, args.model, f"{ROW_ID}:M1", P.build_m1_prompt(claims, blk, allow=allow),
        S.m1_faithfulness_schema(len(claims)),
        lambda r: S.validate_per_claim_response(
            r, "M1_EVIDENCE_FAITHFULNESS", S.M1_FAITHFULNESS_LABELS, len(claims)))
    rec["status"] = m1["status"]
    rec["n_claims"] = len(claims)
    if m1.get("contract_valid"):
        rec["verdicts"] = m1["response"]["verdicts"]
    with open(args.out, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    sup = sum(1 for v in rec.get("verdicts", []) if v["label"] == "SUPPORTED")
    print(f"{ROW_ID}: status={rec['status']} claims={rec.get('n_claims')} supported={sup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
