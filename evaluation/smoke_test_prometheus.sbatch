#!/bin/bash
#SBATCH --job-name=prometheus2_smoke
#SBATCH --partition=gpu80GB
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=00:30:00
#SBATCH --output=/path/to/projects/kc_l_v2_clean/local_audits/prometheus2_smoke_%j.out
#SBATCH --error=/path/to/projects/kc_l_v2_clean/local_audits/prometheus2_smoke_%j.err

set +e

REPO='/path/to/projects/kc_l_v2_clean'
export PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="/path/to/software/python/python-3.11.3/lib:/path/to/software/rh8/usr/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

PY=/path/to/venvs/kc_l_v2/bin/python

echo "PYTHON_BIN=$PY"
nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv

"$PY" /path/to/projects/kc_l_v2_clean/evaluation/smoke_test_prometheus.py
echo "FINAL_RC=$?"
