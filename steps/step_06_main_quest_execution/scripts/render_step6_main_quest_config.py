from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

try:
    import yaml  # type: ignore
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"PyYAML is required to render the main-quest config: {exc}")


REPO_ROOT = Path(__file__).resolve().parents[3]
FORBIDDEN_INPUT_KEYS = {
    "baseline_step6_4_2_summary_json",
    "baseline_step6_4_2_closeout_report",
    "baseline_step6_4_2_false_rejection_audit_json",
    "baseline_step6_4_2_definition_short_audit_jsonl",
    "baseline_step6_4_2_kc_library_jsonl",
    "exact_kc_id_slice",
}
REQUIRED_TOP_LEVEL_KEYS = [
    "project",
    "main_quest",
    "hierarchy_policy",
    "inputs",
    "models",
    "step6_7",
    "semantic_gates",
    "gate_policy",
    "contamination_adjudication",
    "enrichment",
    "provenance_normalization",
    "role_assignment",
    "acceptance_targets",
    "outputs",
    "audit",
]
ALLOWED_STEP67_DOMAIN_POLICIES = {
    "none",
    "model_evaluation_background_v1",
}
ALLOWED_STEP67_DEFINITION_GENERATION_MODES = {
    "legacy_joint_draft_v1",
    "packet_multicandidate_v1",
}
ALLOWED_STEP67_BACKEND_KINDS = {
    "ollama",
}
ALLOWED_STEP67_TRANSPORT_MODES = {
    "ollama_chat",
}
ALLOWED_STEP67_THINKING_ACTIVATION_MODES = {
    "off",
    "request_flag",
    "system_prefix",
}
ALLOWED_STEP67_RESPONSE_PARSE_MODES = {
    "message_content_only",
    "message_content_or_response",
    "message_content_or_response_or_thinking",
}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_structured(path: Path) -> Dict[str, Any]:
    text = read_text(path)
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"Config must parse to a mapping: {path}")
    return data


def write_yaml(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(obj, sort_keys=False, allow_unicode=False)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def deep_merge(base: Any, overlay: Any) -> Any:
    if isinstance(base, dict) and isinstance(overlay, dict):
        merged = dict(base)
        for key, value in overlay.items():
            merged[key] = deep_merge(merged[key], value) if key in merged else value
        return merged
    return overlay


def is_unresolved(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("UNRESOLVED_")


def collect_unresolved(obj: Any, prefix: str = "") -> List[str]:
    out: List[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            out.extend(collect_unresolved(value, child))
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            child = f"{prefix}[{idx}]"
            out.extend(collect_unresolved(value, child))
    elif is_unresolved(obj):
        out.append(prefix)
    return out


def require(condition: bool, message: str, errors: List[str]) -> None:
    if not condition:
        errors.append(message)


def validate_config(config: Dict[str, Any], strict_runtime: bool) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []

    for key in REQUIRED_TOP_LEVEL_KEYS:
        require(key in config, f"Missing required top-level key: {key}", errors)

    inputs = dict(config.get("inputs") or {})
    forbidden_present = sorted(key for key in FORBIDDEN_INPUT_KEYS if key in inputs)
    require(not forbidden_present, f"Forbidden side-quest or validation input keys present: {forbidden_present}", errors)

    hierarchy_policy = dict(config.get("hierarchy_policy") or {})
    require(hierarchy_policy.get("topic_tier_separate_from_atomic_kc_tier") is True, "Topic tier must remain separate from atomic KC tier.", errors)
    require(hierarchy_policy.get("emit_topic_nodes_as_atomic_kcs") is False, "Topic nodes must not be emitted as atomic KCs.", errors)
    require(hierarchy_policy.get("final_atomic_outputs_leaf_only") is True, "Final atomic outputs must remain leaf-only.", errors)

    main_quest = dict(config.get("main_quest") or {})
    require(main_quest.get("execution_authorized_by_config_alone") is False, "Config must remain non-authorizing by itself.", errors)
    policy_path = main_quest.get("semantic_gating_policy_path")
    require(isinstance(policy_path, str) and (REPO_ROOT / policy_path).exists(), "Semantic gating policy path must exist.", errors)

    outputs = dict(config.get("outputs") or {})
    require(outputs.get("processed_root") == "data/processed/kc_library/main_quest", "Processed root must stay inside the dedicated main-quest subtree.", errors)
    require(outputs.get("sets_dir") == "data/processed/kc_library/main_quest/_sets", "Sets dir must stay inside the dedicated main-quest subtree.", errors)

    audit = dict(config.get("audit") or {})
    require(audit.get("runs_dir") == "data/runs/main_quest", "Runs dir must stay inside the dedicated main-quest subtree.", errors)

    step6_7 = dict(config.get("step6_7") or {})
    require(bool(step6_7), "Missing required top-level key contents: step6_7", errors)
    step6_7_inputs = dict(step6_7.get("inputs") or {})
    step6_7_outputs = dict(step6_7.get("outputs") or {})
    step6_7_selection = dict(step6_7.get("selection") or {})
    step6_7_drafting_policy = dict(step6_7.get("drafting_policy") or {})
    execution_mode = str(step6_7.get("execution_mode") or "").strip().lower()
    require(
        execution_mode in {"llm", "heuristic"},
        "step6_7.execution_mode must be either `llm` or `heuristic`.",
        errors,
    )
    require(
        bool(step6_7.get("contract_version")),
        "step6_7.contract_version must be explicit.",
        errors,
    )
    require(
        bool(step6_7.get("heuristic_mode_name")),
        "step6_7.heuristic_mode_name must stay explicit even when LLM mode is selected.",
        errors,
    )
    require(
        step6_7_outputs.get("processed_root") == "data/processed/kc_drafts",
        "Step 6.7 processed_root must stay inside data/processed/kc_drafts.",
        errors,
    )
    require(
        step6_7_outputs.get("sets_root") == "data/processed/kc_drafts/_sets",
        "Step 6.7 sets_root must stay inside data/processed/kc_drafts/_sets.",
        errors,
    )
    require(
        step6_7_outputs.get("runs_root") == "data/runs",
        "Step 6.7 runs_root must stay inside data/runs.",
        errors,
    )
    require(
        bool(step6_7_selection.get("max_bundle_size")),
        "step6_7.selection.max_bundle_size must be explicit.",
        errors,
    )
    require(
        bool(step6_7_selection.get("max_explanatory_candidates")),
        "step6_7.selection.max_explanatory_candidates must be explicit.",
        errors,
    )
    require(
        bool(step6_7_drafting_policy.get("definition_candidate_limit")),
        "step6_7.drafting_policy.definition_candidate_limit must be explicit.",
        errors,
    )
    require(
        bool(step6_7_drafting_policy.get("scope_candidate_limit")),
        "step6_7.drafting_policy.scope_candidate_limit must be explicit.",
        errors,
    )
    require(
        bool(step6_7_drafting_policy.get("definition_generation_mode")),
        "step6_7.drafting_policy.definition_generation_mode must be explicit.",
        errors,
    )
    require(
        step6_7_drafting_policy.get("definition_generation_mode") in ALLOWED_STEP67_DEFINITION_GENERATION_MODES,
        "step6_7.drafting_policy.definition_generation_mode must be one of "
        f"{sorted(ALLOWED_STEP67_DEFINITION_GENERATION_MODES)}.",
        errors,
    )
    require(
        int(step6_7_drafting_policy.get("max_llm_calls_per_kc") or 0) > 0,
        "step6_7.drafting_policy.max_llm_calls_per_kc must be explicit positive config.",
        errors,
    )
    require(
        bool(step6_7_drafting_policy.get("domain_policy")),
        "step6_7.drafting_policy.domain_policy must be explicit.",
        errors,
    )
    require(
        step6_7_drafting_policy.get("domain_policy") in ALLOWED_STEP67_DOMAIN_POLICIES,
        f"step6_7.drafting_policy.domain_policy must be one of {sorted(ALLOWED_STEP67_DOMAIN_POLICIES)}.",
        errors,
    )
    require(
        bool(step6_7_inputs.get("step6_6_set_manifest")),
        "step6_7.inputs.step6_6_set_manifest must be explicit.",
        errors,
    )

    required_paths = [
        Path(inputs["active_step5_primary_set_pointer"]),
    ]
    if step6_7_inputs.get("step6_6_set_manifest"):
        required_paths.append(Path(step6_7_inputs["step6_6_set_manifest"]))
    if inputs.get("active_step5_2_set_pointer"):
        required_paths.append(Path(inputs["active_step5_2_set_pointer"]))
    for rel_path in required_paths:
        require((REPO_ROOT / rel_path).exists(), f"Required input path is missing: {rel_path}", errors)

    optional_paths = [
        Path(inputs["active_step6_set_pointer"]),
        Path(inputs["step4_active_set_pointer"]),
        Path(inputs["kc_registry_path"]),
        Path(inputs["hierarchy_overlay_node_index_path"]),
        Path(inputs["hierarchy_leaf_ancestry_path"]),
    ]
    for rel_path in optional_paths:
        if not (REPO_ROOT / rel_path).exists():
            warnings.append(f"Optional path is not present in this repo snapshot: {rel_path}")

    unresolved_fields = collect_unresolved(config)
    if strict_runtime:
        require(not unresolved_fields, f"Resolved local config still contains unresolved fields: {unresolved_fields}", errors)
    elif unresolved_fields:
        warnings.append(f"Unresolved fields remain: {unresolved_fields}")

    models = dict(config.get("models") or {})
    generation = dict(models.get("generation") or {})
    gate_llm = dict(models.get("gate_llm") or {})
    reranker = dict(models.get("reranker") or {})
    require(
        "preferred_model" not in generation and "fallback_models" not in generation,
        "Legacy Step 6.7 generation fallback fields must not remain in models.generation.",
        errors,
    )
    require(
        "model" not in gate_llm,
        "Legacy Step 6.7 gate model field must not remain in models.gate_llm.",
        errors,
    )
    if execution_mode == "llm":
        require(
            step6_7.get("llm_required") is True,
            "step6_7.llm_required must remain true when execution_mode=llm.",
            errors,
        )
        require(
            step6_7.get("fail_closed_when_llm_unavailable") is True,
            "step6_7.fail_closed_when_llm_unavailable must remain true when execution_mode=llm.",
            errors,
        )
        require(bool(generation.get("generation_model")), "LLM mode must pin models.generation.generation_model.", errors)
        require(bool(generation.get("resolved_model_alias")), "LLM mode must pin models.generation.resolved_model_alias.", errors)
        require(
            generation.get("generation_model") == generation.get("resolved_model_alias"),
            "models.generation.generation_model and models.generation.resolved_model_alias must match.",
            errors,
        )
        require(
            generation.get("backend_kind") in ALLOWED_STEP67_BACKEND_KINDS,
            f"models.generation.backend_kind must be one of {sorted(ALLOWED_STEP67_BACKEND_KINDS)}.",
            errors,
        )
        require(
            generation.get("transport_mode") in ALLOWED_STEP67_TRANSPORT_MODES,
            f"models.generation.transport_mode must be one of {sorted(ALLOWED_STEP67_TRANSPORT_MODES)}.",
            errors,
        )
        require(
            isinstance(generation.get("thinking_enabled"), bool),
            "models.generation.thinking_enabled must be explicit boolean config.",
            errors,
        )
        require(
            generation.get("thinking_activation_mode") in ALLOWED_STEP67_THINKING_ACTIVATION_MODES,
            f"models.generation.thinking_activation_mode must be one of {sorted(ALLOWED_STEP67_THINKING_ACTIVATION_MODES)}.",
            errors,
        )
        require(
            isinstance(generation.get("strip_thought_block_before_parse"), bool),
            "models.generation.strip_thought_block_before_parse must be explicit boolean config.",
            errors,
        )
        require(
            generation.get("response_parse_mode") in ALLOWED_STEP67_RESPONSE_PARSE_MODES,
            f"models.generation.response_parse_mode must be one of {sorted(ALLOWED_STEP67_RESPONSE_PARSE_MODES)}.",
            errors,
        )
        if generation.get("thinking_enabled") and generation.get("thinking_activation_mode") == "system_prefix":
            require(
                bool(generation.get("thinking_system_prefix")),
                "models.generation.thinking_system_prefix must be explicit when thinking uses system_prefix.",
                errors,
            )
        require(bool(generation.get("base_url")), "LLM mode must pin models.generation.base_url.", errors)
        require(bool(gate_llm.get("resolved_model_alias")), "LLM mode must pin models.gate_llm.resolved_model_alias.", errors)
        require(bool(gate_llm.get("base_url")), "LLM mode must pin models.gate_llm.base_url.", errors)

    if strict_runtime:
        execution = dict(config.get("execution") or {})
        require(execution.get("device_mode") == "cuda", "Local runtime must pin device_mode=cuda.", errors)
        interpreter_path = execution.get("interpreter_path")
        require(isinstance(interpreter_path, str) and Path(interpreter_path).exists(), "Pinned interpreter path must exist for local runtime.", errors)
        require(bool(generation.get("base_url")), "Local runtime must pin models.generation.base_url.", errors)
        require(bool(gate_llm.get("base_url")), "Local runtime must pin models.gate_llm.base_url.", errors)
        require(bool(generation.get("resolved_model_alias")), "Local runtime must pin models.generation.resolved_model_alias.", errors)
        require(bool(gate_llm.get("resolved_model_alias")), "Local runtime must pin models.gate_llm.resolved_model_alias.", errors)
        require(reranker.get("device") == "cuda", "Local runtime must pin models.reranker.device=cuda.", errors)

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render and validate main-quest Step 6 config from base plus runtime overlay.")
    parser.add_argument("--base", required=True, help="Repo-relative base config path.")
    parser.add_argument("--overlay", required=True, help="Repo-relative overlay config path.")
    parser.add_argument("--output", required=True, help="Repo-relative resolved config output path.")
    parser.add_argument("--report", required=True, help="Repo-relative validation report output path.")
    parser.add_argument("--strict-runtime", action="store_true", help="Require all runtime-resolved fields to be concrete.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    base_path = (REPO_ROOT / args.base).resolve()
    overlay_path = (REPO_ROOT / args.overlay).resolve()
    output_path = (REPO_ROOT / args.output).resolve()
    report_path = (REPO_ROOT / args.report).resolve()

    base_cfg = load_structured(base_path)
    overlay_cfg = load_structured(overlay_path)
    merged = deep_merge(base_cfg, overlay_cfg)
    report = validate_config(merged, strict_runtime=args.strict_runtime)
    report.update(
        {
            "base_config": str(base_path.relative_to(REPO_ROOT)),
            "overlay_config": str(overlay_path.relative_to(REPO_ROOT)),
            "output_config": str(output_path.relative_to(REPO_ROOT)),
            "strict_runtime": bool(args.strict_runtime),
        }
    )
    write_yaml(output_path, merged)
    write_json(report_path, report)
    if not report["ok"]:
        for message in report["errors"]:
            print(f"ERROR: {message}")
        return 1
    for message in report["warnings"]:
        print(f"WARNING: {message}")
    print(f"Rendered config: {output_path.relative_to(REPO_ROOT)}")
    print(f"Validation report: {report_path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
