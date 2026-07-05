#!/bin/bash
#SBATCH -J s67_g4_smoke
#SBATCH -p gpu
#SBATCH --nodelist=gpu09
#SBATCH --gres=gpu:a30:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH -o logs/%x-%j.out
#SBATCH -e logs/%x-%j.err

set -euo pipefail

REPO=/beegfs1/home/aryp26yc/projects/kc_l_v2_clean
PYTHON_BIN=/home/aryp26yc/venvs/kc_l_v2/bin/python

export PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH=/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}

export OLLAMA_BIN=/beegfs1/home/aryp26yc/apps/ollama_upgrade_clean_20260425_214752/bin/ollama
export OLLAMA_MODELS=/beegfs2/scratch/aryp26yc/kc_l/ollama/models
export OLLAMA_HOST=127.0.0.1:11567
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_KEEP_ALIVE=0

RUNROOT=/beegfs2/scratch/aryp26yc/kc_l/step67_gemma4_smoke_${SLURM_JOB_ID}
mkdir -p "$RUNROOT" "$REPO/logs"
export TMPDIR="$RUNROOT"

cd "$REPO"

echo "==== job context ===="
date -u
hostname
nvidia-smi || true
echo "PYTHON_BIN=$PYTHON_BIN"
echo "OLLAMA_BIN=$OLLAMA_BIN"
echo "OLLAMA_MODELS=$OLLAMA_MODELS"
echo "OLLAMA_HOST=$OLLAMA_HOST"

echo
echo "==== rendered config sanity ===="
grep -nE 'generation_model|resolved_model_alias|thinking_enabled|thinking_activation_mode|thinking_system_prefix|strip_thought_block_before_parse' \
  data/work/cache/generated_configs/main_quest.hpc_gpu.yaml

echo
echo "==== upgraded ollama version ===="
"$OLLAMA_BIN" --version || true

OLLAMA_LOG="$REPO/logs/ollama_step67_gemma4_smoke_${SLURM_JOB_ID}.log"
"$OLLAMA_BIN" serve > "$OLLAMA_LOG" 2>&1 &
OLLAMA_PID=$!

cleanup() {
  status=$?
  kill "$OLLAMA_PID" >/dev/null 2>&1 || true
  wait "$OLLAMA_PID" >/dev/null 2>&1 || true
  exit "$status"
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

if [ "$READY" -ne 1 ]; then
  echo "OLLAMA_NOT_READY"
  tail -n 120 "$OLLAMA_LOG" || true
  exit 1
fi

echo
echo "==== available models ===="
"$OLLAMA_BIN" list | grep -i 'gemma4\|qwen3' || true

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

echo
echo "==== step 6.7 smoke ===="
"$PYTHON_BIN" steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py \
  --config data/work/cache/generated_configs/main_quest.hpc_gpu.yaml \
  --limit-kcs 3

echo
echo "==== latest step 6.7 set(s) ===="
ls -1t data/processed/kc_drafts/_sets/*_step6_7_kc_drafts_set.json | head -n 3

echo
echo "STEP67_SMOKE_OK"
