from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from kc_l.kc.restarted_human_review_capture import build_restarted_human_review_capture
from kc_l.kc.restarted_reviewer_session import build_restarted_reviewer_session_artifacts


def _resolve_repo_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (REPO_ROOT / path).resolve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build blank restarted human-review capture artifacts for a restarted Step 6.8 packet surface."
    )
    parser.add_argument(
        "--review-packet-dir",
        required=True,
        help="Repo-relative or absolute restarted review-packet directory.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=12,
        help="Deterministic reviewer batch size over the neutral session order.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    review_packet_dir = _resolve_repo_path(args.review_packet_dir)
    manual_path, session_md_path, session_manifest_path = build_restarted_reviewer_session_artifacts(review_packet_dir)
    verdict_path, actions_path, workflow_md_path, capture_manifest_path = build_restarted_human_review_capture(
        review_packet_dir,
        batch_size=args.batch_size,
    )
    print(f"Manual inspection bundle: {manual_path}")
    print(f"Real reviewer session markdown: {session_md_path}")
    print(f"Real reviewer session manifest JSON: {session_manifest_path}")
    print(f"Reviewer dry-run verdict template: {verdict_path}")
    print(f"Human-supervised draft actions template: {actions_path}")
    print(f"Human-supervised workflow validation markdown: {workflow_md_path}")
    print(f"Human review capture manifest JSON: {capture_manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
