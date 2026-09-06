from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_SRC = REPO_ROOT / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from kc_l.retrieval_gate.evidence_stage_v3_candidate_bank import (
    FORBIDDEN_SEED_FIELDS,
    REQUIRED_ROW_KEYS,
    SOURCE_DIRECT_OVERLAY_SUPPLEMENT,
    run_candidate_bank_stage,
)
from kc_l.retrieval_gate.evidence_stage_v3_pack_composition import (
    compose_evidence_packs_from_scored_candidates,
)
from kc_l.retrieval_gate.evidence_stage_v3_scored_candidates import (
    score_candidate_rows,
)


TEST_ROOT = REPO_ROOT / ".codex_tmp_test_step5x_direct_overlay_supplement_lane"


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _registry_row(
    *,
    kc_id: str = "KC_NEUTRAL_001",
    canonical_name: str = "Two-Way Option Partition",
    aliases: list[str] | None = None,
) -> dict[str, object]:
    return {
        "kc_id": kc_id,
        "canonical_name": canonical_name,
        "aliases": list(aliases or []),
        "topic_path_labels": ["Neutral Systems", "Partitioning"],
        "topic_path_ids": ["topic_neutral_systems", "topic_partitioning"],
        "parent_topic_id": "topic_partitioning",
        "parent_topic_label": "Partitioning",
        "sibling_labels": ["One-Way Partition"],
    }


def _source_overlay_row(text: str = "Introductory preface without target cues.") -> dict[str, object]:
    return {
        "sentence_text": text,
        "source_block_text": text,
        "doc_id": "DOC_BACKGROUND",
        "page_index": 1,
        "block_id": "DOC_BACKGROUND:block_1",
        "sentence_id": "DOC_BACKGROUND:block_1::s000",
        "sent_idx": 0,
        "patch_id": "patch-bg",
        "patch_heading": "Background",
        "reveal_group_id": "group-bg",
        "layer": "mineru",
        "bbox": [1.0, 2.0, 3.0, 4.0],
        "char_start": 0,
        "char_end": len(text),
        "is_meta": False,
        "is_nav_boilerplate": False,
        "is_author_affiliation": False,
        "is_transition_text": False,
        "is_heading_like": False,
        "is_formula_like": False,
        "is_definition_like": False,
        "is_procedure_like": False,
        "is_example_like": False,
    }


def _supplement_row(
    text: str,
    *,
    kc_id: str = "KC_NEUTRAL_001",
    canonical_name: str = "Two-Way Option Partition",
    candidate_id: str = "supp-1",
    doc_id: str = "DOC_TARGET",
    page_index: int = 3,
    block_id: str = "DOC_TARGET:block_1",
    sentence_id: str = "DOC_TARGET:block_1::s000",
    patch_id: str = "patch-1",
    layer: str = "mineru",
    target_signals: list[str] | None = None,
    reasons: list[str] | None = None,
    flags: dict[str, object] | None = None,
) -> dict[str, object]:
    row = {
        "kc_id": kc_id,
        "canonical_name": canonical_name,
        "candidate_id": candidate_id,
        "candidate_source": "audit_overlay_candidate",
        "doc_id": doc_id,
        "page_index": page_index,
        "block_id": block_id,
        "sentence_id": sentence_id,
        "patch_id": patch_id,
        "candidate_text": text,
        "source_block_text": text,
        "patch_heading": "Partitioning Notes",
        "reveal_group_id": "group-1",
        "layer": layer,
        "bbox": [0.0, 0.0, 1.0, 1.0],
        "char_start": 0,
        "char_end": len(text),
        "is_meta": False,
        "is_nav_boilerplate": False,
        "is_author_affiliation": False,
        "is_transition_text": False,
        "is_heading_like": False,
        "is_formula_like": False,
        "is_definition_like": True,
        "is_procedure_like": True,
        "is_example_like": False,
        "target_signals": list(target_signals or ["binary split"]),
        "v5_reasons": list(
            reasons
            or [
                "required:binary split",
                "context:partition,two groups",
                "strong:binary split",
            ]
        ),
        "v5_blockers": [],
    }
    row.update(dict(flags or {}))
    return row


def _profile_row(*, negative_term: str) -> dict[str, object]:
    return {
        "kc_id": "KC_NEUTRAL_001",
        "canonical_name": "Two-Way Option Partition",
        "profile_status": "usable",
        "query_variants": [],
        "accepted_source_cues": [
            {
                "term": "two-way option partition",
                "active": True,
                "cue_type": "definition_phrase",
                "provenance": [{"snippet_id": "S_PROFILE", "field_path": "sentence_text"}],
            }
        ],
        "expected_evidence_shape_hints": [
            {
                "shape": "procedure_description",
                "shape_family": "process",
                "source": "accepted_source_cue",
                "confidence": "medium",
            }
        ],
        "rejected_candidates": [{"term": negative_term, "reason": "wrong_sense"}],
        "audit": {"profile_input_status": "exploratory_only"},
    }


def _route_block_eval() -> dict[str, object]:
    return {
        "route_contract_present": True,
        "matched_route_count": 1,
        "positive_route_match_count": 0,
        "context_only_route_match_count": 0,
        "route_positive_blocked_by_missing_support_count": 0,
        "context_only_match_without_positive_route": False,
        "matched_routes": [
            {
                "route_id": "route_control_only",
                "activation": "active",
                "route_can_create_positive_support_here": False,
            }
        ],
        "route_control_role": "step5p_retrieval_control_metadata_not_evidence",
    }


def _run_clean_slate_stage(
    *,
    name: str,
    supplement_rows: list[dict[str, object]],
    registry_rows: list[dict[str, object]] | None = None,
    source_overlay_rows: list[dict[str, object]] | None = None,
    profile_rows: list[dict[str, object]] | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    root = TEST_ROOT / name
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    registry_jsonl = root / "seedless_registry.jsonl"
    source_overlay_jsonl = root / "sentence_overlay.jsonl"
    supplement_jsonl = root / "direct_overlay_supplement.jsonl"
    profile_jsonl = root / "profiles.jsonl"
    output_root = root / "out"
    set_manifest_root = output_root / "_sets"

    _write_jsonl(registry_jsonl, list(registry_rows or [_registry_row()]))
    _write_jsonl(source_overlay_jsonl, list(source_overlay_rows or [_source_overlay_row()]))
    _write_jsonl(supplement_jsonl, supplement_rows)
    if profile_rows:
        _write_jsonl(profile_jsonl, profile_rows)

    result = run_candidate_bank_stage(
        run_id=name,
        step5_3_set_manifest_spec=None,
        step5_3_candidates_jsonl_spec=None,
        registry_jsonl_spec=str(registry_jsonl),
        source_overlay_jsonl_spec=str(source_overlay_jsonl),
        profile_jsonl_spec=str(profile_jsonl) if profile_rows else None,
        config_path="tests://direct_overlay_supplement",
        exact_kc_ids=["KC_NEUTRAL_001"],
        limit_kcs=1,
        output_root=output_root,
        set_manifest_root=set_manifest_root,
        allow_reference_artifact_inputs=True,
        fail_if_no_candidate_source=True,
        exclude_seed_fields=True,
        preserve_raw_support_profile=True,
        preserve_raw_alignment_breakdown=True,
        source_surface_fallback_cfg={"enabled": False, "dynamic_broad_token_min_doc_frequency": 2},
        direct_overlay_supplement_cfg={
            "enabled": True,
            "supplement_jsonl": str(supplement_jsonl),
            "max_candidates_per_kc": 8,
            "min_score": 4.8,
        },
        repo_root=root,
    )

    candidate_bank_path = REPO_ROOT / result["candidate_bank_jsonl"]
    stats_path = REPO_ROOT / result["candidate_bank_stats_json"]
    rows = [
        json.loads(line)
        for line in candidate_bank_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    return rows, stats


def test_direct_overlay_supplement_translates_into_candidate_bank_contract_without_seed_fields() -> None:
    rows, stats = _run_clean_slate_stage(
        name="contract_translation",
        supplement_rows=[
            _supplement_row("A binary split is a partition of every option into two groups.")
        ],
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["candidate_source"] == SOURCE_DIRECT_OVERLAY_SUPPLEMENT
    assert row["source_surface"] == SOURCE_DIRECT_OVERLAY_SUPPLEMENT
    assert all(key in row for key in REQUIRED_ROW_KEYS)
    assert row["support_profile"]["direct_overlay_supplement"] is True
    assert row["support_profile"]["candidate_source"] == SOURCE_DIRECT_OVERLAY_SUPPLEMENT
    assert row["provenance"]["candidate_source"] == SOURCE_DIRECT_OVERLAY_SUPPLEMENT
    assert row["provenance"]["supplement_candidate_id"] == "supp-1"
    assert row["provenance"]["source_jsonl"].endswith("direct_overlay_supplement.jsonl")
    assert row["alignment_breakdown"]["supplement_target_signals"] == ["binary split"]
    rendered = json.dumps(row, sort_keys=True)
    for field in FORBIDDEN_SEED_FIELDS:
        assert field not in row
        assert field not in rendered
    assert stats["seed_fields_propagated_to_output"] == 0
    assert stats["direct_overlay_supplement"]["candidate_rows_added"] == 1
    assert stats["direct_overlay_supplement"]["quarantine_count"] == 0
    assert stats["direct_overlay_supplement"]["rehydration_queue_count"] == 0


def test_direct_overlay_seed_bearing_input_is_rejected() -> None:
    root = TEST_ROOT / "seed_rejected"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    registry_jsonl = root / "seedless_registry.jsonl"
    source_overlay_jsonl = root / "sentence_overlay.jsonl"
    supplement_jsonl = root / "direct_overlay_supplement.jsonl"

    _write_jsonl(registry_jsonl, [_registry_row()])
    _write_jsonl(source_overlay_jsonl, [_source_overlay_row()])
    _write_jsonl(
        supplement_jsonl,
        [
            _supplement_row(
                "A binary split is a partition of every option into two groups.",
                flags={"seed_definition": "forbidden"},
            )
        ],
    )

    try:
        run_candidate_bank_stage(
            run_id="seed_rejected",
            step5_3_set_manifest_spec=None,
            step5_3_candidates_jsonl_spec=None,
            registry_jsonl_spec=str(registry_jsonl),
            source_overlay_jsonl_spec=str(source_overlay_jsonl),
            profile_jsonl_spec=None,
            config_path="tests://direct_overlay_seed_rejected",
            exact_kc_ids=["KC_NEUTRAL_001"],
            limit_kcs=1,
            output_root=root / "out",
            set_manifest_root=root / "out" / "_sets",
            allow_reference_artifact_inputs=True,
            fail_if_no_candidate_source=True,
            exclude_seed_fields=True,
            preserve_raw_support_profile=True,
            preserve_raw_alignment_breakdown=True,
            source_surface_fallback_cfg={"enabled": False},
            direct_overlay_supplement_cfg={
                "enabled": True,
                "supplement_jsonl": str(supplement_jsonl),
            },
            repo_root=root,
        )
    except RuntimeError as exc:
        assert "forbidden seed fields" in str(exc)
    else:
        raise AssertionError("Expected seed-bearing supplement input to be rejected.")


def test_fragment_only_direct_overlay_row_is_rehydration_queued_not_admitted() -> None:
    rows, stats = _run_clean_slate_stage(
        name="fragment_rehydration",
        supplement_rows=[
            _supplement_row("A binary split is given by")
        ],
    )

    assert rows == []
    assert stats["direct_overlay_supplement"]["candidate_rows_added"] == 0
    assert stats["direct_overlay_supplement"]["rehydration_queue_count"] == 1
    assert stats["direct_overlay_supplement"]["quarantine_count"] == 0


def test_prompt_like_direct_overlay_row_is_quarantined() -> None:
    rows, stats = _run_clean_slate_stage(
        name="prompt_quarantine",
        supplement_rows=[
            _supplement_row("Explain the two-way option partition in your own words.")
        ],
    )

    assert rows == []
    assert stats["direct_overlay_supplement"]["candidate_rows_added"] == 0
    assert stats["direct_overlay_supplement"]["quarantine_count"] == 1
    assert stats["direct_overlay_supplement"]["rejected_counts"]["prompt_like"] == 1


def test_reference_like_direct_overlay_row_is_quarantined() -> None:
    rows, stats = _run_clean_slate_stage(
        name="reference_quarantine",
        supplement_rows=[
            _supplement_row(
                "Two-Way Option Partition. Journal of Neutral Systems References, 2020."
            )
        ],
    )

    assert rows == []
    assert stats["direct_overlay_supplement"]["candidate_rows_added"] == 0
    assert stats["direct_overlay_supplement"]["quarantine_count"] == 1
    assert stats["direct_overlay_supplement"]["rejected_counts"]["reference_like"] == 1


def test_duplicate_extractor_variants_are_suppressed() -> None:
    rows, stats = _run_clean_slate_stage(
        name="duplicate_variants",
        supplement_rows=[
            _supplement_row(
                "A binary split is a partition of every option into two groups.",
                candidate_id="supp-strong",
                sentence_id="DOC_TARGET:block_1::s000",
                patch_id="patch-dup",
                layer="mineru",
            ),
            _supplement_row(
                "A binary split is a partition of every option into two groups",
                candidate_id="supp-weak",
                sentence_id="DOC_TARGET:block_1::s001",
                patch_id="patch-dup",
                layer="pymupdf",
            ),
        ],
    )

    assert len(rows) == 1
    assert rows[0]["provenance"]["supplement_candidate_id"] == "supp-strong"
    assert stats["direct_overlay_supplement"]["candidate_rows_added"] == 1
    assert stats["direct_overlay_supplement"]["dropped_same_patch_weaker_variant_count"] == 1


def test_same_patch_weaker_variant_is_suppressed() -> None:
    rows, stats = _run_clean_slate_stage(
        name="same_patch_weaker",
        supplement_rows=[
            _supplement_row(
                "A binary split is a partition of every option into two groups and keeps two resulting branches.",
                candidate_id="supp-complete",
                sentence_id="DOC_TARGET:block_1::s010",
                patch_id="patch-stronger",
                layer="mineru",
            ),
            _supplement_row(
                "A binary split is a partition of every option into two groups.",
                candidate_id="supp-shorter",
                sentence_id="DOC_TARGET:block_1::s011",
                patch_id="patch-stronger",
                layer="mineru",
            ),
        ],
    )

    assert len(rows) == 1
    assert rows[0]["provenance"]["supplement_candidate_id"] == "supp-complete"
    assert stats["direct_overlay_supplement"]["candidate_rows_added"] == 1
    assert stats["direct_overlay_supplement"]["dropped_same_patch_weaker_variant_count"] == 1


def test_clean_direct_overlay_candidate_bypasses_missing_profile_route_match_and_reaches_real_composer() -> None:
    rows, stats = _run_clean_slate_stage(
        name="composer_path_route_block",
        supplement_rows=[
            _supplement_row(
                "A binary split is a partition of every option into two groups.",
                target_signals=["binary split"],
                reasons=[
                    "required:binary split",
                    "strong:binary split",
                    "shapes:definition_like,procedure_or_explanation_like",
                ],
            )
        ],
    )

    assert stats["direct_overlay_supplement"]["candidate_rows_added"] == 1
    rows[0]["step5p_route_evaluation"] = _route_block_eval()
    scored_rows = score_candidate_rows(rows)
    assert len(scored_rows) == 1
    scored = scored_rows[0]
    assert scored["candidate_source"] == SOURCE_DIRECT_OVERLAY_SUPPLEMENT
    assert scored["lexical_target_binding"]["binding_strength"] in {"usable", "strong"}
    assert scored["candidate_quality"]["target_bound_positive_support"] is True
    assert scored["candidate_quality"]["target_bound_positive_support_basis"]["direct_overlay_independent_verified_support"] is True
    assert scored["role_eligibility"]["independent_step5x_positive_basis"] is True
    assert scored["role_eligibility"]["profile_route_positive_support_bypassed_by_independent_evidence"] is True
    assert scored["role_eligibility"]["profile_route_positive_support_blocked"] is False
    assert scored["role_eligibility"]["positive_support_eligible"] is True
    assert scored["routing_recommendation"] == "positive_role_candidate"
    assert "direct_overlay_independent_positive_support_accepted" in scored["debug_reasons"]["positive_signals"]
    assert "direct_overlay_independent_verified_support" in scored["debug_reasons"]["positive_signals"]
    assert scored["debug_reasons"]["direct_overlay_verified_local_signal_basis"]
    packs = compose_evidence_packs_from_scored_candidates(scored_rows)
    assert len(packs) == 1
    pack = packs[0]
    assert pack["pack_quality"]["positive_support_count"] >= 1
    assert pack["pack_quality"]["route"] in {"standard_drafting", "partial_grounded_packet"}
    selected = pack["slots"]["definition_kernel"] or pack["slots"]["explanatory_gloss"] or pack["slots"]["example_or_procedure"]
    assert selected
    assert selected[0]["support_profile"]["candidate_source"] == SOURCE_DIRECT_OVERLAY_SUPPLEMENT


def test_wrong_branch_direct_overlay_row_remains_blocked() -> None:
    rows, stats = _run_clean_slate_stage(
        name="wrong_branch_blocked",
        supplement_rows=[
            _supplement_row(
                "A one-way partition is not a two-way option partition.",
                target_signals=["two-way option partition"],
                reasons=[
                    "required:two-way option partition",
                    "strong:two-way option partition",
                    "shapes:procedure_or_explanation_like",
                ],
            )
        ],
    )

    assert stats["direct_overlay_supplement"]["candidate_rows_added"] == 1
    rows[0]["step5p_route_evaluation"] = _route_block_eval()
    scored = score_candidate_rows(rows)[0]
    assert scored["sibling_or_competitor_signals"]["contrastive_target_mention"] is True
    assert scored["role_eligibility"]["positive_support_eligible"] is False
    assert scored["routing_recommendation"] != "positive_role_candidate"


def test_profile_negative_constraint_blocks_direct_overlay_candidate() -> None:
    rows, stats = _run_clean_slate_stage(
        name="negative_constraint_block",
        supplement_rows=[
            _supplement_row(
                "A one-way partition is a different surface and must stay blocked for this target.",
                target_signals=["one-way partition"],
                reasons=["required:one-way partition"],
            )
        ],
        profile_rows=[_profile_row(negative_term="one-way partition")],
    )

    assert rows == []
    assert stats["direct_overlay_supplement"]["candidate_rows_added"] == 0
    assert stats["direct_overlay_supplement"]["quarantine_count"] == 1
    assert stats["direct_overlay_supplement"]["rejected_counts"]["negative_constraint"] == 1


def test_no_production_hardcoded_rescue_kcs_or_domain_terms_in_direct_overlay_lane() -> None:
    targets = [
        REPO_ROOT / "src" / "kc_l" / "retrieval_gate" / "evidence_stage_v3_candidate_bank.py",
        REPO_ROOT / "src" / "kc_l" / "retrieval_gate" / "evidence_stage_v3_scored_candidates.py",
        REPO_ROOT / "steps" / "step_05_x_evidence_stage_v3" / "scripts" / "run_step5x_v3_candidate_bank.py",
        REPO_ROOT / "steps" / "step_05_x_evidence_stage_v3" / "resources" / "step5x_v3_candidate_bank.default.yaml",
    ]
    forbidden_snippets = [
        "KC_CLF_DT_005",
        "KC_CLF_DT_011",
        "KC_CLF_DT_012",
        "KC_CLU_EVAL_002",
        "KC_CLU_HIER_002",
        "KC_CLU_KM_002",
        "KC_FSEL_GEN_002",
        "Entropy (Node)",
        "Binary Decision Tree",
        "Splitting Continuous Attributes",
        "SSE (Cluster Quality)",
        "Agglomerative (Bottom-Up) Clustering",
        "SSE Optimization Criterion",
        "Sequential Backward Generation (SBG)",
        "entropy of splitting",
        "squared error",
        "agglomerative",
        "sequential backward",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in targets)
    for snippet in forbidden_snippets:
        assert snippet not in combined


def main() -> None:
    test_direct_overlay_supplement_translates_into_candidate_bank_contract_without_seed_fields()
    test_direct_overlay_seed_bearing_input_is_rejected()
    test_fragment_only_direct_overlay_row_is_rehydration_queued_not_admitted()
    test_prompt_like_direct_overlay_row_is_quarantined()
    test_reference_like_direct_overlay_row_is_quarantined()
    test_duplicate_extractor_variants_are_suppressed()
    test_same_patch_weaker_variant_is_suppressed()
    test_clean_direct_overlay_candidate_bypasses_missing_profile_route_match_and_reaches_real_composer()
    test_wrong_branch_direct_overlay_row_remains_blocked()
    test_profile_negative_constraint_blocks_direct_overlay_candidate()
    test_no_production_hardcoded_rescue_kcs_or_domain_terms_in_direct_overlay_lane()
    print("TEST_STEP5X_DIRECT_OVERLAY_SUPPLEMENT_LANE_OK")


if __name__ == "__main__":
    main()
