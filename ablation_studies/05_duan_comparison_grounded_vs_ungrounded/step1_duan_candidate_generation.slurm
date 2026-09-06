#!/bin/bash
#SBATCH --job-name=duan_step1_gen
#SBATCH --partition=gpu80GB
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=03:00:00
#SBATCH --output=/path/to/projects/kc_l_v2_clean/ablation_studies/05_duan_comparison_grounded_vs_ungrounded/logs/step1_gen_%A_%a.out
#SBATCH --error=/path/to/projects/kc_l_v2_clean/ablation_studies/05_duan_comparison_grounded_vs_ungrounded/logs/step1_gen_%A_%a.err

# Array job: one task per shard. Submit with, e.g.:
#   sbatch --array=0-19 --export=SHARD_COUNT=20 step1_duan_candidate_generation.slurm
# SHARD_COUNT must match the --array range (array indices 0..SHARD_COUNT-1).
# For a smoke test: sbatch --array=0-0 --export=SHARD_COUNT=1,LIMIT=1 step1_duan_candidate_generation.slurm

set +e

REPO='/path/to/projects/kc_l_v2_clean'
STAGE_DIR="$REPO/ablation_studies/05_duan_comparison_grounded_vs_ungrounded"
LOG_DIR="$STAGE_DIR/logs"
mkdir -p "$LOG_DIR" "$STAGE_DIR/output/step1_raw_candidates"

export PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="/path/to/software/python/python-3.11.3/lib:/path/to/software/rh8/usr/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

KC_L_V2_ENV="$HOME/kc_l_v2_env.sh"
if [ ! -f "$KC_L_V2_ENV" ]; then
  echo "FATAL: kc_l_v2_env.sh not found at $KC_L_V2_ENV"
  exit 1
fi
source "$KC_L_V2_ENV"
if [ -z "${HF_HOME:-}" ]; then
  echo "FATAL: kc_l_v2_env.sh did not set HF_HOME - environment sourcing may have failed"
  exit 1
fi

cd "$REPO"

RUNTIME_ENV='/path/to/projects/kc_l_v2_clean/config/runtime/hpc_ollama_gemma4_31b.env'
if [ -f "$RUNTIME_ENV" ]; then
  set -a
  . "$RUNTIME_ENV"
  set +a
fi

MODEL='gemma4:31b'
SHARD_INDEX="${SLURM_ARRAY_TASK_ID:-0}"
SHARD_COUNT="${SHARD_COUNT:-1}"
LIMIT_ARG=""
if [ -n "${LIMIT:-}" ]; then
  LIMIT_ARG="--limit ${LIMIT}"
fi

PORT=$((25000 + ((${SLURM_JOB_ID:-0} + SHARD_INDEX) % 10000)))
export OLLAMA_HOST="127.0.0.1:$PORT"

echo "===== duan_step1_gen shard=$SHARD_INDEX/$SHARD_COUNT ====="
date -u
hostname
echo "SLURM_JOB_ID=${SLURM_JOB_ID:-}"
echo "OLLAMA_HOST=$OLLAMA_HOST"

"$OLLAMA_BIN" serve > "$LOG_DIR/ollama_serve_${SHARD_INDEX}.log" 2>&1 &
OLLAMA_PID=$!

python3 - <<'PYWAIT'
from __future__ import annotations
import os
import time
import urllib.request

url = "http://" + os.environ["OLLAMA_HOST"] + "/api/tags"
ready = False
last_error = ""
for _ in range(90):
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            print("OLLAMA_READY=1")
            print(r.read().decode("utf-8", errors="replace")[:800])
            ready = True
            break
    except Exception as exc:
        last_error = type(exc).__name__ + ": " + str(exc)
        time.sleep(2)

if not ready:
    print("OLLAMA_READY=0")
    print("LAST_ERROR=" + last_error)
    raise RuntimeError("Ollama did not become ready")
PYWAIT

READY_RC=$?
echo "READY_RC=$READY_RC"
if [ "$READY_RC" -ne 0 ]; then
  echo "FINAL_RC=21"
  exit 21
fi

"$OLLAMA_BIN" list > "$LOG_DIR/ollama_list_${SHARD_INDEX}.txt" 2>&1
grep -q "$MODEL" "$LOG_DIR/ollama_list_${SHARD_INDEX}.txt"
MODEL_VISIBLE_RC=$?
echo "MODEL_VISIBLE_RC=$MODEL_VISIBLE_RC"
if [ "$MODEL_VISIBLE_RC" -ne 0 ]; then
  echo "FINAL_RC=22"
  exit 22
fi

python3 "$STAGE_DIR/step1_duan_candidate_generation.py" \
  --repo-src "$REPO/src" \
  --source-units "$STAGE_DIR/output/source_units.jsonl" \
  --prompt-md "$STAGE_DIR/prompts/step1_generation_prompt.md" \
  --out "$STAGE_DIR/output/step1_raw_candidates/shard_${SHARD_INDEX}.jsonl" \
  --base-url "http://$OLLAMA_HOST" \
  --model "$MODEL" \
  --num-ctx 65536 \
  --timeout-s 180 \
  --shard-index "$SHARD_INDEX" \
  --shard-count "$SHARD_COUNT" \
  $LIMIT_ARG
RUNNER_RC=$?
echo "RUNNER_RC=$RUNNER_RC"
exit "$RUNNER_RC"
