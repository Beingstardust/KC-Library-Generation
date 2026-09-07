#!/bin/bash
#SBATCH --job-name=r8_int23_ab
#SBATCH --partition=gpu80GB,gpu46GB,gpu
#SBATCH --gres=gpu:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=02:30:00
#SBATCH --output=/path/to/shared%j.log
set -u

# Controlled packet A/B. Both arms run sequentially in this one allocation, consume the exact
# frozen-r7 profiles and corpus, and share the dense cache. Arm A is the shipped c3dd685 worktree;
# Arm B is the isolated candidate worktree. No final-run artifact is modified.
BASELINE_REPO=${BASELINE_REPO:-/path/to/shared}
CANDIDATE_REPO=${CANDIDATE_REPO:-/path/to/shared}
PROD_REPO=${PROD_REPO:-/path/to/shared}
RUN_ID=${RUN_ID:-r8_int23_ab_${SLURM_JOB_ID}}
OUT_ROOT=$CANDIDATE_REPO/data/v3/experiments/$RUN_ID
PY=/path/to/venv/bin/python
PROFILES=$BASELINE_REPO/data/v3/runs/final_vnext_r7_20260821/profiles/kc_profiles.jsonl
FROZEN_R7=$BASELINE_REPO/data/v3/runs/final_vnext_r7_20260821/packets/kc_packets.jsonl
CORPUS=$PROD_REPO/data/processed/retrieval_sentence_overlay/20260727T022835Z_9e856df6/2026-07-27_085228/sentence_corpus.jsonl
ARM_A=$OUT_ROOT/packets/arm_a_c3dd685.jsonl
ARM_B=$OUT_ROOT/packets/arm_b_int23.jsonl

export LD_LIBRARY_PATH=/path/to/python/lib
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

for required in "$PROFILES" "$FROZEN_R7" "$CORPUS"; do
  [ -f "$required" ] || { echo "FATAL: missing input $required"; exit 8; }
done
[ -e "$OUT_ROOT" ] && { echo "FATAL: refusing to overwrite $OUT_ROOT"; exit 9; }
mkdir -p "$OUT_ROOT/packets" "$CANDIDATE_REPO/v3/logs"

echo "host=$(hostname) job=$SLURM_JOB_ID start=$(date)"
echo "baseline=$(git -C "$BASELINE_REPO" rev-parse HEAD)"
echo "candidate=$(git -C "$CANDIDATE_REPO" rev-parse HEAD) plus isolated working-tree diff"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || true

echo "=== candidate verifier ==="
export PYTHONPATH=$CANDIDATE_REPO/src
$PY "$CANDIDATE_REPO/v3/verify/verify_pipeline_fixes.py" || exit 3

echo "=== arm A: shipped c3dd685 ==="
export PYTHONPATH=$BASELINE_REPO/src
$PY "$BASELINE_REPO/v3/pipeline/02_build_kc_packets.py" \
  --corpus-jsonl "$CORPUS" \
  --profile-jsonl "$PROFILES" \
  --out-jsonl "$ARM_A" \
  --stats-json "$OUT_ROOT/packets/arm_a_stats.json" \
  --bm25-pool 400 --max-passages 40 --max-chars 14000 --min-relevance 0.55 || exit 4

echo "=== arm B: INT-23 candidate ==="
export PYTHONPATH=$CANDIDATE_REPO/src
$PY "$CANDIDATE_REPO/v3/pipeline/02_build_kc_packets.py" \
  --corpus-jsonl "$CORPUS" \
  --profile-jsonl "$PROFILES" \
  --out-jsonl "$ARM_B" \
  --stats-json "$OUT_ROOT/packets/arm_b_stats.json" \
  --bm25-pool 400 --max-passages 40 --max-chars 14000 --min-relevance 0.55 || exit 5

echo "=== whole-packet comparison ==="
$PY "$CANDIDATE_REPO/v3/evaluation/compare_packet_arms.py" \
  --arm-a "$ARM_A" --arm-b "$ARM_B" \
  --out-json "$OUT_ROOT/packet_ab_comparison.json" \
  --require-same-evidence || exit 6

echo "=== regenerated baseline versus frozen r7 ==="
$PY "$CANDIDATE_REPO/v3/evaluation/compare_packet_arms.py" \
  --arm-a "$FROZEN_R7" --arm-b "$ARM_A" \
  --out-json "$OUT_ROOT/r7_reproduction_comparison.json" || exit 7

echo "arm_a_sha256=$(sha256sum "$ARM_A" | awk '{print $1}')"
echo "arm_b_sha256=$(sha256sum "$ARM_B" | awk '{print $1}')"
echo "=== R8_INT23_AB_COMPLETE $(date) ==="
