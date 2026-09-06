from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from kc_l.retrieval_gate.evidence_stage_v3_lane_semantics import (
    classify_evidence_pack_lane,
    evidence_lane_membership_index,
    evidence_lane_semantics,
    has_automatic_drafting_support,
)
from kc_l.kc.drafting_input_overlay import _evidence_pack_payload


def _item(candidate_id: str = "cand1") -> dict:
    return {
        "candidate_id": candidate_id,
        "source_candidate_id": candidate_id,
        "scored_candidate_id": candidate_id,
        "text": "source grounded evidence text",
    }


def test_lane_semantics_counts_only_drafting_core_as_automatic_support():
    review_only = {"review_needed_evidence": [_item("review1")]}
    rejected_only = {"rejected_false_positive_evidence": [_item("reject1")]}
    insufficient_only = {"pack_quality": {"insufficient_reasons": ["weak_coverage"]}}
    needs_only = {"expected_evidence_needs": [{"need": "definition_concept"}]}
    core = {"drafting_core_evidence": [_item("core1")]}
    mixed = {
        "drafting_core_evidence": [_item("core1")],
        "review_needed_evidence": [_item("review1")],
        "rejected_false_positive_evidence": [_item("reject1")],
    }

    assert classify_evidence_pack_lane(review_only) == "review_only"
    assert classify_evidence_pack_lane(rejected_only) == "rejected_only"
    assert classify_evidence_pack_lane(insufficient_only) == "insufficient_only"
    assert classify_evidence_pack_lane(needs_only) == "expected_needs_only"
    assert classify_evidence_pack_lane(core) == "true_empty_or_unknown_schema"
    assert classify_evidence_pack_lane(mixed) == "mixed_review_and_rejected"
    assert classify_evidence_pack_lane(
        {"ordered_pack_for_drafting": [_item("core1")], "drafting_core_evidence": [_item("core1")]}
    ) == "core_ready"

    assert not has_automatic_drafting_support(review_only)
    assert not has_automatic_drafting_support(rejected_only)
    assert not has_automatic_drafting_support(insufficient_only)
    assert not has_automatic_drafting_support(needs_only)
    assert not has_automatic_drafting_support(core)
    assert not has_automatic_drafting_support(mixed)

    ordered_core = {"ordered_pack_for_drafting": [_item("core1")], "drafting_core_evidence": [_item("core1")]}
    assert has_automatic_drafting_support(ordered_core)

    assert evidence_lane_semantics(review_only)["automatic_drafting_support_source"] == "ordered_pack_for_drafting"
    assert evidence_lane_semantics(review_only)["non_drafting_lanes_are_not_success"] is True


def test_lane_membership_is_separate_from_slot_membership():
    pack = {
        "drafting_core_evidence": [_item("core1")],
        "review_needed_evidence": [_item("review1")],
        "rejected_false_positive_evidence": [_item("reject1")],
    }
    index = evidence_lane_membership_index(pack)

    assert index["core1"]["selected_for_drafting_core"] is True
    assert index["core1"]["drafting_core_positions"] == [0]
    assert index["review1"]["selected_for_drafting_core"] is False
    assert index["review1"]["review_needed_positions"] == [0]
    assert index["reject1"]["selected_for_drafting_core"] is False
    assert index["reject1"]["rejected_false_positive_positions"] == [0]


def test_step66_payload_exposes_lane_semantics_and_does_not_promote_review_only():
    review_pack = {
        "pack_version": "step5x_v3_evidence_packs_v1",
        "pack_quality": {"route": "partial_grounded_packet"},
        "slots": {"definition_kernel": [_item("review1")]},
        "ordered_pack_for_drafting": [_item("review1")],
        "drafting_core_evidence": [],
        "review_needed_evidence": [_item("review1")],
        "rejected_false_positive_evidence": [],
        "provenance_sidecar": {},
    }

    payload = _evidence_pack_payload(
        evidence_pack_row=review_pack,
        pack_candidate_id="review1",
        pack_membership_index=None,
    )

    assert payload["evidence_lane_semantics"]["automatic_drafting_supported"] is False
    assert payload["evidence_lane_semantics"]["lane"] == "review_only"
    assert payload["evidence_pack_membership"]["selected_for_drafting_core"] is False
    assert payload["evidence_pack_membership"]["review_needed_positions"] == [0]


def test_step66_payload_marks_drafting_core_membership_only_for_core_lane():
    core_pack = {
        "pack_version": "step5x_v3_evidence_packs_v1",
        "pack_quality": {"route": "standard_drafting"},
        "slots": {"definition_kernel": [_item("core1")]},
        "ordered_pack_for_drafting": [_item("core1")],
        "drafting_core_evidence": [_item("core1")],
        "review_needed_evidence": [],
        "rejected_false_positive_evidence": [],
        "provenance_sidecar": {},
    }

    payload = _evidence_pack_payload(
        evidence_pack_row=core_pack,
        pack_candidate_id="core1",
        pack_membership_index=None,
    )

    assert payload["evidence_lane_semantics"]["automatic_drafting_supported"] is True
    assert payload["evidence_lane_semantics"]["lane"] == "core_ready"
    assert payload["evidence_pack_membership"]["selected_for_drafting_core"] is True
    assert payload["evidence_pack_membership"]["drafting_core_positions"] == [0]
