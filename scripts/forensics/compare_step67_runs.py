from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from kc_l.forensics.step67_forensics import compare_step67_runs, load_run_snapshot, repo_root, resolve_step67_run_artifacts


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare Step 6.7 runs KC by KC.")
    parser.add_argument("--baseline-run-id", default="2026-04-16_194203")
    parser.add_argument(
        "--candidate-run-id",
        action="append",
        dest="candidate_run_ids",
        default=[],
    )
    parser.add_argument("--output-json", default="")
    args = parser.parse_args()
    candidate_run_ids = args.candidate_run_ids or ["2026-04-16_230621", "2026-04-17_131400"]

    root = repo_root()
    baseline = load_run_snapshot(resolve_step67_run_artifacts(root, args.baseline_run_id), root)
    comparisons = [
        compare_step67_runs(
            baseline,
            load_run_snapshot(resolve_step67_run_artifacts(root, run_id), root),
        )
        for run_id in candidate_run_ids
    ]
    payload = {
        "baseline_run_id": args.baseline_run_id,
        "candidate_run_ids": candidate_run_ids,
        "comparisons": comparisons,
    }
    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
