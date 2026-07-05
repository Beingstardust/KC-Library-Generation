#!/bin/bash
#SBATCH -J probe30bA40
#SBATCH -p gpu46GB
#SBATCH --gres=gpu:a40:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=00:20:00
#SBATCH -o /beegfs1/home/aryp26yc/projects/kc_l_v2_clean/logs/probe30bA40-%j.out
#SBATCH -e /beegfs1/home/aryp26yc/projects/kc_l_v2_clean/logs/probe30bA40-%j.err

set -euo pipefail

REPO=/beegfs1/home/aryp26yc/projects/kc_l_v2_clean
cd "$REPO"

export LD_LIBRARY_PATH=/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}

export OLLAMA_HOME=/home/aryp26yc/apps/ollama_clean
export OLLAMA_BIN=/home/aryp26yc/apps/ollama_clean/bin/ollama
export OLLAMA_MODELS=/beegfs2/scratch/aryp26yc/kc_l/ollama/models
export OLLAMA_HOST=127.0.0.1:11567
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_KEEP_ALIVE=0

JOB_SCRATCH=/beegfs2/scratch/aryp26yc/kc_l/probe30bA40_${SLURM_JOB_ID}
mkdir -p "$JOB_SCRATCH"
export TMPDIR="$JOB_SCRATCH"

echo "===== node ====="
hostname
date
nvidia-smi

"$OLLAMA_BIN" serve > "$REPO/logs/ollama_probe30bA40_${SLURM_JOB_ID}.log" 2>&1 &
OLLAMA_PID=$!

cleanup() {
  status=$?
  kill "${OLLAMA_PID}" >/dev/null 2>&1 || true
  wait "${OLLAMA_PID}" >/dev/null 2>&1 || true
  exit "${status}"
}
trap cleanup EXIT

READY=0
for i in $(seq 1 90); do
  if curl -fsS "http://${OLLAMA_HOST}/api/tags" >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 2
done

if [ "${READY}" -ne 1 ]; then
  echo "OLLAMA_NOT_READY"
  exit 10
fi

echo "===== ollama list ====="
"$OLLAMA_BIN" list

echo "===== qwen3:30b show ====="
"$OLLAMA_BIN" show qwen3:30b >/dev/null

echo "===== tiny 30b generate with num_ctx 8192 ====="
curl -fsS "http://${OLLAMA_HOST}/api/generate" \
  -d '{
    "model":"qwen3:30b",
    "prompt":"Reply with exactly OK.",
    "stream":false,
    "options":{"temperature":0,"num_predict":2,"num_ctx":8192}
  }'

echo
echo "PROBE_OK"
