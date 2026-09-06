#!/bin/bash
#SBATCH -J kc_step4_patches
#SBATCH -p big
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --time=12:00:00
#SBATCH -o /path/to/scratch/kc_l/slurm_logs/%x_%j.out
#SBATCH -e /path/to/scratch/kc_l/slurm_logs/%x_%j.err

set -euo pipefail

unset PROMPT_COMMAND || true
source ~/kc_l_v2_env.sh

REPO=/path/to/projects/kc_l_v2_clean
cd "$REPO"

export PYTHONPATH="$REPO/src"
export LD_LIBRARY_PATH="/path/to/software/python/python-3.11.3/lib:/path/to/software/rh8/usr/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

CONFIG="$REPO/steps/step_04_structure_retrieval_index/resources/step4.patches.hpc.actual_corpus.yaml"

python steps/step_04_structure_retrieval_index/scripts/run_step4.py \
  --config "$CONFIG"
