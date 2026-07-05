from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from kc_l.knowledge_library import contract_overview, validate_current_pilot_artifacts


DEFAULT_TOPIC_LIBRARY = Path(
    "data/processed/topic_final_resolution_restarted/2026-04-01_172430/reviewed_topic_library_resolved_final.jsonl"
)
DEFAULT_TOPIC_BOUNDARY = Path(
    "data/processed/topic_final_resolution_restarted/2026-04-01_172430/topic_review_boundary_consolidated_final.json"
)
DEFAULT_KC_LIBRARY = Path(
    "data/processed/kc_library_pilot_packaging_restarted/2026-04-01_133111/approved_reviewed_library_frozen.jsonl"
)
DEFAULT_KC_MANIFEST = Path(
    "data/processed/kc_library_pilot_packaging_restarted/2026-04-01_133111/approved_reviewed_library_manifest.json"
)
DEFAULT_GRAPH_NODES = Path(
    "data/processed/knowledge_graph_preparation_restarted/2026-04-01_173727/graph_nodes.jsonl"
)
DEFAULT_GRAPH_EDGES = Path(
    "data/processed/knowledge_graph_preparation_restarted/2026-04-01_173727/graph_edges.jsonl"
)
DEFAULT_GRAPH_MANIFEST = Path(
    "data/processed/knowledge_graph_preparation_restarted/2026-04-01_173727/graph_manifest.json"
)
DEFAULT_GRAPH_VALIDATION_REPORT = Path(
    "data/processed/knowledge_graph_preparation_restarted/2026-04-01_173727/graph_validation_report.md"
)
DEFAULT_OUT_ROOT = Path("data/processed/knowledge_library_schema_validation_restarted")


def _resolve_repo_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def _rel(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()


def _choose_out_dir(root: Path) -> tuple[str, Path]:
    base = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    suffix = 0
    while True:
        run_id = base if suffix == 0 else f"{base}_{suffix:02d}"
        out_dir = root / run_id
        if not out_dir.exists():
            return run_id, out_dir
        suffix += 1


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True))
            handle.write("\n")


def _build_schema_report() -> str:
    return """# Knowledge Library Schema Report

## Scope

This pass formalizes a minimal reusable contract layer for the current Knowledge Library pilot without changing any upstream topic, KC, or graph artifact.

## Canonical object contracts

- `TopicNodeRecord`: canonical topic node contract with shared graph-node fields plus a canonical `payload` object for topic-specific structure.
- `KCNodeRecord`: canonical KC node contract with the same shared graph-node envelope plus a distinct KC `payload` object.
- `GraphEdgeRecord`: typed graph edge contract limited to the current pilot edge types.

## Canonical/raw compatibility rule

The canonical node contract uses a single `payload` field.
The current pilot graph bundle is accepted through a narrow adapter that reads the existing typed raw fields:
- `topic_payload`
- `kc_payload`

This keeps the upstream graph bundle read-only while still establishing a cleaner forward contract.

## Pilot edge-type boundary

Only these edge types are valid in this pass:
- `topic_contains_topic`
- `topic_contains_kc`

No prerequisite edges, no semantic relation edges, and no `kc_to_kc` edges were added.

## Validation boundary

The validator checks:
- typed node and edge envelopes
- topic/KC payload-family separation
- allowed status sets
- edge endpoint existence
- edge type to endpoint type compatibility
- excluded-topic leakage
- non-approved-KC leakage
- graph manifest consistency
- graph validation report consistency
"""


def _build_validation_summary(validation_results: dict[str, Any]) -> str:
    summary = validation_results["summary"]
    issues = summary["issue_counts"]
    graph_counts = summary["graph_counts"]
    normalization = summary["normalization"]
    return f"""# Validation Summary

- Overall status: `{summary['overall_status']}`
- Errors: `{issues['error_count']}`
- Warnings: `{issues['warning_count']}`
- Topic nodes validated: `{graph_counts['topic_nodes']}`
- KC nodes validated: `{graph_counts['kc_nodes']}`
- topic_contains_topic edges validated: `{graph_counts['topic_contains_topic_edges']}`
- topic_contains_kc edges validated: `{graph_counts['topic_contains_kc_edges']}`
- Total nodes validated: `{graph_counts['total_nodes']}`
- Total edges validated: `{graph_counts['total_edges']}`
- Canonical payload rows already present upstream: `{normalization['canonical_payload_field_count']}`
- Rows normalized from typed raw payload aliases: `{normalization['typed_payload_alias_count']}`
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the current pilot Knowledge Library artifacts against typed contracts.")
    parser.add_argument("--topic_library", type=Path, default=DEFAULT_TOPIC_LIBRARY)
    parser.add_argument("--topic_boundary", type=Path, default=DEFAULT_TOPIC_BOUNDARY)
    parser.add_argument("--kc_library", type=Path, default=DEFAULT_KC_LIBRARY)
    parser.add_argument("--kc_manifest", type=Path, default=DEFAULT_KC_MANIFEST)
    parser.add_argument("--graph_nodes", type=Path, default=DEFAULT_GRAPH_NODES)
    parser.add_argument("--graph_edges", type=Path, default=DEFAULT_GRAPH_EDGES)
    parser.add_argument("--graph_manifest", type=Path, default=DEFAULT_GRAPH_MANIFEST)
    parser.add_argument("--graph_validation_report", type=Path, default=DEFAULT_GRAPH_VALIDATION_REPORT)
    parser.add_argument("--out_root", type=Path, default=DEFAULT_OUT_ROOT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    out_root = _resolve_repo_path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    run_id, out_dir = _choose_out_dir(out_root)
    out_dir.mkdir(parents=True, exist_ok=False)

    topic_library_path = _resolve_repo_path(args.topic_library)
    topic_boundary_path = _resolve_repo_path(args.topic_boundary)
    kc_library_path = _resolve_repo_path(args.kc_library)
    kc_manifest_path = _resolve_repo_path(args.kc_manifest)
    graph_nodes_path = _resolve_repo_path(args.graph_nodes)
    graph_edges_path = _resolve_repo_path(args.graph_edges)
    graph_manifest_path = _resolve_repo_path(args.graph_manifest)
    graph_validation_report_path = _resolve_repo_path(args.graph_validation_report)

    bundle = validate_current_pilot_artifacts(
        topic_library_path=topic_library_path,
        topic_boundary_path=topic_boundary_path,
        kc_library_path=kc_library_path,
        kc_manifest_path=kc_manifest_path,
        graph_nodes_path=graph_nodes_path,
        graph_edges_path=graph_edges_path,
        graph_manifest_path=graph_manifest_path,
        graph_validation_report_path=graph_validation_report_path,
    )

    created_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    validation_results = {
        "schema_version": bundle.summary["schema_version"],
        "run_id": run_id,
        "created_utc": created_utc,
        "summary": bundle.summary,
        "issues": [issue.to_row() for issue in bundle.issues],
    }

    schema_manifest = {
        "schema_version": "knowledge_library.schema_manifest.v1",
        "run_id": run_id,
        "created_utc": created_utc,
        "package_status": "knowledge_library_schema_validation_bundle_emitted",
        "contract": contract_overview(),
        "code_paths": {
            "contracts_py": "src/kc_l/knowledge_library/contracts.py",
            "validation_py": "src/kc_l/knowledge_library/validation.py",
            "runner_py": "steps/step_01_7_knowledge_library_schema_validation/scripts/run_step01_7_knowledge_library_schema_validation.py",
        },
        "inputs": {
            "topic_library_jsonl": _rel(topic_library_path),
            "topic_boundary_json": _rel(topic_boundary_path),
            "kc_library_jsonl": _rel(kc_library_path),
            "kc_manifest_json": _rel(kc_manifest_path),
            "graph_nodes_jsonl": _rel(graph_nodes_path),
            "graph_edges_jsonl": _rel(graph_edges_path),
            "graph_manifest_json": _rel(graph_manifest_path),
            "graph_validation_report_md": _rel(graph_validation_report_path),
        },
        "outputs": {
            "schema_manifest_json": _rel(out_dir / "schema_manifest.json"),
            "schema_report_md": _rel(out_dir / "schema_report.md"),
            "validation_results_json": _rel(out_dir / "validation_results.json"),
            "validation_summary_md": _rel(out_dir / "validation_summary.md"),
            "normalized_graph_nodes_preview_jsonl": _rel(out_dir / "normalized_graph_nodes_preview.jsonl"),
            "normalized_graph_edges_preview_jsonl": _rel(out_dir / "normalized_graph_edges_preview.jsonl"),
        },
        "validation_outcome": bundle.summary,
        "invariants": {
            "topic_and_kc_collections_remain_typed_and_separate": True,
            "graph_edges_remain_typed": True,
            "only_current_pilot_edge_types_formalized": True,
            "upstream_topic_kc_graph_artifacts_untouched": True,
            "kc_specific_criteria_touched": False,
            "no_step6_7_or_6_8_changes": True,
        },
    }

    _write_json(out_dir / "schema_manifest.json", schema_manifest)
    (out_dir / "schema_report.md").write_text(_build_schema_report(), encoding="utf-8")
    _write_json(out_dir / "validation_results.json", validation_results)
    (out_dir / "validation_summary.md").write_text(
        _build_validation_summary(validation_results),
        encoding="utf-8",
    )
    _write_jsonl(out_dir / "normalized_graph_nodes_preview.jsonl", [row.to_row() for row in bundle.normalized_nodes])
    _write_jsonl(out_dir / "normalized_graph_edges_preview.jsonl", [row.to_row() for row in bundle.normalized_edges])

    print(
        json.dumps(
            {
                "run_id": run_id,
                "out_dir": _rel(out_dir),
                "overall_status": bundle.summary["overall_status"],
                "error_count": bundle.summary["issue_counts"]["error_count"],
                "warning_count": bundle.summary["issue_counts"]["warning_count"],
                "total_nodes": bundle.summary["graph_counts"]["total_nodes"],
                "total_edges": bundle.summary["graph_counts"]["total_edges"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
