#!/bin/bash
#SBATCH --job-name=kc-library-textbook
#SBATCH --partition=REPLACE_ME_SLURM_PARTITION
#SBATCH --account=REPLACE_ME_SLURM_ACCOUNT
#SBATCH --gres=REPLACE_ME_SLURM_GRES
#SBATCH --cpus-per-task=REPLACE_ME_CPUS
#SBATCH --mem=REPLACE_ME_MEMORY
#SBATCH --time=REPLACE_ME_WALLTIME
#SBATCH --output=REPLACE_ME_LOGS_ROOT/%x-%j.out
#SBATCH --error=REPLACE_ME_LOGS_ROOT/%x-%j.err

set -euo pipefail

REPO_ROOT="REPLACE_ME_REPO_ROOT"
SCRATCH_ROOT="REPLACE_ME_SCRATCH_ROOT"
PYTHON_WRAPPER="REPLACE_ME_HPC_PYTHON_OR_WRAPPER"

cd "${REPO_ROOT}"

echo "Render the HPC config before first launch:"
echo "  python scripts/hpc/render_main_quest_config.py --mode hpc_gpu"
echo "Heavy runtime artifacts should land under ${SCRATCH_ROOT}, not inside the repo."
