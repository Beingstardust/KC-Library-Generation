from __future__ import annotations

from pathlib import Path
import sys
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from kc_l.retrieval_gate.shapeaware_shadow import compose_shapeaware_shadow_pack


def _row(
    *,
    kc_id: str = "KC_X",
    canonical_name: str = "Pearson Product-Moment Correlation",
    text: str = "One of the most used dependence measures is the Pearson correlation coefficient, which measures the degree of linear correlation between two variables.",
    policy_atoms: List[str] | None = None,
    concept_head_terms: List[str] | None = None,
    binding_strength: str = "strong",
    target_bound: bool = True,
    subject_alignment: str = "mismatch",
    guard_blocked: bool = True,
    risk_flags: List[str] | None = None,
) -> Dict[str, Any]:
    policy_atoms = policy_atoms or [canonical_name, "Pearson correlation coefficient"]
    concept_head_terms = concept_head_terms or ["pearson", "correlation"]
    blocker_flags = ["definition_subject_mismatch"] if guard_blocked else []
    return {
        "candidate_id": "cand_x",
        "scored_candidate_id": "cand_x",
        "kc_id": kc_id,
        "canonical_name": canonical_name,
        "aliases": policy_atoms,
        "candidate_text": text,
        "text": text,
        "routing_recommendation": "manual_review_candidate" if guard_blocked else "positive_role_candidate",
        "step5x_retrieval_policy_plan": {
            "canonical_name": canonical_name,
            "lexical_atoms": policy_atoms,
            "concept_head_terms": concept_head_terms,
            "shape_priors": ["target_bound_concept_support", "definition", "formula_or_metric"],
            "sibling_terms": [],
        },
        "lexical_target_binding": {
            "is_target_bound": target_bound,
            "binding_strength": binding_strength,
            "exact_target_phrase_in_text": target_bound,
        },
        "definition_framing_score": {
            "subject_alignment": subject_alignment,
            "definition_style": "explicit",
            "reasons": ["definition_subject_mismatch"] if subject_alignment == "mismatch" else [],
        },
        "positive_support_guard": {
            "blocked_from_positive_support": guard_blocked,
            "blocker_flags": blocker_flags,
            "strict_blocker_flags": blocker_flags,
            "pack_action": "near_miss_review_only" if guard_blocked else "allow_positive_support_candidate",
        },
        "role_eligibility": {},
        "support_profile": {"support_roles": ["definitional_anchor"], "generic_context_only": False},
        "candidate_quality": {"overall_score": 6.0},
        "formula_signal": {},
        "contamination_signals": {},
        "sibling_or_competitor_signals": {},
        "risk_flags": risk_flags or ["definition_subject_mismatch"],
    }


def _core_texts(rows: List[Dict[str, Any]]) -> List[str]:
    pack = compose_shapeaware_shadow_pack(rows[0]["kc_id"], rows)
    return [item["text"] for item in pack["drafting_core_evidence"]]


def test_target_named_measure_gloss_promotes_pearson_subject_mismatch():
    rows = [_row()]
    core = _core_texts(rows)
    assert len(core) == 1
    assert "Pearson correlation coefficient" in core[0]


def test_target_named_measure_gloss_promotes_entropy_with_punctuation_boundary():
    rows = [
        _row(
            kc_id="KC_ENTROPY",
            canonical_name="External Index: Entropy",
            text="An example of a supervised index is entropy, which measures how well cluster labels match externally supplied class labels.",
            policy_atoms=[
                "External Index: Entropy",
                "Entropy",
                "measures how well cluster labels match externally supplied class labels",
            ],
            concept_head_terms=["entropy"],
            risk_flags=["definition_subject_mismatch", "example_like", "needs_stronger_anchor_context"],
        )
    ]
    core = _core_texts(rows)
    assert len(core) == 1
    assert "entropy, which measures" in core[0]


def test_target_named_measure_gloss_promotes_separation_measurement_gloss():
    rows = [
        _row(
            kc_id="KC_SEPARATION",
            canonical_name="Separation",
            text="Similarly, the separation between two clusters can be measured by the proximity of the two cluster prototypes.",
            policy_atoms=["Separation", "separation between two clusters"],
            concept_head_terms=["separation"],
            subject_alignment="missing",
            guard_blocked=False,
            risk_flags=["needs_stronger_anchor_context"],
        )
    ]
    core = _core_texts(rows)
    assert len(core) == 1
    assert "separation between two clusters" in core[0]


def test_target_named_measure_gloss_does_not_promote_exercise_prompt():
    rows = [
        _row(
            kc_id="KC_MISCLASS",
            canonical_name="Misclassification Rate",
            text="Calculate the weighted misclassification rate of the child nodes.",
            policy_atoms=["Misclassification Rate", "weighted misclassification rate"],
            concept_head_terms=["misclassification", "rate"],
            subject_alignment="missing",
            guard_blocked=False,
            risk_flags=["procedure_like", "needs_stronger_anchor_context"],
        )
    ]
    assert _core_texts(rows) == []


def test_target_named_measure_gloss_does_not_promote_without_sentence_target_anchor():
    rows = [
        _row(
            kc_id="KC_ENTROPY",
            canonical_name="External Index: Entropy",
            text="The impurity of a node measures how dissimilar the class labels are for the data instances belonging to a common node.",
            policy_atoms=["External Index: Entropy", "Entropy"],
            concept_head_terms=["entropy"],
            risk_flags=["definition_subject_mismatch"],
        )
    ]
    assert _core_texts(rows) == []


def main() -> None:
    test_target_named_measure_gloss_promotes_pearson_subject_mismatch()
    test_target_named_measure_gloss_promotes_entropy_with_punctuation_boundary()
    test_target_named_measure_gloss_promotes_separation_measurement_gloss()
    test_target_named_measure_gloss_does_not_promote_exercise_prompt()
    test_target_named_measure_gloss_does_not_promote_without_sentence_target_anchor()
    print("TEST_SHAPEAWARE_TARGET_NAMED_MEASURE_GLOSS_OK")


if __name__ == "__main__":
    main()
