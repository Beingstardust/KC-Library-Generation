from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from kc_l.kc_drafting.model_profile import apply_step67_model_profile_to_messages
from kc_l.utils.ollama_json import parse_ollama_chat_response_json


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
                "generation_model": "qwen3:30b",
                "provider": "ollama",
                "backend_kind": "ollama",
                "transport_mode": "ollama_chat",
                "resolved_model_alias": "qwen3:30b",
                "base_url": "http://127.0.0.1:11567",
                "max_retries": 2,
                "num_ctx": 8192,
                "timeout_seconds": 180,
                "temperature": 0.0,
                "top_p": 1.0,
                "repeat_penalty": 1.0,
                "thinking_enabled": False,
                "thinking_activation_mode": "request_flag",
                "thinking_system_prefix": "",
                "strip_thought_block_before_parse": False,
                "response_parse_mode": "message_content_or_response_or_thinking",
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
    assert execution["generation_model_field"] == "models.generation.generation_model"
    assert execution["model_profile"]["backend_kind"] == "ollama"
    assert execution["model_profile"]["thinking_enabled"] is False
    assert execution["step6_6_set_manifest_field"] == "step6_7.inputs.step6_6_set_manifest"


def test_main_quest_runner_contract_lifts_definition_generation_mode_from_selection_when_needed():
    cfg = {
        "runtime_profile": {"name": "hpc_gpu"},
        "models": {
            "generation": {
                "generation_model": "qwen3:30b",
                "provider": "ollama",
                "backend_kind": "ollama",
                "transport_mode": "ollama_chat",
                "resolved_model_alias": "qwen3:30b",
                "base_url": "http://127.0.0.1:11567",
                "thinking_enabled": False,
                "thinking_activation_mode": "request_flag",
                "thinking_system_prefix": "",
                "strip_thought_block_before_parse": False,
                "response_parse_mode": "message_content_or_response_or_thinking",
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
                "definition_generation_mode": "packet_multicandidate_v1",
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

    assert normalized["drafting_cfg"]["definition_generation_mode"] == "packet_multicandidate_v1"
    assert (
        normalized["drafting_cfg"]["definition_generation_mode_field"]
        == "step6_7.selection.definition_generation_mode"
    )


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


def test_model_profile_system_prefix_is_config_driven():
    messages = [
        {"role": "system", "content": "Return valid JSON only."},
        {"role": "user", "content": "Draft the field."},
    ]

    prepared = apply_step67_model_profile_to_messages(
        messages,
        {
            "thinking_enabled": True,
            "thinking_activation_mode": "system_prefix",
            "thinking_system_prefix": "Think privately before answering.",
        },
    )

    assert prepared[0]["role"] == "system"
    assert prepared[0]["content"].startswith("Think privately before answering.")
    assert prepared[1] == messages[1]


def test_parse_ollama_chat_response_json_strips_thought_block_only_when_configured():
    outer = {
        "message": {
            "content": (
                '<think>{"private_reasoning":"discard me"}</think>'
                '{"definition":{"status":"grounded","text":"Grounded definition.","supporting_evidence_labels":["E1"],"abstention_reason":""},'
                '"scope":{"status":"abstained","text":"","supporting_evidence_labels":[],"abstention_reason":"insufficient_evidence"}}'
            )
        }
    }

    parsed_without_strip = parse_ollama_chat_response_json(
        outer,
        strip_thought_block_before_parse=False,
    )
    parsed_with_strip = parse_ollama_chat_response_json(
        outer,
        strip_thought_block_before_parse=True,
    )

    assert parsed_without_strip == {"private_reasoning": "discard me"}
    assert parsed_with_strip["definition"]["text"] == "Grounded definition."
