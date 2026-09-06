"""Version the calibration workbook's ANNOTATION SCHEMA without touching the SAMPLE.

The 180 rows - which KCs, which arms, presentation order, blinding mapping, random seed - are
carried through unchanged and verified row-for-row against v1. Resampling after a metric-scope
change would add a researcher degree of freedom, so nothing about the sample is redrawn.

What changes is only how the annotation fields are labelled and which ones exist:

  * M4_evidence_adequacy  ->  M4B_exploratory_holistic_evidence_adequacy
    Retained for audit / optional research annotation, explicitly marked non-primary so it cannot
    be mistaken for a qualification-gating field at annotation time.

  * M4A_retrieval_claim_support ADDED. v1 had no field for the decomposed retrieval-coverage task,
    and that task is now the primary retrieval diagnostic, so it must be representable in the
    human materials.

v1 is left in place unmodified.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent
CAL = BASE / "output" / "human_calibration"
V1 = CAL / "reference_human_calibration_workbook.jsonl"
V2 = CAL / "reference_human_calibration_workbook_v2.jsonl"
META = CAL / "calibration_workbook_v2_metadata.json"

SAMPLE_IDENTITY_FIELDS = ("review_case_id", "unit_id", "presentation_position",
                          "canonical_name", "hierarchy_path")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    v1_rows = [json.loads(l) for l in open(V1, encoding="utf-8") if l.strip()]
    out_rows = []

    for r in v1_rows:
        n = dict(r)

        # --- demote the holistic adequacy field (renamed, marked, value preserved) ---
        holistic_value = n.pop("M4_evidence_adequacy", None)
        n["M4B_exploratory_holistic_evidence_adequacy"] = holistic_value
        n["M4B_scope"] = "EXPLORATORY_NON_PRIMARY"
        n["M4B_note"] = ("Optional. Do NOT use for judge qualification, system ranking, "
                         "materially_sound, or primary statistical testing. Demoted 2026-08-25 "
                         "because the automated version of this task systematically treated the full "
                         "expert reference as a mandatory checklist.")

        # --- add the primary retrieval-coverage task, absent from v1 ---
        n["M4A_retrieval_claim_support"] = None  # per reference claim: SUPPORTED_BY_RETRIEVAL / NOT_SUPPORTED_BY_RETRIEVAL
        n["M4A_scope"] = "PRIMARY_RETRIEVAL_DIAGNOSTIC"
        n["M4A_note"] = ("For each substantive expert-reference claim, does the candidate system "
                         "evidence contain source support for it? This is a per-claim availability "
                         "question, NOT a judgment about whether the evidence was collectively "
                         "sufficient. A value below 100% does not mean the evidence was inadequate.")

        n["task_scope_banner"] = {
            "primary": ["M1_faithfulness_per_claim", "M2_correctness_per_claim",
                         "M3_core_completeness", "TARGET_ALIGNMENT", "M4A_retrieval_claim_support"],
            "exploratory_non_primary": ["M4B_exploratory_holistic_evidence_adequacy"],
            "seed_bias_diagnostics": ["VALID_SOURCE_SUPPORTED_ALTERNATIVE_BEYOND_REFERENCE",
                                       "POSSIBLE_REFERENCE_DEFECT"],
        }
        out_rows.append(n)

    # --- verify the SAMPLE is untouched, row for row, before writing ---
    problems = []
    if len(out_rows) != len(v1_rows):
        problems.append(f"row count changed: {len(v1_rows)} -> {len(out_rows)}")
    for a, b in zip(v1_rows, out_rows):
        for f in SAMPLE_IDENTITY_FIELDS:
            if json.dumps(a.get(f), sort_keys=True) != json.dumps(b.get(f), sort_keys=True):
                problems.append(f"{a.get('review_case_id')}: sample field {f} changed")
        for f in ("expert_reference", "expert_source_citations", "candidate_draft",
                   "candidate_system_evidence"):
            if json.dumps(a.get(f), sort_keys=True) != json.dumps(b.get(f), sort_keys=True):
                problems.append(f"{a.get('review_case_id')}: material field {f} changed")
    if problems:
        print(f"REFUSED - the sample would have changed ({len(problems)} problems):")
        for p in problems[:10]:
            print(f"  - {p}")
        return 1

    with open(V2, "w", encoding="utf-8") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    meta = {
        "schema_version": "calibration_workbook_v2",
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "derived_from": V1.name,
        "v1_sha256": sha(V1),
        "v2_sha256": sha(V2),
        "sample_unchanged": True,
        "sample_verification": "All 180 rows verified field-for-field: review_case_id, unit_id, "
                                "presentation_position, canonical_name, hierarchy_path, expert_reference, "
                                "expert_source_citations, candidate_draft and candidate_system_evidence "
                                "are byte-identical to v1. Only annotation-field labelling changed.",
        "n_rows": len(out_rows),
        "annotation_schema_changes": [
            "M4_evidence_adequacy renamed to M4B_exploratory_holistic_evidence_adequacy and marked "
            "EXPLORATORY_NON_PRIMARY (value carried through unchanged).",
            "M4A_retrieval_claim_support ADDED - v1 had no field for the decomposed retrieval-coverage "
            "task, which is now the primary retrieval diagnostic.",
            "task_scope_banner added to every row so an annotator can see at a glance which fields are "
            "qualification-gating and which are exploratory.",
        ],
        "v1_retained": "reference_human_calibration_workbook.jsonl is left in place unmodified.",
    }
    META.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"wrote {V2.name} ({len(out_rows)} rows) - sample verified unchanged")
    print(f"wrote {META.name}")
    print(f"  v1 sha256: {meta['v1_sha256'][:16]}...")
    print(f"  v2 sha256: {meta['v2_sha256'][:16]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
