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
from kc_l.kc.exchange_matching_pilot import assemble_exchange_matching_pilot
from kc_l.utils.json_io import read_json, write_json


DEFAULT_CONFIG = Path("steps/step_06_exchange_matching_pilot/resources/exchange_matching_pilot.slice48_accepted.yaml")


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
        pilot_dir = (processed_root / run_id).resolve()
        audit_dir = (runs_root / f"{run_id}_exchange_matching_pilot").resolve()
        input_set_path = (sets_root / f"{run_id}_exchange_pilot_input_set.json").resolve()
        retrieval_set_path = (sets_root / f"{run_id}_exchange_pilot_retrieval_set.json").resolve()
        assignment_set_path = (sets_root / f"{run_id}_exchange_pilot_assignment_set.json").resolve()
        if not pilot_dir.exists() and not audit_dir.exists() and not input_set_path.exists() and not retrieval_set_path.exists() and not assignment_set_path.exists():
            return {
                "run_id": Path(run_id),
                "pilot_dir": pilot_dir,
                "audit_dir": audit_dir,
                "input_set_path": input_set_path,
                "retrieval_set_path": retrieval_set_path,
                "assignment_set_path": assignment_set_path,
            }
        suffix += 1


def copy_config_snapshot(config_path: Path, audit_dir: Path) -> Path:
    target = audit_dir / "config_snapshot.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(config_path, target)
    return target


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the bounded exchange-level KC matching pilot on the accepted reviewed/runtime slice48 baseline.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = resolve_repo_path(args.config)
    cfg = load_yaml_or_json(config_path)

    input_cfg = dict(cfg.get("inputs") or {})
    output_cfg = dict(cfg.get("outputs") or {})
    pilot_cfg = dict(cfg.get("pilot") or {})

    processed_root = resolve_repo_path(output_cfg.get("processed_root") or "data/processed/kc_exchange_matching_pilot_restarted")
    sets_root = resolve_repo_path(output_cfg.get("sets_root") or "data/processed/kc_exchange_matching_pilot_restarted/_sets")
    runs_root = resolve_repo_path(output_cfg.get("runs_root") or "data/runs")

    step6_11_set_path = resolve_repo_path(input_cfg.get("step6_11_set_manifest"))
    step6_12_set_path = resolve_repo_path(input_cfg.get("step6_12_set_manifest"))
    retrieval_source_set_path = resolve_repo_path(input_cfg.get("retrieval_source_set_manifest"))
    retrieval_index_set_path = resolve_repo_path(input_cfg.get("retrieval_index_set_manifest"))

    step6_11_set_obj = read_json(step6_11_set_path)
    step6_12_set_obj = read_json(step6_12_set_path)
    retrieval_source_set_obj = read_json(retrieval_source_set_path)
    retrieval_index_set_obj = read_json(retrieval_index_set_path)

    source_step6_11_set_id = str(step6_11_set_obj.get("set_id") or step6_11_set_path.stem)
    source_step6_12_set_id = str(step6_12_set_obj.get("set_id") or step6_12_set_path.stem)
    retrieval_source_set_id = str(retrieval_source_set_obj.get("set_id") or retrieval_source_set_path.stem)
    retrieval_index_set_id = str(retrieval_index_set_obj.get("set_id") or retrieval_index_set_path.stem)

    retrieval_source_path = resolve_repo_path((retrieval_source_set_obj.get("artifacts") or {}).get("reviewed_retrieval_source_jsonl"))
    retrieval_index_path = resolve_repo_path((retrieval_index_set_obj.get("artifacts") or {}).get("reviewed_retrieval_index_json"))
    runtime_library_path = resolve_repo_path((step6_12_set_obj.get("artifacts") or {}).get("runtime_kc_library_jsonl"))
    reviewed_library_path = resolve_repo_path((step6_11_set_obj.get("artifacts") or {}).get("frozen_reviewed_library_jsonl"))

    top_k = int(pilot_cfg.get("top_k") or 5)

    run_paths = choose_run_paths(processed_root, runs_root, sets_root)
    run_id = str(run_paths["run_id"])
    pilot_dir = run_paths["pilot_dir"]
    audit_dir = run_paths["audit_dir"]
    input_set_path = run_paths["input_set_path"]
    retrieval_set_path = run_paths["retrieval_set_path"]
    assignment_set_path = run_paths["assignment_set_path"]
    pilot_dir.mkdir(parents=True, exist_ok=False)
    audit_dir.mkdir(parents=True, exist_ok=False)
    sets_root.mkdir(parents=True, exist_ok=True)

    config_snapshot_path = copy_config_snapshot(config_path, audit_dir)

    result = assemble_exchange_matching_pilot(
        retrieval_source_path=retrieval_source_path,
        retrieval_index_path=retrieval_index_path,
        output_dir=pilot_dir,
        source_reviewed_set_id=source_step6_11_set_id,
        source_runtime_set_id=source_step6_12_set_id,
        retrieval_source_set_id=retrieval_source_set_id,
        retrieval_index_set_id=retrieval_index_set_id,
        top_k=top_k,
    )

    retrieval_summary = read_json(result.retrieval_summary_path)
    assignment_summary = read_json(result.assignment_summary_path)
    assessment_summary = read_json(result.assessment_summary_path)

    input_manifest = build_input_manifest(
        [
            config_path,
            step6_11_set_path,
            step6_12_set_path,
            retrieval_source_set_path,
            retrieval_index_set_path,
            reviewed_library_path,
            runtime_library_path,
            retrieval_source_path,
            retrieval_index_path,
        ]
    )
    write_json(audit_dir / "input_manifest.json", input_manifest)

    summary = {
        "run_id": run_id,
        "created_utc": now_utc_iso(),
        "source_step6_11_set_id": source_step6_11_set_id,
        "source_step6_12_set_id": source_step6_12_set_id,
        "retrieval_source_set_id": retrieval_source_set_id,
        "retrieval_index_set_id": retrieval_index_set_id,
        "retrieval_source_jsonl": rel_path(retrieval_source_path),
        "retrieval_index_json": rel_path(retrieval_index_path),
        "stats": {
            "exchange_count": result.exchange_count,
            "top_k": top_k,
            "label_counts": dict(assignment_summary.get("label_counts") or {}),
            "same_parent_collision_exchange_ids": list(retrieval_summary.get("same_parent_collision_exchange_ids") or []),
            "bounded_ready_answer": str((assessment_summary.get("q4_good_enough_for_bounded_next_segmentation") or {}).get("answer") or ""),
        },
        "env": env_snapshot(),
        "tool_versions": {
            "python": try_cmd_version([sys.executable, "--version"]),
        },
    }
    write_json(audit_dir / "summary.json", summary)

    input_set_manifest = {
        "schema_version": "1.0",
        "kind": "exchange_pilot_input_set",
        "set_id": f"{run_id}_exchange_pilot_input_set",
        "created_utc": now_utc_iso(),
        "run_id_exchange_matching": run_id,
        "artifacts": {
            "exchange_unit_pilot_input_json": rel_path(result.input_path),
        },
        "upstream": {
            "step6_11_set_manifest_json": rel_path(step6_11_set_path),
            "step6_12_set_manifest_json": rel_path(step6_12_set_path),
            "reviewed_retrieval_source_set_manifest_json": rel_path(retrieval_source_set_path),
            "reviewed_retrieval_index_set_manifest_json": rel_path(retrieval_index_set_path),
        },
        "slice": {
            "exchange_count": result.exchange_count,
            "top_k": top_k,
        },
        "audit": {
            "run_dir": rel_path(audit_dir),
            "config_snapshot": rel_path(config_snapshot_path),
            "input_manifest": rel_path(audit_dir / "input_manifest.json"),
            "summary": rel_path(audit_dir / "summary.json"),
            "output_manifest": rel_path(audit_dir / "output_manifest.json"),
        },
    }
    write_json(input_set_path, input_set_manifest)

    retrieval_set_manifest = {
        "schema_version": "1.0",
        "kind": "exchange_pilot_retrieval_set",
        "set_id": f"{run_id}_exchange_pilot_retrieval_set",
        "created_utc": now_utc_iso(),
        "run_id_exchange_matching": run_id,
        "artifacts": {
            "exchange_topk_retrieval_results_json": rel_path(result.retrieval_results_path),
            "exchange_topk_retrieval_summary_json": rel_path(result.retrieval_summary_path),
        },
        "upstream": {
            "exchange_pilot_input_set_manifest_json": rel_path(input_set_path),
            "reviewed_retrieval_source_set_manifest_json": rel_path(retrieval_source_set_path),
            "reviewed_retrieval_index_set_manifest_json": rel_path(retrieval_index_set_path),
        },
        "slice": {
            "exchange_count": result.exchange_count,
            "same_parent_collision_exchange_ids": list(retrieval_summary.get("same_parent_collision_exchange_ids") or []),
            "exchange_ids_with_zero_hits": list(retrieval_summary.get("exchange_ids_with_zero_hits") or []),
        },
        "audit": {
            "run_dir": rel_path(audit_dir),
            "summary": rel_path(audit_dir / "summary.json"),
            "output_manifest": rel_path(audit_dir / "output_manifest.json"),
        },
    }
    write_json(retrieval_set_path, retrieval_set_manifest)

    assignment_set_manifest = {
        "schema_version": "1.0",
        "kind": "exchange_pilot_assignment_set",
        "set_id": f"{run_id}_exchange_pilot_assignment_set",
        "created_utc": now_utc_iso(),
        "run_id_exchange_matching": run_id,
        "artifacts": {
            "exchange_assignment_results_json": rel_path(result.assignment_results_path),
            "exchange_assignment_summary_json": rel_path(result.assignment_summary_path),
            "exchange_matching_preview_md": rel_path(result.preview_path),
            "pilot_assessment_summary_json": rel_path(result.assessment_summary_path),
            "pilot_assessment_md": rel_path(result.assessment_path),
        },
        "upstream": {
            "exchange_pilot_input_set_manifest_json": rel_path(input_set_path),
            "exchange_pilot_retrieval_set_manifest_json": rel_path(retrieval_set_path),
        },
        "slice": {
            "label_counts": dict(assignment_summary.get("label_counts") or {}),
            "bounded_ready_answer": str((assessment_summary.get("q4_good_enough_for_bounded_next_segmentation") or {}).get("answer") or ""),
        },
        "audit": {
            "run_dir": rel_path(audit_dir),
            "summary": rel_path(audit_dir / "summary.json"),
            "output_manifest": rel_path(audit_dir / "output_manifest.json"),
        },
    }
    write_json(assignment_set_path, assignment_set_manifest)

    output_manifest = {
        "processed_outputs": build_output_manifest(pilot_dir),
        "audit_outputs": build_output_manifest(audit_dir),
        "set_manifests": {
            "input": {"path": rel_path(input_set_path)},
            "retrieval": {"path": rel_path(retrieval_set_path)},
            "assignment": {"path": rel_path(assignment_set_path)},
        },
    }
    write_json(audit_dir / "output_manifest.json", output_manifest)

    print(
        json.dumps(
            {
                "run_id": run_id,
                "pilot_dir": rel_path(pilot_dir),
                "audit_dir": rel_path(audit_dir),
                "exchange_count": result.exchange_count,
                "top_k": top_k,
                "label_counts": dict(assignment_summary.get("label_counts") or {}),
                "bounded_ready_answer": str((assessment_summary.get("q4_good_enough_for_bounded_next_segmentation") or {}).get("answer") or ""),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
