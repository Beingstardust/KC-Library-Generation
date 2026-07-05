from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from kc_l.kc.restarted_reviewer_session import build_restarted_reviewer_session_artifacts


def _resolve_repo_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (REPO_ROOT / path).resolve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build restarted reviewer-session artifacts from restarted Step 6.8 packet outputs only."
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
    manual_path, session_md_path, manifest_path = build_restarted_reviewer_session_artifacts(review_packet_dir)
    print(f"Manual inspection bundle: {manual_path}")
    print(f"Real reviewer session markdown: {session_md_path}")
    print(f"Real reviewer session manifest JSON: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
