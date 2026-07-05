from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_SRC = REPO_ROOT / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from kc_l.kc_drafting.orchestration import run_step6_7b_pipeline


DEFAULT_CONFIG = Path("steps/step_06_7b_seed_floor_triage_and_rescue/resources/step6_7b.slice10.yaml")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Triage and rescue Step 6.7 seed-floor fallback KC bundles into persistent Step 6.7B outputs."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    exit_code, payload = run_step6_7b_pipeline(
        config_path=args.config,
        repo_root=REPO_ROOT,
    )
    print(json.dumps(payload, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
