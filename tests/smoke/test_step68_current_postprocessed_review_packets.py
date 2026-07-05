from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    repo = args.repo
    out_dir = args.out_dir
    runner = repo / "steps/step_06_8_review_packet_emission/scripts/run_step68_v2_review_packet_emission_from_postprocessed.py"

    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo / "src") + os.pathsep + env.get("PYTHONPATH", "")

    cmd = [
        sys.executable,
        str(runner),
        "--out-dir",
        str(out_dir),
        "--run-id",
        args.run_id,
    ]

    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)

    stats_path = out_dir / "STEP68_V2_REVIEW_PACKET_STATS.json"
    issues = []
    if proc.returncode != 0:
        issues.append(f"runner_returncode_{proc.returncode}")

    if not stats_path.exists():
        issues.append(f"missing_stats:{stats_path}")
        stats = {}
    else:
        stats = json.loads(stats_path.read_text(encoding="utf-8"))

    expected = {
        "packet_count": 165,
        "unit_type_counter.kc": 144,
        "unit_type_counter.topic": 21,
        "review_mode_counter.segmentable_gap_review": 19,
        "reject_action_present_count": 0,
        "reviewable_missing_evidence_for_synthesis_count": 0,
        "expert_approval_suspect_count": 0,
    }

    actual = {
        "packet_count": stats.get("packet_count"),
        "unit_type_counter.kc": (stats.get("unit_type_counter") or {}).get("kc"),
        "unit_type_counter.topic": (stats.get("unit_type_counter") or {}).get("topic"),
        "review_mode_counter.segmentable_gap_review": (stats.get("review_mode_counter") or {}).get("segmentable_gap_review"),
        "reject_action_present_count": stats.get("reject_action_present_count"),
        "reviewable_missing_evidence_for_synthesis_count": stats.get("reviewable_missing_evidence_for_synthesis_count"),
        "expert_approval_suspect_count": stats.get("expert_approval_suspect_count"),
    }

    for key, exp in expected.items():
        if actual.get(key) != exp:
            issues.append(f"{key}:expected_{exp}:got_{actual.get(key)}")

    report = {
        "schema_version": "step68_current_postprocessed_smoke_v1",
        "repo": str(repo),
        "out_dir": str(out_dir),
        "command": cmd,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "expected": expected,
        "actual": actual,
        "stats": stats,
        "issues": issues,
        "decision": "PASS_STEP68_CURRENT_POSTPROCESSED_SMOKE" if not issues else "FAIL_STEP68_CURRENT_POSTPROCESSED_SMOKE",
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "STEP68_CURRENT_POSTPROCESSED_SMOKE_REPORT.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    print("STEP68_CURRENT_POSTPROCESSED_SMOKE_COMPLETE")
    print(f"DECISION={report['decision']}")
    print(f"REPORT={report_path}")
    print(f"ISSUE_COUNT={len(issues)}")
    print(f"RUNNER_RC={proc.returncode}")
    print(f"PACKET_COUNT={actual.get('packet_count')}")
    print(f"KC_COUNT={actual.get('unit_type_counter.kc')}")
    print(f"TOPIC_COUNT={actual.get('unit_type_counter.topic')}")
    print(f"SEGMENTABLE_GAP_REVIEW={actual.get('review_mode_counter.segmentable_gap_review')}")
    print(f"REJECT_ACTION_PRESENT_COUNT={actual.get('reject_action_present_count')}")
    print(f"REVIEWABLE_MISSING_EVIDENCE_FOR_SYNTHESIS_COUNT={actual.get('reviewable_missing_evidence_for_synthesis_count')}")
    print("SOFJA_MUTATED=0")

    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
