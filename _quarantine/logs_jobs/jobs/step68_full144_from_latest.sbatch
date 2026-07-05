#!/bin/bash
#SBATCH --job-name=step68_full144
#SBATCH --partition=medium
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --output=/beegfs1/home/aryp26yc/projects/kc_l_v2_clean/logs/step68_full144-%j.out
#SBATCH --error=/beegfs1/home/aryp26yc/projects/kc_l_v2_clean/logs/step68_full144-%j.err

set -euo pipefail

cd /beegfs1/home/aryp26yc/projects/kc_l_v2_clean

export PYTHON_BIN=/home/aryp26yc/venvs/kc_l_v2/bin/python
export PYTHONPATH=/beegfs1/home/aryp26yc/projects/kc_l_v2_clean/src${PYTHONPATH:+:$PYTHONPATH}
export LD_LIBRARY_PATH=/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}

echo "==== refresh current artifact aliases ===="
"$PYTHON_BIN" scripts/maintenance/refresh_current_step_artifacts.py

echo
echo "==== run Step 6.8 full 144 ===="
"$PYTHON_BIN" steps/step_06_8_kc_review_packet_emission/scripts/run_step6_8_kc_review_packet_emission.py \
  --config steps/step_06_8_kc_review_packet_emission/resources/step6_8.full128.yaml

echo
echo "==== latest Step 6.8 summary ===="
"$PYTHON_BIN" - <<'PY'
import json
from pathlib import Path

p68 = sorted(Path("data/processed/kc_review_packets_restarted/_sets").glob("*step6_8_kc_review_packets_restarted_set.json"))[-1]
o68 = json.loads(p68.read_text(encoding="utf-8"))
summary = json.loads(Path(o68["artifacts"]["review_packet_summary_json"]).read_text(encoding="utf-8"))

print("STEP68_SET:", o68["set_id"])
print(json.dumps({
    "packet_count": summary.get("packet_count"),
    "excluded_candidate_count": summary.get("excluded_candidate_count"),
    "quarantine_count": summary.get("quarantine_count"),
    "authoritative_definition_status_counts": summary.get("authoritative_definition_status_counts"),
    "trust_state_counts": summary.get("trust_state_counts"),
    "review_readiness_counts": summary.get("review_readiness_counts"),
    "recommendation_counts": summary.get("recommendation_counts"),
    "priority_counts": summary.get("priority_counts"),
    "fallback_definition_count": summary.get("fallback_definition_count"),
    "normalized_grounded_definition_count": summary.get("normalized_grounded_definition_count"),
    "dropped_invalid_page_index_span_count": summary.get("dropped_invalid_page_index_span_count"),
}, indent=2))
PY
