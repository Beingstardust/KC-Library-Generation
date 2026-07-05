from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_SRC = REPO_ROOT / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from kc_l.kc_drafting.orchestration import run_step6_8_pipeline
from kc_l.kc_drafting.provenance import normalize_step6_7_drafting_runtime


DEFAULT_CONFIG = Path("steps/step_06_8_kc_review_packet_emission/resources/step6_8.slice10.yaml")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Emit restarted review packets from the authoritative drafting package.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    exit_code, payload = run_step6_8_pipeline(
        config_path=args.config,
        repo_root=REPO_ROOT,
    )
    print(json.dumps(payload, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
