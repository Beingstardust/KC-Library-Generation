#!/bin/bash
#SBATCH --job-name=step53_qwen8b
#SBATCH --partition=gpu80GB
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=08:00:00
#SBATCH --output=/beegfs1/home/aryp26yc/projects/kc_l_v2_clean/slurm/step53_qwen8b_%j.out
#SBATCH --error=/beegfs1/home/aryp26yc/projects/kc_l_v2_clean/slurm/step53_qwen8b_%j.err

set -euo pipefail

cd /beegfs1/home/aryp26yc/projects/kc_l_v2_clean

export LD_LIBRARY_PATH=/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
export PYTHONPATH=/beegfs1/home/aryp26yc/projects/kc_l_v2_clean/src${PYTHONPATH:+:$PYTHONPATH}
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

PYBIN=/home/aryp26yc/venvs/kc_l_v2/bin/python

echo "HOSTNAME=$(hostname)"
echo "SLURM_JOB_ID=${SLURM_JOB_ID:-}"
echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-}"
echo "PATH=$PATH"
echo "LD_LIBRARY_PATH=$LD_LIBRARY_PATH"
echo "PYBIN=$PYBIN"
"$PYBIN" --version
nvidia-smi -L || true

"$PYBIN" steps/step_05_3_evidence_recalibrated/scripts/run_step5_3.py \
  --config steps/step_05_3_evidence_recalibrated/resources/step5_3.sofja.actual_corpus.yaml
