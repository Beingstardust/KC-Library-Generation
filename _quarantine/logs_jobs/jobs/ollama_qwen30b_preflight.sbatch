#!/bin/bash
#SBATCH -J ollama30b_chk
#SBATCH -p gpu80GB
#SBATCH --gres=gpu:a100:1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:10:00
#SBATCH -o logs/ollama30b_chk-%j.out
#SBATCH -e logs/ollama30b_chk-%j.err

set -euo pipefail

REPO=/beegfs1/home/aryp26yc/projects/kc_l_v2_clean
mkdir -p "$REPO/logs"

export OLLAMA_HOST=127.0.0.1:11567
export OLLAMA_KEEP_ALIVE=0
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_MODELS=/beegfs2/scratch/aryp26yc/kc_l/ollama/models

if command -v ollama >/dev/null 2>&1; then
  OLLAMA_BIN="$(readlink -f "$(command -v ollama)")"
else
  OLLAMA_BIN=/home/aryp26yc/apps/ollama_clean/bin/ollama
fi

RUNROOT=/beegfs2/scratch/aryp26yc/kc_l/ollama_preflight_${SLURM_JOB_ID}
mkdir -p "$RUNROOT"
OLLAMA_PID=""

cleanup() {
  status=$?
  if [[ -n "${OLLAMA_PID}" ]] && kill -0 "${OLLAMA_PID}" 2>/dev/null; then
    kill "${OLLAMA_PID}" 2>/dev/null || true
    wait "${OLLAMA_PID}" 2>/dev/null || true
  fi
  echo "RUNROOT=$RUNROOT"
  exit $status
}
trap cleanup EXIT

echo "==== context ===="
hostname
date
nvidia-smi || true
echo "OLLAMA_BIN=$OLLAMA_BIN"
echo "OLLAMA_MODELS=$OLLAMA_MODELS"

"$OLLAMA_BIN" serve > "$RUNROOT/ollama_server.log" 2>&1 &
OLLAMA_PID=$!

READY=0
for _ in $(seq 1 90); do
  if curl -sf "http://127.0.0.1:11567/api/tags" >/dev/null; then
    READY=1
    break
  fi
  sleep 2
done

[[ "$READY" == "1" ]]

echo "==== ollama list ===="
"$OLLAMA_BIN" list

echo "==== exact model check ===="
"$OLLAMA_BIN" list | awk 'NR>1 {print $1}' | grep -Fx "qwen3:30b"

echo "QWEN30B_VISIBLE=1"