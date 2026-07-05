from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from kc_l.kc_drafting.contracts import (
    EXECUTION_MODE_HEURISTIC,
    EXECUTION_MODE_LLM,
    HEURISTIC_DRAFTING_MODE,
    STEP67_RUNTIME_CONTRACT_VERSION,
    as_bool,
    as_text,
    builder_function_name,
)
from kc_l.kc_drafting.model_profile import (
    normalize_step67_model_profile,
    validate_supported_step67_model_profile,
)
from kc_l.kc_drafting.policy_domain import normalize_domain_policy_name


def rel_path(path: Path, *, repo_root: Path | None = None) -> str:
    resolved = path.resolve()
    if repo_root is not None:
        try:
            return resolved.relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            pass
    return str(resolved)


def _single_model_alias(model_cfg: Dict[str, Any]) -> tuple[str, str]:
    generation_model = as_text(model_cfg.get("generation_model"))
    if generation_model:
        return generation_model, "model.generation_model"
    resolved_alias = as_text(model_cfg.get("resolved_model_alias"))
    if resolved_alias:
        return resolved_alias, "model.resolved_model_alias"
    candidates = [as_text(item) for item in model_cfg.get("candidate_models") or [] if as_text(item)]
    if not candidates:
        return "", ""
    if len(candidates) != 1:
        raise RuntimeError(
            "Legacy Step 6.7 LLM config must specify exactly one candidate model or a single resolved_model_alias."
        )
    return candidates[0], "model.candidate_models[0]"


def _generation_model_alias(generation_cfg: Dict[str, Any]) -> tuple[str, str]:
    generation_model = as_text(generation_cfg.get("generation_model"))
    if generation_model:
        return generation_model, "models.generation.generation_model"
    resolved_alias = as_text(generation_cfg.get("resolved_model_alias"))
    if resolved_alias:
        return resolved_alias, "models.generation.resolved_model_alias"
    return "", "models.generation.generation_model"


def normalize_runner_config(
    cfg: Dict[str, Any],
    *,
    config_path: Path,
    repo_root: Path | None = None,
) -> Dict[str, Any]:
    config_path_str = rel_path(config_path, repo_root=repo_root)

    if isinstance(cfg.get("step6_7"), dict):
        step67_cfg = dict(cfg.get("step6_7") or {})
        input_cfg = dict(step67_cfg.get("inputs") or {})
        output_cfg = dict(step67_cfg.get("outputs") or {})
        slice_cfg = dict(step67_cfg.get("slice") or {})
        selection_cfg = dict(step67_cfg.get("selection") or {})
        drafting_cfg = dict(step67_cfg.get("drafting_policy") or {})
        runtime_profile = as_text(dict(cfg.get("runtime_profile") or {}).get("name"))
        models_cfg = dict(cfg.get("models") or {})
        generation_cfg = dict(models_cfg.get("generation") or {})
        gate_cfg = dict(models_cfg.get("gate_llm") or {})
        execution_mode = as_text(step67_cfg.get("execution_mode")).lower()
        if execution_mode not in {EXECUTION_MODE_LLM, EXECUTION_MODE_HEURISTIC}:
            raise RuntimeError(
                "Rendered main-quest Step 6.7 config must set step6_7.execution_mode to `llm` or `heuristic`."
            )
        generation_alias, generation_field = _generation_model_alias(generation_cfg)
        model_profile = normalize_step67_model_profile(generation_cfg)
        validate_supported_step67_model_profile(model_profile, field_prefix="models.generation")
        domain_policy_name = normalize_domain_policy_name(drafting_cfg.get("domain_policy"))
        return {
            "config_kind": "main_quest_rendered",
            "config_path": config_path_str,
            "input_cfg": input_cfg,
            "output_cfg": output_cfg,
            "slice_cfg": slice_cfg,
            "selection_cfg": selection_cfg,
            "drafting_cfg": drafting_cfg,
            "execution": {
                "contract_version": as_text(step67_cfg.get("contract_version")) or STEP67_RUNTIME_CONTRACT_VERSION,
                "config_kind": "main_quest_rendered",
                "config_path": config_path_str,
                "execution_profile": runtime_profile or "unknown",
                "execution_mode": execution_mode,
                "mode_selection_field": "step6_7.execution_mode",
                "llm_required": as_bool(step67_cfg.get("llm_required"), default=(execution_mode == EXECUTION_MODE_LLM)),
                "fail_closed_when_llm_unavailable": as_bool(
                    step67_cfg.get("fail_closed_when_llm_unavailable"),
                    default=(execution_mode == EXECUTION_MODE_LLM),
                ),
                "heuristic_mode_name": as_text(step67_cfg.get("heuristic_mode_name")) or HEURISTIC_DRAFTING_MODE,
                "provider": as_text(model_profile.get("backend_kind")),
                "generation_model_alias": generation_alias,
                "generation_model_field": generation_field,
                "generation_base_url": as_text(generation_cfg.get("base_url")),
                "generation_base_url_field": "models.generation.base_url",
                "gate_model_alias": as_text(gate_cfg.get("resolved_model_alias")),
                "gate_model_field": "models.gate_llm.resolved_model_alias",
                "model_profile": model_profile,
                "model_profile_field": "models.generation",
                "step6_6_set_manifest": as_text(input_cfg.get("step6_6_set_manifest")),
                "step6_6_set_manifest_field": "step6_7.inputs.step6_6_set_manifest",
                "builder_function": builder_function_name(execution_mode),
                "domain_policy_name": domain_policy_name,
                "domain_policy_field": "step6_7.drafting_policy.domain_policy",
                "max_retries": int(generation_cfg.get("max_retries", 3)),
                "num_ctx": int(generation_cfg.get("num_ctx", 8192)),
                "timeout_seconds": float(generation_cfg.get("timeout_seconds", 180)),
                "temperature": float(generation_cfg.get("temperature", 0.0)),
                "top_p": float(generation_cfg.get("top_p", 1.0)),
                "repeat_penalty": float(generation_cfg.get("repeat_penalty", 1.0)),
                "think": bool(model_profile.get("thinking_enabled")),
            },
        }

    input_cfg = dict(cfg.get("inputs") or {})
    output_cfg = dict(cfg.get("outputs") or {})
    slice_cfg = dict(cfg.get("slice") or {})
    selection_cfg = dict(cfg.get("selection") or {})
    drafting_cfg = dict(cfg.get("drafting") or {})
    model_cfg = dict(cfg.get("model") or {})
    execution_mode = EXECUTION_MODE_LLM if model_cfg else EXECUTION_MODE_HEURISTIC
    generation_alias, generation_field = _single_model_alias(model_cfg)
    gate_alias = as_text(model_cfg.get("resolved_gate_model_alias")) or generation_alias
    gate_field = "model.resolved_gate_model_alias" if as_text(model_cfg.get("resolved_gate_model_alias")) else generation_field
    model_profile = normalize_step67_model_profile(model_cfg)
    validate_supported_step67_model_profile(model_profile, field_prefix="model")
    domain_policy_name = normalize_domain_policy_name(drafting_cfg.get("domain_policy"))
    return {
        "config_kind": "legacy_step6_7_runner",
        "config_path": config_path_str,
        "input_cfg": input_cfg,
        "output_cfg": output_cfg,
        "slice_cfg": slice_cfg,
        "selection_cfg": selection_cfg,
        "drafting_cfg": drafting_cfg,
        "execution": {
            "contract_version": STEP67_RUNTIME_CONTRACT_VERSION,
            "config_kind": "legacy_step6_7_runner",
            "config_path": config_path_str,
            "execution_profile": "legacy_runner_config",
            "execution_mode": execution_mode,
            "mode_selection_field": "legacy:model section present" if model_cfg else "legacy:model section absent",
            "llm_required": execution_mode == EXECUTION_MODE_LLM,
            "fail_closed_when_llm_unavailable": execution_mode == EXECUTION_MODE_LLM,
            "heuristic_mode_name": HEURISTIC_DRAFTING_MODE,
            "provider": as_text(model_profile.get("backend_kind")),
            "generation_model_alias": generation_alias,
            "generation_model_field": generation_field,
            "generation_base_url": as_text(model_cfg.get("base_url") or "http://127.0.0.1:11434"),
            "generation_base_url_field": "model.base_url",
            "gate_model_alias": gate_alias,
            "gate_model_field": gate_field,
            "model_profile": model_profile,
            "model_profile_field": "model",
            "step6_6_set_manifest": as_text(
                input_cfg.get("step6_6_set_manifest")
                or "data/work/cache/current_step_artifacts/step6_6_set_manifest.current.json"
            ),
            "step6_6_set_manifest_field": "inputs.step6_6_set_manifest",
            "builder_function": builder_function_name(execution_mode),
            "domain_policy_name": domain_policy_name,
            "domain_policy_field": "drafting.domain_policy",
            "max_retries": int(model_cfg.get("max_retries", 3)),
            "num_ctx": int(model_cfg.get("num_ctx", 8192)),
            "timeout_seconds": float(model_cfg.get("timeout_seconds", 180)),
            "temperature": float(model_cfg.get("temperature", 0.0)),
            "top_p": float(model_cfg.get("top_p", 1.0)),
            "repeat_penalty": float(model_cfg.get("repeat_penalty", 1.0)),
            "think": bool(model_profile.get("thinking_enabled")),
        },
    }
