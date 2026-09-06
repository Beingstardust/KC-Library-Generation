#!/bin/bash
#SBATCH -J step67b_q30b
#SBATCH -p gpu80GB
#SBATCH --gres=gpu:a100:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --time=04:00:00
#SBATCH -o logs/step67b_q30b-%j.out
#SBATCH -e logs/step67b_q30b-%j.err

set -euo pipefail

REPO=/path/to/projects/kc_l_v2_clean
PYTHON_BIN=/path/to/venvs/kc_l_v2/bin/python

export PYTHONPATH=/path/to/projects/kc_l_v2_clean/src${PYTHONPATH:+:$PYTHONPATH}
export LD_LIBRARY_PATH=/path/to/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}

# Ollama must run only inside this allocation, on localhost.
export OLLAMA_HOST=127.0.0.1:11567
export OLLAMA_KEEP_ALIVE=0
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_MAX_LOADED_MODELS=1

# Keep temporary runtime files off home.
RUNROOT=/path/to/scratch/kc_l/step67b_validation_${SLURM_JOB_ID}
mkdir -p "$RUNROOT"/tmp "$RUNROOT"/logs
export TMPDIR="$RUNROOT/tmp"

# If you already keep Ollama models on scratch, uncomment and adjust this.
# export OLLAMA_MODELS=/path/to/scratch/ollama_models

SUCCESS=0
OLLAMA_PID=""

cleanup() {
  status=$?
  if [[ -n "${OLLAMA_PID}" ]] && kill -0 "${OLLAMA_PID}" 2>/dev/null; then
    kill "${OLLAMA_PID}" 2>/dev/null || true
    wait "${OLLAMA_PID}" 2>/dev/null || true
  fi

  if [[ "${SUCCESS}" == "1" ]]; then
    rm -rf "$RUNROOT"
    echo "SCRATCH_CLEANUP_OK"
  else
    echo "FAILURE_KEEPING_SCRATCH: $RUNROOT"
  fi
  exit $status
}
trap cleanup EXIT

echo "==== job context ===="
date
hostname
nvidia-smi || true
echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-unset}"
echo "RUNROOT=$RUNROOT"

cd "$REPO"

echo
echo "==== preflight ===="
command -v ollama
"$PYTHON_BIN" --version

echo
echo "==== start ollama server on allocated node ===="
ollama serve > "$RUNROOT/logs/ollama_server.log" 2>&1 &
OLLAMA_PID=$!

READY=0
for _ in $(seq 1 90); do
  if curl -sf "http://127.0.0.1:11567/api/tags" >/dev/null; then
    READY=1
    break
  fi
  sleep 2
done

if [[ "$READY" != "1" ]]; then
  echo "OLLAMA_SERVER_NOT_READY"
  echo "==== ollama log tail ===="
  tail -n 120 "$RUNROOT/logs/ollama_server.log" || true
  exit 1
fi

echo
echo "==== verify model availability ===="
if ! ollama list | awk 'NR>1 {print $1}' | grep -Fx "qwen3:30b" >/dev/null; then
  echo "MODEL_NOT_AVAILABLE:qwen3:30b"
  echo "==== ollama list ===="
  ollama list || true
  exit 1
fi

echo
echo "==== run bounded Step 6.7B validation ===="
"$PYTHON_BIN" steps/step_06_7b_seed_floor_triage_and_rescue/scripts/run_step6_7b_seed_floor_triage_and_rescue.py \
  --config steps/step_06_7b_seed_floor_triage_and_rescue/resources/step6_7b.012531.validation.yaml

echo
echo "==== inspect latest Step 6.7B outputs ===="
"$PYTHON_BIN" - <<'PY'
import json
from pathlib import Path
from collections import Counter

set_dir = Path("data/processed/kc_seed_floor_triage_and_rescue/_sets")
latest = sorted(set_dir.glob("*.json"))[-1]
manifest = json.loads(latest.read_text(encoding="utf-8"))

print("LATEST_STEP67B_SET:", latest)
print("SET_ID:", manifest.get("set_id"))

stats_path = Path(manifest["artifacts"]["triage_stats_json"])
rows_path = Path(manifest["artifacts"]["triage_rows_jsonl"])
bundles_path = Path(manifest["artifacts"]["kc_draft_bundles_rescued_jsonl"])

print("\n==== TRIAGE STATS ====")
print(stats_path.read_text(encoding="utf-8"))

status_counts = Counter()
bucket_counts = Counter()
rescue_mode_counts = Counter()

with bundles_path.open("r", encoding="utf-8") as f:
    for line in f:
        if not line.strip():
            continue
        row = json.loads(line)
        status_counts[str(row.get("authoritative_definition_status") or "")] += 1
        triage = dict(row.get("seed_floor_triage") or {})
        bucket_counts[str(triage.get("primary_bucket") or "")] += 1
        rescue_mode_counts[str(triage.get("rescue_mode") or "")] += 1

print("\nAUTHORITATIVE_STATUS_COUNTS:", dict(status_counts))
print("PRIMARY_BUCKET_COUNTS:", dict(bucket_counts))
print("RESCUE_MODE_COUNTS:", dict(rescue_mode_counts))

targets = {
    "KC_CLF_NB_007",
    "KC_CLF_NB_008",
    "KC_EVAL_IMBAL_001",
    "KC_FSEL_GEN_004",
}

print("\n==== TARGET SNAPSHOT ====")
with bundles_path.open("r", encoding="utf-8") as f:
    for line in f:
        if not line.strip():
            continue
        row = json.loads(line)
        kc_id = str(row.get("kc_id") or "")
        if kc_id not in targets:
            continue
        triage = dict(row.get("seed_floor_triage") or {})
        print("=" * 120)
        print("KC_ID:", kc_id)
        print("STATUS:", row.get("authoritative_definition_status"))
        print("CANONICAL_NAME:", row.get("canonical_name"))
        print("DEFINITION_FULL:", json.dumps(row.get("definition_full_candidate"), ensure_ascii=False, indent=2))
        print("TRIAGE:", json.dumps(triage, ensure_ascii=False, indent=2))
PY

SUCCESS=1
echo
echo "STEP67B_VALIDATION_JOB_OK"
