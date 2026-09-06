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
from kc_l.kc.drafting_input_overlay import attach_hierarchy_context_to_registry_rows, select_kc_subset
from kc_l.runtime.current_step_artifacts import resolve_seedless_kc_registry_path
from kc_l.retrieval_gate.evidence_pack_composition import (
    EVIDENCE_PACK_CONTRACT_VERSION,
    build_sentence_context_index,
    compose_evidence_packs,
)
from kc_l.utils.json_io import read_json, read_jsonl, write_json, write_jsonl


DEFAULT_CONFIG = Path("steps/step_05_4_evidence_pack_composition/resources/step5_4.default.yaml")


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


def choose_run_paths(
    processed_root: Path,
    runs_root: Path,
    sets_root: Path,
    *,
    run_id: Optional[str] = None,
) -> Dict[str, Path]:
    if run_id:
        processed_dir = (processed_root / run_id).resolve()
        audit_dir = (runs_root / f"{run_id}_step5_4").resolve()
        set_path = (sets_root / f"{run_id}_step5_4_kc_evidence_packs_set.json").resolve()
        if processed_dir.exists() or audit_dir.exists() or set_path.exists():
            raise RuntimeError(f"Requested run_id already exists: {run_id}")
        return {
            "run_id_step5_4": Path(run_id),
            "processed_dir": processed_dir,
            "audit_dir": audit_dir,
            "set_path": set_path,
        }
    base_stamp = utc_stamp()
    suffix = 0
    while True:
        generated = base_stamp if suffix == 0 else f"{base_stamp}_{suffix:02d}"
        processed_dir = (processed_root / generated).resolve()
        audit_dir = (runs_root / f"{generated}_step5_4").resolve()
        set_path = (sets_root / f"{generated}_step5_4_kc_evidence_packs_set.json").resolve()
        if not processed_dir.exists() and not audit_dir.exists() and not set_path.exists():
            return {
                "run_id_step5_4": Path(generated),
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


def _split_exact_kc_ids(values: Optional[List[str]]) -> List[str]:
    output: List[str] = []
    for value in values or []:
        for part in str(value).split(","):
            part = part.strip()
            if part:
                output.append(part)
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build deterministic Step 5.4 role-aware evidence packs.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--step5-3-set-manifest", dest="step5_3_set_manifest", type=Path, default=None)
    parser.add_argument("--limit-kcs", type=int, default=None)
    parser.add_argument("--exact-kc-ids", nargs="*", default=None)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--run-id", type=str, default=None)
    return parser.parse_args()


def _load_registry_rows(kc_registry_path: Optional[Path]) -> List[Dict[str, Any]]:
    if kc_registry_path is None or not kc_registry_path.exists():
        return []
    rows = read_jsonl(kc_registry_path)
    return [dict(row) for row in rows]


def _attach_hierarchy_context(
    registry_rows: List[Dict[str, Any]],
    hierarchy_overlay_manifest_path: Optional[Path],
) -> List[Dict[str, Any]]:
    if hierarchy_overlay_manifest_path is None or not hierarchy_overlay_manifest_path.exists():
        return registry_rows
    overlay_manifest = read_json(hierarchy_overlay_manifest_path)
    ancestry_path_raw = (overlay_manifest.get("artifacts") or {}).get("leaf_to_overlay_ancestry_json")
    if not ancestry_path_raw:
        return registry_rows
    ancestry_path = resolve_repo_path(ancestry_path_raw)
    if not ancestry_path.exists():
        return registry_rows
    hierarchy_context_by_kc = read_json(ancestry_path)
    return attach_hierarchy_context_to_registry_rows(registry_rows, hierarchy_context_by_kc)


def _fallback_kc_rows_from_step5(step5_rows_by_kc: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for kc_id, row in sorted(step5_rows_by_kc.items()):
        rows.append(
            {
                "kc_id": kc_id,
                "canonical_name": str(row.get("canonical_name") or ""),
                "aliases": [str(item) for item in row.get("aliases") or []],
                "kc_path": [],
                "source_hierarchy_path": [],
                "ancestor_hier_node_ids": [],
                "ancestor_labels": [],
                "leaf_hier_node_id": "",
                "parent_hier_node_id": "",
            }
        )
    return rows


def main() -> int:
    args = parse_args()
    config_path = resolve_repo_path(args.config)
    cfg = load_yaml_or_json(config_path)

    input_cfg = dict(cfg.get("inputs") or {})
    output_cfg = dict(cfg.get("outputs") or {})
    slice_cfg = dict(cfg.get("slice") or {})

    step5_3_set_manifest_path: Optional[Path] = None
    if args.step5_3_set_manifest is not None:
        step5_3_set_manifest_path = resolve_repo_path(args.step5_3_set_manifest)
    elif input_cfg.get("step5_3_set_manifest"):
        step5_3_set_manifest_path = resolve_repo_path(input_cfg.get("step5_3_set_manifest"))
    else:
        step5_3_pointer = resolve_repo_path(
            input_cfg.get("step5_3_active_set_pointer")
            or "data/processed/kc_evidence_recalibrated/_sets/ACTIVE_STEP5_3_EVIDENCE_SET.txt"
        )
        step5_3_set_manifest_path = resolve_pointer(step5_3_pointer)

    if step5_3_set_manifest_path is None or not step5_3_set_manifest_path.exists():
        raise RuntimeError(f"Step 5.3 set manifest not found: {step5_3_set_manifest_path}")

    step5_3_set_obj = read_json(step5_3_set_manifest_path)
    step5_candidates_path = resolve_repo_path(
        (step5_3_set_obj.get("artifacts") or {}).get("kc_evidence_candidates_recalibrated_jsonl")
    )
    if not step5_candidates_path.exists():
        raise RuntimeError(f"Step 5.3 candidate JSONL not found: {step5_candidates_path}")
    step5_rows = [dict(row) for row in read_jsonl(step5_candidates_path)]
    step5_rows_by_kc = {str(row.get("kc_id") or ""): row for row in step5_rows}

    review_queue_path = None
    review_queue_raw = (
        input_cfg.get("review_queue_jsonl")
        or (step5_3_set_obj.get("artifacts") or {}).get("review_queue_jsonl")
    )
    if review_queue_raw:
        review_queue_path = resolve_repo_path(review_queue_raw)
    review_queue_by_kc: Dict[str, Dict[str, Any]] = {}
    if review_queue_path is not None and review_queue_path.exists():
        review_queue_rows = read_jsonl(review_queue_path)
        review_queue_by_kc = {
            str(row.get("kc_id") or ""): dict(row)
            for row in review_queue_rows
            if str(row.get("kc_id") or "")
        }
        for kc_id, row in review_queue_by_kc.items():
            if kc_id in step5_rows_by_kc:
                step5_rows_by_kc[kc_id]["review_queue_aux"] = dict(row)

    kc_registry_path = None
    kc_registry_raw = (
        input_cfg.get("kc_registry_path")
        or (step5_3_set_obj.get("upstream") or {}).get("kc_registry_path")
        or None
    )
    kc_registry_path = resolve_seedless_kc_registry_path(kc_registry_raw, repo_root=REPO_ROOT)

    hierarchy_overlay_manifest_path = None
    hierarchy_overlay_raw = input_cfg.get("hierarchy_overlay_manifest") or "data/work/cache/current_step_artifacts/step1_5_overlay_manifest.current.json"
    if hierarchy_overlay_raw:
        hierarchy_overlay_manifest_path = resolve_repo_path(hierarchy_overlay_raw)

    registry_rows = _attach_hierarchy_context(
        _load_registry_rows(kc_registry_path),
        hierarchy_overlay_manifest_path,
    )
    if not registry_rows:
        registry_rows = _fallback_kc_rows_from_step5(step5_rows_by_kc)

    exact_kc_ids = _split_exact_kc_ids(args.exact_kc_ids) or [str(item) for item in slice_cfg.get("exact_kc_ids") or []]
    limit_kcs = args.limit_kcs if args.limit_kcs is not None else slice_cfg.get("limit_kcs")
    selected_kc_rows = select_kc_subset(registry_rows, limit_kcs, exact_kc_ids=exact_kc_ids or None)

    sentence_context_index = None
    sentence_corpus_path = None
    sentence_corpus_raw = input_cfg.get("sentence_corpus_jsonl") or (step5_3_set_obj.get("upstream") or {}).get("step4_5_sentence_corpus_jsonl")
    if sentence_corpus_raw:
        sentence_corpus_path = resolve_repo_path(sentence_corpus_raw)
    if sentence_corpus_path is not None and sentence_corpus_path.exists():
        sentence_context_index = build_sentence_context_index(read_jsonl(sentence_corpus_path))

    step4_5_set_manifest_path = None
    step4_5_set_manifest_raw = (step5_3_set_obj.get("upstream") or {}).get("step4_5_active_set_target")
    if step4_5_set_manifest_raw:
        candidate = resolve_repo_path(step4_5_set_manifest_raw)
        if candidate.exists():
            step4_5_set_manifest_path = candidate

    processed_root = resolve_repo_path(output_cfg.get("processed_root") or "data/processed/kc_evidence_packs")
    sets_root = resolve_repo_path(output_cfg.get("sets_root") or processed_root / "_sets")
    runs_root = resolve_repo_path(output_cfg.get("runs_root") or "data/runs")
    active_pointer_path = resolve_repo_path(
        output_cfg.get("active_set_pointer")
        or sets_root / "ACTIVE_STEP5_4_EVIDENCE_PACK_SET.txt"
    )
    if args.output_root is not None:
        processed_root = resolve_repo_path(args.output_root)
        sets_root = (processed_root / "_sets").resolve()
        active_pointer_path = (sets_root / "ACTIVE_STEP5_4_EVIDENCE_PACK_SET.txt").resolve()

    run_paths = choose_run_paths(processed_root, runs_root, sets_root, run_id=args.run_id)
    run_id = str(run_paths["run_id_step5_4"])
    processed_dir = run_paths["processed_dir"]
    audit_dir = run_paths["audit_dir"]
    set_path = run_paths["set_path"]
    processed_dir.mkdir(parents=True, exist_ok=False)
    audit_dir.mkdir(parents=True, exist_ok=False)
    sets_root.mkdir(parents=True, exist_ok=True)

    config_snapshot_path = copy_config_snapshot(config_path, audit_dir)
    source_manifests = {
        "step5_3_set_manifest": rel_path(step5_3_set_manifest_path),
        "step4_5_sentence_overlay_manifest": rel_path(step4_5_set_manifest_path) if step4_5_set_manifest_path is not None else "",
    }
    packs, stats = compose_evidence_packs(
        kc_rows=selected_kc_rows,
        step5_rows_by_kc=step5_rows_by_kc,
        sentence_context_index=sentence_context_index,
        cfg=cfg,
        source_manifests=source_manifests,
    )

    packs_path = processed_dir / "kc_evidence_packs.jsonl"
    stats_path = processed_dir / "evidence_pack_stats.json"
    manifest_path = processed_dir / "evidence_pack_manifest.json"
    write_jsonl(packs_path, packs)
    write_json(
        stats_path,
        {
            "run_id_step5_4": run_id,
            "created_utc": now_utc_iso(),
            **stats,
            "selected_kc_ids": [str(row.get("kc_id") or "") for row in selected_kc_rows],
        },
    )

    manifest_payload = {
        "schema_version": "1.0",
        "kind": "step5_4_kc_evidence_packs_run",
        "run_id_step5_4": run_id,
        "created_utc": now_utc_iso(),
        "pack_version": EVIDENCE_PACK_CONTRACT_VERSION,
        "artifacts": {
            "kc_evidence_packs_jsonl": rel_path(packs_path),
            "evidence_pack_stats_json": rel_path(stats_path),
        },
        "source_manifests": source_manifests,
        "slice": {
            "exact_kc_ids": [str(row.get("kc_id") or "") for row in selected_kc_rows],
            "limit_kcs": len(selected_kc_rows),
        },
    }
    write_json(manifest_path, manifest_payload)

    input_manifest_paths: List[Path] = [config_path, step5_3_set_manifest_path, step5_candidates_path]
    if kc_registry_path is not None:
        input_manifest_paths.append(kc_registry_path)
    if hierarchy_overlay_manifest_path is not None:
        input_manifest_paths.append(hierarchy_overlay_manifest_path)
    if sentence_corpus_path is not None:
        input_manifest_paths.append(sentence_corpus_path)
    if review_queue_path is not None:
        input_manifest_paths.append(review_queue_path)
    if step4_5_set_manifest_path is not None:
        input_manifest_paths.append(step4_5_set_manifest_path)
    write_json(audit_dir / "input_manifest.json", build_input_manifest(input_manifest_paths))

    summary = {
        "run_id_step5_4": run_id,
        "created_utc": now_utc_iso(),
        "pack_version": EVIDENCE_PACK_CONTRACT_VERSION,
        "selected_kc_ids": [str(row.get("kc_id") or "") for row in selected_kc_rows],
        "stats": stats,
        "step5_3_set_id": str(step5_3_set_obj.get("set_id") or ""),
        "env": env_snapshot(),
        "tool_versions": {
            "python": try_cmd_version([sys.executable, "--version"]),
        },
    }
    write_json(audit_dir / "summary.json", summary)

    set_manifest = {
        "schema_version": "1.0",
        "kind": "step5_4_kc_evidence_packs_set",
        "set_id": f"{run_id}_step5_4_kc_evidence_packs_set",
        "created_utc": now_utc_iso(),
        "run_id_step5_4": run_id,
        "artifacts": {
            "kc_evidence_packs_jsonl": rel_path(packs_path),
            "evidence_pack_stats_json": rel_path(stats_path),
            "evidence_pack_manifest_json": rel_path(manifest_path),
        },
        "upstream": {
            "step5_3_set_manifest_json": rel_path(step5_3_set_manifest_path),
            "kc_registry_jsonl": rel_path(kc_registry_path) if kc_registry_path is not None else "",
            "hierarchy_overlay_manifest_json": rel_path(hierarchy_overlay_manifest_path) if hierarchy_overlay_manifest_path is not None else "",
            "sentence_corpus_jsonl": rel_path(sentence_corpus_path) if sentence_corpus_path is not None else "",
            "review_queue_jsonl": rel_path(review_queue_path) if review_queue_path is not None else "",
            "step4_5_set_manifest_json": rel_path(step4_5_set_manifest_path) if step4_5_set_manifest_path is not None else "",
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
    active_pointer_path.parent.mkdir(parents=True, exist_ok=True)
    active_pointer_path.write_text(set_path.name + "\n", encoding="utf-8")

    output_manifest = {
        "processed_outputs": build_output_manifest(processed_dir),
        "audit_outputs": build_output_manifest(audit_dir),
        "set_manifest": {"path": rel_path(set_path)},
    }
    write_json(audit_dir / "output_manifest.json", output_manifest)

    print(
        json.dumps(
            {
                "run_id": run_id,
                "processed_dir": rel_path(processed_dir),
                "audit_dir": rel_path(audit_dir),
                "set_manifest": rel_path(set_path),
                "active_pointer": rel_path(active_pointer_path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
