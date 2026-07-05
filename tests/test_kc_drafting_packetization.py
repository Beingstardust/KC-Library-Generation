from __future__ import annotations

from pathlib import Path

from kc_l.kc_drafting import packetization as packetization_module
from kc_l.kc_drafting.contracts import (
    AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED,
    AUTHORITATIVE_DEFINITION_STATUS_SEED_FLOOR_FALLBACK,
)
from kc_l.kc_drafting.heuristic_core import build_kc_draft_bundles
from kc_l.kc_drafting.hierarchy_refs import typed_topic_hierarchy_fields
from kc_l.kc_drafting.packetization import (
    build_restarted_review_packet,
    emit_restarted_review_packets_from_draft_bundles,
    validate_restarted_review_packet,
)
from kc_l.utils.json_io import read_jsonl


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_REVIEWER_DECISION_FIELDS = {
    "kc_candidate_id",
    "title_draft",
    "authoritative_definition_status",
    "seed_definition",
    "definition_draft",
    "scope_draft",
    "scope_status",
    "topic_path_ids",
    "topic_path_labels",
    "parent_topic_id",
    "parent_topic_label",
    "ancestor_topic_ids",
    "ancestor_topic_labels",
    "hierarchy_ancestry",
    "evidence_spans",
    "field_provenance_map",
    "source_provenance",
    "trust_state",
    "review_readiness",
    "review_priority",
    "system_recommendation",
    "kc_specific_criteria",
}


def _synthetic_evidence_item(*, kc_id: str, suffix: str = "01") -> dict[str, object]:
    return {
        "bundle_role": "definition_support",
        "overlay_candidate_id": f"{kc_id}:overlay:{suffix}",
        "selection_score": 8.5,
        "candidate_text": "Synthetic evidence sentence for packetization coverage.",
        "quote_surface": "Synthetic evidence sentence for packetization coverage.",
        "source_block_text": "Synthetic evidence sentence for packetization coverage.",
        "doc_id": "doc.synthetic",
        "block_id": f"block.{suffix}",
        "page_index": 0,
        "sentence_id": f"sent.{suffix}",
        "layer": "sentence",
        "alignment_score": 0.9,
        "contamination_risk": "low",
        "provenance_normalization_status": "normalized",
        "quote_verification_status": "verified",
        "assessment": {
            "classification": "definition_support",
            "definition_signal": True,
            "scope_signal": False,
            "bare_heading": False,
            "formula_lead_in": False,
            "question_like": False,
        },
    }


def _synthetic_hierarchy_fields(*, kc_id: str, canonical_name: str, topic_path_labels: list[str] | None = None) -> dict[str, object]:
    topic_labels = topic_path_labels or ["Synthetic Domain", "Synthetic Branch"]
    hierarchy_payload = {
        "kc_id": kc_id,
        "ancestor_hier_node_ids": [f"hier::{index + 1}" for index in range(len(topic_labels))],
        "ancestor_labels": list(topic_labels),
        "leaf_hier_node_id": f"kc::{kc_id}",
        "parent_hier_node_id": f"hier::{len(topic_labels)}" if topic_labels else "",
        "source_hierarchy_path": [*topic_labels, canonical_name],
    }
    return typed_topic_hierarchy_fields(hierarchy_payload)


def _synthetic_overlay_row(
    *,
    kc_id: str,
    canonical_name: str,
    suffix: str,
    text: str,
    topic_path_labels: list[str] | None = None,
) -> dict[str, object]:
    hierarchy_fields = _synthetic_hierarchy_fields(
        kc_id=kc_id,
        canonical_name=canonical_name,
        topic_path_labels=topic_path_labels,
    )
    ancestry = dict(hierarchy_fields["hierarchy_ancestry"])
    return {
        "kc_id": kc_id,
        "overlay_candidate_id": f"{kc_id}:overlay:{suffix}",
        "canonical_name": canonical_name,
        "aliases": [],
        "seed_definition": f"{canonical_name} seed definition.",
        "quote_surface": text,
        "source_block_text": text,
        "doc_id": "doc.synthetic",
        "block_id": f"block.{suffix}",
        "page_index": 0,
        "sentence_id": f"sent.{suffix}",
        "layer": "sentence",
        "alignment_score": 0.95,
        "contamination_risk": "low",
        "provenance_normalization_status": "normalized",
        "quote_verification_status": "verified",
        "ancestor_hier_node_ids": list(ancestry["ancestor_hier_node_ids"]),
        "ancestor_labels": list(ancestry["ancestor_labels"]),
        "leaf_hier_node_id": ancestry["leaf_hier_node_id"],
        "parent_hier_node_id": ancestry["parent_hier_node_id"],
        "source_hierarchy_path": list(ancestry["source_hierarchy_path"]),
    }


def _synthetic_low_trust_bundle() -> dict[str, object]:
    kc_id = "KC_SYN_LOW"
    hierarchy_fields = _synthetic_hierarchy_fields(kc_id=kc_id, canonical_name="Synthetic Low Trust KC")
    return {
        "semantic_contract_version": "step6_7_survival_semantics_v1",
        "draft_status": "draft_ready_with_holds",
        "kc_id": kc_id,
        "canonical_name": "Synthetic Low Trust KC",
        "aliases": [],
        "authoritative_definition_status": AUTHORITATIVE_DEFINITION_STATUS_SEED_FLOOR_FALLBACK,
        **hierarchy_fields,
        "seed_definition": "A synthetic seed definition used only as an explicit fallback floor.",
        "survival_floor": {
            "status": "seed_definition_floor",
            "text": "A synthetic seed definition used only as an explicit fallback floor.",
            "canonical_name": "Synthetic Low Trust KC",
            "source_field": "hierarchy.seed_definition",
            "used_as_definition_fallback": True,
        },
        "enrichment_layer": {
            "status": "missing",
            "text": "",
            "short_text": "",
            "supporting_overlay_candidate_ids": [],
            "source_field": "",
        },
        "context_layer": {
            "status": "fallback_context",
            "snippet_surfaces": ["Synthetic evidence sentence for packetization coverage."],
            "supporting_overlay_candidate_ids": [f"{kc_id}:overlay:01"],
            "source_document_ids": ["doc.synthetic"],
            "family_context_candidate_ids": [],
            "completion_context_candidate_ids": [],
            "selected_bundle_size": 1,
        },
        "scope_layer": {
            "status": "abstained",
            "text": "",
            "supporting_overlay_candidate_ids": [],
            "source_field": "",
        },
        "trust_state": {
            "label": "fallback_seed_floor_with_risks",
            "definition_grounded": False,
            "scope_grounded": False,
            "context_status": "fallback_context",
            "low_trust": True,
        },
        "risk_flags": [
            "seed_definition_floor_active",
            "definition_enrichment_missing",
            "context_fallback_active",
            "low_trust_survivor",
            "review_needs_attention",
            "scope_gap_reviewer_editable",
        ],
        "review_readiness": {
            "label": "low_trust",
            "survives_review_lane": True,
            "needs_attention": True,
            "draft_status_compatibility": "draft_ready_with_holds",
            "reasons": ["seed_definition_floor_active", "context_fallback_active"],
        },
        "definition_full_candidate": {
            "status": "abstained",
            "text": "",
            "supporting_overlay_candidate_ids": [],
            "selection_reason": "definition_full_candidate_abstained",
            "hold_reasons": ["definition_support_insufficient"],
            "source_text_field": "",
        },
        "definition_short_candidate": {
            "status": "abstained",
            "text": "",
            "supporting_overlay_candidate_ids": [],
            "selection_reason": "definition_short_candidate_abstained",
            "hold_reasons": ["definition_short_unavailable"],
            "source_text_field": "",
        },
        "scope_candidate": {
            "status": "abstained",
            "text": "",
            "supporting_overlay_candidate_ids": [],
            "selection_reason": "scope_candidate_abstained",
            "hold_reasons": ["scope_support_insufficient"],
            "source_text_field": "",
        },
        "evidence_bundle": [_synthetic_evidence_item(kc_id=kc_id)],
        "support_summary": {"support_state": "insufficient_support"},
        "contamination_flags": [],
        "hold_reasons": ["definition_support_insufficient", "scope_support_insufficient"],
        "field_hold_reasons": {
            "definition_full_candidate": ["definition_support_insufficient"],
            "scope_candidate": ["scope_support_insufficient"],
        },
        "field_provenance_map": {
            "definition_full_candidate": {
                "status": "abstained",
                "overlay_candidate_ids": [],
                "source_set_ids": ["step6_6_set"],
                "source_run_ids": ["step6_7_run"],
            },
            "definition_short_candidate": {
                "status": "abstained",
                "overlay_candidate_ids": [],
                "source_set_ids": ["step6_6_set"],
                "source_run_ids": ["step6_7_run"],
            },
            "scope_candidate": {
                "status": "abstained",
                "overlay_candidate_ids": [],
                "source_set_ids": ["step6_6_set"],
                "source_run_ids": ["step6_7_run"],
            },
            "evidence_bundle": {
                "status": "fallback_context",
                "overlay_candidate_ids": [f"{kc_id}:overlay:01"],
                "source_set_ids": ["step6_6_set"],
                "source_run_ids": ["step6_7_run"],
            },
        },
    }


def _synthetic_low_trust_bundle_with_mixed_foreign_definition_support() -> dict[str, object]:
    bundle = _synthetic_low_trust_bundle()
    kc_id = str(bundle["kc_id"])
    field_provenance_map = dict(bundle["field_provenance_map"])
    field_provenance_map["definition_short_candidate"] = {
        "status": "abstained",
        "overlay_candidate_ids": [f"{kc_id}:overlay:01", "KC_FOREIGN_SYN:overlay:99"],
        "source_set_ids": ["step6_6_set"],
        "source_run_ids": ["step6_7_run"],
    }
    bundle["field_provenance_map"] = field_provenance_map
    return bundle


def _synthetic_grounded_bundle() -> dict[str, object]:
    kc_id = "KC_SYN_HIGH"
    hierarchy_fields = _synthetic_hierarchy_fields(kc_id=kc_id, canonical_name="Synthetic Grounded KC")
    return {
        "semantic_contract_version": "step6_7_survival_semantics_v1",
        "draft_status": "draft_ready",
        "kc_id": kc_id,
        "canonical_name": "Synthetic Grounded KC",
        "aliases": [],
        "authoritative_definition_status": AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED,
        **hierarchy_fields,
        "seed_definition": "Seed definition.",
        "survival_floor": {
            "status": "seed_definition_floor",
            "text": "Seed definition.",
            "canonical_name": "Synthetic Grounded KC",
            "source_field": "hierarchy.seed_definition",
            "used_as_definition_fallback": False,
        },
        "enrichment_layer": {
            "status": "grounded",
            "text": "A grounded synthetic definition supported by corpus evidence.",
            "short_text": "A grounded synthetic definition.",
            "supporting_overlay_candidate_ids": [f"{kc_id}:overlay:01"],
            "source_field": "definition_full_candidate",
        },
        "context_layer": {
            "status": "grounded",
            "snippet_surfaces": ["Synthetic evidence sentence for packetization coverage."],
            "supporting_overlay_candidate_ids": [f"{kc_id}:overlay:01"],
            "source_document_ids": ["doc.synthetic"],
            "family_context_candidate_ids": [],
            "completion_context_candidate_ids": [],
            "selected_bundle_size": 1,
        },
        "scope_layer": {
            "status": "grounded",
            "text": "Applies when reviewing grounded synthetic examples.",
            "supporting_overlay_candidate_ids": [f"{kc_id}:overlay:01"],
            "source_field": "scope_candidate",
        },
        "trust_state": {
            "label": "grounded",
            "definition_grounded": True,
            "scope_grounded": True,
            "context_status": "grounded",
            "low_trust": False,
        },
        "risk_flags": [],
        "review_readiness": {
            "label": "ready",
            "survives_review_lane": True,
            "needs_attention": False,
            "draft_status_compatibility": "draft_ready",
            "reasons": [],
        },
        "definition_full_candidate": {
            "status": "grounded",
            "text": "A grounded synthetic definition supported by corpus evidence.",
            "supporting_overlay_candidate_ids": [f"{kc_id}:overlay:01"],
            "selection_reason": "synthetic",
            "hold_reasons": [],
            "source_text_field": "quote_surface",
        },
        "definition_short_candidate": {
            "status": "grounded",
            "text": "A grounded synthetic definition.",
            "supporting_overlay_candidate_ids": [f"{kc_id}:overlay:01"],
            "selection_reason": "synthetic_short",
            "hold_reasons": [],
            "source_text_field": "quote_surface",
        },
        "scope_candidate": {
            "status": "grounded",
            "text": "Applies when reviewing grounded synthetic examples.",
            "supporting_overlay_candidate_ids": [f"{kc_id}:overlay:01"],
            "selection_reason": "synthetic_scope",
            "hold_reasons": [],
            "source_text_field": "quote_surface",
        },
        "evidence_bundle": [_synthetic_evidence_item(kc_id=kc_id)],
        "support_summary": {"support_state": "strict_leaf_support"},
        "contamination_flags": [],
        "hold_reasons": [],
        "field_hold_reasons": {},
        "field_provenance_map": {
            "definition_full_candidate": {
                "status": "grounded",
                "overlay_candidate_ids": [f"{kc_id}:overlay:01"],
                "source_set_ids": ["step6_6_set"],
                "source_run_ids": ["step6_7_run"],
            },
            "definition_short_candidate": {
                "status": "grounded",
                "overlay_candidate_ids": [f"{kc_id}:overlay:01"],
                "source_set_ids": ["step6_6_set"],
                "source_run_ids": ["step6_7_run"],
            },
            "scope_candidate": {
                "status": "grounded",
                "overlay_candidate_ids": [f"{kc_id}:overlay:01"],
                "source_set_ids": ["step6_6_set"],
                "source_run_ids": ["step6_7_run"],
            },
            "evidence_bundle": {
                "status": "grounded",
                "overlay_candidate_ids": [f"{kc_id}:overlay:01"],
                "source_set_ids": ["step6_6_set"],
                "source_run_ids": ["step6_7_run"],
            },
        },
    }


def _synthetic_clean_high_support_grounded_bundle() -> dict[str, object]:
    bundle = _synthetic_grounded_bundle()
    kc_id = str(bundle["kc_id"])
    bundle["evidence_bundle"] = [
        _synthetic_evidence_item(kc_id=kc_id, suffix="01"),
        _synthetic_evidence_item(kc_id=kc_id, suffix="02"),
    ]
    return bundle


def _synthetic_clean_high_support_grounded_bundle_with_strong_risk_flag() -> dict[str, object]:
    bundle = _synthetic_clean_high_support_grounded_bundle()
    bundle["risk_flags"] = ["provenance_repairs_present"]
    return bundle


def _synthetic_low_trust_bundle_with_high_contamination() -> dict[str, object]:
    bundle = _synthetic_low_trust_bundle()
    bundle["risk_flags"] = [
        "high_contamination_candidates_present",
        *[flag for flag in bundle["risk_flags"] if flag != "high_contamination_candidates_present"],
    ]
    return bundle


def _synthetic_grounded_bundle_with_invalid_page_index_span() -> dict[str, object]:
    bundle = _synthetic_grounded_bundle()
    invalid_item = _synthetic_evidence_item(kc_id="KC_SYN_HIGH", suffix="bad")
    invalid_item["page_index"] = -1
    invalid_item["bundle_role"] = "context_support"
    invalid_item["provenance_normalization_status"] = "dropped"
    invalid_item["quote_surface"] = "Synthetic invalid evidence sentence that should be dropped."
    invalid_item["source_block_text"] = "Synthetic invalid evidence sentence that should be dropped."
    bundle["evidence_bundle"] = [bundle["evidence_bundle"][0], invalid_item]
    return bundle


def test_restarted_review_packet_preserves_empty_kc_specific_criteria_on_real_bundle():
    bundle_path = REPO_ROOT / "data/processed/kc_drafts/2026-04-08_131447/kc_draft_bundles.jsonl"
    bundle = next(
        item
        for item in read_jsonl(bundle_path)
        if str(item.get("draft_status") or "") in {"draft_ready", "draft_ready_with_holds"}
    )

    packet = build_restarted_review_packet(
        draft_bundle=bundle,
        step4_set_id="step4_set",
        step4_5_set_id="step4_5_set",
        step5_set_id="step5_set",
        step6_6_set_id="step6_6_set",
        step6_7_set_id="step6_7_set",
        step6_7b_set_id="",
        step6_8_run_id="2026-04-11_test",
    )

    assert "kc_specific_criteria" in packet
    assert packet["kc_specific_criteria"] == ""
    validate_restarted_review_packet(packet)


def test_step67_bundle_emits_typed_hierarchy_fields():
    bundles, _ = build_kc_draft_bundles(
        [
            _synthetic_overlay_row(
                kc_id="KC_SYN_HIER",
                canonical_name="Synthetic Hierarchy KC",
                suffix="01",
                text="Synthetic Hierarchy KC is a grounded synthetic concept.",
                topic_path_labels=["Synthetic Domain", "Synthetic Branch"],
            )
        ]
    )

    bundle = bundles[0]

    assert bundle["topic_path_labels"] == ["Synthetic Domain", "Synthetic Branch"]
    assert len(bundle["topic_path_ids"]) == 2
    assert bundle["parent_topic_label"] == "Synthetic Branch"
    assert bundle["ancestor_topic_labels"] == ["Synthetic Domain", "Synthetic Branch"]
    assert bundle["hierarchy_ancestry"]["source_hierarchy_path"] == [
        "Synthetic Domain",
        "Synthetic Branch",
        "Synthetic Hierarchy KC",
    ]
    assert bundle["authoritative_definition_status"] in {
        AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED,
        AUTHORITATIVE_DEFINITION_STATUS_SEED_FLOOR_FALLBACK,
    }


def test_restarted_review_packet_survives_explicit_low_trust_bundle():
    packet = build_restarted_review_packet(
        draft_bundle=_synthetic_low_trust_bundle(),
        step4_set_id="step4_set",
        step4_5_set_id="step4_5_set",
        step5_set_id="step5_set",
        step6_6_set_id="step6_6_set",
        step6_7_set_id="step6_7_set",
        step6_7b_set_id="",
        step6_8_run_id="2026-04-11_semantics_test",
    )

    assert REQUIRED_REVIEWER_DECISION_FIELDS <= set(packet)
    assert packet["seed_definition"] == "A synthetic seed definition used only as an explicit fallback floor."
    assert packet["definition_draft"] == "A synthetic seed definition used only as an explicit fallback floor."
    assert packet["draft_status"] == "draft_ready_with_holds"
    assert packet["authoritative_definition_status"] == AUTHORITATIVE_DEFINITION_STATUS_SEED_FLOOR_FALLBACK
    assert packet["trust_state"]["label"] == "fallback_seed_floor_with_risks"
    assert packet["review_readiness"]["label"] == "low_trust"
    assert packet["system_recommendation"]["label"] == "review_needed"
    assert "survival_floor_keep_and_edit" in packet["system_recommendation"]["reason_codes"]
    assert "keep the KC in the review lane and edit the definition or scope" in packet["notes_for_reviewer"]
    assert packet["topic_path_labels"] == ["Synthetic Domain", "Synthetic Branch"]
    assert packet["parent_topic_label"] == "Synthetic Branch"
    assert "low_trust_review" in packet["risk_flags"]
    assert packet["kc_specific_criteria"] == ""
    validate_restarted_review_packet(packet)


def test_clean_high_support_grounded_packet_can_still_be_approve_ready():
    packet = build_restarted_review_packet(
        draft_bundle=_synthetic_clean_high_support_grounded_bundle(),
        step4_set_id="step4_set",
        step4_5_set_id="step4_5_set",
        step5_set_id="step5_set",
        step6_6_set_id="step6_6_set",
        step6_7_set_id="step6_7_set",
        step6_7b_set_id="",
        step6_8_run_id="2026-04-14_clean_high_support_test",
    )

    assert packet["review_priority"]["bucket"] == "high_support"
    assert packet["system_recommendation"]["label"] == "approve_ready"
    validate_restarted_review_packet(packet)


def test_grounded_packet_with_strong_risk_flag_is_downgraded_from_approve_ready_to_review_needed():
    packet = build_restarted_review_packet(
        draft_bundle=_synthetic_clean_high_support_grounded_bundle_with_strong_risk_flag(),
        step4_set_id="step4_set",
        step4_5_set_id="step4_5_set",
        step5_set_id="step5_set",
        step6_6_set_id="step6_6_set",
        step6_7_set_id="step6_7_set",
        step6_7b_set_id="",
        step6_8_run_id="2026-04-14_strong_risk_downgrade_test",
    )

    assert packet["review_priority"]["bucket"] == "high_support"
    assert packet["system_recommendation"]["label"] == "review_needed"
    assert "approve_ready_blocked_by_strong_risk" in packet["system_recommendation"]["reason_codes"]
    assert "strong_risk_flag:provenance_repairs_present" in packet["system_recommendation"]["reason_codes"]
    validate_restarted_review_packet(packet)


def test_clearly_suspicious_low_trust_packet_can_still_be_reject_recommended():
    packet = build_restarted_review_packet(
        draft_bundle=_synthetic_low_trust_bundle_with_high_contamination(),
        step4_set_id="step4_set",
        step4_5_set_id="step4_5_set",
        step5_set_id="step5_set",
        step6_6_set_id="step6_6_set",
        step6_7_set_id="step6_7_set",
        step6_7b_set_id="",
        step6_8_run_id="2026-04-14_suspicious_low_trust_test",
    )

    assert packet["system_recommendation"]["label"] == "reject_recommended"
    assert "suspicious_survival_floor_packet" in packet["system_recommendation"]["reason_codes"]
    assert "suspicious_risk_flag:high_contamination_candidates_present" in packet["system_recommendation"]["reason_codes"]
    validate_restarted_review_packet(packet)


def test_restarted_review_packet_keeps_reject_recommendation_for_mixed_foreign_low_trust_survivor():
    packet = build_restarted_review_packet(
        draft_bundle=_synthetic_low_trust_bundle_with_mixed_foreign_definition_support(),
        step4_set_id="step4_set",
        step4_5_set_id="step4_5_set",
        step5_set_id="step5_set",
        step6_6_set_id="step6_6_set",
        step6_7_set_id="step6_7_set",
        step6_7b_set_id="",
        step6_8_run_id="2026-04-14_mixed_foreign_test",
    )

    assert packet["system_recommendation"]["label"] == "reject_recommended"
    assert "definition_decisive_support_mixed_foreign" in packet["risk_flags"]
    validate_restarted_review_packet(packet)


def test_restarted_review_packet_emits_hierarchy_fields_and_authoritative_status():
    packet = build_restarted_review_packet(
        draft_bundle=_synthetic_grounded_bundle(),
        step4_set_id="step4_set",
        step4_5_set_id="step4_5_set",
        step5_set_id="step5_set",
        step6_6_set_id="step6_6_set",
        step6_7_set_id="step6_7_set",
        step6_7b_set_id="",
        step6_8_run_id="2026-04-11_hierarchy_test",
    )

    assert REQUIRED_REVIEWER_DECISION_FIELDS <= set(packet)
    assert packet["authoritative_definition_status"] == AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED
    assert packet["seed_definition"] == "Seed definition."
    assert packet["trust_state"]["label"] == "grounded"
    assert packet["review_readiness"]["label"] == "ready"
    assert packet["topic_path_labels"] == ["Synthetic Domain", "Synthetic Branch"]
    assert len(packet["topic_path_ids"]) == 2
    assert packet["parent_topic_label"] == "Synthetic Branch"
    assert packet["ancestor_topic_labels"] == ["Synthetic Domain", "Synthetic Branch"]
    assert packet["hierarchy_ancestry"]["source_hierarchy_path"] == [
        "Synthetic Domain",
        "Synthetic Branch",
        "Synthetic Grounded KC",
    ]
    validate_restarted_review_packet(packet)


def test_restarted_review_packet_drops_invalid_negative_page_index_span():
    packet = build_restarted_review_packet(
        draft_bundle=_synthetic_grounded_bundle_with_invalid_page_index_span(),
        step4_set_id="step4_set",
        step4_5_set_id="step4_5_set",
        step5_set_id="step5_set",
        step6_6_set_id="step6_6_set",
        step6_7_set_id="step6_7_set",
        step6_7b_set_id="",
        step6_8_run_id="2026-04-11_invalid_page_index_test",
    )

    assert len(packet["evidence_spans"]) == 1
    assert packet["evidence_spans"][0]["page_index"] == 0
    assert packet["risk_flags"].count("invalid_page_index_dropped") == 1
    validate_restarted_review_packet(packet)


def test_emit_restarted_review_packets_keeps_one_packet_per_bundle(monkeypatch):
    captured: dict[str, object] = {}

    def fake_write_json(path: Path, obj):
        captured[str(path)] = obj

    def fake_write_jsonl(path: Path, rows):
        captured[str(path)] = list(rows)

    def fake_write_text(self, text, encoding="utf-8"):
        captured[str(self)] = text
        return len(text)

    monkeypatch.setattr(packetization_module, "write_json", fake_write_json)
    monkeypatch.setattr(packetization_module, "write_jsonl", fake_write_jsonl)
    monkeypatch.setattr(Path, "write_text", fake_write_text)

    output_dir = REPO_ROOT / "data" / "work" / "cache"
    result = emit_restarted_review_packets_from_draft_bundles(
        source_processed_dir=REPO_ROOT / "data" / "work" / "cache",
        output_dir=output_dir,
        draft_rows=[_synthetic_clean_high_support_grounded_bundle(), _synthetic_low_trust_bundle()],
        step4_set_id="step4_set",
        step4_5_set_id="step4_5_set",
        step5_set_id="step5_set",
        step6_6_set_id="step6_6_set",
        step6_7_set_id="step6_7_set",
        step6_7b_set_id="",
        step6_8_run_id="2026-04-11_semantics_test",
        step6_7_drafting_runtime={"execution_mode": "llm", "llm_path_invoked": True, "llm_calls": 2},
    )

    summary = captured[str(result.summary_path)]
    packets = captured[str(result.packet_path)]

    assert result.packet_count == 2
    assert result.excluded_candidate_count == 0
    assert summary["packet_count"] == 2
    assert summary["excluded_kcs"] == []
    assert summary["quarantined_kcs"] == []
    assert all(REQUIRED_REVIEWER_DECISION_FIELDS <= set(packet) for packet in packets)
    assert summary["low_trust_packet_count"] == 1
    assert summary["fallback_definition_count"] == 1
    assert summary["normalized_grounded_definition_count"] == 0
    assert summary["recommendation_counts"].get("reject_recommended", 0) == 0
    assert summary["recommendation_counts"]["approve_ready"] == 1
    assert summary["recommendation_counts"]["review_needed"] == 1
    assert summary["authoritative_definition_status_counts"] == {
        AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED: 1,
        AUTHORITATIVE_DEFINITION_STATUS_SEED_FLOOR_FALLBACK: 1,
    }


def test_emit_restarted_review_packets_counts_dropped_invalid_page_index_spans(monkeypatch):
    captured: dict[str, object] = {}

    def fake_write_json(path: Path, obj):
        captured[str(path)] = obj

    def fake_write_jsonl(path: Path, rows):
        captured[str(path)] = list(rows)

    def fake_write_text(self, text, encoding="utf-8"):
        captured[str(self)] = text
        return len(text)

    monkeypatch.setattr(packetization_module, "write_json", fake_write_json)
    monkeypatch.setattr(packetization_module, "write_jsonl", fake_write_jsonl)
    monkeypatch.setattr(Path, "write_text", fake_write_text)

    output_dir = REPO_ROOT / "data" / "work" / "cache"
    result = emit_restarted_review_packets_from_draft_bundles(
        source_processed_dir=REPO_ROOT / "data" / "work" / "cache",
        output_dir=output_dir,
        draft_rows=[_synthetic_grounded_bundle_with_invalid_page_index_span()],
        step4_set_id="step4_set",
        step4_5_set_id="step4_5_set",
        step5_set_id="step5_set",
        step6_6_set_id="step6_6_set",
        step6_7_set_id="step6_7_set",
        step6_7b_set_id="",
        step6_8_run_id="2026-04-11_invalid_page_index_summary_test",
        step6_7_drafting_runtime={"execution_mode": "llm", "llm_path_invoked": True, "llm_calls": 1},
    )

    summary = captured[str(result.summary_path)]
    packets = captured[str(result.packet_path)]

    assert result.packet_count == 1
    assert summary["packet_count"] == 1
    assert summary["excluded_candidate_count"] == 0
    assert summary["quarantine_count"] == 0
    assert summary["dropped_invalid_page_index_span_count"] == 1
    assert summary["packets_with_invalid_page_index_drops"] == ["KC_SYN_HIGH"]
    assert packets[0]["risk_flags"].count("invalid_page_index_dropped") == 1
