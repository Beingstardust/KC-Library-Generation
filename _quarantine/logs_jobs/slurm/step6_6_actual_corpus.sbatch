#!/bin/bash
#SBATCH --job-name=step66_actual
#SBATCH --partition=medium
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=06:00:00
#SBATCH --output=/beegfs1/home/aryp26yc/projects/kc_l_v2_clean/slurm/step66_actual_%j.out
#SBATCH --error=/beegfs1/home/aryp26yc/projects/kc_l_v2_clean/slurm/step66_actual_%j.err

set -euo pipefail

cd /beegfs1/home/aryp26yc/projects/kc_l_v2_clean

export LD_LIBRARY_PATH=/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
export PYTHONPATH=/beegfs1/home/aryp26yc/projects/kc_l_v2_clean/src${PYTHONPATH:+:$PYTHONPATH}

PYTHON_BIN=/home/aryp26yc/venvs/kc_l_v2/bin/python

echo "HOSTNAME=$(hostname)"
echo "SLURM_JOB_ID=${SLURM_JOB_ID:-}"
echo "PYTHON_BIN=${PYTHON_BIN}"
"${PYTHON_BIN}" --version

"${PYTHON_BIN}" \
  steps/step_06_6_kc_drafting_input_overlay/scripts/run_step6_6_kc_drafting_input_overlay.py \
  --config steps/step_06_6_kc_drafting_input_overlay/resources/step6_6.sofja.actual_corpus.yaml
