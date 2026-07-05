from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from kc_l.runtime.layout import get_operator_layout, repo_relative


MODE_TO_OVERLAY = {
    "local_gpu": "main_quest.local_gpu.example.yaml",
    "hpc_gpu": "main_quest.hpc_gpu.example.yaml",
}
STATUS_SCOPE = "operator_shell_only"
VALIDATION_SCOPE = "operator_shell_config_only"
TRUTH_BOUNDARY = (
    "This validation checks operator-shell config structure, repo layout binding, and referenced "
    "file presence. It does not perform strict runtime readiness validation for interpreter "
    "availability, device availability, endpoint reachability, or historically anchored late-stage "
    "step configs."
)
REQUIRED_TOP_LEVEL_KEYS = (
    "project",
    "operator_runtime",
    "inputs",
    "schema_profile",
    "outputs",
    "review",
    "freeze",
    "hpc",
    "legacy_internal_flow",
    "runtime_profile",
    "execution",
    "models",
    "storage",
)
PLACEHOLDER_PREFIXES = ("REPLACE_ME_", "UNRESOLVED_")


@dataclass(frozen=True)
class MainQuestRenderResult:
    mode: str
    config: dict[str, Any]
    report: dict[str, Any]
    output_yaml_path: Path
    output_report_path: Path


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Config must parse to a mapping: {path}")
    return data


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=False), encoding="utf-8")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _deep_merge(base: Any, overlay: Any) -> Any:
    if isinstance(base, dict) and isinstance(overlay, dict):
        merged = dict(base)
        for key, value in overlay.items():
            merged[key] = _deep_merge(merged[key], value) if key in merged else value
        return merged
    return overlay


def _collect_placeholders(obj: Any, prefix: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            found.extend(_collect_placeholders(value, child))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            found.extend(_collect_placeholders(value, f"{prefix}[{index}]"))
    elif isinstance(obj, str) and obj.startswith(PLACEHOLDER_PREFIXES):
        found.append(prefix)
    return found


def _is_example_runtime_profile(runtime_profile: dict[str, Any]) -> bool:
    status = str(runtime_profile.get("status") or "")
    intended_use = str(runtime_profile.get("intended_use") or "")
    return status.startswith("example_") or "example" in intended_use


def load_main_quest_config(mode: str) -> dict[str, Any]:
    if mode not in MODE_TO_OVERLAY:
        raise ValueError(f"Unsupported mode: {mode}")
    layout = get_operator_layout()
    base_cfg = _load_yaml(layout.configs_root / "pipeline" / "main_quest.base.yaml")
    overlay_cfg = _load_yaml(layout.configs_root / "pipeline" / MODE_TO_OVERLAY[mode])
    return _deep_merge(base_cfg, overlay_cfg)


def validate_main_quest_config_mode(mode: str) -> dict[str, Any]:
    layout = get_operator_layout()
    config = load_main_quest_config(mode)
    errors: list[str] = []
    warnings: list[str] = []

    for key in REQUIRED_TOP_LEVEL_KEYS:
        if key not in config:
            errors.append(f"Missing required top-level key: {key}")

    inputs = dict(config.get("inputs") or {})
    outputs = dict(config.get("outputs") or {})
    schema_profile = dict(config.get("schema_profile") or {})
    hpc_cfg = dict(config.get("hpc") or {})
    legacy_flow = dict(config.get("legacy_internal_flow") or {})
    runtime_profile = dict(config.get("runtime_profile") or {})
    execution_cfg = dict(config.get("execution") or {})
    models_cfg = dict(config.get("models") or {})
    overlay_path = layout.configs_root / "pipeline" / MODE_TO_OVERLAY[mode]
    runtime_profile_status = str(runtime_profile.get("status") or "")
    example_overlay = _is_example_runtime_profile(runtime_profile)

    expected_paths = {
        "inputs.course_materials_dir": repo_relative(layout.course_materials_root),
        "inputs.hierarchy_dir": repo_relative(layout.hierarchy_root),
        "outputs.work_cache_root": repo_relative(layout.cache_root),
        "outputs.work_staging_root": repo_relative(layout.staging_root),
        "outputs.runs_root": repo_relative(layout.runs_root),
        "outputs.frozen_library_root": repo_relative(layout.frozen_library_root),
        "outputs.active_pointer_path": repo_relative(layout.active_library_pointer),
        "outputs.exports_root": repo_relative(layout.exports_root),
    }
    actual_paths = {
        "inputs.course_materials_dir": inputs.get("course_materials_dir"),
        "inputs.hierarchy_dir": inputs.get("hierarchy_dir"),
        "outputs.work_cache_root": outputs.get("work_cache_root"),
        "outputs.work_staging_root": outputs.get("work_staging_root"),
        "outputs.runs_root": outputs.get("runs_root"),
        "outputs.frozen_library_root": outputs.get("frozen_library_root"),
        "outputs.active_pointer_path": outputs.get("active_pointer_path"),
        "outputs.exports_root": outputs.get("exports_root"),
    }
    for key, expected in expected_paths.items():
        if actual_paths.get(key) != expected:
            errors.append(f"{key} must resolve to {expected}.")

    for schema_key in ("locked_core_path", "extension_schema_path"):
        raw_path = schema_profile.get(schema_key)
        if not raw_path:
            errors.append(f"schema_profile.{schema_key} must be set.")
            continue
        resolved = (layout.repo_root / str(raw_path)).resolve()
        if not resolved.exists():
            errors.append(f"schema_profile.{schema_key} does not exist: {raw_path}")

    for key in ("slurm_template_path", "runtime_storage_template_path"):
        raw_path = hpc_cfg.get(key)
        if not raw_path:
            errors.append(f"hpc.{key} must be set.")
            continue
        resolved = (layout.repo_root / str(raw_path)).resolve()
        if not resolved.exists():
            errors.append(f"hpc.{key} does not exist: {raw_path}")

    for stage_key, surfaces in legacy_flow.items():
        if not isinstance(surfaces, list) or not surfaces:
            errors.append(f"legacy_internal_flow.{stage_key} must be a non-empty list.")
            continue
        for surface in surfaces:
            resolved = (layout.repo_root / str(surface)).resolve()
            if not resolved.exists():
                errors.append(f"Missing internal legacy surface referenced by {stage_key}: {surface}")

    placeholders = _collect_placeholders(config)
    if placeholders:
        warnings.append(f"Config still contains placeholders: {placeholders}")

    warnings.append(TRUTH_BOUNDARY)

    if example_overlay:
        warnings.append(
            f"Overlay {repo_relative(overlay_path)} is marked as an example/prep surface "
            f"({runtime_profile_status or 'runtime_profile.status unset'}), so `ok` means "
            "operator-shell config validity rather than retained-pipeline runtime readiness."
        )

    interpreter_path = str(execution_cfg.get("interpreter_path") or "").strip()
    if interpreter_path:
        interpreter_candidate = Path(interpreter_path)
        if interpreter_candidate.is_absolute() and not interpreter_candidate.exists():
            warnings.append(
                "execution.interpreter_path was not required to exist on this machine in "
                f"operator-shell config mode: {interpreter_path}"
            )

    if models_cfg.get("generation_endpoint") or models_cfg.get("gate_endpoint"):
        warnings.append(
            "Model endpoints are recorded for config composition, but they were not contacted or "
            "runtime-validated in operator-shell config mode."
        )

    if mode == "hpc_gpu":
        storage = dict(config.get("storage") or {})
        if not storage.get("external_runtime_root"):
            errors.append("HPC mode requires storage.external_runtime_root.")
        else:
            warnings.append(
                "HPC interpreter and external storage fields are treated as planned operator-shell "
                "values here; strict cluster runtime readiness was not validated."
            )

    return {
        "mode": mode,
        "status_scope": STATUS_SCOPE,
        "validation_scope": VALIDATION_SCOPE,
        "truth_boundary": TRUTH_BOUNDARY,
        "full_pipeline_runnable_claimed": False,
        "strict_runtime_readiness_checked": False,
        "operator_shell_config_valid": not errors,
        "input_overlay_path": repo_relative(overlay_path),
        "runtime_profile_status": runtime_profile_status,
        "example_overlay": example_overlay,
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "placeholder_fields": placeholders,
    }


def render_main_quest_config(mode: str, *, persist: bool = True) -> MainQuestRenderResult:
    layout = get_operator_layout()
    config = load_main_quest_config(mode)
    report = validate_main_quest_config_mode(mode)
    output_dir = layout.cache_root / "generated_configs"
    output_yaml_path = output_dir / f"main_quest.{mode}.yaml"
    output_report_path = output_dir / f"main_quest.{mode}.validation.json"
    if persist:
        _write_yaml(output_yaml_path, config)
        _write_json(output_report_path, report)
    return MainQuestRenderResult(
        mode=mode,
        config=config,
        report=report,
        output_yaml_path=output_yaml_path,
        output_report_path=output_report_path,
    )
