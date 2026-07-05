from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from kc_l.utils.json_io import read_json, write_json


BOUNDARY_NOTE = (
    "This is the first real human reviewer session for the current proof run. "
    "Success is reviewable draft workflow from the packet surface, not machine-generated near-final KCs."
)
SUCCESS_THRESHOLD = (
    "The pilot crosses the important threshold when a reviewer can reliably edit or reject from the packet "
    "surface without reopening raw internals."
)
NON_GOAL = "Machine autonomy or packet-only approval is not the success criterion for this session."


def _resolve_repo_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (REPO_ROOT / path).resolve()


def _relative_repo_path(path: Path) -> str:
    return str(path.resolve().relative_to(REPO_ROOT))


def _group_label(action: str, sufficiency: str) -> str:
    if action == "reject":
        return "reject_control"
    if sufficiency == "sufficient":
        return "edit_from_packet_sufficient"
    return "edit_from_packet_borderline"


def _group_rank(action: str, sufficiency: str, repaired: bool) -> tuple[int, int]:
    if action == "reject":
        return (0, 0)
    if sufficiency == "sufficient":
        return (1, 1 if repaired else 0)
    return (2, 1 if repaired else 0)


def _build_session_order(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        actions,
        key=lambda item: (
            _group_rank(
                str(item.get("draft_human_action") or ""),
                str(item.get("packet_sufficiency") or ""),
                bool(item.get("content_repair_applied")),
            ),
            str(item.get("kc_candidate_id") or ""),
        ),
    )
    session_rows: list[dict[str, Any]] = []
    for index, item in enumerate(ordered, start=1):
        action = str(item.get("draft_human_action") or "")
        sufficiency = str(item.get("packet_sufficiency") or "")
        session_rows.append(
            {
                "session_order": index,
                "kc_candidate_id": item["kc_candidate_id"],
                "title_draft": item["title_draft"],
                "session_group": _group_label(action, sufficiency),
                "machine_bucket": item["machine_bucket"],
                "machine_recommendation": item["machine_recommendation"],
                "expected_reviewer_action": action,
                "packet_sufficiency": sufficiency,
                "content_repair_applied": bool(item.get("content_repair_applied")),
                "content_source_mode": item["content_source_mode"],
                "requires_raw_internals": bool(item.get("requires_raw_internals")),
                "workflow_note": item["workflow_note"],
            }
        )
    return session_rows


def build_real_reviewer_session(review_packet_dir: Path) -> tuple[Path, Path]:
    review_packet_dir = review_packet_dir.resolve()
    workflow_path = review_packet_dir / "human_supervised_draft_actions.json"
    inspection_path = review_packet_dir / "manual_inspection_bundle.md"
    if not workflow_path.exists() or not inspection_path.exists():
        raise FileNotFoundError(f"Required workflow-validation artifacts missing under {review_packet_dir}")

    workflow = read_json(workflow_path)
    actions = list(workflow.get("draft_actions") or [])
    session_order = _build_session_order(actions)
    skipped_case = dict(workflow.get("skipped_case") or {})
    action_counts = dict(workflow.get("draft_action_counts") or {})
    sufficiency_counts = dict(workflow.get("packet_sufficiency_counts") or {})
    paths = dict(workflow.get("paths_exercised") or {})

    payload = {
        "review_packet_dir": str(review_packet_dir),
        "source_processed_dir": str(workflow["source_processed_dir"]),
        "session_mode": "real_human_reviewer_session",
        "boundary_note": BOUNDARY_NOTE,
        "success_threshold": SUCCESS_THRESHOLD,
        "non_goal": NON_GOAL,
        "approve_path_required": False,
        "draft_action_space": ["approve", "edit", "reject"],
        "draft_action_counts": action_counts,
        "packet_sufficiency_counts": sufficiency_counts,
        "paths_exercised_so_far": paths,
        "artifact_inputs": {
            "manual_inspection_bundle": _relative_repo_path(inspection_path),
            "human_supervised_workflow_validation": _relative_repo_path(review_packet_dir / "human_supervised_workflow_validation.md"),
            "human_supervised_draft_actions": _relative_repo_path(workflow_path),
        },
        "session_instructions": [
            "Use the manual inspection bundle as the packet surface for actual reviewer decisions.",
            "Record approve, edit, or reject directly on the packet surface without reopening raw internals unless the packet fails reviewability.",
            "If raw internals are reopened for a packet, record that as a packet-surface workflow miss rather than a reviewer success.",
            "Do not treat machine recommendations as final approval.",
            "Do not count the absence of approve-ready packets as pilot failure on this run.",
        ],
        "session_packet_order": session_order,
        "skipped_case": skipped_case,
    }

    json_path = review_packet_dir / "real_reviewer_session_manifest.json"
    write_json(json_path, payload)

    lines = [
        "# Real Reviewer Session",
        "",
        f"- Proof-run packet directory: `{_relative_repo_path(review_packet_dir)}`",
        f"- Source processed directory: `{_relative_repo_path(Path(workflow['source_processed_dir']))}`",
        f"- Session mode: `{payload['session_mode']}`",
        f"- Boundary: {BOUNDARY_NOTE}",
        f"- Success threshold: {SUCCESS_THRESHOLD}",
        f"- Non-goal: {NON_GOAL}",
        f"- Approve path required on this run: `{payload['approve_path_required']}`",
        f"- Draft action counts: `{action_counts}`",
        f"- Packet sufficiency counts: `{sufficiency_counts}`",
        "",
        "## Session Inputs",
        "",
        f"- Manual packet surface: `{payload['artifact_inputs']['manual_inspection_bundle']}`",
        f"- Workflow validation summary: `{payload['artifact_inputs']['human_supervised_workflow_validation']}`",
        f"- Machine-to-draft action map: `{payload['artifact_inputs']['human_supervised_draft_actions']}`",
        "",
        "## Session Rules",
        "",
    ]
    for instruction in payload["session_instructions"]:
        lines.append(f"- {instruction}")

    lines.extend(["", "## Session Order", ""])
    current_group = ""
    group_titles = {
        "reject_control": "Reject Control",
        "edit_from_packet_sufficient": "Edit Cases That Already Look Packet-Sufficient",
        "edit_from_packet_borderline": "Borderline Edit Cases That Still Stress Packet Sufficiency",
    }
    for item in session_order:
        group = item["session_group"]
        if group != current_group:
            current_group = group
            lines.extend([f"### {group_titles[group]}", ""])
        lines.extend(
            [
                f"- `{item['session_order']:02d}` `{item['kc_candidate_id']}` `{item['title_draft']}` -> expected reviewer action `{item['expected_reviewer_action']}`",
                f"  Packet sufficiency: `{item['packet_sufficiency']}`; machine label: `{item['machine_bucket']}` / `{item['machine_recommendation']}`; content repair applied: `{item['content_repair_applied']}`",
                f"  Reviewer note: {item['workflow_note']}",
            ]
        )

    if skipped_case:
        lines.extend(
            [
                "",
                "## Skipped Case",
                "",
                f"- `{skipped_case.get('kc_candidate_id', '')}` stayed out of the session packet queue.",
                f"- Assessment: `{skipped_case.get('skip_assessment', '')}`",
                f"- Why it matters: {skipped_case.get('verdict_rationale', '')}",
            ]
        )

    lines.extend(
        [
            "",
            "## Bottom Line",
            "",
            "- This session is successful if the reviewer can reliably edit or reject from the packet surface without reopening raw internals.",
            "- This session is not trying to prove that the machine is already producing near-final KCs.",
        ]
    )

    md_path = review_packet_dir / "real_reviewer_session.md"
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return md_path, json_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the first real human reviewer-session bundle for one proof run.")
    parser.add_argument("--review-packet-dir", required=True, help="Repo-relative or absolute emitted review-packet directory.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    review_packet_dir = _resolve_repo_path(args.review_packet_dir)
    md_path, json_path = build_real_reviewer_session(review_packet_dir)
    print(f"Real reviewer session markdown: {md_path}")
    print(f"Real reviewer session manifest JSON: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
