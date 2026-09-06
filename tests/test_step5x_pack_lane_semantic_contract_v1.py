from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from kc_l.retrieval_gate.evidence_stage_v3_lane_semantics import (
    evidence_lane_semantics,
    has_automatic_drafting_support,
)
from kc_l.retrieval_gate.evidence_stage_v3_pack_composition import (
    compose_evidence_packs_from_scored_candidates,
)

# Reuse the existing local row factory rather than duplicating synthetic schema.
from test_step5x_v3_pack_composition import _row


def test_raw_shapeaware_core_without_ordered_pack_is_not_automatic_support():
    pack = {
        "drafting_core_evidence": [{"candidate_id": "risky"}],
        "ordered_pack_for_drafting": [],
        "pack_quality": {"route": "insufficient_support_packet", "insufficient_reasons": ["weak_coverage"]},
    }

    semantics = evidence_lane_semantics(pack)

    assert has_automatic_drafting_support(pack) is False
    assert semantics["automatic_drafting_supported"] is False
    assert semantics["automatic_drafting_support_source"] == "ordered_pack_for_drafting"
    assert semantics["ordered_pack_for_drafting_len"] == 0
    assert semantics["drafting_core_evidence_len"] == 1


def test_shapeaware_core_is_demoted_when_not_admitted_to_ordered_pack():
    row = _row(
        text="Cross-validation is a widely-used model evaluation method.",
        roles={"definition_kernel": True, "positive_support_eligible": True},
        risk_flags=["needs_stronger_anchor_context"],
    )
    row["support_profile"] = {"support_roles": ["definitional_anchor"]}
    row["definition_framing_score"] = {"subject_alignment": "aligned", "definition_style": "explicit"}

    pack = compose_evidence_packs_from_scored_candidates([row])[0]

    assert pack["ordered_pack_for_drafting"] == []
    assert pack["drafting_core_evidence"] == []
    assert pack["pack_quality"]["route"] == "insufficient_support_packet"
    assert pack["pack_quality"]["positive_support_count"] == 0
    assert pack["evidence_lane_semantics"]["automatic_drafting_supported"] is False
    assert pack["review_needed_evidence"]
    assert pack["review_needed_evidence"][0]["lane_demotion_reason"] == "shapeaware_core_not_admitted_to_ordered_pack_for_drafting"


def test_clean_ordered_definition_remains_automatic_support():
    row = _row(
        text="Cross-validation is a widely-used model evaluation method.",
        roles={"definition_kernel": True, "positive_support_eligible": True},
    )
    row["support_profile"] = {"support_roles": ["definitional_anchor"]}
    row["definition_framing_score"] = {"subject_alignment": "aligned", "definition_style": "explicit"}

    pack = compose_evidence_packs_from_scored_candidates([row])[0]

    assert pack["ordered_pack_for_drafting"]
    assert pack["drafting_core_evidence"]
    assert pack["pack_quality"]["route"] == "standard_drafting"
    assert pack["pack_quality"]["positive_support_count"] == 1
    assert pack["evidence_lane_semantics"]["automatic_drafting_supported"] is True


def main():
    test_raw_shapeaware_core_without_ordered_pack_is_not_automatic_support()
    test_shapeaware_core_is_demoted_when_not_admitted_to_ordered_pack()
    test_clean_ordered_definition_remains_automatic_support()


if __name__ == "__main__":
    main()
