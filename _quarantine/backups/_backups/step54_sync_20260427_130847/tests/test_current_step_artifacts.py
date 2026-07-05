from pathlib import Path

from kc_l.runtime.current_step_artifacts import (
    build_current_step_artifact_status,
    current_step_artifact_alias_paths,
    refresh_current_step_artifacts,
)


def test_current_step_artifact_status_reports_missing_when_no_sources_exist(tmp_path):
    status = build_current_step_artifact_status(tmp_path)
    assert status["ok"] is False
    assert len(status["errors"]) == 4
    assert status["artifacts"]["step1_kc_registry"]["source_path"] is None
    assert status["artifacts"]["step6_7_set_manifest"]["source_path"] is None


def test_refresh_current_step_artifacts_materializes_aliases(tmp_path):
    step1 = tmp_path / "data/processed/hierarchy/2026-04-05_101010/kc_registry.jsonl"
    step1.parent.mkdir(parents=True, exist_ok=True)
    step1.write_text('{"kc_id": "KC_001"}\n', encoding="utf-8")

    step1_5 = tmp_path / "data/processed/hierarchy_overlay/2026-04-05_101515_hierarchy_overlay/overlay_manifest.json"
    step1_5.parent.mkdir(parents=True, exist_ok=True)
    step1_5.write_text('{"artifacts": {}}\n', encoding="utf-8")

    step6_6 = tmp_path / "data/processed/kc_drafting_input_overlay/_sets/2026-04-05_111111_step6_6_kc_drafting_input_overlay_set.json"
    step6_6.parent.mkdir(parents=True, exist_ok=True)
    step6_6.write_text('{"set_id": "step6_6_latest"}\n', encoding="utf-8")

    step6_7 = tmp_path / "data/processed/kc_drafts/_sets/2026-04-05_121212_step6_7_kc_drafts_set.json"
    step6_7.parent.mkdir(parents=True, exist_ok=True)
    step6_7.write_text('{"set_id": "step6_7_latest"}\n', encoding="utf-8")

    result = refresh_current_step_artifacts(tmp_path, persist=True)
    alias_paths = current_step_artifact_alias_paths(tmp_path)

    assert result["ok"] is True
    assert alias_paths["step1_kc_registry"].read_text(encoding="utf-8") == step1.read_text(encoding="utf-8")
    assert alias_paths["step1_5_overlay_manifest"].read_text(encoding="utf-8") == step1_5.read_text(encoding="utf-8")
    assert alias_paths["step6_6_set_manifest"].read_text(encoding="utf-8") == step6_6.read_text(encoding="utf-8")
    assert alias_paths["step6_7_set_manifest"].read_text(encoding="utf-8") == step6_7.read_text(encoding="utf-8")
    assert (tmp_path / "data/work/cache/current_step_artifacts/current_step_artifacts.status.json").exists()
