from __future__ import annotations

from typing import Any, Dict, Mapping

from kc_l.kc_drafting.contracts import (
    EXECUTION_MODE_LLM,
    HEURISTIC_DRAFTING_MODE,
    STEP67_RUNTIME_CONTRACT_VERSION,
    as_text,
    builder_function_name,
)


def llm_call_count_from_draft_stats(draft_stats: Mapping[str, Any]) -> int:
    return int(((draft_stats.get("llm_runtime") or {}).get("llm_calls") or 0))


def build_drafting_runtime_record(
    execution: Mapping[str, Any],
    *,
    llm_path_invoked: bool,
    llm_calls: int,
    availability_checked: bool,
    availability_error: str = "",
    status: str,
) -> Dict[str, Any]:
    return {
        "contract_version": as_text(execution.get("contract_version")) or STEP67_RUNTIME_CONTRACT_VERSION,
        "config_kind": as_text(execution.get("config_kind")),
        "config_path": as_text(execution.get("config_path")),
        "execution_profile": as_text(execution.get("execution_profile")),
        "execution_mode": as_text(execution.get("execution_mode")),
        "mode_selection_field": as_text(execution.get("mode_selection_field")),
        "heuristic_mode_name": as_text(execution.get("heuristic_mode_name")) or HEURISTIC_DRAFTING_MODE,
        "llm_required": bool(execution.get("llm_required")),
        "fail_closed_when_llm_unavailable": bool(execution.get("fail_closed_when_llm_unavailable")),
        "builder_function": as_text(execution.get("builder_function")),
        "provider": as_text(execution.get("provider")),
        "domain_policy_name": as_text(execution.get("domain_policy_name")) or "none",
        "domain_policy_field": as_text(execution.get("domain_policy_field")),
        "resolved_generation_model_alias": as_text(execution.get("generation_model_alias")),
        "resolved_generation_model_field": as_text(execution.get("generation_model_field")),
        "resolved_generation_base_url": as_text(execution.get("generation_base_url")),
        "resolved_generation_base_url_field": as_text(execution.get("generation_base_url_field")),
        "resolved_gate_model_alias": as_text(execution.get("gate_model_alias")),
        "resolved_gate_model_field": as_text(execution.get("gate_model_field")),
        "step6_6_set_manifest": as_text(execution.get("step6_6_set_manifest")),
        "step6_6_set_manifest_field": as_text(execution.get("step6_6_set_manifest_field")),
        "llm_mode_selected": as_text(execution.get("execution_mode")) == EXECUTION_MODE_LLM,
        "llm_path_invoked": bool(llm_path_invoked),
        "llm_calls": int(llm_calls or 0),
        "availability_checked": bool(availability_checked),
        "availability_error": as_text(availability_error),
        "status": status,
    }


def normalize_step6_7_drafting_runtime(
    step6_7_set_obj: Mapping[str, Any],
    draft_stats: Mapping[str, Any],
) -> Dict[str, Any]:
    runtime = dict(step6_7_set_obj.get("drafting_runtime") or draft_stats.get("drafting_runtime") or {})
    if runtime:
        runtime.setdefault("domain_policy_name", as_text(runtime.get("domain_policy_name")) or "legacy_not_recorded")
        runtime.setdefault("domain_policy_field", as_text(runtime.get("domain_policy_field")) or "legacy_not_recorded")
        return runtime

    llm_calls = llm_call_count_from_draft_stats(draft_stats)
    drafting_mode = as_text(draft_stats.get("drafting_mode"))
    config_snapshot = as_text((step6_7_set_obj.get("audit") or {}).get("config_snapshot"))
    model_name = as_text(draft_stats.get("model_name"))
    llm_selected = llm_calls > 0 or drafting_mode.startswith("llm")
    execution_mode = "llm" if llm_selected else "heuristic"
    return {
        "contract_version": "legacy_step6_7_artifact_backfill_v1",
        "config_kind": "legacy_step6_7_set_artifact",
        "config_path": config_snapshot,
        "execution_profile": "legacy_unknown",
        "execution_mode": execution_mode,
        "mode_selection_field": "legacy_not_recorded",
        "heuristic_mode_name": HEURISTIC_DRAFTING_MODE,
        "llm_required": llm_selected,
        "fail_closed_when_llm_unavailable": llm_selected,
        "builder_function": builder_function_name(execution_mode),
        "provider": "ollama" if llm_selected else "",
        "domain_policy_name": "legacy_not_recorded",
        "domain_policy_field": "legacy_not_recorded",
        "resolved_generation_model_alias": model_name,
        "resolved_generation_model_field": "legacy_not_recorded",
        "resolved_generation_base_url": "",
        "resolved_generation_base_url_field": "legacy_not_recorded",
        "resolved_gate_model_alias": "",
        "resolved_gate_model_field": "",
        "step6_6_set_manifest": as_text((step6_7_set_obj.get("upstream") or {}).get("step6_6_set_manifest_json")),
        "step6_6_set_manifest_field": "upstream.step6_6_set_manifest_json",
        "llm_mode_selected": llm_selected,
        "llm_path_invoked": llm_calls > 0,
        "llm_calls": llm_calls,
        "availability_checked": False,
        "availability_error": "",
        "status": "legacy_backfilled",
    }
