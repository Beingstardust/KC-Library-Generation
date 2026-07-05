#!/bin/bash
#SBATCH --job-name=s67b_v2_preflight
#SBATCH --partition=short
#SBATCH --output=logs/s67b_v2_preflight_%j.out
#SBATCH --error=logs/s67b_v2_preflight_%j.err
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:05:00

set -euo pipefail

cd /beegfs1/home/aryp26yc/projects/kc_l_v2_clean || exit 1

export PY=/home/aryp26yc/venvs/kc_l_v2/bin/python
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUTDIR="data/work/cache/diagnostics/step67b_v2_model_preflight_${STAMP}"
mkdir -p "$OUTDIR"

SCRIPT="scripts/experimental/step67b_lane_aware_gemma4_onepass.py"
V2_REPLAY_ROOT="data/work/cache/diagnostics/step67_generic_lane_policy_v2_sofja_replay"
V2_REPLAY_DIR="$(ls -1td "$V2_REPLAY_ROOT"/2026-* | head -n 1)"
V2_LANES="$V2_REPLAY_DIR/lane_packets.jsonl"
V2_SUMMARY="$V2_REPLAY_DIR/summary.json"

{
  echo "OUTDIR=$OUTDIR"
  echo "HOST=$(hostname)"
  echo "PWD=$PWD"
  echo "PY=$PY"
  "$PY" --version
  echo "SCRIPT=$SCRIPT"
  echo "V2_REPLAY_DIR=$V2_REPLAY_DIR"
  echo "V2_LANES=$V2_LANES"
  echo "V2_SUMMARY=$V2_SUMMARY"
  echo "SLURM_JOB_ID=${SLURM_JOB_ID:-NA}"
  echo "SLURM_JOB_PARTITION=${SLURM_JOB_PARTITION:-NA}"
} | tee "$OUTDIR/00_paths.log"

echo
echo "===== FILE EXISTENCE =====" | tee "$OUTDIR/01_file_existence.log"
for f in "$SCRIPT" "$V2_LANES" "$V2_SUMMARY"; do
  if [ -f "$f" ]; then
    ls -lh "$f" | tee -a "$OUTDIR/01_file_existence.log"
  else
    echo "MISSING: $f" | tee -a "$OUTDIR/01_file_existence.log"
  fi
done

echo
echo "===== PY_COMPILE STEP67B SCRIPT =====" | tee "$OUTDIR/02_py_compile.log"
"$PY" -m py_compile "$SCRIPT" 2>&1 | tee -a "$OUTDIR/02_py_compile.log"

echo
echo "===== STEP67B HELP =====" | tee "$OUTDIR/03_help.log"
set +e
"$PY" "$SCRIPT" --help 2>&1 | tee -a "$OUTDIR/03_help.log"
HELP_RC=${PIPESTATUS[0]}
set -e
echo "HELP_RC=$HELP_RC" | tee -a "$OUTDIR/03_help.log"

echo
echo "===== STEP67B TOP 260 LINES =====" | tee "$OUTDIR/04_script_head.log"
sed -n '1,260p' "$SCRIPT" | tee -a "$OUTDIR/04_script_head.log"

echo
echo "===== STEP67B RISK GREP =====" | tee "$OUTDIR/05_risk_grep.log"
grep -nEi 'ACTIVE|pointer|CURRENT|alias|step6_8|review|seed_definition|seed_floor|hardcoded|/beegfs|2026-04|gemma4|qwen3|ollama|model|host|port|temperature|num_ctx|lane|out|draft' "$SCRIPT" \
  2>&1 | tee -a "$OUTDIR/05_risk_grep.log" || true

echo
echo "===== V2 REPLAY SUMMARY =====" | tee "$OUTDIR/06_v2_summary.log"
cat "$V2_SUMMARY" | tee -a "$OUTDIR/06_v2_summary.log"

echo
echo "===== GPU STATE SNAPSHOT =====" | tee "$OUTDIR/07_gpu_state.log"
sinfo -N -p gpu,gpu80GB,gpu46GB,gpu7d -o "%N %P %t %G %C %m" | tee -a "$OUTDIR/07_gpu_state.log"

echo
echo "===== CURRENT USER JOBS =====" | tee "$OUTDIR/08_user_jobs.log"
squeue -u "$USER" -o "%.18i %.28j %.12P %.10T %.12M %.12l %.20R" | tee -a "$OUTDIR/08_user_jobs.log"

echo
echo "===== PREFLIGHT OUTDIR ====="
echo "$OUTDIR"

echo
echo "STEP67B_V2_MODEL_PREFLIGHT_DONE"
