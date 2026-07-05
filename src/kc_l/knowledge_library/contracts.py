from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal


KNOWLEDGE_LIBRARY_CONTRACT_VERSION = "knowledge_library.contract.v1"
KNOWLEDGE_LIBRARY_VALIDATION_VERSION = "knowledge_library.validation_result.v1"

KnowledgeLibraryNodeType = Literal["topic", "kc"]
KnowledgeLibraryEdgeType = Literal["topic_contains_topic", "topic_contains_kc"]
KnowledgeLibraryNodeStatus = Literal["approved", "edited_approved"]
KnowledgeLibraryEdgeStatus = Literal["resolved", "conservative_candidate", "excluded"]

ALLOWED_PILOT_NODE_TYPES = {"topic", "kc"}
ALLOWED_PILOT_EDGE_TYPES = {"topic_contains_topic", "topic_contains_kc"}
ALLOWED_PILOT_NODE_STATUSES = {"approved", "edited_approved"}
ALLOWED_PILOT_EDGE_STATUSES = {"resolved", "conservative_candidate", "excluded"}

CANONICAL_NODE_FIELDS = (
    "node_id",
    "node_type",
    "source_id",
    "title",
    "parent_id",
    "status",
    "provenance_ref",
    "payload",
)

CANONICAL_EDGE_FIELDS = (
    "edge_id",
    "edge_type",
    "source_node_id",
    "target_node_id",
    "status",
    "provenance_ref",
    "justification",
    "notes",
)

RAW_TOPIC_PAYLOAD_FIELD = "topic_payload"
RAW_KC_PAYLOAD_FIELD = "kc_payload"

TOPIC_PAYLOAD_REQUIRED_FIELDS = (
    "topic_level",
    "parent_source_id",
    "review_status",
    "final_decision_status",
    "library_tier",
)

KC_PAYLOAD_REQUIRED_FIELDS = (
    "canonical_name",
    "review_status",
    "final_decision_status",
    "library_tier",
    "family_root",
    "family_branch",
)


@dataclass(frozen=True)
class ValidationIssue:
    level: str
    code: str
    message: str
    artifact: str
    record_id: str | None = None
    context: dict[str, Any] | None = None

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TopicNodeRecord:
    node_id: str
    node_type: Literal["topic"]
    source_id: str
    title: str
    parent_id: str | None
    status: KnowledgeLibraryNodeStatus
    provenance_ref: dict[str, Any]
    payload: dict[str, Any]

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class KCNodeRecord:
    node_id: str
    node_type: Literal["kc"]
    source_id: str
    title: str
    parent_id: str | None
    status: KnowledgeLibraryNodeStatus
    provenance_ref: dict[str, Any]
    payload: dict[str, Any]

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GraphEdgeRecord:
    edge_id: str
    edge_type: KnowledgeLibraryEdgeType
    source_node_id: str
    target_node_id: str
    status: KnowledgeLibraryEdgeStatus
    provenance_ref: dict[str, Any]
    justification: str = ""
    notes: str = ""

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


def contract_overview() -> dict[str, Any]:
    return {
        "contract_version": KNOWLEDGE_LIBRARY_CONTRACT_VERSION,
        "canonical_node_fields": list(CANONICAL_NODE_FIELDS),
        "canonical_edge_fields": list(CANONICAL_EDGE_FIELDS),
        "allowed_pilot_node_types": sorted(ALLOWED_PILOT_NODE_TYPES),
        "allowed_pilot_edge_types": sorted(ALLOWED_PILOT_EDGE_TYPES),
        "allowed_pilot_node_statuses": sorted(ALLOWED_PILOT_NODE_STATUSES),
        "allowed_pilot_edge_statuses": sorted(ALLOWED_PILOT_EDGE_STATUSES),
        "raw_node_payload_aliases": {
            "topic": RAW_TOPIC_PAYLOAD_FIELD,
            "kc": RAW_KC_PAYLOAD_FIELD,
        },
        "topic_payload_required_fields": list(TOPIC_PAYLOAD_REQUIRED_FIELDS),
        "kc_payload_required_fields": list(KC_PAYLOAD_REQUIRED_FIELDS),
    }
