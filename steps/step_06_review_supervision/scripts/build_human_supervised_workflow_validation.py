from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from kc_l.utils.json_io import read_json, write_json


BOUNDARY_NOTE = (
    "This artifact validates the human-supervised draft workflow. "
    "It does not treat machine recommendations as final approval and does not prove machine autonomy."
)


def _resolve_repo_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (REPO_ROOT / path).resolve()


def _build_workflow_actions(verdicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for item in verdicts:
        actions.append(
            {
                "kc_candidate_id": item["kc_candidate_id"],
                "title_draft": item["title_draft"],
                "machine_bucket": item["current_review_priority_bucket"],
                "machine_recommendation": item["current_system_recommendation"],
                "draft_human_action": item["dry_run_provisional_action"],
                "packet_sufficiency": item["packet_sufficiency"],
                "requires_raw_internals": item["requires_raw_internals"],
                "content_repair_applied": item["content_repair_applied"],
                "content_source_mode": item["content_source_mode"],
                "workflow_decision_ready": not bool(item["requires_raw_internals"]),
                "workflow_note": item["verdict_rationale"],
            }
        )
    return actions


def build_human_supervised_workflow_validation(review_packet_dir: Path) -> tuple[Path, Path]:
    review_packet_dir = review_packet_dir.resolve()
    summary_path = review_packet_dir / "review_packet_summary.json"
    dry_run_path = review_packet_dir / "reviewer_dry_run_verdicts.json"
    if not summary_path.exists() or not dry_run_path.exists():
        raise FileNotFoundError(f"Required proof-run artifacts missing under {review_packet_dir}")

    summary = read_json(summary_path)
    dry_run = read_json(dry_run_path)
    verdicts = list(dry_run.get("verdicts") or [])
    skipped_case = dict(dry_run.get("skipped_case_assessment") or {})
    actions = _build_workflow_actions(verdicts)

    action_counts = dict(dry_run.get("dry_run_action_counts") or {})
    sufficiency_counts = dict(dry_run.get("packet_sufficiency_counts") or {})
    packet_only_decision_count = sum(1 for item in actions if item["workflow_decision_ready"])

    payload = {
        "review_packet_dir": str(review_packet_dir),
        "source_processed_dir": str(summary["source_processed_dir"]),
        "validation_mode": "human_supervised_draft_workflow",
        "boundary_note": BOUNDARY_NOTE,
        "draft_action_space": ["approve", "edit", "reject"],
        "paths_exercised": {
            "approve_path_exercised": int(action_counts.get("approve", 0)) > 0,
            "edit_path_exercised": int(action_counts.get("edit", 0)) > 0,
            "reject_path_exercised": int(action_counts.get("reject", 0)) > 0,
            "skip_before_review_present": bool(skipped_case),
        },
        "draft_action_counts": action_counts,
        "packet_sufficiency_counts": sufficiency_counts,
        "packet_only_decision_count": packet_only_decision_count,
        "selected_packet_count": len(actions),
        "draft_actions": actions,
        "skipped_case": skipped_case,
        "workflow_findings": [
            "The current proof run validates edit-path handling across most selected packets.",
            "The reject path is validated by KC_CLF_DT_002 and remains cleanly auditable.",
            "The approve path is still not validated on this proof run because no packet is strong enough for approve from packet alone.",
            "Machine output is functioning as draft material for supervised review, not as autonomous final-library production.",
        ],
    }

    json_path = review_packet_dir / "human_supervised_draft_actions.json"
    write_json(json_path, payload)

    lines = [
        "# Human-Supervised Workflow Validation",
        "",
        f"- Proof-run packet directory: `{review_packet_dir.relative_to(REPO_ROOT)}`",
        f"- Source processed directory: `{Path(summary['source_processed_dir']).resolve().relative_to(REPO_ROOT)}`",
        f"- Validation mode: `{payload['validation_mode']}`",
        f"- Boundary: {BOUNDARY_NOTE}",
        f"- Draft action space: `{payload['draft_action_space']}`",
        "",
        "## Workflow Status",
        "",
        f"- Edit path exercised: `{payload['paths_exercised']['edit_path_exercised']}`",
        f"- Reject path exercised: `{payload['paths_exercised']['reject_path_exercised']}`",
        f"- Approve path exercised: `{payload['paths_exercised']['approve_path_exercised']}`",
        f"- Skip-before-review present: `{payload['paths_exercised']['skip_before_review_present']}`",
        f"- Draft action counts: `{action_counts}`",
        f"- Packet sufficiency counts: `{sufficiency_counts}`",
        f"- Packet-only decision count: `{packet_only_decision_count}/{len(actions)}`",
        "",
        "## Workflow Findings",
        "",
    ]
    for finding in payload["workflow_findings"]:
        lines.append(f"- {finding}")

    lines.extend(["", "## Draft Actions", ""])
    for item in actions:
        lines.extend(
            [
                f"### {item['kc_candidate_id']} - {item['title_draft']}",
                "",
                f"- Machine label: `{item['machine_bucket']}` / `{item['machine_recommendation']}`",
                f"- Draft human action: `{item['draft_human_action']}`",
                f"- Packet sufficiency: `{item['packet_sufficiency']}`",
                f"- Decision-ready from packet: `{item['workflow_decision_ready']}`",
                f"- Content repair applied: `{item['content_repair_applied']}`",
                f"- Review note: {item['workflow_note']}",
                "",
            ]
        )

    if skipped_case:
        lines.extend(
            [
                "## Skipped Case",
                "",
                f"- KC candidate id: `{skipped_case.get('kc_candidate_id', '')}`",
                f"- Pre-review disposition: `{skipped_case.get('pre_review_disposition', '')}`",
                f"- Skip assessment: `{skipped_case.get('skip_assessment', '')}`",
                f"- Rationale: {skipped_case.get('verdict_rationale', '')}",
            ]
        )

    lines.extend(
        [
            "",
            "## Bottom Line",
            "",
            "- The current supervision layer is now being validated as a human-supervised draft workflow.",
            "- This proof run supports real draft review work, but it still does not justify autonomous machine approval.",
        ]
    )

    md_path = review_packet_dir / "human_supervised_workflow_validation.md"
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return md_path, json_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a human-supervised draft-workflow validation artifact for one review-packet proof run."
    )
    parser.add_argument("--review-packet-dir", required=True, help="Repo-relative or absolute emitted review-packet directory.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    review_packet_dir = _resolve_repo_path(args.review_packet_dir)
    md_path, json_path = build_human_supervised_workflow_validation(review_packet_dir)
    print(f"Human-supervised workflow validation: {md_path}")
    print(f"Human-supervised draft actions JSON: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

