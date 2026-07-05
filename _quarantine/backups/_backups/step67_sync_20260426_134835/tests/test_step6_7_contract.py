from __future__ import annotations

import importlib.util
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


STEP67_RUNNER = _load_module(
    REPO_ROOT / "steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py",
    "step67_runner_contract_test",
)
STEP68_RUNNER = _load_module(
    REPO_ROOT / "steps/step_06_8_kc_review_packet_emission/scripts/run_step6_8_kc_review_packet_emission.py",
    "step68_runner_contract_test",
)


def test_main_quest_runner_contract_prefers_explicit_llm_resolution():
    cfg = {
        "runtime_profile": {"name": "hpc_gpu"},
        "models": {
            "generation": {
                "provider": "ollama",
                "resolved_model_alias": "qwen3:30b",
                "base_url": "http://127.0.0.1:11567",
                "max_retries": 2,
                "num_ctx": 8192,
                "timeout_seconds": 180,
                "temperature": 0.0,
                "top_p": 1.0,
                "repeat_penalty": 1.0,
                "think": False,
            },
            "gate_llm": {
                "resolved_model_alias": "qwen3:30b",
                "base_url": "http://127.0.0.1:11567",
            },
        },
        "step6_7": {
            "contract_version": "step6_7_authoritative_runtime_v1",
            "execution_mode": "llm",
            "llm_required": True,
            "fail_closed_when_llm_unavailable": True,
            "heuristic_mode_name": "heuristic_extract_grounded_v1",
            "inputs": {
                "step6_6_set_manifest": "data/work/cache/current_step_artifacts/step6_6_set_manifest.current.json",
            },
            "outputs": {
                "processed_root": "data/processed/kc_drafts",
                "sets_root": "data/processed/kc_drafts/_sets",
                "runs_root": "data/runs",
            },
            "selection": {
                "max_bundle_size": 6,
                "max_explanatory_candidates": 5,
            },
            "drafting_policy": {
                "definition_candidate_limit": 5,
                "scope_candidate_limit": 5,
                "family_context_limit": 4,
                "completion_context_limit": 4,
                "evidence_text_max_chars": 320,
                "short_definition_max_chars": 220,
                "short_definition_max_tokens": 32,
            },
        },
    }

    normalized = STEP67_RUNNER.normalize_runner_config(
        cfg,
        config_path=REPO_ROOT / "data/work/cache/generated_configs/synthetic_main_quest.hpc_gpu.yaml",
    )
    execution = normalized["execution"]

    assert normalized["config_kind"] == "main_quest_rendered"
    assert execution["execution_mode"] == "llm"
    assert execution["builder_function"] == "build_kc_draft_bundles_llm"
    assert execution["generation_model_alias"] == "qwen3:30b"
    assert execution["generation_model_field"] == "models.generation.resolved_model_alias"
    assert execution["step6_6_set_manifest_field"] == "step6_7.inputs.step6_6_set_manifest"


def test_llm_mode_rejects_unresolved_runtime_without_fallback():
    execution = {
        "execution_mode": "llm",
        "provider": "ollama",
        "generation_model_alias": "UNRESOLVED_STEP67_GENERATION_MODEL_ALIAS",
        "generation_model_field": "models.generation.resolved_model_alias",
        "generation_base_url": "UNRESOLVED_STEP67_MODEL_ENDPOINT",
        "generation_base_url_field": "models.generation.base_url",
    }

    with pytest.raises(RuntimeError, match="requires a concrete generation model alias"):
        STEP67_RUNNER.ensure_llm_runtime_available(execution)


def test_step68_backfills_legacy_llm_runtime_proof_from_draft_stats():
    runtime = STEP68_RUNNER.normalize_step6_7_drafting_runtime(
        {
            "audit": {"config_snapshot": "data/runs/2026-04-08_131447_step6_7/config_snapshot.yaml"},
            "upstream": {"step6_6_set_manifest_json": "data/work/cache/current_step_artifacts/step6_6_set_manifest.current.json"},
        },
        {
            "drafting_mode": "llm_multispan_grounded_v1",
            "model_name": "qwen3:30b",
            "llm_runtime": {"llm_calls": 658},
        },
    )

    assert runtime["execution_mode"] == "llm"
    assert runtime["llm_path_invoked"] is True
    assert runtime["llm_calls"] == 658
    assert runtime["resolved_generation_model_alias"] == "qwen3:30b"
