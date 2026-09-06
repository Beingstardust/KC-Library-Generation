from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from kc_l.runtime import render_main_quest_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render and validate operator-shell main-quest config overlays. This checks config structure and references, not full retained-pipeline runtime readiness."
    )
    parser.add_argument("--mode", choices=("local_gpu", "hpc_gpu"), required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = render_main_quest_config(args.mode, persist=True)
    print(
        json.dumps(
            {
                "mode": result.mode,
                "ok": result.report["ok"],
                "status_scope": result.report["status_scope"],
                "validation_scope": result.report["validation_scope"],
                "truth_boundary": result.report["truth_boundary"],
                "full_pipeline_runnable_claimed": result.report["full_pipeline_runnable_claimed"],
                "strict_runtime_readiness_checked": result.report["strict_runtime_readiness_checked"],
                "operator_shell_config_valid": result.report["operator_shell_config_valid"],
                "input_overlay_path": result.report["input_overlay_path"],
                "runtime_profile_status": result.report["runtime_profile_status"],
                "example_overlay": result.report["example_overlay"],
                "warnings": result.report["warnings"],
                "output_yaml_path": result.output_yaml_path.relative_to(REPO_ROOT).as_posix(),
                "output_report_path": result.output_report_path.relative_to(REPO_ROOT).as_posix(),
            },
            indent=2,
        )
    )
    return 0 if result.report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
