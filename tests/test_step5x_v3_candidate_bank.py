from __future__ import annotations

import json
import shutil
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_SRC = REPO_ROOT / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from kc_l.retrieval_gate.evidence_stage_v3_candidate_bank import (
    CANDIDATE_BANK_CONTRACT_VERSION,
    REQUIRED_ROW_KEYS,
    SOURCE_SURFACE_FALLBACK,
    build_kc_context_lookup,
    flatten_step5_3_nested_evidence_rows,
    run_candidate_bank_stage,
)

TEST_ROOT = REPO_ROOT / ".codex_tmp_test_step5x_v3_candidate_bank"


def _kc_row(
    kc_id: str,
    canonical_name: str,
    *evidence: dict[str, object],
    aliases: list[str] | None = None,
    seed_definition: str | None = None,
    seed_keywords: list[str] | None = None,
) -> dict[str, object]:
    row: dict[str, object] = {
        "kc_id": kc_id,
        "canonical_name": canonical_name,
        "aliases": list(aliases or []),
        "evidence": list(evidence),
    }
    if seed_definition is not None:
        row["seed_definition"] = seed_definition
    if seed_keywords is not None:
        row["seed_keywords"] = list(seed_keywords)
    return row


def _candidate(
    text: str,
    *,
    doc_id: str = "DOC_1",
    page_index: int | None = 1,
    block_id: str = "DOC_1:block:001",
    sentence_id: str = "DOC_1:block:001::s000",
    sent_idx: int | None = 0,
    patch_id: str = "patch-1",
    patch_heading: str = "Heading",
    reveal_group_id: str = "group-1",
    layer: str = "pymupdf",
    bbox: list[float] | None = None,
    char_start: int | None = 0,
    char_end: int | None = None,
    source_block_text: str | None = None,
    source_kc_id: str | None = None,
    source_canonical_name: str | None = None,
) -> dict[str, object]:
    return {
        "snippet": text,
        "source_block_text": source_block_text or text,
        "doc_id": doc_id,
        "page_index": page_index,
        "block_id": block_id,
        "sentence_id": sentence_id,
        "sent_idx": sent_idx,
        "patch_id": patch_id,
        "patch_heading": patch_heading,
        "reveal_group_id": reveal_group_id,
        "layer": layer,
        "bbox": list(bbox or [1.0, 2.0, 3.0, 4.0]),
        "char_start": char_start,
        "char_end": char_end if char_end is not None else len(text),
        "alignment_score": 7.5,
        "alignment_breakdown": {"exact_name_phrase": True},
        "support_profile": {"anchor_quality": "usable"},
        "retrieval_scores": {"combined": 0.8},
        "source_kc_id": source_kc_id,
        "source_canonical_name": source_canonical_name,
    }


def _kc_context_lookup() -> dict[str, dict[str, object]]:
    registry_rows = [
        {
            "kc_id": "KC_A",
            "canonical_name": "Concept A",
            "aliases": ["Alias A"],
            "kc_path": ["Topic Root", "Topic Mid", "Concept A"],
            "seed_definition": "must not survive",
        },
        {
            "kc_id": "KC_B",
            "canonical_name": "Concept B",
            "aliases": [],
            "kc_path": ["Topic Root", "Topic Other", "Concept B"],
        },
    ]
    return build_kc_context_lookup(registry_rows)


def _registry_fixture_rows() -> list[dict[str, object]]:
    return [
        {
            "kc_id": "KC_A",
            "canonical_name": "Learning Phase",
            "aliases": [],
            "kc_path": ["Classification", "Classification Underpinnings", "Learning Phase"],
        },
        {
            "kc_id": "KC_B",
            "canonical_name": "Entropy",
            "aliases": [],
            "kc_path": ["Classification", "Decision Trees", "Entropy"],
        },
        {
            "kc_id": "KC_C",
            "canonical_name": "Prior Probability",
            "aliases": [],
            "kc_path": ["Classification", "Naive Bayes", "Prior Probability"],
        },
    ]


def _clustering_registry_fixture_rows() -> list[dict[str, object]]:
    return [
        {
            "kc_id": "KC_A",
            "canonical_name": "Cluster Definition",
            "aliases": [],
            "kc_path": ["Clustering", "Cluster Foundations", "Cluster Definition"],
        },
        {
            "kc_id": "KC_B",
            "canonical_name": "Cluster Center",
            "aliases": [],
            "kc_path": ["Clustering", "Cluster Foundations", "Cluster Center"],
        },
        {
            "kc_id": "KC_C",
            "canonical_name": "Silhouette Coefficient",
            "aliases": [],
            "kc_path": ["Clustering", "Cluster Evaluation", "Silhouette Coefficient"],
        },
    ]


def _sentence_surface_row(
    text: str,
    *,
    patch_heading: str,
    sentence_id: str = "DOC_1::block_1::s000",
    block_id: str = "DOC_1:block_1",
    doc_id: str = "DOC_1",
) -> dict[str, object]:
    return {
        "sentence_text": text,
        "source_block_text": text,
        "doc_id": doc_id,
        "page_index": 1,
        "block_id": block_id,
        "sentence_id": sentence_id,
        "sent_idx": 0,
        "patch_id": "patch-1",
        "patch_heading": patch_heading,
        "reveal_group_id": "group-1",
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
        "is_definition_like": True,
        "is_procedure_like": False,
        "is_example_like": False,
    }


def _write_registry_fixture(root: Path, rows: list[dict[str, object]] | None = None) -> Path:
    path = root / "data" / "work" / "cache" / "current_step_artifacts" / "step1_seedless_hierarchy_registry.current.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in (rows or _registry_fixture_rows())) + "\n", encoding="utf-8")
    return path


def _write_retired_registry_alias(root: Path, rows: list[dict[str, object]]) -> Path:
    path = root / "data" / "work" / "cache" / "current_step_artifacts" / "step1_kc_registry.current.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def _write_sentence_corpus(root: Path, rows: list[dict[str, object]]) -> Path:
    path = root / "sentence_corpus.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def _rows_and_stats(
    rows: list[dict[str, object]],
    *,
    exact_kc_ids: list[str] | None = None,
    limit_kcs: int | None = None,
) -> tuple[list[dict[str, object]], dict[str, object], dict[str, object]]:
    return flatten_step5_3_nested_evidence_rows(
        rows,
        run_id="demo_run",
        source_manifest="demo_manifest.json",
        source_jsonl="demo_candidates.jsonl",
        exact_kc_ids=exact_kc_ids,
        limit_kcs=limit_kcs,
        kc_context_lookup=_kc_context_lookup(),
    )


def test_flattening_emits_one_candidate_row_per_nested_evidence_item():
    source_rows = [
        _kc_row(
            "KC_A",
            "Concept A",
            _candidate("Sentence one.", sentence_id="S1", sent_idx=0),
            _candidate("Sentence two.", sentence_id="S2", sent_idx=1),
            _candidate("Sentence three.", sentence_id="S3", sent_idx=2),
        )
    ]
    output_rows, stats, _ = _rows_and_stats(source_rows)
    assert len(output_rows) == 3
    assert stats["total_candidate_rows_emitted"] == 3


def test_stable_ids_repeat_on_identical_input():
    source_rows = [
        _kc_row(
            "KC_A",
            "Concept A",
            _candidate("Stable sentence.", sentence_id="S1", sent_idx=0),
        )
    ]
    rows_one, _, _ = _rows_and_stats(source_rows)
    rows_two, _, _ = _rows_and_stats(source_rows)
    assert [row["candidate_id"] for row in rows_one] == [row["candidate_id"] for row in rows_two]


def test_provenance_fields_are_preserved_when_present():
    source_rows = [
        _kc_row(
            "KC_A",
            "Concept A",
            _candidate(
                "Preserve provenance.",
                doc_id="DOC_X",
                page_index=9,
                block_id="DOC_X:block:009",
                sentence_id="DOC_X:block:009::s003",
                sent_idx=3,
                patch_id="patch-x",
                patch_heading="Patch Heading",
                reveal_group_id="rg-9",
                bbox=[9.0, 8.0, 7.0, 6.0],
                char_start=11,
                char_end=29,
            ),
        )
    ]
    output_rows, _, _ = _rows_and_stats(source_rows)
    row = output_rows[0]
    assert row["doc_id"] == "DOC_X"
    assert row["page_index"] == 9
    assert row["block_id"] == "DOC_X:block:009"
    assert row["sentence_id"] == "DOC_X:block:009::s003"
    assert row["sent_idx"] == 3
    assert row["patch_id"] == "patch-x"
    assert row["patch_heading"] == "Patch Heading"
    assert row["reveal_group_id"] == "rg-9"
    assert row["bbox"] == [9.0, 8.0, 7.0, 6.0]
    assert row["char_start"] == 11
    assert row["char_end"] == 29


def test_seed_fields_are_detected_but_not_propagated():
    source_rows = [
        _kc_row(
            "KC_A",
            "Concept A",
            _candidate("Seed fields must not leak.", sentence_id="S1", sent_idx=0),
            seed_definition="forbidden seed text",
            seed_keywords=["forbidden", "seed"],
        )
    ]
    output_rows, stats, _ = _rows_and_stats(source_rows)
    row_json = json.dumps(output_rows[0], sort_keys=True)
    assert "seed_definition" not in row_json
    assert "seed_keywords" not in row_json
    assert stats["seed_fields_detected_in_input"] >= 2
    assert stats["seed_fields_propagated_to_output"] == 0


def test_empty_evidence_emits_zero_candidate_rows_and_counts_missing_kc():
    source_rows = [_kc_row("KC_A", "Concept A")]
    output_rows, stats, _ = _rows_and_stats(source_rows)
    assert output_rows == []
    assert stats["kcs_without_candidates"] == 1
    assert stats["candidate_count_by_kc"]["KC_A"] == 0


def test_clean_slate_seed_bearing_registry_fails_by_default() -> None:
    root = TEST_ROOT
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    try:
        registry_path = root / "registry_seeded.jsonl"
        registry_path.write_text(
            json.dumps(
                {
                    "kc_id": "KC_A",
                    "canonical_name": "Neutral Concept",
                    "aliases": [],
                    "topic_path_labels": ["Course", "Unit"],
                    "seed_definition": "forbidden",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        sentence_corpus = _write_sentence_corpus(
            root,
            [_sentence_surface_row("Neutral Concept is defined by a source-observed sentence.", patch_heading="Unit")],
        )
        try:
            run_candidate_bank_stage(
                run_id="seed_fail_default",
                step5_3_set_manifest_spec=None,
                step5_3_candidates_jsonl_spec=None,
                registry_jsonl_spec=str(registry_path),
                source_overlay_jsonl_spec=str(sentence_corpus),
                config_path="tests://seed_fail_default",
                exact_kc_ids=["KC_A"],
                limit_kcs=1,
                output_root=root / "out",
                set_manifest_root=root / "out" / "_sets",
                allow_reference_artifact_inputs=True,
                fail_if_no_candidate_source=True,
                exclude_seed_fields=True,
                preserve_raw_support_profile=True,
                preserve_raw_alignment_breakdown=True,
                repo_root=root,
            )
            raise AssertionError("Expected seed-bearing registry input to fail by default.")
        except RuntimeError as exc:
            assert "forbidden seed fields" in str(exc)
    finally:
        if root.exists():
            shutil.rmtree(root)


def test_diagnostic_escape_hatch_allows_seed_bearing_clean_slate_input() -> None:
    root = TEST_ROOT
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    try:
        registry_path = root / "registry_seeded.jsonl"
        registry_path.write_text(
            json.dumps(
                {
                    "kc_id": "KC_A",
                    "canonical_name": "Neutral Concept",
                    "aliases": [],
                    "topic_path_labels": ["Course", "Unit"],
                    "seed_definition": "forbidden",
                    "seed_keywords": ["forbidden"],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        sentence_corpus = _write_sentence_corpus(
            root,
            [_sentence_surface_row("Neutral Concept is defined by a source-observed sentence.", patch_heading="Unit")],
        )
        result = run_candidate_bank_stage(
            run_id="seed_diagnostic_ok",
            step5_3_set_manifest_spec=None,
            step5_3_candidates_jsonl_spec=None,
            registry_jsonl_spec=str(registry_path),
            source_overlay_jsonl_spec=str(sentence_corpus),
            config_path="tests://seed_diagnostic_ok",
            exact_kc_ids=["KC_A"],
            limit_kcs=1,
            output_root=root / "out",
            set_manifest_root=root / "out" / "_sets",
            allow_reference_artifact_inputs=True,
            fail_if_no_candidate_source=True,
            exclude_seed_fields=True,
            preserve_raw_support_profile=True,
            preserve_raw_alignment_breakdown=True,
            allow_seed_bearing_input_for_diagnostic=True,
            repo_root=root,
        )
        stats = json.loads((root / "out" / "seed_diagnostic_ok" / "candidate_bank_stats.json").read_text(encoding="utf-8"))
        rows = [json.loads(line) for line in (root / "out" / "seed_diagnostic_ok" / "candidate_bank.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        assert result["total_candidate_rows_emitted"] == 1
        assert stats["allow_seed_bearing_input_for_diagnostic"] is True
        assert stats["seed_field_detection"]["registry_input"]["total"] == 2
        assert "seed_definition" not in json.dumps(rows[0], sort_keys=True)
        assert "seed_keywords" not in json.dumps(rows[0], sort_keys=True)
    finally:
        if root.exists():
            shutil.rmtree(root)


def test_legacy_mode_uses_seedless_alias_and_not_retired_registry_alias() -> None:
    root = TEST_ROOT
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    try:
        _write_registry_fixture(
            root,
            [
                {
                    "kc_id": "KC_A",
                    "canonical_name": "Neutral Concept",
                    "aliases": [],
                    "topic_path_labels": ["Course", "Unit"],
                }
            ],
        )
        _write_retired_registry_alias(
            root,
            [
                {
                    "kc_id": "KC_A",
                    "canonical_name": "Retired Alias Concept",
                    "seed_definition": "forbidden",
                }
            ],
        )
        step5_jsonl = root / "step5_3_candidates.jsonl"
        step5_manifest = root / "step5_3_set.json"
        step5_jsonl.write_text(json.dumps({"kc_id": "KC_A", "canonical_name": "Neutral Concept", "evidence": []}) + "\n", encoding="utf-8")
        step5_manifest.write_text(
            json.dumps({"artifacts": {"kc_evidence_candidates_recalibrated_jsonl": str(step5_jsonl)}}),
            encoding="utf-8",
        )
        result = run_candidate_bank_stage(
            run_id="seedless_alias_only",
            step5_3_set_manifest_spec=str(step5_manifest),
            step5_3_candidates_jsonl_spec=None,
            config_path="tests://seedless_alias_only",
            exact_kc_ids=["KC_A"],
            limit_kcs=1,
            output_root=root / "out",
            set_manifest_root=root / "out" / "_sets",
            allow_reference_artifact_inputs=True,
            fail_if_no_candidate_source=True,
            exclude_seed_fields=True,
            preserve_raw_support_profile=True,
            preserve_raw_alignment_breakdown=True,
            repo_root=root,
        )
        stats = json.loads((root / "out" / "seedless_alias_only" / "candidate_bank_stats.json").read_text(encoding="utf-8"))
        assert result["run_id"] == "seedless_alias_only"
        assert stats["registry_jsonl"].endswith("step1_seedless_hierarchy_registry.current.jsonl")
        assert stats["seed_field_detection"]["registry_input"]["total"] == 0
    finally:
        if root.exists():
            shutil.rmtree(root)


def test_source_row_and_evidence_index_are_preserved():
    source_rows = [
        _kc_row("KC_A", "Concept A", _candidate("A0", sentence_id="S1"), _candidate("A1", sentence_id="S2")),
        _kc_row("KC_B", "Concept B", _candidate("B0", sentence_id="S3")),
    ]
    output_rows, _, _ = _rows_and_stats(source_rows)
    assert output_rows[0]["source_row_index"] == 0
    assert output_rows[0]["source_evidence_index"] == 0
    assert output_rows[1]["source_row_index"] == 0
    assert output_rows[1]["source_evidence_index"] == 1
    assert output_rows[2]["source_row_index"] == 1
    assert output_rows[2]["source_evidence_index"] == 0


def test_exact_kc_ids_filtering_only_emits_requested_kcs():
    source_rows = [
        _kc_row("KC_A", "Concept A", _candidate("A0", sentence_id="S1")),
        _kc_row("KC_B", "Concept B", _candidate("B0", sentence_id="S2")),
    ]
    output_rows, stats, _ = _rows_and_stats(source_rows, exact_kc_ids=["KC_B"])
    assert [row["kc_id"] for row in output_rows] == ["KC_B"]
    assert stats["total_kc_rows_seen"] == 1


def test_output_does_not_include_semantic_scoring_or_pack_fields():
    source_rows = [_kc_row("KC_A", "Concept A", _candidate("No pack fields.", sentence_id="S1"))]
    output_rows, _, _ = _rows_and_stats(source_rows)
    row = output_rows[0]
    forbidden = {"role_scores", "eligibility", "pack_quality", "ordered_pack_for_drafting", "slots"}
    assert forbidden.isdisjoint(row.keys())


def test_every_emitted_row_has_required_contract_keys():
    source_rows = [_kc_row("KC_A", "Concept A", _candidate("Contract row.", sentence_id="S1"))]
    output_rows, _, schema = _rows_and_stats(source_rows)
    row = output_rows[0]
    for key in REQUIRED_ROW_KEYS:
        assert key in row
    assert schema["candidate_bank_version"] == CANDIDATE_BANK_CONTRACT_VERSION


def test_runner_does_not_create_active_pointer_files():
    root = TEST_ROOT
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    try:
        step5_jsonl = root / "step5_3_candidates.jsonl"
        step5_manifest = root / "step5_3_set.json"
        output_root = root / "out"
        sets_root = output_root / "_sets"
        step5_rows = [
            _kc_row("KC_A", "Concept A", _candidate("Runner smoke.", sentence_id="S1")),
        ]
        step5_jsonl.write_text("\n".join(json.dumps(row) for row in step5_rows) + "\n", encoding="utf-8")
        step5_manifest.write_text(
            json.dumps(
                {
                    "artifacts": {
                        "kc_evidence_candidates_recalibrated_jsonl": str(step5_jsonl),
                    }
                }
            ),
            encoding="utf-8",
        )
        result = run_candidate_bank_stage(
            run_id="runner_smoke",
            step5_3_set_manifest_spec=str(step5_manifest),
            step5_3_candidates_jsonl_spec=None,
            config_path="tests://runner_smoke",
            exact_kc_ids=None,
            limit_kcs=None,
            output_root=output_root,
            set_manifest_root=sets_root,
            allow_reference_artifact_inputs=True,
            fail_if_no_candidate_source=True,
            exclude_seed_fields=True,
            preserve_raw_support_profile=True,
            preserve_raw_alignment_breakdown=True,
            repo_root=root,
        )
        assert result["run_id"] == "runner_smoke"
        assert not any(path.name.startswith("ACTIVE_STEP5X_V3") for path in sets_root.iterdir())
    finally:
        if root.exists():
            shutil.rmtree(root)


def test_fallback_disabled_preserves_existing_behavior() -> None:
    root = TEST_ROOT
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    try:
        _write_registry_fixture(root)
        step5_jsonl = root / "step5_3_candidates.jsonl"
        step5_manifest = root / "step5_3_set.json"
        output_root = root / "out"
        sets_root = output_root / "_sets"
        sentence_corpus = _write_sentence_corpus(
            root,
            [
                _sentence_surface_row(
                    "The learning phase is the stage where the classifier is built from training data.",
                    patch_heading="Classification Underpinnings",
                )
            ],
        )
        step5_rows = [_kc_row("KC_A", "Learning Phase")]
        step5_jsonl.write_text("\n".join(json.dumps(row) for row in step5_rows) + "\n", encoding="utf-8")
        step5_manifest.write_text(
            json.dumps(
                {
                    "artifacts": {
                        "kc_evidence_candidates_recalibrated_jsonl": str(step5_jsonl),
                    },
                    "upstream": {
                        "step4_5_sentence_corpus_jsonl": str(sentence_corpus),
                    },
                }
            ),
            encoding="utf-8",
        )
        result = run_candidate_bank_stage(
            run_id="fallback_disabled",
            step5_3_set_manifest_spec=str(step5_manifest),
            step5_3_candidates_jsonl_spec=None,
            config_path="tests://fallback_disabled",
            exact_kc_ids=["KC_A"],
            limit_kcs=1,
            output_root=output_root,
            set_manifest_root=sets_root,
            allow_reference_artifact_inputs=True,
            fail_if_no_candidate_source=True,
            exclude_seed_fields=True,
            preserve_raw_support_profile=True,
            preserve_raw_alignment_breakdown=True,
            source_surface_fallback_cfg={"enabled": False},
            repo_root=root,
        )
        candidate_bank_path = output_root / "fallback_disabled" / "candidate_bank.jsonl"
        stats_path = output_root / "fallback_disabled" / "candidate_bank_stats.json"
        rows = [json.loads(line) for line in candidate_bank_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        stats = json.loads(stats_path.read_text(encoding="utf-8"))
        assert result["total_candidate_rows_emitted"] == 0
        assert rows == []
        assert stats["kcs_without_candidates"] == 1
        assert stats["source_surface_fallback"]["enabled"] is False
    finally:
        if root.exists():
            shutil.rmtree(root)


def test_fallback_enabled_adds_marked_candidates_and_no_active_pointer_update() -> None:
    root = TEST_ROOT
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    try:
        _write_registry_fixture(root, _clustering_registry_fixture_rows())
        step5_jsonl = root / "step5_3_candidates.jsonl"
        step5_manifest = root / "step5_3_set.json"
        output_root = root / "out"
        sets_root = output_root / "_sets"
        sentence_corpus = _write_sentence_corpus(
            root,
            [
                _sentence_surface_row(
                    "A cluster is a collection of data objects treated as a single group.",
                    patch_heading="Cluster Foundations",
                )
            ],
        )
        step5_rows = [_kc_row("KC_A", "Cluster Definition")]
        step5_jsonl.write_text("\n".join(json.dumps(row) for row in step5_rows) + "\n", encoding="utf-8")
        step5_manifest.write_text(
            json.dumps(
                {
                    "artifacts": {
                        "kc_evidence_candidates_recalibrated_jsonl": str(step5_jsonl),
                    },
                    "upstream": {
                        "step4_5_sentence_corpus_jsonl": str(sentence_corpus),
                    },
                }
            ),
            encoding="utf-8",
        )
        result = run_candidate_bank_stage(
            run_id="fallback_enabled",
            step5_3_set_manifest_spec=str(step5_manifest),
            step5_3_candidates_jsonl_spec=None,
            config_path="tests://fallback_enabled",
            exact_kc_ids=["KC_A"],
            limit_kcs=1,
            output_root=output_root,
            set_manifest_root=sets_root,
            allow_reference_artifact_inputs=True,
            fail_if_no_candidate_source=True,
            exclude_seed_fields=True,
            preserve_raw_support_profile=True,
            preserve_raw_alignment_breakdown=True,
            source_surface_fallback_cfg={"enabled": True, "dynamic_broad_token_min_doc_frequency": 2},
            repo_root=root,
        )
        candidate_bank_path = output_root / "fallback_enabled" / "candidate_bank.jsonl"
        stats_path = output_root / "fallback_enabled" / "candidate_bank_stats.json"
        rows = [json.loads(line) for line in candidate_bank_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        stats = json.loads(stats_path.read_text(encoding="utf-8"))
        assert result["total_candidate_rows_emitted"] == 1
        assert len(rows) == 1
        row = rows[0]
        for key in REQUIRED_ROW_KEYS:
            assert key in row
        assert row["source_surface"] == SOURCE_SURFACE_FALLBACK
        assert row["candidate_source"] == SOURCE_SURFACE_FALLBACK
        assert row["fallback_tier"] == "definition_head"
        assert row["surface_match_type"].startswith("head_")
        assert row["matched_target_tokens"] == ["cluster"]
        assert row["hierarchy_compatibility_signal"] == "heading_branch_overlap"
        assert row["fallback_reason"].startswith("definition_head:")
        assert row["support_profile"]["candidate_source"] == SOURCE_SURFACE_FALLBACK
        assert row["support_profile"]["fallback_tier"] == "definition_head"
        assert row["query_plan_id"]
        assert row["retrieval_intent"] == "head_term_plus_definition_frame"
        assert row["candidate_origin"] == "head_term_plus_definition_frame"
        assert row["target_binding_basis"]
        assert "heading_branch_overlap" in row["target_binding_basis"]
        assert row["evidence_shape_match"] == "definition_or_gloss"
        assert row["authority_contract"] == "step5x_must_verify_against_source_rows"
        assert row["provenance"]["candidate_source"] == SOURCE_SURFACE_FALLBACK
        assert row["provenance"]["fallback_tier"] == "definition_head"
        assert row["provenance"]["query_plan_id"] == row["query_plan_id"]
        row_json = json.dumps(row, sort_keys=True)
        assert "seed_definition" not in row_json
        assert "seed_keywords" not in row_json
        assert stats["source_surface_breakdown"][SOURCE_SURFACE_FALLBACK] == 1
        assert stats["source_surface_fallback"]["candidate_rows_added"] == 1
        assert stats["source_surface_fallback"]["fallback_tier_counter"]["definition_head"] == 1
        assert stats["retrieval_policy"]["policy_plan_count"] == 1
        assert stats["retrieval_policy"]["authority_contract"] == "step5x_must_verify_against_source_rows"
        assert stats["kcs_with_candidates"] == 1
        assert not any(path.name.startswith("ACTIVE_STEP5X_V3") for path in sets_root.iterdir())
    finally:
        if root.exists():
            shutil.rmtree(root)


def _run_direct() -> None:
    module = sys.modules[__name__]
    for name in sorted(dir(module)):
        if not name.startswith("test_"):
            continue
        value = getattr(module, name)
        if callable(value):
            value()
    print("TEST_STEP5X_V3_CANDIDATE_BANK_OK")


if __name__ == "__main__":
    _run_direct()
