from __future__ import annotations

import argparse
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from kc_l.audit.logger import JsonlLogger
from kc_l.audit.manifests import (
    build_input_manifest,
    build_output_manifest,
    env_snapshot,
    pip_freeze,
    try_cmd_version,
)
from kc_l.hierarchy_overlay import (
    build_leaf_to_overlay_ancestry,
    build_overlay,
    build_overlay_node_index,
    validate_overlay,
)
from kc_l.utils.hash import sha256_file
from kc_l.utils.json_io import read_json, read_jsonl, write_json, write_jsonl


def overlay_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S_hierarchy_overlay")


def _write_run_log(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")


def _normalize_manifest_source_set_id(normalized_manifest: dict[str, object] | None) -> str | None:
    if not normalized_manifest:
        return None
    value = normalized_manifest.get("source_set_id")
    text = str(value).strip() if value is not None else ""
    return text or None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hierarchy", type=str, required=True)
    parser.add_argument("--normalized_registry", type=str, required=True)
    parser.add_argument("--normalized_manifest", type=str, default="")
    parser.add_argument("--out_root", type=str, default="data/processed/hierarchy_overlay")
    parser.add_argument("--runs_dir", type=str, default="data/runs")
    parser.add_argument("--print_summary", action="store_true")
    args = parser.parse_args()

    start = time.perf_counter()
    created_utc = datetime.now(timezone.utc).isoformat()
    run_id = overlay_run_id()
    console = Console()

    run_dir = Path(args.runs_dir) / run_id
    out_dir = Path(args.out_root) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)

    logger = JsonlLogger(run_dir / "logs" / "events.jsonl")
    logger.log("INFO", "run_started", step="step_01_5_hierarchy_overlay", run_id=run_id)

    hierarchy_path = Path(args.hierarchy)
    normalized_registry_path = Path(args.normalized_registry)
    normalized_manifest_path = Path(args.normalized_manifest) if args.normalized_manifest else None

    if not hierarchy_path.exists():
        raise FileNotFoundError(f"Hierarchy not found: {hierarchy_path}")
    if not normalized_registry_path.exists():
        raise FileNotFoundError(f"Normalized registry not found: {normalized_registry_path}")
    if normalized_manifest_path and not normalized_manifest_path.exists():
        raise FileNotFoundError(f"Normalized manifest not found: {normalized_manifest_path}")

    raw_tree = read_json(hierarchy_path)
    normalized_rows = read_jsonl(normalized_registry_path)
    normalized_manifest = read_json(normalized_manifest_path) if normalized_manifest_path else None

    raw_source_set_id = sha256_file(hierarchy_path)
    manifest_source_set_id = _normalize_manifest_source_set_id(normalized_manifest)
    if manifest_source_set_id and manifest_source_set_id != raw_source_set_id:
        raise ValueError(
            "Normalized hierarchy manifest source_set_id does not match the raw hierarchy sha256. "
            f"manifest={manifest_source_set_id} raw={raw_source_set_id}"
        )

    config_snapshot = {
        "step": "step_01_5_hierarchy_overlay",
        "created_utc": created_utc,
        "hierarchy": args.hierarchy,
        "normalized_registry": args.normalized_registry,
        "normalized_manifest": args.normalized_manifest,
        "out_root": args.out_root,
        "runs_dir": args.runs_dir,
        "constraints": {
            "preserve_leaf_kc_ids_exactly": True,
            "no_active_update": True,
            "no_step6_rerun": True,
            "no_128_run": True,
            "no_semantic_population_from_hierarchy_description_raw": True,
            "conservative_node_type": True,
        },
    }
    write_json(run_dir / "config_snapshot.json", config_snapshot)

    invocation_argv = [
        "steps/step_01_5_hierarchy_overlay/scripts/run_step01_5_hierarchy_overlay.py",
        "--hierarchy",
        args.hierarchy,
        "--normalized_registry",
        args.normalized_registry,
        "--out_root",
        args.out_root,
        "--runs_dir",
        args.runs_dir,
    ]
    if args.normalized_manifest:
        invocation_argv.extend(["--normalized_manifest", args.normalized_manifest])
    if args.print_summary:
        invocation_argv.append("--print_summary")

    write_json(
        run_dir / "invocation.json",
        {
            "argv": invocation_argv,
            "created_utc": created_utc,
            "cwd": ".",
        },
    )

    input_paths = [hierarchy_path, normalized_registry_path]
    if normalized_manifest_path:
        input_paths.append(normalized_manifest_path)
    write_json(run_dir / "input_manifest.json", build_input_manifest(input_paths))
    write_json(run_dir / "environment_snapshot.json", env_snapshot())
    write_json(
        run_dir / "tool_versions.json",
        {
            "python": platform.python_version(),
            "git": try_cmd_version(["git", "--version"]),
            "rg": try_cmd_version(["rg", "--version"]),
            "pip_freeze": pip_freeze(),
        },
    )

    logger.log("INFO", "inputs_loaded", raw_source_set_id=raw_source_set_id, normalized_leaf_count=len(normalized_rows))

    build_result = build_overlay(
        raw_tree=raw_tree,
        normalized_rows=normalized_rows,
        source_set_id=raw_source_set_id,
    )
    ancestry = build_leaf_to_overlay_ancestry(build_result.nodes)
    overlay_index = build_overlay_node_index(build_result.nodes)
    validation_report = validate_overlay(
        nodes=build_result.nodes,
        normalized_rows=normalized_rows,
        raw_total_nodes=build_result.raw_total_nodes,
        raw_leaf_nodes=build_result.raw_leaf_nodes,
        raw_nonleaf_nodes=build_result.raw_nonleaf_nodes,
    )

    overlay_rows = [node.to_row() for node in build_result.nodes]
    overlay_stats = {
        **validation_report["counts"],
        "raw_source_set_id": raw_source_set_id,
        "normalized_manifest_source_set_id": manifest_source_set_id,
    }
    overlay_manifest = {
        "run_id": run_id,
        "created_utc": created_utc,
        "raw_source_set_id": raw_source_set_id,
        "normalized_registry": args.normalized_registry,
        "normalized_manifest": args.normalized_manifest,
        "overlay_total_nodes": len(overlay_rows),
        "has_errors": validation_report["has_errors"],
        "artifacts": {
            "hierarchy_overlay_jsonl": str(out_dir / "hierarchy_overlay.jsonl"),
            "overlay_manifest_json": str(out_dir / "overlay_manifest.json"),
            "overlay_stats_json": str(out_dir / "overlay_stats.json"),
            "leaf_to_overlay_ancestry_json": str(out_dir / "leaf_to_overlay_ancestry.json"),
            "overlay_node_index_json": str(out_dir / "overlay_node_index.json"),
            "validation_report_json": str(out_dir / "validation_report.json"),
        },
    }

    write_jsonl(out_dir / "hierarchy_overlay.jsonl", overlay_rows)
    write_json(out_dir / "overlay_manifest.json", overlay_manifest)
    write_json(out_dir / "overlay_stats.json", overlay_stats)
    write_json(out_dir / "leaf_to_overlay_ancestry.json", ancestry)
    write_json(out_dir / "overlay_node_index.json", overlay_index)
    write_json(out_dir / "validation_report.json", validation_report)

    elapsed = time.perf_counter() - start
    write_json(
        run_dir / "timings.json",
        {
            "total_seconds": elapsed,
            "build_seconds": elapsed,
        },
    )

    summary = {
        "run_id": run_id,
        "created_utc": created_utc,
        "step": "step_01_5_hierarchy_overlay",
        "raw_source_set_id": raw_source_set_id,
        "normalized_registry": args.normalized_registry,
        "normalized_manifest": args.normalized_manifest,
        "stats": overlay_stats,
        "checks": validation_report["checks"],
        "has_errors": validation_report["has_errors"],
    }
    write_json(run_dir / "summary.json", summary)

    run_log_lines = [
        f"[{created_utc}] Started Step 01.5 hierarchy overlay build.",
        f"[{created_utc}] Raw hierarchy: {args.hierarchy}",
        f"[{created_utc}] Normalized registry: {args.normalized_registry}",
        f"[{created_utc}] Overlay output dir: {out_dir.as_posix()}",
        f"[{created_utc}] Overlay nodes: {len(overlay_rows)}",
        f"[{created_utc}] Validation has_errors: {validation_report['has_errors']}",
    ]
    _write_run_log(run_dir / "run.log", run_log_lines)

    logger.log(
        "INFO",
        "run_finished",
        step="step_01_5_hierarchy_overlay",
        run_id=run_id,
        overlay_total_nodes=len(overlay_rows),
        has_errors=validation_report["has_errors"],
    )
    write_json(run_dir / "output_manifest.json", build_output_manifest(run_dir))

    if args.print_summary:
        table = Table(title="Step 01.5 Hierarchy Overlay Summary")
        table.add_column("Metric")
        table.add_column("Value")
        table.add_row("run_id", run_id)
        table.add_row("raw_total_nodes", str(validation_report["counts"]["raw_total_nodes"]))
        table.add_row("normalized_leaf_nodes", str(validation_report["counts"]["normalized_leaf_nodes"]))
        table.add_row("overlay_total_nodes", str(validation_report["counts"]["overlay_total_nodes"]))
        table.add_row("overlay_node_type_counts", str(validation_report["counts"]["overlay_node_type_counts"]))
        table.add_row("has_errors", str(validation_report["has_errors"]))
        console.print(table)

    return 1 if validation_report["has_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
