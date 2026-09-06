from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from kc_l.forensics.step67_forensics import (
    audit_step67_touch_comparison,
    load_run_snapshot,
    render_touch_comparison_markdown,
    repo_root,
    resolve_step67_run_artifacts,
    write_json,
    write_text,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Step 6.7 touched-vs-untouched binding outcomes for two runs.")
    parser.add_argument("--baseline-run-id", default="2026-04-16_194203")
    parser.add_argument("--candidate-run-id", default="2026-04-17_194932")
    parser.add_argument(
        "--output-json",
        default="docs/operator_notes/step67_194203_vs_194932_touch_comparison_2026-04-18.json",
    )
    parser.add_argument(
        "--output-md",
        default="docs/operator_notes/step67_194203_vs_194932_touch_comparison_2026-04-18.md",
    )
    args = parser.parse_args()

    root = repo_root()
    baseline = load_run_snapshot(resolve_step67_run_artifacts(root, args.baseline_run_id), root)
    candidate = load_run_snapshot(resolve_step67_run_artifacts(root, args.candidate_run_id), root)
    payload = audit_step67_touch_comparison(baseline, candidate)
    write_json(Path(args.output_json), payload)
    write_text(Path(args.output_md), render_touch_comparison_markdown(payload))
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
