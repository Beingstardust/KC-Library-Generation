from __future__ import annotations

from tests.test_step5x_v3_pack_composition import _row
from kc_l.retrieval_gate.evidence_stage_v3_pack_composition import compose_evidence_packs_from_scored_candidates


def test_ordered_pack_blocks_rejected_false_positive_bucket():
    row = _row(
        roles={"definition_kernel": True, "positive_support_eligible": True},
        text="Cross-validation is a widely-used model evaluation method.",
    )
    row["shapeaware_bucket"] = "rejected_false_positive"
    packs = compose_evidence_packs_from_scored_candidates([row])
    assert packs[0]["ordered_pack_for_drafting"] == []


def test_ordered_pack_blocks_anaphoric_fragment_text():
    row = _row(
        roles={"definition_kernel": True, "positive_support_eligible": True},
        text="This is discussed in the next section.",
    )
    row["shapeaware_bucket"] = "drafting_core"
    packs = compose_evidence_packs_from_scored_candidates([row])
    assert packs[0]["ordered_pack_for_drafting"] == []


def test_shapeaware_core_not_exposed_unless_ordered_admitted():
    row = _row(
        roles={"definition_kernel": True, "positive_support_eligible": True},
        text="This is discussed in the next section.",
    )
    row["shapeaware_bucket"] = "drafting_core"
    packs = compose_evidence_packs_from_scored_candidates([row])
    assert packs[0]["drafting_core_evidence"] == []
    assert any(
        item.get("lane_demotion_reason") == "shapeaware_core_not_admitted_to_ordered_pack_for_drafting"
        for item in packs[0]["review_needed_evidence"]
    )
