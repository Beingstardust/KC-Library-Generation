from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STEP6_9_RUNNER = _load_module(
    REPO_ROOT / "steps/step_06_9_kc_review_audit_ingestion/scripts/run_step6_9_kc_review_audit_ingestion.py",
    "step6_9_runner_schema_test",
)


# Minimal shapes sufficient to exercise resolve_review_packet_manifest()'s
# schema-detection branches - not full real manifests.
V2_MANIFEST_FIXTURE = {
    "run_id": "20260521T231531Z_current_postprocessed_source_runner_return_contract_fix",
    "schema_version": "step68_v2_current_postprocessed_review_packet_manifest_v1",
    "invariants": {"legacy_step68_runner_not_used": True},
    "outputs": {
        "review_packets_jsonl": (
            "/path/to/projects/kc_l_v2_clean/data/processed/"
            "step68_v2_review_packets_from_postprocessed_source/"
            "20260521T231531Z_current_postprocessed_source_runner_return_contract_fix/"
            "step68_v2_review_packets.jsonl"
        ),
        "stats_json": (
            "/path/to/projects/kc_l_v2_clean/data/processed/"
            "step68_v2_review_packets_from_postprocessed_source/"
            "20260521T231531Z_current_postprocessed_source_runner_return_contract_fix/"
            "STEP68_V2_REVIEW_PACKET_STATS.json"
        ),
    },
}

LEGACY_MANIFEST_FIXTURE = {
    "set_id": "2026-04-24_212725_step6_8_kc_review_packets_restarted_set",
    "schema_version": "1.0",
    "artifacts": {
        "review_packet_jsonl": "data/processed/kc_review_packets_restarted/2026-04-24_212725/review_packets.jsonl",
        "review_packet_summary_json": "data/processed/kc_review_packets_restarted/2026-04-24_212725/review_packet_summary.json",
    },
}


def _write_manifest(tmp_path: Path, name: str, payload: dict) -> Path:
    manifest_path = tmp_path / name
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    return manifest_path


def _use_identity_resolve_repo_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """resolve_repo_path() joins absolute-looking paths against REPO_ROOT in a
    way that mishandles POSIX-absolute HPC paths on Windows test runners;
    stub it to an identity passthrough so these assertions are independent of
    that separately tracked, out-of-scope path-resolution behavior.
    """
    monkeypatch.setattr(
        STEP6_9_RUNNER,
        "resolve_repo_path",
        lambda raw_path, base_dir=None: Path(str(raw_path)),
    )


def test_resolve_review_packet_manifest_detects_v2_schema(tmp_path, monkeypatch):
    _use_identity_resolve_repo_path(monkeypatch)
    manifest_path = _write_manifest(tmp_path, "STEP68_V2_REVIEW_PACKET_MANIFEST.json", V2_MANIFEST_FIXTURE)

    result = STEP6_9_RUNNER.resolve_review_packet_manifest(manifest_path)

    assert result["schema"] == "v2"
    assert result["set_id"] == V2_MANIFEST_FIXTURE["run_id"]
    assert result["review_packet_jsonl_path"] == Path(V2_MANIFEST_FIXTURE["outputs"]["review_packets_jsonl"])
    assert result["review_packet_summary_path"] == Path(V2_MANIFEST_FIXTURE["outputs"]["stats_json"])


def test_resolve_review_packet_manifest_detects_legacy_schema(tmp_path, monkeypatch):
    _use_identity_resolve_repo_path(monkeypatch)
    manifest_path = _write_manifest(
        tmp_path, "2026-04-24_212725_step6_8_kc_review_packets_restarted_set.json", LEGACY_MANIFEST_FIXTURE
    )

    result = STEP6_9_RUNNER.resolve_review_packet_manifest(manifest_path)

    assert result["schema"] == "legacy"
    assert result["set_id"] == LEGACY_MANIFEST_FIXTURE["set_id"]
    assert result["review_packet_jsonl_path"] == Path(LEGACY_MANIFEST_FIXTURE["artifacts"]["review_packet_jsonl"])
    assert result["review_packet_summary_path"] == Path(
        LEGACY_MANIFEST_FIXTURE["artifacts"]["review_packet_summary_json"]
    )
