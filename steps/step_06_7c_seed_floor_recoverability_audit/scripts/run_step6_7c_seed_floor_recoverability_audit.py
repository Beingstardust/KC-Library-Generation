from __future__ import annotations

import argparse
import json
from pathlib import Path

from kc_l.kc_drafting.step67c_recoverability import emit_step67c_recoverability_audit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    result = emit_step67c_recoverability_audit(config_path=Path(args.config))
    print(
        json.dumps(
            {
                "run_id": result.run_id,
                "processed_dir": result.processed_dir.as_posix(),
                "audit_dir": result.run_dir.as_posix(),
                "recoverability_rows_jsonl": result.recoverability_rows_path.as_posix(),
                "recoverability_packets_jsonl": result.recoverability_packets_path.as_posix(),
                "recoverability_failures_jsonl": result.recoverability_failures_path.as_posix(),
                "recoverability_stats_json": result.recoverability_stats_path.as_posix(),
                "set_manifest": result.set_manifest_path.as_posix(),
                "recoverability_class_counts": result.stats.get("recoverability_class_counts", {}),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
