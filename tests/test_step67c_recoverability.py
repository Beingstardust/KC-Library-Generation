from kc_l.kc_drafting.step67c_recoverability import (
    RECOVERABILITY_A_DIRECT,
    RECOVERABILITY_B_NORMALIZED,
    RECOVERABILITY_C_NOT_RECOVERABLE,
    _recoverability_class,
    _seed_shape,
)


def test_seed_shape_detects_formula_and_conditions():
    bundle = {
        "canonical_name": "Nemenyi Test",
        "seed_definition": "If the Friedman test rejects, compute CD = q * sqrt(n*(n+1)/(6m)) and conclude a difference when the gap exceeds CD.",
    }
    shape = _seed_shape(bundle)
    assert shape["formula_required"] is True
    assert shape["condition_required"] is True
    assert shape["consequence_required"] is True


def test_recoverability_class_direct_when_required_roles_present():
    bundle = {
        "canonical_name": "Leave-One-Out Cross Validation",
        "seed_definition": "k-fold CV with k = |D|: each single instance is the test set in turn.",
    }
    packet = {
        "target_witness_spans": [{"selection_score": 1.0}],
        "definition_spans": [{"selection_score": 1.0}],
        "formula_spans": [],
        "condition_spans": [],
        "consequence_spans": [],
        "competitor_spans": [],
    }
    klass, _, action, failure = _recoverability_class(
        bundle=bundle,
        packet=packet,
        seed_shape=_seed_shape(bundle),
        same_kc_rows=[{"overlay_candidate_id": "x"}],
    )
    assert klass == RECOVERABILITY_A_DIRECT
    assert action == "draft_direct"
    assert failure == ""


def test_recoverability_class_not_recoverable_when_target_witness_missing():
    bundle = {
        "canonical_name": "Deletion Strategy",
        "seed_definition": "Handle missingness by discarding affected records or attributes when the amount of missing data is small.",
    }
    packet = {
        "target_witness_spans": [],
        "definition_spans": [{"selection_score": 1.0}],
        "formula_spans": [],
        "condition_spans": [],
        "consequence_spans": [],
        "competitor_spans": [],
    }
    klass, reasons, action, failure = _recoverability_class(
        bundle=bundle,
        packet=packet,
        seed_shape=_seed_shape(bundle),
        same_kc_rows=[{"overlay_candidate_id": "x"}],
    )
    assert klass == RECOVERABILITY_C_NOT_RECOVERABLE
    assert "missing_target_witness" in reasons
    assert action == "hold_upstream"
    assert failure == "missing_target_witness"


def test_recoverability_class_normalized_when_one_role_missing():
    bundle = {
        "canonical_name": "External Index: Entropy",
        "seed_definition": "Entropy = sum_Xi (|Xi|/|D|) * clusEntropy(Xi). Low entropy means clusters are pure.",
    }
    packet = {
        "target_witness_spans": [{"selection_score": 1.0}],
        "definition_spans": [{"selection_score": 1.0}],
        "formula_spans": [],
        "condition_spans": [],
        "consequence_spans": [],
        "competitor_spans": [],
    }
    klass, reasons, action, failure = _recoverability_class(
        bundle=bundle,
        packet=packet,
        seed_shape=_seed_shape(bundle),
        same_kc_rows=[{"overlay_candidate_id": "x"}],
    )
    assert klass == RECOVERABILITY_B_NORMALIZED
    assert "missing_formula" in reasons
    assert action == "draft_normalized"
    assert failure == ""
