#!/bin/bash
#SBATCH -J kc_step3_5_corpus3
#SBATCH -p big
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=12:00:00
#SBATCH -o /beegfs2/scratch/aryp26yc/kc_l/slurm_logs/%x_%j.out
#SBATCH -e /beegfs2/scratch/aryp26yc/kc_l/slurm_logs/%x_%j.err

set -euo pipefail

unset PROMPT_COMMAND || true
source ~/kc_l_v2_env.sh

REPO=/beegfs1/home/aryp26yc/projects/kc_l_v2_clean
cd "$REPO"

export PYTHONPATH="$REPO/src"
export LD_LIBRARY_PATH="/beegfs1/software/rh8/usr/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export HF_HOME=/beegfs2/scratch/aryp26yc/kc_l/cache/hf
export XDG_CACHE_HOME=/beegfs2/scratch/aryp26yc/kc_l/cache/xdg
unset TRANSFORMERS_CACHE || true

CONFIG="$REPO/steps/step_03_5_blockstore_cleanup/resources/step3_5.sofja.actual_corpus.yaml"

python steps/step_03_5_blockstore_cleanup/scripts/run_step3_5.py \
  --config "$CONFIG"
