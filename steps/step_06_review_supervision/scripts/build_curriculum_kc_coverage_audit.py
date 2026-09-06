from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from kc_l.utils.json_io import read_json, read_jsonl, write_json


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")


def _resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (REPO_ROOT / path).resolve()


def _relative_repo_path(path: Path) -> str:
    return str(path.resolve().relative_to(REPO_ROOT))


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _load_required_json(review_packet_dir: Path, name: str) -> dict[str, Any]:
    path = review_packet_dir / name
    if not path.exists():
        raise FileNotFoundError(f"Missing required artifact under {review_packet_dir}: {name}")
    obj = read_json(path)
    if not isinstance(obj, dict):
        raise ValueError(f"Expected JSON object at {path}")
    return obj


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a validation bundle for the curriculum-coverage layer over the current restarted Step 6.8 surface."
    )
    parser.add_argument(
        "--review-packet-dir",
        required=True,
        help="Repo-relative or absolute restarted review-packet directory.",
    )
    parser.add_argument(
        "--output-dir",
        help="Optional repo-relative or absolute output directory. Defaults under data/runs/_audit/.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    review_packet_dir = _resolve_repo_path(args.review_packet_dir)

    coverage_rows = read_jsonl(review_packet_dir / "curriculum_kc_coverage_manifest.jsonl")
    coverage_summary = _load_required_json(review_packet_dir, "curriculum_kc_coverage_summary.json")
    review_summary = _load_required_json(review_packet_dir, "review_packet_summary.json")
    session_manifest = _load_required_json(review_packet_dir, "real_reviewer_session_manifest.json")
    capture_manifest = _load_required_json(review_packet_dir, "human_review_capture_manifest.json")
    packets = read_jsonl(review_packet_dir / "review_packets.jsonl")

    output_dir = (
        _resolve_repo_path(args.output_dir)
        if args.output_dir
        else (REPO_ROOT / "data" / "runs" / "_audit" / f"{_utc_stamp()}_curriculum_kc_coverage_validation").resolve()
    )
    output_dir.mkdir(parents=True, exist_ok=False)

    coverage_row_count = len(coverage_rows)
    ready_packet_count = len(packets)
    session_bucket_counts = Counter(
        _as_text(item.get("session_bucket"))
        for item in session_manifest.get("session_packet_order") or []
        if isinstance(item, dict)
    )
    criteria_ok = all("kc_specific_criteria" in row and not _as_text(row.get("kc_specific_criteria")) for row in coverage_rows)
    packet_criteria_ok = all(
        "kc_specific_criteria" in packet and not _as_text(packet.get("kc_specific_criteria")) for packet in packets
    )

    represented_count = int(coverage_summary.get("represented_kc_count") or 0)
    missing_count = int(coverage_summary.get("missing_kc_count") or 0)
    quarantine_count = int(coverage_summary.get("quarantine_count") or 0)
    excluded_count = int(coverage_summary.get("excluded_count") or 0)

    validation_summary = {
        "generated_utc": _now_utc_iso(),
        "review_packet_dir": _relative_repo_path(review_packet_dir),
        "total_curriculum_atomic_kc_count": int(coverage_summary.get("total_curriculum_atomic_kc_count") or 0),
        "represented_kc_count": represented_count,
        "missing_kc_count": missing_count,
        "ready_packet_count": ready_packet_count,
        "quarantine_count": quarantine_count,
        "excluded_count": excluded_count,
        "counts_by_state_tier": dict(coverage_summary.get("representation_tier_counts") or {}),
        "drafting_state_counts": dict(coverage_summary.get("drafting_state_counts") or {}),
        "review_lane_state_counts": dict(coverage_summary.get("review_lane_state_counts") or {}),
        "approved_frozen_state_counts": dict(coverage_summary.get("approved_frozen_state_counts") or {}),
        "session_bucket_counts": dict(session_bucket_counts),
        "segmentation_eligible_count": int(coverage_summary.get("segmentation_eligible_count") or 0),
        "evaluation_eligible_count": int(coverage_summary.get("evaluation_eligible_count") or 0),
        "validation_checks": {
            "all_curriculum_atomic_kcs_represented": missing_count == 0,
            "coverage_row_count_matches_summary": coverage_row_count == represented_count,
            "ready_packet_count_matches_summary": ready_packet_count == int(review_summary.get("packet_count") or 0),
            "quarantine_count_matches_summary": quarantine_count == int(review_summary.get("quarantine_count") or 0),
            "excluded_count_matches_summary": excluded_count == len(review_summary.get("excluded_kcs") or []),
            "kc_specific_criteria_present_and_empty": bool(coverage_summary.get("kc_specific_criteria_present_and_empty"))
            and criteria_ok
            and packet_criteria_ok,
            "approved_frozen_library_semantics_unchanged": _as_text(
                coverage_summary.get("approved_frozen_boundary_mode")
            )
            == "parallel_not_modified",
            "reviewer_session_artifacts_build": int(session_manifest.get("packet_count") or 0) == ready_packet_count,
            "human_review_capture_artifacts_build": int(capture_manifest.get("packet_count") or 0) == ready_packet_count,
        },
        "approved_frozen_artifact_present_in_repo": bool(coverage_summary.get("approved_frozen_artifact_present_in_repo")),
        "missing_kc_ids": list(coverage_summary.get("missing_kc_ids") or []),
        "session_order_preview": [
            {
                "session_order": item.get("session_order"),
                "kc_candidate_id": item.get("kc_candidate_id"),
                "session_bucket": item.get("session_bucket"),
                "review_priority_bucket": item.get("review_priority_bucket"),
                "system_recommendation": item.get("system_recommendation"),
            }
            for item in (session_manifest.get("session_packet_order") or [])[:15]
            if isinstance(item, dict)
        ],
        "artifacts": {
            "curriculum_kc_coverage_manifest_jsonl": _relative_repo_path(
                review_packet_dir / "curriculum_kc_coverage_manifest.jsonl"
            ),
            "curriculum_kc_coverage_summary_json": _relative_repo_path(
                review_packet_dir / "curriculum_kc_coverage_summary.json"
            ),
            "review_packets_jsonl": _relative_repo_path(review_packet_dir / "review_packets.jsonl"),
            "review_packet_summary_json": _relative_repo_path(review_packet_dir / "review_packet_summary.json"),
            "real_reviewer_session_manifest_json": _relative_repo_path(
                review_packet_dir / "real_reviewer_session_manifest.json"
            ),
            "human_review_capture_manifest_json": _relative_repo_path(
                review_packet_dir / "human_review_capture_manifest.json"
            ),
        },
    }

    write_json(output_dir / "validation_summary.json", validation_summary)
    print(
        json.dumps(
            {
                "output_dir": _relative_repo_path(output_dir),
                "represented_kc_count": represented_count,
                "missing_kc_count": missing_count,
                "ready_packet_count": ready_packet_count,
                "quarantine_count": quarantine_count,
                "excluded_count": excluded_count,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
