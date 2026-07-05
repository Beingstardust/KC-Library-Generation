#!/bin/bash
#SBATCH --job-name=s67bc_genval
#SBATCH --partition=short
#SBATCH --output=logs/s67bc_genval_%j.out
#SBATCH --error=logs/s67bc_genval_%j.err
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:05:00

set -euo pipefail

cd /beegfs1/home/aryp26yc/projects/kc_l_v2_clean || exit 1

export PY=/home/aryp26yc/venvs/kc_l_v2/bin/python
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

B="scripts/experimental/step67b_lane_aware_onepass_generic.py"
C="scripts/experimental/step67c_validate_lane_aware_drafts_generic.py"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUTDIR="data/work/cache/diagnostics/step67bc_generic_script_validate_${STAMP}"
mkdir -p "$OUTDIR"

{
  echo "OUTDIR=$OUTDIR"
  echo "HOST=$(hostname)"
  echo "PWD=$PWD"
  echo "PY=$PY"
  "$PY" --version
  echo "B=$B"
  echo "C=$C"
  echo "SLURM_JOB_ID=${SLURM_JOB_ID:-NA}"
  echo "SLURM_JOB_PARTITION=${SLURM_JOB_PARTITION:-NA}"
} | tee "$OUTDIR/00_paths.log"

echo
echo "===== PY_COMPILE =====" | tee "$OUTDIR/01_py_compile.log"
"$PY" -m py_compile "$B" "$C" 2>&1 | tee -a "$OUTDIR/01_py_compile.log"

echo
echo "===== STEP67B GENERIC HELP =====" | tee "$OUTDIR/02_step67b_help.log"
"$PY" "$B" --help 2>&1 | tee -a "$OUTDIR/02_step67b_help.log"

echo
echo "===== STEP67C GENERIC HELP =====" | tee "$OUTDIR/03_step67c_help.log"
"$PY" "$C" --help 2>&1 | tee -a "$OUTDIR/03_step67c_help.log"

echo
echo "===== LEAKAGE / ARCHITECTURE GREP =====" | tee "$OUTDIR/04_leakage_grep.log"
grep -nEi 'seed_definition|seed_floor|gemma4|gemma3|qwen3|KC_[A-Z0-9_]+|ACTIVE|CURRENT|step6_8|review packet|data/processed/.*/2026-04' "$B" "$C" \
  2>&1 | tee -a "$OUTDIR/04_leakage_grep.log" || true

echo
echo "===== OLLAMA/BACKEND REFERENCES =====" | tee "$OUTDIR/05_backend_grep.log"
grep -nEi 'ollama|base-url|api/chat|model|reasoning-mode|think|nothink' "$B" "$C" \
  2>&1 | tee -a "$OUTDIR/05_backend_grep.log" || true

echo
echo "===== VALIDATION OUTDIR ====="
echo "$OUTDIR"

echo
echo "STEP67BC_GENERIC_SCRIPT_VALIDATE_DONE"
