from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from kc_l.kc_drafting.evidence_lane_policy import (  # noqa: E402
    LANE_CONTEXT,
    LANE_DEFINITION,
    LANE_QUARANTINE,
    LANE_SCOPE,
    LANE_SIBLING,
    KCProfile,
    build_lane_packet,
    classify_evidence_item,
)


def _profile(name: str, *, aliases: list[str] | None = None, topic_path_labels: list[str] | None = None) -> KCProfile:
    return KCProfile.from_mapping(
        {
            "kc_id": "alpha-001",
            "canonical_name": name,
            "aliases": aliases or [],
            "topic_path_labels": topic_path_labels or ["Foundations", "Examples"],
        }
    )


def _item(
    quote_text: str,
    *,
    context_text: str = "",
    evidence_id: str = "E1",
    overlay_candidate_id: str = "alpha-001:overlay:01",
    **metadata: object,
) -> dict[str, object]:
    row: dict[str, object] = {
        "evidence_id": evidence_id,
        "overlay_candidate_id": overlay_candidate_id,
        "quote_text": quote_text,
        "context_text": context_text or quote_text,
        "provenance": {"doc_id": "doc.synthetic", "page_index": 0},
    }
    row.update(metadata)
    return row


def test_quote_local_formula_definition_is_promoted() -> None:
    decision = classify_evidence_item(
        _item("Overlap Ratio is defined by the following equation."),
        _profile("Overlap Ratio"),
    )

    assert decision["primary_lane"] == LANE_DEFINITION
    assert decision["decisive_surface"] == "quote_text"


def test_context_formula_leak_does_not_promote_relation_or_usage_quote() -> None:
    decision = classify_evidence_item(
        _item(
            "Overlap Ratio can be used to compare two groups.",
            context_text="Overlap Ratio is defined by the following equation.",
        ),
        _profile("Overlap Ratio"),
    )

    assert decision["primary_lane"] == LANE_SCOPE
    assert "context_definition_leak" in decision["flags"]


def test_reduction_relation_stays_contextual() -> None:
    decision = classify_evidence_item(
        _item("Boundary Object reduces to Alpha Measure when the shared boundary is fixed."),
        _profile("Boundary Object"),
    )

    assert decision["primary_lane"] == LANE_CONTEXT


def test_generalization_relation_stays_contextual() -> None:
    decision = classify_evidence_item(
        _item("Boundary Object is a generalization of Alpha Measure for grouped inputs."),
        _profile("Boundary Object"),
    )

    assert decision["primary_lane"] == LANE_CONTEXT


def test_use_case_quote_becomes_scope_not_definition() -> None:
    decision = classify_evidence_item(
        _item("Delta Procedure is used for ranking candidate revisions when inputs arrive late."),
        _profile("Delta Procedure"),
    )

    assert decision["primary_lane"] == LANE_SCOPE


def test_negative_contrast_becomes_sibling_lane() -> None:
    decision = classify_evidence_item(
        _item("Unlike Boundary Object, Rule Table stores fixed outputs rather than shared boundary data."),
        _profile("Boundary Object"),
    )

    assert decision["primary_lane"] == LANE_SIBLING


def test_incomplete_fragment_is_quarantined() -> None:
    decision = classify_evidence_item(
        _item("Rule Table in the context of"),
        _profile("Rule Table"),
    )

    assert decision["primary_lane"] == LANE_QUARANTINE


def test_unfinished_modifier_tail_is_quarantined() -> None:
    decision = classify_evidence_item(
        _item("Delta Procedure is a generic procedure for arranging values in a greedy"),
        _profile("Delta Procedure"),
    )

    assert decision["primary_lane"] == LANE_QUARANTINE


def test_exercise_prompt_is_quarantined() -> None:
    decision = classify_evidence_item(
        _item("Compute the Delta Procedure for the given sample."),
        _profile("Delta Procedure"),
    )

    assert decision["primary_lane"] == LANE_QUARANTINE


def test_missing_target_anchor_never_promotes_definition() -> None:
    decision = classify_evidence_item(
        _item(
            "This is defined by the following equation.",
            context_text="The value is calculated as the aligned total divided by the baseline total.",
        ),
        _profile("Alpha Measure"),
    )

    assert decision["primary_lane"] != LANE_DEFINITION
    assert decision["primary_lane"] == LANE_QUARANTINE


def test_build_lane_packet_preserves_structural_kc_id_without_using_it_for_binding() -> None:
    lane_packet = build_lane_packet(
        {
            "kc_id": "rule-777",
            "canonical_name": "Alpha Measure",
            "aliases": [],
            "topic_path_labels": ["Foundations", "Examples"],
            "evidence": [
                {
                    "evidence_id": "E1",
                    "overlay_candidate_id": "rule-777:overlay:01",
                    "text": "Alpha Measure is defined as the base comparison value.",
                }
            ],
        }
    )

    assert lane_packet["kc_id"] == "rule-777"
    assert lane_packet["definition_lane"][0]["evidence_id"] == "E1"


def test_using_target_to_clause_is_not_definition() -> None:
    decision = classify_evidence_item(
        _item("Using Alpha Method to find three groups."),
        _profile("Alpha Method"),
    )

    assert decision["primary_lane"] == LANE_SCOPE


def test_steps_of_target_clause_is_context_not_definition() -> None:
    decision = classify_evidence_item(
        _item("Steps 3 and 4 of Alpha Method directly attempt to minimize the objective."),
        _profile("Alpha Method"),
    )

    assert decision["primary_lane"] == LANE_CONTEXT


def test_target_is_then_applied_clause_is_context_not_definition() -> None:
    decision = classify_evidence_item(
        _item("Alpha Method is then recursively applied to each child."),
        _profile("Alpha Method"),
    )

    assert decision["primary_lane"] == LANE_CONTEXT


def test_often_used_clause_is_scope_not_definition() -> None:
    decision = classify_evidence_item(
        _item("Alpha Measure is often used in the literature."),
        _profile("Alpha Measure"),
    )

    assert decision["primary_lane"] == LANE_SCOPE


def test_most_commonly_used_clause_is_scope_not_definition() -> None:
    decision = classify_evidence_item(
        _item("Alpha Measure is the most commonly used in the literature."),
        _profile("Alpha Measure"),
    )

    assert decision["primary_lane"] == LANE_SCOPE


def test_tendency_clause_is_scope_not_definition() -> None:
    decision = classify_evidence_item(
        _item("Alpha Measure has a tendency to select wider intervals."),
        _profile("Alpha Measure"),
    )

    assert decision["primary_lane"] == LANE_SCOPE


def test_subject_copula_definition_is_promoted() -> None:
    decision = classify_evidence_item(
        _item("Beta Table is a table that summarizes predictions."),
        _profile("Beta Table"),
    )

    assert decision["primary_lane"] == LANE_DEFINITION


def test_article_led_subject_copula_definition_is_promoted() -> None:
    decision = classify_evidence_item(
        _item("A Beta Table is a table that summarizes predictions."),
        _profile("Beta Table"),
    )

    assert decision["primary_lane"] == LANE_DEFINITION


def test_called_target_case_is_promoted() -> None:
    decision = classify_evidence_item(
        _item("This information is summarized in a table called a Beta Table."),
        _profile("Beta Table"),
    )

    assert decision["primary_lane"] == LANE_DEFINITION


def test_truncated_called_target_fragment_is_quarantined() -> None:
    decision = classify_evidence_item(
        _item("Summarized in a table called a Beta Table."),
        _profile("Beta Table"),
    )

    assert decision["primary_lane"] == LANE_QUARANTINE


def test_special_case_relation_stays_contextual() -> None:
    decision = classify_evidence_item(
        _item("Gamma Score is a special case of Delta Score."),
        _profile("Gamma Score"),
    )

    assert decision["primary_lane"] == LANE_CONTEXT


def test_short_target_collision_does_not_promote_definition() -> None:
    decision = classify_evidence_item(
        _item("The min-max scaling method is defined as the bounded scaling rule."),
        _profile("MX (Merge Extension)"),
    )

    assert decision["primary_lane"] != LANE_DEFINITION


def test_called_clause_requires_exact_target_phrase() -> None:
    decision = classify_evidence_item(
        _item("The archive is summarized in a tree diagram called a Branch Map."),
        _profile("Branch Tree Layout"),
    )

    assert decision["primary_lane"] != LANE_DEFINITION


def test_called_clause_does_not_promote_subphrase_inside_longer_name() -> None:
    decision = classify_evidence_item(
        _item("This rule is called a Signal Function when evaluated."),
        _profile("Signal"),
    )

    assert decision["primary_lane"] != LANE_DEFINITION




def test_surface_only_wrong_source_heading_is_quarantined() -> None:
    decision = classify_evidence_item(
        _item(
            "Alpha Charge is a required account fee.",
            context_text="Alpha Charge is a required account fee during account filing.",
            page_heading_norm="Account Fees",
            patch_heading="Account Fees",
        ),
        _profile("Alpha Charge", topic_path_labels=["Systems", "Signal Circuits", "Alpha Charge"]),
    )

    assert decision["primary_lane"] == LANE_QUARANTINE
    assert "source_sense_demoted" in decision["flags"]
    assert decision["source_sense_status"] == "cross_sense_risk"


def test_same_surface_target_branch_context_is_retained() -> None:
    decision = classify_evidence_item(
        _item(
            "Alpha Charge is a required value in signal circuits.",
            context_text="Signal circuits use Alpha Charge as a required value for the target branch.",
            page_heading_norm="Signal Circuits",
            patch_heading="Signal Circuits",
        ),
        _profile("Alpha Charge", topic_path_labels=["Systems", "Signal Circuits", "Alpha Charge"]),
    )

    assert decision["primary_lane"] == LANE_DEFINITION
    assert decision["source_sense_status"] == "same_sense_positive"
    assert "source_sense_demoted" not in decision["flags"]




def test_heading_surface_family_match_retains_same_family_heading() -> None:
    decision = classify_evidence_item(
        _item(
            "Boundary Object is a marker used in the local system.",
            context_text="The local system describes Boundary Object together with neighboring objects.",
            page_heading_norm="Boundary and Interior Objects",
            patch_heading="Boundary and Interior Objects",
        ),
        _profile("Boundary Object", topic_path_labels=["Systems", "Signal Circuits", "Boundary Object"]),
    )

    assert decision["primary_lane"] == LANE_DEFINITION
    assert decision["source_sense_status"] == "same_sense_positive"
    assert "source_sense_heading_surface_family" in decision["flags"]
    assert "source_sense_demoted" not in decision["flags"]



def test_broad_branch_only_with_weak_surface_is_quarantined() -> None:
    decision = classify_evidence_item(
        _item(
            "Object x is called a complete object when all values are present.",
            context_text="In grouping imputation, an object is called a complete object when all values are present.",
            page_heading_norm="Neighbor Grouping Imputation",
            patch_heading="Neighbor Grouping Imputation",
        ),
        _profile("Complete Method", topic_path_labels=["Systems", "Grouping", "Hierarchical Grouping", "Complete Method"]),
    )

    assert decision["primary_lane"] == LANE_QUARANTINE
    assert decision["source_sense_status"] == "cross_sense_risk"
    assert "source_sense_broad_branch_only" in decision["flags"]
    # It is enough that this item is not allowed into a positive evidence lane.
    # source_sense_demoted is only required when an item was first positive
    # and then demoted by source-sense logic; already-quarantined items need
    # not carry that flag.


def test_broad_branch_with_exact_target_anchor_is_retained_for_review() -> None:
    decision = classify_evidence_item(
        _item(
            "The SQE value is lower when the representative object is closer.",
            context_text="For grouping quality, SQE is used as an objective value for choosing representatives.",
            page_heading_norm="Representative Objectives",
            patch_heading="Representative Objectives",
        ),
        _profile("SQE (Sequence Quality)", aliases=["SQE"], topic_path_labels=["Systems", "Grouping", "Sequence Quality", "SQE"]),
    )

    assert decision["primary_lane"] in {LANE_CONTEXT, LANE_SCOPE}
    assert decision["source_sense_status"] == "same_sense_positive"
    # The important invariant is that an exact target anchor is retained for
    # review and not demoted. It may be retained through broad-branch support,
    # specific-branch support, or another stronger same-sense route.
    assert "source_sense_demoted" not in decision["flags"]



def test_for_leadin_complete_target_definition_is_not_fragmentary() -> None:
    decision = classify_evidence_item(
        _item(
            "For the Delta Link or MX version of layered grouping, the distance between two groups is defined as the largest distance between any members of the two groups.",
            context_text="For the Delta Link or MX version of layered grouping, the distance between two groups is defined as the largest distance between any members of the two groups.",
            page_heading_norm="Delta Link grouping example",
            patch_heading="Delta Link grouping example",
        ),
        _profile(
            "MX (Delta Linkage)",
            aliases=["MX", "Delta Link"],
            topic_path_labels=["Systems", "Grouping", "Layered Grouping", "Delta Linkage"],
        ),
    )

    assert decision["primary_lane"] == LANE_DEFINITION
    assert "fragmentary_quote" not in decision["flags"]
    assert decision["source_sense_status"] == "same_sense_positive"
    assert "source_sense_demoted" not in decision["flags"]

def _run_direct() -> None:
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            value()
    print("TEST_EVIDENCE_LANE_POLICY_OK")


if __name__ == "__main__":
    _run_direct()
