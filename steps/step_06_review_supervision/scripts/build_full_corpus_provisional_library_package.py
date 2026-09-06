from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from build_provisional_machine_pass_library import build_full_provisional_machine_pass_library
from kc_l.kc.review_packets import build_default_output_dir, emit_review_packets_from_processed_dir
from kc_l.utils.json_io import read_json


def _resolve_repo_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (REPO_ROOT / path).resolve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit full-corpus review packets from one Step 6 processed output directory and assemble full provisional/sandbox library tiers."
    )
    parser.add_argument("--source-processed-dir", required=True, help="Repo-relative or absolute Step 6 processed output directory.")
    parser.add_argument("--output-dir", help="Optional repo-relative or absolute output directory for emitted review packets and assembled outputs.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    source_processed_dir = _resolve_repo_path(args.source_processed_dir)
    if not source_processed_dir.exists():
        raise SystemExit(f"Source processed dir not found: {source_processed_dir}")

    output_dir = _resolve_repo_path(args.output_dir) if args.output_dir else build_default_output_dir(REPO_ROOT, source_processed_dir)
    packet_result = emit_review_packets_from_processed_dir(
        source_processed_dir=source_processed_dir,
        output_dir=output_dir,
    )
    provisional_path, sandbox_path, manifest_path = build_full_provisional_machine_pass_library(output_dir)

    packet_summary = read_json(packet_result.summary_path)
    manifest = read_json(manifest_path)

    print(f"Source processed dir: {source_processed_dir}")
    print(f"Review packet output dir: {output_dir}")
    print(f"Packet file: {packet_result.packet_path}")
    print(f"Packet summary: {packet_result.summary_path}")
    print(f"Packet preview: {packet_result.preview_path}")
    print(f"Full provisional library: {provisional_path}")
    print(f"Full sandbox: {sandbox_path}")
    print(f"Full manifest: {manifest_path}")
    print(f"Packet count: {packet_result.packet_count}")
    print(f"Skipped candidate count: {packet_result.skipped_candidate_count}")
    print(json.dumps({
        "packet_summary": {
            "packet_count": packet_summary.get("packet_count"),
            "skipped_candidate_count": packet_summary.get("skipped_candidate_count"),
            "priority_bucket_counts": packet_summary.get("priority_bucket_counts"),
            "system_recommendation_counts": packet_summary.get("system_recommendation_counts"),
        },
        "assembly_counts": manifest.get("counts"),
        "source_scope": manifest.get("source_scope"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
