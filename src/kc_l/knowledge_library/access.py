from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

from kc_l.knowledge_library.contracts import GraphEdgeRecord, KCNodeRecord, TopicNodeRecord, ValidationIssue
from kc_l.knowledge_library.validation import normalize_edge_row, normalize_node_row
from kc_l.runtime.library_state import (
    DEFAULT_ACTIVE_LIBRARY_POINTER,
    resolve_active_release_manifest_path as resolve_active_library_manifest_path,
)
from kc_l.runtime.layout import REPO_ROOT


DEFAULT_ACTIVE_RELEASE_POINTER = DEFAULT_ACTIVE_LIBRARY_POINTER


@dataclass(frozen=True)
class TopicLibraryRecord:
    topic_id: str
    title: str
    parent_topic_id: str | None
    status: str
    provenance_ref: dict[str, Any]
    payload: dict[str, Any]

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class KCLibraryRecord:
    kc_id: str
    title: str
    status: str
    provenance_ref: dict[str, Any]
    payload: dict[str, Any]

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TopicKCCandidateRecord:
    topic_id: str
    kc_id: str
    edge: GraphEdgeRecord
    kc: KCLibraryRecord

    def to_row(self) -> dict[str, Any]:
        return {
            "topic_id": self.topic_id,
            "kc_id": self.kc_id,
            "edge": self.edge.to_row(),
            "kc": self.kc.to_row(),
        }


@dataclass(frozen=True)
class RetrievalPointer:
    manifest_path: Path
    manifest: dict[str, Any]
    retrieval_source_path: Path
    retrieval_index_path: Path
    retrieval_query_contract_path: Path
    top_k_default: int
    included_kc_ids: tuple[str, ...]

    def to_row(self) -> dict[str, Any]:
        return {
            "manifest_path": self.manifest_path.as_posix(),
            "retrieval_source_path": self.retrieval_source_path.as_posix(),
            "retrieval_index_path": self.retrieval_index_path.as_posix(),
            "retrieval_query_contract_path": self.retrieval_query_contract_path.as_posix(),
            "top_k_default": self.top_k_default,
            "included_kc_ids": list(self.included_kc_ids),
        }


@dataclass(frozen=True)
class GraphAccess:
    nodes: tuple[TopicNodeRecord | KCNodeRecord, ...]
    edges: tuple[GraphEdgeRecord, ...]
    node_index: dict[str, TopicNodeRecord | KCNodeRecord]
    topic_node_index: dict[str, TopicNodeRecord]
    kc_node_index: dict[str, KCNodeRecord]
    topic_children_source_ids: dict[str, tuple[str, ...]]
    topic_kc_candidate_edges: dict[str, tuple[GraphEdgeRecord, ...]]


@dataclass(frozen=True)
class AccessValidationBundle:
    summary: dict[str, Any]
    issues: tuple[ValidationIssue, ...]

    @property
    def has_errors(self) -> bool:
        return any(issue.level == "ERROR" for issue in self.issues)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _resolve_repo_path(raw_path: str | Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def _strip_payload(row: Mapping[str, Any], excluded_keys: set[str]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in excluded_keys}


def resolve_active_release_manifest_path(pointer_path: str | Path | None = None) -> Path:
    return resolve_active_library_manifest_path(pointer_path)


@dataclass
class KnowledgeLibraryReleaseAccess:
    release_manifest_path: Path
    manifest: dict[str, Any]
    pointer_path: Path | None = None
    retrieval_manifest_path: Path | None = None
    _topics: tuple[TopicLibraryRecord, ...] | None = field(default=None, init=False, repr=False)
    _topic_index: dict[str, TopicLibraryRecord] | None = field(default=None, init=False, repr=False)
    _kcs: tuple[KCLibraryRecord, ...] | None = field(default=None, init=False, repr=False)
    _kc_index: dict[str, KCLibraryRecord] | None = field(default=None, init=False, repr=False)
    _graph: GraphAccess | None = field(default=None, init=False, repr=False)
    _retrieval_pointer: RetrievalPointer | None | bool = field(default=False, init=False, repr=False)

    @property
    def release_dir(self) -> Path:
        return self.release_manifest_path.parent

    @property
    def release_label(self) -> str:
        return str(self.manifest.get("release_label") or self.release_manifest_path.stem)

    @property
    def topic_library_path(self) -> Path:
        return _resolve_repo_path(self.manifest["sources"]["topic_library_jsonl"])

    @property
    def topic_boundary_path(self) -> Path:
        return _resolve_repo_path(self.manifest["sources"]["topic_boundary_json"])

    @property
    def kc_library_path(self) -> Path:
        return _resolve_repo_path(self.manifest["sources"]["kc_library_jsonl"])

    @property
    def kc_manifest_path(self) -> Path:
        return _resolve_repo_path(self.manifest["sources"]["kc_manifest_json"])

    @property
    def graph_nodes_path(self) -> Path:
        return _resolve_repo_path(self.manifest["sources"]["graph_nodes_jsonl"])

    @property
    def graph_edges_path(self) -> Path:
        return _resolve_repo_path(self.manifest["sources"]["graph_edges_jsonl"])

    @property
    def graph_manifest_path(self) -> Path:
        return _resolve_repo_path(self.manifest["sources"]["graph_manifest_json"])

    @property
    def schema_manifest_path(self) -> Path:
        return _resolve_repo_path(self.manifest["sources"]["schema_manifest_json"])

    @property
    def validation_results_path(self) -> Path:
        return _resolve_repo_path(self.manifest["sources"]["validation_results_json"])

    @property
    def validation_summary_path(self) -> Path:
        return _resolve_repo_path(self.manifest["sources"]["validation_summary_md"])

    def load_topics(self) -> tuple[TopicLibraryRecord, ...]:
        if self._topics is None:
            rows = _read_jsonl(self.topic_library_path)
            topics = tuple(
                TopicLibraryRecord(
                    topic_id=str(row["topic_id"]),
                    title=str(row["topic_title"]),
                    parent_topic_id=row.get("parent_topic_id"),
                    status=str(row.get("status") or row.get("final_decision_status") or ""),
                    provenance_ref=dict(row.get("source_provenance") or {}),
                    payload=_strip_payload(
                        row,
                        {
                            "topic_id",
                            "topic_title",
                            "parent_topic_id",
                            "status",
                            "source_provenance",
                        },
                    ),
                )
                for row in rows
            )
            self._topics = topics
            self._topic_index = {topic.topic_id: topic for topic in topics}
        return self._topics

    def load_kcs(self) -> tuple[KCLibraryRecord, ...]:
        if self._kcs is None:
            rows = _read_jsonl(self.kc_library_path)
            kcs = tuple(
                KCLibraryRecord(
                    kc_id=str(row["kc_id"]),
                    title=str(row["title"]),
                    status=str(row.get("status") or row.get("final_decision_status") or ""),
                    provenance_ref=dict(row.get("source_provenance") or {}),
                    payload=_strip_payload(
                        row,
                        {
                            "kc_id",
                            "title",
                            "status",
                            "source_provenance",
                        },
                    ),
                )
                for row in rows
            )
            self._kcs = kcs
            self._kc_index = {kc.kc_id: kc for kc in kcs}
        return self._kcs

    def load_graph(self) -> GraphAccess:
        if self._graph is None:
            node_rows = _read_jsonl(self.graph_nodes_path)
            edge_rows = _read_jsonl(self.graph_edges_path)
            node_issues: list[ValidationIssue] = []
            edge_issues: list[ValidationIssue] = []
            nodes: list[TopicNodeRecord | KCNodeRecord] = []
            edges: list[GraphEdgeRecord] = []

            for row in node_rows:
                normalized, issues, _ = normalize_node_row(row, artifact=self.graph_nodes_path.as_posix())
                node_issues.extend(issues)
                if normalized is not None:
                    nodes.append(normalized)
            for row in edge_rows:
                normalized, issues = normalize_edge_row(row, artifact=self.graph_edges_path.as_posix())
                edge_issues.extend(issues)
                if normalized is not None:
                    edges.append(normalized)

            blocking = [issue for issue in (*node_issues, *edge_issues) if issue.level == "ERROR"]
            if blocking:
                raise ValueError(
                    "Graph bundle could not be normalized for access loading: "
                    + "; ".join(f"{issue.code}:{issue.message}" for issue in blocking[:10])
                )

            node_index: dict[str, TopicNodeRecord | KCNodeRecord] = {node.node_id: node for node in nodes}
            topic_node_index: dict[str, TopicNodeRecord] = {
                node.source_id: node for node in nodes if isinstance(node, TopicNodeRecord)
            }
            kc_node_index: dict[str, KCNodeRecord] = {
                node.source_id: node for node in nodes if isinstance(node, KCNodeRecord)
            }
            topic_children_source_ids: dict[str, list[str]] = {}
            topic_kc_candidate_edges: dict[str, list[GraphEdgeRecord]] = {}
            for edge in edges:
                source_node = node_index.get(edge.source_node_id)
                target_node = node_index.get(edge.target_node_id)
                if source_node is None or target_node is None:
                    continue
                if edge.edge_type == "topic_contains_topic" and isinstance(source_node, TopicNodeRecord) and isinstance(target_node, TopicNodeRecord):
                    topic_children_source_ids.setdefault(source_node.source_id, []).append(target_node.source_id)
                elif edge.edge_type == "topic_contains_kc" and isinstance(source_node, TopicNodeRecord) and isinstance(target_node, KCNodeRecord):
                    topic_kc_candidate_edges.setdefault(source_node.source_id, []).append(edge)

            self._graph = GraphAccess(
                nodes=tuple(nodes),
                edges=tuple(edges),
                node_index=node_index,
                topic_node_index=topic_node_index,
                kc_node_index=kc_node_index,
                topic_children_source_ids={key: tuple(value) for key, value in topic_children_source_ids.items()},
                topic_kc_candidate_edges={key: tuple(value) for key, value in topic_kc_candidate_edges.items()},
            )
        return self._graph

    def get_topic(self, topic_id: str) -> TopicLibraryRecord | None:
        self.load_topics()
        assert self._topic_index is not None
        return self._topic_index.get(topic_id)

    def get_kc(self, kc_id: str) -> KCLibraryRecord | None:
        self.load_kcs()
        assert self._kc_index is not None
        return self._kc_index.get(kc_id)

    def get_topic_children(self, topic_id: str) -> tuple[TopicLibraryRecord, ...]:
        graph = self.load_graph()
        self.load_topics()
        assert self._topic_index is not None
        child_ids = graph.topic_children_source_ids.get(topic_id, ())
        return tuple(self._topic_index[child_id] for child_id in child_ids if child_id in self._topic_index)

    def get_topic_kc_candidates(self, topic_id: str) -> tuple[TopicKCCandidateRecord, ...]:
        graph = self.load_graph()
        self.load_kcs()
        assert self._kc_index is not None
        candidates: list[TopicKCCandidateRecord] = []
        for edge in graph.topic_kc_candidate_edges.get(topic_id, ()):
            target_node = graph.node_index.get(edge.target_node_id)
            if isinstance(target_node, KCNodeRecord) and target_node.source_id in self._kc_index:
                candidates.append(
                    TopicKCCandidateRecord(
                        topic_id=topic_id,
                        kc_id=target_node.source_id,
                        edge=edge,
                        kc=self._kc_index[target_node.source_id],
                    )
                )
        return tuple(candidates)

    def get_retrieval_pointer(self) -> RetrievalPointer | None:
        if self.retrieval_manifest_path is None:
            return None
        if self._retrieval_pointer is False:
            manifest = _read_json(self.retrieval_manifest_path)
            artifacts = dict(manifest.get("retrieval_artifacts") or {})
            policy = dict(manifest.get("retrieval_policy") or {})
            pointer = RetrievalPointer(
                manifest_path=self.retrieval_manifest_path,
                manifest=dict(manifest),
                retrieval_source_path=_resolve_repo_path(artifacts["approved_only_retrieval_source_jsonl"]),
                retrieval_index_path=_resolve_repo_path(artifacts["approved_only_retrieval_index_json"]),
                retrieval_query_contract_path=_resolve_repo_path(artifacts["retrieval_query_contract_json"]),
                top_k_default=int(policy.get("top_k_default") or 0),
                included_kc_ids=tuple(str(kc_id) for kc_id in manifest.get("included_kc_ids") or []),
            )
            self._retrieval_pointer = pointer
        return self._retrieval_pointer if isinstance(self._retrieval_pointer, RetrievalPointer) else None


def load_release(
    *,
    release_manifest_path: str | Path | None = None,
    pointer_path: str | Path | None = None,
) -> KnowledgeLibraryReleaseAccess:
    resolved_manifest_path = (
        _resolve_repo_path(release_manifest_path)
        if release_manifest_path is not None
        else resolve_active_release_manifest_path(pointer_path)
    )
    manifest = _read_json(resolved_manifest_path)
    pointer_resolved = _resolve_repo_path(pointer_path) if pointer_path is not None else DEFAULT_ACTIVE_RELEASE_POINTER
    kc_bundle_dir = _resolve_repo_path(manifest["sources"]["kc_boundary_source_path"])
    retrieval_manifest_candidate = kc_bundle_dir / "approved_only_retrieval_manifest.json"
    retrieval_manifest_path = retrieval_manifest_candidate if retrieval_manifest_candidate.exists() else None
    return KnowledgeLibraryReleaseAccess(
        release_manifest_path=resolved_manifest_path,
        manifest=dict(manifest),
        pointer_path=pointer_resolved if pointer_resolved.exists() else None,
        retrieval_manifest_path=retrieval_manifest_path,
    )


def load_topics(release: KnowledgeLibraryReleaseAccess | None = None) -> tuple[TopicLibraryRecord, ...]:
    active_release = release or load_release()
    return active_release.load_topics()


def load_kcs(release: KnowledgeLibraryReleaseAccess | None = None) -> tuple[KCLibraryRecord, ...]:
    active_release = release or load_release()
    return active_release.load_kcs()


def load_graph(release: KnowledgeLibraryReleaseAccess | None = None) -> GraphAccess:
    active_release = release or load_release()
    return active_release.load_graph()


def get_topic(topic_id: str, release: KnowledgeLibraryReleaseAccess | None = None) -> TopicLibraryRecord | None:
    active_release = release or load_release()
    return active_release.get_topic(topic_id)


def get_kc(kc_id: str, release: KnowledgeLibraryReleaseAccess | None = None) -> KCLibraryRecord | None:
    active_release = release or load_release()
    return active_release.get_kc(kc_id)


def get_topic_children(topic_id: str, release: KnowledgeLibraryReleaseAccess | None = None) -> tuple[TopicLibraryRecord, ...]:
    active_release = release or load_release()
    return active_release.get_topic_children(topic_id)


def get_topic_kc_candidates(
    topic_id: str,
    release: KnowledgeLibraryReleaseAccess | None = None,
) -> tuple[TopicKCCandidateRecord, ...]:
    active_release = release or load_release()
    return active_release.get_topic_kc_candidates(topic_id)


def validate_release_access(
    *,
    release_manifest_path: str | Path | None = None,
    pointer_path: str | Path | None = None,
) -> AccessValidationBundle:
    issues: list[ValidationIssue] = []
    try:
        release = load_release(release_manifest_path=release_manifest_path, pointer_path=pointer_path)
    except Exception as exc:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="ACTIVE_RELEASE_RESOLUTION_FAILED",
                message=str(exc),
                artifact=str(pointer_path or DEFAULT_ACTIVE_RELEASE_POINTER),
            )
        )
        return AccessValidationBundle(
            summary={
                "schema_version": "knowledge_library.access_validation.v1",
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

    manifest = release.manifest
    for path in (
        release.release_manifest_path,
        release.topic_library_path,
        release.topic_boundary_path,
        release.kc_library_path,
        release.kc_manifest_path,
        release.graph_nodes_path,
        release.graph_edges_path,
        release.graph_manifest_path,
        release.schema_manifest_path,
        release.validation_results_path,
    ):
        if not path.exists():
            issues.append(
                ValidationIssue(
                    level="ERROR",
                    code="MISSING_RELEASE_SOURCE",
                    message=f"Referenced release source does not exist: {path}",
                    artifact=release.release_manifest_path.as_posix(),
                )
            )

    topics = release.load_topics()
    kcs = release.load_kcs()
    graph = release.load_graph()
    topic_boundary = _read_json(release.topic_boundary_path)
    kc_manifest = _read_json(release.kc_manifest_path)
    graph_manifest = _read_json(release.graph_manifest_path)

    excluded_topic_ids = {
        str(row.get("topic_id"))
        for row in topic_boundary.get("rescue_heavy_or_excluded_topics") or []
        if isinstance(row, Mapping)
    }
    excluded_topic_titles = {
        str(row.get("topic_title"))
        for row in topic_boundary.get("rescue_heavy_or_excluded_topics") or []
        if isinstance(row, Mapping)
    }
    included_kc_ids = {str(kc_id) for kc_id in kc_manifest.get("included_kc_ids") or []}

    if len(topics) != int(manifest["counts"]["resolved_reviewed_topics"]):
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="TOPIC_COUNT_MISMATCH",
                message=(
                    f"Access layer loaded {len(topics)} topics, expected {manifest['counts']['resolved_reviewed_topics']} from release boundary."
                ),
                artifact=release.topic_library_path.as_posix(),
            )
        )
    if len(kcs) != int(manifest["counts"]["approved_frozen_kcs"]):
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="KC_COUNT_MISMATCH",
                message=f"Access layer loaded {len(kcs)} KCs, expected {manifest['counts']['approved_frozen_kcs']} from release boundary.",
                artifact=release.kc_library_path.as_posix(),
            )
        )

    leaked_topics = [topic.topic_id for topic in topics if topic.topic_id in excluded_topic_ids or topic.title in excluded_topic_titles]
    if leaked_topics:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="EXCLUDED_TOPICS_EXPOSED",
                message=f"Excluded topics leaked into usable topic access: {leaked_topics}",
                artifact=release.topic_library_path.as_posix(),
            )
        )

    nonapproved_kcs = [kc.kc_id for kc in kcs if kc.kc_id not in included_kc_ids]
    if nonapproved_kcs:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="NONAPPROVED_KCS_EXPOSED",
                message=f"Non-approved KCs leaked into usable KC access: {nonapproved_kcs}",
                artifact=release.kc_library_path.as_posix(),
            )
        )

    if len(graph.nodes) != int(manifest["counts"]["graph_nodes"]):
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="GRAPH_NODE_COUNT_MISMATCH",
                message=f"Access layer loaded {len(graph.nodes)} graph nodes, expected {manifest['counts']['graph_nodes']}.",
                artifact=release.graph_nodes_path.as_posix(),
            )
        )
    if len(graph.edges) != int(manifest["counts"]["graph_edges"]):
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="GRAPH_EDGE_COUNT_MISMATCH",
                message=f"Access layer loaded {len(graph.edges)} graph edges, expected {manifest['counts']['graph_edges']}.",
                artifact=release.graph_edges_path.as_posix(),
            )
        )

    graph_missing_endpoints = [
        edge.edge_id
        for edge in graph.edges
        if edge.source_node_id not in graph.node_index or edge.target_node_id not in graph.node_index
    ]
    if graph_missing_endpoints:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="GRAPH_EDGE_ENDPOINTS_MISSING",
                message=f"Graph edges point to missing nodes: {graph_missing_endpoints}",
                artifact=release.graph_edges_path.as_posix(),
            )
        )

    topic_node_source_ids = {node.source_id for node in graph.topic_node_index.values()}
    kc_node_source_ids = {node.source_id for node in graph.kc_node_index.values()}
    if topic_node_source_ids != {topic.topic_id for topic in topics}:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="GRAPH_TOPIC_NODE_SET_MISMATCH",
                message="Graph topic node source ids do not match usable topic access ids.",
                artifact=release.graph_manifest_path.as_posix(),
            )
        )
    if kc_node_source_ids != {kc.kc_id for kc in kcs}:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="GRAPH_KC_NODE_SET_MISMATCH",
                message="Graph KC node source ids do not match usable KC access ids.",
                artifact=release.graph_manifest_path.as_posix(),
            )
        )

    retrieval_pointer = release.get_retrieval_pointer()
    retrieval_manifest_exists = retrieval_pointer is not None and retrieval_pointer.manifest_path.exists()
    if release.retrieval_manifest_path is not None and not retrieval_manifest_exists:
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="MISSING_RETRIEVAL_MANIFEST",
                message=f"Expected retrieval manifest does not exist: {release.retrieval_manifest_path}",
                artifact=release.kc_manifest_path.as_posix(),
            )
        )

    graph_counts = dict(graph_manifest.get("counts") or {})
    if int(graph_counts.get("topic_nodes") or 0) != len(graph.topic_node_index):
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="GRAPH_TOPIC_COUNT_BUNDLE_MISMATCH",
                message="Loaded graph topic count does not match referenced graph manifest.",
                artifact=release.graph_manifest_path.as_posix(),
            )
        )
    if int(graph_counts.get("kc_nodes") or 0) != len(graph.kc_node_index):
        issues.append(
            ValidationIssue(
                level="ERROR",
                code="GRAPH_KC_COUNT_BUNDLE_MISMATCH",
                message="Loaded graph KC count does not match referenced graph manifest.",
                artifact=release.graph_manifest_path.as_posix(),
            )
        )

    error_count = sum(1 for issue in issues if issue.level == "ERROR")
    warning_count = sum(1 for issue in issues if issue.level == "WARN")
    summary = {
        "schema_version": "knowledge_library.access_validation.v1",
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
            "graph_topic_nodes": len(graph.topic_node_index),
            "graph_kc_nodes": len(graph.kc_node_index),
        },
        "boundary_checks": {
            "excluded_topics_exposed": len(leaked_topics),
            "nonapproved_kcs_exposed": len(nonapproved_kcs),
            "edges_with_missing_nodes": len(graph_missing_endpoints),
        },
        "retrieval_pointer": {
            "present": retrieval_pointer is not None,
            "manifest_exists": retrieval_manifest_exists if release.retrieval_manifest_path is not None else None,
            "manifest_path": release.retrieval_manifest_path.as_posix() if release.retrieval_manifest_path is not None else None,
        },
        "semantics": {
            "topic_contains_topic": "resolved structural hierarchy",
            "topic_contains_kc": "conservative candidate membership only",
        },
    }
    return AccessValidationBundle(summary=summary, issues=tuple(issues))

