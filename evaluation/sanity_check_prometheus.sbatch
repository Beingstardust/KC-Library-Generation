#!/bin/bash
#SBATCH --job-name=prometheus2_sanity17
#SBATCH --partition=gpu80GB
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=00:45:00
#SBATCH --output=/path/to/projects/kc_l_v2_clean/local_audits/prometheus2_sanity17_%j.out
#SBATCH --error=/path/to/projects/kc_l_v2_clean/local_audits/prometheus2_sanity17_%j.err

set +e

REPO='/path/to/projects/kc_l_v2_clean'
export PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="/path/to/software/python/python-3.11.3/lib:/path/to/software/rh8/usr/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

PY=/path/to/venvs/kc_l_v2/bin/python

cd "$REPO" || exit 1
"$PY" evaluation/sanity_check_prometheus.py
echo "FINAL_RC=$?"
