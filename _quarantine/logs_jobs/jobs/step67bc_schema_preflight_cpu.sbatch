#!/bin/bash
#SBATCH --job-name=s67bc_schema
#SBATCH --partition=short
#SBATCH --output=logs/s67bc_schema_%j.out
#SBATCH --error=logs/s67bc_schema_%j.err
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:05:00

set -euo pipefail

cd /beegfs1/home/aryp26yc/projects/kc_l_v2_clean || exit 1

export PY=/home/aryp26yc/venvs/kc_l_v2/bin/python
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUTDIR="data/work/cache/diagnostics/step67bc_schema_preflight_${STAMP}"
mkdir -p "$OUTDIR"

B="scripts/experimental/step67b_lane_aware_gemma4_onepass.py"
C="scripts/experimental/step67c_validate_lane_aware_drafts.py"

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
echo "===== FILE EXISTENCE =====" | tee "$OUTDIR/01_file_existence.log"
for f in "$B" "$C"; do
  if [ -f "$f" ]; then
    ls -lh "$f" | tee -a "$OUTDIR/01_file_existence.log"
  else
    echo "MISSING: $f" | tee -a "$OUTDIR/01_file_existence.log"
  fi
done

echo
echo "===== PY_COMPILE =====" | tee "$OUTDIR/02_py_compile.log"
"$PY" -m py_compile "$B" "$C" 2>&1 | tee -a "$OUTDIR/02_py_compile.log"

echo
echo "===== STEP67B LINES 260-390 =====" | tee "$OUTDIR/03_step67b_tail.log"
sed -n '260,390p' "$B" | tee -a "$OUTDIR/03_step67b_tail.log"

echo
echo "===== STEP67C HELP =====" | tee "$OUTDIR/04_step67c_help.log"
set +e
"$PY" "$C" --help 2>&1 | tee -a "$OUTDIR/04_step67c_help.log"
HELP_RC=${PIPESTATUS[0]}
set -e
echo "HELP_RC=$HELP_RC" | tee -a "$OUTDIR/04_step67c_help.log"

echo
echo "===== STEP67C TOP 340 LINES =====" | tee "$OUTDIR/05_step67c_head.log"
sed -n '1,340p' "$C" | tee -a "$OUTDIR/05_step67c_head.log"

echo
echo "===== STEP67C RISK GREP =====" | tee "$OUTDIR/06_step67c_risk_grep.log"
grep -nEi 'ACTIVE|pointer|CURRENT|alias|step6_8|review|seed_definition|seed_floor|hardcoded|/beegfs|2026-04|gemma4|qwen3|ollama|model|host|port|temperature|num_ctx|lane|out|draft|grounded|abstained|supporting_evidence|status|definition|scope' "$C" \
  2>&1 | tee -a "$OUTDIR/06_step67c_risk_grep.log" || true

echo
echo "===== EXISTING V8 VALIDATED SUMMARY IF PRESENT =====" | tee "$OUTDIR/07_v8_validated_summary.log"
V8SUM="data/processed/step67_sidecar_lane_validated/2026-04-28_173218/summary.json"
if [ -f "$V8SUM" ]; then
  cat "$V8SUM" | tee -a "$OUTDIR/07_v8_validated_summary.log"
else
  echo "Missing: $V8SUM" | tee -a "$OUTDIR/07_v8_validated_summary.log"
fi

echo
echo "===== EXISTING V8 VALIDATION ROW SAMPLE IF PRESENT =====" | tee "$OUTDIR/08_v8_validation_rows_sample.log"
V8ROWS="data/processed/step67_sidecar_lane_validated/2026-04-28_173218/validation_rows.jsonl"
if [ -f "$V8ROWS" ]; then
  head -n 3 "$V8ROWS" | tee -a "$OUTDIR/08_v8_validation_rows_sample.log"
else
  echo "Missing: $V8ROWS" | tee -a "$OUTDIR/08_v8_validation_rows_sample.log"
fi

echo
echo "===== SCHEMA PREFLIGHT OUTDIR ====="
echo "$OUTDIR"

echo
echo "STEP67BC_SCHEMA_PREFLIGHT_DONE"
