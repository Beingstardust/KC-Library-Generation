from kc_l.utils.kc_step67_model_drafting import _definition_binding_replacement_is_strictly_better
from kc_l.kc_drafting.heuristic_core import _definition_support_pack_variant_allowed


def test_binding_replacement_allows_cleaner_same_kc_swap_with_margin():
    current = {
        "reject_reasons": ["context_only_anchor", "procedure_or_example_anchor"],
        "overlap_count": 20,
        "binding_score": 39.0,
    }
    proposed = {
        "reject_reasons": [],
        "overlap_count": 1,
        "binding_score": 70.0,
    }
    assert _definition_binding_replacement_is_strictly_better(
        current_analysis=current,
        proposed_analysis=proposed,
    )


def test_binding_replacement_still_rejects_no_margin_swap():
    current = {
        "reject_reasons": ["context_only_anchor", "procedure_or_example_anchor"],
        "overlap_count": 8,
        "binding_score": 52.0,
    }
    proposed = {
        "reject_reasons": [],
        "overlap_count": 1,
        "binding_score": 57.0,
    }
    assert not _definition_binding_replacement_is_strictly_better(
        current_analysis=current,
        proposed_analysis=proposed,
    )


def test_support_pack_blocks_example_like_non_relational_variant():
    row = {
        "is_example_like": True,
        "is_procedure_like": False,
        "canonical_name": "Random Subsampling",
        "aliases": [],
        "seed_definition": "Repeated random train/test splits for model evaluation.",
    }
    assessment = {
        "usable_evidence": True,
        "question_like": False,
        "bare_heading": False,
        "contamination_block": False,
        "background_drift_block": False,
        "concept_mix_block": False,
        "definition_candidate": False,
        "context_candidate": True,
        "equation_support": False,
        "formula_candidate": False,
    }
    allowed, relation_score = _definition_support_pack_variant_allowed(
        row=row,
        assessment=assessment,
        text="For example, split the data several times and average the result.",
    )
    assert not allowed
    assert relation_score == 0.0


def test_support_pack_keeps_example_like_row_when_it_is_explicitly_definitional():
    row = {
        "is_example_like": True,
        "is_procedure_like": False,
        "canonical_name": "Prior Probability",
        "aliases": [],
        "seed_definition": "Probability of a class before observing other attributes.",
    }
    assessment = {
        "usable_evidence": True,
        "question_like": False,
        "bare_heading": False,
        "contamination_block": False,
        "background_drift_block": False,
        "concept_mix_block": False,
        "definition_candidate": True,
        "context_candidate": False,
        "equation_support": False,
        "formula_candidate": False,
    }
    allowed, relation_score = _definition_support_pack_variant_allowed(
        row=row,
        assessment=assessment,
        text="The prior probability captures the class distribution before observing the attributes.",
    )
    assert allowed
    assert relation_score >= 0.0
