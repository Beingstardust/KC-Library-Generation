#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_SRC = REPO_ROOT / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from kc_l.topic_5p5x.scored_trace_rehydration import rehydrate_topic5x_scored_trace_fields


def resolve_repo_path(path: Path | str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else (REPO_ROOT / p)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rehydrate topic 5x scored-candidate trace fields dropped by the shared KC-shaped scorer."
    )
    parser.add_argument("--source-scored-jsonl", type=Path, required=True)
    parser.add_argument("--typed-candidate-bank-jsonl", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-run-id", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_scored_jsonl = resolve_repo_path(args.source_scored_jsonl)
    typed_candidate_bank_jsonl = resolve_repo_path(args.typed_candidate_bank_jsonl)
    out_dir = resolve_repo_path(args.out_dir)

    if not source_scored_jsonl.exists():
        print(f"ERROR_SOURCE_SCORED_JSONL_MISSING={source_scored_jsonl}")
        return 2
    if not typed_candidate_bank_jsonl.exists():
        print(f"ERROR_TYPED_CANDIDATE_BANK_JSONL_MISSING={typed_candidate_bank_jsonl}")
        return 2

    result = rehydrate_topic5x_scored_trace_fields(
        source_scored_jsonl=source_scored_jsonl,
        typed_candidate_bank_jsonl=typed_candidate_bank_jsonl,
        output_dir=out_dir,
        run_id=args.run_id,
        source_run_id=args.source_run_id,
    )

    print("TOPIC5X_SCORED_TRACE_REHYDRATION_COMPLETE")
    print(f"RUN_ID={args.run_id}")
    print(f"SOURCE_SCORED_JSONL={source_scored_jsonl}")
    print(f"TYPED_CANDIDATE_BANK_JSONL={typed_candidate_bank_jsonl}")
    print(f"OUT_DIR={out_dir}")
    print(f"TOPIC_SCORED_CANDIDATES_JSONL={result['topic_scored_candidates_jsonl']}")
    print(f"TOPIC_SCORED_CANDIDATES_SHA256={result['hashes']['topic_scored_candidates_jsonl_sha256']}")
    print(f"REHYDRATED_ROWS={result['rehydrated_rows']}")
    print(f"BRIDGE_LOADER_KNOWLEDGE_UNIT_TYPE_COUNTER={result['bridge_loader_knowledge_unit_type_counter']}")
    print(f"TOPIC5P_PROFILE_STATUS_COUNTER={result['topic5p_profile_status_counter']}")
    print(f"TOPIC5P_WEAK_PROFILE_CARRY_FORWARD_COUNTER={result['topic5p_weak_profile_carry_forward_counter']}")
    print(f"TRACE_COUNTER={result['trace_counter']}")
    print(f"CONTENT_RISK_COUNTER={result['content_risk_counter']}")
    print(f"SOFT_RISK_COUNTER={result['soft_risk_counter']}")
    print(f"CONTENT_RISK_TABLE_HITS={result['observed_content_risk_candidate_id_table_hit_count']}")
    print(f"CONTENT_RISK_TABLE_NONHITS={result['observed_content_risk_candidate_id_table_nonhit_count']}")
    print(f"SOFT_RISK_TABLE_HITS={result['observed_soft_risk_candidate_id_table_hit_count']}")
    print(f"SOFT_RISK_TABLE_NONHITS={result['observed_soft_risk_candidate_id_table_nonhit_count']}")
    print(f"UNOBSERVED_PROFILE_STATUS_COUNTER={result['unobserved_profile_status_counter']}")
    print(f"UNOBSERVED_BRIDGE_LOADER_KNOWLEDGE_UNIT_TYPE_COUNTER={result['unobserved_bridge_loader_knowledge_unit_type_counter']}")
    print(f"UNOBSERVED_KNOWLEDGE_UNIT_TYPE_COUNTER={result['unobserved_knowledge_unit_type_counter']}")
    print(f"STATS_JSON={result['stats_json']}")
    print(f"MANIFEST_JSON={result['manifest_json']}")
    print(f"AUDIT_JSON={result['audit_json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
