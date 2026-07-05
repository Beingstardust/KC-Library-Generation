from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_SRC = REPO_ROOT / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from kc_l.audit.manifests import build_input_manifest, build_output_manifest, env_snapshot, try_cmd_version
from kc_l.kc.restarted_review_audit_resolution import resolve_restarted_review_audits
from kc_l.utils.json_io import read_json, write_json


DEFAULT_CONFIG = Path("steps/step_06_10_kc_review_audit_resolution/resources/step6_10.slice8.yaml")


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


def choose_run_paths(processed_root: Path, runs_root: Path, sets_root: Path) -> Dict[str, Path]:
    base_stamp = utc_stamp()
    suffix = 0
    while True:
        run_id = base_stamp if suffix == 0 else f"{base_stamp}_{suffix:02d}"
        processed_dir = (processed_root / run_id).resolve()
        audit_dir = (runs_root / f"{run_id}_step6_10").resolve()
        set_path = (sets_root / f"{run_id}_step6_10_kc_review_audits_restarted_resolved_set.json").resolve()
        if not processed_dir.exists() and not audit_dir.exists() and not set_path.exists():
            return {
                "run_id_step6_10": Path(run_id),
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
    parser = argparse.ArgumentParser(description="Resolve restarted review-audit events with bounded final-text capture.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = resolve_repo_path(args.config)
    cfg = load_yaml_or_json(config_path)

    input_cfg = dict(cfg.get("inputs") or {})
    output_cfg = dict(cfg.get("outputs") or {})

    processed_root = resolve_repo_path(output_cfg.get("processed_root") or "data/processed/kc_review_audits_restarted_resolved")
    sets_root = resolve_repo_path(output_cfg.get("sets_root") or "data/processed/kc_review_audits_restarted_resolved/_sets")
    runs_root = resolve_repo_path(output_cfg.get("runs_root") or "data/runs")

    review_audit_set_path = resolve_repo_path(
        input_cfg.get("step6_9_set_manifest")
        or "data/processed/kc_review_audits_restarted/_sets/2026-03-23_011446_step6_9_kc_review_audits_restarted_set.json"
    )
    review_audit_set_obj = read_json(review_audit_set_path)
    source_step6_9_set_id = str(review_audit_set_obj.get("set_id") or review_audit_set_path.stem)
    source_review_audit_dir = resolve_repo_path(review_audit_set_obj.get("artifacts", {}).get("review_audit_jsonl")).parent
    review_audit_jsonl_path = source_review_audit_dir / "review_audit.jsonl"
    review_audit_summary_path = source_review_audit_dir / "review_audit_summary.json"

    step6_8_set_path = resolve_repo_path(review_audit_set_obj.get("upstream", {}).get("step6_8_set_manifest_json"))
    step6_8_set_obj = read_json(step6_8_set_path)
    source_step6_8_set_id = str(step6_8_set_obj.get("set_id") or step6_8_set_path.stem)
    source_review_packet_dir = resolve_repo_path(step6_8_set_obj.get("artifacts", {}).get("review_packet_jsonl")).parent
    review_packet_jsonl_path = source_review_packet_dir / "review_packet.jsonl"
    review_packet_summary_path = source_review_packet_dir / "review_packet_summary.json"

    run_paths = choose_run_paths(processed_root, runs_root, sets_root)
    run_id = str(run_paths["run_id_step6_10"])
    processed_dir = run_paths["processed_dir"]
    audit_dir = run_paths["audit_dir"]
    set_path = run_paths["set_path"]
    processed_dir.mkdir(parents=True, exist_ok=False)
    audit_dir.mkdir(parents=True, exist_ok=False)
    sets_root.mkdir(parents=True, exist_ok=True)

    config_snapshot_path = copy_config_snapshot(config_path, audit_dir)

    result = resolve_restarted_review_audits(
        source_review_audit_dir=source_review_audit_dir,
        source_review_packet_dir=source_review_packet_dir,
        output_dir=processed_dir,
    )

    resolution_summary = read_json(result.summary_path)
    input_manifest = build_input_manifest(
        [
            config_path,
            review_audit_set_path,
            review_audit_jsonl_path,
            review_audit_summary_path,
            step6_8_set_path,
            review_packet_jsonl_path,
            review_packet_summary_path,
        ]
    )
    write_json(audit_dir / "input_manifest.json", input_manifest)

    summary = {
        "run_id": run_id,
        "created_utc": now_utc_iso(),
        "source_step6_9_set_id": source_step6_9_set_id,
        "source_step6_8_set_id": source_step6_8_set_id,
        "source_review_audit_dir": rel_path(source_review_audit_dir),
        "source_review_packet_dir": rel_path(source_review_packet_dir),
        "stats": resolution_summary,
        "env": env_snapshot(),
        "tool_versions": {
            "python": try_cmd_version([sys.executable, "--version"]),
        },
    }
    write_json(audit_dir / "summary.json", summary)

    set_manifest = {
        "schema_version": "1.0",
        "kind": "step6_10_kc_review_audits_restarted_resolved_set",
        "set_id": f"{run_id}_step6_10_kc_review_audits_restarted_resolved_set",
        "created_utc": now_utc_iso(),
        "run_id_step6_10": run_id,
        "artifacts": {
            "review_audit_resolved_jsonl": rel_path(result.resolved_audit_jsonl_path),
            "review_audit_resolution_summary_json": rel_path(result.summary_path),
            "review_audit_resolution_preview_md": rel_path(result.preview_path),
        },
        "upstream": {
            "step6_9_set_manifest_json": rel_path(review_audit_set_path),
            "review_audit_jsonl": rel_path(review_audit_jsonl_path),
            "review_audit_summary_json": rel_path(review_audit_summary_path),
            "step6_8_set_manifest_json": rel_path(step6_8_set_path),
            "review_packet_jsonl": rel_path(review_packet_jsonl_path),
            "review_packet_summary_json": rel_path(review_packet_summary_path),
        },
        "slice": {
            "approved_kcs": list(resolution_summary.get("approved_kcs") or []),
            "edited_approved_kcs": list(resolution_summary.get("edited_approved_kcs") or []),
            "rejected_kcs": list(resolution_summary.get("rejected_kcs") or []),
            "unresolved_edit_kcs": list(resolution_summary.get("unresolved_edit_kcs") or []),
            "intentionally_blank_final_fields": list(resolution_summary.get("intentionally_blank_final_fields") or []),
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

    print(
        json.dumps(
            {
                "run_id": run_id,
                "processed_dir": rel_path(processed_dir),
                "audit_dir": rel_path(audit_dir),
                "event_count": result.event_count,
                "final_status_counts": resolution_summary.get("final_status_counts") or {},
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
