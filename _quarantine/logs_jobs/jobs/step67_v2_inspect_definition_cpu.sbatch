#!/bin/bash
#SBATCH --job-name=s67v2_definspect
#SBATCH --partition=short
#SBATCH --output=logs/s67v2_definspect_%j.out
#SBATCH --error=logs/s67v2_definspect_%j.err
#SBATCH --cpus-per-task=1
#SBATCH --mem=1G
#SBATCH --time=00:05:00

set -euo pipefail

cd /beegfs1/home/aryp26yc/projects/kc_l_v2_clean || exit 1

export PY=/home/aryp26yc/venvs/kc_l_v2/bin/python
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

VALID_ROOT="$(ls -1td data/work/cache/diagnostics/step67_generic_policy_v2_sofja_validation_* | head -n 1)"
LANES="$VALID_ROOT/replay_lane_packets.jsonl"

echo "VALID_ROOT=$VALID_ROOT"
echo "LANES=$LANES"
echo "HOST=$(hostname)"
echo

if [ ! -f "$LANES" ]; then
  echo "Missing lane packet file at: $LANES"
  exit 1
fi

"$PY" - "$LANES" <<'PY'
import json
import sys
from pathlib import Path

lanes = Path(sys.argv[1])

if not lanes.exists():
    raise SystemExit(f"Missing lane packet file: {lanes}")

target_kc = "KC_EVAL_BASIC_001"
found = False

with lanes.open("r", encoding="utf-8") as f:
    for line in f:
        if not line.strip():
            continue

        pkt = json.loads(line)

        if pkt.get("kc_id") != target_kc:
            continue

        found = True

        print("kc_id =", pkt.get("kc_id"))
        print("canonical_name =", pkt.get("canonical_name"))
        print("definition_lane_count =", len(pkt.get("definition_lane") or []))
        print("scope_lane_count =", len(pkt.get("scope_lane") or []))
        print("context_lane_count =", len(pkt.get("context_lane") or []))
        print("quarantine_lane_count =", len(pkt.get("quarantine_lane") or []))
        print()

        for i, item in enumerate(pkt.get("definition_lane") or [], start=1):
            print(f"--- definition item {i} ---")
            print("evidence_id =", item.get("evidence_id"))
            print("reason =", item.get("reason"))
            print("target_binding_strength =", item.get("target_binding_strength"))
            print("decisive_surface =", item.get("decisive_surface"))
            print("quote_text =", item.get("quote_text"))
            print("context_text =", item.get("context_text"))
            print("flags =", item.get("flags"))
            print()

if not found:
    raise SystemExit(f"{target_kc} not found in {lanes}")
PY
