from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from kc_l.runtime import build_operator_repo_status, stage_catalog_rows


def main() -> int:
    status = build_operator_repo_status()
    result = {
        "ok": status["ok"],
        "status_scope": status["status_scope"],
        "truth_boundary": status["truth_boundary"],
        "full_pipeline_runnable_claimed": status["full_pipeline_runnable_claimed"],
        "stage_count": len(stage_catalog_rows()),
        "errors": status["errors"],
        "warnings": status["warnings"],
        "runtime_state": status["runtime_state"],
        "schema_profile": status["schema_profile"],
        "legacy_execution_surfaces": status["legacy_execution_surfaces"],
        "configs": {
            "local_gpu_ok": status["configs"]["local_gpu"]["ok"],
            "hpc_gpu_ok": status["configs"]["hpc_gpu"]["ok"],
            "local_gpu_warnings": status["configs"]["local_gpu"]["warnings"],
            "hpc_gpu_warnings": status["configs"]["hpc_gpu"]["warnings"],
        },
    }
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
