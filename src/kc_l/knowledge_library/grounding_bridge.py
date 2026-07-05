from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from kc_l.knowledge_library.access import (
    KCLibraryRecord,
    KnowledgeLibraryReleaseAccess,
    RetrievalPointer,
    TopicLibraryRecord,
    load_release,
)
from kc_l.knowledge_library.contracts import ValidationIssue
from kc_l.runtime.library_state import DEFAULT_ACTIVE_LIBRARY_POINTER


TOPIC_HIERARCHY_SEMANTICS = "resolved structural hierarchy"
TOPIC_KC_CANDIDATE_SEMANTICS = "conservative candidate membership only"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class GraphNeighborhoodSummary:
    parent_topic_id: str | None
    child_topic_ids: tuple[str, ...]
    child_topic_titles: tuple[str, ...]
    candidate_kc_ids: tuple[str, ...]
    candidate_kc_titles: tuple[str, ...]
    topic_hierarchy_semantics: str = TOPIC_HIERARCHY_SEMANTICS
    topic_kc_semantics: str = TOPIC_KC_CANDIDATE_SEMANTICS

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TopicKCCandidateSummary:
    topic_id: str
    kc_id: str
    kc_title: str
    edge_id: str
    edge_status: str
    membership_semantics: str = TOPIC_KC_CANDIDATE_SEMANTICS
    justification: str = ""
    notes: str = ""

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TopicBundle:
    topic: TopicLibraryRecord
    graph_neighborhood: GraphNeighborhoodSummary

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TopicGroundingBundle:
    topic_bundle: TopicBundle
    child_topics: tuple[TopicLibraryRecord, ...]
    topic_kc_candidates: tuple[TopicKCCandidateSummary, ...]
    retrieval_pointer_present: bool

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class KCBundle:
    kc: KCLibraryRecord
    candidate_topic_ids: tuple[str, ...]
    candidate_topic_titles: tuple[str, ...]
    candidate_membership_semantics: str = TOPIC_KC_CANDIDATE_SEMANTICS
    retrieval_indexed: bool = False

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GroundingReleaseSummary:
    release_label: str
    resolved_release_manifest_path: str
    topic_count: int
    kc_count: int
    graph_node_count: int
    graph_edge_count: int
    excluded_topic_ids: tuple[str, ...]
    excluded_topic_titles: tuple[str, ...]
    retrieval_pointer_present: bool
    semantics: dict[str, str]

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GroundingBridgeValidationBundle:
    summary: dict[str, Any]
    issues: tuple[ValidationIssue, ...]

    @property
    def has_errors(self) -> bool:
        return any(issue.level == "ERROR" for issue in self.issues)


@dataclass
class KnowledgeLibraryGroundingBridge:
    release: KnowledgeLibraryReleaseAccess
    _topic_boundary: dict[str, Any] | None = field(default=None, init=False, repr=False)
    _kc_manifest: dict[str, Any] | None = field(default=None, init=False, repr=False)
    _reverse_kc_topics: dict[str, tuple[str, ...]] | None = field(default=None, init=False, repr=False)

    @property
    def excluded_topic_ids(self) -> set[str]:
        boundary = self._load_topic_boundary()
        return {
            str(row.get("topic_id"))
            for row in boundary.get("rescue_heavy_or_excluded_topics") or []
            if isinstance(row, dict) and row.get("topic_id")
        }

    @property
    def excluded_topic_titles(self) -> set[str]:
        boundary = self._load_topic_boundary()
        return {
            str(row.get("topic_title"))
            for row in boundary.get("rescue_heavy_or_excluded_topics") or []
            if isinstance(row, dict) and row.get("topic_title")
        }

    @property
    def approved_kc_ids(self) -> set[str]:
        manifest = self._load_kc_manifest()
        return {str(kc_id) for kc_id in manifest.get("included_kc_ids") or []}

    @property
    def excluded_kc_ids(self) -> set[str]:
        manifest = self._load_kc_manifest()
        excluded = set()
        for values in (manifest.get("excluded_from_frozen") or {}).values():
            if isinstance(values, list):
                excluded.update(str(value) for value in values)
        return excluded

    def _load_topic_boundary(self) -> dict[str, Any]:
        if self._topic_boundary is None:
            self._topic_boundary = _read_json(self.release.topic_boundary_path)
        return self._topic_boundary

    def _load_kc_manifest(self) -> dict[str, Any]:
        if self._kc_manifest is None:
            self._kc_manifest = _read_json(self.release.kc_manifest_path)
        return self._kc_manifest

    def _build_reverse_kc_topics(self) -> dict[str, tuple[str, ...]]:
        if self._reverse_kc_topics is None:
            reverse: dict[str, list[str]] = {}
            graph = self.release.load_graph()
            for topic_id, edges in graph.topic_kc_candidate_edges.items():
                for edge in edges:
                    target_node = graph.node_index.get(edge.target_node_id)
                    if target_node is None:
                        continue
                    reverse.setdefault(target_node.source_id, []).append(topic_id)
            self._reverse_kc_topics = {kc_id: tuple(topic_ids) for kc_id, topic_ids in reverse.items()}
        return self._reverse_kc_topics

    def get_release_summary(self) -> GroundingReleaseSummary:
        topics = self.release.load_topics()
        kcs = self.release.load_kcs()
        graph = self.release.load_graph()
        retrieval_pointer = self.get_retrieval_pointer()
        return GroundingReleaseSummary(
            release_label=self.release.release_label,
            resolved_release_manifest_path=self.release.release_manifest_path.as_posix(),
            topic_count=len(topics),
            kc_count=len(kcs),
            graph_node_count=len(graph.nodes),
            graph_edge_count=len(graph.edges),
            excluded_topic_ids=tuple(sorted(self.excluded_topic_ids)),
            excluded_topic_titles=tuple(sorted(self.excluded_topic_titles)),
            retrieval_pointer_present=retrieval_pointer is not None,
            semantics={
                "topic_contains_topic": TOPIC_HIERARCHY_SEMANTICS,
                "topic_contains_kc": TOPIC_KC_CANDIDATE_SEMANTICS,
            },
        )

    def get_topic_kc_candidates(self, topic_id: str) -> tuple[TopicKCCandidateSummary, ...]:
        topic = self.release.get_topic(topic_id)
        if topic is None or topic_id in self.excluded_topic_ids or topic.title in self.excluded_topic_titles:
            return ()

        candidate_rows = []
        for candidate in self.release.get_topic_kc_candidates(topic_id):
            candidate_rows.append(
                TopicKCCandidateSummary(
                    topic_id=topic_id,
                    kc_id=candidate.kc_id,
                    kc_title=candidate.kc.title,
                    edge_id=candidate.edge.edge_id,
                    edge_status=candidate.edge.status,
                    justification=candidate.edge.justification,
                    notes=candidate.edge.notes,
                )
            )
        return tuple(candidate_rows)

    def get_topic_bundle(self, topic_id: str) -> TopicBundle | None:
        topic = self.release.get_topic(topic_id)
        if topic is None or topic_id in self.excluded_topic_ids or topic.title in self.excluded_topic_titles:
            return None

        child_topics = self.release.get_topic_children(topic_id)
        candidate_kcs = self.get_topic_kc_candidates(topic_id)
        neighborhood = GraphNeighborhoodSummary(
            parent_topic_id=topic.parent_topic_id,
            child_topic_ids=tuple(child.topic_id for child in child_topics),
            child_topic_titles=tuple(child.title for child in child_topics),
            candidate_kc_ids=tuple(candidate.kc_id for candidate in candidate_kcs),
            candidate_kc_titles=tuple(candidate.kc_title for candidate in candidate_kcs),
        )
        return TopicBundle(topic=topic, graph_neighborhood=neighborhood)

    def get_topic_grounding(self, topic_id: str) -> TopicGroundingBundle | None:
        topic_bundle = self.get_topic_bundle(topic_id)
        if topic_bundle is None:
            return None
        child_topics = self.release.get_topic_children(topic_id)
        candidate_kcs = self.get_topic_kc_candidates(topic_id)
        return TopicGroundingBundle(
            topic_bundle=topic_bundle,
            child_topics=child_topics,
            topic_kc_candidates=candidate_kcs,
            retrieval_pointer_present=self.get_retrieval_pointer() is not None,
        )

    def get_kc_bundle(self, kc_id: str) -> KCBundle | None:
        kc = self.release.get_kc(kc_id)
        if kc is None or kc_id not in self.approved_kc_ids:
            return None

        reverse_topics = self._build_reverse_kc_topics().get(kc_id, ())
        candidate_topic_titles = []
        for topic_id in reverse_topics:
            topic = self.release.get_topic(topic_id)
            if topic is not None:
                candidate_topic_titles.append(topic.title)

        retrieval_pointer = self.get_retrieval_pointer()
        retrieval_indexed = retrieval_pointer is not None and kc_id in retrieval_pointer.included_kc_ids
        return KCBundle(
            kc=kc,
            candidate_topic_ids=tuple(reverse_topics),
            candidate_topic_titles=tuple(candidate_topic_titles),
            retrieval_indexed=retrieval_indexed,
        )

    def get_retrieval_pointer(self) -> RetrievalPointer | None:
        return self.release.get_retrieval_pointer()


def load_grounding_bridge(
    *,
    release_manifest_path: str | Path | None = None,
    pointer_path: str | Path | None = None,
) -> KnowledgeLibraryGroundingBridge:
    return KnowledgeLibraryGroundingBridge(
        release=load_release(release_manifest_path=release_manifest_path, pointer_path=pointer_path)
    )


def get_release_summary(
    bridge: KnowledgeLibraryGroundingBridge | None = None,
) -> GroundingReleaseSummary:
    active_bridge = bridge or load_grounding_bridge()
    return active_bridge.get_release_summary()


def get_topic_bundle(
    topic_id: str,
    bridge: KnowledgeLibraryGroundingBridge | None = None,
) -> TopicBundle | None:
    active_bridge = bridge or load_grounding_bridge()
    return active_bridge.get_topic_bundle(topic_id)


def get_kc_bundle(
    kc_id: str,
    bridge: KnowledgeLibraryGroundingBridge | None = None,
) -> KCBundle | None:
    active_bridge = bridge or load_grounding_bridge()
    return active_bridge.get_kc_bundle(kc_id)


def get_topic_grounding(
    topic_id: str,
    bridge: KnowledgeLibraryGroundingBridge | None = None,
) -> TopicGroundingBundle | None:
    active_bridge = bridge or load_grounding_bridge()
    return active_bridge.get_topic_grounding(topic_id)


def get_topic_kc_candidates(
    topic_id: str,
    bridge: KnowledgeLibraryGroundingBridge | None = None,
) -> tuple[TopicKCCandidateSummary, ...]:
    active_bridge = bridge or load_grounding_bridge()
    return active_bridge.get_topic_kc_candidates(topic_id)


def get_retrieval_pointer(
    bridge: KnowledgeLibraryGroundingBridge | None = None,
) -> RetrievalPointer | None:
    active_bridge = bridge or load_grounding_bridge()
    return active_bridge.get_retrieval_pointer()


def validate_grounding_bridge(
    *,
    release_manifest_path: str | Path | None = None,
    pointer_path: str | Path | None = None,
) -> GroundingBridgeValidationBundle:
    issues: list[ValidationIssue] = []
    try:
        bridge = load_grounding_bridge(
            release_manifest_path=release_manifest_path,
            pointer_path=pointer_path,
        )
    except Exception as exc:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="GROUNDING_BRIDGE_RELEASE_RESOLUTION_FAILED",
                message=str(exc),
                artifact=str(pointer_path or DEFAULT_ACTIVE_LIBRARY_POINTER),
            )
        )
        return GroundingBridgeValidationBundle(
            summary={
                "schema_version": "knowledge_library.grounding_bridge_validation.v1",
                "overall_status": "fail",
                "release_resolution_succeeded": False,
                "issue_counts": {
                    "error_count": 1,
                    "warning_count": 0,
                    "total_issue_count": 1,
                },
            },
            issues=tuple(issues),
        )

    release = bridge.release
    topics = release.load_topics()
    kcs = release.load_kcs()
    graph = release.load_graph()
    summary = bridge.get_release_summary()
    retrieval_pointer = bridge.get_retrieval_pointer()

    if summary.topic_count != len(topics):
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="GROUNDING_RELEASE_TOPIC_COUNT_MISMATCH",
                message="Grounding bridge release summary topic count does not match access layer topics.",
                artifact=release.release_manifest_path.as_posix(),
            )
        )
    if summary.kc_count != len(kcs):
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="GROUNDING_RELEASE_KC_COUNT_MISMATCH",
                message="Grounding bridge release summary KC count does not match access layer KCs.",
                artifact=release.release_manifest_path.as_posix(),
            )
        )
    if summary.graph_node_count != len(graph.nodes) or summary.graph_edge_count != len(graph.edges):
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="GROUNDING_RELEASE_GRAPH_COUNT_MISMATCH",
                message="Grounding bridge release summary graph counts do not match the access layer graph.",
                artifact=release.release_manifest_path.as_posix(),
            )
        )

    representative_topic = min(topics, key=lambda topic: topic.topic_id) if topics else None
    representative_grounding_topic = next(
        (topic for topic in sorted(topics, key=lambda row: row.topic_id) if bridge.get_topic_kc_candidates(topic.topic_id)),
        representative_topic,
    )
    representative_kc = min(kcs, key=lambda kc: kc.kc_id) if kcs else None
    excluded_topic_id = min(bridge.excluded_topic_ids) if bridge.excluded_topic_ids else None
    nonapproved_kc_id = min(bridge.excluded_kc_ids) if bridge.excluded_kc_ids else None

    topic_bundle = bridge.get_topic_bundle(representative_topic.topic_id) if representative_topic is not None else None
    topic_grounding = (
        bridge.get_topic_grounding(representative_grounding_topic.topic_id)
        if representative_grounding_topic is not None
        else None
    )
    kc_bundle = bridge.get_kc_bundle(representative_kc.kc_id) if representative_kc is not None else None

    if representative_topic is not None and topic_bundle is None:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="REPRESENTATIVE_TOPIC_BUNDLE_MISSING",
                message=f"Bridge could not return a topic bundle for {representative_topic.topic_id}.",
                artifact=release.topic_library_path.as_posix(),
            )
        )
    if representative_kc is not None and kc_bundle is None:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="REPRESENTATIVE_KC_BUNDLE_MISSING",
                message=f"Bridge could not return a KC bundle for {representative_kc.kc_id}.",
                artifact=release.kc_library_path.as_posix(),
            )
        )
    if representative_grounding_topic is not None and topic_grounding is None:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="REPRESENTATIVE_TOPIC_GROUNDING_MISSING",
                message=f"Bridge could not return grounding for {representative_grounding_topic.topic_id}.",
                artifact=release.graph_edges_path.as_posix(),
            )
        )

    if excluded_topic_id is not None and bridge.get_topic_bundle(excluded_topic_id) is not None:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="EXCLUDED_TOPIC_EXPOSED_BY_BRIDGE",
                message=f"Excluded topic leaked through the grounding bridge: {excluded_topic_id}.",
                artifact=release.topic_boundary_path.as_posix(),
            )
        )
    if nonapproved_kc_id is not None and bridge.get_kc_bundle(nonapproved_kc_id) is not None:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="NONAPPROVED_KC_EXPOSED_BY_BRIDGE",
                message=f"Non-approved KC leaked through the grounding bridge: {nonapproved_kc_id}.",
                artifact=release.kc_manifest_path.as_posix(),
            )
        )

    if release.retrieval_manifest_path is not None:
        if retrieval_pointer is None or not retrieval_pointer.manifest_path.exists():
            issues.append(
                ValidationIssue(
                    level="ERROR",
                    code="GROUNDING_RETRIEVAL_POINTER_MISSING",
                    message="Grounding bridge did not expose the expected read-only retrieval pointer.",
                    artifact=release.kc_manifest_path.as_posix(),
                )
            )

    if summary.semantics.get("topic_contains_topic") != TOPIC_HIERARCHY_SEMANTICS:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="TOPIC_HIERARCHY_SEMANTICS_RELABELLED",
                message="Grounding bridge relabeled topic hierarchy semantics.",
                artifact=release.graph_manifest_path.as_posix(),
            )
        )
    if summary.semantics.get("topic_contains_kc") != TOPIC_KC_CANDIDATE_SEMANTICS:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="TOPIC_KC_SEMANTICS_RELABELLED",
                message="Grounding bridge relabeled topic-to-KC semantics.",
                artifact=release.graph_manifest_path.as_posix(),
            )
        )

    if topic_bundle is not None:
        if topic_bundle.graph_neighborhood.topic_hierarchy_semantics != TOPIC_HIERARCHY_SEMANTICS:
            issues.append(
                ValidationIssue(
                    level="ERROR",
                    code="TOPIC_BUNDLE_HIERARCHY_SEMANTICS_RELABELLED",
                    message="Topic bundle graph neighborhood relabeled topic hierarchy semantics.",
                    artifact=release.graph_edges_path.as_posix(),
                )
            )
        if topic_bundle.graph_neighborhood.topic_kc_semantics != TOPIC_KC_CANDIDATE_SEMANTICS:
            issues.append(
                ValidationIssue(
                    level="ERROR",
                    code="TOPIC_BUNDLE_KC_SEMANTICS_RELABELLED",
                    message="Topic bundle graph neighborhood relabeled topic-to-KC semantics.",
                    artifact=release.graph_edges_path.as_posix(),
                )
            )

    if topic_grounding is not None:
        for candidate in topic_grounding.topic_kc_candidates:
            if candidate.membership_semantics != TOPIC_KC_CANDIDATE_SEMANTICS:
                issues.append(
                    ValidationIssue(
                        level="ERROR",
                        code="CANDIDATE_MEMBERSHIP_RELABELLED",
                        message=f"Candidate membership semantics changed for {candidate.kc_id}.",
                        artifact=release.graph_edges_path.as_posix(),
                        record_id=candidate.edge_id,
                    )
                )
            if candidate.edge_status != "conservative_candidate":
                issues.append(
                    ValidationIssue(
                        level="ERROR",
                        code="CANDIDATE_EDGE_STATUS_NOT_CONSERVATIVE",
                        message=f"Expected conservative_candidate status for {candidate.edge_id}, found {candidate.edge_status}.",
                        artifact=release.graph_edges_path.as_posix(),
                        record_id=candidate.edge_id,
                    )
                )

    if kc_bundle is not None and kc_bundle.candidate_membership_semantics != TOPIC_KC_CANDIDATE_SEMANTICS:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="KC_BUNDLE_KC_SEMANTICS_RELABELLED",
                message="KC bundle relabeled reverse candidate membership semantics.",
                artifact=release.graph_edges_path.as_posix(),
            )
        )

    error_count = sum(1 for issue in issues if issue.level == "ERROR")
    warning_count = sum(1 for issue in issues if issue.level == "WARN")
    result_summary = {
        "schema_version": "knowledge_library.grounding_bridge_validation.v1",
        "overall_status": "pass" if error_count == 0 else "fail",
        "release_resolution_succeeded": True,
        "release_label": release.release_label,
        "resolved_release_manifest_path": release.release_manifest_path.as_posix(),
        "issue_counts": {
            "error_count": error_count,
            "warning_count": warning_count,
            "total_issue_count": len(issues),
        },
        "loaded_counts": {
            "topics": len(topics),
            "kcs": len(kcs),
            "graph_nodes": len(graph.nodes),
            "graph_edges": len(graph.edges),
        },
        "smoke_examples": {
            "topic_bundle_topic_id": representative_topic.topic_id if representative_topic is not None else None,
            "topic_grounding_topic_id": (
                representative_grounding_topic.topic_id if representative_grounding_topic is not None else None
            ),
            "kc_bundle_kc_id": representative_kc.kc_id if representative_kc is not None else None,
            "excluded_topic_id_checked": excluded_topic_id,
            "nonapproved_kc_id_checked": nonapproved_kc_id,
        },
        "checks": {
            "release_summary_available": True,
            "topic_bundle_available": topic_bundle is not None,
            "kc_bundle_available": kc_bundle is not None,
            "topic_grounding_available": topic_grounding is not None,
            "excluded_topics_hidden": excluded_topic_id is None or bridge.get_topic_bundle(excluded_topic_id) is None,
            "nonapproved_kcs_hidden": nonapproved_kc_id is None or bridge.get_kc_bundle(nonapproved_kc_id) is None,
            "retrieval_pointer_present": retrieval_pointer is not None,
        },
        "retrieval_pointer": {
            "present": retrieval_pointer is not None,
            "manifest_exists": retrieval_pointer.manifest_path.exists() if retrieval_pointer is not None else None,
            "manifest_path": retrieval_pointer.manifest_path.as_posix() if retrieval_pointer is not None else None,
        },
        "semantics": {
            "topic_contains_topic": TOPIC_HIERARCHY_SEMANTICS,
            "topic_contains_kc": TOPIC_KC_CANDIDATE_SEMANTICS,
        },
    }
    return GroundingBridgeValidationBundle(summary=result_summary, issues=tuple(issues))

