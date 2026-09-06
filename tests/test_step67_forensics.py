from __future__ import annotations

import json

from kc_l.forensics.step67_forensics import (
    _definition_grounding_diagnostics,
    audit_baseline_fallbacks,
    audit_baseline_step67_rejection_subbuckets,
    audit_baseline_step67_support_binding_subtypes,
    audit_step67_definition_not_grounded_cases,
    audit_step67_persistent_regressions,
    audit_step67_touch_comparison,
    audit_step67_untouched_definition_not_grounded_regressions,
    compare_step67_runs,
    evaluate_no_regression_gate,
)


def _snapshot(run_id: str, llm_calls: int, rows: list[dict[str, object]]) -> dict[str, object]:
    counts: dict[str, int] = {}
    for row in rows:
        status = row["authoritative_definition_status"]
        counts[status] = counts.get(status, 0) + 1
    return {
        "run_id": run_id,
        "artifacts": {
            "bundle_path": f"data/processed/kc_drafts/{run_id}/kc_draft_bundles.jsonl",
            "summary_path": f"data/runs/{run_id}_step6_7/summary.json",
            "input_manifest_path": f"data/runs/{run_id}_step6_7/input_manifest.json",
        },
        "rows_by_kc": {row["kc_id"]: row for row in rows},
        "status_counts": counts,
        "total_kcs": len(rows),
        "llm_calls": llm_calls,
        "grounded_total": counts.get("direct_grounded", 0) + counts.get("normalized_grounded", 0),
    }


def _row(
    kc_id: str,
    status: str,
    *,
    definition_ids: list[str] | None = None,
    selected_ids: list[str] | None = None,
    draft_grounded: bool = False,
    verify_abstained: bool = False,
    verify_grounded: bool = False,
    verify_reason: str = "",
    risk_flags: list[str] | None = None,
    definition_full_status: str = "abstained",
    draft_support_ids: list[str] | None = None,
    binding_diag: dict[str, object] | None = None,
    definition_selection_reason: str = "definition_full_candidate_abstained",
    verify_error: str = "",
    definition_redraft_verify_error: str = "",
) -> dict[str, object]:
    draft_status = "grounded" if draft_grounded else "abstained"
    verify_status = "grounded" if verify_grounded else "abstained" if verify_abstained else "grounded"
    definition_ids = definition_ids or []
    selected_ids = selected_ids or []
    risk_flags = risk_flags or []
    draft_support_ids = draft_support_ids or definition_ids or selected_ids
    return {
        "kc_id": kc_id,
        "canonical_name": kc_id,
        "seed_definition": kc_id,
        "authoritative_definition_status": status,
        "trust_state": {"label": status},
        "risk_flags": risk_flags,
        "definition_full_candidate": {
            "status": definition_full_status,
            "text": "",
            "selection_reason": definition_selection_reason,
        },
        "evidence_bundle": [{"overlay_candidate_id": overlay_id, "bundle_role": "definition_support"} for overlay_id in selected_ids],
        "selection_diagnostics": {
            "definition_support_binding": dict(binding_diag or {}),
            "selected_bundle_candidate_ids": selected_ids,
            "field_candidate_sets": {
                "definition": [
                    {
                        "overlay_candidate_id": overlay_id,
                        "source_kc_id": kc_id,
                        "assessment": {"definition_signal": True, "definition_candidate": True},
                    }
                    for overlay_id in definition_ids
                ],
                "definition_support_pack": [],
            },
            "llm_drafting": {
                "draft_response": {
                    "definition": {
                        "status": draft_status,
                        "text": "grounded text" if draft_grounded else "",
                        "supporting_overlay_candidate_ids": draft_support_ids,
                    }
                },
                "verify_response": {
                    "definition": {
                        "status": verify_status,
                        "text": "verified text" if verify_grounded else "",
                        "abstention_reason": verify_reason,
                    }
                },
                "definition_redraft_response": {
                    "definition": {
                        "status": draft_status,
                        "text": "grounded text" if draft_grounded else "",
                        "supporting_overlay_candidate_ids": draft_support_ids,
                    }
                },
                "definition_redraft_verify_response": {
                    "definition": {
                        "status": verify_status,
                        "text": "verified text" if verify_grounded else "",
                        "abstention_reason": verify_reason,
                    }
                },
                "verify_error": verify_error,
                "definition_redraft_verify_error": definition_redraft_verify_error,
            },
        },
    }


def test_compare_step67_runs_tracks_regressions_and_improvements() -> None:
    baseline = _snapshot(
        "baseline",
        100,
        [
            _row("KC_A", "direct_grounded"),
            _row("KC_B", "seed_floor_fallback"),
            _row("KC_C", "normalized_grounded"),
        ],
    )
    candidate = _snapshot(
        "candidate",
        120,
        [
            _row("KC_A", "seed_floor_fallback"),
            _row("KC_B", "normalized_grounded"),
            _row("KC_C", "normalized_grounded"),
        ],
    )

    comparison = compare_step67_runs(baseline, candidate)
    assert comparison["transition_counts"]["direct_grounded->seed_floor_fallback"] == 1
    assert comparison["transition_counts"]["seed_floor_fallback->normalized_grounded"] == 1
    assert comparison["regression_count"] == 1
    assert comparison["improvement_count"] == 1


def test_no_regression_gate_fails_for_direct_to_fallback_and_fallback_growth() -> None:
    baseline = _snapshot(
        "baseline",
        100,
        [
            _row("KC_A", "direct_grounded"),
            _row("KC_B", "seed_floor_fallback"),
        ],
    )
    candidate = _snapshot(
        "candidate",
        170,
        [
            _row("KC_A", "seed_floor_fallback"),
            _row("KC_B", "seed_floor_fallback"),
        ],
    )

    gate = evaluate_no_regression_gate(baseline, candidate)
    assert gate["pass"] is False
    assert gate["direct_to_fallback_kcs"] == ["KC_A"]
    assert any("seed-floor fallback increased" in reason for reason in gate["reasons"])


def test_audit_baseline_fallbacks_marks_verify_rejection_as_high_confidence(tmp_path) -> None:
    step6_6_manifest = tmp_path / "step6_6_manifest.json"
    step6_7_manifest = tmp_path / "step6_7_manifest.json"
    step6_6_manifest.write_text(
        """
{
  "artifacts": {
    "candidate_sentence_overlay_jsonl": "missing_overlay.jsonl",
    "overlay_stats_json": "missing_overlay_stats.json"
  },
  "upstream": {
    "step5_3_active_set_target": "missing_step53_set.json",
    "review_queue_jsonl": "missing_review_queue.jsonl"
  },
  "set_id": "step6_6_test"
}
""".strip(),
        encoding="utf-8",
    )
    step6_7_manifest.write_text('{"set_id": "step6_7_test"}', encoding="utf-8")

    baseline = _snapshot(
        "baseline",
        100,
        [
            _row(
                "KC_A",
                "seed_floor_fallback",
                definition_ids=["KC_A:overlay:1"],
                selected_ids=["KC_A:overlay:1"],
                draft_grounded=True,
                verify_abstained=True,
            )
        ],
    )
    audit = audit_baseline_fallbacks(baseline, step6_6_manifest, step6_7_manifest, diagnostic_snapshots=[])
    record = audit["fallback_records"][0]
    assert record["step5_3_definition_evidence_visible"] == "uncertain"
    assert record["step5_3_definition_evidence_visible_basis"] == "step6_7_lineage_only"
    assert record["step6_7_definition_candidate_set"] == "yes"
    assert record["step6_7_prellm_definition_surface"] == "yes"
    assert record["raw_draft_candidate_present"] == "yes"
    assert record["likely_failure_locus"] == "step6_7_verification_or_control_rejection_after_good_raw_drafting"
    assert record["confidence"] == "high"


def test_audit_baseline_fallbacks_uses_real_upstream_payload_when_available(tmp_path) -> None:
    step53_set = tmp_path / "step53_set.json"
    step53_candidates = tmp_path / "step53_candidates.jsonl"
    review_queue = tmp_path / "review_queue.jsonl"
    overlay = tmp_path / "overlay.jsonl"
    step6_6_manifest = tmp_path / "step6_6_manifest.json"
    step6_7_manifest = tmp_path / "step6_7_manifest.json"

    step53_set.write_text(
        json.dumps(
            {
                "artifacts": {
                    "kc_evidence_candidates_recalibrated_jsonl": str(step53_candidates).replace("\\", "/")
                },
                "set_id": "step53_test",
            }
        ),
        encoding="utf-8",
    )
    step53_candidates.write_text(
        """
{"kc_id":"KC_A","canonical_name":"KC_A","aliases":[],"query_text":"KC_A","seed_definition":"KC_A","evidence":[{"snippet":"KC_A is a concept.","alignment_breakdown":{"name_or_alias_hit":true,"exact_name_phrase":true,"seed_keyword_hits":2,"strong_same_topic":true,"strong_structured_candidate":true,"contamination_risk":"low","flags":{"is_definition_like":true}}}]}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    review_queue.write_text("", encoding="utf-8")
    overlay.write_text(
        """
{"kc_id":"KC_A","overlay_candidate_id":"KC_A:overlay:1","source_candidate_index":0,"quote_surface":"KC_A is a concept.","is_definition_like":true,"strong_same_topic":true,"strong_structured_candidate":true,"contamination_risk":"low"}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    step6_6_manifest.write_text(
        json.dumps(
            {
                "artifacts": {
                    "candidate_sentence_overlay_jsonl": str(overlay).replace("\\", "/"),
                    "overlay_stats_json": str(tmp_path / "missing_overlay_stats.json").replace("\\", "/"),
                },
                "upstream": {
                    "step5_3_active_set_target": str(step53_set).replace("\\", "/"),
                    "review_queue_jsonl": str(review_queue).replace("\\", "/"),
                },
                "set_id": "step6_6_test",
            }
        ),
        encoding="utf-8",
    )
    step6_7_manifest.write_text('{"set_id": "step6_7_test"}', encoding="utf-8")

    baseline = _snapshot(
        "baseline",
        100,
        [
            _row(
                "KC_A",
                "seed_floor_fallback",
                definition_ids=["KC_A:overlay:1"],
                selected_ids=["KC_A:overlay:1"],
                draft_grounded=True,
                verify_abstained=True,
            )
        ],
    )
    audit = audit_baseline_fallbacks(baseline, step6_6_manifest, step6_7_manifest, diagnostic_snapshots=[])
    record = audit["fallback_records"][0]
    assert record["step5_3_definition_evidence_visible"] == "yes"
    assert record["step5_3_definition_evidence_visible_basis"] == "direct_upstream_payload_inspection"
    assert record["step6_6_preserved_in_overlay"] == "full"
    assert record["step6_6_preserved_in_overlay_basis"] == "direct_upstream_payload_inspection"
    assert record["step6_6_overlay_preserved_all_step5_3_indices"] == "yes"
    assert record["step6_6_overlay_preserved_all_step5_3_definition_like_indices"] == "yes"


def test_rejection_subbucket_audit_marks_binding_weak_when_support_is_procedure_like(tmp_path) -> None:
    overlay = tmp_path / "overlay.jsonl"
    step6_6_manifest = tmp_path / "step6_6_manifest.json"
    overlay.write_text(
        """
{"overlay_candidate_id":"KC_A:overlay:1","kc_id":"KC_A","source_candidate_index":0,"quote_surface":"Calculate the weighted misclassification rate.","is_definition_like":false,"strong_same_topic":true,"contamination_risk":"low","sentence_flags":{"is_definition_like":false,"is_procedure_like":true,"is_example_like":false}}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    step6_6_manifest.write_text(
        json.dumps(
            {
                "artifacts": {
                    "candidate_sentence_overlay_jsonl": str(overlay).replace("\\", "/"),
                    "overlay_stats_json": str(tmp_path / "missing_overlay_stats.json").replace("\\", "/"),
                }
            }
        ),
        encoding="utf-8",
    )
    baseline = _snapshot(
        "baseline",
        100,
        [
            _row(
                "KC_A",
                "seed_floor_fallback",
                definition_ids=["KC_A:overlay:1"],
                selected_ids=["KC_A:overlay:1"],
                draft_grounded=True,
                verify_abstained=True,
                verify_reason="not directly supported",
            )
        ],
    )
    payload = audit_baseline_step67_rejection_subbuckets(baseline, step6_6_manifest)
    record = payload["records"][0]
    assert record["rejection_subbucket"] == "support_provenance_binding_or_supporting_overlay_id_linkage_is_weak_or_mismatched"
    assert "no_clean_same_kc_definition_support" in record["support_binding_assessment"]["issue_signals"]


def test_rejection_subbucket_audit_marks_false_reject_for_clean_support_and_strict_verify(tmp_path) -> None:
    overlay = tmp_path / "overlay.jsonl"
    step6_6_manifest = tmp_path / "step6_6_manifest.json"
    overlay.write_text(
        """
{"overlay_candidate_id":"KC_A:overlay:1","kc_id":"KC_A","source_candidate_index":0,"quote_surface":"Manhattan distance between points in a cluster.","is_definition_like":true,"strong_same_topic":true,"contamination_risk":"low","sentence_flags":{"is_definition_like":true,"is_procedure_like":false,"is_example_like":false}}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    step6_6_manifest.write_text(
        json.dumps(
            {
                "artifacts": {
                    "candidate_sentence_overlay_jsonl": str(overlay).replace("\\", "/"),
                    "overlay_stats_json": str(tmp_path / "missing_overlay_stats.json").replace("\\", "/"),
                }
            }
        ),
        encoding="utf-8",
    )
    baseline = _snapshot(
        "baseline",
        100,
        [
            _row(
                "KC_A",
                "seed_floor_fallback",
                definition_ids=["KC_A:overlay:1"],
                selected_ids=["KC_A:overlay:1"],
                draft_grounded=True,
                verify_abstained=True,
                verify_reason="The phrase is not directly supported by the cited evidence.",
            )
        ],
    )
    payload = audit_baseline_step67_rejection_subbuckets(baseline, step6_6_manifest)
    record = payload["records"][0]
    assert record["rejection_subbucket"] == "raw_draft_clearly_good_and_verifier_likely_false_rejected_it"
    assert record["rejection_subbucket_basis"] == "inferred_from_step67_payload_and_verify_reason"


def test_rejection_subbucket_audit_marks_control_override_when_verify_is_grounded(tmp_path) -> None:
    overlay = tmp_path / "overlay.jsonl"
    step6_6_manifest = tmp_path / "step6_6_manifest.json"
    overlay.write_text(
        """
{"overlay_candidate_id":"KC_A:overlay:1","kc_id":"KC_A","source_candidate_index":0,"quote_surface":"A clean same-KC definition.","is_definition_like":true,"strong_same_topic":true,"contamination_risk":"low","sentence_flags":{"is_definition_like":true,"is_procedure_like":false,"is_example_like":false}}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    step6_6_manifest.write_text(
        json.dumps(
            {
                "artifacts": {
                    "candidate_sentence_overlay_jsonl": str(overlay).replace("\\", "/"),
                    "overlay_stats_json": str(tmp_path / "missing_overlay_stats.json").replace("\\", "/"),
                }
            }
        ),
        encoding="utf-8",
    )
    baseline = _snapshot(
        "baseline",
        100,
        [
            _row(
                "KC_A",
                "seed_floor_fallback",
                definition_ids=["KC_A:overlay:1"],
                selected_ids=["KC_A:overlay:1"],
                draft_grounded=True,
                verify_grounded=True,
                definition_full_status="abstained",
            )
        ],
    )
    payload = audit_baseline_step67_rejection_subbuckets(baseline, step6_6_manifest)
    record = payload["records"][0]
    assert record["rejection_subbucket"] == "raw_draft_clearly_good_but_later_control_logic_or_preservation_rescue_interaction_caused_the_loss"
    assert record["direct_control_override_keys"] == ["verify_response", "definition_redraft_verify_response"]


def test_support_binding_subtype_marks_better_same_kc_definition_available_but_unbound(tmp_path) -> None:
    overlay = tmp_path / "overlay.jsonl"
    step6_6_manifest = tmp_path / "step6_6_manifest.json"
    overlay.write_text(
        """
{"overlay_candidate_id":"KC_A:overlay:1","kc_id":"KC_A","source_candidate_index":0,"quote_surface":"Perform the node split and compare impurity values.","is_definition_like":false,"strong_same_topic":true,"contamination_risk":"low","sentence_flags":{"is_definition_like":false,"is_procedure_like":true,"is_example_like":false,"is_formula_like":false,"is_heading_like":false}}
{"overlay_candidate_id":"KC_A:overlay:2","kc_id":"KC_A","source_candidate_index":1,"quote_surface":"Node impurity measures how mixed the class labels are at a node.","is_definition_like":true,"strong_same_topic":true,"contamination_risk":"low","sentence_flags":{"is_definition_like":true,"is_procedure_like":false,"is_example_like":false,"is_formula_like":false,"is_heading_like":false}}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    step6_6_manifest.write_text(
        json.dumps(
            {
                "artifacts": {
                    "candidate_sentence_overlay_jsonl": str(overlay).replace("\\", "/"),
                    "overlay_stats_json": str(tmp_path / "missing_overlay_stats.json").replace("\\", "/"),
                }
            }
        ),
        encoding="utf-8",
    )
    baseline = _snapshot(
        "baseline",
        100,
        [
            _row(
                "KC_A",
                "seed_floor_fallback",
                definition_ids=["KC_A:overlay:1", "KC_A:overlay:2"],
                selected_ids=["KC_A:overlay:1", "KC_A:overlay:2"],
                draft_grounded=True,
                verify_abstained=True,
                verify_reason="not directly supported",
                draft_support_ids=["KC_A:overlay:1"],
            )
        ],
    )
    payload = audit_baseline_step67_support_binding_subtypes(baseline, step6_6_manifest)
    record = payload["records"][0]
    assert record["support_binding_subtype"] == "better_same_kc_definition_available_but_unbound"
    assert record["support_binding_subtype_basis"] == "direct_artifact_inspection"
    assert record["same_kc_clean_definition_alternative_overlay_ids"] == ["KC_A:overlay:2"]


def test_support_binding_subtype_marks_binding_outside_pool_or_bundle(tmp_path) -> None:
    overlay = tmp_path / "overlay.jsonl"
    step6_6_manifest = tmp_path / "step6_6_manifest.json"
    overlay.write_text(
        """
{"overlay_candidate_id":"KC_A:overlay:1","kc_id":"KC_A","source_candidate_index":0,"quote_surface":"A broad background statement.","is_definition_like":false,"strong_same_topic":true,"contamination_risk":"low","sentence_flags":{"is_definition_like":false,"is_procedure_like":false,"is_example_like":false,"is_formula_like":false,"is_heading_like":false}}
{"overlay_candidate_id":"KC_A:overlay:2","kc_id":"KC_A","source_candidate_index":1,"quote_surface":"A neighboring row not kept in the saved pool.","is_definition_like":false,"strong_same_topic":true,"contamination_risk":"low","sentence_flags":{"is_definition_like":false,"is_procedure_like":false,"is_example_like":false,"is_formula_like":false,"is_heading_like":false}}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    step6_6_manifest.write_text(
        json.dumps(
            {
                "artifacts": {
                    "candidate_sentence_overlay_jsonl": str(overlay).replace("\\", "/"),
                    "overlay_stats_json": str(tmp_path / "missing_overlay_stats.json").replace("\\", "/"),
                }
            }
        ),
        encoding="utf-8",
    )
    baseline = _snapshot(
        "baseline",
        100,
        [
            _row(
                "KC_A",
                "seed_floor_fallback",
                definition_ids=["KC_A:overlay:1"],
                selected_ids=["KC_A:overlay:1"],
                draft_grounded=True,
                verify_abstained=True,
                verify_reason="not directly supported",
                draft_support_ids=["KC_A:overlay:2"],
            )
        ],
    )
    payload = audit_baseline_step67_support_binding_subtypes(baseline, step6_6_manifest)
    record = payload["records"][0]
    assert record["support_binding_subtype"] == "binding_outside_definition_pool_or_selected_bundle"
    assert record["support_binding_subtype_basis"] == "direct_artifact_inspection"


def test_support_binding_subtype_marks_collapsed_multi_row_weak_composite_binding(tmp_path) -> None:
    overlay = tmp_path / "overlay.jsonl"
    step6_6_manifest = tmp_path / "step6_6_manifest.json"
    overlay.write_text(
        """
{"overlay_candidate_id":"KC_A:overlay:1","kc_id":"KC_A","source_candidate_index":0,"quote_surface":"Use the parameter alpha to control the update.","is_definition_like":false,"strong_same_topic":true,"contamination_risk":"low","sentence_flags":{"is_definition_like":false,"is_procedure_like":true,"is_example_like":false,"is_formula_like":false,"is_heading_like":false}}
{"overlay_candidate_id":"KC_A:overlay:2","kc_id":"KC_A","source_candidate_index":1,"quote_surface":"alpha = 1 / (1 + exp(-x))","is_definition_like":false,"strong_same_topic":true,"contamination_risk":"low","sentence_flags":{"is_definition_like":false,"is_procedure_like":false,"is_example_like":false,"is_formula_like":true,"is_heading_like":false}}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    step6_6_manifest.write_text(
        json.dumps(
            {
                "artifacts": {
                    "candidate_sentence_overlay_jsonl": str(overlay).replace("\\", "/"),
                    "overlay_stats_json": str(tmp_path / "missing_overlay_stats.json").replace("\\", "/"),
                }
            }
        ),
        encoding="utf-8",
    )
    baseline = _snapshot(
        "baseline",
        100,
        [
            _row(
                "KC_A",
                "seed_floor_fallback",
                definition_ids=["KC_A:overlay:1", "KC_A:overlay:2"],
                selected_ids=["KC_A:overlay:1", "KC_A:overlay:2"],
                draft_grounded=True,
                verify_abstained=True,
                verify_reason="not directly supported",
                draft_support_ids=["KC_A:overlay:1", "KC_A:overlay:2"],
            )
        ],
    )
    payload = audit_baseline_step67_support_binding_subtypes(baseline, step6_6_manifest)
    record = payload["records"][0]
    assert record["support_binding_subtype"] == "collapsed_multi_row_weak_composite_binding"
    assert record["support_binding_subtype_basis"] == "inferred_from_support_shape"


def test_support_binding_subtype_marks_weak_topic_or_crossconcept_anchor(tmp_path) -> None:
    overlay = tmp_path / "overlay.jsonl"
    step6_6_manifest = tmp_path / "step6_6_manifest.json"
    overlay.write_text(
        """
{"overlay_candidate_id":"KC_A:overlay:1","kc_id":"KC_A","source_candidate_index":0,"quote_surface":"This section compares several nearby concepts in context.","is_definition_like":false,"strong_same_topic":false,"contamination_risk":"medium","sentence_flags":{"is_definition_like":false,"is_procedure_like":false,"is_example_like":false,"is_formula_like":false,"is_heading_like":false}}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    step6_6_manifest.write_text(
        json.dumps(
            {
                "artifacts": {
                    "candidate_sentence_overlay_jsonl": str(overlay).replace("\\", "/"),
                    "overlay_stats_json": str(tmp_path / "missing_overlay_stats.json").replace("\\", "/"),
                }
            }
        ),
        encoding="utf-8",
    )
    baseline = _snapshot(
        "baseline",
        100,
        [
            _row(
                "KC_A",
                "seed_floor_fallback",
                definition_ids=["KC_A:overlay:1"],
                selected_ids=["KC_A:overlay:1"],
                draft_grounded=True,
                verify_abstained=True,
                verify_reason="not directly supported",
                risk_flags=["review_queue_weak_coverage"],
            )
        ],
    )
    payload = audit_baseline_step67_support_binding_subtypes(baseline, step6_6_manifest)
    record = payload["records"][0]
    assert record["support_binding_subtype"] == "weak_topic_or_crossconcept_anchor"
    assert record["support_binding_subtype_basis"] == "direct_artifact_inspection"


def test_compare_step67_runs_normalizes_touched_vs_untouched_binding_classification() -> None:
    baseline = _snapshot(
        "baseline",
        100,
        [
            _row("KC_A", "direct_grounded"),
            _row("KC_B", "seed_floor_fallback"),
            _row("KC_C", "normalized_grounded"),
            _row("KC_D", "direct_grounded"),
            _row("KC_E", "normalized_grounded"),
            _row("KC_F", "normalized_grounded"),
        ],
    )
    candidate = _snapshot(
        "candidate",
        120,
        [
            _row(
                "KC_A",
                "normalized_grounded",
                binding_diag={"repair_applied": True, "repair_reason": "promoted_stronger_same_kc_definition_anchor"},
            ),
            _row(
                "KC_B",
                "normalized_grounded",
                binding_diag={"repair_applied": True, "repair_reason": "blocked_out_of_pool_definition_binding"},
            ),
            _row(
                "KC_C",
                "normalized_grounded",
                binding_diag={"repair_applied": True, "repair_reason": "promoted_bounded_multi_row_definition_binding"},
            ),
            _row(
                "KC_D",
                "seed_floor_fallback",
                binding_diag={"repair_applied": False, "repair_reason": "definition_not_grounded"},
            ),
            _row(
                "KC_E",
                "direct_grounded",
                binding_diag={"repair_applied": False, "repair_reason": "replaced_weak_definition_anchor"},
            ),
            _row(
                "KC_F",
                "normalized_grounded",
                binding_diag={"repair_applied": False, "repair_reason": "retained_existing_binding"},
            ),
        ],
    )

    comparison = compare_step67_runs(baseline, candidate)
    summary = comparison["binding_touch_summary"]
    assert summary["touched_and_harmed"] == 1
    assert summary["touched_and_improved"] == 1
    assert summary["touched_and_unchanged"] == 1
    assert summary["untouched_but_regressed"] == 1
    assert summary["untouched_but_improved"] == 1
    assert summary["untouched_and_stable"] == 1

    per_kc = {record["kc_id"]: record for record in comparison["per_kc"]}
    assert per_kc["KC_E"]["binding_repair_diagnostics"]["repair_state"] == "repair_attempted_but_rejected"
    assert per_kc["KC_E"]["binding_repair_diagnostics"]["repair_attempt_reason"] == "replaced_weak_definition_anchor"
    assert per_kc["KC_E"]["binding_touch_classification"] == "untouched_but_improved"


def test_audit_step67_untouched_definition_not_grounded_regressions_surfaces_verification_and_control_paths() -> None:
    baseline = _snapshot(
        "baseline",
        100,
        [
            _row(
                "KC_VERIFY",
                "direct_grounded",
                definition_ids=["KC_VERIFY:overlay:1"],
                selected_ids=["KC_VERIFY:overlay:1"],
                draft_grounded=True,
                verify_grounded=True,
                definition_full_status="grounded",
                definition_selection_reason="definition_full_candidate_llm_multispan_verified",
            ),
            _row(
                "KC_CONTROL",
                "direct_grounded",
                definition_ids=["KC_CONTROL:overlay:1"],
                selected_ids=["KC_CONTROL:overlay:1"],
                draft_grounded=True,
                verify_abstained=True,
                definition_full_status="grounded",
                definition_selection_reason="definition_full_candidate_single_span_fallback",
                verify_error="RuntimeError:timeout",
            ),
        ],
    )
    candidate = _snapshot(
        "candidate",
        120,
        [
            _row(
                "KC_VERIFY",
                "seed_floor_fallback",
                definition_ids=["KC_VERIFY:overlay:1", "KC_VERIFY:overlay:2"],
                selected_ids=["KC_VERIFY:overlay:1"],
                draft_grounded=True,
                definition_full_status="abstained",
                binding_diag={"repair_applied": False, "repair_reason": "definition_not_grounded"},
            ),
            _row(
                "KC_CONTROL",
                "seed_floor_fallback",
                definition_ids=["KC_CONTROL:overlay:1", "KC_CONTROL:overlay:2"],
                selected_ids=["KC_CONTROL:overlay:1"],
                draft_grounded=True,
                definition_full_status="abstained",
                binding_diag={"repair_applied": False, "repair_reason": "definition_not_grounded"},
            ),
        ],
    )
    candidate["rows_by_kc"]["KC_VERIFY"]["selection_diagnostics"]["llm_drafting"].update(
        {
            "preservation_draft_response": {
                "definition": {
                    "status": "grounded",
                    "text": "grounded text",
                    "supporting_overlay_candidate_ids": ["KC_VERIFY:overlay:1"],
                }
            },
            "preservation_verify_response": {
                "definition": {
                    "status": "abstained",
                    "text": "",
                    "abstention_reason": "unsupported detail",
                }
            },
            "rescue_verify_response": {"definition": {"status": "abstained", "text": "", "abstention_reason": "unsupported detail"}},
            "definition_redraft_verify_response": {"definition": {"status": "abstained", "text": "", "abstention_reason": "unsupported detail"}},
        }
    )
    candidate["rows_by_kc"]["KC_CONTROL"]["selection_diagnostics"]["llm_drafting"].update(
        {
            "preservation_draft_response": {
                "definition": {
                    "status": "grounded",
                    "text": "grounded text",
                    "supporting_overlay_candidate_ids": ["KC_CONTROL:overlay:1"],
                }
            },
            "preservation_verify_response": {
                "definition": {
                    "status": "abstained",
                    "text": "",
                    "abstention_reason": "insufficient_evidence",
                }
            },
            "rescue_verify_response": {"definition": {"status": "abstained", "text": "", "abstention_reason": "insufficient_evidence"}},
            "definition_redraft_verify_response": {"definition": {"status": "abstained", "text": "", "abstention_reason": "insufficient_evidence"}},
        }
    )

    payload = audit_step67_untouched_definition_not_grounded_regressions(
        baseline,
        candidate,
        kc_ids=["KC_VERIFY", "KC_CONTROL"],
    )
    records = {record["kc_id"]: record for record in payload["records"]}
    assert records["KC_VERIFY"]["dominant_collapse_path"] == "verification_result_changed"
    assert records["KC_VERIFY"]["candidate_pool_changed"] is True
    assert records["KC_CONTROL"]["dominant_collapse_path"] == "later_control_logic_changed"
    assert records["KC_CONTROL"]["later_control_logic_changed"] is True


def test_audit_step67_touch_comparison_preserves_real_touch_bucket_counts() -> None:
    baseline = _snapshot(
        "baseline",
        100,
        [
            _row("KC_A", "direct_grounded"),
            _row("KC_B", "seed_floor_fallback"),
        ],
    )
    candidate = _snapshot(
        "candidate",
        120,
        [
            _row(
                "KC_A",
                "normalized_grounded",
                binding_diag={"repair_applied": True, "repair_reason": "promoted_stronger_same_kc_definition_anchor"},
            ),
            _row(
                "KC_B",
                "seed_floor_fallback",
                binding_diag={"repair_applied": False, "repair_reason": "definition_not_grounded"},
            ),
        ],
    )

    payload = audit_step67_touch_comparison(baseline, candidate)
    assert payload["binding_touch_summary"]["touched_and_harmed"] == 1
    assert payload["binding_touch_summary"]["untouched_and_stable"] == 1


def test_audit_step67_definition_not_grounded_cases_splits_verify_rejection_and_abstention_paths() -> None:
    candidate = _snapshot(
        "candidate",
        120,
        [
            _row(
                "KC_FALLBACK",
                "seed_floor_fallback",
                definition_ids=["KC_FALLBACK:overlay:1"],
                selected_ids=["KC_FALLBACK:overlay:1"],
                draft_grounded=True,
                definition_full_status="abstained",
                binding_diag={"repair_state": "no_binding_possible", "repair_applied": False, "repair_reason": "definition_not_grounded"},
            ),
            _row(
                "KC_ABSTAIN",
                "seed_floor_fallback",
                definition_ids=["KC_ABSTAIN:overlay:1"],
                selected_ids=["KC_ABSTAIN:overlay:1"],
                draft_grounded=False,
                definition_full_status="abstained",
                binding_diag={"repair_state": "no_binding_possible", "repair_applied": False, "repair_reason": "definition_not_grounded"},
            ),
        ],
    )
    fallback_row = candidate["rows_by_kc"]["KC_FALLBACK"]
    abstain_row = candidate["rows_by_kc"]["KC_ABSTAIN"]
    fallback_row["selection_diagnostics"]["field_candidate_sets"]["definition"][0].update(
        {
            "single_span_accepted": True,
            "candidate_source_relation": "local",
        }
    )
    fallback_row["selection_diagnostics"]["llm_drafting"].update(
        {
            "preservation_draft_response": {
                "definition": {
                    "status": "grounded",
                    "text": "grounded text",
                    "supporting_overlay_candidate_ids": ["KC_FALLBACK:overlay:1"],
                }
            },
            "preservation_verify_response": {
                "definition": {"status": "abstained", "text": "", "abstention_reason": "unsupported detail"}
            },
            "rescue_used": True,
            "rescue_draft_response": {
                "definition": {
                    "status": "grounded",
                    "text": "grounded text",
                    "supporting_overlay_candidate_ids": ["KC_FALLBACK:overlay:1"],
                }
            },
            "rescue_verify_response": {
                "definition": {"status": "abstained", "text": "", "abstention_reason": "unsupported detail"}
            },
            "definition_redraft_response": {
                "definition": {
                    "status": "grounded",
                    "text": "grounded text",
                    "supporting_overlay_candidate_ids": ["KC_FALLBACK:overlay:1"],
                }
            },
            "definition_redraft_verify_response": {
                "definition": {"status": "abstained", "text": "", "abstention_reason": "unsupported detail"}
            },
        }
    )
    abstain_row["selection_diagnostics"]["field_candidate_sets"]["definition"][0].update(
        {
            "single_span_accepted": False,
            "candidate_source_relation": "local",
        }
    )
    abstain_row["selection_diagnostics"]["llm_drafting"].update(
        {
            "preservation_draft_response": {
                "definition": {"status": "abstained", "text": "", "supporting_overlay_candidate_ids": []}
            },
            "preservation_verify_response": {
                "definition": {"status": "abstained", "text": "", "abstention_reason": "insufficient_evidence"}
            },
            "rescue_used": True,
            "rescue_draft_response": {
                "definition": {"status": "abstained", "text": "", "supporting_overlay_candidate_ids": []}
            },
            "rescue_verify_response": {
                "definition": {"status": "abstained", "text": "", "abstention_reason": "insufficient_evidence"}
            },
            "definition_redraft_response": {
                "definition": {"status": "grounded", "text": "drafted text", "supporting_overlay_candidate_ids": ["KC_ABSTAIN:overlay:1"]}
            },
            "definition_redraft_verify_response": {
                "definition": {"status": "abstained", "text": "", "abstention_reason": "insufficient_evidence"}
            },
        }
    )

    payload = audit_step67_definition_not_grounded_cases(candidate)
    assert payload["definition_not_grounded_case_count"] == 2
    assert payload["definition_not_grounded_subbucket_summary"][
        "verify_rejected_no_binding_despite_prior_single_span_support_match"
    ] == 1
    assert payload["definition_not_grounded_subbucket_summary"][
        "preservation_draft_abstained_rescue_abstained_no_binding"
    ] == 1
    records = {record["kc_id"]: record for record in payload["records"]}
    assert records["KC_FALLBACK"]["grounding_diagnostics"]["control_fallback_candidate_present"] is True
    assert records["KC_ABSTAIN"]["grounding_diagnostics"]["collapse_stage"] == "no_binding_after_preservation_draft_abstention"


def test_definition_grounding_diagnostics_backfills_draft_supported_single_span_aliases_from_native_payload() -> None:
    row = _row(
        "KC_NATIVE",
        "seed_floor_fallback",
        definition_ids=["KC_NATIVE:overlay:1"],
        selected_ids=["KC_NATIVE:overlay:1"],
        draft_grounded=True,
        definition_full_status="abstained",
        binding_diag={"repair_state": "no_binding_possible", "repair_applied": False, "repair_reason": "definition_not_grounded"},
    )
    row["selection_diagnostics"]["definition_grounding_diagnostics"] = {
        "control_fallback_candidate_present": True,
        "control_fallback_source_phase": "preservation_draft_response",
        "control_fallback_support_ids": ["KC_NATIVE:overlay:1"],
        "control_fallback_applied": True,
        "collapse_stage": "control_fallback_applied",
    }

    diagnostics, basis = _definition_grounding_diagnostics(row)

    assert basis == "native_definition_grounding_diagnostics"
    assert diagnostics["draft_supported_single_span_fallback_candidate_present"] is True
    assert diagnostics["draft_supported_single_span_fallback_source_phase"] == "preservation_draft_response"
    assert diagnostics["draft_supported_single_span_fallback_support_ids"] == ["KC_NATIVE:overlay:1"]
    assert diagnostics["draft_supported_single_span_fallback_applied"] is True


def test_audit_step67_persistent_regressions_surfaces_named_cases_across_two_candidates() -> None:
    baseline = _snapshot(
        "baseline",
        100,
        [
            _row("KC_VERIFY", "direct_grounded", definition_full_status="grounded", definition_selection_reason="definition_full_candidate_llm_multispan_verified"),
            _row("KC_BIND", "direct_grounded", definition_full_status="grounded", definition_selection_reason="definition_full_candidate_llm_multispan_verified"),
        ],
    )
    candidate_a = _snapshot(
        "candidate_a",
        120,
        [
            _row(
                "KC_VERIFY",
                "seed_floor_fallback",
                definition_ids=["KC_VERIFY:overlay:1"],
                selected_ids=["KC_VERIFY:overlay:1"],
                draft_grounded=True,
                definition_full_status="abstained",
                binding_diag={"repair_state": "no_binding_possible", "repair_applied": False, "repair_reason": "definition_not_grounded"},
            ),
            _row(
                "KC_BIND",
                "normalized_grounded",
                definition_full_status="grounded",
                binding_diag={
                    "repair_state": "repair_attempted_but_rejected",
                    "repair_applied": False,
                    "repair_reason": "non_monotonic_single_row_replacement_rejected",
                    "repair_attempt_reason": "promoted_stronger_same_kc_definition_anchor",
                },
                definition_selection_reason="definition_full_candidate_source_faithful_local_support_unit_normalization",
            ),
        ],
    )
    candidate_b = _snapshot(
        "candidate_b",
        121,
        [
            _row(
                "KC_VERIFY",
                "seed_floor_fallback",
                definition_ids=["KC_VERIFY:overlay:1"],
                selected_ids=["KC_VERIFY:overlay:1"],
                draft_grounded=True,
                definition_full_status="abstained",
                binding_diag={"repair_state": "no_binding_possible", "repair_applied": False, "repair_reason": "definition_not_grounded"},
            ),
            _row(
                "KC_BIND",
                "normalized_grounded",
                definition_full_status="grounded",
                binding_diag={
                    "repair_state": "repair_attempted_but_rejected",
                    "repair_applied": False,
                    "repair_reason": "non_monotonic_single_row_replacement_rejected",
                    "repair_attempt_reason": "promoted_stronger_same_kc_definition_anchor",
                },
                definition_selection_reason="definition_full_candidate_source_faithful_local_support_unit_normalization",
            ),
        ],
    )
    for snapshot in (candidate_a, candidate_b):
        verify_row = snapshot["rows_by_kc"]["KC_VERIFY"]
        verify_row["selection_diagnostics"]["field_candidate_sets"]["definition"][0].update(
            {"single_span_accepted": True, "candidate_source_relation": "local"}
        )
        verify_row["selection_diagnostics"]["llm_drafting"].update(
            {
                "preservation_draft_response": {
                    "definition": {
                        "status": "grounded",
                        "text": "grounded text",
                        "supporting_overlay_candidate_ids": ["KC_VERIFY:overlay:1"],
                    }
                },
                "preservation_verify_response": {
                    "definition": {"status": "abstained", "text": "", "abstention_reason": "unsupported detail"}
                },
                "rescue_used": True,
                "rescue_draft_response": {
                    "definition": {
                        "status": "grounded",
                        "text": "grounded text",
                        "supporting_overlay_candidate_ids": ["KC_VERIFY:overlay:1"],
                    }
                },
                "rescue_verify_response": {
                    "definition": {"status": "abstained", "text": "", "abstention_reason": "unsupported detail"}
                },
                "definition_redraft_response": {
                    "definition": {
                        "status": "grounded",
                        "text": "grounded text",
                        "supporting_overlay_candidate_ids": ["KC_VERIFY:overlay:1"],
                    }
                },
                "definition_redraft_verify_response": {
                    "definition": {"status": "abstained", "text": "", "abstention_reason": "unsupported detail"}
                },
            }
        )

    payload = audit_step67_persistent_regressions(
        baseline,
        [candidate_a, candidate_b],
        kc_ids=["KC_VERIFY", "KC_BIND"],
    )
    assert payload["persistent_regression_count"] == 2
    records = {record["kc_id"]: record for record in payload["records"]}
    verify_stages = {item["candidate_run_id"]: item["collapse_stage"] for item in records["KC_VERIFY"]["candidate_records"]}
    bind_stages = {item["candidate_run_id"]: item["collapse_stage"] for item in records["KC_BIND"]["candidate_records"]}
    assert set(verify_stages.values()) == {"no_binding_after_preservation_verify_rejection"}
    assert set(bind_stages.values()) == {"binding_repair_rejected_then_normalization_only"}
