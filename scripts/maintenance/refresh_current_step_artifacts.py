from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from kc_l.runtime import build_current_step_artifact_status, refresh_current_step_artifacts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Discover current Step 1, Step 1.5, Step 5.4, Step 6.6, Step 6.7, and Step 6.75 artifacts and refresh "
            "the stable alias files used by the clean-start Step 5 and Step 6 templates."
        )
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only report discovery status; do not write or remove alias files.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = build_current_step_artifact_status() if args.check else refresh_current_step_artifacts()
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
