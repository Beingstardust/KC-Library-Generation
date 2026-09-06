#!/usr/bin/env python3
"""Verify the reconstructed topic5x scored-candidates trace rehydration against the real
historical before/after pair.

This is a parsed field-by-field equality check across all 608 rows. It intentionally does
not wire the stage into run-stage or the orchestrator dependency chain.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from kc_l.topic_5p5x.scored_trace_rehydration import (  # noqa: E402
    read_jsonl,
    rehydrate_topic5x_scored_trace_fields,
    sha256_file,
)

PRE_REHYDRATION_JSONL = REPO_ROOT / (
    "data/processed/topic_evidence_stage_v3_scored_candidates/"
    "topic5x_scored_candidates_risk_gated_20260519T194017Z/topic_scored_candidates.jsonl"
)
TYPED_CANDIDATE_BANK_JSONL = REPO_ROOT / (
    "data/processed/topic_evidence_stage_v3_candidate_bank/"
    "topic5x_candidate_bank_typed_from_topic5p_full21_20260519T191223Z/topic_candidate_bank.jsonl"
)
POST_REHYDRATION_JSONL = REPO_ROOT / (
    "data/processed/topic_evidence_stage_v3_scored_candidates/"
    "topic5x_scored_candidates_trace_rehydrated_20260519T194558Z/topic_scored_candidates.jsonl"
)


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        raise SystemExit(f"Verification failed: {label}")


def _candidate_id(row: Mapping[str, Any]) -> str:
    return str(row.get("candidate_id") or "")


def _field_differences(a: Mapping[str, Any], b: Mapping[str, Any]) -> List[str]:
    return [key for key in sorted(set(a) | set(b)) if a.get(key, "<MISSING>") != b.get(key, "<MISSING>")]


def main() -> int:
    check("pre-rehydration scored JSONL exists", PRE_REHYDRATION_JSONL.exists())
    check("typed candidate bank JSONL exists", TYPED_CANDIDATE_BANK_JSONL.exists())
    check("post-rehydration scored JSONL exists", POST_REHYDRATION_JSONL.exists())

    before_rows = read_jsonl(PRE_REHYDRATION_JSONL)
    real_rows = read_jsonl(POST_REHYDRATION_JSONL)

    print(f"pre row count: {len(before_rows)}")
    print(f"historical post row count: {len(real_rows)}")

    changed_target_fields = 0
    stayed_target_fields = 0
    for before_row, real_row in zip(before_rows, real_rows):
        changed = (
            before_row.get("bridge_loader_knowledge_unit_type", "<MISSING>")
            != real_row.get("bridge_loader_knowledge_unit_type", "<MISSING>")
            or before_row.get("topic5p_weak_profile_carry_forward", "<MISSING>")
            != real_row.get("topic5p_weak_profile_carry_forward", "<MISSING>")
        )
        if changed:
            changed_target_fields += 1
        else:
            stayed_target_fields += 1
    print(f"rows changed on bridge_loader_knowledge_unit_type/topic5p_weak_profile_carry_forward: {changed_target_fields}")
    print(f"rows unchanged on those target fields: {stayed_target_fields}")

    example_ids = [
        "cand_33e856392a41b4bf94dbce8f",
        "cand_5402126eef47e7bf05bcb396",
        "cand_791198a857e149e072e51e1d",
    ]
    before_by_id = {_candidate_id(row): row for row in before_rows}
    real_by_id = {_candidate_id(row): row for row in real_rows}
    print("\nconcrete before/after examples:")
    for candidate_id in example_ids:
        before_row = before_by_id[candidate_id]
        real_row = real_by_id[candidate_id]
        print(
            json.dumps(
                {
                    "candidate_id": candidate_id,
                    "before": {
                        "bridge_loader_knowledge_unit_type": before_row.get(
                            "bridge_loader_knowledge_unit_type", "<MISSING>"
                        ),
                        "topic5p_weak_profile_carry_forward": before_row.get(
                            "topic5p_weak_profile_carry_forward", "<MISSING>"
                        ),
                        "topic5x_input_content_risk_tags": before_row.get(
                            "topic5x_input_content_risk_tags", "<MISSING>"
                        ),
                    },
                    "after": {
                        "bridge_loader_knowledge_unit_type": real_row.get("bridge_loader_knowledge_unit_type"),
                        "topic5p_weak_profile_carry_forward": real_row.get("topic5p_weak_profile_carry_forward"),
                        "topic5x_input_content_risk_tags": real_row.get("topic5x_input_content_risk_tags"),
                        "topic5x_input_trace_tags": real_row.get("topic5x_input_trace_tags"),
                    },
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )

    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        result = rehydrate_topic5x_scored_trace_fields(
            source_scored_jsonl=PRE_REHYDRATION_JSONL,
            typed_candidate_bank_jsonl=TYPED_CANDIDATE_BANK_JSONL,
            output_dir=out_dir,
            run_id="verify_topic5x_scored_trace_rehydration_reconstruction",
            source_run_id="topic5x_scored_candidates_risk_gated_20260519T194017Z",
        )
        generated_rows = read_jsonl(out_dir / "topic_scored_candidates.jsonl")
        generated_sha256 = sha256_file(out_dir / "topic_scored_candidates.jsonl")

    check("generated row count is 608", len(generated_rows) == 608)
    check("historical post row count is 608", len(real_rows) == 608)
    check(
        "candidate_id order matches historical post exactly",
        [_candidate_id(row) for row in generated_rows] == [_candidate_id(row) for row in real_rows],
    )

    exact_row_matches = 0
    mismatches = []
    for generated_row, real_row in zip(generated_rows, real_rows):
        if generated_row == real_row:
            exact_row_matches += 1
        else:
            mismatches.append((_candidate_id(real_row), _field_differences(generated_row, real_row), generated_row, real_row))

    print(f"\nparsed field-by-field exact row matches: {exact_row_matches}/608")
    print(f"parsed field-by-field mismatched rows: {len(mismatches)}")
    if mismatches:
        candidate_id, fields, generated_row, real_row = mismatches[0]
        print(f"first mismatch candidate_id: {candidate_id}")
        print(f"first mismatch differing fields: {fields}")
        print("generated row:")
        print(json.dumps(generated_row, ensure_ascii=False, sort_keys=True))
        print("historical row:")
        print(json.dumps(real_row, ensure_ascii=False, sort_keys=True))

    print(f"\ngenerated sha256: {generated_sha256}")
    print(f"historical sha256: {sha256_file(POST_REHYDRATION_JSONL)}")
    print(f"bridge counter: {result['bridge_loader_knowledge_unit_type_counter']}")
    print(f"profile status counter: {result['topic5p_profile_status_counter']}")
    print(f"weak profile counter: {result['topic5p_weak_profile_carry_forward_counter']}")
    print(f"trace counter: {result['trace_counter']}")
    print(f"content risk counter: {result['content_risk_counter']}")
    print(f"soft risk counter: {result['soft_risk_counter']}")
    print(
        "observed content-risk table coverage: "
        f"{result['observed_content_risk_candidate_id_table_hit_count']} hit / "
        f"{result['observed_content_risk_candidate_id_table_nonhit_count']} nonhit "
        f"(of {len(generated_rows)} rows)"
    )
    print(
        "observed soft-risk table coverage: "
        f"{result['observed_soft_risk_candidate_id_table_hit_count']} hit / "
        f"{result['observed_soft_risk_candidate_id_table_nonhit_count']} nonhit "
        f"(of {len(generated_rows)} rows)"
    )
    check(
        "content-risk table hit/nonhit counts sum to total rows",
        result["observed_content_risk_candidate_id_table_hit_count"]
        + result["observed_content_risk_candidate_id_table_nonhit_count"]
        == len(generated_rows),
    )
    check(
        "soft-risk table hit/nonhit counts sum to total rows",
        result["observed_soft_risk_candidate_id_table_hit_count"]
        + result["observed_soft_risk_candidate_id_table_nonhit_count"]
        == len(generated_rows),
    )
    print(f"blind spots: {result['blind_spots']}")
    print(f"fallback/unobserved profile status counter: {result['unobserved_profile_status_counter']}")
    print(
        "fallback/unobserved bridge type counter: "
        f"{result['unobserved_bridge_loader_knowledge_unit_type_counter']}"
    )
    print(f"fallback/unobserved unit type counter: {result['unobserved_knowledge_unit_type_counter']}")

    check("all 608 parsed rows match the historical post artifact exactly", exact_row_matches == 608)
    print("\nALL TOPIC5X SCORED TRACE REHYDRATION RECONSTRUCTION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
