from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_SRC = REPO_ROOT / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from kc_l.retrieval_gate.evidence_stage_v3_candidate_bank import (  # noqa: E402
    PROFILE_PROVENANCE_REHYDRATION,
    run_candidate_bank_stage,
)
from kc_l.retrieval_gate.evidence_stage_v3_scored_candidates import score_candidate_row  # noqa: E402


TEST_ROOT = REPO_ROOT / ".codex_tmp_test_step5x_profile_provenance_rehydration"


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _registry_row() -> dict[str, object]:
    return {
        "kc_id": "KC_SIGNAL_001",
        "canonical_name": "Signal Dropout Cause",
        "aliases": [],
        "topic_path_labels": ["Signal Systems", "Signal Reliability"],
        "topic_path_ids": ["topic_signal_systems", "topic_signal_reliability"],
        "parent_topic_id": "topic_signal_reliability",
        "parent_topic_label": "Signal Reliability",
        "sibling_labels": ["Signal Dropout Effect"],
    }


def _sentence_row(
    text: str,
    *,
    sentence_id: str = "DOC_SIGNAL:block_1::s000",
    snippet_id: str = "SRC_SIGNAL_001",
    block_id: str = "DOC_SIGNAL:block_1",
) -> dict[str, object]:
    return {
        "sentence_id": sentence_id,
        "snippet_id": snippet_id,
        "doc_id": "DOC_SIGNAL",
        "block_id": block_id,
        "sent_idx": 0,
        "char_start": 0,
        "char_end": len(text),
        "page_index": 1,
        "layer": "synthetic",
        "bbox": [1.0, 2.0, 3.0, 4.0],
        "patch_id": "patch-signal",
        "patch_heading": "Signal Reliability",
        "reveal_group_id": "group-signal",
        "sentence_text": text,
        "source_block_text": text,
        "is_meta": False,
        "is_nav_boilerplate": False,
        "is_author_affiliation": False,
        "is_transition_text": False,
        "is_heading_like": False,
        "is_formula_like": False,
        "is_definition_like": True,
        "is_procedure_like": False,
        "is_example_like": False,
    }


def _profile_row(*, context_only: bool = False, duplicate_sources: bool = False) -> dict[str, object]:
    route = {
        "route_id": "route_signal_observed",
        "route_type": "context_locator" if context_only else "anchored_phrase",
        "activation": "context_only" if context_only else "active",
        "route_strength": "strong",
        "verification_status": "source_observed_same_window",
        "primary_terms_any": ["signal dropout occurs"],
        "support_terms_any": [],
        "support_terms_all": [],
        "negative_terms_any": [],
        "source_provenance_ids": ["SRC_SIGNAL_001"],
        "provenance": [{"snippet_id": "SRC_SIGNAL_001", "field_path": "sentence_text"}],
        "can_create_candidates": True,
        "can_create_positive_support": not context_only,
        "broad_context_only": context_only,
    }
    profile = {
        "kc_id": "KC_SIGNAL_001",
        "canonical_name": "Signal Dropout Cause",
        "profile_status": "usable",
        "accepted_source_cues": [
            {
                "term": "signal dropout occurs",
                "active": True,
                "cue_type": "context_phrase" if context_only else "definition_phrase",
                "provenance": [{"snippet_id": "SRC_SIGNAL_001", "field_path": "sentence_text"}],
            }
        ],
        "query_variants": [
            {
                "query": "signal dropout occurs",
                "active": True,
                "source": "accepted_source_cue",
                "cue_type": "definition_phrase",
                "retrieval_role": "lexical_query",
                "retrieval_channels": ["lexical"],
                "step5x_eligible": True,
                "provenance": [{"snippet_id": "SRC_SIGNAL_001", "field_path": "sentence_text"}],
            }
        ],
        "retrieval_routes": [route],
        "expected_evidence_shape_hints": [
            {
                "shape": "definition_phrase",
                "shape_family": "definition",
                "source": "accepted_source_cue",
                "confidence": "medium",
                "provenance": [{"snippet_id": "SRC_SIGNAL_001", "field_path": "sentence_text"}],
            }
        ],
    }
    if duplicate_sources:
        profile["retrieval_routes"].append(dict(route, route_id="route_signal_duplicate"))
    return profile


def _run_candidate_bank(profile: dict[str, object], source_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    root = TEST_ROOT
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    registry_jsonl = root / "registry.jsonl"
    source_overlay_jsonl = root / "source_overlay.jsonl"
    profile_jsonl = root / "profiles.jsonl"
    output_root = root / "out"

    _write_jsonl(registry_jsonl, [_registry_row()])
    _write_jsonl(source_overlay_jsonl, source_rows)
    _write_jsonl(profile_jsonl, [profile])

    run_candidate_bank_stage(
        run_id="profile_provenance_test",
        step5_3_set_manifest_spec=None,
        step5_3_candidates_jsonl_spec=None,
        registry_jsonl_spec=str(registry_jsonl),
        source_overlay_jsonl_spec=str(source_overlay_jsonl),
        profile_jsonl_spec=str(profile_jsonl),
        config_path="tests://profile_provenance_test",
        exact_kc_ids=["KC_SIGNAL_001"],
        limit_kcs=1,
        output_root=output_root,
        set_manifest_root=output_root / "_sets",
        allow_reference_artifact_inputs=True,
        fail_if_no_candidate_source=True,
        exclude_seed_fields=True,
        preserve_raw_support_profile=True,
        preserve_raw_alignment_breakdown=True,
        source_surface_fallback_cfg={"enabled": False, "dynamic_broad_token_min_doc_frequency": 2},
        repo_root=root,
    )
    candidate_path = output_root / "profile_provenance_test" / "candidate_bank.jsonl"
    return [json.loads(line) for line in candidate_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_profile_provenance_rehydration_emits_exact_source_observed_route_sentence() -> None:
    rows = _run_candidate_bank(
        _profile_row(),
        [_sentence_row("The signal dropout occurs when an input connector loses its carrier.")],
    )
    rehydrated = [row for row in rows if row.get("candidate_source") == PROFILE_PROVENANCE_REHYDRATION]
    assert len(rehydrated) == 1
    row = rehydrated[0]
    assert row["text"] == "The signal dropout occurs when an input connector loses its carrier."
    assert row["retrieval_intent"] == PROFILE_PROVENANCE_REHYDRATION
    assert row["candidate_origin"] == PROFILE_PROVENANCE_REHYDRATION
    assert row["authority_contract"] == "step5x_must_verify_against_source_rows"
    assert row["provenance"]["step5p_source_provenance_rehydrated"] is True
    assert row["provenance"]["source_provenance_id"] == "SRC_SIGNAL_001"
    assert row["provenance"]["profile_output_role"] == "retrieval_control_metadata_not_evidence"
    assert row["support_profile"]["fallback_tier"] == "profile_provenance"
    assert row["alignment_breakdown"]["source_observed_profile_provenance"] is True


def test_profile_provenance_rehydration_does_not_make_context_route_positive_by_itself() -> None:
    rows = _run_candidate_bank(
        _profile_row(context_only=True),
        [_sentence_row("This section discusses signal reliability across several environments.")],
    )
    row = [item for item in rows if item.get("candidate_source") == PROFILE_PROVENANCE_REHYDRATION][0]
    assert row["review_only_candidate"] is True
    assert row["support_profile"]["generic_context_only"] is True
    scored = score_candidate_row(row)
    assert scored["routing_recommendation"] == "review_only_candidate"
    assert not scored["role_eligibility"]["positive_support_eligible"]


def test_profile_provenance_rehydration_deduplicates_existing_surface_candidate() -> None:
    rows = _run_candidate_bank(
        _profile_row(duplicate_sources=True),
        [_sentence_row("The signal dropout occurs when an input connector loses its carrier.")],
    )
    rehydrated = [row for row in rows if row.get("candidate_source") == PROFILE_PROVENANCE_REHYDRATION]
    assert len(rehydrated) == 1
    assert sum(1 for row in rows if row.get("sentence_id") == "DOC_SIGNAL:block_1::s000") <= 2


if __name__ == "__main__":
    test_profile_provenance_rehydration_emits_exact_source_observed_route_sentence()
    test_profile_provenance_rehydration_does_not_make_context_route_positive_by_itself()
    test_profile_provenance_rehydration_deduplicates_existing_surface_candidate()
    print("TEST_STEP5X_PROFILE_PROVENANCE_REHYDRATION_OK")
