#!/usr/bin/env python3
"""Verify the 2026-07-16 fix to src/kc_l/review_packets/builder.py's validate_review_packets():
it used to hard-assert packet_count==165/kc==144/topic==21/segmentable_gap_review==19 - the
exact counts of ONE historical run (20260520T151731Z_policy_repair_replay's "full165"), not a
real correctness invariant. A real production run (20260714T131417Z_9e856df6, 159 KC + 22
topic = 181 packets, after fixing the upstream stale-pointer bugs investigated the same night)
hard-failed step_06_8_review_packet_emission purely because of this mismatch, with otherwise
zero real issues.

Builds synthetic packets matching the REAL run's actual distribution (159 kc + 22 topic) rather
than committing the real 13MB review-packets file as a fixture - the check only needs a handful
of top-level fields per packet, not full packet content.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from kc_l.review_packets.builder import ALLOWED_REVIEWER_ACTIONS, validate_review_packets


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        raise SystemExit(f"Verification failed: {label}")


def _make_valid_packet(uid: str, utype: str) -> dict:
    return {
        "knowledge_unit_id": uid,
        "knowledge_unit_type": utype,
        "canonical_name": f"Name for {uid}",
        "review_preflight": {"checked": True},
        "reviewer_decision": {"status": "pending"},
        "allowed_reviewer_actions": list(ALLOWED_REVIEWER_ACTIONS),
        "review_mode": "standard_review",
        "step68_packetization_metadata": {},
        "source_row": {
            "source_packet": {
                "evidence_for_synthesis": [
                    {"text": "some real evidence text", "doc_id": "DOC_X", "sentence_id": "s1", "page_index": 3}
                ],
            },
        },
    }


def _make_packet_set(kc_count: int, topic_count: int) -> list[dict]:
    packets = [_make_valid_packet(f"KC_{i:03d}", "kc") for i in range(kc_count)]
    packets += [_make_valid_packet(f"TOPIC_{i:03d}", "topic") for i in range(topic_count)]
    return packets


def main() -> int:
    print("=== This run's real distribution (159 kc + 22 topic = 181) must now PASS ===")
    real_shaped_packets = _make_packet_set(159, 22)
    result = validate_review_packets(real_shaped_packets)
    check(f"decision is PASS (was: FAIL due to the hardcoded 165/144/21 mismatch)", result["decision"] == "PASS_STEP68_CURRENT_REVIEW_PACKET_VALIDATION")
    check("issues list is empty", result["issues"] == [])
    check("real unit_type_counter reports kc=159 (not the old hardcoded 144)", result["unit_type_counter"]["kc"] == 159)
    check("real unit_type_counter reports topic=22 (not the old hardcoded 21)", result["unit_type_counter"]["topic"] == 22)
    check("packet_count reports the real 181 (not the old hardcoded 165)", result["packet_count"] == 181)
    check("expected_counts_ok field no longer exists (removed, not left as a vestigial always-true flag)", "expected_counts_ok" not in result)

    print("\n=== The OLD historical run's own counts (144 kc + 21 topic = 165) must ALSO still PASS ===")
    # Confirms this isn't just "165 is no longer hardcoded" but genuinely count-independent -
    # the historical full165 run itself would still validate cleanly under the new logic.
    old_shaped_packets = _make_packet_set(144, 21)
    result_old = validate_review_packets(old_shaped_packets)
    check("historical-shaped packet set also passes now (count-independent, not count-165-only)", result_old["decision"] == "PASS_STEP68_CURRENT_REVIEW_PACKET_VALIDATION")

    print("\n=== A genuinely broken packet must still be caught (regression: other checks untouched) ===")
    broken_packets = _make_packet_set(159, 22)
    broken_packets[0] = dict(broken_packets[0])
    broken_packets[0]["canonical_name"] = ""  # missing identity - a real, unrelated defect
    result_broken = validate_review_packets(broken_packets)
    check(
        "a genuinely broken packet (missing canonical_name) still fails validation",
        result_broken["decision"] == "FAIL_STEP68_CURRENT_REVIEW_PACKET_VALIDATION",
    )
    check(
        "the specific missing_identity issue is reported",
        any("missing_identity" in issue for issue in result_broken["issues"]),
    )

    print("\n=== A packet with 'reject' in allowed actions must still be caught (regression) ===")
    reject_packets = _make_packet_set(1, 0)
    reject_packets[0] = dict(reject_packets[0])
    reject_packets[0]["allowed_reviewer_actions"] = list(ALLOWED_REVIEWER_ACTIONS) + ["reject"]
    result_reject = validate_review_packets(reject_packets)
    check(
        "a packet with a 'reject' action still fails validation",
        result_reject["decision"] == "FAIL_STEP68_CURRENT_REVIEW_PACKET_VALIDATION",
    )
    check(
        "the specific reject_action_present issue is reported",
        any("reject_action_present" in issue for issue in result_reject["issues"]),
    )

    print("\nALL review_packet_count_gate_removed CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
