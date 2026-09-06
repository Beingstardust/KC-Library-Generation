from __future__ import annotations

from typing import Any, Mapping

from kc_l.topic.minimal_draft import _topic_id


def _text_list(values: Any) -> list[str]:
    return [str(value).strip() for value in values or [] if str(value).strip()]


def hierarchy_ancestry_from_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    nested = payload.get("hierarchy_ancestry")
    ancestry_payload = dict(nested) if isinstance(nested, Mapping) else dict(payload or {})
    return {
        "ancestor_hier_node_ids": _text_list(ancestry_payload.get("ancestor_hier_node_ids")),
        "ancestor_labels": _text_list(ancestry_payload.get("ancestor_labels")),
        "leaf_hier_node_id": str(ancestry_payload.get("leaf_hier_node_id") or "").strip(),
        "parent_hier_node_id": str(ancestry_payload.get("parent_hier_node_id") or "").strip(),
        "source_hierarchy_path": _text_list(ancestry_payload.get("source_hierarchy_path")),
    }


def typed_topic_hierarchy_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    ancestry = hierarchy_ancestry_from_payload(payload)
    source_hierarchy_path = list(ancestry.get("source_hierarchy_path") or [])
    topic_path_labels = source_hierarchy_path[:-1] if len(source_hierarchy_path) > 1 else list(ancestry.get("ancestor_labels") or [])
    topic_path_ids = [
        _topic_id(topic_path_labels[: index + 1])
        for index in range(len(topic_path_labels))
    ]
    parent_topic_id = topic_path_ids[-1] if topic_path_ids else None
    parent_topic_label = topic_path_labels[-1] if topic_path_labels else None
    ancestor_topic_labels = list(ancestry.get("ancestor_labels") or topic_path_labels)
    ancestor_topic_ids = [
        _topic_id(ancestor_topic_labels[: index + 1])
        for index in range(len(ancestor_topic_labels))
    ]
    return {
        "topic_path_ids": topic_path_ids,
        "topic_path_labels": topic_path_labels,
        "parent_topic_id": parent_topic_id,
        "parent_topic_label": parent_topic_label,
        "ancestor_topic_ids": ancestor_topic_ids,
        "ancestor_topic_labels": ancestor_topic_labels,
        "hierarchy_ancestry": ancestry,
    }
