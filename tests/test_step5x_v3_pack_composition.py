from __future__ import annotations

import json
import shutil
from pathlib import Path
import sys
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from kc_l.retrieval_gate.evidence_stage_v3_pack_composition import (
    PACK_CONTRACT_VERSION,
    build_evidence_pack_artifacts,
    compose_evidence_packs_from_scored_candidates,
    load_scored_candidate_rows,
)


TEST_ROOT = REPO_ROOT / ".codex_tmp_test_step5x_v3_pack_composition"


def _with_repo_tmp(name: str, fn) -> None:
    tmp_path = TEST_ROOT / name
    if tmp_path.exists():
        shutil.rmtree(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    try:
        fn(tmp_path)
    finally:
        if tmp_path.exists():
            shutil.rmtree(tmp_path, ignore_errors=True)


def _row(
    kc_id: str = "KC_A",
    text: str = "Cross-validation is a widely-used model evaluation method.",
    *,
    candidate_id: str = "cand_a",
    route: str = "positive_role_candidate",
    roles: Dict[str, bool] | None = None,
    risk_flags: List[str] | None = None,
    source_evidence_index: int = 0,
    page_index: int = 1,
) -> Dict[str, Any]:
    role_eligibility = {
        "definition_kernel": False,
        "explanatory_gloss": False,
        "scope_condition": False,
        "formula_notation": False,
        "context_completion_candidate": False,
        "example_or_procedure": False,
        "sibling_contrast": False,
        "positive_support_eligible": False,
        "auxiliary_support_eligible": False,
        "guardrail_support_eligible": False,
    }
    if roles:
        role_eligibility.update(roles)
    return {
        "candidate_id": candidate_id,
        "scored_candidate_id": candidate_id,
        "scored_candidate_version": "step5x_v3_scored_candidates_v1",
        "kc_id": kc_id,
        "canonical_name": "Cross Validation" if kc_id == "KC_A" else "Core Point",
        "aliases": [],
        "topic_path_ids": ["topic::root"],
        "topic_path_labels": ["Root"],
        "parent_topic_id": "topic::root",
        "parent_topic_label": "Root",
        "text": text,
        "candidate_text": text,
        "doc_id": "doc1",
        "block_id": "block1",
        "page_index": page_index,
        "layer": "mineru",
        "bbox": [0, 0, 1, 1],
        "sentence_id": f"doc1::block1::s{source_evidence_index}",
        "sent_idx": source_evidence_index,
        "char_start": source_evidence_index * 10,
        "char_end": source_evidence_index * 10 + len(text),
        "patch_id": "patch1",
        "patch_heading": "Heading",
        "reveal_group_id": "rg1",
        "source_row_index": 0,
        "source_evidence_index": source_evidence_index,
        "source_kc_id": kc_id,
        "source_canonical_name": "Cross Validation",
        "source_manifest": "stage2-set.json",
        "stage1_source_manifest": "stage1-set.json",
        "retrieval_scores": {"rerank_target": 0.9},
        "alignment_score": 9.0,
        "support_profile": {},
        "risk_flags": risk_flags or [],
        "debug_reasons": {},
        "role_scores": {
            "definition_kernel": 7.0,
            "explanatory_gloss": 5.0,
            "scope_condition": 2.0,
            "formula_notation": 1.0,
            "context_completion_candidate": 4.0,
            "example_or_procedure": 2.0,
            "sibling_contrast": 1.0,
        },
        "role_eligibility": role_eligibility,
        "candidate_quality": {"overall_score": 6.0, "target_bound_positive_support": bool(role_eligibility.get("positive_support_eligible"))},
        "lexical_target_binding": {"binding_strength": "usable", "score": 2.8, "is_target_bound": True},
        "definition_framing_score": {},
        "formula_signal": {},
        "fragment_or_caption_signal": {},
        "contamination_signals": {},
        "sibling_or_competitor_signals": {},
        "routing_recommendation": route,
        "provenance": {},
    }


def test_one_pack_is_emitted_per_kc_and_identity_is_preserved():
    rows = [
        _row("KC_A", candidate_id="cand_a", roles={"definition_kernel": True, "positive_support_eligible": True}),
        _row("KC_B", candidate_id="cand_b", roles={"explanatory_gloss": True, "positive_support_eligible": True}),
    ]
    packs = compose_evidence_packs_from_scored_candidates(rows)
    assert [pack["kc_id"] for pack in packs] == ["KC_A", "KC_B"]
    assert all(pack["pack_version"] == PACK_CONTRACT_VERSION for pack in packs)
    assert packs[0]["slots"]["definition_kernel"][0]["stage2_candidate_id"] == "cand_a"
    assert packs[1]["slots"]["explanatory_gloss"][0]["stage2_candidate_id"] == "cand_b"


def test_positive_definition_becomes_standard_drafting_and_ordered_pack_item():
    row = _row(roles={"definition_kernel": True, "positive_support_eligible": True})
    row["support_profile"] = {"support_roles": ["definitional_anchor"]}
    row["definition_framing_score"] = {"subject_alignment": "aligned", "definition_style": "explicit"}
    rows = [row]
    pack = compose_evidence_packs_from_scored_candidates(rows)[0]
    assert pack["pack_quality"]["route"] == "standard_drafting"
    assert pack["pack_quality"]["definition_anchor_present"] is True
    assert [item["role"] for item in pack["ordered_pack_for_drafting"]] == ["definition_kernel"]
    assert pack["ordered_pack_for_drafting"][0]["candidate_id"].startswith("KC_A:step5_4:")
    assert pack["shapeaware_route"] == "standard_definition_packet"
    assert len(pack["drafting_core_evidence"]) == 1
    assert pack["drafting_core_evidence"][0]["shapeaware_support_roles"] == ["definition_anchor"]
    assert pack["auxiliary_evidence"] == []
    assert pack["review_needed_evidence"] == []
    assert pack["rejected_false_positive_evidence"] == []


def test_auxiliary_only_context_does_not_create_standard_or_ordered_pack():
    rows = [
        _row(
            text="neighborhood of a core point.",
            route="auxiliary_only_candidate",
            roles={"context_completion_candidate": True, "auxiliary_support_eligible": True},
        )
    ]
    pack = compose_evidence_packs_from_scored_candidates(rows)[0]
    assert pack["slots"]["context_completion"]
    assert pack["ordered_pack_for_drafting"] == []
    assert pack["pack_quality"]["route"] == "insufficient_support_packet"
    assert "auxiliary_without_positive_anchor" in pack["pack_quality"]["insufficient_reasons"]


def test_sibling_contrast_is_guardrail_only_and_never_ordered():
    rows = [
        _row(
            text="A border point is not a core point, but falls within the neighborhood of a core point.",
            route="guardrail_only_candidate",
            roles={"sibling_contrast": True, "guardrail_support_eligible": True},
        )
    ]
    pack = compose_evidence_packs_from_scored_candidates(rows)[0]
    assert pack["slots"]["sibling_contrast"]
    assert pack["ordered_pack_for_drafting"] == []
    assert pack["pack_quality"]["route"] == "insufficient_support_packet"
    assert all(item["role"] != "sibling_contrast" for item in pack["ordered_pack_for_drafting"])


def test_context_completion_can_support_existing_positive_anchor_in_ordered_pack():
    rows = [
        _row(
            candidate_id="cand_def",
            text="Cross-validation is a widely-used model evaluation method.",
            roles={"definition_kernel": True, "positive_support_eligible": True},
            source_evidence_index=0,
        ),
        _row(
            candidate_id="cand_ctx",
            text="For each run, one fold is used as the test fold.",
            route="auxiliary_only_candidate",
            roles={"context_completion_candidate": True, "auxiliary_support_eligible": True},
            source_evidence_index=1,
        ),
    ]
    pack = compose_evidence_packs_from_scored_candidates(rows)[0]
    ordered_roles = [item["role"] for item in pack["ordered_pack_for_drafting"]]
    assert "definition_kernel" in ordered_roles
    assert "context_completion" in ordered_roles
    assert pack["pack_quality"]["context_completion_used"] is True


def test_no_positive_support_still_emits_represented_insufficient_pack():
    rows = [
        _row(candidate_id="drop1", route="drop_from_positive_roles", roles={}, risk_flags=["no_target_binding"]),
        _row(candidate_id="drop2", route="drop_from_positive_roles", roles={}, risk_flags=["fragmentary"]),
    ]
    pack = compose_evidence_packs_from_scored_candidates(rows)[0]
    assert pack["slots"]["definition_kernel"] == []
    assert pack["ordered_pack_for_drafting"] == []
    assert pack["pack_quality"]["route"] == "insufficient_support_packet"
    assert "weak_coverage" in pack["pack_quality"]["insufficient_reasons"]
    assert len(pack["provenance_sidecar"]["dropped_candidate_ids"]) == 2


def test_build_artifacts_creates_step66_compatible_manifest_without_active_pointer(tmp_path: Path):
    rows = [_row(roles={"definition_kernel": True, "positive_support_eligible": True})]
    out_root = tmp_path / "packs"
    set_root = out_root / "_sets"
    result = build_evidence_pack_artifacts(
        rows,
        run_id="stage3_smoke",
        source_manifest="stage2-set.json",
        scored_candidates_jsonl_path="scored.jsonl",
        config_path="cfg.yaml",
        exact_kc_ids=["KC_A"],
        limit_kcs=1,
        cfg={},
        output_root=out_root,
        set_manifest_root=set_root,
        repo_root=tmp_path,
    )
    set_path = tmp_path / result["set_manifest"]
    set_obj = json.loads(set_path.read_text(encoding="utf-8"))
    assert set_obj["artifacts"]["kc_evidence_packs_jsonl"].endswith("kc_evidence_packs.jsonl")
    assert set_obj["compatibility"]["step6_6_ready"] is True
    assert not list(set_root.glob("ACTIVE_STEP5X_V3*"))


def test_build_artifacts_embeds_gap_requests_on_insufficient_pack(tmp_path: Path):
    rows = [_row(candidate_id="drop1", route="drop_from_positive_roles", roles={}, risk_flags=["context_only_support"])]
    out_root = tmp_path / "packs"
    set_root = out_root / "_sets"
    result = build_evidence_pack_artifacts(
        rows,
        run_id="stage3_gap_sidecar",
        source_manifest="stage2-set.json",
        scored_candidates_jsonl_path="scored.jsonl",
        config_path="cfg.yaml",
        exact_kc_ids=["KC_A"],
        limit_kcs=1,
        cfg={},
        output_root=out_root,
        set_manifest_root=set_root,
        repo_root=tmp_path,
    )
    pack_path = tmp_path / result["kc_evidence_packs_jsonl"]
    gap_path = tmp_path / result["retrieval_gap_requests_jsonl"]
    packs = [json.loads(line) for line in pack_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    gaps = [json.loads(line) for line in gap_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert len(gaps) == 1
    assert packs[0]["ordered_pack_for_drafting"] == []
    assert packs[0]["pack_quality"]["insufficient_reasons"]
    assert packs[0]["near_miss_review_items"]
    assert packs[0]["retrieval_gap_requests"][0]["gap_request_id"] == gaps[0]["gap_request_id"]


def test_loader_supports_stage2_set_manifest_and_exact_kc_filter(tmp_path: Path):
    rows = [
        _row("KC_A", candidate_id="cand_a", roles={"definition_kernel": True, "positive_support_eligible": True}),
        _row("KC_B", candidate_id="cand_b", roles={"explanatory_gloss": True, "positive_support_eligible": True}),
    ]
    rows_path = tmp_path / "scored_candidates.jsonl"
    rows_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    set_path = tmp_path / "stage2_set.json"
    set_path.write_text(
        json.dumps({"artifacts": {"scored_candidates_jsonl": rows_path.as_posix()}}),
        encoding="utf-8",
    )
    loaded, info = load_scored_candidate_rows(
        stage2_set_manifest=set_path.as_posix(),
        scored_candidates_jsonl=None,
        exact_kc_ids=["KC_B"],
        limit_kcs=None,
        repo_root=tmp_path,
    )
    assert [row["kc_id"] for row in loaded] == ["KC_B"]
    assert info["source_manifest"] == set_path.as_posix()


def test_seed_and_stage2_pack_fields_do_not_leak_to_pack_output():
    row = _row(roles={"definition_kernel": True, "positive_support_eligible": True})
    row["seed_definition"] = "must not leak"
    row["seed_keywords"] = ["must", "not", "leak"]
    row["pack_quality"] = {"old": True}
    row["ordered_pack_for_drafting"] = [{"old": True}]
    row["slots"] = {"old": True}
    pack = compose_evidence_packs_from_scored_candidates([row])[0]
    serialized = json.dumps(pack, ensure_ascii=False)
    assert "seed_definition" not in serialized
    assert "seed_keywords" not in serialized
    assert '"old"' not in serialized


def test_near_miss_review_items_preserved_in_insufficient_pack():
    rows = [
        _row(
            candidate_id="near1",
            route="manual_review_candidate",
            roles={},
            risk_flags=["label_mismatch"],
        )
    ]
    rows[0]["retrieval_intent"] = "head_term_plus_definition_frame"
    rows[0]["candidate_origin"] = "head_term_plus_definition_frame"
    rows[0]["target_binding_basis"] = "head_term_text"

    pack = compose_evidence_packs_from_scored_candidates(rows)[0]

    assert pack["ordered_pack_for_drafting"] == []
    assert pack["near_miss_review_items"]
    assert pack["near_miss_review_items"][0]["candidate_id"] == "near1"
    assert pack["retrieval_failure_diagnosis"]["diagnosis_labels"]


def test_ordered_pack_remains_empty_when_only_review_candidates_exist():
    rows = [
        _row(
            candidate_id="review1",
            route="review_only_candidate",
            roles={"review_only_candidate": True},
            risk_flags=["context_only_support"],
        )
    ]

    pack = compose_evidence_packs_from_scored_candidates(rows)[0]

    assert pack["ordered_pack_for_drafting"] == []
    assert pack["pack_quality"]["route"] == "insufficient_support_packet"
    assert pack["missing_positive_support_reason"]


def test_positive_anchor_plus_context_completion_builds_pack_without_threshold_weakening():
    test_context_completion_can_support_existing_positive_anchor_in_ordered_pack()


def test_feedback_payload_present_only_for_severe_zero_anchor_cases():
    rows = [
        _row(candidate_id="zero1", route="drop_from_positive_roles", roles={}, risk_flags=["retrieval_failure"])
    ]

    disabled = compose_evidence_packs_from_scored_candidates(rows, cfg={})[0]
    enabled = compose_evidence_packs_from_scored_candidates(
        rows,
        cfg={"feedback": {"enabled": True, "max_feedback_rounds": 1}},
    )[0]

    assert disabled["feedback_eligible"] is False
    assert disabled["feedback_payload"] == {}
    assert enabled["feedback_eligible"] is True
    assert enabled["feedback_payload"]["max_feedback_rounds"] == 1


def test_zero_candidate_pack_keeps_shapeaware_shadow_fields_empty(tmp_path: Path):
    result = build_evidence_pack_artifacts(
        [],
        run_id="zero_candidate_shapeaware",
        source_manifest="stage2-set.json",
        scored_candidates_jsonl_path="scored.jsonl",
        config_path="cfg.yaml",
        exact_kc_ids=["KC_ZERO"],
        limit_kcs=1,
        cfg={},
        output_root=tmp_path / "packs",
        set_manifest_root=tmp_path / "packs" / "_sets",
        repo_root=tmp_path,
    )
    pack_path = tmp_path / result["kc_evidence_packs_jsonl"]
    pack = json.loads(pack_path.read_text(encoding="utf-8").splitlines()[0])
    assert pack["shapeaware_route"] == "insufficient_source_support_packet"
    assert pack["expected_evidence_needs"] == []
    assert pack["drafting_core_evidence"] == []
    assert pack["review_needed_evidence"] == []


def main():
    test_one_pack_is_emitted_per_kc_and_identity_is_preserved()
    test_positive_definition_becomes_standard_drafting_and_ordered_pack_item()
    test_auxiliary_only_context_does_not_create_standard_or_ordered_pack()
    test_sibling_contrast_is_guardrail_only_and_never_ordered()
    test_context_completion_can_support_existing_positive_anchor_in_ordered_pack()
    test_no_positive_support_still_emits_represented_insufficient_pack()
    _with_repo_tmp("artifact_manifest", test_build_artifacts_creates_step66_compatible_manifest_without_active_pointer)
    _with_repo_tmp("gap_sidecar", test_build_artifacts_embeds_gap_requests_on_insufficient_pack)
    _with_repo_tmp("loader_manifest", test_loader_supports_stage2_set_manifest_and_exact_kc_filter)
    test_seed_and_stage2_pack_fields_do_not_leak_to_pack_output()
    test_near_miss_review_items_preserved_in_insufficient_pack()
    test_ordered_pack_remains_empty_when_only_review_candidates_exist()
    test_positive_anchor_plus_context_completion_builds_pack_without_threshold_weakening()
    test_feedback_payload_present_only_for_severe_zero_anchor_cases()
    _with_repo_tmp("zero_candidate_shapeaware", test_zero_candidate_pack_keeps_shapeaware_shadow_fields_empty)
    print("TEST_STEP5X_V3_PACK_COMPOSITION_OK")


if __name__ == "__main__":
    main()
