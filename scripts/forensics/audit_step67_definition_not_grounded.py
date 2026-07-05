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
    audit_step67_definition_not_grounded_cases,
    audit_step67_persistent_regressions,
    load_run_snapshot,
    render_definition_not_grounded_markdown,
    render_persistent_regressions_markdown,
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
    "KC_CLU_DBS_002",
    "KC_EVAL_SAMP_001",
]


def _default_output_paths(
    *,
    baseline_run_id: str,
    candidate_run_id: str,
    comparison_run_ids: list[str],
) -> dict[str, str]:
    comparison_label = "__".join(comparison_run_ids) if comparison_run_ids else candidate_run_id
    return {
        "output_json": f"docs/operator_notes/step67_definition_not_grounded_{candidate_run_id}.json",
        "output_md": f"docs/operator_notes/step67_definition_not_grounded_{candidate_run_id}.md",
        "persistent_output_json": (
            f"docs/operator_notes/step67_persistent_regressions_{baseline_run_id}_{comparison_label}.json"
        ),
        "persistent_output_md": (
            f"docs/operator_notes/step67_persistent_regressions_{baseline_run_id}_{comparison_label}.md"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit the Step 6.7 definition_not_grounded seam and persistent regressions.")
    parser.add_argument("--baseline-run-id", default="2026-04-16_194203")
    parser.add_argument("--candidate-run-id", default="2026-04-18_005843")
    parser.add_argument(
        "--comparison-run-id",
        action="append",
        dest="comparison_run_ids",
        default=[],
        help="Additional candidate runs to compare against the accepted baseline for persistent-regression analysis.",
    )
    parser.add_argument("--kc-id", action="append", dest="kc_ids", default=[])
    parser.add_argument("--output-json")
    parser.add_argument("--output-md")
    parser.add_argument("--persistent-output-json")
    parser.add_argument("--persistent-output-md")
    args = parser.parse_args()

    root = repo_root()
    baseline = load_run_snapshot(resolve_step67_run_artifacts(root, args.baseline_run_id), root)
    candidate = load_run_snapshot(resolve_step67_run_artifacts(root, args.candidate_run_id), root)
    comparison_run_ids = args.comparison_run_ids or [args.candidate_run_id]
    comparison_snapshots = [
        load_run_snapshot(resolve_step67_run_artifacts(root, run_id), root)
        for run_id in comparison_run_ids
    ]
    kc_ids = args.kc_ids or list(DEFAULT_KC_IDS)
    default_outputs = _default_output_paths(
        baseline_run_id=args.baseline_run_id,
        candidate_run_id=args.candidate_run_id,
        comparison_run_ids=comparison_run_ids,
    )
    output_json = args.output_json or default_outputs["output_json"]
    output_md = args.output_md or default_outputs["output_md"]
    persistent_output_json = args.persistent_output_json or default_outputs["persistent_output_json"]
    persistent_output_md = args.persistent_output_md or default_outputs["persistent_output_md"]

    definition_not_grounded_payload = audit_step67_definition_not_grounded_cases(candidate)
    persistent_regression_payload = audit_step67_persistent_regressions(
        baseline,
        comparison_snapshots,
        kc_ids=kc_ids,
    )

    write_json(Path(output_json), definition_not_grounded_payload)
    write_text(Path(output_md), render_definition_not_grounded_markdown(definition_not_grounded_payload))
    write_json(Path(persistent_output_json), persistent_regression_payload)
    write_text(Path(persistent_output_md), render_persistent_regressions_markdown(persistent_regression_payload))

    print(
        json.dumps(
            {
                "definition_not_grounded_output_json": output_json,
                "persistent_regression_output_json": persistent_output_json,
                "definition_not_grounded_case_count": definition_not_grounded_payload["definition_not_grounded_case_count"],
                "persistent_regression_count": persistent_regression_payload["persistent_regression_count"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
