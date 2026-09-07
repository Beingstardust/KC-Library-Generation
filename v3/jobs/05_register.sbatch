#!/bin/bash
#SBATCH --job-name=v3_register
#SBATCH --partition=big
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:15:00
#SBATCH --output=/path/to/kc_l/v3/logs/05_register_%j.log
set -u
MIR=/path/to/kc_l
cd $MIR || exit 1
python3 v3/pipeline/05_register_run.py --run-id v3_20260812
echo "=== registered $(date) ==="
