#!/bin/bash
#SBATCH -J kc_step4_5_overlay
#SBATCH -p big
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --time=12:00:00
#SBATCH -o /path/to/scratch/kc_l/slurm_logs/%x_%j.out
#SBATCH -e /path/to/scratch/kc_l/slurm_logs/%x_%j.err

set -euo pipefail
set -x

unset PROMPT_COMMAND || true
source ~/kc_l_v2_env.sh

REPO=/path/to/projects/kc_l_v2_clean
cd "$REPO"

export PYTHONUNBUFFERED=1
export PYTHONPATH="$REPO/src"
export LD_LIBRARY_PATH="/path/to/software/python/python-3.11.3/lib:/path/to/software/rh8/usr/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

CONFIG="$REPO/steps/step_04_5_sentence_overlay/resources/step4_5.hpc.actual_corpus.yaml"

echo "HOST=$(hostname)"
echo "PWD=$(pwd)"
echo "PYTHON=$(which python)"
python -V
echo "CONFIG=$CONFIG"
sed -n '1,220p' "$CONFIG"

python -u steps/step_04_5_sentence_overlay/scripts/run_step4_5.py --config "$CONFIG"

echo "== POST RUN SEARCH =="
find /path/to/scratch/kc_l/data/processed/retrieval_sentence_overlay -maxdepth 3 | sort | sed -n '1,220p'
