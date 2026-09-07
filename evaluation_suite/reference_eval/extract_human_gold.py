"""Convert the annotated KC_ANNOTATION_FOCUSED.xlsx into the JSONL schema
run_judge_qualification.py expects, and freeze it with an honest provenance record.

PROVENANCE DISCLOSURE (recorded, not hidden): these labels were produced with LLM suggestions
visible to the annotator, who then validated and in several cases revised them. This is NOT
independent unaided human annotation, and it is NOT a second data point for human-human agreement.
It carries a structurally identical anchoring risk to the Qwen-seed threat that is already central
to this project's reference-construction methodology - a human judgment made in the presence of a
machine suggestion can be pulled toward that suggestion even when the human believes they are
judging independently.

Evidence this pass involved genuine verification rather than wholesale acceptance, checked
mechanically rather than asserted:
  - 0/36 notes are byte-identical to the prior ChatGPT-only pass (all freshly written)
  - 6/144 primary-task labels (M1 x3, M2 x2, M1+M2 on one row) differ from that prior pass
  - every divergence moves PASS -> FAIL (the stricter direction), each with a specific technical
    rationale citing evidence ids
  - three notes explicitly say "REVISED on recheck" and cross-reference other rows sharing evidence

This does not make the process independent; it is reported so the qualification result is read
with its actual evidentiary weight, not a stronger one.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import load_workbook

BASE = Path(__file__).parent
CAL = BASE / "output" / "human_calibration"
XLSX = CAL / "KC_ANNOTATION_FOCUSED.xlsx"
CHATGPT_REF = Path(r"r:\Downloads\KC_ANNOTATION_WORKBOOK_ChatGPT_ANNOTATED.xlsx")
OUT_JSONL = CAL / "human_gold_focused36.jsonl"
OUT_META = CAL / "human_gold_focused36_provenance.json"

COL_MAP = {
    "M1 faithfulness": "M1_faithfulness_per_claim",
    "M2 correctness": "M2_correctness_per_claim",
    "M3 completeness": "M3_core_completeness",
    "TARGET alignment": "TARGET_ALIGNMENT",
    "Valid alt. beyond ref?": "VALID_SOURCE_SUPPORTED_ALTERNATIVE_BEYOND_REFERENCE",
    "Possible ref defect?": "POSSIBLE_REFERENCE_DEFECT",
}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    ws = load_workbook(XLSX)["Annotate"]
    hdr = [c.value for c in ws[1]]
    ci = {h: i for i, h in enumerate(hdr)}

    out_rows = []
    unfilled = []
    for r in ws.iter_rows(min_row=2, values_only=False):
        vals = [c.value for c in r]
        cid = vals[ci["Case ID"]]
        row = {"review_case_id": cid, "unit_id": vals[ci["KC ID"]]}
        for src_col, dst_key in COL_MAP.items():
            row[dst_key] = vals[ci[src_col]]
        row["confidence"] = vals[ci["Confidence"]]
        row["notes"] = vals[ci["Notes"]]
        if any(row[k] in (None, "") for k in COL_MAP.values() if k not in
               ("VALID_SOURCE_SUPPORTED_ALTERNATIVE_BEYOND_REFERENCE", "POSSIBLE_REFERENCE_DEFECT")):
            unfilled.append(cid)
        out_rows.append(row)

    if unfilled:
        print(f"REFUSED: {len(unfilled)} row(s) have unfilled primary judgments: {unfilled}")
        return 1

    with open(OUT_JSONL, "w", encoding="utf-8") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # --- verification against the discarded ChatGPT-only pass, for the provenance record ---
    divergence = {"n_compared": 0, "n_identical_notes": 0, "label_diffs": []}
    if CHATGPT_REF.exists():
        b_ws = load_workbook(CHATGPT_REF)["Annotate"]
        b_hdr = [c.value for c in b_ws[1]]
        b_ci = {h: i for i, h in enumerate(b_hdr)}
        b_rows = {r[b_ci["Case ID"]]: r for r in ([c.value for c in row] for row in b_ws.iter_rows(min_row=2))}
        for r in out_rows:
            b = b_rows.get(r["review_case_id"])
            if b is None:
                continue
            divergence["n_compared"] += 1
            if r["notes"] and r["notes"] == b[b_ci.get("Notes", -1)]:
                divergence["n_identical_notes"] += 1
            for src_col, dst_key in list(COL_MAP.items())[:4]:
                if dst_key in ("VALID_SOURCE_SUPPORTED_ALTERNATIVE_BEYOND_REFERENCE", "POSSIBLE_REFERENCE_DEFECT"):
                    continue
                if r[dst_key] != b[b_ci[src_col]]:
                    divergence["label_diffs"].append({
                        "case_id": r["review_case_id"], "task": dst_key,
                        "final": r[dst_key], "chatgpt_only_pass": b[b_ci[src_col]],
                    })

    class_counts = {}
    for dst_key, minority in [("M1_faithfulness_per_claim", "FAIL"), ("M2_correctness_per_claim", "FAIL"),
                               ("M3_core_completeness", "MATERIAL_OMISSION"), ("TARGET_ALIGNMENT", "WRONG_TARGET")]:
        c = Counter(r[dst_key] for r in out_rows)
        class_counts[dst_key] = {"distribution": dict(c), "minority_class": minority,
                                  "minority_n": c.get(minority, 0),
                                  "meets_min_10": c.get(minority, 0) >= 10}

    meta = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_xlsx": XLSX.name,
        "source_xlsx_sha256": sha(XLSX),
        "output_jsonl": OUT_JSONL.name,
        "output_jsonl_sha256": sha(OUT_JSONL),
        "n_rows": len(out_rows),
        "annotator_provenance": {
            "type": "LLM-SUGGESTION-ASSISTED, HUMAN-VALIDATED — single pass",
            "NOT": "independent unaided human annotation; NOT a second data point for human-human agreement",
            "disclosed_by": "annotator, at handoff",
            "operator_statement": "used several LLM experts for suggestions; performed validation and "
                                   "made most judgments themselves",
            "anchoring_risk": "structurally identical to the Qwen-seed anchoring threat central to this "
                               "project's reference construction (see paper_methods/THREATS_TO_VALIDITY.md "
                               "section 1): a human judgment formed in the presence of a machine suggestion "
                               "can be pulled toward it even when the human believes they judged independently.",
            "verification_evidence_of_genuine_engagement": divergence,
        },
        "human_human_agreement": "NOT COMPUTABLE — only one annotation pass exists for this subset.",
        "class_counts_vs_protocol_min_10": class_counts,
        "note": "class counts are fixed by the human labels and do not depend on Selene's predictions; "
                "whether a task returns INSUFFICIENT_VALIDATION_SUPPORT is therefore already determined "
                "at this point, before any judge inference is run.",
    }
    OUT_META.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"wrote {OUT_JSONL.name} ({len(out_rows)} rows)")
    print(f"wrote {OUT_META.name}")
    print(f"\ndivergence from discarded ChatGPT-only pass: {len(divergence['label_diffs'])}/"
          f"{divergence['n_compared']*4} labels differ, {divergence['n_identical_notes']}/"
          f"{divergence['n_compared']} notes byte-identical")
    print("\nclass counts vs the frozen protocol's minimum of 10:")
    for k, v in class_counts.items():
        print(f"  {k:<32} {v['minority_class']:<20} n={v['minority_n']:<4} "
              f"{'OK' if v['meets_min_10'] else 'BELOW MINIMUM -> INSUFFICIENT_VALIDATION_SUPPORT expected'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
