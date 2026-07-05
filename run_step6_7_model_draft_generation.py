from __future__ import annotations

import argparse
import json
from collections import Counter
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

REPO_ROOT = Path(__file__).resolve().parent
REPO_SRC = REPO_ROOT / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from kc_l.audit.manifests import build_input_manifest, build_output_manifest, env_snapshot, try_cmd_version
from kc_l.kc.draft_generation import DRAFT_CONTRACT_VERSION, select_overlay_kc_subset
from kc_l.utils.json_io import read_json, read_jsonl, write_json, write_jsonl
from kc_l.utils.kc_step67_model_drafting import Step67DraftingPolicy, Step67ModelRuntime, build_kc_draft_bundles_llm
from kc_l.utils.ollama_json import choose_generation_model, list_ollama_models, ollama_http_version


DEFAULT_CONFIG = Path("step6_7_full128_model_rewrite_2026-03-27.yaml")


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


def rel_path(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()



def evidence_pack_rows_to_step67_overlay_rows(pack_rows: List[Dict[str, Any]], *, source_step_kind: str) -> List[Dict[str, Any]]:
    """Convert manifest-authorized evidence pack rows into Step6.7 overlay-like rows.

    This is a compatibility bridge for non-KC knowledge-unit packs, especially topic units.
    It does not fabricate evidence. It exposes ordered evidence already admitted upstream.
    """
    overlay_rows: List[Dict[str, Any]] = []
    for pack_index, pack in enumerate(pack_rows):
        unit_id = str(
            pack.get("knowledge_unit_id")
            or pack.get("kc_id")
            or pack.get("topic_id")
            or pack.get("node_id")
            or ""
        )
        if not unit_id:
            continue
        unit_type = str(pack.get("knowledge_unit_type") or "knowledge_unit")
        canonical_name = str(pack.get("canonical_name") or "")
        ordered = [dict(item) for item in (pack.get("ordered_pack_for_drafting") or []) if isinstance(item, dict)]
        evidence_rows = ordered if ordered else [{}]

        for evidence_index, item in enumerate(evidence_rows):
            source_refs = item.get("source_refs") if isinstance(item.get("source_refs"), dict) else {}
            text = str(
                item.get("text")
                or item.get("quote")
                or item.get("candidate_sentence_text")
                or item.get("source_block_text")
                or ""
            )
            candidate_id = str(
                item.get("candidate_id")
                or item.get("source_candidate_id")
                or f"{unit_id}:pack:{pack_index}:item:{evidence_index}"
            )
            row: Dict[str, Any] = {
                "overlay_contract_version": "step67_manifest_pack_overlay_v1",
                "overlay_candidate_id": candidate_id,
                "source_candidate_index": evidence_index,
                "source_step_kind": source_step_kind,
                "kc_id": unit_id,
                "knowledge_unit_id": unit_id,
                "knowledge_unit_type": unit_type,
                "canonical_name": canonical_name,
                "aliases": list(pack.get("aliases") or []),
                "topic_path_ids": list(pack.get("topic_path_ids") or []),
                "topic_path_labels": list(pack.get("topic_path_labels") or []),
                "parent_topic_id": str(pack.get("parent_topic_id") or ""),
                "parent_topic_label": str(pack.get("parent_topic_label") or ""),
                "query_text": canonical_name,
                "query_used": canonical_name,
                "doc_id": str(item.get("doc_id") or source_refs.get("doc_id") or ""),
                "block_id": str(item.get("block_id") or source_refs.get("block_id") or ""),
                "page_index": item.get("page_index", source_refs.get("page_index")),
                "layer": str(item.get("layer") or ""),
                "sentence_id": str(item.get("sentence_id") or source_refs.get("sentence_id") or ""),
                "patch_id": str(item.get("patch_id") or source_refs.get("patch_id") or ""),
                "patch_heading": str(item.get("patch_heading") or ""),
                "quote_surface": text,
                "original_quote_surface": text,
                "source_block_text": str(item.get("source_block_text") or text),
                "source_block_text_raw": str(item.get("source_block_text") or text),
                "retrieval_scores": dict(item.get("retrieval_scores") or {}),
                "support_profile": dict(item.get("support_profile") or {}),
                "role_hint": {
                    "role": str(item.get("role") or item.get("slot_role") or ""),
                    "slot_role": str(item.get("slot_role") or item.get("role") or ""),
                    "raw_role_hint": str(item.get("role") or item.get("slot_role") or ""),
                },
                "evidence_pack_available": bool(ordered),
                "evidence_pack_version": str(pack.get("pack_version") or ""),
                "evidence_pack_quality": dict(pack.get("pack_quality") or {}),
                "ordered_pack_for_drafting": ordered,
                "drafting_core_evidence": list(pack.get("drafting_core_evidence") or []),
                "auxiliary_evidence": list(pack.get("auxiliary_evidence") or []),
                "review_needed_evidence": list(pack.get("review_needed_evidence") or []),
                "rejected_false_positive_evidence": list(pack.get("rejected_false_positive_evidence") or []),
                "near_miss_review_items": list(pack.get("near_miss_review_items") or []),
                "retrieval_gap_requests": list(pack.get("retrieval_gap_requests") or []),
                "review_risk_flags": list(pack.get("review_risk_flags") or []),
                "provenance_sidecar": dict(pack.get("provenance_sidecar") or {}),
                "source_evidence_pack_row_metadata_sidecars": dict(pack.get("source_evidence_pack_row_metadata_sidecars") or {}),
                "evidence_pack_membership": {
                    "source_pack_unit_id": unit_id,
                    "source_pack_unit_type": unit_type,
                    "source_pack_ordered_index": evidence_index,
                    "slot_roles": [str(item.get("role") or item.get("slot_role") or "")] if item else [],
                },
            }
            overlay_rows.append(row)
    return overlay_rows

def choose_run_paths(processed_root: Path, runs_root: Path, sets_root: Path) -> Dict[str, Path]:
    base_stamp = utc_stamp()
    suffix = 0
    while True:
        run_id = base_stamp if suffix == 0 else f"{base_stamp}_{suffix:02d}"
        processed_dir = (processed_root / run_id).resolve()
        audit_dir = (runs_root / f"{run_id}_step6_7").resolve()
        set_path = (sets_root / f"{run_id}_step6_7_kc_drafts_set.json").resolve()
        if not processed_dir.exists() and not audit_dir.exists() and not set_path.exists():
            return {
                "run_id_step6_7": Path(run_id),
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run model-backed Step 6.7 KC draft generation from a Step 6.6 overlay.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--limit-kcs", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = resolve_repo_path(args.config)
    cfg = load_yaml_or_json(config_path)

    input_cfg = dict(cfg.get("inputs") or {})
    output_cfg = dict(cfg.get("outputs") or {})
    slice_cfg = dict(cfg.get("slice") or {})
    selection_cfg = dict(cfg.get("selection") or {})
    drafting_cfg = dict(cfg.get("drafting") or {})
    model_cfg = dict(cfg.get("model") or {})
    if not model_cfg:
        raise RuntimeError("Model-backed Step 6.7 requires a `model` section in the config.")

    processed_root = resolve_repo_path(output_cfg.get("processed_root") or "data/processed/kc_drafts")
    sets_root = resolve_repo_path(output_cfg.get("sets_root") or "data/processed/kc_drafts/_sets")
    runs_root = resolve_repo_path(output_cfg.get("runs_root") or "data/runs")

    step6_6_set_path = resolve_repo_path(input_cfg.get("step6_6_set_manifest"))
    step6_6_set_obj = read_json(step6_6_set_path)
    overlay_path = resolve_repo_path(step6_6_set_obj.get("artifacts", {}).get("candidate_sentence_overlay_jsonl"))
    overlay_stats_path = resolve_repo_path(step6_6_set_obj.get("artifacts", {}).get("overlay_stats_json"))
    reference_step6_7_set_path = None
    reference_step6_7_set_obj: Dict[str, Any] = {}
    reference_bundles_by_kc: Dict[str, Dict[str, Any]] = {}
    reference_scope_step6_7_set_path = None
    reference_scope_step6_7_set_obj: Dict[str, Any] = {}
    reference_scope_bundles_by_kc: Dict[str, Dict[str, Any]] = {}
    if input_cfg.get("reference_step6_7_set_manifest"):
        reference_step6_7_set_path = resolve_repo_path(input_cfg.get("reference_step6_7_set_manifest"))
        reference_step6_7_set_obj = read_json(reference_step6_7_set_path)
        reference_bundle_path = resolve_repo_path(reference_step6_7_set_obj.get("artifacts", {}).get("kc_draft_bundles_jsonl"))
        reference_bundles = read_jsonl(reference_bundle_path)
        reference_bundles_by_kc = {
            str(bundle.get("kc_id") or ""): dict(bundle)
            for bundle in reference_bundles
            if str(bundle.get("kc_id") or "")
        }
    if input_cfg.get("reference_scope_step6_7_set_manifest"):
        reference_scope_step6_7_set_path = resolve_repo_path(input_cfg.get("reference_scope_step6_7_set_manifest"))
        reference_scope_step6_7_set_obj = read_json(reference_scope_step6_7_set_path)
        reference_scope_bundle_path = resolve_repo_path(
            reference_scope_step6_7_set_obj.get("artifacts", {}).get("kc_draft_bundles_jsonl")
        )
        reference_scope_bundles = read_jsonl(reference_scope_bundle_path)
        reference_scope_bundles_by_kc = {
            str(bundle.get("kc_id") or ""): dict(bundle)
            for bundle in reference_scope_bundles
            if str(bundle.get("kc_id") or "")
        }

    overlay_rows = read_jsonl(overlay_path)
    unit_drafting_cfg = dict(cfg.get("unit_drafting") or {})
    include_manifest_authorized_topic_units = bool(
        unit_drafting_cfg.get("include_manifest_authorized_topic_units", True)
    )
    topic_pack_path = None
    topic_overlay_rows: List[Dict[str, Any]] = []
    if include_manifest_authorized_topic_units:
        manifest_bridge = dict(step6_6_set_obj.get("manifest_bridge") or {})
        upstream_bridge = dict(step6_6_set_obj.get("upstream") or {})
        topic_pack_raw = (
            manifest_bridge.get("authorized_topic_evidence_pack_jsonl")
            or upstream_bridge.get("step6_authorized_topic_evidence_pack_jsonl")
            or input_cfg.get("topic_evidence_pack_jsonl")
        )
        if topic_pack_raw:
            topic_pack_path = resolve_repo_path(topic_pack_raw)
            topic_pack_rows = read_jsonl(topic_pack_path)
            topic_overlay_rows = evidence_pack_rows_to_step67_overlay_rows(
                topic_pack_rows,
                source_step_kind="topic_evidence_pack",
            )
            overlay_rows.extend(topic_overlay_rows)
    exact_kc_ids = [str(item) for item in slice_cfg.get("exact_kc_ids") or step6_6_set_obj.get("slice", {}).get("exact_kc_ids") or []]
    limit_kcs = args.limit_kcs if args.limit_kcs is not None else slice_cfg.get("limit_kcs")
    selected_overlay_rows = select_overlay_kc_subset(
        overlay_rows,
        limit_kcs,
        exact_kc_ids=exact_kc_ids or None,
    )
    overlay_set_id = str(step6_6_set_obj.get("set_id") or "")
    for row in selected_overlay_rows:
        row["draft_input_overlay_set_id"] = overlay_set_id

    installed_models = list_ollama_models()
    model_name = choose_generation_model(installed_models, model_cfg)
    runtime = Step67ModelRuntime(
        base_url=str(model_cfg.get("base_url") or "http://127.0.0.1:11434"),
        model=model_name,
        max_retries=int(model_cfg.get("max_retries", 3)),
        num_ctx=int(model_cfg.get("num_ctx", 8192)),
        timeout_seconds=float(model_cfg.get("timeout_seconds", 180)),
        temperature=float(model_cfg.get("temperature", 0.0)),
        top_p=float(model_cfg.get("top_p", 1.0)),
        repeat_penalty=float(model_cfg.get("repeat_penalty", 1.0)),
        think=model_cfg.get("think"),
    )
    policy = Step67DraftingPolicy(
        definition_candidate_limit=int(drafting_cfg.get("definition_candidate_limit", 5)),
        scope_candidate_limit=int(drafting_cfg.get("scope_candidate_limit", 5)),
        family_context_limit=int(drafting_cfg.get("family_context_limit", 4)),
        completion_context_limit=int(drafting_cfg.get("completion_context_limit", 4)),
        evidence_text_max_chars=int(drafting_cfg.get("evidence_text_max_chars", 320)),
        max_bundle_size=int(selection_cfg.get("max_bundle_size", 6)),
        max_explanatory_candidates=int(selection_cfg.get("max_explanatory_candidates", 5)),
        short_definition_max_chars=int(drafting_cfg.get("short_definition_max_chars", 220)),
        short_definition_max_tokens=int(drafting_cfg.get("short_definition_max_tokens", 32)),
    )

    run_paths = choose_run_paths(processed_root, runs_root, sets_root)
    run_id = str(run_paths["run_id_step6_7"])
    processed_dir = run_paths["processed_dir"]
    audit_dir = run_paths["audit_dir"]
    set_path = run_paths["set_path"]
    processed_dir.mkdir(parents=True, exist_ok=False)
    audit_dir.mkdir(parents=True, exist_ok=False)
    sets_root.mkdir(parents=True, exist_ok=True)

    config_snapshot_path = copy_config_snapshot(config_path, audit_dir)

    bundles, draft_stats = build_kc_draft_bundles_llm(
        selected_overlay_rows,
        runtime=runtime,
        policy=policy,
        reference_bundles=reference_bundles_by_kc or None,
        reference_scope_bundles=reference_scope_bundles_by_kc or None,
    )

    bundles_path = processed_dir / "kc_draft_bundles.jsonl"
    stats_path = processed_dir / "draft_stats.json"
    write_jsonl(bundles_path, bundles)
    write_json(stats_path, draft_stats)

    input_manifest_paths: List[Path] = [
        config_path,
        step6_6_set_path,
        overlay_path,
        overlay_stats_path,
    ]
    if topic_pack_path is not None:
        input_manifest_paths.append(topic_pack_path)
    if reference_step6_7_set_path is not None:
        input_manifest_paths.append(reference_step6_7_set_path)
    if reference_scope_step6_7_set_path is not None:
        input_manifest_paths.append(reference_scope_step6_7_set_path)
    input_manifest = build_input_manifest(input_manifest_paths)
    write_json(audit_dir / "input_manifest.json", input_manifest)

    summary = {
        "run_id": run_id,
        "created_utc": now_utc_iso(),
        "draft_contract_version": DRAFT_CONTRACT_VERSION,
        "selected_kc_ids": [
            str(bundle.get("kc_id") or "")
            for bundle in bundles
            if str(bundle.get("knowledge_unit_type") or "kc") == "kc"
        ],
        "selected_knowledge_unit_ids": [str(bundle.get("knowledge_unit_id") or bundle.get("kc_id") or "") for bundle in bundles],
        "selected_unit_type_breakdown": dict(Counter(str(bundle.get("knowledge_unit_type") or "kc") for bundle in bundles)),
        "topic_overlay_rows_added": len(topic_overlay_rows),
        "source_set_ids": {
            "step6_6_overlay": overlay_set_id,
            "step5_3": str(bundles[0].get("source_set_id") or "") if bundles else "",
            "reference_step6_7": str(reference_step6_7_set_obj.get("set_id") or "") if reference_step6_7_set_path is not None else "",
            "reference_scope_step6_7": (
                str(reference_scope_step6_7_set_obj.get("set_id") or "")
                if reference_scope_step6_7_set_path is not None
                else ""
            ),
        },
        "model_runtime": {
            "base_url": runtime.base_url,
            "model_name": model_name,
        },
        "stats": draft_stats,
        "env": env_snapshot(),
        "tool_versions": {
            "python": try_cmd_version([sys.executable, "--version"]),
            "ollama_http_version": ollama_http_version(runtime.base_url),
        },
    }
    write_json(audit_dir / "summary.json", summary)

    set_manifest = {
        "schema_version": "1.0",
        "kind": "step6_7_kc_drafts_set",
        "set_id": f"{run_id}_step6_7_kc_drafts_set",
        "created_utc": now_utc_iso(),
        "run_id_step6_7": run_id,
        "artifacts": {
            "kc_draft_bundles_jsonl": rel_path(bundles_path),
            "knowledge_unit_draft_bundles_jsonl": rel_path(bundles_path),
            "draft_stats_json": rel_path(stats_path),
        },
        "upstream": {
            "step6_6_set_manifest_json": rel_path(step6_6_set_path),
            "candidate_sentence_overlay_jsonl": rel_path(overlay_path),
            "overlay_stats_json": rel_path(overlay_stats_path),
        },
        "slice": {
            "exact_kc_ids": [str(bundle.get("kc_id") or "") for bundle in bundles],
            "limit_kcs": len(bundles),
        },
        "audit": {
            "run_dir": rel_path(audit_dir),
            "config_snapshot": rel_path(config_snapshot_path),
            "input_manifest": rel_path(audit_dir / "input_manifest.json"),
            "summary": rel_path(audit_dir / "summary.json"),
            "output_manifest": rel_path(audit_dir / "output_manifest.json"),
        },
    }
    if reference_step6_7_set_path is not None:
        set_manifest["upstream"]["reference_step6_7_set_manifest_json"] = rel_path(reference_step6_7_set_path)
    if reference_scope_step6_7_set_path is not None:
        set_manifest["upstream"]["reference_scope_step6_7_set_manifest_json"] = rel_path(reference_scope_step6_7_set_path)
    write_json(set_path, set_manifest)

    output_manifest = {
        "processed_outputs": build_output_manifest(processed_dir),
        "audit_outputs": build_output_manifest(audit_dir),
        "set_manifest": {
            "path": rel_path(set_path),
        },
    }
    write_json(audit_dir / "output_manifest.json", output_manifest)

    print(
        json.dumps(
            {
                "run_id": run_id,
                "processed_dir": rel_path(processed_dir),
                "audit_dir": rel_path(audit_dir),
                "model_name": model_name,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
