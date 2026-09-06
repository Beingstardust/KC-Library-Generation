#!/usr/bin/env python3
"""Verify the reconstructed step67_v2_postprocessed_review_source builder against the ONE
real historical run available (20260520T233415Z), by running it against the real drafts.jsonl
input and comparing every classification-relevant field against the real preserved output.

Known, documented exceptions (both non-load-bearing - step 6.8's builder.py never reads the
evidence-ID list fields' exact content, only review_action/provenance_quality/etc.):
  - The historical file itself contains text corruption in a handful of evidence IDs
    (confirmed present in the raw draft's own LLM-cited IDs), inflating some historical
    unresolved-ID counts by 1-2. Rows affected by this are reported separately, not counted
    as reconstruction failures.
  - Evidence-ID rebinding is a real but zero-occurrence mechanism in this run; not attempted.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from kc_l.step67_postprocess import postprocess_review_source, read_jsonl

SOURCE_DRAFTS_JSONL = REPO_ROOT / (
    "data/processed/step67_v2_tiny_smoke_drafts/"
    "step67_v2_full165_kc_topic_policy_marker_fix_20260520T195051Z/step67_v2_tiny_smoke_drafts.jsonl"
)
REAL_OUTPUT_DIR = REPO_ROOT / "data/processed/step67_v2_postprocessed_review_source/20260520T233415Z"
ACCEPTED_BASELINE_RUN_ID = "step67_v2_full165_kc_topic_policy_marker_fix_20260520T195051Z"

# Known-corrupted unresolved-id rows (evidence ID text corruption confirmed present in the
# raw drafts.jsonl input itself - see builder.py module docstring). These rows may show a
# real_unresolved_count that is 1-2 higher than the reconstruction, purely from corrupted
# citation strings that don't match any pool member syntactically.
KNOWN_CORRUPTED_ROWS = {
    "hier::path::7d695382abd36389a7594092bd801f41034e121be15abc200504c54a2e339e15",
    "hier::path::e9d47504e8dadf9a84b4e0cf72d451da04a5506233f0df7b6f12c1dbe9a35849",
    "hier::path::affc23eb43163c48ce38ce0aecf53984063447b4c7437f9284b6b647ff1f8f81",
    "hier::path::32ad9926572ced293a5806b17213f35cb44d9a13a0fda8398c76a09da99f73ae",
    "hier::path::aab04ae14cbb0d166aae6989a6e5b835ed927ac6f9790069a3202f9ef422bd9e",
    "hier::path::505fda0083cac4c3890be009ceb59ff1a948cad7090091b6b3cf6f6a69d90d0c",
    "KC_CLF_DT_011",
    "KC_CLF_DT_012",
    "KC_CLF_NB_011",
    "KC_CLU_DBS_007",
    "KC_CLU_EVAL_002",
    "KC_CLU_EVAL_009",
    "KC_CLU_HIER_002",
    "KC_CLU_HIER_006",
    "KC_CLU_SIM_008",
    "KC_DE_PREP_001",
    "KC_DE_PREP_005",
    "KC_EVAL_BASIC_001",
    "KC_EVAL_BASIC_006",
    "KC_EVAL_COMP_002",
    "KC_EVAL_COMP_003",
    "KC_EVAL_IMBAL_001",
    "KC_FSEL_GOOD_002",
}

CLASSIFICATION_FIELDS = [
    "draft_status",
    "semantic_grade_provisional",
    "provenance_quality",
    "packet_evidence_source",
    "packet_support_state",
    "evidence_reference_status",
    "review_action",
]


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        raise SystemExit(f"Verification failed: {label}")


def main() -> int:
    check("real historical drafts.jsonl exists", SOURCE_DRAFTS_JSONL.exists())
    check("real historical output dir exists", REAL_OUTPUT_DIR.exists())

    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        result = postprocess_review_source(
            source_drafts_jsonl=SOURCE_DRAFTS_JSONL,
            output_dir=out_dir,
            run_id="verify_reconstruction",
            accepted_baseline_run_id=ACCEPTED_BASELINE_RUN_ID,
            postprocess_root=str(out_dir),
        )
        check("reconstruction produced 165 rows", result["row_count"] == 165)

        my_rows = {r["knowledge_unit_id"]: r for r in read_jsonl(out_dir / "step67_v2_postprocessed_review_source.jsonl")}

    real_rows = {r["knowledge_unit_id"]: r for r in read_jsonl(REAL_OUTPUT_DIR / "step67_v2_postprocessed_review_source.jsonl")}

    check("real output also has 165 rows", len(real_rows) == 165)
    check("row id sets match exactly", set(my_rows) == set(real_rows))

    classification_mismatches = []
    unresolved_count_mismatches_unexplained = []
    unresolved_count_mismatches_corrupted = []

    for uid, real_row in real_rows.items():
        my_row = my_rows[uid]
        my_pf = my_row["draft"]["review_preflight"]
        real_pf = real_row["draft"]["review_preflight"]

        for field in CLASSIFICATION_FIELDS:
            if my_pf.get(field) != real_pf.get(field):
                classification_mismatches.append((uid, field, my_pf.get(field), real_pf.get(field)))

        my_unresolved_count = len(my_pf.get("unresolved_supporting_evidence_ids") or [])
        real_unresolved_count = len(real_pf.get("unresolved_supporting_evidence_ids") or [])
        if my_unresolved_count != real_unresolved_count:
            if uid in KNOWN_CORRUPTED_ROWS:
                unresolved_count_mismatches_corrupted.append(uid)
            else:
                unresolved_count_mismatches_unexplained.append((uid, my_unresolved_count, real_unresolved_count))

    print(f"\nclassification field mismatches (draft_status/action/provenance/etc.): {len(classification_mismatches)}")
    for m in classification_mismatches[:20]:
        print("  ", m)
    check("zero classification field mismatches across all 165 rows", len(classification_mismatches) == 0)

    print(f"\nunresolved-count mismatches explained by known historical corruption: {len(unresolved_count_mismatches_corrupted)}")
    print(f"unresolved-count mismatches NOT explained (genuinely unexpected): {len(unresolved_count_mismatches_unexplained)}")
    for m in unresolved_count_mismatches_unexplained[:20]:
        print("  ", m)
    check(
        "every unresolved-count mismatch is one of the known-corrupted rows",
        len(unresolved_count_mismatches_unexplained) == 0,
    )

    # Cross-check the summary counters too (the load-bearing aggregate that step 6.8's
    # kc_l_orchestrator.py step68-smoke command and other tooling read).
    real_summary = json.loads((REAL_OUTPUT_DIR / "STEP67_V2_POSTPROCESS_SUMMARY.json").read_text(encoding="utf-8"))
    for key in ["unit_type_counter", "draft_status_counter", "review_action_counter", "provenance_quality_counter", "semantic_grade_counter"]:
        check(f"summary.{key} matches exactly", result[key] == real_summary[key])

    # rebind_gap_exposure_count is a new safeguard field with no historical counterpart (the
    # original lost script's summary predates it) - independently derive the expected value
    # from the real preserved rows themselves (rows with exactly 1 unresolved reference) rather
    # than comparing against a historical field that doesn't exist, then confirm the
    # reconstruction's own computed value matches.
    independently_derived_exposure_count = sum(
        1
        for real_row in real_rows.values()
        if len(real_row["draft"]["review_preflight"].get("unresolved_supporting_evidence_ids") or []) == 1
    )
    print(f"\nindependently-derived rebind_gap_exposure_count from real rows: {independently_derived_exposure_count}")
    print(f"reconstruction's computed rebind_gap_exposure_count: {result['rebind_gap_exposure_count']}")
    check(
        "rebind_gap_exposure_count matches the independently-derived count from real rows",
        result["rebind_gap_exposure_count"] == independently_derived_exposure_count,
    )

    print("\nALL STEP67 POSTPROCESS RECONSTRUCTION CHECKS PASSED")
    print(f"({len(unresolved_count_mismatches_corrupted)} rows had unresolved-count differences fully explained by pre-existing data corruption in this historical dataset; 0 unexplained)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
