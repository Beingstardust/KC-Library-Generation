from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_SRC = REPO_ROOT / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from kc_l.audit.manifests import build_input_manifest, build_output_manifest, env_snapshot, try_cmd_version
from kc_l.kc.restarted_packet_failure_audit import assemble_restarted_packet_failure_audit
from kc_l.utils.json_io import read_json, write_json


DEFAULT_CONFIG = Path("steps/step_06_14_kc_packet_failure_audit/resources/step6_14.slice48.yaml")


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
    root = base_dir if base_dir is not None else REPO_ROOT
    return (root / candidate).resolve()


def rel_path(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()


def choose_run_paths(processed_root: Path, runs_root: Path, sets_root: Path) -> Dict[str, Path]:
    base_stamp = utc_stamp()
    suffix = 0
    while True:
        run_id = base_stamp if suffix == 0 else f"{base_stamp}_{suffix:02d}"
        audit_dir = (runs_root / f"{run_id}_step6_14").resolve()
        output_dir = (processed_root / run_id).resolve()
        registry_set = (sets_root / f"{run_id}_step6_14_packet_cohort_registry_restarted_set.json").resolve()
        matrix_set = (sets_root / f"{run_id}_step6_14_packet_failure_matrix_restarted_set.json").resolve()
        dossier_set = (sets_root / f"{run_id}_step6_14_packet_dossiers_restarted_set.json").resolve()
        summary_set = (sets_root / f"{run_id}_step6_14_packet_failure_summary_restarted_set.json").resolve()
        if not audit_dir.exists() and not output_dir.exists() and not registry_set.exists() and not matrix_set.exists() and not dossier_set.exists() and not summary_set.exists():
            return {
                "run_id": Path(run_id),
                "audit_dir": audit_dir,
                "output_dir": output_dir,
                "registry_set": registry_set,
                "matrix_set": matrix_set,
                "dossier_set": dossier_set,
                "summary_set": summary_set,
            }
        suffix += 1


def copy_config_snapshot(config_path: Path, audit_dir: Path) -> Path:
    target = audit_dir / "config_snapshot.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(config_path, target)
    return target


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a compact packet-failure audit bundle for the repaired restarted slice48 packet surface.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = resolve_repo_path(args.config)
    cfg = load_yaml_or_json(config_path)
    input_cfg = dict(cfg.get("inputs") or {})
    output_cfg = dict(cfg.get("outputs") or {})

    processed_root = resolve_repo_path(output_cfg.get("processed_root") or "data/processed/kc_packet_failure_audit_restarted")
    sets_root = resolve_repo_path(output_cfg.get("sets_root") or "data/processed/kc_packet_failure_audit_restarted/_sets")
    runs_root = resolve_repo_path(output_cfg.get("runs_root") or "data/runs")
    review_packet_path = resolve_repo_path(input_cfg.get("review_packet_jsonl"))
    review_packet_summary_path = resolve_repo_path(input_cfg.get("review_packet_summary_json"))
    real_reviewer_session_path = resolve_repo_path(input_cfg.get("real_reviewer_session_md"))
    human_actions_path = resolve_repo_path(input_cfg.get("human_supervised_draft_actions_json"))
    reviewer_verdicts_path = resolve_repo_path(input_cfg.get("reviewer_dry_run_verdicts_json"))
    review_audit_path = resolve_repo_path(input_cfg.get("review_audit_jsonl"))
    review_audit_summary_path = resolve_repo_path(input_cfg.get("review_audit_summary_json"))
    resolved_audit_path = resolve_repo_path(input_cfg.get("resolved_audit_jsonl"))
    resolved_audit_summary_path = resolve_repo_path(input_cfg.get("resolved_audit_summary_json"))
    frozen_reviewed_library_path = resolve_repo_path(input_cfg.get("frozen_reviewed_library_jsonl"))
    reviewed_library_summary_path = resolve_repo_path(input_cfg.get("reviewed_library_summary_json"))
    sandbox_path = resolve_repo_path(input_cfg.get("sandbox_jsonl"))
    sandbox_summary_path = resolve_repo_path(input_cfg.get("sandbox_summary_json"))
    runtime_library_path = resolve_repo_path(input_cfg.get("runtime_kc_library_jsonl"))
    retrieval_source_path = resolve_repo_path(input_cfg.get("retrieval_source_jsonl"))
    retrieval_validation_results_path = resolve_repo_path(input_cfg.get("retrieval_validation_results_json"))
    retrieval_assessment_path = resolve_repo_path(input_cfg.get("retrieval_pilot_assessment_md"))
    step6_7_draft_path = resolve_repo_path(input_cfg.get("step6_7_draft_jsonl"))
    step6_7_stats_path = resolve_repo_path(input_cfg.get("step6_7_draft_stats_json"))
    step6_6_overlay_path = resolve_repo_path(input_cfg.get("step6_6_overlay_jsonl"))
    step6_6_stats_path = resolve_repo_path(input_cfg.get("step6_6_overlay_stats_json"))

    run_paths = choose_run_paths(processed_root, runs_root, sets_root)
    run_id = str(run_paths["run_id"])
    audit_dir = run_paths["audit_dir"]
    output_dir = run_paths["output_dir"]
    registry_set_path = run_paths["registry_set"]
    matrix_set_path = run_paths["matrix_set"]
    dossier_set_path = run_paths["dossier_set"]
    summary_set_path = run_paths["summary_set"]

    output_dir.mkdir(parents=True, exist_ok=False)
    audit_dir.mkdir(parents=True, exist_ok=False)
    sets_root.mkdir(parents=True, exist_ok=True)
    config_snapshot_path = copy_config_snapshot(config_path, audit_dir)

    result = assemble_restarted_packet_failure_audit(
        review_packet_path=review_packet_path,
        review_packet_summary_path=review_packet_summary_path,
        review_audit_path=review_audit_path,
        review_audit_summary_path=review_audit_summary_path,
        resolved_audit_path=resolved_audit_path,
        resolved_audit_summary_path=resolved_audit_summary_path,
        frozen_reviewed_library_path=frozen_reviewed_library_path,
        reviewed_library_summary_path=reviewed_library_summary_path,
        sandbox_path=sandbox_path,
        sandbox_summary_path=sandbox_summary_path,
        runtime_library_path=runtime_library_path,
        retrieval_source_path=retrieval_source_path,
        retrieval_validation_results_path=retrieval_validation_results_path,
        step6_7_draft_path=step6_7_draft_path,
        output_dir=output_dir,
    )

    registry_summary = read_json(result.registry_summary_path)
    matrix_summary = read_json(result.matrix_summary_path)
    aggregate_summary = read_json(result.aggregate_summary_json_path)

    input_manifest = build_input_manifest([
        config_path,
        review_packet_path,
        review_packet_summary_path,
        real_reviewer_session_path,
        human_actions_path,
        reviewer_verdicts_path,
        review_audit_path,
        review_audit_summary_path,
        resolved_audit_path,
        resolved_audit_summary_path,
        frozen_reviewed_library_path,
        reviewed_library_summary_path,
        sandbox_path,
        sandbox_summary_path,
        runtime_library_path,
        retrieval_source_path,
        retrieval_validation_results_path,
        retrieval_assessment_path,
        step6_7_draft_path,
        step6_7_stats_path,
        step6_6_overlay_path,
        step6_6_stats_path,
    ])
    write_json(audit_dir / "input_manifest.json", input_manifest)

    summary = {
        "run_id": run_id,
        "created_utc": now_utc_iso(),
        "packet_surface": rel_path(review_packet_path),
        "stats": {
            "registry_record_count": registry_summary.get("record_count"),
            "failure_matrix_row_count": matrix_summary.get("row_count"),
            "final_outcome_counts": registry_summary.get("final_outcome_counts"),
            "tentative_stage_counts": matrix_summary.get("tentative_stage_counts"),
        },
        "env": env_snapshot(),
        "tool_versions": {"python": try_cmd_version([sys.executable, "--version"])}
    }
    write_json(audit_dir / "summary.json", summary)

    registry_set = {
        "schema_version": "1.0",
        "kind": "step6_14_packet_cohort_registry_restarted_set",
        "set_id": f"{run_id}_step6_14_packet_cohort_registry_restarted_set",
        "created_utc": now_utc_iso(),
        "run_id_step6_14": run_id,
        "artifacts": {
            "packet_cohort_registry_jsonl": rel_path(result.registry_path),
            "packet_cohort_registry_summary_json": rel_path(result.registry_summary_path),
            "packet_cohort_registry_preview_md": rel_path(result.registry_preview_path),
        },
        "upstream": {"review_packet_jsonl": rel_path(review_packet_path), "review_audit_jsonl": rel_path(review_audit_path), "resolved_audit_jsonl": rel_path(resolved_audit_path)},
        "audit": {"run_dir": rel_path(audit_dir), "config_snapshot": rel_path(config_snapshot_path), "input_manifest": rel_path(audit_dir / "input_manifest.json"), "summary": rel_path(audit_dir / "summary.json"), "output_manifest": rel_path(audit_dir / "output_manifest.json")},
    }
    write_json(registry_set_path, registry_set)
    matrix_set = {
        "schema_version": "1.0",
        "kind": "step6_14_packet_failure_matrix_restarted_set",
        "set_id": f"{run_id}_step6_14_packet_failure_matrix_restarted_set",
        "created_utc": now_utc_iso(),
        "run_id_step6_14": run_id,
        "artifacts": {
            "packet_failure_matrix_jsonl": rel_path(result.matrix_path),
            "packet_failure_matrix_summary_json": rel_path(result.matrix_summary_path),
            "packet_failure_matrix_preview_md": rel_path(result.matrix_preview_path),
        },
        "upstream": {"packet_cohort_registry_set_manifest_json": rel_path(registry_set_path), "sandbox_jsonl": rel_path(sandbox_path), "retrieval_source_jsonl": rel_path(retrieval_source_path)},
        "audit": {"run_dir": rel_path(audit_dir), "summary": rel_path(audit_dir / "summary.json"), "output_manifest": rel_path(audit_dir / "output_manifest.json")},
    }
    write_json(matrix_set_path, matrix_set)

    dossier_set = {
        "schema_version": "1.0",
        "kind": "step6_14_packet_dossiers_restarted_set",
        "set_id": f"{run_id}_step6_14_packet_dossiers_restarted_set",
        "created_utc": now_utc_iso(),
        "run_id_step6_14": run_id,
        "artifacts": {
            "representative_packet_dossiers_json": rel_path(result.dossiers_json_path),
            "representative_packet_dossiers_md": rel_path(result.dossiers_md_path),
        },
        "upstream": {"packet_cohort_registry_set_manifest_json": rel_path(registry_set_path), "packet_failure_matrix_set_manifest_json": rel_path(matrix_set_path)},
        "audit": {"run_dir": rel_path(audit_dir), "summary": rel_path(audit_dir / "summary.json"), "output_manifest": rel_path(audit_dir / "output_manifest.json")},
    }
    write_json(dossier_set_path, dossier_set)

    summary_set = {
        "schema_version": "1.0",
        "kind": "step6_14_packet_failure_summary_restarted_set",
        "set_id": f"{run_id}_step6_14_packet_failure_summary_restarted_set",
        "created_utc": now_utc_iso(),
        "run_id_step6_14": run_id,
        "artifacts": {
            "packet_failure_audit_summary_json": rel_path(result.aggregate_summary_json_path),
            "packet_failure_audit_report_md": rel_path(result.aggregate_report_md_path),
        },
        "upstream": {"packet_cohort_registry_set_manifest_json": rel_path(registry_set_path), "packet_failure_matrix_set_manifest_json": rel_path(matrix_set_path), "packet_dossiers_set_manifest_json": rel_path(dossier_set_path)},
        "audit": {"run_dir": rel_path(audit_dir), "summary": rel_path(audit_dir / "summary.json"), "output_manifest": rel_path(audit_dir / "output_manifest.json")},
    }
    write_json(summary_set_path, summary_set)

    output_manifest = {
        "processed_outputs": build_output_manifest(output_dir),
        "audit_outputs": build_output_manifest(audit_dir),
        "set_manifests": {
            "registry": {"path": rel_path(registry_set_path)},
            "matrix": {"path": rel_path(matrix_set_path)},
            "dossiers": {"path": rel_path(dossier_set_path)},
            "summary": {"path": rel_path(summary_set_path)},
        },
    }
    write_json(audit_dir / "output_manifest.json", output_manifest)

    print(json.dumps({
        "run_id": run_id,
        "output_dir": rel_path(output_dir),
        "registry_record_count": registry_summary.get("record_count"),
        "failure_matrix_row_count": matrix_summary.get("row_count"),
        "final_outcome_counts": registry_summary.get("final_outcome_counts"),
        "dossier_count": aggregate_summary.get("dossier_count"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
