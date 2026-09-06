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
SEEDLESS_REGISTRY_ARTIFACT_KEY = "step1_kc_registry"
SEEDLESS_REGISTRY_ALIAS_FILENAME = "step1_seedless_hierarchy_registry.current.jsonl"
SEEDLESS_REGISTRY_POINTER_FILENAME = "ACTIVE_SEEDLESS_KC_REGISTRY.txt"
LEGACY_REGISTRY_ALIAS_FILENAME = "step1_kc_registry.current.jsonl"
FORBIDDEN_SEED_KEYS = frozenset(
    {
        "seed_definition",
        "seed_keywords",
        "seed_floor",
        "seed_floor_fallback",
        "seed_definition_text",
        "seed_scope",
    }
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


def get_active_seedless_kc_registry_pointer_path(repo_root: Path | None = None) -> Path:
    return get_current_step_artifacts_root(repo_root) / SEEDLESS_REGISTRY_POINTER_FILENAME


def get_seedless_kc_registry_alias_path(repo_root: Path | None = None) -> Path:
    return current_step_artifact_alias_paths(repo_root)[SEEDLESS_REGISTRY_ARTIFACT_KEY]


def _resolve_pointer_target(raw_target: str, *, repo_root: Path, pointer_path: Path) -> Path:
    candidate = Path(raw_target)
    if candidate.is_absolute():
        return candidate.resolve()
    repo_relative_candidate = (repo_root / candidate).resolve()
    if repo_relative_candidate.exists():
        return repo_relative_candidate
    return (pointer_path.parent / candidate).resolve()


def _assert_not_legacy_registry_alias(path: Path) -> None:
    if path.name == LEGACY_REGISTRY_ALIAS_FILENAME:
        raise RuntimeError(
            "Retired seed-bearing registry alias is not allowed in active runtime: "
            f"{LEGACY_REGISTRY_ALIAS_FILENAME}"
        )


def _count_forbidden_seed_keys(value: Any) -> int:
    if isinstance(value, dict):
        hits = sum(1 for key in value.keys() if str(key) in FORBIDDEN_SEED_KEYS)
        for nested in value.values():
            hits += _count_forbidden_seed_keys(nested)
        return hits
    if isinstance(value, list):
        return sum(_count_forbidden_seed_keys(item) for item in value)
    return 0


def _looks_like_kc_registry_row(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if str(value.get("kc_id") or "").strip():
        return True
    knowledge_unit_type = str(
        value.get("knowledge_unit_type") or value.get("unit_type") or value.get("node_type") or ""
    ).strip().lower()
    if knowledge_unit_type == "kc" and str(value.get("knowledge_unit_id") or value.get("node_id") or "").strip():
        return True
    return False


def _validate_existing_seedless_alias(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False,
        "path": str(path),
        "reason": "",
        "parsed_row_count": 0,
        "kc_like_row_count": 0,
        "forbidden_seed_key_hits": 0,
    }
    if not path.exists() or not path.is_file():
        result["reason"] = "missing_file"
        return result

    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if not isinstance(row, dict):
                    result["reason"] = f"non_object_jsonl_row:{line_number}"
                    return result
                result["parsed_row_count"] += 1
                result["forbidden_seed_key_hits"] += _count_forbidden_seed_keys(row)
                if _looks_like_kc_registry_row(row):
                    result["kc_like_row_count"] += 1
    except json.JSONDecodeError as exc:
        result["reason"] = f"json_decode_error:{exc.lineno}"
        return result
    except OSError as exc:
        result["reason"] = f"os_error:{exc.__class__.__name__}"
        return result

    if result["parsed_row_count"] <= 0:
        result["reason"] = "no_jsonl_rows"
        return result
    if result["kc_like_row_count"] <= 0:
        result["reason"] = "no_kc_like_rows"
        return result
    if result["forbidden_seed_key_hits"] > 0:
        result["reason"] = "forbidden_seed_keys_present"
        return result

    result["ok"] = True
    result["reason"] = "clean_existing_alias"
    return result


def resolve_seedless_kc_registry_path(
    explicit_path: str | Path | None = None,
    *,
    repo_root: Path | None = None,
) -> Path:
    root = _resolve_repo_root(repo_root)
    if explicit_path is not None and str(explicit_path).strip():
        candidate = Path(str(explicit_path).strip())
        resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
        _assert_not_legacy_registry_alias(resolved)
        return resolved

    pointer_path = get_active_seedless_kc_registry_pointer_path(root)
    if pointer_path.exists():
        raw_target = pointer_path.read_text(encoding="utf-8").strip()
        if raw_target:
            resolved = _resolve_pointer_target(raw_target, repo_root=root, pointer_path=pointer_path)
            _assert_not_legacy_registry_alias(resolved)
            return resolved

    resolved = get_seedless_kc_registry_alias_path(root).resolve()
    _assert_not_legacy_registry_alias(resolved)
    return resolved


def current_step_artifact_specs() -> tuple[CurrentStepArtifactSpec, ...]:
    return (
        CurrentStepArtifactSpec(
            key=SEEDLESS_REGISTRY_ARTIFACT_KEY,
            description="Step 1 seedless kc_registry_seedless.jsonl",
            alias_filename=SEEDLESS_REGISTRY_ALIAS_FILENAME,
            source_glob="data/processed/hierarchy_seedless_registry/*/kc_registry_seedless.jsonl",
            sort_key_mode="parent_name",
            missing_hint="Run the seedless hierarchy registry builder first.",
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
            key="step5_4_set_manifest",
            description="Step 5.4 set manifest",
            alias_filename="step5_4_set_manifest.current.json",
            source_glob="data/processed/kc_evidence_packs/_sets/*_step5_4_kc_evidence_packs_set.json",
            sort_key_mode="file_name",
            missing_hint="Run steps/step_05_4_evidence_pack_composition/scripts/run_step5_4_evidence_pack_composition.py first.",
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
    seedless_pointer_path = get_active_seedless_kc_registry_pointer_path(root)

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
        "seedless_registry_pointer_path": repo_relative(seedless_pointer_path, root),
    }


def refresh_current_step_artifacts(repo_root: Path | None = None, *, persist: bool = True) -> dict[str, Any]:
    root = _resolve_repo_root(repo_root)
    status = build_current_step_artifact_status(root)
    alias_root = get_current_step_artifacts_root(root)
    status_path = get_current_step_artifacts_status_path(root)
    alias_paths = current_step_artifact_alias_paths(root)
    seedless_pointer_path = get_active_seedless_kc_registry_pointer_path(root)

    if persist:
        alias_root.mkdir(parents=True, exist_ok=True)

    refreshed_artifacts: dict[str, Any] = {}
    for spec in current_step_artifact_specs():
        artifact = dict(status["artifacts"][spec.key])
        alias_path = alias_paths[spec.key]
        source_rel = artifact.get("source_path")
        source_path = (root / str(source_rel)).resolve() if source_rel else None
        stale_alias_removed = False
        preserved_existing_clean_alias = False
        existing_clean_alias_validation: dict[str, Any] | None = None

        if (
            persist
            and spec.key == SEEDLESS_REGISTRY_ARTIFACT_KEY
            and source_path is None
            and alias_path.exists()
        ):
            existing_clean_alias_validation = _validate_existing_seedless_alias(alias_path)
            artifact["existing_clean_alias_validation"] = existing_clean_alias_validation
            if bool(existing_clean_alias_validation.get("ok")):
                preserved_existing_clean_alias = True
                artifact["source_path"] = repo_relative(alias_path, root)
                artifact["resolution_strategy"] = "preserved_existing_clean_alias"
                artifact["ok"] = True
                artifact["message"] = (
                    f"No current {spec.description} discovered under {spec.source_glob}. "
                    f"Preserved existing clean seedless alias from {repo_relative(alias_path, root)}."
                )

        if persist and source_path is not None:
            shutil.copyfile(source_path, alias_path)
            artifact["alias_exists"] = True
            artifact["alias_written"] = True
            artifact["stale_alias_removed"] = False
            artifact["preserved_existing_clean_alias"] = False
        elif preserved_existing_clean_alias:
            artifact["alias_exists"] = True
            artifact["alias_written"] = False
            artifact["stale_alias_removed"] = False
            artifact["preserved_existing_clean_alias"] = True
        else:
            if persist and alias_path.exists():
                alias_path.unlink()
                stale_alias_removed = True
            if (
                spec.key == SEEDLESS_REGISTRY_ARTIFACT_KEY
                and existing_clean_alias_validation is not None
                and not bool(existing_clean_alias_validation.get("ok"))
            ):
                artifact["message"] = (
                    f"No current {spec.description} discovered under {spec.source_glob}. "
                    f"Existing seedless alias at {repo_relative(alias_path, root)} was not preserved: "
                    f"{existing_clean_alias_validation.get('reason')}. {spec.missing_hint}"
                )
            artifact["alias_exists"] = alias_path.exists() if persist else alias_path.exists()
            artifact["alias_written"] = False
            artifact["stale_alias_removed"] = stale_alias_removed
            artifact["preserved_existing_clean_alias"] = False

        refreshed_artifacts[spec.key] = artifact

    refreshed_errors = [
        str(artifact.get("message") or "")
        for spec in current_step_artifact_specs()
        for artifact in [refreshed_artifacts[spec.key]]
        if not bool(artifact.get("ok"))
    ]
    refreshed = {
        **status,
        "ok": not refreshed_errors,
        "errors": refreshed_errors,
        "persisted": persist,
        "artifacts": refreshed_artifacts,
    }

    if persist:
        seedless_alias_path = alias_paths[SEEDLESS_REGISTRY_ARTIFACT_KEY]
        seedless_artifact = refreshed_artifacts.get(SEEDLESS_REGISTRY_ARTIFACT_KEY) or {}
        if bool(seedless_artifact.get("alias_exists")):
            seedless_pointer_path.write_text(
                repo_relative(seedless_alias_path, root) + "\n",
                encoding="utf-8",
            )
        elif seedless_pointer_path.exists():
            seedless_pointer_path.unlink()
        status_path.write_text(json.dumps(refreshed, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    return refreshed
