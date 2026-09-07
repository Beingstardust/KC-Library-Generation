#!/bin/bash
#SBATCH --job-name=v3_retry_hardfail2
#SBATCH --partition=gpu80GB
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --gres=gpu:1
#SBATCH --time=00:30:00
#SBATCH --output=/path/to/kc_l/v3/logs/retry_246363_hardfail2_%j.log
set -u
MIR=/path/to/kc_l
RUN=v3_20260817_baseline_rag_datamining_promptfix
export LD_LIBRARY_PATH=/path/to/python/lib
export PYTHONPATH=$MIR/src
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
PY=/path/to/venv/bin/python
DATA=$MIR/data/v3/runs/$RUN
cd $MIR || exit 1
echo "host=$(hostname) run=$RUN start=$(date)"
echo "targeted retry: KC_CLF_DT_012, KC_EVAL_BASIC_003 (both failed job 246363 with "
echo "unparseable_raw_response:JSONDecodeError - done_reason=length, prompt+eval tokens hit the "
echo "32768 num_ctx ceiling)"

source $MIR/config/runtime/clusterb_ollama_qwen38_27b.env

BASE_PORT=$(( 21000 + (${SLURM_JOB_ID:-0} % 8000) ))
for OFFSET in $(seq 0 40); do
  CAND=$(( BASE_PORT + OFFSET ))
  if ! (exec 3<>/dev/tcp/127.0.0.1/$CAND) 2>/dev/null; then export OLLAMA_HOST="127.0.0.1:$CAND"; break; fi
done
echo "ollama port: $OLLAMA_HOST"

PKT=$DATA/packets/kc_packets_retry_hardfail2.jsonl
OUT=$DATA/drafts/kc_work_qwen38_27b_retry_hardfail2
[ -f "$PKT" ] || { echo "FATAL: subset packets missing: $PKT"; exit 2; }
[ -e "$OUT" ] && { echo "FATAL: refusing to overwrite existing retry output"; exit 8; }
mkdir -p "$OUT"

OLLAMA_PID=""
cleanup(){ [ -n "$OLLAMA_PID" ] && kill "$OLLAMA_PID" 2>/dev/null || true; }
trap cleanup EXIT

"$KC_L_OLLAMA_BIN" serve > "$OUT/ollama_serve.log" 2>&1 &
OLLAMA_PID=$!
UP=0
for i in $(seq 1 120); do curl -sf "http://$OLLAMA_HOST/api/tags" >/dev/null 2>&1 && { UP=1; break; }; sleep 2; done
[ "$UP" = "1" ] || { echo "FATAL: ollama did not start"; exit 3; }

"$KC_L_OLLAMA_BIN" show "$KC_L_PROFILE_MODEL" >/dev/null 2>&1 || { echo "FATAL: model absent: $KC_L_PROFILE_MODEL"; exit 4; }
curl -sf "http://$OLLAMA_HOST/api/generate" -d "{\"model\":\"$KC_L_PROFILE_MODEL\",\"prompt\":\"ready\",\"stream\":false}" >/dev/null 2>&1 \
  || { echo "FATAL: model failed preflight"; exit 5; }
echo "preflight OK: $KC_L_PROFILE_MODEL"

echo '{}' > "$OUT/plan.json"
"$PY" steps/step_06_7_kc_draft_generation/scripts/v2_chain/run_step67_v2_schema_contract_probe.py \
  --base-runner "$MIR/v3/pipeline/04_draft_runner.py" \
  --selected-packets-jsonl "$PKT" \
  --plan-json "$OUT/plan.json" \
  --out-dir "$OUT" \
  --run-id kc_qwen38_27b_retry_hardfail2 \
  --model "$KC_L_PROFILE_MODEL" \
  --num-ctx 32768 --num-predict 16000 --timeout-s 1200 \
  --ollama-host "$OLLAMA_HOST" --seed 20260812
echo "probe rc=$? (informational: a correct abstention makes this non-zero)"

RAW=$OUT/step67_v2_tiny_smoke_drafts.jsonl
[ -f "$RAW" ] || { echo "FATAL: no drafts produced"; exit 6; }
echo "retry drafts -> $RAW ($(wc -l < "$RAW") rows)"

"$PY" "$MIR/v3/verify/validate_drafts.py" --drafts-jsonl "$RAW" --packets-jsonl "$PKT" --run-id kc_qwen38_27b_retry_hardfail2
VAL=$?
echo "=== validation rc=$VAL model=$KC_L_PROFILE_MODEL $(date) ==="
exit $VAL
