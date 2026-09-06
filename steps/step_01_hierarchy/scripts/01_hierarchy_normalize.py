from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

from rich.console import Console
from rich.table import Table

from kc_l.audit.run_context import RunContext, utc_run_id
from kc_l.audit.logger import JsonlLogger
from kc_l.audit.manifests import build_input_manifest
from kc_l.utils.hashing import sha256_file
from kc_l.utils.json_io import read_json, write_json, write_jsonl
from kc_l.hierarchy.loader import load_hierarchy_kcs
from kc_l.hierarchy.normalize import to_registry_rows
from kc_l.hierarchy.validators import validate_kc_leaves, has_errors
from kc_l.hierarchy.stats import compute_stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hierarchy", type=str, required=True)
    parser.add_argument("--out_root", type=str, required=True)
    parser.add_argument("--runs_dir", type=str, default="data/runs")
    parser.add_argument("--print_summary", action="store_true")
    args = parser.parse_args()

    console = Console()
    repo_root = Path(".").resolve()

    run_id = utc_run_id()
    run_dir = Path(args.runs_dir) / run_id
    run = RunContext(run_id=run_id, run_dir=run_dir, repo_root=repo_root)
    run.init_dirs()

    logger = JsonlLogger(run_dir / "logs" / "events.jsonl")
    logger.log("INFO", "run_started", step="step_01_hierarchy", run_id=run_id)

    run.write_cli_invocation(sys.argv)
    run.write_environment()

    hierarchy_path = Path(args.hierarchy)
    if not hierarchy_path.exists():
        raise FileNotFoundError(f"Hierarchy not found: {hierarchy_path}")

    source_set_id = sha256_file(hierarchy_path)
    run.write_config_used(
        {
            "step": "step_01_hierarchy",
            "hierarchy_path": str(hierarchy_path),
            "out_root": args.out_root,
            "created_utc": datetime.now(timezone.utc).isoformat(),
        }
    )
    inputs_manifest = run.write_inputs_manifest({"hierarchy_json": hierarchy_path})
    logger.log("INFO", "inputs_loaded", source_set_id=source_set_id)

    tree = read_json(hierarchy_path)
    kcs = load_hierarchy_kcs(tree)
    issues = validate_kc_leaves(kcs)

    out_dir = Path(args.out_root) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    registry_path = out_dir / "kc_registry.jsonl"
    stats_path = out_dir / "hierarchy_stats.json"
    manifest_path = out_dir / "hierarchy_manifest.json"

    write_jsonl(registry_path, to_registry_rows(kcs))
    write_json(stats_path, compute_stats(kcs, issues, source_set_id))

    hierarchy_manifest = {
        "run_id": run_id,
        "source_set_id": source_set_id,
        "num_kcs": len(kcs),
        "registry_path": str(registry_path),
        "stats_path": str(stats_path),
        "issues_has_errors": has_errors(issues),
    }
    write_json(manifest_path, hierarchy_manifest)

    outputs_manifest = build_input_manifest(
        [
            registry_path,
            stats_path,
            manifest_path,
        ]
    )

    write_json(
        run_dir / "run_manifest.json",
        {
            "run_id": run_id,
            "step": "step_01_hierarchy",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "inputs": inputs_manifest,
            "outputs": outputs_manifest,
            "out_dir": str(out_dir),
        },
    )

    if args.print_summary:
        t = Table(title="Step 01 Summary")
        t.add_column("Metric")
        t.add_column("Value")
        t.add_row("run_id", run_id)
        t.add_row("source_set_id", source_set_id)
        t.add_row("num_kcs", str(len(kcs)))
        t.add_row("num_issues", str(len(issues)))
        t.add_row("has_errors", str(has_errors(issues)))
        t.add_row("out_dir", str(out_dir))
        console.print(t)

        if issues:
            it = Table(title="Issues (first 20)")
            it.add_column("level")
            it.add_column("code")
            it.add_column("message")
            it.add_column("kc_id")
            it.add_column("kc_path")
            for i in issues[:20]:
                it.add_row(i.level, i.code, i.message, i.kc_id or "", " > ".join(i.kc_path or []))
            console.print(it)

    logger.log(
        "INFO",
        "run_finished",
        step="step_01_hierarchy",
        run_id=run_id,
        num_kcs=len(kcs),
        has_errors=has_errors(issues),
    )

    return 1 if has_errors(issues) else 0


if __name__ == "__main__":
    raise SystemExit(main())