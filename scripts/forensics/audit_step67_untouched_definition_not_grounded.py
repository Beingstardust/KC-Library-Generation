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
    audit_step67_untouched_definition_not_grounded_regressions,
    load_run_snapshot,
    render_untouched_definition_not_grounded_markdown,
    repo_root,
    resolve_step67_run_artifacts,
    write_json,
    write_text,
)


DEFAULT_KC_IDS = [
    "KC_CLU_EVAL_001",
    "KC_CLU_EVAL_002",
    "KC_DE_PREP_004",
    "KC_EVAL_BASIC_005",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit untouched Step 6.7 definition_not_grounded regressions.")
    parser.add_argument("--baseline-run-id", default="2026-04-16_194203")
    parser.add_argument("--candidate-run-id", default="2026-04-17_194932")
    parser.add_argument("--kc-id", action="append", dest="kc_ids", default=[])
    parser.add_argument(
        "--output-json",
        default="docs/operator_notes/step67_untouched_definition_not_grounded_regressions_2026-04-18.json",
    )
    parser.add_argument(
        "--output-md",
        default="docs/operator_notes/step67_untouched_definition_not_grounded_regressions_2026-04-18.md",
    )
    args = parser.parse_args()

    kc_ids = args.kc_ids or list(DEFAULT_KC_IDS)
    root = repo_root()
    baseline = load_run_snapshot(resolve_step67_run_artifacts(root, args.baseline_run_id), root)
    candidate = load_run_snapshot(resolve_step67_run_artifacts(root, args.candidate_run_id), root)
    payload = audit_step67_untouched_definition_not_grounded_regressions(
        baseline,
        candidate,
        kc_ids=kc_ids,
    )
    write_json(Path(args.output_json), payload)
    write_text(Path(args.output_md), render_untouched_definition_not_grounded_markdown(payload))
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
