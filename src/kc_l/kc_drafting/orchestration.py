from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from shutil import copyfile
from typing import Any, Dict, List, Mapping, Optional, Tuple

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

from kc_l.audit.manifests import build_input_manifest, build_output_manifest, env_snapshot, try_cmd_version
from kc_l.kc.curriculum_kc_coverage import emit_curriculum_kc_coverage_manifest
from kc_l.kc_drafting.backend import build_drafting_backend
from kc_l.kc_drafting.canonicalization import (
    STEP675_CANONICALIZATION_CONTRACT_VERSION,
    emit_canonicalized_draft_bundles,
)
from kc_l.kc_drafting.config import normalize_runner_config
from kc_l.kc_drafting.contracts import (
    DRAFT_CONTRACT_VERSION,
    EXECUTION_MODE_HEURISTIC,
    EXECUTION_MODE_LLM,
    HEURISTIC_DRAFTING_MODE,
    as_text,
)
from kc_l.kc_drafting.packetization import emit_restarted_review_packets_from_draft_bundles
from kc_l.kc_drafting.policy_domain import drafting_domain_policy
from kc_l.kc_drafting.policy_generic import select_overlay_kc_subset
from kc_l.kc_drafting.provenance import (
    build_drafting_runtime_record,
    llm_call_count_from_draft_stats,
    normalize_step6_7_drafting_runtime,
)
from kc_l.kc_drafting.seed_floor_triage import (
    STEP67B_CONTRACT_VERSION,
    emit_seed_floor_triaged_bundles,
)
from kc_l.runtime.current_step_artifacts import resolve_seedless_kc_registry_path
from kc_l.utils.json_io import read_json, read_jsonl, write_json, write_jsonl


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_yaml_or_json(path: Path) -> Dict[str, Any]:
    text = read_text(path)
    if yaml is not None:
        obj = yaml.safe_load(text)
    else:
        obj = json.loads(text)
    if not isinstance(obj, dict):
        raise RuntimeError(f"Expected mapping at config root: {path}")
    return obj


def resolve_repo_path(raw_path: Any, *, base_dir: Optional[Path] = None) -> Path:
    candidate = Path(str(raw_path))
    if candidate.is_absolute():
        return candidate
    root = base_dir if base_dir is not None else Path.cwd()
    return (root / candidate).resolve()


def rel_path(path: Path, *, repo_root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def choose_stage_run_paths(
    processed_root: Path,
    runs_root: Path,
    sets_root: Path,
    *,
    stage_name: str,
    set_file_suffix: str,
) -> Dict[str, Path]:
    base_stamp = utc_stamp()
    suffix = 0
    while True:
        run_id = base_stamp if suffix == 0 else f"{base_stamp}_{suffix:02d}"
        processed_dir = (processed_root / run_id).resolve()
        audit_dir = (runs_root / f"{run_id}_{stage_name}").resolve()
        set_path = (sets_root / f"{run_id}_{set_file_suffix}.json").resolve()
        if not processed_dir.exists() and not audit_dir.exists() and not set_path.exists():
            return {
                "run_id": Path(run_id),
                "processed_dir": processed_dir,
                "audit_dir": audit_dir,
                "set_path": set_path,
            }
        suffix += 1


def copy_config_snapshot(config_path: Path, audit_dir: Path) -> Path:
    target = audit_dir / "config_snapshot.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    copyfile(config_path, target)
    return target


def write_failure_artifacts(
    *,
    audit_dir: Path,
    run_id: str,
    execution: Mapping[str, Any],
    error_message: str,
    source_set_ids: Mapping[str, str],
    tool_versions: Mapping[str, Any],
    input_manifest_paths: List[Path],
) -> None:
    status = (
        "failed_closed"
        if as_text(execution.get("execution_mode")) == EXECUTION_MODE_LLM
        and bool(execution.get("fail_closed_when_llm_unavailable"))
        else "failed"
    )
    failure_runtime = build_drafting_runtime_record(
        execution,
        llm_path_invoked=False,
        llm_calls=0,
        availability_checked=as_text(execution.get("execution_mode")) == EXECUTION_MODE_LLM,
        availability_error=error_message,
        status=status,
    )
    summary = {
        "run_id": run_id,
        "created_utc": now_utc_iso(),
        "draft_contract_version": DRAFT_CONTRACT_VERSION,
        "status": status,
        "error": error_message,
        "selected_kc_ids": [],
        "source_set_ids": dict(source_set_ids),
        "drafting_runtime": failure_runtime,
        "env": env_snapshot(),
        "tool_versions": dict(tool_versions),
    }
    write_json(audit_dir / "summary.json", summary)
    if input_manifest_paths:
        write_json(audit_dir / "input_manifest.json", build_input_manifest(input_manifest_paths))
    write_json(
        audit_dir / "output_manifest.json",
        {
            "processed_outputs": [],
            "audit_outputs": build_output_manifest(audit_dir),
            "set_manifest": {"path": ""},
        },
    )


def resolve_active_set_manifest(pointer_path: Path) -> Path:
    active_name = read_text(pointer_path).strip()
    if not active_name:
        raise RuntimeError(f"Empty active pointer: {pointer_path}")
    return (pointer_path.parent / active_name).resolve()


def resolve_preferred_set_manifest(
    local_pointer_path: Path,
    *,
    fallback_pointer_path: Optional[Path] = None,
    fallback_target_path: Optional[Path] = None,
) -> tuple[Optional[Path], Optional[Path]]:
    if local_pointer_path.exists():
        return local_pointer_path, resolve_active_set_manifest(local_pointer_path)
    if fallback_target_path is not None and fallback_target_path.exists():
        if fallback_pointer_path is not None and fallback_pointer_path.exists():
            return fallback_pointer_path, fallback_target_path.resolve()
        return None, fallback_target_path.resolve()
    if fallback_pointer_path is not None and fallback_pointer_path.exists():
        return fallback_pointer_path, resolve_active_set_manifest(fallback_pointer_path)
    return None, None


def derive_set_id_from_path_hint(raw_value: Any) -> str:
    text = str(raw_value or "").strip().replace("\\", "/")
    if not text:
        return ""
    name = Path(text).name
    if name.endswith(".json"):
        return name[:-5]
    if name.endswith(".txt"):
        return name[:-4]
    return name


def run_step6_7_pipeline(
    *,
    config_path: Path,
    repo_root: Path,
    limit_kcs: int | None = None,
) -> Tuple[int, Dict[str, Any]]:
    resolved_config_path = resolve_repo_path(config_path, base_dir=repo_root)
    cfg = load_yaml_or_json(resolved_config_path)
    normalized = normalize_runner_config(cfg, config_path=resolved_config_path, repo_root=repo_root)

    input_cfg = dict(normalized.get("input_cfg") or {})
    output_cfg = dict(normalized.get("output_cfg") or {})
    slice_cfg = dict(normalized.get("slice_cfg") or {})
    selection_cfg = dict(normalized.get("selection_cfg") or {})
    drafting_cfg = dict(normalized.get("drafting_cfg") or {})
    execution = dict(normalized.get("execution") or {})

    processed_root = resolve_repo_path(output_cfg.get("processed_root") or "data/processed/kc_drafts", base_dir=repo_root)
    sets_root = resolve_repo_path(output_cfg.get("sets_root") or "data/processed/kc_drafts/_sets", base_dir=repo_root)
    runs_root = resolve_repo_path(output_cfg.get("runs_root") or "data/runs", base_dir=repo_root)

    run_paths = choose_stage_run_paths(
        processed_root,
        runs_root,
        sets_root,
        stage_name="step6_7",
        set_file_suffix="step6_7_kc_drafts_set",
    )
    run_id = str(run_paths["run_id"])
    processed_dir = run_paths["processed_dir"]
    audit_dir = run_paths["audit_dir"]
    set_path = run_paths["set_path"]
    audit_dir.mkdir(parents=True, exist_ok=False)
    sets_root.mkdir(parents=True, exist_ok=True)

    config_snapshot_path = copy_config_snapshot(resolved_config_path, audit_dir)

    tool_versions: Dict[str, Any] = {
        "python": try_cmd_version([sys.executable, "--version"]),
    }
    input_manifest_paths: List[Path] = [resolved_config_path]
    source_set_ids: Dict[str, str] = {
        "step6_6_overlay": "",
        "step5_3": "",
    }

    try:
        step6_6_set_path = resolve_repo_path(
            execution.get("step6_6_set_manifest")
            or input_cfg.get("step6_6_set_manifest")
            or "data/work/cache/current_step_artifacts/step6_6_set_manifest.current.json",
            base_dir=repo_root,
        )
        step6_6_set_obj = read_json(step6_6_set_path)
        overlay_path = resolve_repo_path(
            step6_6_set_obj.get("artifacts", {}).get("candidate_sentence_overlay_jsonl"),
            base_dir=repo_root,
        )
        overlay_stats_path = resolve_repo_path(
            step6_6_set_obj.get("artifacts", {}).get("overlay_stats_json"),
            base_dir=repo_root,
        )
        input_manifest_paths.extend([step6_6_set_path, overlay_path, overlay_stats_path])

        overlay_rows = read_jsonl(overlay_path)
        exact_kc_ids = [
            as_text(item)
            for item in slice_cfg.get("exact_kc_ids") or step6_6_set_obj.get("slice", {}).get("exact_kc_ids") or []
            if as_text(item)
        ]
        effective_limit = limit_kcs if limit_kcs is not None else slice_cfg.get("limit_kcs")
        selected_overlay_rows = select_overlay_kc_subset(
            overlay_rows,
            effective_limit,
            exact_kc_ids=exact_kc_ids or None,
        )
        overlay_set_id = as_text(step6_6_set_obj.get("set_id"))
        source_set_ids["step6_6_overlay"] = overlay_set_id
        for row in selected_overlay_rows:
            row["draft_input_overlay_set_id"] = overlay_set_id

        drafting_runtime = build_drafting_runtime_record(
            execution,
            llm_path_invoked=False,
            llm_calls=0,
            availability_checked=False,
            status="selected",
        )

        backend = build_drafting_backend(execution, drafting_cfg=drafting_cfg, selection_cfg=selection_cfg)
        if as_text(execution.get("execution_mode")) == EXECUTION_MODE_LLM:
            backend.ensure_available()
            tool_versions.update(backend.tool_versions())

        with drafting_domain_policy(execution.get("domain_policy_name")):
            bundles, draft_stats = backend.draft(selected_overlay_rows)

        llm_calls = llm_call_count_from_draft_stats(draft_stats)
        drafting_runtime = build_drafting_runtime_record(
            execution,
            llm_path_invoked=llm_calls > 0,
            llm_calls=llm_calls,
            availability_checked=as_text(execution.get("execution_mode")) == EXECUTION_MODE_LLM,
            status="completed",
        )

        draft_stats["drafting_runtime"] = drafting_runtime
        if as_text(execution.get("execution_mode")) == EXECUTION_MODE_HEURISTIC:
            draft_stats["drafting_mode"] = HEURISTIC_DRAFTING_MODE

        source_set_ids["step5_3"] = as_text(bundles[0].get("source_set_id")) if bundles else ""
        processed_dir.mkdir(parents=True, exist_ok=False)

        bundles_path = processed_dir / "kc_draft_bundles.jsonl"
        stats_path = processed_dir / "draft_stats.json"
        write_jsonl(bundles_path, bundles)
        write_json(stats_path, draft_stats)

        input_manifest = build_input_manifest(input_manifest_paths)
        write_json(audit_dir / "input_manifest.json", input_manifest)

        summary = {
            "run_id": run_id,
            "created_utc": now_utc_iso(),
            "draft_contract_version": DRAFT_CONTRACT_VERSION,
            "selected_kc_ids": [as_text(bundle.get("kc_id")) for bundle in bundles],
            "source_set_ids": source_set_ids,
            "drafting_runtime": drafting_runtime,
            "stats": draft_stats,
            "env": env_snapshot(),
            "tool_versions": tool_versions,
        }
        write_json(audit_dir / "summary.json", summary)

        set_manifest = {
            "schema_version": "1.0",
            "kind": "step6_7_kc_drafts_set",
            "set_id": f"{run_id}_step6_7_kc_drafts_set",
            "created_utc": now_utc_iso(),
            "run_id_step6_7": run_id,
            "artifacts": {
                "kc_draft_bundles_jsonl": rel_path(bundles_path, repo_root=repo_root),
                "draft_stats_json": rel_path(stats_path, repo_root=repo_root),
            },
            "upstream": {
                "step6_6_set_manifest_json": rel_path(step6_6_set_path, repo_root=repo_root),
                "candidate_sentence_overlay_jsonl": rel_path(overlay_path, repo_root=repo_root),
                "overlay_stats_json": rel_path(overlay_stats_path, repo_root=repo_root),
            },
            "slice": {
                "exact_kc_ids": [as_text(bundle.get("kc_id")) for bundle in bundles],
                "limit_kcs": len(bundles),
            },
            "drafting_runtime": drafting_runtime,
            "audit": {
                "run_dir": rel_path(audit_dir, repo_root=repo_root),
                "config_snapshot": rel_path(config_snapshot_path, repo_root=repo_root),
                "input_manifest": rel_path(audit_dir / "input_manifest.json", repo_root=repo_root),
                "summary": rel_path(audit_dir / "summary.json", repo_root=repo_root),
                "output_manifest": rel_path(audit_dir / "output_manifest.json", repo_root=repo_root),
            },
        }
        write_json(set_path, set_manifest)

        output_manifest = {
            "processed_outputs": build_output_manifest(processed_dir),
            "audit_outputs": build_output_manifest(audit_dir),
            "set_manifest": {
                "path": rel_path(set_path, repo_root=repo_root),
            },
        }
        write_json(audit_dir / "output_manifest.json", output_manifest)
        return 0, {
            "run_id": run_id,
            "processed_dir": rel_path(processed_dir, repo_root=repo_root),
            "audit_dir": rel_path(audit_dir, repo_root=repo_root),
            "execution_mode": as_text(execution.get("execution_mode")),
            "resolved_generation_model_alias": as_text(execution.get("generation_model_alias")),
            "domain_policy_name": as_text(execution.get("domain_policy_name")),
        }
    except Exception as exc:
        error_message = f"{type(exc).__name__}:{exc}"
        write_failure_artifacts(
            audit_dir=audit_dir,
            run_id=run_id,
            execution=execution,
            error_message=error_message,
            source_set_ids=source_set_ids,
            tool_versions=tool_versions,
            input_manifest_paths=input_manifest_paths,
        )
        return 1, {
            "run_id": run_id,
            "audit_dir": rel_path(audit_dir, repo_root=repo_root),
            "status": "failed_closed" if as_text(execution.get("execution_mode")) == EXECUTION_MODE_LLM else "failed",
            "error": error_message,
            "domain_policy_name": as_text(execution.get("domain_policy_name")),
        }


def run_step6_7b_pipeline(
    *,
    config_path: Path,
    repo_root: Path,
) -> Tuple[int, Dict[str, Any]]:
    resolved_config_path = resolve_repo_path(config_path, base_dir=repo_root)
    cfg = load_yaml_or_json(resolved_config_path)

    input_cfg = dict(cfg.get("inputs") or {})
    output_cfg = dict(cfg.get("outputs") or {})
    model_rescue_cfg = dict(cfg.get("model_rescue") or {})

    processed_root = resolve_repo_path(
        output_cfg.get("processed_root") or "data/processed/kc_seed_floor_triage_and_rescue",
        base_dir=repo_root,
    )
    sets_root = resolve_repo_path(
        output_cfg.get("sets_root") or "data/processed/kc_seed_floor_triage_and_rescue/_sets",
        base_dir=repo_root,
    )
    runs_root = resolve_repo_path(output_cfg.get("runs_root") or "data/runs", base_dir=repo_root)

    step6_7_set_path = resolve_repo_path(
        input_cfg.get("step6_7_set_manifest")
        or "data/work/cache/current_step_artifacts/step6_7_set_manifest.current.json",
        base_dir=repo_root,
    )
    step6_7_set_obj = read_json(step6_7_set_path)
    step6_6_set_manifest_path = resolve_repo_path(
        step6_7_set_obj.get("upstream", {}).get("step6_6_set_manifest_json")
        or "data/work/cache/current_step_artifacts/step6_6_set_manifest.current.json",
        base_dir=repo_root,
    )
    step6_6_set_obj = read_json(step6_6_set_manifest_path)

    bundle_path = resolve_repo_path(
        step6_7_set_obj.get("artifacts", {}).get("kc_draft_bundles_jsonl"),
        base_dir=repo_root,
    )
    overlay_path = resolve_repo_path(
        step6_7_set_obj.get("upstream", {}).get("candidate_sentence_overlay_jsonl"),
        base_dir=repo_root,
    )
    overlay_stats_path = resolve_repo_path(
        step6_7_set_obj.get("upstream", {}).get("overlay_stats_json"),
        base_dir=repo_root,
    )

    draft_rows = read_jsonl(bundle_path)
    overlay_rows = read_jsonl(overlay_path)

    run_paths = choose_stage_run_paths(
        processed_root,
        runs_root,
        sets_root,
        stage_name="step6_7b",
        set_file_suffix="step6_7b_seed_floor_triage_and_rescue_set",
    )
    run_id = str(run_paths["run_id"])
    processed_dir = run_paths["processed_dir"]
    audit_dir = run_paths["audit_dir"]
    set_path = run_paths["set_path"]
    processed_dir.mkdir(parents=True, exist_ok=False)
    audit_dir.mkdir(parents=True, exist_ok=False)
    sets_root.mkdir(parents=True, exist_ok=True)

    config_snapshot_path = copy_config_snapshot(resolved_config_path, audit_dir)

    result = emit_seed_floor_triaged_bundles(
        output_dir=processed_dir,
        draft_rows=draft_rows,
        overlay_rows=overlay_rows,
        model_rescue_cfg=model_rescue_cfg,
    )

    input_manifest_paths = [
        resolved_config_path,
        step6_7_set_path,
        step6_6_set_manifest_path,
        bundle_path,
        overlay_path,
        overlay_stats_path,
    ]
    write_json(audit_dir / "input_manifest.json", build_input_manifest(input_manifest_paths))

    step6_7_set_id = str(step6_7_set_obj.get("set_id") or "")
    step6_6_set_id = str(step6_6_set_obj.get("set_id") or "")
    summary = {
        "run_id": run_id,
        "created_utc": now_utc_iso(),
        "source_set_ids": {
            "step6_6": step6_6_set_id,
            "step6_7": step6_7_set_id,
        },
        "step6_7b_runtime": {
            "contract_version": STEP67B_CONTRACT_VERSION,
            "config_path": rel_path(resolved_config_path, repo_root=repo_root),
            "model_rescue_execution_mode": as_text(model_rescue_cfg.get("execution_mode") or "disabled"),
            "source_step6_7_set_manifest": rel_path(step6_7_set_path, repo_root=repo_root),
        },
        "stats": result.stats,
        "env": env_snapshot(),
        "tool_versions": {
            "python": try_cmd_version([sys.executable, "--version"]),
        },
    }
    write_json(audit_dir / "summary.json", summary)

    set_manifest = {
        "schema_version": "1.0",
        "kind": "step6_7b_seed_floor_triage_and_rescue_set",
        "set_id": f"{run_id}_step6_7b_seed_floor_triage_and_rescue_set",
        "created_utc": now_utc_iso(),
        "run_id_step6_7b": run_id,
        "step6_7b_runtime": summary["step6_7b_runtime"],
        "artifacts": {
            "kc_draft_bundles_rescued_jsonl": rel_path(result.bundle_path, repo_root=repo_root),
            "triage_rows_jsonl": rel_path(result.triage_path, repo_root=repo_root),
            "triage_stats_json": rel_path(result.stats_path, repo_root=repo_root),
        },
        "upstream": {
            "step6_7_set_manifest_json": rel_path(step6_7_set_path, repo_root=repo_root),
            "kc_draft_bundles_jsonl": rel_path(bundle_path, repo_root=repo_root),
            "candidate_sentence_overlay_jsonl": rel_path(overlay_path, repo_root=repo_root),
            "overlay_stats_json": rel_path(overlay_stats_path, repo_root=repo_root),
            "step6_6_set_manifest_json": rel_path(step6_6_set_manifest_path, repo_root=repo_root),
        },
        "slice": dict(step6_7_set_obj.get("slice") or {}),
        "audit": {
            "run_dir": rel_path(audit_dir, repo_root=repo_root),
            "config_snapshot": rel_path(config_snapshot_path, repo_root=repo_root),
            "input_manifest": rel_path(audit_dir / "input_manifest.json", repo_root=repo_root),
            "summary": rel_path(audit_dir / "summary.json", repo_root=repo_root),
            "output_manifest": rel_path(audit_dir / "output_manifest.json", repo_root=repo_root),
        },
    }
    write_json(set_path, set_manifest)

    output_manifest = {
        "processed_outputs": build_output_manifest(processed_dir),
        "audit_outputs": build_output_manifest(audit_dir),
        "set_manifest": {
            "path": rel_path(set_path, repo_root=repo_root),
        },
    }
    write_json(audit_dir / "output_manifest.json", output_manifest)
    return 0, {
        "run_id": run_id,
        "processed_dir": rel_path(processed_dir, repo_root=repo_root),
        "audit_dir": rel_path(audit_dir, repo_root=repo_root),
        "triaged_fallback_count": result.triaged_count,
        "rescued_direct_count": int(result.stats.get("rescued_direct_count") or 0),
        "rescued_normalized_count": int(result.stats.get("rescued_normalized_count") or 0),
    }


def run_step6_75_pipeline(
    *,
    config_path: Path,
    repo_root: Path,
) -> Tuple[int, Dict[str, Any]]:
    resolved_config_path = resolve_repo_path(config_path, base_dir=repo_root)
    cfg = load_yaml_or_json(resolved_config_path)

    input_cfg = dict(cfg.get("inputs") or {})
    output_cfg = dict(cfg.get("outputs") or {})
    canonicalization_cfg = dict(cfg.get("canonicalization") or {})

    processed_root = resolve_repo_path(
        output_cfg.get("processed_root") or "data/processed/kc_draft_canonicalization",
        base_dir=repo_root,
    )
    sets_root = resolve_repo_path(
        output_cfg.get("sets_root") or "data/processed/kc_draft_canonicalization/_sets",
        base_dir=repo_root,
    )
    runs_root = resolve_repo_path(output_cfg.get("runs_root") or "data/runs", base_dir=repo_root)

    step6_7b_candidate_path = resolve_repo_path(
        input_cfg.get("step6_7b_set_manifest")
        or "data/work/cache/current_step_artifacts/step6_7b_set_manifest.current.json",
        base_dir=repo_root,
    )
    step6_7b_set_path = step6_7b_candidate_path if step6_7b_candidate_path.exists() else None
    step6_7b_set_obj = read_json(step6_7b_set_path) if step6_7b_set_path is not None else {}

    step6_7_set_path = resolve_repo_path(
        step6_7b_set_obj.get("upstream", {}).get("step6_7_set_manifest_json")
        or input_cfg.get("step6_7_set_manifest")
        or "data/work/cache/current_step_artifacts/step6_7_set_manifest.current.json",
        base_dir=repo_root,
    )
    step6_7_set_obj = read_json(step6_7_set_path)
    step6_6_set_manifest_path = resolve_repo_path(
        step6_7b_set_obj.get("upstream", {}).get("step6_6_set_manifest_json")
        or step6_7_set_obj.get("upstream", {}).get("step6_6_set_manifest_json")
        or "data/work/cache/current_step_artifacts/step6_6_set_manifest.current.json",
        base_dir=repo_root,
    )
    step6_6_set_obj = read_json(step6_6_set_manifest_path)

    if step6_7b_set_path is not None:
        bundle_path = resolve_repo_path(
            step6_7b_set_obj.get("artifacts", {}).get("kc_draft_bundles_rescued_jsonl"),
            base_dir=repo_root,
        )
        triage_path = resolve_repo_path(
            step6_7b_set_obj.get("artifacts", {}).get("triage_rows_jsonl"),
            base_dir=repo_root,
        )
        triage_stats_path = resolve_repo_path(
            step6_7b_set_obj.get("artifacts", {}).get("triage_stats_json"),
            base_dir=repo_root,
        )
    else:
        bundle_path = resolve_repo_path(
            step6_7_set_obj.get("artifacts", {}).get("kc_draft_bundles_jsonl"),
            base_dir=repo_root,
        )
        triage_path = None
        triage_stats_path = None
    overlay_path = resolve_repo_path(
        step6_7b_set_obj.get("upstream", {}).get("candidate_sentence_overlay_jsonl")
        or step6_7_set_obj.get("upstream", {}).get("candidate_sentence_overlay_jsonl"),
        base_dir=repo_root,
    )
    overlay_stats_path = resolve_repo_path(
        step6_7b_set_obj.get("upstream", {}).get("overlay_stats_json")
        or step6_7_set_obj.get("upstream", {}).get("overlay_stats_json"),
        base_dir=repo_root,
    )
    draft_rows = read_jsonl(bundle_path)
    overlay_rows = read_jsonl(overlay_path)

    run_paths = choose_stage_run_paths(
        processed_root,
        runs_root,
        sets_root,
        stage_name="step6_75",
        set_file_suffix="step6_75_kc_draft_canonicalization_set",
    )
    run_id = str(run_paths["run_id"])
    processed_dir = run_paths["processed_dir"]
    audit_dir = run_paths["audit_dir"]
    set_path = run_paths["set_path"]
    processed_dir.mkdir(parents=True, exist_ok=False)
    audit_dir.mkdir(parents=True, exist_ok=False)
    sets_root.mkdir(parents=True, exist_ok=True)

    config_snapshot_path = copy_config_snapshot(resolved_config_path, audit_dir)

    allow_definition_extractive_selection = bool(
        canonicalization_cfg.get("allow_definition_extractive_selection", True)
    )
    allow_scope_extractive_selection = bool(
        canonicalization_cfg.get("allow_scope_extractive_selection", False)
    )
    result = emit_canonicalized_draft_bundles(
        output_dir=processed_dir,
        draft_rows=draft_rows,
        overlay_rows=overlay_rows,
        allow_definition_extractive_selection=allow_definition_extractive_selection,
        allow_scope_extractive_selection=allow_scope_extractive_selection,
    )

    input_manifest_paths = [
        resolved_config_path,
        step6_7_set_path,
        step6_6_set_manifest_path,
        bundle_path,
        overlay_path,
        overlay_stats_path,
    ]
    if step6_7b_set_path is not None:
        input_manifest_paths.append(step6_7b_set_path)
    if triage_path is not None:
        input_manifest_paths.append(triage_path)
    if triage_stats_path is not None:
        input_manifest_paths.append(triage_stats_path)
    write_json(audit_dir / "input_manifest.json", build_input_manifest(input_manifest_paths))

    step6_7_set_id = str(step6_7_set_obj.get("set_id") or "")
    step6_6_set_id = str(step6_6_set_obj.get("set_id") or "")
    step6_7b_set_id = str(step6_7b_set_obj.get("set_id") or "") if step6_7b_set_path is not None else ""
    canonicalization_runtime = {
        "contract_version": STEP675_CANONICALIZATION_CONTRACT_VERSION,
        "config_path": rel_path(resolved_config_path, repo_root=repo_root),
        "allow_definition_extractive_selection": allow_definition_extractive_selection,
        "allow_scope_extractive_selection": allow_scope_extractive_selection,
        "source_step6_7_set_manifest": rel_path(step6_7_set_path, repo_root=repo_root),
    }
    if step6_7b_set_path is not None:
        canonicalization_runtime["source_step6_7b_set_manifest"] = rel_path(step6_7b_set_path, repo_root=repo_root)
    summary = {
        "run_id": run_id,
        "created_utc": now_utc_iso(),
        "source_set_ids": {
            "step6_6": step6_6_set_id,
            "step6_7": step6_7_set_id,
            "step6_7b": step6_7b_set_id,
        },
        "canonicalization_runtime": canonicalization_runtime,
        "stats": result.stats,
        "env": env_snapshot(),
        "tool_versions": {
            "python": try_cmd_version([sys.executable, "--version"]),
        },
    }
    write_json(audit_dir / "summary.json", summary)

    set_manifest = {
        "schema_version": "1.0",
        "kind": "step6_75_kc_draft_canonicalization_set",
        "set_id": f"{run_id}_step6_75_kc_draft_canonicalization_set",
        "created_utc": now_utc_iso(),
        "run_id_step6_75": run_id,
        "canonicalization_runtime": canonicalization_runtime,
        "artifacts": {
            "kc_draft_bundles_canonicalized_jsonl": rel_path(result.bundle_path, repo_root=repo_root),
            "canonicalization_stats_json": rel_path(result.stats_path, repo_root=repo_root),
        },
        "upstream": {
            "step6_7_set_manifest_json": rel_path(step6_7_set_path, repo_root=repo_root),
            "kc_draft_bundles_jsonl": rel_path(bundle_path, repo_root=repo_root),
            "candidate_sentence_overlay_jsonl": rel_path(overlay_path, repo_root=repo_root),
            "overlay_stats_json": rel_path(overlay_stats_path, repo_root=repo_root),
            "step6_6_set_manifest_json": rel_path(step6_6_set_manifest_path, repo_root=repo_root),
        },
        "slice": dict(step6_7_set_obj.get("slice") or {}),
        "audit": {
            "run_dir": rel_path(audit_dir, repo_root=repo_root),
            "config_snapshot": rel_path(config_snapshot_path, repo_root=repo_root),
            "input_manifest": rel_path(audit_dir / "input_manifest.json", repo_root=repo_root),
            "summary": rel_path(audit_dir / "summary.json", repo_root=repo_root),
            "output_manifest": rel_path(audit_dir / "output_manifest.json", repo_root=repo_root),
        },
    }
    if step6_7b_set_path is not None:
        set_manifest["upstream"]["step6_7b_set_manifest_json"] = rel_path(step6_7b_set_path, repo_root=repo_root)
        set_manifest["upstream"]["kc_draft_bundles_rescued_jsonl"] = rel_path(bundle_path, repo_root=repo_root)
        if triage_path is not None:
            set_manifest["upstream"]["triage_rows_jsonl"] = rel_path(triage_path, repo_root=repo_root)
        if triage_stats_path is not None:
            set_manifest["upstream"]["triage_stats_json"] = rel_path(triage_stats_path, repo_root=repo_root)
    write_json(set_path, set_manifest)

    output_manifest = {
        "processed_outputs": build_output_manifest(processed_dir),
        "audit_outputs": build_output_manifest(audit_dir),
        "set_manifest": {
            "path": rel_path(set_path, repo_root=repo_root),
        },
    }
    write_json(audit_dir / "output_manifest.json", output_manifest)
    return 0, {
        "run_id": run_id,
        "processed_dir": rel_path(processed_dir, repo_root=repo_root),
        "audit_dir": rel_path(audit_dir, repo_root=repo_root),
        "bundle_count": result.bundle_count,
    }


def run_step6_8_pipeline(
    *,
    config_path: Path,
    repo_root: Path,
) -> Tuple[int, Dict[str, Any]]:
    resolved_config_path = resolve_repo_path(config_path, base_dir=repo_root)
    cfg = load_yaml_or_json(resolved_config_path)

    input_cfg = dict(cfg.get("inputs") or {})
    output_cfg = dict(cfg.get("outputs") or {})

    processed_root = resolve_repo_path(
        output_cfg.get("processed_root") or "data/processed/kc_review_packets_restarted",
        base_dir=repo_root,
    )
    sets_root = resolve_repo_path(
        output_cfg.get("sets_root") or "data/processed/kc_review_packets_restarted/_sets",
        base_dir=repo_root,
    )
    runs_root = resolve_repo_path(output_cfg.get("runs_root") or "data/runs", base_dir=repo_root)

    step6_75_candidate_path = resolve_repo_path(
        input_cfg.get("step6_75_set_manifest")
        or "data/work/cache/current_step_artifacts/step6_75_set_manifest.current.json",
        base_dir=repo_root,
    )
    step6_75_set_path = step6_75_candidate_path if step6_75_candidate_path.exists() else None
    step6_75_set_obj = read_json(step6_75_set_path) if step6_75_set_path is not None else {}

    step6_7b_set_path = (
        resolve_repo_path(step6_75_set_obj.get("upstream", {}).get("step6_7b_set_manifest_json"), base_dir=repo_root)
        if step6_75_set_obj.get("upstream", {}).get("step6_7b_set_manifest_json")
        else None
    )
    step6_7b_set_obj = read_json(step6_7b_set_path) if step6_7b_set_path is not None else {}

    step6_7_set_path = resolve_repo_path(
        input_cfg.get("step6_7_set_manifest")
        or step6_75_set_obj.get("upstream", {}).get("step6_7_set_manifest_json")
        or step6_7b_set_obj.get("upstream", {}).get("step6_7_set_manifest_json")
        or "data/work/cache/current_step_artifacts/step6_7_set_manifest.current.json",
        base_dir=repo_root,
    )
    step6_7_set_obj = read_json(step6_7_set_path)

    step6_6_set_manifest_path = resolve_repo_path(
        step6_7_set_obj.get("upstream", {}).get("step6_6_set_manifest_json")
        or "data/work/cache/current_step_artifacts/step6_6_set_manifest.current.json",
        base_dir=repo_root,
    )
    step6_6_set_obj = read_json(step6_6_set_manifest_path)
    step1_registry_path = resolve_seedless_kc_registry_path(
        step6_6_set_obj.get("upstream", {}).get("kc_registry_jsonl"),
        repo_root=repo_root,
    )
    step1_5_overlay_manifest_path = resolve_repo_path(
        step6_6_set_obj.get("upstream", {}).get("hierarchy_overlay_manifest_json")
        or "data/work/cache/current_step_artifacts/step1_5_overlay_manifest.current.json",
        base_dir=repo_root,
    )
    leaf_to_overlay_ancestry_path = resolve_repo_path(
        step6_6_set_obj.get("upstream", {}).get("leaf_to_overlay_ancestry_json"),
        base_dir=repo_root,
    )

    raw_step6_7_bundle_path = resolve_repo_path(
        step6_7_set_obj.get("artifacts", {}).get("kc_draft_bundles_jsonl"),
        base_dir=repo_root,
    )
    draft_stats_path = resolve_repo_path(step6_7_set_obj.get("artifacts", {}).get("draft_stats_json"), base_dir=repo_root)
    draft_stats = read_json(draft_stats_path)
    step6_7_drafting_runtime = normalize_step6_7_drafting_runtime(step6_7_set_obj, draft_stats)

    if step6_75_set_path is not None:
        bundle_path = resolve_repo_path(
            step6_75_set_obj.get("artifacts", {}).get("kc_draft_bundles_canonicalized_jsonl"),
            base_dir=repo_root,
        )
        canonicalization_stats_path = resolve_repo_path(
            step6_75_set_obj.get("artifacts", {}).get("canonicalization_stats_json"),
            base_dir=repo_root,
        )
    else:
        bundle_path = raw_step6_7_bundle_path
        canonicalization_stats_path = None

    draft_rows = read_jsonl(bundle_path)
    step1_registry_rows = read_jsonl(step1_registry_path)
    leaf_to_overlay_ancestry = read_json(leaf_to_overlay_ancestry_path)
    source_processed_dir = bundle_path.parent

    local_step4_pointer = resolve_repo_path("data/processed/retrieval_index/_sets/ACTIVE_STEP4_SET.txt", base_dir=repo_root)
    local_step4_5_pointer = resolve_repo_path(
        "data/processed/retrieval_sentence_overlay/_sets/ACTIVE_STEP4_5_SENTENCE_SET.txt",
        base_dir=repo_root,
    )

    fallback_step4_pointer = (
        resolve_repo_path(step6_6_set_obj.get("upstream", {}).get("step4_active_set_pointer"), base_dir=repo_root)
        if step6_6_set_obj.get("upstream", {}).get("step4_active_set_pointer")
        else None
    )
    fallback_step4_target = (
        resolve_repo_path(step6_6_set_obj.get("upstream", {}).get("step4_active_set_target"), base_dir=repo_root)
        if step6_6_set_obj.get("upstream", {}).get("step4_active_set_target")
        else None
    )
    fallback_step4_5_pointer = (
        resolve_repo_path(step6_6_set_obj.get("upstream", {}).get("step4_5_active_set_pointer"), base_dir=repo_root)
        if step6_6_set_obj.get("upstream", {}).get("step4_5_active_set_pointer")
        else None
    )
    fallback_step4_5_target = (
        resolve_repo_path(step6_6_set_obj.get("upstream", {}).get("step4_5_active_set_target"), base_dir=repo_root)
        if step6_6_set_obj.get("upstream", {}).get("step4_5_active_set_target")
        else None
    )

    raw_step4_pointer = step6_6_set_obj.get("upstream", {}).get("step4_active_set_pointer")
    raw_step4_target = step6_6_set_obj.get("upstream", {}).get("step4_active_set_target")
    raw_step4_5_pointer = step6_6_set_obj.get("upstream", {}).get("step4_5_active_set_pointer")
    raw_step4_5_target = step6_6_set_obj.get("upstream", {}).get("step4_5_active_set_target")

    step4_pointer, step4_set_manifest_path = resolve_preferred_set_manifest(
        local_step4_pointer,
        fallback_pointer_path=fallback_step4_pointer,
        fallback_target_path=fallback_step4_target,
    )
    step4_5_pointer, step4_5_set_manifest_path = resolve_preferred_set_manifest(
        local_step4_5_pointer,
        fallback_pointer_path=fallback_step4_5_pointer,
        fallback_target_path=fallback_step4_5_target,
    )

    step4_set_id = (
        str(read_json(step4_set_manifest_path).get("set_id") or step4_set_manifest_path.stem)
        if step4_set_manifest_path is not None
        else derive_set_id_from_path_hint(raw_step4_target) or derive_set_id_from_path_hint(raw_step4_pointer)
    )
    step4_5_set_id = (
        str(read_json(step4_5_set_manifest_path).get("set_id") or step4_5_set_manifest_path.stem)
        if step4_5_set_manifest_path is not None
        else derive_set_id_from_path_hint(raw_step4_5_target) or derive_set_id_from_path_hint(raw_step4_5_pointer)
    )

    step5_set_id = str(draft_rows[0].get("source_set_id") or "") if draft_rows else ""
    step6_6_set_id = str(
        step6_6_set_obj.get("set_id")
        or (draft_rows[0].get("draft_input_overlay_set_id") if draft_rows else "")
        or ""
    )
    step6_7_set_id = str(step6_7_set_obj.get("set_id") or "")
    step6_7b_set_id = str(step6_7b_set_obj.get("set_id") or "") if step6_7b_set_path is not None else ""

    run_paths = choose_stage_run_paths(
        processed_root,
        runs_root,
        sets_root,
        stage_name="step6_8",
        set_file_suffix="step6_8_kc_review_packets_restarted_set",
    )
    run_id = str(run_paths["run_id"])
    processed_dir = run_paths["processed_dir"]
    audit_dir = run_paths["audit_dir"]
    set_path = run_paths["set_path"]
    processed_dir.mkdir(parents=True, exist_ok=False)
    audit_dir.mkdir(parents=True, exist_ok=False)
    sets_root.mkdir(parents=True, exist_ok=True)

    config_snapshot_path = copy_config_snapshot(resolved_config_path, audit_dir)

    step6_75_set_id = str(step6_75_set_obj.get("set_id") or "") if step6_75_set_path is not None else ""

    result = emit_restarted_review_packets_from_draft_bundles(
        source_processed_dir=source_processed_dir,
        output_dir=processed_dir,
        draft_rows=draft_rows,
        step4_set_id=step4_set_id,
        step4_5_set_id=step4_5_set_id,
        step5_set_id=step5_set_id,
        step6_6_set_id=step6_6_set_id,
        step6_7_set_id=step6_7_set_id,
        step6_7b_set_id=step6_7b_set_id,
        step6_75_set_id=step6_75_set_id,
        step6_8_run_id=run_id,
        step6_7_drafting_runtime=step6_7_drafting_runtime,
    )

    review_packets = read_jsonl(result.packet_path)
    packet_summary = read_json(result.summary_path)
    coverage_result = emit_curriculum_kc_coverage_manifest(
        output_dir=processed_dir,
        registry_rows=step1_registry_rows,
        ancestry_by_kc_id=leaf_to_overlay_ancestry,
        draft_rows=draft_rows,
        ready_packets=review_packets,
        review_summary=packet_summary,
        step1_registry_path=step1_registry_path,
        step1_5_overlay_manifest_path=step1_5_overlay_manifest_path,
        step6_6_set_id=step6_6_set_id,
        step6_7_set_id=step6_7_set_id,
        step6_8_run_id=run_id,
    )
    coverage_summary = read_json(coverage_result.summary_path)

    input_manifest_paths = [
        resolved_config_path,
        step6_7_set_path,
        step6_6_set_manifest_path,
        step1_registry_path,
        step1_5_overlay_manifest_path,
        leaf_to_overlay_ancestry_path,
        raw_step6_7_bundle_path,
        draft_stats_path,
    ]
    if step6_7b_set_path is not None:
        input_manifest_paths.append(step6_7b_set_path)
    if step6_75_set_path is not None:
        input_manifest_paths.append(step6_75_set_path)
    if canonicalization_stats_path is not None:
        input_manifest_paths.append(canonicalization_stats_path)
    if step6_75_set_path is not None:
        input_manifest_paths.append(bundle_path)
    if step4_set_manifest_path is not None:
        input_manifest_paths.append(step4_set_manifest_path)
    if step4_5_set_manifest_path is not None:
        input_manifest_paths.append(step4_5_set_manifest_path)
    if step4_pointer is not None:
        input_manifest_paths.append(step4_pointer)
    if step4_5_pointer is not None:
        input_manifest_paths.append(step4_5_pointer)

    input_manifest = build_input_manifest(input_manifest_paths)
    write_json(audit_dir / "input_manifest.json", input_manifest)

    summary = {
        "run_id": run_id,
        "created_utc": now_utc_iso(),
        "source_set_ids": {
            "step4": step4_set_id,
            "step4_5": step4_5_set_id,
            "step5_3": step5_set_id,
            "step6_6": step6_6_set_id,
            "step6_7": step6_7_set_id,
            "step6_7b": step6_7b_set_id,
        },
        "source_processed_dir": rel_path(source_processed_dir, repo_root=repo_root),
        "step6_7_drafting_runtime": step6_7_drafting_runtime,
        "stats": packet_summary,
        "curriculum_kc_coverage": coverage_summary,
        "env": env_snapshot(),
        "tool_versions": {
            "python": try_cmd_version([sys.executable, "--version"]),
        },
    }
    write_json(audit_dir / "summary.json", summary)

    set_manifest = {
        "schema_version": "1.0",
        "kind": "step6_8_kc_review_packets_restarted_set",
        "set_id": f"{run_id}_step6_8_kc_review_packets_restarted_set",
        "created_utc": now_utc_iso(),
        "run_id_step6_8": run_id,
        "artifacts": {
            "review_packet_jsonl": rel_path(result.packet_path, repo_root=repo_root),
            "review_packet_summary_json": rel_path(result.summary_path, repo_root=repo_root),
            "review_packet_preview_md": rel_path(result.preview_path, repo_root=repo_root),
            "curriculum_kc_coverage_manifest_jsonl": rel_path(coverage_result.manifest_path, repo_root=repo_root),
            "curriculum_kc_coverage_summary_json": rel_path(coverage_result.summary_path, repo_root=repo_root),
        },
        "upstream": {
            "step1_kc_registry_jsonl": rel_path(step1_registry_path, repo_root=repo_root),
            "step1_5_overlay_manifest_json": rel_path(step1_5_overlay_manifest_path, repo_root=repo_root),
            "leaf_to_overlay_ancestry_json": rel_path(leaf_to_overlay_ancestry_path, repo_root=repo_root),
            "step6_7_set_manifest_json": rel_path(step6_7_set_path, repo_root=repo_root),
            "step6_6_set_manifest_json": rel_path(step6_6_set_manifest_path, repo_root=repo_root),
            "kc_draft_bundles_jsonl": rel_path(bundle_path, repo_root=repo_root),
            "draft_stats_json": rel_path(draft_stats_path, repo_root=repo_root),
        },
        "step6_7_drafting_runtime": step6_7_drafting_runtime,
        "slice": {
            "included_kcs": list(packet_summary.get("included_kcs") or []),
            "excluded_kcs": list(packet_summary.get("excluded_kcs") or []),
            "represented_kcs": int(coverage_summary.get("represented_kc_count") or 0),
            "missing_kcs": list(coverage_summary.get("missing_kc_ids") or []),
        },
        "audit": {
            "run_dir": rel_path(audit_dir, repo_root=repo_root),
            "config_snapshot": rel_path(config_snapshot_path, repo_root=repo_root),
            "input_manifest": rel_path(audit_dir / "input_manifest.json", repo_root=repo_root),
            "summary": rel_path(audit_dir / "summary.json", repo_root=repo_root),
            "output_manifest": rel_path(audit_dir / "output_manifest.json", repo_root=repo_root),
        },
    }
    if step6_7b_set_path is not None:
        set_manifest["upstream"]["step6_7b_set_manifest_json"] = rel_path(step6_7b_set_path, repo_root=repo_root)
    write_json(set_path, set_manifest)

    output_manifest = {
        "processed_outputs": build_output_manifest(processed_dir),
        "audit_outputs": build_output_manifest(audit_dir),
        "set_manifest": {
            "path": rel_path(set_path, repo_root=repo_root),
        },
    }
    write_json(audit_dir / "output_manifest.json", output_manifest)
    return 0, {
        "run_id": run_id,
        "processed_dir": rel_path(processed_dir, repo_root=repo_root),
        "audit_dir": rel_path(audit_dir, repo_root=repo_root),
        "packet_count": result.packet_count,
        "excluded_candidate_count": result.excluded_candidate_count,
    }
