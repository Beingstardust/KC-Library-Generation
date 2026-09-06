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
from kc_l.kc.restarted_retrieval_pilot import assemble_restarted_retrieval_pilot
from kc_l.utils.json_io import read_json, write_json


DEFAULT_CONFIG = Path("steps/step_06_13_reviewed_library_retrieval_pilot/resources/step6_13.slice48.yaml")


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
        audit_dir = (runs_root / f"{run_id}_step6_13").resolve()
        source_set_path = (sets_root / f"{run_id}_step6_13_reviewed_retrieval_source_restarted_set.json").resolve()
        index_set_path = (sets_root / f"{run_id}_step6_13_reviewed_retrieval_index_restarted_set.json").resolve()
        validation_set_path = (sets_root / f"{run_id}_step6_13_reviewed_retrieval_validation_restarted_set.json").resolve()
        if not pilot_dir.exists() and not audit_dir.exists() and not source_set_path.exists() and not index_set_path.exists() and not validation_set_path.exists():
            return {
                "run_id_step6_13": Path(run_id),
                "pilot_dir": pilot_dir,
                "audit_dir": audit_dir,
                "source_set_path": source_set_path,
                "index_set_path": index_set_path,
                "validation_set_path": validation_set_path,
            }
        suffix += 1


def copy_config_snapshot(config_path: Path, audit_dir: Path) -> Path:
    target = audit_dir / "config_snapshot.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(config_path, target)
    return target


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a reviewed-only retrieval/index pilot for the repaired restarted slice48 closure.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = resolve_repo_path(args.config)
    cfg = load_yaml_or_json(config_path)

    input_cfg = dict(cfg.get("inputs") or {})
    output_cfg = dict(cfg.get("outputs") or {})
    query_cfg = dict(cfg.get("query") or {})

    processed_root = resolve_repo_path(output_cfg.get("processed_root") or "data/processed/kc_library_retrieval_pilot_restarted")
    sets_root = resolve_repo_path(output_cfg.get("sets_root") or "data/processed/kc_library_retrieval_pilot_restarted/_sets")
    runs_root = resolve_repo_path(output_cfg.get("runs_root") or "data/runs")

    step6_11_set_path = resolve_repo_path(input_cfg.get("step6_11_set_manifest") or "data/processed/kc_library_reviewed_restarted/_sets/2026-03-24_164654_step6_11_kc_library_reviewed_restarted_set.json")
    step6_12_set_path = resolve_repo_path(input_cfg.get("step6_12_set_manifest") or "data/processed/kc_library_runtime_restarted/_sets/2026-03-24_165020_step6_12_kc_library_runtime_restarted_set.json")

    step6_11_set_obj = read_json(step6_11_set_path)
    step6_12_set_obj = read_json(step6_12_set_path)

    source_step6_11_set_id = str(step6_11_set_obj.get("set_id") or step6_11_set_path.stem)
    source_step6_12_set_id = str(step6_12_set_obj.get("set_id") or step6_12_set_path.stem)
    source_reviewed_library_path = resolve_repo_path(step6_11_set_obj.get("artifacts", {}).get("frozen_reviewed_library_jsonl"))
    reviewed_summary_path = resolve_repo_path(step6_11_set_obj.get("artifacts", {}).get("reviewed_library_summary_json"))
    reviewed_preview_path = resolve_repo_path(step6_11_set_obj.get("artifacts", {}).get("reviewed_library_preview_md"))
    source_runtime_library_path = resolve_repo_path(step6_12_set_obj.get("artifacts", {}).get("runtime_kc_library_jsonl"))
    runtime_summary_path = resolve_repo_path(step6_12_set_obj.get("artifacts", {}).get("runtime_package_summary_json"))
    runtime_preview_path = resolve_repo_path(step6_12_set_obj.get("artifacts", {}).get("runtime_package_preview_md"))

    top_k = int(query_cfg.get("top_k") or 5)

    run_paths = choose_run_paths(processed_root, runs_root, sets_root)
    run_id = str(run_paths["run_id_step6_13"])
    pilot_dir = run_paths["pilot_dir"]
    audit_dir = run_paths["audit_dir"]
    source_set_path = run_paths["source_set_path"]
    index_set_path = run_paths["index_set_path"]
    validation_set_path = run_paths["validation_set_path"]
    pilot_dir.mkdir(parents=True, exist_ok=False)
    audit_dir.mkdir(parents=True, exist_ok=False)
    sets_root.mkdir(parents=True, exist_ok=True)

    config_snapshot_path = copy_config_snapshot(config_path, audit_dir)

    result = assemble_restarted_retrieval_pilot(
        source_reviewed_library_path=source_reviewed_library_path,
        source_runtime_library_path=source_runtime_library_path,
        output_dir=pilot_dir,
        assembly_run_id=run_id,
        source_reviewed_set_id=source_step6_11_set_id,
        source_runtime_set_id=source_step6_12_set_id,
        top_k=top_k,
    )

    source_summary = read_json(result.source_summary_path)
    index_summary = read_json(result.index_summary_path)
    validation_summary = read_json(result.validation_summary_path)

    input_manifest = build_input_manifest([
        config_path,
        step6_11_set_path,
        step6_12_set_path,
        source_reviewed_library_path,
        reviewed_summary_path,
        reviewed_preview_path,
        source_runtime_library_path,
        runtime_summary_path,
        runtime_preview_path,
    ])
    write_json(audit_dir / "input_manifest.json", input_manifest)

    summary = {
        "run_id": run_id,
        "created_utc": now_utc_iso(),
        "source_step6_11_set_id": source_step6_11_set_id,
        "source_step6_12_set_id": source_step6_12_set_id,
        "source_reviewed_library_jsonl": rel_path(source_reviewed_library_path),
        "source_runtime_library_jsonl": rel_path(source_runtime_library_path),
        "stats": {
            "retrieval_record_count": source_summary.get("record_count"),
            "indexed_record_count": index_summary.get("indexed_record_count"),
            "query_count": validation_summary.get("query_count"),
            "top1_hit_count": validation_summary.get("top1_hit_count"),
            "top3_hit_count": validation_summary.get("top3_hit_count"),
            "sandbox_entries_included": 0,
        },
        "env": env_snapshot(),
        "tool_versions": {
            "python": try_cmd_version([sys.executable, "--version"]),
        },
    }
    write_json(audit_dir / "summary.json", summary)

    source_set_manifest = {
        "schema_version": "1.0",
        "kind": "step6_13_reviewed_retrieval_source_restarted_set",
        "set_id": f"{run_id}_step6_13_reviewed_retrieval_source_restarted_set",
        "created_utc": now_utc_iso(),
        "run_id_step6_13": run_id,
        "artifacts": {
            "reviewed_retrieval_source_jsonl": rel_path(result.retrieval_source_path),
            "reviewed_retrieval_source_summary_json": rel_path(result.source_summary_path),
            "reviewed_retrieval_source_preview_md": rel_path(result.source_preview_path),
        },
        "upstream": {
            "step6_11_set_manifest_json": rel_path(step6_11_set_path),
            "step6_12_set_manifest_json": rel_path(step6_12_set_path),
            "frozen_reviewed_library_jsonl": rel_path(source_reviewed_library_path),
            "runtime_kc_library_jsonl": rel_path(source_runtime_library_path),
        },
        "slice": {
            "included_kcs": list(source_summary.get("included_kcs") or []),
            "review_status_counts": dict(source_summary.get("review_status_counts") or {}),
            "sandbox_entries_included": 0,
        },
        "audit": {
            "run_dir": rel_path(audit_dir),
            "config_snapshot": rel_path(config_snapshot_path),
            "input_manifest": rel_path(audit_dir / "input_manifest.json"),
            "summary": rel_path(audit_dir / "summary.json"),
            "output_manifest": rel_path(audit_dir / "output_manifest.json"),
        },
    }
    write_json(source_set_path, source_set_manifest)

    index_set_manifest = {
        "schema_version": "1.0",
        "kind": "step6_13_reviewed_retrieval_index_restarted_set",
        "set_id": f"{run_id}_step6_13_reviewed_retrieval_index_restarted_set",
        "created_utc": now_utc_iso(),
        "run_id_step6_13": run_id,
        "artifacts": {
            "reviewed_retrieval_index_json": rel_path(result.index_path),
            "reviewed_retrieval_index_summary_json": rel_path(result.index_summary_path),
            "retrieval_query_contract_json": rel_path(result.query_contract_path),
        },
        "upstream": {
            "reviewed_retrieval_source_set_manifest_json": rel_path(source_set_path),
            "step6_11_set_manifest_json": rel_path(step6_11_set_path),
            "step6_12_set_manifest_json": rel_path(step6_12_set_path),
        },
        "slice": {
            "indexed_kcs": list(index_summary.get("indexed_kcs") or []),
            "indexed_record_count": index_summary.get("indexed_record_count"),
            "sandbox_entries_included": 0,
        },
        "audit": {
            "run_dir": rel_path(audit_dir),
            "summary": rel_path(audit_dir / "summary.json"),
            "output_manifest": rel_path(audit_dir / "output_manifest.json"),
        },
    }
    write_json(index_set_path, index_set_manifest)

    validation_set_manifest = {
        "schema_version": "1.0",
        "kind": "step6_13_reviewed_retrieval_validation_restarted_set",
        "set_id": f"{run_id}_step6_13_reviewed_retrieval_validation_restarted_set",
        "created_utc": now_utc_iso(),
        "run_id_step6_13": run_id,
        "artifacts": {
            "retrieval_validation_queries_json": rel_path(result.validation_queries_path),
            "retrieval_validation_results_json": rel_path(result.validation_results_path),
            "retrieval_validation_summary_json": rel_path(result.validation_summary_path),
            "retrieval_validation_preview_md": rel_path(result.validation_preview_path),
            "retrieval_pilot_assessment_md": rel_path(result.assessment_path),
        },
        "upstream": {
            "reviewed_retrieval_source_set_manifest_json": rel_path(source_set_path),
            "reviewed_retrieval_index_set_manifest_json": rel_path(index_set_path),
        },
        "slice": {
            "query_count": validation_summary.get("query_count"),
            "top1_hit_count": validation_summary.get("top1_hit_count"),
            "top3_hit_count": validation_summary.get("top3_hit_count"),
            "weak_queries": list(validation_summary.get("weak_queries") or []),
            "ambiguous_queries": list(validation_summary.get("ambiguous_queries") or []),
            "sandbox_entries_included": 0,
        },
        "audit": {
            "run_dir": rel_path(audit_dir),
            "summary": rel_path(audit_dir / "summary.json"),
            "output_manifest": rel_path(audit_dir / "output_manifest.json"),
        },
    }
    write_json(validation_set_path, validation_set_manifest)

    output_manifest = {
        "processed_outputs": build_output_manifest(pilot_dir),
        "audit_outputs": build_output_manifest(audit_dir),
        "set_manifests": {
            "source": {"path": rel_path(source_set_path)},
            "index": {"path": rel_path(index_set_path)},
            "validation": {"path": rel_path(validation_set_path)},
        },
    }
    write_json(audit_dir / "output_manifest.json", output_manifest)

    print(json.dumps({
        "run_id": run_id,
        "pilot_dir": rel_path(pilot_dir),
        "audit_dir": rel_path(audit_dir),
        "retrieval_record_count": source_summary.get("record_count"),
        "validation_query_count": validation_summary.get("query_count"),
        "top1_hit_count": validation_summary.get("top1_hit_count"),
        "top3_hit_count": validation_summary.get("top3_hit_count"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
