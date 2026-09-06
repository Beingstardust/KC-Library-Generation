from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from kc_l.knowledge_library import load_release, validate_release_access


DEFAULT_POINTER = Path("CURRENT_KNOWLEDGE_LIBRARY_PILOT_RELEASE.md")
DEFAULT_OUT_ROOT = Path("data/processed/knowledge_library_access_layer_restarted")


def _resolve_repo_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def _rel(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _choose_out_dir(root: Path) -> tuple[str, Path]:
    base = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    suffix = 0
    while True:
        run_id = base if suffix == 0 else f"{base}_{suffix:02d}"
        out_dir = root / run_id
        if not out_dir.exists():
            return run_id, out_dir
        suffix += 1


def _build_report(release, validation_summary: dict[str, Any], retrieval_present: bool) -> str:
    loaded = validation_summary["loaded_counts"]
    return f"""# Knowledge Library Access-Layer Report

## Scope

This pass adds a thin read-only access layer over the active pilot Knowledge Library release without modifying any upstream topic, KC, graph, or schema-validation artifact.

## Active release

- Release label: `{validation_summary['release_label']}`
- Release manifest: `{release.release_manifest_path.as_posix()}`
- Active pointer: `{release.pointer_path.as_posix() if release.pointer_path is not None else 'None'}`

## Read-only access surface

- `load_release()` resolves the active pilot release.
- `load_topics()` returns typed Topic Library records from the release boundary.
- `load_kcs()` returns typed KC Library records from the approved frozen KC boundary.
- `load_graph()` returns normalized typed graph nodes and edges from the conservative graph bundle.
- `get_topic()`, `get_kc()`, `get_topic_children()`, and `get_topic_kc_candidates()` provide small audit-friendly helpers.
- Retrieval is exposed only as a read-only pointer helper when the approved-only retrieval manifest exists.

## Loaded counts

- Topics: `{loaded['topics']}`
- KCs: `{loaded['kcs']}`
- Graph nodes: `{loaded['graph_nodes']}`
- Graph edges: `{loaded['graph_edges']}`

## Conservative semantics preserved

- `topic_contains_topic` remains resolved structural hierarchy.
- `topic_contains_kc` remains conservative candidate membership only.
- No new edge types, no inference logic, and no retrieval rebuild were introduced.

## Retrieval pointer status

- Approved-only retrieval manifest exposed read-only: `{retrieval_present}`
"""


def _build_validation_summary(results: dict[str, Any]) -> str:
    summary = results["summary"]
    issue_counts = summary["issue_counts"]
    loaded = summary["loaded_counts"]
    retrieval = summary["retrieval_pointer"]
    return f"""# Access Validation Summary

- Overall status: `{summary['overall_status']}`
- Release resolution succeeded: `{summary['release_resolution_succeeded']}`
- Errors: `{issue_counts['error_count']}`
- Warnings: `{issue_counts['warning_count']}`
- Topics exposed: `{loaded['topics']}`
- KCs exposed: `{loaded['kcs']}`
- Graph nodes exposed: `{loaded['graph_nodes']}`
- Graph edges exposed: `{loaded['graph_edges']}`
- Retrieval pointer present: `{retrieval['present']}`
- Retrieval manifest exists: `{retrieval['manifest_exists']}`
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare and validate the thin read-only pilot Knowledge Library access layer.")
    parser.add_argument("--pointer", type=Path, default=DEFAULT_POINTER)
    parser.add_argument("--release_manifest", type=Path, default=None)
    parser.add_argument("--out_root", type=Path, default=DEFAULT_OUT_ROOT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    pointer_path = _resolve_repo_path(args.pointer)
    release_manifest_path = _resolve_repo_path(args.release_manifest) if args.release_manifest is not None else None
    out_root = _resolve_repo_path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    run_id, out_dir = _choose_out_dir(out_root)
    out_dir.mkdir(parents=True, exist_ok=False)

    release = load_release(release_manifest_path=release_manifest_path, pointer_path=pointer_path)
    validation_bundle = validate_release_access(release_manifest_path=release.release_manifest_path, pointer_path=pointer_path)

    topics = release.load_topics()
    kcs = release.load_kcs()
    graph = release.load_graph()
    retrieval_pointer = release.get_retrieval_pointer()

    created_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    access_validation_results = {
        "schema_version": "knowledge_library.access_validation_result.v1",
        "run_id": run_id,
        "created_utc": created_utc,
        "summary": validation_bundle.summary,
        "issues": [issue.to_row() for issue in validation_bundle.issues],
    }

    access_layer_manifest = {
        "schema_version": "knowledge_library.access_layer_manifest.v1",
        "run_id": run_id,
        "created_utc": created_utc,
        "package_status": "knowledge_library_access_layer_prepared",
        "active_release_pointer": _rel(pointer_path),
        "resolved_release_manifest": _rel(release.release_manifest_path),
        "release_label": release.release_label,
        "code_paths": {
            "access_py": "src/kc_l/knowledge_library/access.py",
            "contracts_py": "src/kc_l/knowledge_library/contracts.py",
            "validation_py": "src/kc_l/knowledge_library/validation.py",
            "runner_py": "steps/step_01_8_knowledge_library_access_layer/scripts/run_step01_8_knowledge_library_access_layer.py",
        },
        "source_paths": {
            "topic_library_jsonl": _rel(release.topic_library_path),
            "topic_boundary_json": _rel(release.topic_boundary_path),
            "kc_library_jsonl": _rel(release.kc_library_path),
            "kc_manifest_json": _rel(release.kc_manifest_path),
            "graph_nodes_jsonl": _rel(release.graph_nodes_path),
            "graph_edges_jsonl": _rel(release.graph_edges_path),
            "graph_manifest_json": _rel(release.graph_manifest_path),
            "schema_manifest_json": _rel(release.schema_manifest_path),
            "validation_results_json": _rel(release.validation_results_path),
            "retrieval_manifest_json": _rel(retrieval_pointer.manifest_path) if retrieval_pointer is not None else None,
        },
        "loaded_counts": {
            "topics": len(topics),
            "kcs": len(kcs),
            "graph_nodes": len(graph.nodes),
            "graph_edges": len(graph.edges),
        },
        "helper_surface": [
            "load_release",
            "load_topics",
            "load_kcs",
            "load_graph",
            "get_topic",
            "get_kc",
            "get_topic_children",
            "get_topic_kc_candidates",
        ],
        "retrieval_pointer": retrieval_pointer.to_row() if retrieval_pointer is not None else None,
        "semantics": {
            "topic_contains_topic": "resolved structural hierarchy",
            "topic_contains_kc": "conservative candidate membership only",
        },
        "validation_outcome": validation_bundle.summary,
        "invariants": {
            "topic_and_kc_layers_remain_separate": True,
            "graph_semantics_remain_conservative": True,
            "upstream_release_and_source_bundles_untouched": True,
            "retrieval_not_rebuilt": True,
            "kc_specific_criteria_touched": False,
        },
        "outputs": {
            "access_layer_manifest_json": _rel(out_dir / "access_layer_manifest.json"),
            "access_layer_report_md": _rel(out_dir / "access_layer_report.md"),
            "access_validation_results_json": _rel(out_dir / "access_validation_results.json"),
            "access_validation_summary_md": _rel(out_dir / "access_validation_summary.md"),
            "access_inventory_preview_csv": _rel(out_dir / "access_inventory_preview.csv"),
        },
    }

    inventory_rows = [
        {"component": "active_release_pointer", "path": _rel(pointer_path), "status": "resolved"},
        {"component": "release_manifest", "path": _rel(release.release_manifest_path), "status": "resolved"},
        {"component": "topic_library", "path": _rel(release.topic_library_path), "status": f"{len(topics)} topics"},
        {"component": "topic_boundary", "path": _rel(release.topic_boundary_path), "status": "resolved"},
        {"component": "kc_library", "path": _rel(release.kc_library_path), "status": f"{len(kcs)} kcs"},
        {"component": "kc_manifest", "path": _rel(release.kc_manifest_path), "status": "resolved"},
        {"component": "graph_nodes", "path": _rel(release.graph_nodes_path), "status": f"{len(graph.nodes)} nodes"},
        {"component": "graph_edges", "path": _rel(release.graph_edges_path), "status": f"{len(graph.edges)} edges"},
        {"component": "schema_manifest", "path": _rel(release.schema_manifest_path), "status": "resolved"},
        {"component": "validation_results", "path": _rel(release.validation_results_path), "status": validation_bundle.summary["overall_status"]},
    ]
    if retrieval_pointer is not None:
        inventory_rows.extend(
            [
                {"component": "retrieval_manifest", "path": _rel(retrieval_pointer.manifest_path), "status": "resolved"},
                {"component": "retrieval_source", "path": _rel(retrieval_pointer.retrieval_source_path), "status": "read_only_pointer"},
                {"component": "retrieval_index", "path": _rel(retrieval_pointer.retrieval_index_path), "status": "read_only_pointer"},
                {"component": "retrieval_query_contract", "path": _rel(retrieval_pointer.retrieval_query_contract_path), "status": "read_only_pointer"},
            ]
        )

    _write_json(out_dir / "access_layer_manifest.json", access_layer_manifest)
    (out_dir / "access_layer_report.md").write_text(
        _build_report(release, validation_bundle.summary, retrieval_pointer is not None),
        encoding="utf-8",
    )
    _write_json(out_dir / "access_validation_results.json", access_validation_results)
    (out_dir / "access_validation_summary.md").write_text(
        _build_validation_summary(access_validation_results),
        encoding="utf-8",
    )
    with (out_dir / "access_inventory_preview.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["component", "path", "status"])
        writer.writeheader()
        writer.writerows(inventory_rows)

    print(
        json.dumps(
            {
                "run_id": run_id,
                "out_dir": _rel(out_dir),
                "overall_status": validation_bundle.summary["overall_status"],
                "topic_count": len(topics),
                "kc_count": len(kcs),
                "graph_nodes": len(graph.nodes),
                "graph_edges": len(graph.edges),
                "retrieval_pointer_present": retrieval_pointer is not None,
            },
            indent=2,
        )
    )
    return 0 if not validation_bundle.has_errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
