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

from kc_l.knowledge_library import load_grounding_bridge, validate_grounding_bridge


DEFAULT_POINTER = Path("CURRENT_KNOWLEDGE_LIBRARY_PILOT_RELEASE.md")
DEFAULT_ACCESS_MANIFEST = Path(
    "data/processed/knowledge_library_access_layer_restarted/2026-04-01_182416/access_layer_manifest.json"
)
DEFAULT_ACCESS_VALIDATION = Path(
    "data/processed/knowledge_library_access_layer_restarted/2026-04-01_182416/access_validation_results.json"
)
DEFAULT_OUT_ROOT = Path("data/processed/knowledge_library_grounding_bridge_restarted")


def _resolve_repo_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def _rel(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


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


def _build_report(bridge, summary: dict[str, Any], access_alignment: dict[str, Any]) -> str:
    loaded = summary["loaded_counts"]
    smoke = summary["smoke_examples"]
    return f"""# Knowledge Library Grounding-Bridge Report

## Scope

This pass adds one thin downstream-facing grounding bridge over the active pilot Knowledge Library release by consuming the read-only access layer and repackaging it into a smaller downstream-safe interface.

## Active release

- Release label: `{summary['release_label']}`
- Release manifest: `{bridge.release.release_manifest_path.as_posix()}`
- Active pointer: `{bridge.release.pointer_path.as_posix() if bridge.release.pointer_path is not None else 'None'}`

## Downstream-facing bridge surface

- `load_grounding_bridge()` resolves the active pilot release through the access layer.
- `get_release_summary()` exposes counts, exclusions, retrieval-pointer presence, and conservative semantics.
- `get_topic_bundle()` exposes a typed topic record plus a graph neighborhood summary.
- `get_topic_grounding()` exposes a typed topic bundle plus conservative topic-to-KC candidate summaries.
- `get_kc_bundle()` exposes a typed KC record plus reverse candidate-topic context.
- `get_retrieval_pointer()` reuses the approved-only retrieval boundary as a read-only pointer only.

## Loaded counts

- Topics: `{loaded['topics']}`
- KCs: `{loaded['kcs']}`
- Graph nodes: `{loaded['graph_nodes']}`
- Graph edges: `{loaded['graph_edges']}`

## Conservative semantics preserved

- `topic_contains_topic` remains resolved structural hierarchy.
- `topic_contains_kc` remains conservative candidate membership only.
- No new edge types, no inference logic, and no retrieval rebuild were introduced.

## Access-layer alignment

- Access layer release label matched bridge release label: `{access_alignment['release_label_matches']}`
- Access layer validation already passing: `{access_alignment['access_validation_passed']}`
- Access layer counts matched bridge counts: `{access_alignment['count_alignment_passed']}`

## Smoke examples

- Topic bundle sample: `{smoke['topic_bundle_topic_id']}`
- Topic grounding sample: `{smoke['topic_grounding_topic_id']}`
- KC bundle sample: `{smoke['kc_bundle_kc_id']}`
"""


def _build_validation_summary(results: dict[str, Any]) -> str:
    summary = results["summary"]
    issue_counts = summary["issue_counts"]
    checks = summary["checks"]
    retrieval = summary["retrieval_pointer"]
    access_alignment = results["access_layer_alignment"]
    return f"""# Grounding-Bridge Validation Summary

- Overall status: `{summary['overall_status']}`
- Release resolution succeeded: `{summary['release_resolution_succeeded']}`
- Errors: `{issue_counts['error_count']}`
- Warnings: `{issue_counts['warning_count']}`
- Topic bundle smoke check: `{checks['topic_bundle_available']}`
- Topic grounding smoke check: `{checks['topic_grounding_available']}`
- KC bundle smoke check: `{checks['kc_bundle_available']}`
- Excluded topics hidden: `{checks['excluded_topics_hidden']}`
- Non-approved KCs hidden: `{checks['nonapproved_kcs_hidden']}`
- Retrieval pointer present: `{retrieval['present']}`
- Retrieval manifest exists: `{retrieval['manifest_exists']}`
- Access-layer release label match: `{access_alignment['release_label_matches']}`
- Access-layer count alignment: `{access_alignment['count_alignment_passed']}`
- Access-layer validation pass carried forward: `{access_alignment['access_validation_passed']}`
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare and validate the thin downstream Knowledge Library grounding bridge.")
    parser.add_argument("--pointer", type=Path, default=DEFAULT_POINTER)
    parser.add_argument("--release_manifest", type=Path, default=None)
    parser.add_argument("--access_manifest", type=Path, default=DEFAULT_ACCESS_MANIFEST)
    parser.add_argument("--access_validation", type=Path, default=DEFAULT_ACCESS_VALIDATION)
    parser.add_argument("--out_root", type=Path, default=DEFAULT_OUT_ROOT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    pointer_path = _resolve_repo_path(args.pointer)
    release_manifest_path = _resolve_repo_path(args.release_manifest) if args.release_manifest is not None else None
    access_manifest_path = _resolve_repo_path(args.access_manifest)
    access_validation_path = _resolve_repo_path(args.access_validation)
    out_root = _resolve_repo_path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    run_id, out_dir = _choose_out_dir(out_root)
    out_dir.mkdir(parents=True, exist_ok=False)

    bridge = load_grounding_bridge(release_manifest_path=release_manifest_path, pointer_path=pointer_path)
    validation_bundle = validate_grounding_bridge(
        release_manifest_path=bridge.release.release_manifest_path,
        pointer_path=pointer_path,
    )
    release_summary = bridge.get_release_summary()
    retrieval_pointer = bridge.get_retrieval_pointer()

    access_manifest = _read_json(access_manifest_path)
    access_validation = _read_json(access_validation_path)

    access_alignment_issues: list[dict[str, Any]] = []
    access_validation_summary = access_validation["summary"]
    if access_validation_summary.get("overall_status") != "pass":
        access_alignment_issues.append(
            {
                "level": "ERROR",
                "code": "ACCESS_LAYER_VALIDATION_NOT_PASSING",
                "message": "Referenced access-layer validation bundle is not in pass state.",
                "artifact": _rel(access_validation_path),
                "record_id": None,
                "context": None,
            }
        )

    release_label_matches = access_manifest.get("release_label") == bridge.release.release_label
    if not release_label_matches:
        access_alignment_issues.append(
            {
                "level": "ERROR",
                "code": "ACCESS_LAYER_RELEASE_LABEL_MISMATCH",
                "message": "Access-layer bundle release label does not match the active grounding-bridge release.",
                "artifact": _rel(access_manifest_path),
                "record_id": None,
                "context": None,
            }
        )

    access_counts = access_manifest.get("loaded_counts") or {}
    count_alignment_passed = (
        int(access_counts.get("topics") or -1) == release_summary.topic_count
        and int(access_counts.get("kcs") or -1) == release_summary.kc_count
        and int(access_counts.get("graph_nodes") or -1) == release_summary.graph_node_count
        and int(access_counts.get("graph_edges") or -1) == release_summary.graph_edge_count
    )
    if not count_alignment_passed:
        access_alignment_issues.append(
            {
                "level": "ERROR",
                "code": "ACCESS_LAYER_COUNT_ALIGNMENT_FAILED",
                "message": "Access-layer counts do not match the grounding-bridge release summary.",
                "artifact": _rel(access_manifest_path),
                "record_id": None,
                "context": {
                    "access_counts": access_counts,
                    "bridge_counts": {
                        "topics": release_summary.topic_count,
                        "kcs": release_summary.kc_count,
                        "graph_nodes": release_summary.graph_node_count,
                        "graph_edges": release_summary.graph_edge_count,
                    },
                },
            }
        )

    combined_issues = [issue.to_row() for issue in validation_bundle.issues] + access_alignment_issues
    error_count = sum(1 for issue in combined_issues if issue["level"] == "ERROR")
    warning_count = sum(1 for issue in combined_issues if issue["level"] == "WARN")

    combined_summary = dict(validation_bundle.summary)
    combined_summary["overall_status"] = "pass" if error_count == 0 else "fail"
    combined_summary["issue_counts"] = {
        "error_count": error_count,
        "warning_count": warning_count,
        "total_issue_count": len(combined_issues),
    }

    access_alignment = {
        "access_layer_manifest_path": _rel(access_manifest_path),
        "access_layer_validation_results_path": _rel(access_validation_path),
        "release_label_matches": release_label_matches,
        "count_alignment_passed": count_alignment_passed,
        "access_validation_passed": access_validation_summary.get("overall_status") == "pass",
    }

    smoke = combined_summary["smoke_examples"]
    topic_bundle = bridge.get_topic_bundle(smoke["topic_bundle_topic_id"]) if smoke["topic_bundle_topic_id"] else None
    topic_grounding = (
        bridge.get_topic_grounding(smoke["topic_grounding_topic_id"])
        if smoke["topic_grounding_topic_id"]
        else None
    )
    kc_bundle = bridge.get_kc_bundle(smoke["kc_bundle_kc_id"]) if smoke["kc_bundle_kc_id"] else None

    created_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    grounding_bridge_validation_results = {
        "schema_version": "knowledge_library.grounding_bridge_validation_result.v1",
        "run_id": run_id,
        "created_utc": created_utc,
        "summary": combined_summary,
        "access_layer_alignment": access_alignment,
        "issues": combined_issues,
    }

    grounding_bridge_manifest = {
        "schema_version": "knowledge_library.grounding_bridge_manifest.v1",
        "run_id": run_id,
        "created_utc": created_utc,
        "package_status": "knowledge_library_grounding_bridge_prepared",
        "active_release_pointer": _rel(pointer_path),
        "resolved_release_manifest": _rel(bridge.release.release_manifest_path),
        "release_label": bridge.release.release_label,
        "code_paths": {
            "access_py": "src/kc_l/knowledge_library/access.py",
            "grounding_bridge_py": "src/kc_l/knowledge_library/grounding_bridge.py",
            "runner_py": "steps/step_01_9_knowledge_library_grounding_bridge/scripts/run_step01_9_knowledge_library_grounding_bridge.py",
        },
        "source_paths": {
            "access_layer_manifest_json": _rel(access_manifest_path),
            "access_layer_validation_results_json": _rel(access_validation_path),
            "topic_library_jsonl": _rel(bridge.release.topic_library_path),
            "topic_boundary_json": _rel(bridge.release.topic_boundary_path),
            "kc_library_jsonl": _rel(bridge.release.kc_library_path),
            "kc_manifest_json": _rel(bridge.release.kc_manifest_path),
            "graph_nodes_jsonl": _rel(bridge.release.graph_nodes_path),
            "graph_edges_jsonl": _rel(bridge.release.graph_edges_path),
            "graph_manifest_json": _rel(bridge.release.graph_manifest_path),
            "schema_manifest_json": _rel(bridge.release.schema_manifest_path),
            "validation_results_json": _rel(bridge.release.validation_results_path),
            "retrieval_manifest_json": _rel(retrieval_pointer.manifest_path) if retrieval_pointer is not None else None,
        },
        "helper_surface": [
            "load_grounding_bridge",
            "get_release_summary",
            "get_topic_bundle",
            "get_topic_grounding",
            "get_topic_kc_candidates",
            "get_kc_bundle",
            "get_retrieval_pointer",
        ],
        "loaded_counts": {
            "topics": release_summary.topic_count,
            "kcs": release_summary.kc_count,
            "graph_nodes": release_summary.graph_node_count,
            "graph_edges": release_summary.graph_edge_count,
        },
        "retrieval_pointer": retrieval_pointer.to_row() if retrieval_pointer is not None else None,
        "semantics": release_summary.semantics,
        "access_layer_alignment": access_alignment,
        "validation_outcome": combined_summary,
        "invariants": {
            "topic_and_kc_layers_remain_separate": True,
            "graph_semantics_remain_conservative": True,
            "upstream_release_and_source_bundles_untouched": True,
            "retrieval_not_rebuilt": True,
            "kc_specific_criteria_touched": False,
        },
        "outputs": {
            "grounding_bridge_manifest_json": _rel(out_dir / "grounding_bridge_manifest.json"),
            "grounding_bridge_report_md": _rel(out_dir / "grounding_bridge_report.md"),
            "grounding_bridge_validation_results_json": _rel(out_dir / "grounding_bridge_validation_results.json"),
            "grounding_bridge_validation_summary_md": _rel(out_dir / "grounding_bridge_validation_summary.md"),
            "grounding_bridge_examples_json": _rel(out_dir / "grounding_bridge_examples.json"),
        },
    }

    examples = {
        "release_summary": release_summary.to_row(),
        "topic_bundle_example": topic_bundle.to_row() if topic_bundle is not None else None,
        "topic_grounding_example": topic_grounding.to_row() if topic_grounding is not None else None,
        "kc_bundle_example": kc_bundle.to_row() if kc_bundle is not None else None,
        "retrieval_pointer": retrieval_pointer.to_row() if retrieval_pointer is not None else None,
    }

    _write_json(out_dir / "grounding_bridge_manifest.json", grounding_bridge_manifest)
    (out_dir / "grounding_bridge_report.md").write_text(
        _build_report(bridge, combined_summary, access_alignment),
        encoding="utf-8",
    )
    _write_json(out_dir / "grounding_bridge_validation_results.json", grounding_bridge_validation_results)
    (out_dir / "grounding_bridge_validation_summary.md").write_text(
        _build_validation_summary(grounding_bridge_validation_results),
        encoding="utf-8",
    )
    _write_json(out_dir / "grounding_bridge_examples.json", examples)

    print(
        json.dumps(
            {
                "run_id": run_id,
                "out_dir": _rel(out_dir),
                "overall_status": combined_summary["overall_status"],
                "topic_count": release_summary.topic_count,
                "kc_count": release_summary.kc_count,
                "graph_nodes": release_summary.graph_node_count,
                "graph_edges": release_summary.graph_edge_count,
                "retrieval_pointer_present": retrieval_pointer is not None,
            },
            indent=2,
        )
    )
    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
