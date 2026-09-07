from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_SRC = REPO_ROOT / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from kc_l.review_packets import emit_review_packets_from_postprocessed_source


DEFAULT_STEP67_POINTER = Path("data/processed/step67_v2_postprocessed_review_source/_sets/BEST_STEP67_V2_POSTPROCESSED_REVIEW_SOURCE.txt")
DEFAULT_STEP68_POINTER = Path("data/processed/step68_v2_review_packets_from_postprocessed_source/_sets/BEST_STEP68_V2_REVIEW_PACKETS_FROM_POSTPROCESSED_SOURCE.txt")


def read_pointer(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            out[key.strip()] = value.strip()
    return out


def resolve_repo_path(path: Path | str, repo_root: Path) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = repo_root / p
    return p


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Emit current Step6.8 review packets from the Step6.7 postprocessed review-source JSONL."
    )
    parser.add_argument("--postprocessed-jsonl", type=Path, default=None)
    parser.add_argument("--step67-best-pointer", type=Path, default=DEFAULT_STEP67_POINTER)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--update-best-pointer", action="store_true")
    parser.add_argument("--step68-best-pointer", type=Path, default=DEFAULT_STEP68_POINTER)
    parser.add_argument("--pointer-backup-dir", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.postprocessed_jsonl is None:
        pointer_path = resolve_repo_path(args.step67_best_pointer, REPO_ROOT)
        pointer = read_pointer(pointer_path)
        source_text = (
            pointer.get("POSTPROCESSED_JSONL")
            or pointer.get("REVIEW_SOURCE_JSONL")
            or pointer.get("SOURCE_JSONL")
            or ""
        )
        if not source_text:
            print(f"ERROR_STEP67_POSTPROCESSED_POINTER_HAS_NO_SOURCE={pointer_path}")
            return 2
        postprocessed_jsonl = resolve_repo_path(source_text, REPO_ROOT)
    else:
        postprocessed_jsonl = resolve_repo_path(args.postprocessed_jsonl, REPO_ROOT)

    out_dir = resolve_repo_path(args.out_dir, REPO_ROOT)
    best_pointer = resolve_repo_path(args.step68_best_pointer, REPO_ROOT)
    pointer_backup_dir = resolve_repo_path(args.pointer_backup_dir, REPO_ROOT) if args.pointer_backup_dir else None

    if not postprocessed_jsonl.exists():
        print(f"ERROR_POSTPROCESSED_JSONL_MISSING={postprocessed_jsonl}")
        return 2

    result = emit_review_packets_from_postprocessed_source(
        postprocessed_jsonl=postprocessed_jsonl,
        output_dir=out_dir,
        run_id=args.run_id,
        update_best_pointer=args.update_best_pointer,
        best_pointer=best_pointer,
        pointer_backup_dir=pointer_backup_dir,
    )

    print("STEP68_CURRENT_POSTPROCESSED_REVIEW_PACKET_RUNNER_COMPLETE")
    print(f"DECISION={result['decision']}")
    print(f"RUN_ID={args.run_id}")
    print(f"POSTPROCESSED_JSONL={postprocessed_jsonl}")
    print(f"OUT_DIR={out_dir}")
    print(f"REVIEW_PACKETS_JSONL={result['review_packets_jsonl']}")
    print(f"REVIEW_QUEUE_CSV={result['review_queue_csv']}")
    print(f"STATS_JSON={result['stats_json']}")
    print(f"MANIFEST_JSON={result['manifest_json']}")
    print(f"CLOSEOUT_TXT={result['closeout_txt']}")
    print(f"PACKET_COUNT={result['packet_count']}")
    print(f"UNIT_TYPE_COUNTER={result['unit_type_counter']}")
    print(f"DRAFT_STATUS_COUNTER={result['draft_status_counter']}")
    print(f"REVIEW_MODE_COUNTER={result['review_mode_counter']}")
    print(f"ALLOWED_ACTION_COUNTER={result['allowed_action_counter']}")
    print(f"REJECT_ACTION_PRESENT_COUNT={result['reject_action_present_count']}")
    print(f"NEEDS_EXPERT_REWRITE_ACTION_COUNT={result['needs_expert_rewrite_action_count']}")
    print(f"TOPIC_EVIDENCE_RECOVERED_COUNT={result['topic_evidence_recovered_count']}")
    print(f"REVIEWABLE_MISSING_EVIDENCE_FOR_SYNTHESIS_COUNT={result['reviewable_missing_evidence_for_synthesis_count']}")
    print(f"HARD_ISSUE_COUNT={len(result['issues'])}")
    print(f"BEST_POINTER_UPDATED={int(result['best_pointer_updated'])}")
    print("NO_MODEL_RERUN=1")
    print("NO_DRAFT_REGENERATION=1")
    print("NO_EVIDENCE_INVENTION=1")
    print("NO_EXPERT_APPROVAL_INFERRED=1")
    print("KC_SURVIVAL_PRESERVED=1")
    return 0 if result["decision"] == "PASS_STEP68_CURRENT_REVIEW_PACKET_VALIDATION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
