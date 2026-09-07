#!/bin/bash
#SBATCH --job-name=r8_selected_generation
#SBATCH --partition=gpu-stud
#SBATCH --gres=gpu:h100:1
#SBATCH --time=00:30:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --output=/path/to/projects/kcl_final_draft/r8_selected_generation_%j.out
set -u

# Reusable end-to-end generation check for an explicitly selected packet JSONL. The caller owns
# selection; this runner changes neither packet content nor the frozen r7 artifacts.
V=${V:-/path/to/projects/kcl_final_draft}
PACKETS=${PACKETS:?set PACKETS to the selected packet JSONL}
DEST=$HOME/apps/ollama_v0.32.13_ants
RUN_ID=${RUN_ID:-r8_selected_generation_${SLURM_JOB_ID}}
ROOT=$V/r8_experiments/$RUN_ID
PY=$HOME/projects/kcl_int2_verifiers/.venv/bin/python
BIN=$DEST/bin/ollama

export PYTHONPATH=$V/src
export LD_LIBRARY_PATH="$DEST/lib:${LD_LIBRARY_PATH:-}"
export OLLAMA_MODELS=$HOME/ollama_models
export OLLAMA_CONTEXT_LENGTH=32768
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_FLASH_ATTENTION=1

[ -e "$ROOT" ] && { echo "FATAL: refusing to overwrite $ROOT"; exit 9; }
[ -s "$PACKETS" ] || { echo "FATAL: missing selected packets: $PACKETS"; exit 8; }
mkdir -p "$ROOT/work"
echo '{}' > "$ROOT/work/plan.json"

BASE_PORT=$((23000 + (${SLURM_JOB_ID:-0} % 6000)))
for OFFSET in $(seq 0 40); do
  CAND=$((BASE_PORT + OFFSET))
  if ! (exec 3<>/dev/tcp/127.0.0.1/$CAND) 2>/dev/null; then
    export OLLAMA_HOST="127.0.0.1:$CAND"
    break
  fi
done

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

$PY "$V/steps/step_06_7_kc_draft_generation/scripts/v2_chain/run_step67_v2_schema_contract_probe.py" \
  --base-runner "$V/v3/pipeline/04_draft_runner.py" \
  --selected-packets-jsonl "$PACKETS" \
  --plan-json "$ROOT/work/plan.json" \
  --out-dir "$ROOT/work" \
  --run-id "$RUN_ID" \
  --model qwen3.8:27b \
  --num-ctx 32768 --num-predict 16000 --timeout-s 1200 \
  --ollama-host "$OLLAMA_HOST" --seed 20260812 || true

RAW=$ROOT/work/step67_v2_tiny_smoke_drafts.jsonl
[ -s "$RAW" ] || { echo "FATAL: no draft artifact produced"; exit 6; }
cp "$RAW" "$ROOT/drafts.jsonl"
$PY "$V/v3/verify/validate_drafts.py" \
  --drafts-jsonl "$ROOT/drafts.jsonl" --packets-jsonl "$PACKETS" --run-id "$RUN_ID" || exit 7
$PY "$V/int12_draft_hygiene.py" \
  --drafts-jsonl "$ROOT/drafts.jsonl" --out-jsonl "$ROOT/hygiene.jsonl" || exit 8

echo "=== R8_SELECTED_PACKET_GENERATION_COMPLETE $(date) ==="
