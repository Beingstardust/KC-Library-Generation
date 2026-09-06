#!/usr/bin/env python3
"""Verify the 2026-07-16 partial-insufficient-support repair added to
run_step67_v2_policy_segmentable_abstention_marker_fix.py.

Background: the existing "segmentable abstention" repair only tolerates FULL abstention
(model outputs nothing). A real production run (20260714T131417Z_9e856df6) hit a KC
(KC_CLU_EVAL_007, "Models of Randomness (Approach 2)") where the model honestly attempted a
short PARTIAL draft (status="partial", 152 real chars, 1 cited evidence id) from genuinely
thin evidence (1 real evidence_for_synthesis item on the packet, model's own uncertainty_notes
explicitly saying evidence was "extremely limited... only a fragment") - this failed
validate_output()'s len(text) < 180 check with no path to acceptance, hard-stopping the whole
181-packet drafting job on this single KC (confirmed twice, byte-identical failure both times -
not stochastic).

Uses the REAL packet + REAL draft row fetched from that actual failed run as fixtures (not
synthetic), confirming the fix accepts the exact real case that motivated it. Also exercises
negative cases (more evidence, no insufficiency language, an unrelated co-occurring validation
issue, more supporting_evidence_ids) to confirm no false positives, and confirms the pre-existing
full-abstention repair path is unaffected (no false negatives / regressions).
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
CHAIN_DIR = REPO_ROOT / "steps/step_06_7_kc_draft_generation/scripts/v2_chain"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

POLICY_RUNNER = CHAIN_DIR / "run_step67_v2_policy_segmentable_abstention_marker_fix.py"
FINAL_SCHEMA_RUNNER = CHAIN_DIR / "run_step67_v2_topic_schema_dict_aligned.py"
SOURCE_SCHEMA_RUNNER = CHAIN_DIR / "run_step67_v2_schema_contract_probe.py"
BASE_RUNNER = REPO_ROOT / "scripts/experimental/run_step67_v2_tiny_smoke.py"

REAL_PACKET_PATH = FIXTURES_DIR / "kc_clu_eval_007_real_packet.json"
REAL_DRAFT_ROW_PATH = FIXTURES_DIR / "kc_clu_eval_007_real_draft_row.json"


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        raise SystemExit(f"Verification failed: {label}")


def _load_policy_module():
    os.environ["KC_L_FINAL_SCHEMA_RUNNER"] = str(FINAL_SCHEMA_RUNNER)
    os.environ["KC_L_SOURCE_SCHEMA_RUNNER"] = str(SOURCE_SCHEMA_RUNNER)
    spec = importlib.util.spec_from_file_location("policy_partial_support_test", POLICY_RUNNER)
    assert spec is not None and spec.loader is not None
    policy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(policy)
    policy.load_base_runner_policy(BASE_RUNNER)
    return policy


def main() -> int:
    for label, path in [
        ("real packet fixture", REAL_PACKET_PATH),
        ("real draft row fixture", REAL_DRAFT_ROW_PATH),
    ]:
        check(f"{label} exists: {path}", path.exists())

    real_packet: dict[str, Any] = json.loads(REAL_PACKET_PATH.read_text(encoding="utf-8"))
    real_draft_row: dict[str, Any] = json.loads(REAL_DRAFT_ROW_PATH.read_text(encoding="utf-8"))
    real_draft: dict[str, Any] = real_draft_row["draft"]

    check(
        "real fixture's evidence_for_synthesis has exactly 1 item (genuinely thin, as investigated)",
        len(real_packet.get("evidence_for_synthesis") or []) == 1,
    )
    check(
        "real fixture's contextual_kc_draft.text is under the 180-char threshold",
        len(real_draft["contextual_kc_draft"]["text"]) < 180,
    )
    check(
        "real fixture's contextual_kc_draft.status is 'partial' (not full abstention)",
        real_draft["contextual_kc_draft"]["status"] == "partial",
    )

    policy = _load_policy_module()

    print("\n=== Positive: the real, actual failing case must now be tolerated ===")
    normalized, actions = policy.normalize_draft_from_packet_policy(real_packet, copy.deepcopy(real_draft))
    check(
        f"real case is repaired (actions={actions})",
        policy._PARTIAL_INSUFFICIENT_SUPPORT_MARKER in actions,
    )
    check(
        "repaired draft's contextual_kc_draft.status is still 'partial' (not converted to abstained)",
        normalized["contextual_kc_draft"]["status"] == "partial",
    )
    check(
        "repaired draft's real text is preserved verbatim (not wiped like full-abstention repair)",
        normalized["contextual_kc_draft"]["text"] == real_draft["contextual_kc_draft"]["text"],
    )
    check(
        "repaired draft's real supporting_evidence_ids are preserved verbatim",
        normalized["contextual_kc_draft"]["supporting_evidence_ids"]
        == real_draft["contextual_kc_draft"]["supporting_evidence_ids"],
    )
    final_issues = policy.validate_output_policy(real_packet, normalized)
    check(f"validate_output_policy() now returns zero issues (was: kc_contextual_draft_missing_or_too_short)", final_issues == [])

    print("\n=== Negative: more than 1 supporting_evidence_ids -> must NOT repair ===")
    draft_more_evidence_ids = copy.deepcopy(real_draft)
    draft_more_evidence_ids["contextual_kc_draft"]["supporting_evidence_ids"] = ["cand_a", "cand_b"]
    normalized2, actions2 = policy.normalize_draft_from_packet_policy(real_packet, draft_more_evidence_ids)
    check(
        "not repaired when >1 supporting_evidence_ids cited",
        policy._PARTIAL_INSUFFICIENT_SUPPORT_MARKER not in actions2,
    )
    issues2 = policy.validate_output_policy(real_packet, normalized2)
    check("validation still fails (too-short) when >1 evidence ids cited", len(issues2) == 1)

    print("\n=== Negative: packet's own real evidence pool is NOT thin -> must NOT repair ===")
    packet_more_evidence = copy.deepcopy(real_packet)
    extra_item = copy.deepcopy(packet_more_evidence["evidence_for_synthesis"][0])
    packet_more_evidence["evidence_for_synthesis"] = [extra_item, extra_item, extra_item, extra_item]
    normalized3, actions3 = policy.normalize_draft_from_packet_policy(packet_more_evidence, copy.deepcopy(real_draft))
    check(
        "not repaired when packet has >2 real evidence_for_synthesis items",
        policy._PARTIAL_INSUFFICIENT_SUPPORT_MARKER not in actions3,
    )
    issues3 = policy.validate_output_policy(packet_more_evidence, normalized3)
    check("validation still fails (too-short) when packet evidence pool is not thin", len(issues3) == 1)

    print("\n=== Negative: no insufficiency language in the model's own notes -> must NOT repair ===")
    draft_no_markers = copy.deepcopy(real_draft)
    draft_no_markers["contextual_kc_draft"]["uncertainty_notes"] = ["The tree-growing procedure was mentioned briefly in passing."]
    normalized4, actions4 = policy.normalize_draft_from_packet_policy(real_packet, draft_no_markers)
    check(
        "not repaired when the model's own notes don't express insufficiency",
        policy._PARTIAL_INSUFFICIENT_SUPPORT_MARKER not in actions4,
    )
    issues4 = policy.validate_output_policy(real_packet, normalized4)
    check("validation still fails (too-short) when no insufficiency language present", len(issues4) == 1)

    print("\n=== Negative: an UNRELATED co-occurring validation issue -> must NOT repair either issue ===")
    # knowledge_unit_id/type and kc_specific_criteria* are deterministically self-corrected by
    # the base runner's own normalize_draft_from_packet() regardless of policy - segmentation_
    # support is untouched by it, so removing it is a genuinely independent validation issue.
    draft_missing_segmentation = copy.deepcopy(real_draft)
    del draft_missing_segmentation["segmentation_support"]
    normalized5, actions5 = policy.normalize_draft_from_packet_policy(real_packet, draft_missing_segmentation)
    check(
        "not repaired when a genuinely unrelated validation issue co-occurs",
        policy._PARTIAL_INSUFFICIENT_SUPPORT_MARKER not in actions5,
    )
    issues5 = policy.validate_output_policy(real_packet, normalized5)
    issue_codes5 = {i["code"] for i in issues5}
    check(
        f"both the unrelated issue AND the too-short issue still surface (codes={issue_codes5})",
        "segmentation_support_missing" in issue_codes5 and "kc_contextual_draft_missing_or_too_short" in issue_codes5,
    )

    print("\n=== Regression: a normal, adequately-supported draft is completely unaffected ===")
    good_draft = copy.deepcopy(real_draft)
    good_draft["contextual_kc_draft"]["text"] = "X" * 200
    good_draft["contextual_kc_draft"]["status"] = "complete"
    good_draft["evidence_map"] = [{"claim": "x", "supporting_evidence_ids": ["cand_3f1d7971686f4c38dbc53fbe"]}]
    normalized6, actions6 = policy.normalize_draft_from_packet_policy(real_packet, good_draft)
    check(
        "a long, complete draft triggers neither repair path",
        policy._PARTIAL_INSUFFICIENT_SUPPORT_MARKER not in actions6
        and "policy_segmentable_abstention_repair" not in actions6,
    )

    print("\n=== Regression: the pre-existing FULL abstention repair path is unaffected ===")
    abstained_draft = copy.deepcopy(real_draft)
    abstained_draft["contextual_kc_draft"] = {
        "status": "abstained",
        "text": "",
        "supporting_evidence_ids": [],
        "coverage_notes": [],
        "uncertainty_notes": ["insufficient evidence was found for this knowledge component."],
    }
    abstained_draft["evidence_map"] = []
    normalized7, actions7 = policy.normalize_draft_from_packet_policy(real_packet, abstained_draft)
    check(
        "full abstention still repairs via the ORIGINAL policy_segmentable_abstention_repair path",
        "policy_segmentable_abstention_repair" in actions7,
    )
    check(
        "full abstention repair does NOT also fire the new partial-support marker",
        policy._PARTIAL_INSUFFICIENT_SUPPORT_MARKER not in actions7,
    )
    issues7 = policy.validate_output_policy(real_packet, normalized7)
    check("full abstention case still validates cleanly (regression check)", issues7 == [])

    print("\nALL partial_insufficient_support_repair CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
