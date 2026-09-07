#!/bin/bash
#SBATCH --job-name=r9_dos_budget_match
#SBATCH --partition=gpu80GB
#SBATCH --gres=gpu:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=04:00:00
#SBATCH --output=/path/to/shared%j.log
set -u

MIR=${MIR:-/path/to/shared}
OLD_MIR=${OLD_MIR:-/path/to/kc_l}
PROD=${PROD:-/path/to/shared}
EXPERIMENT_ID=${EXPERIMENT_ID:-r9_dos_budget_matched_${SLURM_JOB_ID:-manual}}
MATCHED_RUN=${MATCHED_RUN:-${EXPERIMENT_ID}_run}

PROPOSED_PACKETS=${PROPOSED_PACKETS:-$MIR/data/v3/experiments/r8_int23_ab_249460/packets/arm_b_int23.jsonl}
DOS_FULL_PACKETS=${DOS_FULL_PACKETS:-$OLD_MIR/data/v3/runs/final_e3944aa_20260818T140248Z/dos_rag/packets/kc_packets.jsonl}
CORPUS=${CORPUS:-$PROD/data/processed/retrieval_sentence_overlay/20260727T022835Z_9e856df6/2026-07-27_085228/sentence_corpus.jsonl}
INDEX_CACHE=${INDEX_CACHE:-$OLD_MIR/data/v3/runs/final_e3944aa_20260818T140248Z/dos_rag/_index_cache/dosrag_nodes.pkl}
OUT_ROOT=$MIR/data/v3/experiments/$EXPERIMENT_ID
MATCHED_RUN_DIR=$MIR/data/v3/runs/$MATCHED_RUN

export LD_LIBRARY_PATH=/path/to/python/lib
export PYTHONPATH=$MIR/src
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
PY=${PY:-/path/to/venv/bin/python}

cd "$MIR" || exit 1
mkdir -p "$MIR/v3/logs"
source "$MIR/config/runtime/clusterb_ollama_qwen38_27b.env"

echo "host=$(hostname) job=${SLURM_JOB_ID:-?} experiment=$EXPERIMENT_ID matched_run=$MATCHED_RUN start=$(date)"
echo "repo_head=$(git -C "$MIR" rev-parse HEAD)"
echo "proposed=$PROPOSED_PACKETS"
echo "dos_full=$DOS_FULL_PACKETS"
echo "corpus=$CORPUS"
echo "embedding_model_dir=not_used_for_frozen_cache_matching"
echo "token_model=$KC_L_PROFILE_MODEL"
echo "ollama_bin=$KC_L_OLLAMA_BIN"
echo "allow_ollama_generate_token_count=${ALLOW_OLLAMA_GENERATE_TOKEN_COUNT:-0}"
"$KC_L_OLLAMA_BIN" --version 2>&1 | head -5 || true
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || true

for required in "$PROPOSED_PACKETS" "$DOS_FULL_PACKETS" "$CORPUS" "$INDEX_CACHE"; do
  [ -e "$required" ] || { echo "FATAL: missing input $required"; exit 8; }
done
[ -e "$OUT_ROOT" ] && { echo "FATAL: refusing to overwrite $OUT_ROOT"; exit 9; }
[ -e "$MATCHED_RUN_DIR" ] && { echo "FATAL: refusing to overwrite $MATCHED_RUN_DIR"; exit 10; }

BASE_PORT=$(( 24000 + (${SLURM_JOB_ID:-0} % 6000) ))
for OFFSET in $(seq 0 40); do
  CAND=$(( BASE_PORT + OFFSET ))
  if ! (exec 3<>/dev/tcp/127.0.0.1/$CAND) 2>/dev/null; then
    export OLLAMA_HOST="127.0.0.1:$CAND"
    break
  fi
done

OLLAMA_PID=""
cleanup(){ [ -n "$OLLAMA_PID" ] && kill "$OLLAMA_PID" 2>/dev/null || true; }
trap cleanup EXIT
"$KC_L_OLLAMA_BIN" serve > "$OUT_ROOT.ollama_serve.log" 2>&1 &
OLLAMA_PID=$!
UP=0
for i in $(seq 1 120); do
  curl -sf "http://$OLLAMA_HOST/api/tags" >/dev/null 2>&1 && { UP=1; break; }
  sleep 2
done
[ "$UP" = "1" ] || { echo "FATAL: ollama did not start"; exit 3; }
curl -sf "http://$OLLAMA_HOST/api/generate" \
  -d "{\"model\":\"$KC_L_PROFILE_MODEL\",\"prompt\":\"ready\",\"stream\":false,\"options\":{\"num_predict\":1}}" \
  >/dev/null 2>&1 || { echo "FATAL: model preflight failed"; exit 5; }

TOKEN_COUNT_ARGS=()
if [ "${ALLOW_OLLAMA_GENERATE_TOKEN_COUNT:-0}" = "1" ]; then
  TOKEN_COUNT_ARGS+=(--allow-ollama-generate-token-count)
fi

"$PY" "$MIR/v3/evaluation/build_dos_budget_matched_packets.py" \
  --proposed-packets-jsonl "$PROPOSED_PACKETS" \
  --dos-full-packets-jsonl "$DOS_FULL_PACKETS" \
  --corpus-jsonl "$CORPUS" \
  --index-cache "$INDEX_CACHE" \
  --out-root "$OUT_ROOT" \
  --matched-run-dir "$MATCHED_RUN_DIR" \
  --tokenizer ollama \
  --ollama-host "$OLLAMA_HOST" \
  --ollama-model "$KC_L_PROFILE_MODEL" \
  --prompt-mode controlled_comparator \
  "${TOKEN_COUNT_ARGS[@]}"
RC=$?
cp "$OUT_ROOT.ollama_serve.log" "$OUT_ROOT/ollama_serve.log" 2>/dev/null || true
echo "=== R9_DOS_BUDGET_MATCH rc=$RC $(date) ==="
exit "$RC"
