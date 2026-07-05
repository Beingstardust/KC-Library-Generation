from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from kc_l.kc.restarted_human_review_pass import build_restarted_human_reviewer_pass


def _resolve_repo_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (REPO_ROOT / path).resolve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build bounded restarted human-review-pass artifacts from restarted Step 6.8 packets."
    )
    parser.add_argument(
        "--review-packet-dir",
        required=True,
        help="Repo-relative or absolute restarted review-packet directory.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    review_packet_dir = _resolve_repo_path(args.review_packet_dir)
    verdict_path, workflow_json_path, workflow_md_path = build_restarted_human_reviewer_pass(review_packet_dir)
    print(f"Reviewer dry-run verdicts: {verdict_path}")
    print(f"Human-supervised draft actions JSON: {workflow_json_path}")
    print(f"Human-supervised workflow validation markdown: {workflow_md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
