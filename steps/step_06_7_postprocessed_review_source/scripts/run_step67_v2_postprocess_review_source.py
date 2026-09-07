from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_SRC = REPO_ROOT / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from kc_l.runtime.stage_pointers import resolve_pointer
from kc_l.step67_postprocess import postprocess_review_source

DEFAULT_STEP67_DRAFTS_BEST_POINTER = Path(
    "data/processed/step67_v2_tiny_smoke_drafts/_sets/BEST_STEP67_V2_FULL165_KC_TOPIC_POLICY_MARKER_FIX.txt"
)
DEFAULT_STEP67_POSTPROCESS_BEST_POINTER = Path(
    "data/processed/step67_v2_postprocessed_review_source/_sets/BEST_STEP67_V2_POSTPROCESSED_REVIEW_SOURCE.txt"
)


def resolve_repo_path(path: Path | str, repo_root: Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else (repo_root / p)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Postprocess step 6.7 v2 drafts into the step67_v2_postprocessed_review_source review source."
    )
    parser.add_argument("--source-drafts-jsonl", type=Path, default=None)
    parser.add_argument("--accepted-baseline-run-id", default=None)
    parser.add_argument("--step67-drafts-best-pointer", type=Path, default=DEFAULT_STEP67_DRAFTS_BEST_POINTER)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--update-best-pointer", action="store_true")
    parser.add_argument("--step67-postprocess-best-pointer", type=Path, default=DEFAULT_STEP67_POSTPROCESS_BEST_POINTER)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.source_drafts_jsonl is not None:
        source_drafts_jsonl = resolve_repo_path(args.source_drafts_jsonl, REPO_ROOT)
        accepted_baseline_run_id = args.accepted_baseline_run_id
        if not accepted_baseline_run_id:
            print("ERROR_ACCEPTED_BASELINE_RUN_ID_REQUIRED_WITH_EXPLICIT_SOURCE_DRAFTS_JSONL")
            return 2
    else:
        pointer_path = resolve_repo_path(args.step67_drafts_best_pointer, REPO_ROOT)
        source_drafts_jsonl = resolve_pointer(pointer_path, key="DRAFTS_JSONL")
        accepted_baseline_run_id = args.accepted_baseline_run_id or resolve_pointer(
            pointer_path, key="RUN_ID", require_exists=False
        ).name

    out_dir = resolve_repo_path(args.out_dir, REPO_ROOT)

    if not source_drafts_jsonl.exists():
        print(f"ERROR_SOURCE_DRAFTS_JSONL_MISSING={source_drafts_jsonl}")
        return 2

    result = postprocess_review_source(
        source_drafts_jsonl=source_drafts_jsonl,
        output_dir=out_dir,
        run_id=args.run_id,
        accepted_baseline_run_id=accepted_baseline_run_id,
        postprocess_root=str(out_dir),
    )

    print("STEP67_V2_POSTPROCESS_REVIEW_SOURCE_COMPLETE")
    print(f"DECISION={result['decision']}")
    print(f"RUN_ID={args.run_id}")
    print(f"ACCEPTED_BASELINE_RUN_ID={accepted_baseline_run_id}")
    print(f"SOURCE_DRAFTS_JSONL={source_drafts_jsonl}")
    print(f"OUT_DIR={out_dir}")
    print(f"POSTPROCESSED_JSONL={result['postprocessed_jsonl']}")
    print(f"POSTPROCESSED_SHA256={result['postprocessed_sha256']}")
    print(f"ROW_COUNT={result['row_count']}")
    print(f"UNIT_TYPE_COUNTER={result['unit_type_counter']}")
    print(f"DRAFT_STATUS_COUNTER={result['draft_status_counter']}")
    print(f"REVIEW_ACTION_COUNTER={result['review_action_counter']}")
    print(f"PROVENANCE_QUALITY_COUNTER={result['provenance_quality_counter']}")
    print(f"EVIDENCE_REFERENCE_STATUS_COUNTER={result['evidence_reference_status_counter']}")
    print(f"REBIND_COUNT={result['rebind_count']}")
    print(f"UNRESOLVED_REFERENCE_COUNT={result['unresolved_reference_count']}")
    print(f"REBIND_GAP_EXPOSURE_COUNT={result['rebind_gap_exposure_count']}")
    print(f"TEXT_NORMALIZATION_CHANGE_COUNT={result['text_normalization_change_count']}")
    print(f"CLOSEOUT_TXT={result['closeout_txt']}")
    print(f"ISSUE_COUNT={len(result['issues'])}")

    best_pointer_updated = False
    if args.update_best_pointer and result["decision"] == "POSTPROCESSED_REVIEW_SOURCE_READY":
        best_pointer_path = resolve_repo_path(args.step67_postprocess_best_pointer, REPO_ROOT)
        best_pointer_path.parent.mkdir(parents=True, exist_ok=True)
        best_pointer_path.write_text(
            "\n".join(
                [
                    f"RUN_ID={args.run_id}",
                    f"ACCEPTED_BASELINE_RUN_ID={accepted_baseline_run_id}",
                    f"OUT_DIR={out_dir}",
                    f"POSTPROCESSED_JSONL={result['postprocessed_jsonl']}",
                    f"SUMMARY_JSON={out_dir / 'STEP67_V2_POSTPROCESS_SUMMARY.json'}",
                    f"AUDIT_CSV={result['postprocess_audit_csv']}",
                    f"UNRESOLVED_REFS_CSV={result['unresolved_refs_csv']}",
                    f"EVIDENCE_REBINDS_CSV={result['evidence_rebinds_csv']}",
                    f"CLOSEOUT_TXT={result['closeout_txt']}",
                    f"POSTPROCESSED_SHA256={result['postprocessed_sha256']}",
                    "NOTE=BEST pointer only. ACTIVE pointer not mutated.",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        best_pointer_updated = True

    print(f"BEST_POINTER_UPDATED={int(best_pointer_updated)}")
    return 0 if result["decision"] == "POSTPROCESSED_REVIEW_SOURCE_READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
