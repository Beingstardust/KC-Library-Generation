from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from kc_l.runtime.layout import ensure_operator_layout, is_effectively_empty, list_visible_children
from kc_l.runtime.library_state import load_active_library_pointer
from kc_l.runtime.main_quest_config import validate_main_quest_config_mode
from kc_l.runtime.schema_profiles import (
    build_merged_schema_profile,
    default_extension_template_path,
    default_locked_core_path,
)


HISTORICAL_SURFACES = (
    "archive",
    "logs",
    "manual_backups",
    "data/cache",
    "data/processed",
    "data/raw",
    "data/review_inputs",
    "data/reranker_models",
    "CURRENT_ACTIVE_STATE.md",
    "CURRENT_KNOWLEDGE_LIBRARY_PILOT_RELEASE.md",
    "Current.md",
    "Target design.md",
    "STEP6_SCHEMA_LINEAGE.md",
    "data_mining_kc_hierarchy.json",
)
LEGACY_EXECUTION_AUTHORITY_DOCS = (
    "PROJECT_STATE/MAIN_QUEST_EXECUTION_AUTHORIZATION.md",
    "PROJECT_STATE/MAIN_QUEST_ENTRY_CONTRACT.md",
    "PROJECT_STATE/MAIN_QUEST_PREFLIGHT_RECIPE.md",
    "PROJECT_STATE/KC_SEMANTIC_GATING_POLICY_FROM_SIDEQUEST.md",
    "PROJECT_STATE/REPO_GROUNDED_MASTER_DOSSIER.md",
)
LEGACY_MAIN_QUEST_RESOURCES = (
    "steps/step_06_main_quest_execution/resources/step6_main_quest_v1.base.yaml",
    "steps/step_06_main_quest_execution/resources/step6_main_quest_v1.local_gpu.yaml",
    "steps/step_06_main_quest_execution/resources/step6_main_quest_v1.hpc_gpu.yaml",
)
LEGACY_ROOT_STEP67_LAUNCHER = "run_step6_7_model_draft_generation.py"
LEGACY_ROOT_YAML_PATTERNS = (
    "step6_6_*.yaml",
    "step6_7_*.yaml",
    "step6_8_*.yaml",
)
REQUIRED_DOCS = (
    "README.md",
    "docs/architecture/operator_repo.md",
    "docs/architecture/schema_model.md",
    "docs/workflows/offline_generation_lifecycle.md",
    "docs/workflows/hpc_first_run_preparation.md",
    "docs/supervisor_overview/operator_repo_overview.md",
)
REQUIRED_SCRIPTS = (
    "scripts/local/run_stage.py",
    "scripts/local/run_corpus_intake.py",
    "scripts/hpc/render_main_quest_config.py",
    "scripts/maintenance/check_operator_repo.py",
)
REQUIRED_CONFIGS = (
    "configs/pipeline/main_quest.base.yaml",
    "configs/pipeline/main_quest.local_gpu.example.yaml",
    "configs/pipeline/main_quest.hpc_gpu.example.yaml",
    "configs/pipeline/review.default.yaml",
    "configs/pipeline/freeze.default.yaml",
    "configs/schemas/default/core_schema.locked.json",
    "configs/schemas/examples/extension_schema.template.json",
    "configs/schemas/examples/extension_schema.textbook_example.json",
    "configs/hpc/runtime_storage.template.yaml",
    "configs/hpc/slurm_textbook_first_run.template.sh",
)
INPUT_SURFACE_METADATA = {".gitkeep", "README.md"}


@dataclass(frozen=True)
class StageDefinition:
    key: str
    title: str
    description: str
    operator_command: str
    internal_surfaces: tuple[str, ...]

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


STAGES = (
    StageDefinition(
        key="intake",
        title="Source Preparation And Ingest",
        description="Operator-shell readiness and discoverability for the cross-platform Step 2 corpus-intake bridge into the retained steps tree.",
        operator_command="python scripts/local/run_corpus_intake.py",
        internal_surfaces=(
            "steps/step_01_hierarchy/scripts/01_hierarchy_normalize.py",
            "steps/step_01_5_hierarchy_overlay/scripts/run_step01_5_hierarchy_overlay.py",
            "steps/step_02_pdf_ingest_blockstore/scripts/run_step2.py",
            "steps/step_02_pdf_ingest_blockstore/scripts/run_step2_all.ps1",
            "steps/step_03_doctree_index/scripts/run_step3.py",
        ),
    ),
    StageDefinition(
        key="draft_generation",
        title="Draft Generation",
        description="Operator-shell preflight for the preserved Step 3.5 -> 6.8 draft lane; not a late-stage executor by itself.",
        operator_command="python scripts/local/run_stage.py draft-preflight",
        internal_surfaces=(
            "steps/step_03_5_blockstore_cleanup/scripts/run_step3_5.py",
            "steps/step_03_6_math_salvage/scripts/run_step3_6.py",
            "steps/step_04_structure_retrieval_index/scripts/run_step4.py",
            "steps/step_04_structure_retrieval_index/scripts/run_step4_3.py",
            "steps/step_04_5_sentence_overlay/scripts/run_step4_5.py",
            "steps/step_05_kc_evidence_mining/scripts/run_step5.py",
            "steps/step_05_2_evidence_sharpen/scripts/run_step5_2.py",
            "steps/step_05_3_evidence_recalibrated/scripts/run_step5_3.py",
            "steps/step_06_6_kc_drafting_input_overlay/scripts/run_step6_6_kc_drafting_input_overlay.py",
            "steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py",
            "steps/step_06_8_kc_review_packet_emission/scripts/run_step6_8_kc_review_packet_emission.py",
        ),
    ),
    StageDefinition(
        key="review_resolution",
        title="Review And Resolution",
        description="Operator-shell preflight for the preserved review and resolution lane without widening the approval boundary.",
        operator_command="python scripts/local/run_stage.py review-preflight",
        internal_surfaces=(
            "steps/step_06_9_kc_review_audit_ingestion/scripts/run_step6_9_kc_review_audit_ingestion.py",
            "steps/step_06_10_kc_review_audit_resolution/scripts/run_step6_10_kc_review_audit_resolution.py",
            "steps/step_06_11_reviewed_library_assembly/scripts/run_step6_11_reviewed_library_assembly.py",
        ),
    ),
    StageDefinition(
        key="freeze_package_index",
        title="Freeze, Package, And Index",
        description="Operator-shell preflight for the preserved freeze, packaging, and index lane.",
        operator_command="python scripts/local/run_stage.py freeze-preflight",
        internal_surfaces=(
            "steps/step_06_12_reviewed_library_runtime_packaging/scripts/run_step6_12_reviewed_library_runtime_packaging.py",
            "steps/step_06_13_reviewed_library_retrieval_pilot/scripts/run_step6_13_reviewed_library_retrieval_pilot.py",
            "steps/step_01_8_knowledge_library_access_layer/scripts/run_step01_8_knowledge_library_access_layer.py",
            "steps/step_01_9_knowledge_library_grounding_bridge/scripts/run_step01_9_knowledge_library_grounding_bridge.py",
        ),
    ),
    StageDefinition(
        key="inspection_export_maintenance",
        title="Inspection, Export, And Maintenance",
        description="Inspect operator-shell readiness and discover preserved legacy execution surfaces without claiming full pipeline runnability.",
        operator_command="python scripts/local/run_stage.py status",
        internal_surfaces=(
            "scripts/maintenance/check_operator_repo.py",
            "scripts/hpc/render_main_quest_config.py",
        ),
    ),
)


def stage_catalog_rows() -> list[dict[str, Any]]:
    return [stage.to_row() for stage in STAGES]


def _globbed_root_files(repo_root, pattern: str) -> list[str]:
    return sorted(path.name for path in repo_root.glob(pattern) if path.is_file())


def _build_legacy_execution_surface_inventory(repo_root) -> dict[str, Any]:
    return {
        "execution_authority_docs": [
            path for path in LEGACY_EXECUTION_AUTHORITY_DOCS if (repo_root / path).exists()
        ],
        "main_quest_execution_resources": [
            path for path in LEGACY_MAIN_QUEST_RESOURCES if (repo_root / path).exists()
        ],
        "root_model_backed_step6_7_launcher": LEGACY_ROOT_STEP67_LAUNCHER
        if (repo_root / LEGACY_ROOT_STEP67_LAUNCHER).exists()
        else None,
        "root_yaml_families": {
            pattern: _globbed_root_files(repo_root, pattern) for pattern in LEGACY_ROOT_YAML_PATTERNS
        },
    }


def build_operator_repo_status() -> dict[str, Any]:
    layout = ensure_operator_layout()
    pointer = load_active_library_pointer()
    errors: list[str] = []
    warnings: list[str] = []

    missing_docs = [path for path in REQUIRED_DOCS if not (layout.repo_root / path).exists()]
    missing_scripts = [path for path in REQUIRED_SCRIPTS if not (layout.repo_root / path).exists()]
    missing_configs = [path for path in REQUIRED_CONFIGS if not (layout.repo_root / path).exists()]
    historical_present = [path for path in HISTORICAL_SURFACES if (layout.repo_root / path).exists()]
    legacy_surfaces = _build_legacy_execution_surface_inventory(layout.repo_root)
    missing_legacy_docs = [path for path in LEGACY_EXECUTION_AUTHORITY_DOCS if not (layout.repo_root / path).exists()]
    missing_legacy_resources = [path for path in LEGACY_MAIN_QUEST_RESOURCES if not (layout.repo_root / path).exists()]
    missing_legacy_yaml_families = [
        pattern for pattern, names in legacy_surfaces["root_yaml_families"].items() if not names
    ]

    if missing_docs:
        errors.append(f"Missing required docs: {missing_docs}")
    if missing_scripts:
        errors.append(f"Missing required scripts: {missing_scripts}")
    if missing_configs:
        errors.append(f"Missing required configs: {missing_configs}")
    if historical_present:
        errors.append(f"Historical live surfaces still present: {historical_present}")
    if missing_legacy_docs:
        warnings.append(f"Restored legacy execution-authority docs missing: {missing_legacy_docs}")
    if missing_legacy_resources:
        warnings.append(f"Retained main-quest execution resources missing: {missing_legacy_resources}")
    if legacy_surfaces["root_model_backed_step6_7_launcher"] is None:
        warnings.append("Restored root Step 6.7 model-backed launcher is missing.")
    if missing_legacy_yaml_families:
        warnings.append(f"Restored root Step 6 YAML families missing: {missing_legacy_yaml_families}")

    course_material_files = list_visible_children(layout.course_materials_root, allowed_names=INPUT_SURFACE_METADATA)
    hierarchy_files = list_visible_children(layout.hierarchy_root, allowed_names=INPUT_SURFACE_METADATA)
    run_entries = list_visible_children(layout.runs_root, allowed_names={".gitkeep"})
    frozen_entries = list_visible_children(layout.frozen_library_root, allowed_names={".gitkeep"})

    if course_material_files:
        warnings.append(f"Course materials already present: {course_material_files}")
    if hierarchy_files:
        warnings.append(f"Hierarchy inputs already present: {hierarchy_files}")
    if run_entries:
        errors.append(f"Runs directory is not clean: {run_entries}")
    if frozen_entries and pointer.state != "active":
        errors.append("Frozen library contains entries while the active pointer is still unset.")

    local_config_report = validate_main_quest_config_mode("local_gpu")
    hpc_config_report = validate_main_quest_config_mode("hpc_gpu")
    if not local_config_report["ok"]:
        errors.extend(local_config_report["errors"])
    if not hpc_config_report["ok"]:
        errors.extend(hpc_config_report["errors"])
    warnings.extend(local_config_report["warnings"])
    warnings.extend(hpc_config_report["warnings"])

    try:
        merged_schema = build_merged_schema_profile(default_extension_template_path(), default_locked_core_path())
        merged_field_count = len(merged_schema["merged_field_ids"])
    except Exception as exc:
        errors.append(f"Schema profile validation failed: {exc}")
        merged_field_count = 0

    return {
        "ok": not errors,
        "status_scope": "operator_shell_only",
        "truth_boundary": (
            "This status validates the clean operator shell, input roots, and template/config "
            "surfaces. It does not prove that the full retained legacy pipeline is runnable "
            "end to end."
        ),
        "full_pipeline_runnable_claimed": False,
        "errors": errors,
        "warnings": warnings,
        "layout": {
            "course_materials_root": layout.course_materials_root.as_posix(),
            "hierarchy_root": layout.hierarchy_root.as_posix(),
            "runs_root": layout.runs_root.as_posix(),
            "active_library_pointer": layout.active_library_pointer.as_posix(),
            "frozen_library_root": layout.frozen_library_root.as_posix(),
        },
        "inputs": {
            "course_material_file_count": len(course_material_files),
            "hierarchy_file_count": len(hierarchy_files),
        },
        "runtime_state": {
            "runs_clean": is_effectively_empty(layout.runs_root, allowed_names={".gitkeep"}),
            "frozen_library_clean": is_effectively_empty(layout.frozen_library_root, allowed_names={".gitkeep"}),
            "active_pointer_state": pointer.state,
        },
        "schema_profile": {
            "locked_core_path": default_locked_core_path().as_posix(),
            "extension_template_path": default_extension_template_path().as_posix(),
            "merged_field_count": merged_field_count,
        },
        "configs": {
            "local_gpu": local_config_report,
            "hpc_gpu": hpc_config_report,
        },
        "legacy_execution_surfaces": legacy_surfaces,
    }


def build_stage_preflight(stage_key: str) -> dict[str, Any]:
    status = build_operator_repo_status()
    stage = next((item for item in STAGES if item.key == stage_key), None)
    if stage is None:
        raise ValueError(f"Unknown stage: {stage_key}")

    input_counts = status["inputs"]
    course_materials_present = input_counts["course_material_file_count"] > 0
    hierarchy_present = input_counts["hierarchy_file_count"] > 0
    support_ready = status["ok"]
    ready_for_first_run = support_ready and course_materials_present and hierarchy_present
    blocking_conditions: list[str] = []

    if not support_ready:
        blocking_conditions.extend(status["errors"])
    if stage_key in {"intake", "draft_generation"}:
        if not course_materials_present:
            blocking_conditions.append("No course materials have been added to data/input/course_materials yet.")
        if not hierarchy_present:
            blocking_conditions.append("No hierarchy input has been added to data/input/hierarchy yet.")
    if stage_key == "review_resolution":
        blocking_conditions.append("No fresh review packet bundle exists yet in this clean repo.")
    if stage_key == "freeze_package_index":
        blocking_conditions.append("No approved frozen library exists yet in this clean repo.")

    next_actions = {
        "intake": [
            "Add source PDFs to data/input/course_materials.",
            "Add a hierarchy JSON or YAML file to data/input/hierarchy.",
            "Run python scripts/local/run_corpus_intake.py locally or python3 scripts/local/run_corpus_intake.py on the HPC cluster (Linux) to ingest every PDF in data/input/course_materials.",
            "Use steps/step_02_pdf_ingest_blockstore/scripts/run_step2_all.ps1 only as a repaired Windows legacy helper.",
            "Run python steps/step_03_doctree_index/scripts/run_step3.py --config steps/step_03_doctree_index/resources/step3.default.yaml after Step 2 completes.",
            "Treat this preflight as operator-shell readiness only; downstream execution still continues in the preserved steps/ tree.",
        ],
        "draft_generation": [
            "Read PROJECT_STATE/MAIN_QUEST_EXECUTION_AUTHORIZATION.md and PROJECT_STATE/MAIN_QUEST_PREFLIGHT_RECIPE.md before late-stage execution.",
            "Use the retained steps/ lane for the preserved Step 3.5 -> 6.8 flow.",
            "Use python run_step6_7_model_draft_generation.py --config step6_7_full128_model_rewrite_2026-03-27.yaml when the restored model-backed Step 6.7 launcher is the intended surface.",
            "Review the restored root step6_6_*.yaml, step6_7_*.yaml, and step6_8_*.yaml family before late-stage execution.",
        ],
        "review_resolution": [
            "Generate new review packets first.",
            "Capture reviewer decisions as approve, edit_and_approve, or reject only.",
            "Treat this preflight as operator-shell readiness only; the preserved review lane still lives in the retained steps/ tree.",
        ],
        "freeze_package_index": [
            "Freeze only approved outputs.",
            "Update data/library/active/knowledge_library_release_pointer.json after a real frozen bundle exists.",
            "Treat this preflight as operator-shell readiness only; it does not certify that the preserved freeze/index lane has already been executed.",
        ],
        "inspection_export_maintenance": [
            "Use scripts/maintenance/check_operator_repo.py to verify clean operator-shell state.",
            "Use scripts/hpc/render_main_quest_config.py for HPC preparation only.",
            "Use PROJECT_STATE/ and the restored root Step 6.7 launcher family when you need late-stage legacy execution authority.",
        ],
    }

    return {
        "stage_key": stage.key,
        "title": stage.title,
        "description": stage.description,
        "operator_command": stage.operator_command,
        "status_scope": "operator_shell_only",
        "truth_boundary": (
            "This preflight reports operator-shell readiness only. It does not certify that the "
            "full retained legacy step ladder or late-stage launchers are runnable end to end."
        ),
        "full_pipeline_runnable_claimed": False,
        "internal_surfaces": list(stage.internal_surfaces),
        "support_ready": support_ready,
        "ready_for_first_run": ready_for_first_run,
        "blocking_conditions": blocking_conditions,
        "next_actions": next_actions[stage.key],
        "legacy_execution_surfaces": status["legacy_execution_surfaces"],
    }
