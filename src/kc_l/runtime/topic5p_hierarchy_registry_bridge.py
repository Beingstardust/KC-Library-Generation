from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from kc_l.runtime.step5p_hierarchy_registry_bridge import (
    resolve_hierarchy_overlay_jsonl_from_output_root,
    resolve_sentence_overlay_jsonl_from_output_root,
)
from kc_l.utils.json_io import read_jsonl, write_jsonl

TOPIC_REGISTRY_SCHEMA_VERSION = "topic_registry_from_hierarchy_registry_v1"
TOPIC_EDGE_SCHEMA_VERSION = "topic_to_kc_edge_from_hierarchy_registry_v1"

# Re-exported so callers only need to import this one module for topic_05p's full input
# resolution - both functions are generic hierarchy_registry/step_04_5 output resolvers with
# nothing step5p-specific in their own logic, confirmed by reading them directly.
__all__ = [
    "resolve_hierarchy_overlay_jsonl_from_output_root",
    "resolve_sentence_overlay_jsonl_from_output_root",
    "extract_topic_registry_and_edges",
]


def extract_topic_registry_and_edges(
    *,
    hierarchy_overlay_jsonl: Path,
    out_dir: Path,
) -> Tuple[Path, Path]:
    """Derive topic_05p/topic_05x's two required inputs directly from hierarchy_registry's
    real output, replacing the one-off reconstructed-registry workaround
    (data/processed/topic_reconstructed_registry/... - self-documented as "not the missing
    human-reviewed topic final-resolution artifact").

    There is no separate topic registry: the KC hierarchy IS the topic hierarchy.
    hierarchy_overlay.jsonl already carries the full tree - node_type=="leaf" rows are KCs,
    node_type=="topic" rows are every internal node plus the root. A "topic unit" (in the sense
    topic_05p/topic_05x need) is precisely a "topic" node whose children are all KC leaves
    directly - confirmed by an exact 1:1 match (same labels, same KC counts, same hier_node_id
    hashes) against the historical reconstructed registry's 21 topic rows on a real 171-row
    hierarchy_overlay.jsonl. Higher-level aggregator nodes (the root, plus category nodes like
    "Classification"/"Clustering" whose children are OTHER topic nodes, not KC leaves) are
    deliberately excluded - they were never part of the reconstructed registry either.
    """
    rows = read_jsonl(hierarchy_overlay_jsonl)

    label_by_kc_id: Dict[str, str] = {
        str(row["kc_id"]): str(row.get("label") or row["kc_id"])
        for row in rows
        if row.get("node_type") == "leaf" and row.get("kc_id")
    }

    topic_rows = [
        row
        for row in rows
        if row.get("node_type") == "topic"
        and row.get("child_hier_node_ids")
        and all(str(c).startswith("kc::") for c in row["child_hier_node_ids"])
    ]

    if not topic_rows:
        raise ValueError(
            f"No direct-KC-parent topic nodes found in {hierarchy_overlay_jsonl} - cannot "
            "build a topic registry from this hierarchy_registry output"
        )

    registry_rows: List[Dict[str, Any]] = []
    edge_rows: List[Dict[str, Any]] = []

    for row in topic_rows:
        topic_id = str(row["hier_node_id"])
        topic_label = str(row.get("label") or topic_id)
        contained_kc_ids = [str(k) for k in row.get("descendant_kc_ids", [])]
        contained_kc_labels = [label_by_kc_id.get(kc_id, kc_id) for kc_id in contained_kc_ids]

        registry_rows.append(
            {
                "schema_version": TOPIC_REGISTRY_SCHEMA_VERSION,
                "knowledge_unit_type": "topic",
                "topic_id": topic_id,
                "topic_label": topic_label,
                "topic_path": list(row.get("source_hierarchy_path") or [topic_label]),
                "contained_kc_ids": contained_kc_ids,
                "contained_kc_labels": contained_kc_labels,
                "hierarchy_description_raw": row.get("hierarchy_description_raw", ""),
                "source": "hierarchy_registry_direct_extraction",
                "source_hier_node_id": topic_id,
            }
        )

        for kc_id in contained_kc_ids:
            edge_rows.append(
                {
                    "schema_version": TOPIC_EDGE_SCHEMA_VERSION,
                    "edge_type": "topic_contains_kc",
                    "topic_id": topic_id,
                    "topic_label": topic_label,
                    "kc_id": kc_id,
                    "kc_label": label_by_kc_id.get(kc_id, kc_id),
                    "source": "hierarchy_registry_direct_extraction",
                }
            )

    registry_path = out_dir / "topic_registry_from_hierarchy_registry.jsonl"
    edges_path = out_dir / "topic_to_kc_edges_from_hierarchy_registry.jsonl"
    write_jsonl(registry_path, registry_rows)
    write_jsonl(edges_path, edge_rows)
    return registry_path, edges_path
