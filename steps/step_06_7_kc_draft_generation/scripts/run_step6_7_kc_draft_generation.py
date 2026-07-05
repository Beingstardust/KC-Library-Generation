from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_SRC = REPO_ROOT / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from kc_l.kc_drafting.backend import ensure_llm_runtime_available
from kc_l.kc_drafting.config import normalize_runner_config
from kc_l.kc_drafting.orchestration import run_step6_7_pipeline
from kc_l.kc_drafting.provenance import build_drafting_runtime_record


DEFAULT_CONFIG = Path("steps/step_06_7_kc_draft_generation/resources/step6_7.012531.packet_multicandidate_full.yaml")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Step 6.7 KC draft bundles from the authoritative drafting package.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--limit-kcs", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    exit_code, payload = run_step6_7_pipeline(
        config_path=args.config,
        repo_root=REPO_ROOT,
        limit_kcs=args.limit_kcs,
    )
    print(json.dumps(payload, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
