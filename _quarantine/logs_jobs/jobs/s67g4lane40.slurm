#!/bin/bash
#SBATCH --job-name=s67g4l40
#SBATCH --partition=gpu46GB
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=02:00:00
#SBATCH --output=logs/s67g4lane40-%j.out
#SBATCH --error=logs/s67g4lane40-%j.err

set -euo pipefail

cd /beegfs1/home/aryp26yc/projects/kc_l_v2_clean

export PY=/home/aryp26yc/venvs/kc_l_v2/bin/python
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

export OLLAMA_BIN=/beegfs1/home/aryp26yc/apps/ollama_upgrade_clean_20260425_214752/bin/ollama
export OLLAMA_MODELS=/beegfs2/scratch/aryp26yc/kc_l/ollama/models
export OLLAMA_FLASH_ATTENTION=true
export CUDA_VISIBLE_DEVICES=0
export OLLAMA_NUM_PARALLEL=1

PORT=$((30000 + SLURM_JOB_ID % 20000))
export OLLAMA_HOST="http://127.0.0.1:${PORT}"

echo "===== host ====="
hostname

echo
echo "===== env ====="
echo "OLLAMA_HOST=$OLLAMA_HOST"
echo "OLLAMA_MODELS=$OLLAMA_MODELS"
echo "CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES"

echo
echo "===== start ollama ====="
"$OLLAMA_BIN" serve > "logs/ollama-s67g4lane40-${SLURM_JOB_ID}.log" 2>&1 &
OLLAMA_PID=$!

cleanup() {
  kill "$OLLAMA_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo
echo "===== wait for ollama ====="
for i in $(seq 1 90); do
  if "$OLLAMA_BIN" list >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

"$OLLAMA_BIN" list

LANES="$(ls -1td data/processed/step67_sidecar_lane_packets_v4_40/2026-* | head -n 1)/lane_packets.jsonl"

echo
echo "===== lanes ====="
echo "$LANES"
test -f "$LANES"

echo
echo "===== run lane-aware Gemma4 onepass, think=false ====="
"$PY" scripts/experimental/step67b_lane_aware_gemma4_onepass.py \
  --lanes "$LANES" \
  --model gemma4:31b \
  --base-url "$OLLAMA_HOST" \
  --think false \
  --num-ctx 8192 \
  --num-predict 700 \
  --temperature 0.0

DRAFTS="$(ls -1td data/processed/step67_sidecar_lane_drafts/2026-* | head -n 1)/onepass_drafts.jsonl"

echo
echo "===== drafts ====="
echo "$DRAFTS"
test -f "$DRAFTS"

echo
echo "===== lane-aware validation ====="
VALIDATION_EXIT=0
"$PY" scripts/experimental/step67c_validate_lane_aware_drafts.py \
  --lanes "$LANES" \
  --drafts "$DRAFTS" || VALIDATION_EXIT=$?

echo "VALIDATION_EXIT=$VALIDATION_EXIT"

LATEST_VALIDATION_DIR="$(ls -1td data/processed/step67_sidecar_lane_validated/2026-* | head -n 1)"

echo
echo "===== latest draft summary ====="
cat "$(dirname "$DRAFTS")/summary.json"

echo
echo "===== latest validation summary ====="
cat "$LATEST_VALIDATION_DIR/summary.json"

echo
echo "===== validation snapshot preview ====="
sed -n '1,360p' "$LATEST_VALIDATION_DIR/review_snapshot.md"

echo
echo "STEP67_GEMMA4_LANE_AWARE_STRESS40_JOB_DONE"
