#!/bin/bash
#SBATCH --job-name=step67v2_cpuval
#SBATCH --partition=short
#SBATCH --output=logs/step67v2_cpuval_%j.out
#SBATCH --error=logs/step67v2_cpuval_%j.err
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=00:20:00

set -euo pipefail

cd /beegfs1/home/aryp26yc/projects/kc_l_v2_clean || exit 1

export PY=/home/aryp26yc/venvs/kc_l_v2/bin/python
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

RUN_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
VALID_ROOT="data/work/cache/diagnostics/step67_generic_policy_v2_sofja_validation_${RUN_STAMP}"
OUTROOT="data/work/cache/diagnostics/step67_generic_lane_policy_v2_sofja_replay"

mkdir -p "$VALID_ROOT" "$OUTROOT"

{
  echo "VALID_ROOT=$VALID_ROOT"
  echo "OUTROOT=$OUTROOT"
  echo "HOST=$(hostname)"
  echo "PWD=$PWD"
  echo "PY=$PY"
  "$PY" --version
  echo "SLURM_JOB_ID=${SLURM_JOB_ID:-NA}"
  echo "SLURM_JOB_NAME=${SLURM_JOB_NAME:-NA}"
  echo "SLURM_JOB_PARTITION=${SLURM_JOB_PARTITION:-NA}"
  echo "SLURM_CPUS_PER_TASK=${SLURM_CPUS_PER_TASK:-NA}"
} | tee "$VALID_ROOT/00_paths.log"

echo
echo "===== PY_COMPILE ====="
"$PY" -m py_compile \
  src/kc_l/kc_drafting/evidence_lane_policy.py \
  scripts/experimental/step67a_build_field_lane_packets_generic.py \
  tests/test_evidence_lane_policy.py \
  tests/test_step67_sidecar_domain_agnosticity.py \
  2>&1 | tee "$VALID_ROOT/01_py_compile.log"

echo
echo "===== DIRECT TEST: evidence lane policy ====="
"$PY" tests/test_evidence_lane_policy.py \
  2>&1 | tee "$VALID_ROOT/02_test_evidence_lane_policy.log"

echo
echo "===== DIRECT TEST: domain agnosticity ====="
"$PY" tests/test_step67_sidecar_domain_agnosticity.py \
  2>&1 | tee "$VALID_ROOT/03_test_step67_sidecar_domain_agnosticity.log"

echo
echo "===== SIMPLE IMPLEMENTATION LEAKAGE SCAN ====="
LEAKAGE_LOG="$VALID_ROOT/04_simple_leakage_scan.log"
: > "$LEAKAGE_LOG"

echo "Implementation files scanned:" | tee -a "$LEAKAGE_LOG"
echo "src/kc_l/kc_drafting/evidence_lane_policy.py" | tee -a "$LEAKAGE_LOG"
echo "scripts/experimental/step67a_build_field_lane_packets_generic.py" | tee -a "$LEAKAGE_LOG"
echo | tee -a "$LEAKAGE_LOG"

grep -InEi \
  'kmeans|k-means|k means|jaccard|gini|hunt|core point|border point|noise point|euclidean|mahalanobis|dbscan|(^|[^a-zA-Z0-9])eps([^a-zA-Z0-9]|$)|minpts|information gain|confusion matrix|naive bayes|bayes|laplace|gemma4|gemma3|qwen3|ollama|seed_definition|seed_floor|seed definition|KC_[A-Z0-9_]+' \
  src/kc_l/kc_drafting/evidence_lane_policy.py \
  scripts/experimental/step67a_build_field_lane_packets_generic.py \
  2>&1 | tee -a "$LEAKAGE_LOG" || true

echo
echo "===== BOUNDED 40-PACKET REPLAY ====="
"$PY" scripts/experimental/step67a_build_field_lane_packets_generic.py \
  --packets data/processed/step67_sidecar_packets_40/2026-04-28_161958/evidence_packets.jsonl \
  --overlay data/processed/kc_drafting_input_overlay/2026-04-28_002730/candidate_sentence_overlay.jsonl \
  --out-root "$OUTROOT" \
  2>&1 | tee "$VALID_ROOT/05_bounded_replay.log"

REPLAY_DIR="$(ls -1td "$OUTROOT"/2026-* | head -n 1)"
echo "REPLAY_DIR=$REPLAY_DIR" | tee "$VALID_ROOT/06_replay_dir.log"

cp "$REPLAY_DIR/summary.json" "$VALID_ROOT/replay_summary.json"
cp "$REPLAY_DIR/lane_audit.md" "$VALID_ROOT/replay_lane_audit.md"
cp "$REPLAY_DIR/lane_packets.jsonl" "$VALID_ROOT/replay_lane_packets.jsonl"

echo
echo "===== REPLAY SUMMARY ====="
cat "$REPLAY_DIR/summary.json" | tee "$VALID_ROOT/07_replay_summary_printed.log"

echo
echo "===== HIGH-RISK KC EXTRACT ====="
HIGH_RISK="$VALID_ROOT/08_high_risk_kc_extract.log"
: > "$HIGH_RISK"

for KC in \
  KC_CLF_DT_001 \
  KC_CLU_KM_001 \
  KC_CLU_SIM_003 \
  KC_CLU_HIER_005 \
  KC_CLF_DT_010 \
  KC_CLF_NB_003 \
  KC_EVAL_BASIC_001 \
  KC_EVAL_SAMP_003
do
  echo | tee -a "$HIGH_RISK"
  echo "==================== $KC ====================" | tee -a "$HIGH_RISK"
  grep -n -A 25 "$KC" "$REPLAY_DIR/lane_audit.md" | sed -n "1,80p" | tee -a "$HIGH_RISK" || true
done

echo
echo "===== VALIDATION ROOT ====="
echo "$VALID_ROOT"

echo
echo "STEP67_GENERIC_POLICY_V2_SOFJA_VALIDATION_DONE"
