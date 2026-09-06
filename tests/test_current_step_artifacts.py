from pathlib import Path

from kc_l.runtime.current_step_artifacts import (
    build_current_step_artifact_status,
    current_step_artifact_alias_paths,
    current_step_artifact_specs,
    get_active_seedless_kc_registry_pointer_path,
    refresh_current_step_artifacts,
    resolve_seedless_kc_registry_path,
)


def test_current_step_artifact_status_reports_missing_when_no_sources_exist(tmp_path):
    status = build_current_step_artifact_status(tmp_path)
    assert status["ok"] is False
    assert len(status["errors"]) == len(current_step_artifact_specs())
    assert status["artifacts"]["step1_kc_registry"]["source_path"] is None
    assert status["artifacts"]["step5_4_set_manifest"]["source_path"] is None
    assert status["artifacts"]["step6_7_set_manifest"]["source_path"] is None


def _write_non_seedless_current_artifact_sources(tmp_path):
    step1_5 = tmp_path / "data/processed/hierarchy_overlay/2026-04-05_101515_hierarchy_overlay/overlay_manifest.json"
    step1_5.parent.mkdir(parents=True, exist_ok=True)
    step1_5.write_text('{"artifacts": {}}\n', encoding="utf-8")

    step5_4 = tmp_path / "data/processed/kc_evidence_packs/_sets/2026-04-05_110000_step5_4_kc_evidence_packs_set.json"
    step5_4.parent.mkdir(parents=True, exist_ok=True)
    step5_4.write_text('{"set_id": "step5_4_latest"}\n', encoding="utf-8")

    step6_6 = tmp_path / "data/processed/kc_drafting_input_overlay/_sets/2026-04-05_111111_step6_6_kc_drafting_input_overlay_set.json"
    step6_6.parent.mkdir(parents=True, exist_ok=True)
    step6_6.write_text('{"set_id": "step6_6_latest"}\n', encoding="utf-8")

    step6_7 = tmp_path / "data/processed/kc_drafts/_sets/2026-04-05_121212_step6_7_kc_drafts_set.json"
    step6_7.parent.mkdir(parents=True, exist_ok=True)
    step6_7.write_text('{"set_id": "step6_7_latest"}\n', encoding="utf-8")

    step6_7b = tmp_path / "data/processed/kc_seed_floor_triage_and_rescue/_sets/2026-04-05_122222_step6_7b_seed_floor_triage_and_rescue_set.json"
    step6_7b.parent.mkdir(parents=True, exist_ok=True)
    step6_7b.write_text('{"set_id": "step6_7b_latest"}\n', encoding="utf-8")

    step6_75 = tmp_path / "data/processed/kc_draft_canonicalization/_sets/2026-04-05_123333_step6_75_kc_draft_canonicalization_set.json"
    step6_75.parent.mkdir(parents=True, exist_ok=True)
    step6_75.write_text('{"set_id": "step6_75_latest"}\n', encoding="utf-8")


def test_refresh_current_step_artifacts_materializes_aliases(tmp_path):
    step1 = tmp_path / "data/processed/hierarchy_seedless_registry/2026-04-05_101010/kc_registry_seedless.jsonl"
    step1.parent.mkdir(parents=True, exist_ok=True)
    step1.write_text('{"kc_id": "KC_001"}\n', encoding="utf-8")

    _write_non_seedless_current_artifact_sources(tmp_path)

    result = refresh_current_step_artifacts(tmp_path, persist=True)
    alias_paths = current_step_artifact_alias_paths(tmp_path)
    pointer_path = get_active_seedless_kc_registry_pointer_path(tmp_path)

    assert result["ok"] is True
    assert alias_paths["step1_kc_registry"].read_text(encoding="utf-8") == step1.read_text(encoding="utf-8")
    assert pointer_path.read_text(encoding="utf-8").strip() == "data/work/cache/current_step_artifacts/step1_seedless_hierarchy_registry.current.jsonl"
    assert (tmp_path / "data/work/cache/current_step_artifacts/current_step_artifacts.status.json").exists()


def test_resolve_seedless_kc_registry_path_prefers_pointer_then_alias(tmp_path):
    alias_path = current_step_artifact_alias_paths(tmp_path)["step1_kc_registry"]
    alias_path.parent.mkdir(parents=True, exist_ok=True)
    alias_path.write_text('{"kc_id": "KC_ALIAS"}\n', encoding="utf-8")

    pointer_target = tmp_path / "data/processed/hierarchy_seedless_registry/run_01/kc_registry_seedless.jsonl"
    pointer_target.parent.mkdir(parents=True, exist_ok=True)
    pointer_target.write_text('{"kc_id": "KC_POINTER"}\n', encoding="utf-8")
    pointer_path = get_active_seedless_kc_registry_pointer_path(tmp_path)
    pointer_path.write_text("data/processed/hierarchy_seedless_registry/run_01/kc_registry_seedless.jsonl\n", encoding="utf-8")

    assert resolve_seedless_kc_registry_path(repo_root=tmp_path) == pointer_target.resolve()


def test_refresh_preserves_existing_clean_seedless_alias_when_source_glob_is_missing(tmp_path):
    _write_non_seedless_current_artifact_sources(tmp_path)
    alias_path = current_step_artifact_alias_paths(tmp_path)["step1_kc_registry"]
    alias_path.parent.mkdir(parents=True, exist_ok=True)
    alias_text = (
        '{"knowledge_unit_type": "topic", "knowledge_unit_id": "topic::root"}\n'
        '{"kc_id": "KC_001", "knowledge_unit_type": "kc", "canonical_name": "Neutral Concept"}\n'
    )
    alias_path.write_text(alias_text, encoding="utf-8")
    pointer_path = get_active_seedless_kc_registry_pointer_path(tmp_path)

    result = refresh_current_step_artifacts(tmp_path, persist=True)
    artifact = result["artifacts"]["step1_kc_registry"]

    assert result["ok"] is True
    assert alias_path.read_text(encoding="utf-8") == alias_text
    assert pointer_path.read_text(encoding="utf-8").strip() == "data/work/cache/current_step_artifacts/step1_seedless_hierarchy_registry.current.jsonl"
    assert artifact["ok"] is True
    assert artifact["alias_exists"] is True
    assert artifact["alias_written"] is False
    assert artifact["preserved_existing_clean_alias"] is True
    assert artifact["resolution_strategy"] == "preserved_existing_clean_alias"
    assert artifact["source_path"] == "data/work/cache/current_step_artifacts/step1_seedless_hierarchy_registry.current.jsonl"
    assert artifact["existing_clean_alias_validation"]["ok"] is True
    assert artifact["existing_clean_alias_validation"]["kc_like_row_count"] == 1


def test_refresh_does_not_preserve_seed_bearing_existing_seedless_alias(tmp_path):
    _write_non_seedless_current_artifact_sources(tmp_path)
    alias_path = current_step_artifact_alias_paths(tmp_path)["step1_kc_registry"]
    alias_path.parent.mkdir(parents=True, exist_ok=True)
    alias_path.write_text(
        '{"kc_id": "KC_001", "knowledge_unit_type": "kc", "seed_definition": "forbidden"}\n',
        encoding="utf-8",
    )
    pointer_path = get_active_seedless_kc_registry_pointer_path(tmp_path)
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    pointer_path.write_text("data/work/cache/current_step_artifacts/step1_seedless_hierarchy_registry.current.jsonl\n", encoding="utf-8")

    result = refresh_current_step_artifacts(tmp_path, persist=True)
    artifact = result["artifacts"]["step1_kc_registry"]

    assert result["ok"] is False
    assert not alias_path.exists()
    assert not pointer_path.exists()
    assert artifact["ok"] is False
    assert artifact["alias_exists"] is False
    assert artifact["stale_alias_removed"] is True
    assert artifact["preserved_existing_clean_alias"] is False
    assert artifact["existing_clean_alias_validation"]["ok"] is False
    assert artifact["existing_clean_alias_validation"]["forbidden_seed_key_hits"] == 1
