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
from kc_l.kc.restarted_review_audits import emit_restarted_review_audits
from kc_l.utils.json_io import read_json, write_json


DEFAULT_CONFIG = Path("steps/step_06_9_kc_review_audit_ingestion/resources/step6_9.slice8.yaml")


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
        audit_dir = (runs_root / f"{run_id}_step6_9").resolve()
        set_path = (sets_root / f"{run_id}_step6_9_kc_review_audits_restarted_set.json").resolve()
        if not processed_dir.exists() and not audit_dir.exists() and not set_path.exists():
            return {
                "run_id_step6_9": Path(run_id),
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


def resolve_review_packet_manifest(review_packet_set_path: Path) -> Dict[str, Any]:
    """Read a Step 6.8 review-packet manifest, supporting both the legacy
    (set_id/artifacts) schema and the v2 (run_id/outputs) schema.

    v2 manifests declare invariants.legacy_step68_runner_not_used and have no
    artifacts/set_id keys, so detect on run_id+outputs rather than assuming.
    """
    review_packet_set_obj = read_json(review_packet_set_path)
    is_v2_manifest = "run_id" in review_packet_set_obj and "outputs" in review_packet_set_obj
    if is_v2_manifest:
        set_id = str(review_packet_set_obj.get("run_id") or review_packet_set_path.stem)
        review_packet_jsonl_path = resolve_repo_path(review_packet_set_obj.get("outputs", {}).get("review_packets_jsonl"))
        review_packet_summary_path = resolve_repo_path(review_packet_set_obj.get("outputs", {}).get("stats_json"))
    else:
        set_id = str(review_packet_set_obj.get("set_id") or review_packet_set_path.stem)
        review_packet_jsonl_path = resolve_repo_path(review_packet_set_obj.get("artifacts", {}).get("review_packet_jsonl"))
        review_packet_summary_path = resolve_repo_path(review_packet_set_obj.get("artifacts", {}).get("review_packet_summary_json"))
    return {
        "schema": "v2" if is_v2_manifest else "legacy",
        "set_id": set_id,
        "review_packet_jsonl_path": review_packet_jsonl_path,
        "review_packet_summary_path": review_packet_summary_path,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest restarted reviewer-pass outputs into scope-aware review-audit events.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = resolve_repo_path(args.config)
    cfg = load_yaml_or_json(config_path)

    input_cfg = dict(cfg.get("inputs") or {})
    output_cfg = dict(cfg.get("outputs") or {})

    processed_root = resolve_repo_path(output_cfg.get("processed_root") or "data/processed/kc_review_audits_restarted")
    sets_root = resolve_repo_path(output_cfg.get("sets_root") or "data/processed/kc_review_audits_restarted/_sets")
    runs_root = resolve_repo_path(output_cfg.get("runs_root") or "data/runs")

    review_packet_set_path = resolve_repo_path(
        input_cfg.get("review_packet_set_manifest")
        or "data/processed/step68_v2_review_packets_from_postprocessed_source/20260521T231531Z_current_postprocessed_source_runner_return_contract_fix/STEP68_V2_REVIEW_PACKET_MANIFEST.json"
    )
    manifest_fields = resolve_review_packet_manifest(review_packet_set_path)
    source_step6_8_set_id = manifest_fields["set_id"]
    review_packet_jsonl_path = manifest_fields["review_packet_jsonl_path"]
    review_packet_summary_path = manifest_fields["review_packet_summary_path"]
    source_review_packet_dir = review_packet_jsonl_path.parent
    reviewer_verdicts_path = source_review_packet_dir / "reviewer_dry_run_verdicts.json"
    draft_actions_path = source_review_packet_dir / "human_supervised_draft_actions.json"
    workflow_validation_path = source_review_packet_dir / "human_supervised_workflow_validation.md"
    manual_inspection_bundle_path = source_review_packet_dir / "manual_inspection_bundle.md"
    real_reviewer_session_md_path = source_review_packet_dir / "real_reviewer_session.md"
    real_reviewer_session_manifest_path = source_review_packet_dir / "real_reviewer_session_manifest.json"
    source_reviewer_session_run_id = source_review_packet_dir.name
    source_reviewer_session_set_id = None

    run_paths = choose_run_paths(processed_root, runs_root, sets_root)
    run_id = str(run_paths["run_id_step6_9"])
    processed_dir = run_paths["processed_dir"]
    audit_dir = run_paths["audit_dir"]
    set_path = run_paths["set_path"]
    processed_dir.mkdir(parents=True, exist_ok=False)
    audit_dir.mkdir(parents=True, exist_ok=False)
    sets_root.mkdir(parents=True, exist_ok=True)

    config_snapshot_path = copy_config_snapshot(config_path, audit_dir)

    result = emit_restarted_review_audits(
        source_review_packet_dir=source_review_packet_dir,
        output_dir=processed_dir,
        run_id_step6_9=run_id,
        source_review_packet_set_id=source_step6_8_set_id,
        source_reviewer_session_run_id=source_reviewer_session_run_id,
        source_reviewer_session_set_id=source_reviewer_session_set_id,
    )

    audit_summary = read_json(result.summary_path)
    input_manifest = build_input_manifest(
        [
            config_path,
            review_packet_set_path,
            review_packet_jsonl_path,
            review_packet_summary_path,
            reviewer_verdicts_path,
            draft_actions_path,
            workflow_validation_path,
            manual_inspection_bundle_path,
            real_reviewer_session_md_path,
            real_reviewer_session_manifest_path,
        ]
    )
    write_json(audit_dir / "input_manifest.json", input_manifest)

    summary = {
        "run_id": run_id,
        "created_utc": now_utc_iso(),
        "source_step6_8_set_id": source_step6_8_set_id,
        "source_review_packet_dir": rel_path(source_review_packet_dir),
        "source_reviewer_session_run_id": source_reviewer_session_run_id,
        "source_reviewer_session_set_id": source_reviewer_session_set_id,
        "stats": audit_summary,
        "env": env_snapshot(),
        "tool_versions": {
            "python": try_cmd_version([sys.executable, "--version"]),
        },
    }
    write_json(audit_dir / "summary.json", summary)

    set_manifest = {
        "schema_version": "1.0",
        "kind": "step6_9_kc_review_audits_restarted_set",
        "set_id": f"{run_id}_step6_9_kc_review_audits_restarted_set",
        "created_utc": now_utc_iso(),
        "run_id_step6_9": run_id,
        "artifacts": {
            "review_audit_jsonl": rel_path(result.audit_jsonl_path),
            "review_audit_summary_json": rel_path(result.summary_path),
            "review_audit_preview_md": rel_path(result.preview_path),
        },
        "upstream": {
            "step6_8_set_manifest_json": rel_path(review_packet_set_path),
            "review_packet_jsonl": rel_path(review_packet_jsonl_path),
            "review_packet_summary_json": rel_path(review_packet_summary_path),
            "reviewer_dry_run_verdicts_json": rel_path(reviewer_verdicts_path),
            "human_supervised_draft_actions_json": rel_path(draft_actions_path),
            "human_supervised_workflow_validation_md": rel_path(workflow_validation_path),
            "manual_inspection_bundle_md": rel_path(manual_inspection_bundle_path),
            "real_reviewer_session_md": rel_path(real_reviewer_session_md_path),
            "real_reviewer_session_manifest_json": rel_path(real_reviewer_session_manifest_path),
        },
        "slice": {
            "included_kcs": list(audit_summary.get("included_kcs") or []),
            "approved_kcs": list(audit_summary.get("approved_kcs") or []),
            "pending_edit_kcs": list(audit_summary.get("pending_edit_kcs") or []),
            "rejected_kcs": list(audit_summary.get("rejected_kcs") or []),
            "excluded_kcs": [
                {
                    "kc_candidate_id": item.get("kc_candidate_id"),
                    "summary_exclusion_reasons": list(item.get("summary_exclusion_reasons") or []),
                }
                for item in audit_summary.get("excluded_case_assessments") or []
            ],
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
                "action_counts": audit_summary.get("action_counts") or {},
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
