from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from kc_l.runtime.stage_config import render_stage_config
from kc_l.runtime.stage_pointers import resolve_pointer
from kc_l.utils.json_io import read_json

BASE_CONFIG_PATH = Path("steps/step_05_p_kc_retrieval_profile/resources/step5p.hpc.production_gemma4_31b.yaml")


def _resolve_repo_path(path_spec: str | Path, *, repo_root: Path) -> Path:
    path = Path(str(path_spec))
    if path.is_absolute():
        return path
    return (repo_root / path).resolve()


def read_hierarchy_overlay_jsonl(overlay_manifest_obj: Mapping[str, Any]) -> str:
    """Read the final hierarchy overlay artifact path from a step 01.5 manifest.

    Step 5p consumes the *overlay* JSONL, not step 01's intermediate normalized registry.
    The stable contract in the real overlay manifests is artifacts.hierarchy_overlay_jsonl.
    A top-level fallback is accepted defensively for verification-era fixtures.
    """
    artifacts = overlay_manifest_obj.get("artifacts")
    if isinstance(artifacts, Mapping) and "hierarchy_overlay_jsonl" in artifacts:
        return str(artifacts["hierarchy_overlay_jsonl"])
    if "hierarchy_overlay_jsonl" in overlay_manifest_obj:
        return str(overlay_manifest_obj["hierarchy_overlay_jsonl"])
    raise KeyError(
        "hierarchy_overlay_jsonl not found in overlay manifest at either "
        "artifacts.hierarchy_overlay_jsonl or the top level"
    )


def resolve_hierarchy_overlay_jsonl_from_output_root(
    *,
    repo_root: Path,
    hierarchy_output_root: Path,
) -> Path:
    overlay_manifest_path = hierarchy_output_root / "overlay_manifest.json"
    if not overlay_manifest_path.exists():
        nested_matches = sorted(hierarchy_output_root.glob("*/overlay_manifest.json"))
        if len(nested_matches) == 1:
            overlay_manifest_path = nested_matches[0]
        elif not nested_matches:
            raise FileNotFoundError(
                "Hierarchy overlay manifest not found at either the stage output root or a "
                f"single nested run dir: {hierarchy_output_root}"
            )
        else:
            raise FileNotFoundError(
                "Expected exactly one nested hierarchy overlay manifest under "
                f"{hierarchy_output_root}, found {len(nested_matches)}: {nested_matches}"
            )
    overlay_manifest = read_json(overlay_manifest_path)
    hierarchy_overlay_jsonl = read_hierarchy_overlay_jsonl(overlay_manifest)
    return _resolve_repo_path(hierarchy_overlay_jsonl, repo_root=repo_root)


def resolve_sentence_overlay_jsonl_from_output_root(
    *,
    repo_root: Path,
    sentence_overlay_output_root: Path,
) -> Path:
    """Resolve step_04_5's real current-run sentence_corpus.jsonl via its own self-written
    ACTIVE_STEP4_5_SET.txt pointer, not a flat-file assumption.

    CONFIRMED BUG (see ORCHESTRATOR_BUILD_STATE.md's "step_05p final flip-and-verify pass"):
    the real run_step4_5.py (via its own choose_run_paths()) nests sentence_corpus.jsonl one
    level deeper, under its own internally-generated timestamp run_id - it is never flat at
    sentence_overlay_output_root, the same internal-run_id pattern already documented for step
    6.6/6.9-6.13/step_04_patches/step_04_3. Confirmed by actually running the real runner
    against a real chain state, not by inspection alone.

    Fix: read the stage's own ACTIVE_STEP4_5_SET.txt pointer (confirmed real path/format by
    reading run_step4_5.py's own pointer-writing code directly: a legacy filename-only pointer
    at <output_root>/_sets/ACTIVE_STEP4_5_SET.txt, the same "_sets" convention every other wired
    stage uses) via the shared stage_pointers.resolve_pointer() - the same pointer-resolution
    mechanism the rest of this orchestrator already uses, rather than reimplementing it - to
    find the set manifest run_step4_5.py itself just wrote, then reads that manifest's own
    artifacts.sentence_corpus_jsonl field (confirmed the real field name by reading
    run_step4_5.py's set_manifest dict directly - a repo-relative path). This uses the stage's
    own declared output location rather than inferring one, so it stays correct regardless of
    exactly how deep run_step4_5.py happens to nest its own internal run directory.
    """
    active_pointer_path = sentence_overlay_output_root / "_sets" / "ACTIVE_STEP4_5_SET.txt"
    set_manifest_path = resolve_pointer(active_pointer_path, repo_root=repo_root)
    set_manifest = read_json(set_manifest_path)

    artifacts = set_manifest.get("artifacts")
    if not isinstance(artifacts, Mapping) or "sentence_corpus_jsonl" not in artifacts:
        raise KeyError(
            "artifacts.sentence_corpus_jsonl not found in step_04_5 set manifest: "
            f"{set_manifest_path}"
        )
    sentence_overlay_jsonl = _resolve_repo_path(artifacts["sentence_corpus_jsonl"], repo_root=repo_root)
    if not sentence_overlay_jsonl.exists():
        raise FileNotFoundError(f"Sentence overlay JSONL not found: {sentence_overlay_jsonl}")
    return sentence_overlay_jsonl


def build_step5p_run_config(
    *,
    run_id: str,
    repo_root: Path,
    run_dir: Path,
    hierarchy_output_root: Path,
    sentence_overlay_output_root: Path,
    base_config_path: Path | None = None,
) -> Path:
    """Render a per-run Step 5p config from current-run upstream artifacts.

    This intentionally has no historical fallback path baked into it. The caller must provide
    the hierarchy stage output root and the step 4.5 output root for the *current* run chain.
    Historical paths are only appropriate when a verification script explicitly supplies them.

    base_config_path (2026-07-30, ablation studies): optional override for the base YAML this
    run's config is rendered from - defaults to BASE_CONFIG_PATH (the production
    gemma4:31b config) when omitted, so every existing caller and the production baseline stay
    byte-identical. Lets an ablation study (e.g. a step5p run swapped to a different model)
    supply its own standalone, self-documented base YAML - mirroring the production file's own
    structure - without touching BASE_CONFIG_PATH or any shared production file.
    """
    run_dir.mkdir(parents=True, exist_ok=True)

    registry_jsonl = resolve_hierarchy_overlay_jsonl_from_output_root(
        repo_root=repo_root,
        hierarchy_output_root=hierarchy_output_root,
    )
    source_overlay_jsonl = resolve_sentence_overlay_jsonl_from_output_root(
        repo_root=repo_root,
        sentence_overlay_output_root=sentence_overlay_output_root
    )

    overrides = {
        "inputs": {
            "registry_jsonl": str(registry_jsonl),
            "source_overlay_jsonl": str(source_overlay_jsonl),
        },
    }
    rendered_config_path = run_dir / f"{run_id}_step_05p_config.json"
    resolved_base_config_path = (
        repo_root / base_config_path if base_config_path is not None else repo_root / BASE_CONFIG_PATH
    )
    render_stage_config(resolved_base_config_path, overrides, rendered_config_path)
    return rendered_config_path
