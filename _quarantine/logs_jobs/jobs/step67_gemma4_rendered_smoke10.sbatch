#!/bin/bash
#SBATCH -J s67_g4_sm10
#SBATCH -p gpu
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=02:00:00
#SBATCH -o logs/s67_g4_smoke10-%j.out
#SBATCH -e logs/s67_g4_smoke10-%j.err

set -euo pipefail

cd /beegfs1/home/aryp26yc/projects/kc_l_v2_clean || exit 1

export PYTHON_BIN=/home/aryp26yc/venvs/kc_l_v2/bin/python
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH=/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}

export OLLAMA_BIN=/beegfs1/home/aryp26yc/apps/ollama_upgrade_clean_20260425_214752/bin/ollama
export OLLAMA_MODELS=/beegfs2/scratch/aryp26yc/kc_l/ollama/models
export OLLAMA_HOST=127.0.0.1:11567
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_KEEP_ALIVE=0

mkdir -p logs
RUNSTAMP=$(date +%Y%m%d_%H%M%S)
OLLAMA_LOG="logs/ollama_step67_gemma4_smoke10_${SLURM_JOB_ID}.log"

echo "==== job context ===="
date -u
hostname
nvidia-smi || true
echo "PYTHON_BIN=$PYTHON_BIN"
echo "OLLAMA_BIN=$OLLAMA_BIN"
echo "OLLAMA_MODELS=$OLLAMA_MODELS"
echo "OLLAMA_HOST=$OLLAMA_HOST"
echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-UNSET}"

"$OLLAMA_BIN" serve > "$OLLAMA_LOG" 2>&1 &
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
  exit 1
fi

echo
echo "==== available models ===="
"$OLLAMA_BIN" list || true

echo
echo "==== direct Gemma smoke ===="
curl -fsS "http://${OLLAMA_HOST}/api/generate" \
  -d '{
    "model":"gemma4:31b",
    "prompt":"Reply with exactly OK.",
    "stream":false,
    "options":{"temperature":0,"num_predict":2,"num_ctx":2048}
  }'

echo
echo "==== step 6.7 smoke ===="
"$PYTHON_BIN" steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py \
  --config data/work/cache/generated_configs/main_quest.hpc_gpu.gemma_smoke10.yaml
