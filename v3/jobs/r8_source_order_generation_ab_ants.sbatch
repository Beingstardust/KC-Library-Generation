#!/bin/bash
#SBATCH --job-name=r8_order_ab
#SBATCH --partition=gpu-stud
#SBATCH --gres=gpu:h100:1
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --output=/path/to/projects/kcl_final_draft/r8_order_ab_%j.out
set -u

# Cluster A form of the matched source-order generation A/B. The r7 mirror, model, prompt, and Python
# environment are the same ones that produced the frozen r7 draft artifact on this cluster.
V=${V:-/path/to/projects/kcl_final_draft}
DEST=$HOME/apps/ollama_v0.32.13_ants
RUN_ID=${RUN_ID:-r8_source_order_ab_${SLURM_JOB_ID}}
ROOT=$V/r8_experiments/$RUN_ID
PACKET_DIR=$ROOT/packet_arms
PY=$HOME/projects/kcl_int2_verifiers/.venv/bin/python
BIN=$DEST/bin/ollama
FROZEN_PACKETS=$V/packets/kc_packets.jsonl
FROZEN_DRAFTS=$V/r7_kc_drafts_qwen38_27b.jsonl

export PYTHONPATH=$V/src
export LD_LIBRARY_PATH="$DEST/lib:${LD_LIBRARY_PATH:-}"
export OLLAMA_MODELS=$HOME/ollama_models
export OLLAMA_CONTEXT_LENGTH=32768
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_FLASH_ATTENTION=1

[ -e "$ROOT" ] && { echo "FATAL: refusing to overwrite $ROOT"; exit 9; }
[ -f "$FROZEN_PACKETS" ] || { echo "FATAL: missing $FROZEN_PACKETS"; exit 8; }
[ -f "$FROZEN_DRAFTS" ] || { echo "FATAL: missing $FROZEN_DRAFTS"; exit 8; }
mkdir -p "$ROOT"

echo "host=$(hostname) job=$SLURM_JOB_ID start=$(date)"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || true

echo "=== build matched packet arms ==="
$PY "$V/v3/evaluation/build_r8_source_order_ab.py" \
  --packets "$FROZEN_PACKETS" --drafts "$FROZEN_DRAFTS" \
  --out-dir "$PACKET_DIR" --control-count 8 || exit 2

BASE_PORT=$((23000 + (${SLURM_JOB_ID:-0} % 6000)))
for OFFSET in $(seq 0 40); do
  CAND=$((BASE_PORT + OFFSET))
  if ! (exec 3<>/dev/tcp/127.0.0.1/$CAND) 2>/dev/null; then
    export OLLAMA_HOST="127.0.0.1:$CAND"
    break
  fi
done
echo "ollama port: $OLLAMA_HOST"

OLLAMA_PID=""
cleanup(){ [ -n "$OLLAMA_PID" ] && kill "$OLLAMA_PID" 2>/dev/null || true; }
trap cleanup EXIT
"$BIN" serve > "$ROOT/ollama_serve.log" 2>&1 &
OLLAMA_PID=$!
UP=0
for i in $(seq 1 120); do
  curl -sf "http://$OLLAMA_HOST/api/tags" >/dev/null 2>&1 && { UP=1; break; }
  sleep 2
done
[ "$UP" = "1" ] || { echo "FATAL: ollama did not start"; exit 3; }
curl -sf "http://$OLLAMA_HOST/api/generate" \
  -d '{"model":"qwen3.8:27b","prompt":"ready","stream":false}' \
  >/dev/null 2>&1 || { echo "FATAL: model preflight failed"; exit 5; }

run_arm(){
  ARM_NAME=$1
  PACKETS=$2
  ARM_DIR=$ROOT/$ARM_NAME
  WORK=$ARM_DIR/work
  FINAL=$ARM_DIR/drafts.jsonl
  mkdir -p "$WORK"
  echo '{}' > "$WORK/plan.json"
  echo "=== drafting $ARM_NAME $(date) ==="
  $PY "$V/steps/step_06_7_kc_draft_generation/scripts/v2_chain/run_step67_v2_schema_contract_probe.py" \
    --base-runner "$V/v3/pipeline/04_draft_runner.py" \
    --selected-packets-jsonl "$PACKETS" \
    --plan-json "$WORK/plan.json" \
    --out-dir "$WORK" \
    --run-id "$ARM_NAME" \
    --model qwen3.8:27b \
    --num-ctx 32768 --num-predict 16000 --timeout-s 1200 \
    --ollama-host "$OLLAMA_HOST" --seed 20260812 || true
  RAW=$WORK/step67_v2_tiny_smoke_drafts.jsonl
  [ -s "$RAW" ] || { echo "FATAL: $ARM_NAME produced no drafts"; return 6; }
  cp "$RAW" "$FINAL"
  $PY "$V/v3/verify/validate_drafts.py" \
    --drafts-jsonl "$FINAL" --packets-jsonl "$PACKETS" --run-id "$ARM_NAME" || return 7
  $PY "$V/int12_draft_hygiene.py" \
    --drafts-jsonl "$FINAL" --out-jsonl "$ARM_DIR/hygiene.jsonl" || return 8
}

run_arm arm_a_current "$PACKET_DIR/arm_a_current_order_packets.jsonl" || exit $?
run_arm arm_b_source "$PACKET_DIR/arm_b_source_order_packets.jsonl" || exit $?

echo "=== matched output comparison ==="
$PY "$V/v3/evaluation/compare_r8_source_order_drafts.py" \
  --arm-a "$ROOT/arm_a_current/drafts.jsonl" \
  --arm-b "$ROOT/arm_b_source/drafts.jsonl" \
  --manifest "$PACKET_DIR/selection_manifest.json" \
  --hygiene-a "$ROOT/arm_a_current/hygiene.jsonl" \
  --hygiene-b "$ROOT/arm_b_source/hygiene.jsonl" \
  --out-json "$ROOT/draft_comparison.json" || exit 10

echo "=== R8_SOURCE_ORDER_AB_COMPLETE $(date) ==="
