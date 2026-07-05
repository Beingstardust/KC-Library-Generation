from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kc_l.runtime.layout import REPO_ROOT, get_operator_layout, repo_relative


TRUTH_BOUNDARY = (
    "This discovery layer only resolves stable alias files for the current Step 5 and Step 6 "
    "clean-start templates. It does not certify semantic suitability or full pipeline runtime readiness."
)


@dataclass(frozen=True)
class CurrentStepArtifactSpec:
    key: str
    description: str
    alias_filename: str
    source_glob: str
    sort_key_mode: str
    missing_hint: str


def _resolve_repo_root(repo_root: Path | None = None) -> Path:
    return (repo_root or REPO_ROOT).resolve()


def get_current_step_artifacts_root(repo_root: Path | None = None) -> Path:
    root = _resolve_repo_root(repo_root)
    return get_operator_layout(root).cache_root / "current_step_artifacts"


def get_current_step_artifacts_status_path(repo_root: Path | None = None) -> Path:
    return get_current_step_artifacts_root(repo_root) / "current_step_artifacts.status.json"


def current_step_artifact_specs() -> tuple[CurrentStepArtifactSpec, ...]:
    return (
        CurrentStepArtifactSpec(
            key="step1_kc_registry",
            description="Step 1 kc_registry.jsonl",
            alias_filename="step1_kc_registry.current.jsonl",
            source_glob="data/processed/hierarchy/*/kc_registry.jsonl",
            sort_key_mode="parent_name",
            missing_hint="Run steps/step_01_hierarchy/scripts/01_hierarchy_normalize.py first.",
        ),
        CurrentStepArtifactSpec(
            key="step1_5_overlay_manifest",
            description="Step 1.5 overlay_manifest.json",
            alias_filename="step1_5_overlay_manifest.current.json",
            source_glob="data/processed/hierarchy_overlay/*/overlay_manifest.json",
            sort_key_mode="parent_name",
            missing_hint="Run steps/step_01_5_hierarchy_overlay/scripts/run_step01_5_hierarchy_overlay.py first.",
        ),
        CurrentStepArtifactSpec(
            key="step6_6_set_manifest",
            description="Step 6.6 set manifest",
            alias_filename="step6_6_set_manifest.current.json",
            source_glob="data/processed/kc_drafting_input_overlay/_sets/*_step6_6_kc_drafting_input_overlay_set.json",
            sort_key_mode="file_name",
            missing_hint="Run steps/step_06_6_kc_drafting_input_overlay/scripts/run_step6_6_kc_drafting_input_overlay.py first.",
        ),
        CurrentStepArtifactSpec(
            key="step6_7_set_manifest",
            description="Step 6.7 set manifest",
            alias_filename="step6_7_set_manifest.current.json",
            source_glob="data/processed/kc_drafts/_sets/*_step6_7_kc_drafts_set.json",
            sort_key_mode="file_name",
            missing_hint="Run steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py first.",
        ),
        CurrentStepArtifactSpec(
            key="step6_7b_set_manifest",
            description="Step 6.7B set manifest",
            alias_filename="step6_7b_set_manifest.current.json",
            source_glob="data/processed/kc_seed_floor_triage_and_rescue/_sets/*_step6_7b_seed_floor_triage_and_rescue_set.json",
            sort_key_mode="file_name",
            missing_hint="Run steps/step_06_7b_seed_floor_triage_and_rescue/scripts/run_step6_7b_seed_floor_triage_and_rescue.py first.",
        ),
        CurrentStepArtifactSpec(
            key="step6_75_set_manifest",
            description="Step 6.75 set manifest",
            alias_filename="step6_75_set_manifest.current.json",
            source_glob="data/processed/kc_draft_canonicalization/_sets/*_step6_75_kc_draft_canonicalization_set.json",
            sort_key_mode="file_name",
            missing_hint="Run steps/step_06_75_kc_draft_canonicalization/scripts/run_step6_75_kc_draft_canonicalization.py first.",
        ),
    )


def current_step_artifact_alias_paths(repo_root: Path | None = None) -> dict[str, Path]:
    alias_root = get_current_step_artifacts_root(repo_root)
    return {spec.key: alias_root / spec.alias_filename for spec in current_step_artifact_specs()}


def _discovery_key(path: Path, mode: str) -> tuple[str, str]:
    base = path.parent.name if mode == "parent_name" else path.name
    return (base, path.as_posix())


def _candidate_paths(repo_root: Path, source_glob: str) -> list[Path]:
    return sorted(
        [path.resolve() for path in repo_root.glob(source_glob) if path.is_file()],
        key=lambda item: item.as_posix(),
    )


def _discover_current_source(repo_root: Path, spec: CurrentStepArtifactSpec) -> tuple[Path | None, list[Path]]:
    candidates = _candidate_paths(repo_root, spec.source_glob)
    if not candidates:
        return None, []
    chosen = max(candidates, key=lambda item: _discovery_key(item, spec.sort_key_mode))
    return chosen, candidates


def build_current_step_artifact_status(repo_root: Path | None = None) -> dict[str, Any]:
    root = _resolve_repo_root(repo_root)
    alias_root = get_current_step_artifacts_root(root)
    status_path = get_current_step_artifacts_status_path(root)
    alias_paths = current_step_artifact_alias_paths(root)

    artifacts: dict[str, Any] = {}
    errors: list[str] = []
    for spec in current_step_artifact_specs():
        alias_path = alias_paths[spec.key]
        source_path, candidates = _discover_current_source(root, spec)
        if source_path is None:
            message = (
                f"No current {spec.description} discovered under {spec.source_glob}. "
                f"{spec.missing_hint}"
            )
            errors.append(message)
        else:
            message = (
                f"Resolved current {spec.description} from {repo_relative(source_path, root)} "
                f"using latest compatible artifact discovery under {spec.source_glob}."
            )
        artifacts[spec.key] = {
            "description": spec.description,
            "alias_path": repo_relative(alias_path, root),
            "source_glob": spec.source_glob,
            "resolution_strategy": f"latest_{spec.sort_key_mode}_under_glob",
            "source_path": repo_relative(source_path, root) if source_path is not None else None,
            "candidate_count": len(candidates),
            "ok": source_path is not None,
            "message": message,
        }

    return {
        "ok": not errors,
        "status_scope": "operator_shell_current_artifact_discovery",
        "truth_boundary": TRUTH_BOUNDARY,
        "full_pipeline_runnable_claimed": False,
        "artifacts": artifacts,
        "errors": errors,
        "alias_root": repo_relative(alias_root, root),
        "status_path": repo_relative(status_path, root),
    }


def refresh_current_step_artifacts(repo_root: Path | None = None, *, persist: bool = True) -> dict[str, Any]:
    root = _resolve_repo_root(repo_root)
    status = build_current_step_artifact_status(root)
    alias_root = get_current_step_artifacts_root(root)
    status_path = get_current_step_artifacts_status_path(root)
    alias_paths = current_step_artifact_alias_paths(root)

    if persist:
        alias_root.mkdir(parents=True, exist_ok=True)

    refreshed_artifacts: dict[str, Any] = {}
    for spec in current_step_artifact_specs():
        artifact = dict(status["artifacts"][spec.key])
        alias_path = alias_paths[spec.key]
        source_rel = artifact.get("source_path")
        source_path = (root / str(source_rel)).resolve() if source_rel else None
        stale_alias_removed = False

        if persist and source_path is not None:
            shutil.copyfile(source_path, alias_path)
            artifact["alias_exists"] = True
            artifact["alias_written"] = True
            artifact["stale_alias_removed"] = False
        else:
            if persist and alias_path.exists():
                alias_path.unlink()
                stale_alias_removed = True
            artifact["alias_exists"] = alias_path.exists() if persist else alias_path.exists()
            artifact["alias_written"] = False
            artifact["stale_alias_removed"] = stale_alias_removed

        refreshed_artifacts[spec.key] = artifact

    refreshed = {
        **status,
        "persisted": persist,
        "artifacts": refreshed_artifacts,
    }

    if persist:
        status_path.write_text(json.dumps(refreshed, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    return refreshed
