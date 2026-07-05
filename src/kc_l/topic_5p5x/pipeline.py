from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

from kc_l.retrieval_profile.builder import build_profiles
from kc_l.retrieval_gate.evidence_stage_v3_candidate_bank import (
    resolve_repo_path,
    run_candidate_bank_stage,
)
from kc_l.retrieval_gate.evidence_stage_v3_scored_candidates import (
    build_scored_candidate_artifacts,
    load_candidate_bank_rows,
)
from kc_l.retrieval_gate.evidence_stage_v3_pack_composition import (
    build_evidence_pack_artifacts,
    load_scored_candidate_rows,
)

TOPIC_WRAPPER_VERSION = "topic_5p5x_typed_wrappers_v1_20260519"
TOPIC_PROFILE_STAGE = "step5tp_topic_retrieval_profile"
TOPIC_CANDIDATE_STAGE = "step5tx_topic_candidate_bank"
TOPIC_SCORED_STAGE = "step5tx_topic_scored_candidates"
TOPIC_PACK_STAGE = "step5tx_topic_evidence_packs"

DEFAULT_TOPIC_PROFILE_OUTPUT_ROOT = Path("data/processed/topic_retrieval_profiles")
DEFAULT_TOPIC_CANDIDATE_OUTPUT_ROOT = Path("data/processed/topic_evidence_stage_v3_candidate_bank")
DEFAULT_TOPIC_SCORED_OUTPUT_ROOT = Path("data/processed/topic_evidence_stage_v3_scored_candidates")
DEFAULT_TOPIC_PACK_OUTPUT_ROOT = Path("data/processed/topic_evidence_stage_v3_evidence_packs")


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except Exception as exc:
                raise RuntimeError(f"bad JSONL at {path}:{line_no}: {exc}") from exc
            if not isinstance(obj, dict):
                raise RuntimeError(f"expected object row at {path}:{line_no}")
            rows.append(obj)
    return rows


def write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=False) + "\n")


def read_json(path: Path) -> Dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(obj, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return obj


def write_json(path: Path, obj: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(obj), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_yaml_or_json(path: Optional[Path]) -> Dict[str, Any]:
    if path is None:
        return {}
    text = path.read_text(encoding="utf-8", errors="replace")
    if yaml is not None and path.suffix.lower() in {".yaml", ".yml"}:
        obj = yaml.safe_load(text)
    else:
        obj = json.loads(text)
    if obj is None:
        return {}
    if not isinstance(obj, dict):
        raise RuntimeError(f"expected config mapping at {path}")
    return obj


def repo_rel(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()


def split_ids(values: Optional[Sequence[str]]) -> List[str]:
    out: List[str] = []
    for value in values or []:
        for part in str(value).split(","):
            part = part.strip()
            if part and part not in out:
                out.append(part)
    return out


def as_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def str_list(value: Any) -> List[str]:
    out: List[str] = []
    for item in as_list(value):
        text = as_text(item)
        if text and text not in out:
            out.append(text)
    return out


def topic_id(row: Mapping[str, Any]) -> str:
    return as_text(row.get("topic_id") or row.get("knowledge_unit_id") or row.get("id") or row.get("node_id"))


def topic_label(row: Mapping[str, Any]) -> str:
    return as_text(row.get("topic_label") or row.get("label") or row.get("name") or row.get("title") or topic_id(row))


def load_topic_registry_inputs(
    *,
    topic_registry_jsonl: Path,
    topic_edges_jsonl: Optional[Path],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    topics = read_jsonl(topic_registry_jsonl)
    edges = read_jsonl(topic_edges_jsonl) if topic_edges_jsonl is not None and topic_edges_jsonl.exists() else []

    missing = [i for i, row in enumerate(topics, start=1) if not topic_id(row) or not topic_label(row)]
    if missing:
        raise RuntimeError(f"topic registry has rows missing topic_id/topic_label: {missing[:20]}")

    duplicate_ids = [tid for tid, count in Counter(topic_id(row) for row in topics).items() if count > 1]
    if duplicate_ids:
        raise RuntimeError(f"duplicate topic ids in topic registry: {duplicate_ids[:20]}")

    return topics, edges


def topic_registry_to_step5_unit_rows(
    *,
    topics: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
    mode: str,
) -> List[Dict[str, Any]]:
    """Convert typed topic rows into the KC-shaped contract consumed by existing Step5p/5x internals.

    mode="profile":
        keep knowledge_unit_type="topic" because Step5p can include exact topic IDs.

    mode="candidate_bank":
        set knowledge_unit_type="kc" only for the temporary bridge registry because the
        current clean-slate candidate-bank loader filters non-KC rows before profile
        guidance is applied. The profile guidance then restores knowledge_unit_type="topic"
        on generated candidates.
    """
    if mode not in {"profile", "candidate_bank"}:
        raise ValueError(f"bad mode: {mode}")

    labels = [topic_label(row) for row in topics]
    edge_labels_by_topic: Dict[str, List[str]] = {}
    edge_ids_by_topic: Dict[str, List[str]] = {}

    for edge in edges:
        tid = as_text(edge.get("topic_id"))
        if not tid:
            continue
        kc_label = as_text(edge.get("kc_label"))
        kc_id = as_text(edge.get("kc_id"))
        if kc_label:
            edge_labels_by_topic.setdefault(tid, []).append(kc_label)
        if kc_id:
            edge_ids_by_topic.setdefault(tid, []).append(kc_id)

    rows: List[Dict[str, Any]] = []
    for row in topics:
        tid = topic_id(row)
        label = topic_label(row)
        topic_path = str_list(row.get("topic_path")) or [label]
        contained_kc_ids = str_list(row.get("contained_kc_ids")) or edge_ids_by_topic.get(tid, [])
        contained_kc_labels = str_list(row.get("contained_kc_labels")) or edge_labels_by_topic.get(tid, [])
        sibling_labels = [x for x in labels if x and x != label]

        aliases = []
        aliases.extend(str_list(row.get("aliases")))
        aliases.extend([x for x in contained_kc_labels if x and not x.startswith("KC_")])
        aliases = [x for x in aliases if x and x != label]

        unit_type = "topic" if mode == "profile" else "kc"

        out = {
            **dict(row),
            "kc_id": tid,
            "knowledge_unit_id": tid,
            "knowledge_unit_type": unit_type,
            "node_id": tid,
            "node_type": unit_type,
            "canonical_name": label,
            "label": label,
            "name": label,
            "aliases": aliases,
            "topic_path_labels": topic_path,
            "hierarchy_path_labels": topic_path,
            "parent_topic_id": "",
            "parent_topic_label": topic_path[-2] if len(topic_path) >= 2 else "",
            "sibling_labels": sibling_labels,
            "contained_kc_ids": contained_kc_ids,
            "contained_kc_labels": contained_kc_labels,
            "topic_lane_original_knowledge_unit_type": "topic",
            "topic_lane_bridge_mode": mode,
            "topic_lane_wrapper_version": TOPIC_WRAPPER_VERSION,
            "source": as_text(row.get("source") or "reconstructed_topic_registry"),
        }
        rows.append(out)

    return rows



def normalize_topic_candidate_bank_rows(
    rows: Sequence[Mapping[str, Any]],
    topic_profiles: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Restore topic semantics after the KC-compatible candidate-bank bridge.

    The underlying clean-slate candidate-bank loader currently expects KC-shaped
    rows. Topic5x therefore uses a temporary bridge where topic registry rows are
    loader-compatible. This helper must run after candidate generation so the
    published topic candidate-bank artifact is correctly typed as topic evidence
    retrieval, not KC evidence retrieval.
    """
    profile_by_id: Dict[str, Mapping[str, Any]] = {}
    for profile in topic_profiles:
        pid = as_text(
            profile.get("knowledge_unit_id")
            or profile.get("kc_id")
            or profile.get("topic_id")
            or profile.get("node_id")
        )
        if pid:
            profile_by_id[pid] = profile

    normalized: List[Dict[str, Any]] = []
    for row in rows:
        out = dict(row)
        tid = as_text(
            out.get("knowledge_unit_id")
            or out.get("kc_id")
            or out.get("topic_id")
            or out.get("node_id")
        )
        profile = profile_by_id.get(tid, {})
        profile_status = as_text(profile.get("profile_status") or "")

        bridge_unit_type = as_text(out.get("knowledge_unit_type") or "kc")
        out["bridge_loader_knowledge_unit_type"] = bridge_unit_type
        out["topic_lane_original_knowledge_unit_type"] = "topic"
        out["topic_lane_bridge_mode"] = "candidate_bank_loader_compatibility"
        out["topic_candidate_bank_normalization_version"] = "topic_candidate_bank_type_normalization_v1_20260519"

        out["kc_id"] = tid
        out["knowledge_unit_id"] = tid
        out["topic_id"] = tid
        out["node_id"] = tid
        out["knowledge_unit_type"] = "topic"
        out["node_type"] = "topic"

        out["topic5p_profile_status"] = profile_status
        out["topic5p_weak_profile_carry_forward"] = profile_status.lower() == "weak"
        out["topic5x_candidate_bank_unit_semantics"] = "topic_context_retrieval_candidate"
        out["topic5x_candidate_bank_role"] = "candidate_surface_for_topic_scoring"
        out["authority_contract"] = "topic5x_must_verify_against_source_rows"

        guidance = out.get("step5p_profile_guidance")
        if isinstance(guidance, dict):
            guidance = dict(guidance)
            guidance["knowledge_unit_type"] = "topic"
            guidance["topic5p_profile_status"] = profile_status
            guidance["topic5p_weak_profile_carry_forward"] = profile_status.lower() == "weak"
            out["step5p_profile_guidance"] = guidance

        role_guidance = out.get("step5p_role_target_guidance")
        if isinstance(role_guidance, dict):
            role_guidance = dict(role_guidance)
            role_guidance["knowledge_unit_type"] = "topic"
            out["step5p_role_target_guidance"] = role_guidance

        normalized.append(out)

    return normalized


def exact_topic_ids_from_rows(rows: Sequence[Mapping[str, Any]], exact_topic_ids: Optional[Sequence[str]]) -> List[str]:
    requested = split_ids(exact_topic_ids)
    if requested:
        available = {topic_id(row) for row in rows}
        missing = [x for x in requested if x not in available]
        if missing:
            raise RuntimeError(f"requested exact topic ids not in topic registry: {missing[:20]}")
        return requested
    return [topic_id(row) for row in rows]


def write_topic_set_manifest(
    *,
    path: Path,
    run_id: str,
    stage: str,
    artifacts: Mapping[str, Any],
    inputs: Mapping[str, Any],
    stats: Mapping[str, Any],
) -> None:
    payload = {
        "schema_version": "1.0",
        "wrapper_version": TOPIC_WRAPPER_VERSION,
        "stage": stage,
        "run_id": run_id,
        "set_id": f"{run_id}_{stage}_set",
        "created_at": now_utc_iso(),
        "artifacts": dict(artifacts),
        "inputs": dict(inputs),
        "stats": dict(stats),
        "active_pointer_updated": False,
        "typed_lane": "topic",
    }
    write_json(path, payload)


def run_topic_profile_stage(
    *,
    topic_registry_jsonl: Path,
    topic_edges_jsonl: Path,
    source_overlay_jsonl: Path,
    output_root: Path,
    set_manifest_root: Path,
    run_id: str,
    exact_topic_ids: Optional[Sequence[str]] = None,
    limit_topics: Optional[int] = None,
    max_snippets_per_topic: int = 12,
    min_snippet_score: float = 4.0,
    use_model: bool = False,
    llm_policy: Optional[str] = None,
    model_config: Optional[Mapping[str, Any]] = None,
    dynamic_broad_token_min_df: int = 12,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    repo_root = repo_root or Path.cwd()
    topics, edges = load_topic_registry_inputs(
        topic_registry_jsonl=topic_registry_jsonl,
        topic_edges_jsonl=topic_edges_jsonl,
    )
    selected_topic_ids = exact_topic_ids_from_rows(topics, exact_topic_ids)
    if limit_topics is not None:
        selected_topic_ids = selected_topic_ids[: int(limit_topics)]

    bridge_rows = topic_registry_to_step5_unit_rows(topics=topics, edges=edges, mode="profile")
    bridge_dir = output_root / "_bridge_inputs" / run_id
    bridge_registry = bridge_dir / "topic_registry_as_step5p_units.jsonl"
    write_jsonl(bridge_registry, bridge_rows)

    base_result = build_profiles(
        registry_jsonl=bridge_registry,
        source_overlay_jsonl=source_overlay_jsonl,
        output_root=output_root,
        set_manifest_root=set_manifest_root,
        run_id=run_id,
        exact_kc_ids=selected_topic_ids,
        limit_kcs=None,
        max_snippets_per_kc=max_snippets_per_topic,
        min_snippet_score=min_snippet_score,
        use_model=use_model,
        llm_policy=llm_policy,
        model_config=model_config or {},
        dynamic_broad_token_min_df=dynamic_broad_token_min_df,
    )

    processed_dir = output_root / run_id
    base_profile_jsonl = processed_dir / "kc_retrieval_profiles.jsonl"
    base_stats_json = processed_dir / "kc_retrieval_profile_stats.json"
    base_schema_json = processed_dir / "kc_retrieval_profile_schema_snapshot.json"
    base_audit_md = processed_dir / "kc_retrieval_profile_audit.md"

    topic_profile_jsonl = processed_dir / "topic_retrieval_profiles.jsonl"
    topic_stats_json = processed_dir / "topic_retrieval_profile_stats.json"
    topic_schema_json = processed_dir / "topic_retrieval_profile_schema_snapshot.json"
    topic_manifest_json = processed_dir / "topic_retrieval_profile_manifest.json"
    topic_audit_md = processed_dir / "topic_retrieval_profile_audit.md"
    topic_set_manifest = set_manifest_root / f"{run_id}_topic_retrieval_profile_set.json"

    shutil.copy2(base_profile_jsonl, topic_profile_jsonl)
    if base_schema_json.exists():
        shutil.copy2(base_schema_json, topic_schema_json)
    if base_audit_md.exists():
        shutil.copy2(base_audit_md, topic_audit_md)

    profiles = read_jsonl(topic_profile_jsonl)
    type_counter = Counter(as_text(row.get("knowledge_unit_type") or "unknown") for row in profiles)
    status_counter = Counter(as_text(row.get("profile_status") or "unknown") for row in profiles)

    model_metadata = {
        "use_model": bool(use_model),
        "llm_policy": llm_policy,
        "model": model_config.get("model") if isinstance(model_config, Mapping) else None,
        "base_url": model_config.get("base_url") if isinstance(model_config, Mapping) else None,
        "timeout_seconds": model_config.get("timeout_seconds") if isinstance(model_config, Mapping) else None,
        "temperature": model_config.get("temperature") if isinstance(model_config, Mapping) else None,
        "think": model_config.get("think") if isinstance(model_config, Mapping) else None,
    }

    stats = {
        "wrapper_version": TOPIC_WRAPPER_VERSION,
        "stage": TOPIC_PROFILE_STAGE,
        "run_id": run_id,
        "topic_registry_jsonl": topic_registry_jsonl.as_posix(),
        "topic_edges_jsonl": topic_edges_jsonl.as_posix(),
        "source_overlay_jsonl": source_overlay_jsonl.as_posix(),
        "bridge_registry_jsonl": bridge_registry.as_posix(),
        "topic_count": len(profiles),
        "selected_topic_ids": selected_topic_ids,
        "knowledge_unit_type_counter": dict(type_counter),
        "profile_status_counter": dict(status_counter),
        "model_metadata": model_metadata,
        "base_step5p_stats_json": base_stats_json.as_posix(),
        "base_step5p_result": base_result,
        "active_pointer_updated": False,
    }
    write_json(topic_stats_json, stats)

    artifacts = {
        "topic_retrieval_profiles_jsonl": repo_rel(topic_profile_jsonl, repo_root),
        "topic_retrieval_profile_stats_json": repo_rel(topic_stats_json, repo_root),
        "topic_retrieval_profile_schema_snapshot_json": repo_rel(topic_schema_json, repo_root),
        "topic_retrieval_profile_manifest_json": repo_rel(topic_manifest_json, repo_root),
        "topic_retrieval_profile_audit_md": repo_rel(topic_audit_md, repo_root),
        "base_kc_named_profile_jsonl": repo_rel(base_profile_jsonl, repo_root),
        "bridge_topic_registry_jsonl": repo_rel(bridge_registry, repo_root),
    }
    inputs = {
        "topic_registry_jsonl": topic_registry_jsonl.as_posix(),
        "topic_edges_jsonl": topic_edges_jsonl.as_posix(),
        "source_overlay_jsonl": source_overlay_jsonl.as_posix(),
        "exact_topic_ids": selected_topic_ids,
        "limit_topics": limit_topics,
    }
    manifest = {
        "schema_version": "1.0",
        "wrapper_version": TOPIC_WRAPPER_VERSION,
        "stage": TOPIC_PROFILE_STAGE,
        "run_id": run_id,
        "created_at": now_utc_iso(),
        "artifacts": artifacts,
        "inputs": inputs,
        "stats": stats,
        "model_metadata": model_metadata,
        "active_pointer_updated": False,
        "typed_lane": "topic",
    }
    write_json(topic_manifest_json, manifest)
    write_topic_set_manifest(
        path=topic_set_manifest,
        run_id=run_id,
        stage=TOPIC_PROFILE_STAGE,
        artifacts=artifacts,
        inputs=inputs,
        stats=stats,
    )

    return {
        "ok": len(profiles) == len(selected_topic_ids),
        "run_id": run_id,
        "processed_dir": processed_dir.as_posix(),
        "set_manifest": topic_set_manifest.as_posix(),
        "topic_retrieval_profiles_jsonl": topic_profile_jsonl.as_posix(),
        "topic_retrieval_profile_stats_json": topic_stats_json.as_posix(),
        "topic_retrieval_profile_manifest_json": topic_manifest_json.as_posix(),
        "topic_count": len(profiles),
        "profile_status_counter": dict(status_counter),
    }


def run_topic_candidate_bank_stage(
    *,
    topic_registry_jsonl: Path,
    topic_edges_jsonl: Path,
    source_overlay_jsonl: Path,
    topic_profile_jsonl: Path,
    config_path: str,
    output_root: Path,
    set_manifest_root: Path,
    run_id: str,
    exact_topic_ids: Optional[Sequence[str]] = None,
    limit_topics: Optional[int] = None,
    source_surface_fallback_cfg: Optional[Mapping[str, Any]] = None,
    direct_overlay_supplement_cfg: Optional[Mapping[str, Any]] = None,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    repo_root = repo_root or Path.cwd()
    topics, edges = load_topic_registry_inputs(
        topic_registry_jsonl=topic_registry_jsonl,
        topic_edges_jsonl=topic_edges_jsonl,
    )
    selected_topic_ids = exact_topic_ids_from_rows(topics, exact_topic_ids)
    if limit_topics is not None:
        selected_topic_ids = selected_topic_ids[: int(limit_topics)]

    bridge_rows = topic_registry_to_step5_unit_rows(topics=topics, edges=edges, mode="candidate_bank")
    bridge_dir = output_root / "_bridge_inputs" / run_id
    bridge_registry = bridge_dir / "topic_registry_as_step5x_units.jsonl"
    write_jsonl(bridge_registry, bridge_rows)

    result = run_candidate_bank_stage(
        run_id=run_id,
        step5_3_set_manifest_spec=None,
        step5_3_candidates_jsonl_spec=None,
        registry_jsonl_spec=bridge_registry.as_posix(),
        source_overlay_jsonl_spec=source_overlay_jsonl.as_posix(),
        config_path=config_path,
        exact_kc_ids=selected_topic_ids,
        limit_kcs=None,
        output_root=output_root,
        set_manifest_root=set_manifest_root,
        allow_reference_artifact_inputs=True,
        fail_if_no_candidate_source=True,
        exclude_seed_fields=True,
        preserve_raw_support_profile=True,
        preserve_raw_alignment_breakdown=True,
        allow_seed_bearing_input_for_diagnostic=False,
        profile_jsonl_spec=topic_profile_jsonl.as_posix(),
        source_surface_fallback_cfg=source_surface_fallback_cfg or {"enabled": True},
        direct_overlay_supplement_cfg=direct_overlay_supplement_cfg or {"enabled": False},
        repo_root=repo_root,
    )

    processed_dir = output_root / run_id
    base_candidate_jsonl = processed_dir / "candidate_bank.jsonl"
    topic_candidate_jsonl = processed_dir / "topic_candidate_bank.jsonl"
    topic_stats_json = processed_dir / "topic_candidate_bank_stats.json"
    topic_manifest_json = processed_dir / "topic_candidate_bank_manifest.json"
    topic_set_manifest = set_manifest_root / f"{run_id}_topic_candidate_bank_set.json"

    base_rows = read_jsonl(base_candidate_jsonl)
    topic_profiles = read_jsonl(topic_profile_jsonl)
    rows = normalize_topic_candidate_bank_rows(base_rows, topic_profiles)
    write_jsonl(topic_candidate_jsonl, rows)
    unit_type_counter = Counter(as_text(row.get("knowledge_unit_type") or "unknown") for row in rows)
    bridge_unit_type_counter = Counter(as_text(row.get("bridge_loader_knowledge_unit_type") or "unknown") for row in rows)
    topic5p_profile_status_counter = Counter(as_text(row.get("topic5p_profile_status") or "unknown") for row in rows)
    candidate_count_by_topic = Counter(as_text(row.get("kc_id") or row.get("knowledge_unit_id")) for row in rows)

    stats = {
        "wrapper_version": TOPIC_WRAPPER_VERSION,
        "stage": TOPIC_CANDIDATE_STAGE,
        "run_id": run_id,
        "topic_count": len(selected_topic_ids),
        "candidate_rows": len(rows),
        "candidate_count_by_topic": dict(candidate_count_by_topic),
        "knowledge_unit_type_counter": dict(unit_type_counter),
        "bridge_loader_knowledge_unit_type_counter": dict(bridge_unit_type_counter),
        "topic5p_profile_status_counter": dict(topic5p_profile_status_counter),
        "weak_profile_candidate_rows": int(topic5p_profile_status_counter.get("weak", 0)),
        "base_candidate_result": result,
        "bridge_registry_jsonl": bridge_registry.as_posix(),
        "active_pointer_updated": False,
    }
    write_json(topic_stats_json, stats)

    artifacts = {
        "topic_candidate_bank_jsonl": repo_rel(topic_candidate_jsonl, repo_root),
        "topic_candidate_bank_stats_json": repo_rel(topic_stats_json, repo_root),
        "topic_candidate_bank_manifest_json": repo_rel(topic_manifest_json, repo_root),
        "base_candidate_bank_jsonl": repo_rel(base_candidate_jsonl, repo_root),
        "bridge_topic_registry_jsonl": repo_rel(bridge_registry, repo_root),
    }
    inputs = {
        "topic_registry_jsonl": topic_registry_jsonl.as_posix(),
        "topic_edges_jsonl": topic_edges_jsonl.as_posix(),
        "source_overlay_jsonl": source_overlay_jsonl.as_posix(),
        "topic_profile_jsonl": topic_profile_jsonl.as_posix(),
        "exact_topic_ids": selected_topic_ids,
        "limit_topics": limit_topics,
    }
    manifest = {
        "schema_version": "1.0",
        "wrapper_version": TOPIC_WRAPPER_VERSION,
        "stage": TOPIC_CANDIDATE_STAGE,
        "run_id": run_id,
        "created_at": now_utc_iso(),
        "artifacts": artifacts,
        "inputs": inputs,
        "stats": stats,
        "active_pointer_updated": False,
        "typed_lane": "topic",
    }
    write_json(topic_manifest_json, manifest)
    write_topic_set_manifest(
        path=topic_set_manifest,
        run_id=run_id,
        stage=TOPIC_CANDIDATE_STAGE,
        artifacts=artifacts,
        inputs=inputs,
        stats=stats,
    )

    return {
        "ok": True,
        "run_id": run_id,
        "processed_dir": processed_dir.as_posix(),
        "set_manifest": topic_set_manifest.as_posix(),
        "topic_candidate_bank_jsonl": topic_candidate_jsonl.as_posix(),
        "topic_candidate_bank_stats_json": topic_stats_json.as_posix(),
        "topic_candidate_bank_manifest_json": topic_manifest_json.as_posix(),
        "candidate_rows": len(rows),
        "topic_count": len(selected_topic_ids),
    }


def run_topic_scored_candidates_stage(
    *,
    topic_candidate_bank_jsonl: Path,
    config_path: Path,
    output_root: Path,
    set_manifest_root: Path,
    run_id: str,
    exact_topic_ids: Optional[Sequence[str]] = None,
    limit_topics: Optional[int] = None,
    cfg: Optional[Mapping[str, Any]] = None,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    repo_root = repo_root or Path.cwd()
    candidate_rows, input_info = load_candidate_bank_rows(
        stage1_set_manifest=None,
        candidate_bank_jsonl=topic_candidate_bank_jsonl.as_posix(),
        exact_kc_ids=split_ids(exact_topic_ids) or None,
        limit_kcs=limit_topics,
    )
    result = build_scored_candidate_artifacts(
        candidate_rows,
        run_id=run_id,
        source_manifest=str(input_info.get("source_manifest") or ""),
        candidate_bank_jsonl_path=str(input_info.get("candidate_bank_jsonl") or topic_candidate_bank_jsonl),
        config_path=config_path.as_posix(),
        exact_kc_ids=split_ids(exact_topic_ids) or None,
        limit_kcs=limit_topics,
        cfg=cfg or {},
        output_root=output_root,
        set_manifest_root=set_manifest_root,
    )

    processed_dir = output_root / run_id
    base_scored_jsonl = processed_dir / "scored_candidates.jsonl"
    topic_scored_jsonl = processed_dir / "topic_scored_candidates.jsonl"
    topic_stats_json = processed_dir / "topic_scored_candidate_stats.json"
    topic_manifest_json = processed_dir / "topic_scored_candidate_manifest.json"
    topic_set_manifest = set_manifest_root / f"{run_id}_topic_scored_candidates_set.json"

    shutil.copy2(base_scored_jsonl, topic_scored_jsonl)
    rows = read_jsonl(topic_scored_jsonl)
    unit_type_counter = Counter(as_text(row.get("knowledge_unit_type") or "unknown") for row in rows)

    stats = {
        "wrapper_version": TOPIC_WRAPPER_VERSION,
        "stage": TOPIC_SCORED_STAGE,
        "run_id": run_id,
        "scored_rows": len(rows),
        "knowledge_unit_type_counter": dict(unit_type_counter),
        "base_scored_result": result,
        "active_pointer_updated": False,
    }
    write_json(topic_stats_json, stats)

    artifacts = {
        "topic_scored_candidates_jsonl": repo_rel(topic_scored_jsonl, repo_root),
        "topic_scored_candidate_stats_json": repo_rel(topic_stats_json, repo_root),
        "topic_scored_candidate_manifest_json": repo_rel(topic_manifest_json, repo_root),
        "base_scored_candidates_jsonl": repo_rel(base_scored_jsonl, repo_root),
    }
    inputs = {
        "topic_candidate_bank_jsonl": topic_candidate_bank_jsonl.as_posix(),
        "exact_topic_ids": split_ids(exact_topic_ids),
        "limit_topics": limit_topics,
    }
    manifest = {
        "schema_version": "1.0",
        "wrapper_version": TOPIC_WRAPPER_VERSION,
        "stage": TOPIC_SCORED_STAGE,
        "run_id": run_id,
        "created_at": now_utc_iso(),
        "artifacts": artifacts,
        "inputs": inputs,
        "stats": stats,
        "active_pointer_updated": False,
        "typed_lane": "topic",
    }
    write_json(topic_manifest_json, manifest)
    write_topic_set_manifest(
        path=topic_set_manifest,
        run_id=run_id,
        stage=TOPIC_SCORED_STAGE,
        artifacts=artifacts,
        inputs=inputs,
        stats=stats,
    )

    return {
        "ok": True,
        "run_id": run_id,
        "processed_dir": processed_dir.as_posix(),
        "set_manifest": topic_set_manifest.as_posix(),
        "topic_scored_candidates_jsonl": topic_scored_jsonl.as_posix(),
        "topic_scored_candidate_stats_json": topic_stats_json.as_posix(),
        "topic_scored_candidate_manifest_json": topic_manifest_json.as_posix(),
        "scored_rows": len(rows),
    }


def run_topic_pack_composition_stage(
    *,
    topic_scored_candidates_jsonl: Path,
    config_path: Path,
    output_root: Path,
    set_manifest_root: Path,
    run_id: str,
    exact_topic_ids: Optional[Sequence[str]] = None,
    limit_topics: Optional[int] = None,
    cfg: Optional[Mapping[str, Any]] = None,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    repo_root = repo_root or Path.cwd()
    scored_rows, input_info = load_scored_candidate_rows(
        stage2_set_manifest=None,
        scored_candidates_jsonl=topic_scored_candidates_jsonl.as_posix(),
        exact_kc_ids=split_ids(exact_topic_ids) or None,
        limit_kcs=limit_topics,
        repo_root=repo_root,
    )
    result = build_evidence_pack_artifacts(
        scored_rows,
        run_id=run_id,
        source_manifest=str(input_info.get("source_manifest") or ""),
        scored_candidates_jsonl_path=str(input_info.get("scored_candidates_jsonl") or topic_scored_candidates_jsonl),
        config_path=config_path.as_posix(),
        exact_kc_ids=split_ids(exact_topic_ids) or None,
        limit_kcs=limit_topics,
        cfg=cfg or {},
        output_root=output_root,
        set_manifest_root=set_manifest_root,
        repo_root=repo_root,
    )

    processed_dir = output_root / run_id
    base_pack_jsonl = processed_dir / "kc_evidence_packs.jsonl"
    base_gap_jsonl = processed_dir / "retrieval_gap_requests.jsonl"
    base_gap_stats_json = processed_dir / "retrieval_gap_request_stats.json"
    topic_pack_jsonl = processed_dir / "topic_evidence_packs.jsonl"
    topic_gap_jsonl = processed_dir / "topic_gap_requests.jsonl"
    topic_stats_json = processed_dir / "topic_evidence_pack_stats.json"
    topic_manifest_json = processed_dir / "topic_evidence_pack_manifest.json"
    topic_set_manifest = set_manifest_root / f"{run_id}_topic_evidence_packs_set.json"

    shutil.copy2(base_pack_jsonl, topic_pack_jsonl)
    if base_gap_jsonl.exists():
        shutil.copy2(base_gap_jsonl, topic_gap_jsonl)

    packs = read_jsonl(topic_pack_jsonl)
    gaps = read_jsonl(topic_gap_jsonl) if topic_gap_jsonl.exists() else []
    ordered_total = 0
    for pack in packs:
        ordered = pack.get("ordered_pack_for_drafting")
        if isinstance(ordered, list):
            ordered_total += len(ordered)

    stats = {
        "wrapper_version": TOPIC_WRAPPER_VERSION,
        "stage": TOPIC_PACK_STAGE,
        "run_id": run_id,
        "topic_pack_rows": len(packs),
        "topic_gap_rows": len(gaps),
        "ordered_evidence_total": ordered_total,
        "base_pack_result": result,
        "base_gap_stats_json": base_gap_stats_json.as_posix(),
        "active_pointer_updated": False,
    }
    write_json(topic_stats_json, stats)

    artifacts = {
        "topic_evidence_packs_jsonl": repo_rel(topic_pack_jsonl, repo_root),
        "topic_gap_requests_jsonl": repo_rel(topic_gap_jsonl, repo_root),
        "topic_evidence_pack_stats_json": repo_rel(topic_stats_json, repo_root),
        "topic_evidence_pack_manifest_json": repo_rel(topic_manifest_json, repo_root),
        "base_kc_named_evidence_packs_jsonl": repo_rel(base_pack_jsonl, repo_root),
        "base_retrieval_gap_requests_jsonl": repo_rel(base_gap_jsonl, repo_root),
        "base_retrieval_gap_request_stats_json": repo_rel(base_gap_stats_json, repo_root),
    }
    inputs = {
        "topic_scored_candidates_jsonl": topic_scored_candidates_jsonl.as_posix(),
        "exact_topic_ids": split_ids(exact_topic_ids),
        "limit_topics": limit_topics,
    }
    manifest = {
        "schema_version": "1.0",
        "wrapper_version": TOPIC_WRAPPER_VERSION,
        "stage": TOPIC_PACK_STAGE,
        "run_id": run_id,
        "created_at": now_utc_iso(),
        "artifacts": artifacts,
        "inputs": inputs,
        "stats": stats,
        "active_pointer_updated": False,
        "typed_lane": "topic",
    }
    write_json(topic_manifest_json, manifest)
    write_topic_set_manifest(
        path=topic_set_manifest,
        run_id=run_id,
        stage=TOPIC_PACK_STAGE,
        artifacts=artifacts,
        inputs=inputs,
        stats=stats,
    )

    return {
        "ok": True,
        "run_id": run_id,
        "processed_dir": processed_dir.as_posix(),
        "set_manifest": topic_set_manifest.as_posix(),
        "topic_evidence_packs_jsonl": topic_pack_jsonl.as_posix(),
        "topic_gap_requests_jsonl": topic_gap_jsonl.as_posix(),
        "topic_evidence_pack_stats_json": topic_stats_json.as_posix(),
        "topic_evidence_pack_manifest_json": topic_manifest_json.as_posix(),
        "topic_pack_rows": len(packs),
        "topic_gap_rows": len(gaps),
        "ordered_evidence_total": ordered_total,
    }


def add_common_topic_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--topic-registry-jsonl", required=True, type=Path)
    parser.add_argument("--topic-to-kc-edges-jsonl", required=True, type=Path)
    parser.add_argument("--exact-topic-ids", nargs="*", default=None)
    parser.add_argument("--limit-topics", type=int, default=None)
    parser.add_argument("--run-id", type=str, default=None)


def parse_profile_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build typed Topic Step5p retrieval profiles.")
    parser.add_argument("--config", type=Path, default=None)
    add_common_topic_args(parser)
    parser.add_argument("--source-overlay-jsonl", required=True, type=Path)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_TOPIC_PROFILE_OUTPUT_ROOT)
    parser.add_argument("--set-manifest-root", type=Path, default=DEFAULT_TOPIC_PROFILE_OUTPUT_ROOT / "_sets")
    parser.add_argument("--max-snippets-per-topic", type=int, default=12)
    parser.add_argument("--min-snippet-score", type=float, default=4.0)
    parser.add_argument("--use-model", action="store_true")
    parser.add_argument("--no-model", action="store_true")
    parser.add_argument("--llm-policy", choices=["always", "edge", "never"], default=None)
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--base-url", type=str, default=None)
    parser.add_argument("--dynamic-broad-token-min-df", type=int, default=12)
    return parser.parse_args(argv)


def main_topic_profile(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_profile_args(argv)
    cfg = load_yaml_or_json(args.config)
    inputs = dict(cfg.get("inputs") or {})
    outputs = dict(cfg.get("outputs") or {})
    behavior = dict(cfg.get("behavior") or {})
    model_cfg = dict(cfg.get("model") or {})

    use_model = bool(behavior.get("use_model", False))
    llm_policy = behavior.get("llm_policy")
    if args.use_model:
        use_model = True
        llm_policy = "always"
    if args.no_model:
        use_model = False
        llm_policy = "never"
    if args.llm_policy:
        llm_policy = args.llm_policy
    if args.model:
        model_cfg["model"] = args.model
    if args.base_url:
        model_cfg["base_url"] = args.base_url

    result = run_topic_profile_stage(
        topic_registry_jsonl=args.topic_registry_jsonl,
        topic_edges_jsonl=args.topic_to_kc_edges_jsonl,
        source_overlay_jsonl=args.source_overlay_jsonl,
        output_root=args.output_root or Path(outputs.get("output_root") or DEFAULT_TOPIC_PROFILE_OUTPUT_ROOT),
        set_manifest_root=args.set_manifest_root or Path(outputs.get("set_manifest_root") or DEFAULT_TOPIC_PROFILE_OUTPUT_ROOT / "_sets"),
        run_id=args.run_id or f"step5tp_topic_retrieval_profiles_{utc_stamp()}",
        exact_topic_ids=split_ids(args.exact_topic_ids) or split_ids(inputs.get("exact_topic_ids") or []),
        limit_topics=args.limit_topics if args.limit_topics is not None else inputs.get("limit_topics"),
        max_snippets_per_topic=args.max_snippets_per_topic if args.max_snippets_per_topic is not None else int(behavior.get("max_snippets_per_topic", 12)),
        min_snippet_score=args.min_snippet_score if args.min_snippet_score is not None else float(behavior.get("min_snippet_score", 4.0)),
        use_model=use_model,
        llm_policy=llm_policy,
        model_config=model_cfg,
        dynamic_broad_token_min_df=args.dynamic_broad_token_min_df,
        repo_root=Path.cwd(),
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 2


def parse_candidate_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build typed Topic Step5x candidate bank.")
    parser.add_argument("--config", type=Path, default=None)
    add_common_topic_args(parser)
    parser.add_argument("--source-overlay-jsonl", required=True, type=Path)
    parser.add_argument("--topic-profile-jsonl", required=True, type=Path)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_TOPIC_CANDIDATE_OUTPUT_ROOT)
    parser.add_argument("--set-manifest-root", type=Path, default=DEFAULT_TOPIC_CANDIDATE_OUTPUT_ROOT / "_sets")
    return parser.parse_args(argv)


def main_topic_candidate_bank(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_candidate_args(argv)
    cfg = load_yaml_or_json(args.config)
    fallback_cfg = dict(cfg.get("source_surface_fallback") or {"enabled": True})
    direct_cfg = dict(cfg.get("direct_overlay_supplement") or {"enabled": False})
    result = run_topic_candidate_bank_stage(
        topic_registry_jsonl=args.topic_registry_jsonl,
        topic_edges_jsonl=args.topic_to_kc_edges_jsonl,
        source_overlay_jsonl=args.source_overlay_jsonl,
        topic_profile_jsonl=args.topic_profile_jsonl,
        config_path=args.config.as_posix() if args.config else "topic_5tx_candidate_bank_cli",
        output_root=args.output_root,
        set_manifest_root=args.set_manifest_root,
        run_id=args.run_id or f"step5tx_topic_candidate_bank_{utc_stamp()}",
        exact_topic_ids=split_ids(args.exact_topic_ids),
        limit_topics=args.limit_topics,
        source_surface_fallback_cfg=fallback_cfg,
        direct_overlay_supplement_cfg=direct_cfg,
        repo_root=Path.cwd(),
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 2


def parse_scored_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score typed Topic Step5x candidate rows.")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--topic-candidate-bank-jsonl", required=True, type=Path)
    parser.add_argument("--exact-topic-ids", nargs="*", default=None)
    parser.add_argument("--limit-topics", type=int, default=None)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_TOPIC_SCORED_OUTPUT_ROOT)
    parser.add_argument("--set-manifest-root", type=Path, default=DEFAULT_TOPIC_SCORED_OUTPUT_ROOT / "_sets")
    parser.add_argument("--run-id", type=str, default=None)
    return parser.parse_args(argv)


def main_topic_scored_candidates(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_scored_args(argv)
    result = run_topic_scored_candidates_stage(
        topic_candidate_bank_jsonl=args.topic_candidate_bank_jsonl,
        config_path=args.config or Path("topic_5tx_scored_candidates_cli"),
        output_root=args.output_root,
        set_manifest_root=args.set_manifest_root,
        run_id=args.run_id or f"step5tx_topic_scored_candidates_{utc_stamp()}",
        exact_topic_ids=split_ids(args.exact_topic_ids),
        limit_topics=args.limit_topics,
        cfg=load_yaml_or_json(args.config),
        repo_root=Path.cwd(),
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 2


def parse_pack_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compose typed Topic Step5x evidence packs.")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--topic-scored-candidates-jsonl", required=True, type=Path)
    parser.add_argument("--exact-topic-ids", nargs="*", default=None)
    parser.add_argument("--limit-topics", type=int, default=None)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_TOPIC_PACK_OUTPUT_ROOT)
    parser.add_argument("--set-manifest-root", type=Path, default=DEFAULT_TOPIC_PACK_OUTPUT_ROOT / "_sets")
    parser.add_argument("--run-id", type=str, default=None)
    return parser.parse_args(argv)


def main_topic_pack_composition(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_pack_args(argv)
    result = run_topic_pack_composition_stage(
        topic_scored_candidates_jsonl=args.topic_scored_candidates_jsonl,
        config_path=args.config or Path("topic_5tx_pack_composition_cli"),
        output_root=args.output_root,
        set_manifest_root=args.set_manifest_root,
        run_id=args.run_id or f"step5tx_topic_evidence_packs_{utc_stamp()}",
        exact_topic_ids=split_ids(args.exact_topic_ids),
        limit_topics=args.limit_topics,
        cfg=load_yaml_or_json(args.config),
        repo_root=Path.cwd(),
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 2
