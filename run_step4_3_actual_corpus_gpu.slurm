#!/bin/bash
#SBATCH -J kc_step4_3_index_gpu
#SBATCH -p gpu46GB
#SBATCH --gres=gpu:a40:1
#SBATCH --cpus-per-task=12
#SBATCH --mem=96G
#SBATCH --time=24:00:00
#SBATCH -o /beegfs2/scratch/aryp26yc/kc_l/slurm_logs/%x_%j.out
#SBATCH -e /beegfs2/scratch/aryp26yc/kc_l/slurm_logs/%x_%j.err

set -euo pipefail

unset PROMPT_COMMAND || true
source ~/kc_l_v2_env.sh

REPO=/beegfs1/home/aryp26yc/projects/kc_l_v2_clean
cd "$REPO"

export PYTHONPATH="$REPO/src"
export LD_LIBRARY_PATH="/beegfs1/software/rh8/usr/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

export OLLAMA_HOST=127.0.0.1:11434
export OLLAMA_MODELS=/beegfs2/scratch/aryp26yc/kc_l/ollama/models
export OLLAMA_KEEP_ALIVE=2h
export OLLAMA_NUM_PARALLEL=1
export CUDA_VISIBLE_DEVICES=0

CONFIG="$REPO/steps/step_04_structure_retrieval_index/resources/step4.index.sofja.actual_corpus.yaml"

echo "[step4.3] host=$(hostname)"
echo "[step4.3] config=$CONFIG"
echo "[step4.3] OLLAMA_HOST=$OLLAMA_HOST"
echo "[step4.3] OLLAMA_MODELS=$OLLAMA_MODELS"
echo "[step4.3] OLLAMA_MODEL=$(grep -E '^  model:' "$CONFIG" | head -n 1 | awk '{print $2}')"

nvidia-smi || true
command -v ollama || true
python --version || true

echo "[step4.3] starting local ollama server"
nohup /home/aryp26yc/apps/ollama_clean/bin/ollama serve \
  > /beegfs2/scratch/aryp26yc/kc_l/slurm_logs/ollama_step4_3_${SLURM_JOB_ID}.out \
  2> /beegfs2/scratch/aryp26yc/kc_l/slurm_logs/ollama_step4_3_${SLURM_JOB_ID}.err &

echo "[step4.3] waiting for ollama API"
for i in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

echo "[step4.3] /api/version OK"
curl -fsS http://127.0.0.1:11434/api/version || true
echo

echo "[step4.3] checking embedding model availability"
ollama list || true

echo "[step4.3] launching index build"
python steps/step_04_structure_retrieval_index/scripts/run_step4_3.py \
  --config "$CONFIG"
