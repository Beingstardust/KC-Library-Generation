from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from kc_l.kc.review_packets import build_default_output_dir, emit_review_packets_from_processed_dir
from kc_l.utils.json_io import read_json


def _resolve_repo_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (REPO_ROOT / path).resolve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Emit validated review packets from one Step 6 processed output directory.")
    parser.add_argument("--source-processed-dir", required=True, help="Repo-relative or absolute Step 6 processed output directory.")
    parser.add_argument("--output-dir", help="Optional repo-relative or absolute output directory for emitted review packets.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    source_processed_dir = _resolve_repo_path(args.source_processed_dir)
    if not source_processed_dir.exists():
        raise SystemExit(f"Source processed dir not found: {source_processed_dir}")

    output_dir = _resolve_repo_path(args.output_dir) if args.output_dir else build_default_output_dir(REPO_ROOT, source_processed_dir)
    result = emit_review_packets_from_processed_dir(
        source_processed_dir=source_processed_dir,
        output_dir=output_dir,
    )
    summary = read_json(result.summary_path)

    print(f"Source processed dir: {source_processed_dir}")
    print(f"Review packet output dir: {result.output_dir}")
    print(f"Packet file: {result.packet_path}")
    print(f"Summary file: {result.summary_path}")
    print(f"Preview file: {result.preview_path}")
    print(f"Packet count: {result.packet_count}")
    print(f"Skipped candidate count: {result.skipped_candidate_count}")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
