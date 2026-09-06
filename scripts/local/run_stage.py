from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from kc_l.runtime import build_operator_repo_status, build_stage_preflight, stage_catalog_rows


COMMAND_TO_STAGE_KEY = {
    "intake": "intake",
    "draft-preflight": "draft_generation",
    "review-preflight": "review_resolution",
    "freeze-preflight": "freeze_package_index",
}


def _print_text(payload: object) -> None:
    if isinstance(payload, list):
        for row in payload:
            if isinstance(row, dict):
                print(f"{row['key']}: {row['title']}")
                print(f"  command: {row['operator_command']}")
                print(f"  description: {row['description']}")
            else:
                print(row)
        print("note: these are operator-shell readiness and discoverability surfaces, not a full replacement for the retained legacy execution ladder.")
        return
    if isinstance(payload, dict):
        for key, value in payload.items():
            print(f"{key}: {value}")
        return
    print(payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Operator-shell readiness and discoverability surface for the KC Library repo. This CLI does not execute the full retained legacy pipeline."
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list", help="List the public operator stages.")
    subparsers.add_parser("status", help="Inspect operator-shell readiness and legacy-surface discoverability.")
    subparsers.add_parser("intake", help="Inspect source-preparation and cross-platform corpus-intake readiness in the operator shell.")
    subparsers.add_parser("draft-preflight", help="Inspect late-stage draft-lane preflight in the operator shell.")
    subparsers.add_parser("review-preflight", help="Inspect review-stage preflight in the operator shell.")
    subparsers.add_parser("freeze-preflight", help="Inspect freeze-and-index preflight in the operator shell.")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.command == "list":
        payload = stage_catalog_rows()
    elif args.command == "status":
        payload = build_operator_repo_status()
    else:
        payload = build_stage_preflight(COMMAND_TO_STAGE_KEY[args.command])

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        _print_text(payload)

    if isinstance(payload, dict) and payload.get("ok") is False:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
