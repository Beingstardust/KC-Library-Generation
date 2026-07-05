from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_SRC = REPO_ROOT / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from kc_l.audit.manifests import build_input_manifest, build_output_manifest, env_snapshot, try_cmd_version
from kc_l.kc.drafting_input_overlay import (
    OVERLAY_CONTRACT_VERSION,
    attach_hierarchy_context_to_registry_rows,
    build_overlay_records,
    build_review_queue_lookup,
    load_source_corpus,
    select_kc_subset,
)
from kc_l.retrieval_gate.provenance_normalize import build_sentence_provenance_index
from kc_l.utils.json_io import read_json, read_jsonl, write_json, write_jsonl


DEFAULT_CONFIG = Path("steps/step_06_6_kc_drafting_input_overlay/resources/step6_6.slice10.yaml")


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_yaml_or_json(path: Path) -> Dict[str, Any]:
    text = read_text(path)
    if yaml is not None:
        obj = yaml.safe_load(text)
    else:
        obj = json.loads(text)
    if not isinstance(obj, dict):
        raise RuntimeError(f"Expected mapping at config root: {path}")
    return obj


def resolve_repo_path(raw_path: Any, *, base_dir: Optional[Path] = None) -> Path:
    candidate = Path(str(raw_path))
    if candidate.is_absolute():
        return candidate
    root = base_dir if base_dir is not None else REPO_ROOT
    return (root / candidate).resolve()


def resolve_pointer(pointer_path: Path) -> Path:
    raw = read_text(pointer_path).strip()
    if not raw:
        raise RuntimeError(f"Pointer file is empty: {pointer_path}")
    return resolve_repo_path(raw, base_dir=pointer_path.parent)


def rel_path(path: Path) -> str:
    resolved = path.resolve()
    repo_resolved = REPO_ROOT.resolve()
    try:
        return resolved.relative_to(repo_resolved).as_posix()
    except ValueError:
        return resolved.as_posix()


def choose_run_paths(processed_root: Path, runs_root: Path, sets_root: Path) -> Dict[str, Path]:
    base_stamp = utc_stamp()
    suffix = 0
    while True:
        run_id = base_stamp if suffix == 0 else f"{base_stamp}_{suffix:02d}"
        processed_dir = (processed_root / run_id).resolve()
        audit_dir = (runs_root / f"{run_id}_step6_6").resolve()
        set_path = (sets_root / f"{run_id}_step6_6_kc_drafting_input_overlay_set.json").resolve()
        if not processed_dir.exists() and not audit_dir.exists() and not set_path.exists():
            return {
                "run_id_step6_6": Path(run_id),
                "processed_dir": processed_dir,
                "audit_dir": audit_dir,
                "set_path": set_path,
            }
        suffix += 1


def copy_config_snapshot(config_path: Path, audit_dir: Path) -> Path:
    target = audit_dir / "config_snapshot.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(config_path, target)
    return target


def write_generated_json(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, obj)


def build_step6_assembly_bridge_manifest(
    *,
    assembly_manifest_path: Path,
    bridge_root: Path,
) -> Dict[str, Any]:
    assembly_obj = read_json(assembly_manifest_path)
    if assembly_obj.get("ready_for_step6") is not True:
        raise RuntimeError(f"Step6 input assembly is not marked ready: {assembly_manifest_path}")

    authorized_inputs = dict(assembly_obj.get("step6_authorized_inputs") or {})
    kc_pack_raw = authorized_inputs.get("kc_evidence_pack_jsonl")
    if not kc_pack_raw:
        raise RuntimeError("Step6 input assembly is missing step6_authorized_inputs.kc_evidence_pack_jsonl")

    kc_pack_path = resolve_repo_path(kc_pack_raw)
    if not kc_pack_path.exists():
        raise RuntimeError(f"Assembly-authorized KC evidence pack not found: {kc_pack_path}")

    topic_pack_raw = authorized_inputs.get("topic_evidence_pack_jsonl") or ""
    topic_gap_raw = authorized_inputs.get("topic_gap_jsonl") or ""

    bridge_root.mkdir(parents=True, exist_ok=True)
    bridge_set_path = bridge_root / f"{utc_stamp()}_step6_assembly_authorized_kc_pack_set.json"

    bridge_set_manifest = {
        "schema_version": "1.0",
        "kind": "step5x_v3_evidence_packs_set",
        "set_id": f"{bridge_set_path.stem}",
        "created_utc": now_utc_iso(),
        "artifacts": {
            "kc_evidence_packs_jsonl": kc_pack_path.as_posix(),
        },
        "upstream": {
            "step6_input_assembly_manifest_json": assembly_manifest_path.as_posix(),
            "topic_evidence_pack_jsonl": str(topic_pack_raw),
            "topic_gap_jsonl": str(topic_gap_raw),
        },
        "policy": {
            "generated_by_step6_6_manifest_bridge": True,
            "assembly_manifest_is_source_of_truth": True,
            "topic_inputs_are_preserved_as_lineage": True,
            "do_not_mutate_best_or_active_pointers": True,
        },
    }
    write_generated_json(bridge_set_path, bridge_set_manifest)
    return {
        "assembly_manifest_path": assembly_manifest_path,
        "assembly_obj": assembly_obj,
        "authorized_inputs": authorized_inputs,
        "kc_pack_path": kc_pack_path,
        "topic_pack_path": resolve_repo_path(topic_pack_raw) if topic_pack_raw else None,
        "topic_gap_path": resolve_repo_path(topic_gap_raw) if topic_gap_raw else None,
        "bridge_set_manifest_path": bridge_set_path,
        "bridge_set_manifest": bridge_set_manifest,
    }


def build_registry_rows_from_evidence_packs(evidence_packs_by_kc: Mapping[str, Mapping[str, Any]]) -> List[Dict[str, Any]]:
    registry_rows: List[Dict[str, Any]] = []
    for unit_id, pack_row in evidence_packs_by_kc.items():
        unit_id_s = str(unit_id or pack_row.get("kc_id") or pack_row.get("knowledge_unit_id") or "")
        if not unit_id_s:
            continue

        aliases = [str(item) for item in pack_row.get("aliases") or [] if str(item).strip()]
        topic_ids = [str(item) for item in pack_row.get("topic_path_ids") or [] if str(item).strip()]
        topic_labels = [str(item) for item in pack_row.get("topic_path_labels") or [] if str(item).strip()]
        hierarchy_path = list(topic_labels)

        row = {
            "kc_id": unit_id_s,
            "knowledge_unit_id": str(pack_row.get("knowledge_unit_id") or unit_id_s),
            "knowledge_unit_type": str(pack_row.get("knowledge_unit_type") or "kc"),
            "canonical_name": str(pack_row.get("canonical_name") or ""),
            "aliases": aliases,
            "topic_path_ids": topic_ids,
            "topic_path_labels": topic_labels,
            "source_hierarchy_path": hierarchy_path,
            "kc_path": hierarchy_path,
            "ancestor_hier_node_ids": topic_ids[:-1],
            "ancestor_labels": topic_labels[:-1],
            "leaf_hier_node_id": topic_ids[-1] if topic_ids else "",
            "parent_hier_node_id": str(pack_row.get("parent_topic_id") or (topic_ids[-1] if topic_ids else "")),
            "parent_topic_id": str(pack_row.get("parent_topic_id") or ""),
            "parent_topic_label": str(pack_row.get("parent_topic_label") or ""),
            "registry_source": "assembly_authorized_evidence_pack",
        }
        registry_rows.append(row)
    return registry_rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Step 6.6 KC drafting-input overlay.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--limit-kcs", type=int, default=None)
    parser.add_argument(
        "--step6-input-assembly-manifest",
        type=Path,
        default=None,
        help="Optional Step6 input assembly manifest. When provided, its authorized KC evidence pack is bridged into Step6.6 through the existing evidence-pack set manifest contract.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = resolve_repo_path(args.config)
    cfg = load_yaml_or_json(config_path)

    input_cfg = dict(cfg.get("inputs") or {})
    output_cfg = dict(cfg.get("outputs") or {})
    slice_cfg = dict(cfg.get("slice") or {})
    provenance_cfg = dict(cfg.get("provenance") or {})
    role_hint_cfg = dict(cfg.get("role_hints") or {})

    assembly_bridge_info: Dict[str, Any] = {}
    if args.step6_input_assembly_manifest is not None:
        assembly_manifest_path = resolve_repo_path(args.step6_input_assembly_manifest)
        bridge_root = resolve_repo_path(
            output_cfg.get("assembly_bridge_root") or "data/work/cache/step6_6_manifest_bridge"
        )
        assembly_bridge_info = build_step6_assembly_bridge_manifest(
            assembly_manifest_path=assembly_manifest_path,
            bridge_root=bridge_root,
        )
        configured_step5_4_manifest = str(assembly_bridge_info["bridge_set_manifest_path"])
    else:
        configured_step5_4_manifest = input_cfg.get("step5_4_set_manifest")

    processed_root = resolve_repo_path(output_cfg.get("processed_root") or "data/processed/kc_drafting_input_overlay")
    sets_root = resolve_repo_path(output_cfg.get("sets_root") or "data/processed/kc_drafting_input_overlay/_sets")
    runs_root = resolve_repo_path(output_cfg.get("runs_root") or "data/runs")

    step4_pointer = resolve_repo_path(
        input_cfg.get("step4_active_set_pointer") or "data/processed/retrieval_index/_sets/ACTIVE_STEP4_SET.txt"
    )
    step4_5_pointer = resolve_repo_path(
        input_cfg.get("step4_5_active_set_pointer")
        or "data/processed/retrieval_sentence_overlay/_sets/ACTIVE_STEP4_5_SENTENCE_SET.txt"
    )
    step5_3_pointer = resolve_repo_path(
        input_cfg.get("step5_3_active_set_pointer")
        or "data/processed/kc_evidence_recalibrated/_sets/ACTIVE_STEP5_3_EVIDENCE_SET.txt"
    )

    step4_set_path = resolve_pointer(step4_pointer)
    step4_5_set_path = resolve_pointer(step4_5_pointer)
    step5_3_set_path = resolve_pointer(step5_3_pointer)
    step5_4_set_path = None
    if configured_step5_4_manifest:
        step5_4_set_path = resolve_repo_path(configured_step5_4_manifest)
        if not step5_4_set_path.exists():
            raise RuntimeError(f"Configured Step 5.4 set manifest not found: {step5_4_set_path}")
    else:
        candidate_step5_4_set_path = resolve_repo_path(
            "data/work/cache/current_step_artifacts/step5_4_set_manifest.current.json"
        )
        if candidate_step5_4_set_path.exists():
            step5_4_set_path = candidate_step5_4_set_path

    step4_set_obj = read_json(step4_set_path)
    step4_5_set_obj = read_json(step4_5_set_path)
    step5_3_set_obj = read_json(step5_3_set_path)
    step5_4_set_obj = read_json(step5_4_set_path) if step5_4_set_path is not None and step5_4_set_path.exists() else {}

    overlay_manifest_path = resolve_repo_path(
        input_cfg.get("hierarchy_overlay_manifest")
        or "data/processed/hierarchy_overlay/2026-03-10_005659_hierarchy_overlay/overlay_manifest.json"
    )
    overlay_manifest = read_json(overlay_manifest_path)
    leaf_to_overlay_ancestry_path = resolve_repo_path(
        overlay_manifest.get("artifacts", {}).get("leaf_to_overlay_ancestry_json")
    )
    overlay_node_index_path = resolve_repo_path(overlay_manifest.get("artifacts", {}).get("overlay_node_index_json"))
    kc_registry_path = resolve_repo_path(
        step5_3_set_obj.get("upstream", {}).get("kc_registry_path")
        or overlay_manifest.get("normalized_registry")
    )
    sentence_corpus_path = resolve_repo_path(
        step4_5_set_obj.get("artifacts", {}).get("sentence_corpus_jsonl")
        or step5_3_set_obj.get("upstream", {}).get("step4_5_sentence_corpus_jsonl")
    )
    step5_candidates_path = resolve_repo_path(
        step5_3_set_obj.get("artifacts", {}).get("kc_evidence_candidates_recalibrated_jsonl")
    )
    review_queue_path = resolve_repo_path(step5_3_set_obj.get("artifacts", {}).get("review_queue_jsonl"))
    evidence_packs_path = None
    evidence_packs_by_kc: Dict[str, Dict[str, Any]] = {}
    step5_4_integration = {
        "status": "not_available",
        "set_manifest_json": "",
        "kc_evidence_packs_jsonl": "",
    }
    if step5_4_set_obj:
        evidence_packs_raw = (step5_4_set_obj.get("artifacts") or {}).get("kc_evidence_packs_jsonl")
        if evidence_packs_raw:
            evidence_packs_path = resolve_repo_path(evidence_packs_raw)
        step5_4_integration["set_manifest_json"] = rel_path(step5_4_set_path) if step5_4_set_path is not None else ""
        step5_4_integration["kc_evidence_packs_jsonl"] = rel_path(evidence_packs_path) if evidence_packs_path is not None else ""
        if evidence_packs_path is not None and evidence_packs_path.exists():
            evidence_packs_rows = read_jsonl(evidence_packs_path)
            evidence_packs_by_kc = {
                str(row.get("kc_id") or ""): dict(row)
                for row in evidence_packs_rows
                if str(row.get("kc_id") or "")
            }
            step5_4_integration["status"] = "loaded"
        else:
            step5_4_integration["status"] = "manifest_present_artifact_missing"

    if assembly_bridge_info:
        authorized_inputs = dict(assembly_bridge_info.get("authorized_inputs") or {})
        step5_4_integration["step6_input_assembly"] = {
            "manifest_json": rel_path(Path(assembly_bridge_info["assembly_manifest_path"])),
            "authorized_kc_evidence_pack_jsonl": rel_path(Path(assembly_bridge_info["kc_pack_path"])),
            "authorized_topic_evidence_pack_jsonl": (
                rel_path(Path(assembly_bridge_info["topic_pack_path"]))
                if assembly_bridge_info.get("topic_pack_path") is not None
                else str(authorized_inputs.get("topic_evidence_pack_jsonl") or "")
            ),
            "authorized_topic_gap_jsonl": (
                rel_path(Path(assembly_bridge_info["topic_gap_path"]))
                if assembly_bridge_info.get("topic_gap_path") is not None
                else str(authorized_inputs.get("topic_gap_jsonl") or "")
            ),
            "bridge_set_manifest_json": rel_path(Path(assembly_bridge_info["bridge_set_manifest_path"])),
        }

    registry_source = "configured_registry"
    if kc_registry_path.exists():
        registry_rows = read_jsonl(kc_registry_path)
    elif assembly_bridge_info and evidence_packs_by_kc:
        registry_rows = build_registry_rows_from_evidence_packs(evidence_packs_by_kc)
        registry_source = "assembly_authorized_evidence_pack"
    else:
        registry_rows = read_jsonl(kc_registry_path)

    if leaf_to_overlay_ancestry_path.exists():
        hierarchy_context_by_kc = read_json(leaf_to_overlay_ancestry_path)
    elif assembly_bridge_info:
        hierarchy_context_by_kc = {}
    else:
        hierarchy_context_by_kc = read_json(leaf_to_overlay_ancestry_path)

    attached_registry_rows = attach_hierarchy_context_to_registry_rows(registry_rows, hierarchy_context_by_kc)

    if assembly_bridge_info and evidence_packs_by_kc:
        exact_kc_ids = [str(unit_id) for unit_id in evidence_packs_by_kc.keys() if str(unit_id)]
        limit_kcs = args.limit_kcs if args.limit_kcs is not None else len(exact_kc_ids)
    else:
        exact_kc_ids = [str(item) for item in slice_cfg.get("exact_kc_ids") or []]
        limit_kcs = args.limit_kcs if args.limit_kcs is not None else slice_cfg.get("limit_kcs")

    selected_kc_rows = select_kc_subset(attached_registry_rows, limit_kcs, exact_kc_ids=exact_kc_ids or None)

    step5_rows = read_jsonl(step5_candidates_path)
    step5_rows_by_kc = {str(row.get("kc_id") or ""): row for row in step5_rows}
    review_queue_rows = read_jsonl(review_queue_path)
    review_queue_by_kc = build_review_queue_lookup(review_queue_rows)

    source_corpus = load_source_corpus(step4_set_obj, REPO_ROOT)
    sentence_rows = read_jsonl(sentence_corpus_path)
    provenance_index = build_sentence_provenance_index(sentence_rows, source_corpus["source_lookup"])

    run_paths = choose_run_paths(processed_root, runs_root, sets_root)
    run_id = str(run_paths["run_id_step6_6"])
    processed_dir = run_paths["processed_dir"]
    audit_dir = run_paths["audit_dir"]
    set_path = run_paths["set_path"]
    processed_dir.mkdir(parents=True, exist_ok=False)
    audit_dir.mkdir(parents=True, exist_ok=False)
    sets_root.mkdir(parents=True, exist_ok=True)

    config_snapshot_path = copy_config_snapshot(config_path, audit_dir)

    layer_preference = [str(item) for item in provenance_cfg.get("layer_preference") or ["mineru", "pymupdf", "docling"]]
    overlay_records, overlay_stats = build_overlay_records(
        kc_rows=selected_kc_rows,
        step5_rows_by_kc=step5_rows_by_kc,
        review_queue_by_kc=review_queue_by_kc,
        evidence_packs_by_kc=evidence_packs_by_kc,
        provenance_index=provenance_index,
        source_set_id=str(step5_3_set_obj.get("set_id") or ""),
        source_run_id=str(step5_3_set_obj.get("run_id_step5_3") or ""),
        layer_preference=layer_preference,
        role_hints_enabled=bool(role_hint_cfg.get("enabled", True)),
    )

    candidates_path = processed_dir / "candidate_sentence_overlay.jsonl"
    stats_path = processed_dir / "overlay_stats.json"
    write_jsonl(candidates_path, overlay_records)
    write_json(stats_path, overlay_stats)

    input_manifest_paths: List[Path] = [
        config_path,
        step4_pointer,
        step4_set_path,
        step4_5_pointer,
        step4_5_set_path,
        step5_3_pointer,
        step5_3_set_path,
        kc_registry_path,
        overlay_manifest_path,
        leaf_to_overlay_ancestry_path,
        overlay_node_index_path,
        sentence_corpus_path,
        step5_candidates_path,
        review_queue_path,
    ]
    if step5_4_set_path is not None:
        input_manifest_paths.append(step5_4_set_path)
    if evidence_packs_path is not None:
        input_manifest_paths.append(evidence_packs_path)
    if assembly_bridge_info:
        input_manifest_paths.append(Path(assembly_bridge_info["assembly_manifest_path"]))
        input_manifest_paths.append(Path(assembly_bridge_info["bridge_set_manifest_path"]))
        if assembly_bridge_info.get("topic_pack_path") is not None:
            input_manifest_paths.append(Path(assembly_bridge_info["topic_pack_path"]))
        if assembly_bridge_info.get("topic_gap_path") is not None:
            input_manifest_paths.append(Path(assembly_bridge_info["topic_gap_path"]))
    if assembly_bridge_info:
        input_manifest_paths = [Path(path) for path in input_manifest_paths if Path(path).exists()]
    input_manifest = build_input_manifest(input_manifest_paths)
    write_json(audit_dir / "input_manifest.json", input_manifest)

    summary = {
        "run_id": run_id,
        "created_utc": now_utc_iso(),
        "overlay_contract_version": OVERLAY_CONTRACT_VERSION,
        "selected_kc_ids": [str(row.get("kc_id") or "") for row in selected_kc_rows],
        "source_set_ids": {
            "step4": str(step4_set_obj.get("set_id") or ""),
            "step4_5": str(step4_5_set_obj.get("set_id") or ""),
            "step5_3": str(step5_3_set_obj.get("set_id") or ""),
            "step5_4": str(step5_4_set_obj.get("set_id") or ""),
        },
        "step5_4_integration": step5_4_integration,
        "kc_registry_source": registry_source,
        "stats": overlay_stats,
        "env": env_snapshot(),
        "tool_versions": {
            "python": try_cmd_version([sys.executable, "--version"]),
        },
    }
    write_json(audit_dir / "summary.json", summary)

    set_manifest = {
        "schema_version": "1.0",
        "kind": "step6_6_kc_drafting_input_overlay_set",
        "set_id": f"{run_id}_step6_6_kc_drafting_input_overlay_set",
        "created_utc": now_utc_iso(),
        "run_id_step6_6": run_id,
        "artifacts": {
            "candidate_sentence_overlay_jsonl": rel_path(candidates_path),
            "overlay_stats_json": rel_path(stats_path),
        },
        "upstream": {
            "step4_active_set_pointer": rel_path(step4_pointer),
            "step4_active_set_target": rel_path(step4_set_path),
            "step4_5_active_set_pointer": rel_path(step4_5_pointer),
            "step4_5_active_set_target": rel_path(step4_5_set_path),
            "step5_3_active_set_pointer": rel_path(step5_3_pointer),
            "step5_3_active_set_target": rel_path(step5_3_set_path),
            "step5_4_set_manifest_json": rel_path(step5_4_set_path) if step5_4_set_path is not None else "",
            "step5_4_kc_evidence_packs_jsonl": rel_path(evidence_packs_path) if evidence_packs_path is not None else "",
            "kc_registry_jsonl": rel_path(kc_registry_path),
            "hierarchy_overlay_manifest_json": rel_path(overlay_manifest_path),
            "leaf_to_overlay_ancestry_json": rel_path(leaf_to_overlay_ancestry_path),
            "overlay_node_index_json": rel_path(overlay_node_index_path),
            "sentence_corpus_jsonl": rel_path(sentence_corpus_path),
            "review_queue_jsonl": rel_path(review_queue_path),
        },
        "slice": {
            "exact_kc_ids": [str(row.get("kc_id") or "") for row in selected_kc_rows],
            "limit_kcs": len(selected_kc_rows),
        },
        "audit": {
            "run_dir": rel_path(audit_dir),
            "config_snapshot": rel_path(config_snapshot_path),
            "input_manifest": rel_path(audit_dir / "input_manifest.json"),
            "summary": rel_path(audit_dir / "summary.json"),
            "output_manifest": rel_path(audit_dir / "output_manifest.json"),
        },
    }
    write_json(set_path, set_manifest)

    output_manifest = {
        "processed_outputs": build_output_manifest(processed_dir),
        "audit_outputs": build_output_manifest(audit_dir),
        "set_manifest": {
            "path": rel_path(set_path),
        },
    }
    write_json(audit_dir / "output_manifest.json", output_manifest)

    print(json.dumps({"run_id": run_id, "processed_dir": rel_path(processed_dir), "audit_dir": rel_path(audit_dir)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
