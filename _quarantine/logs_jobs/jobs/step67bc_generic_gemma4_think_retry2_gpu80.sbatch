#!/bin/bash
#SBATCH --job-name=s67bc_g4_t2
#SBATCH --partition=gpu80GB
#SBATCH --gres=gpu:a100:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=01:15:00
#SBATCH --output=logs/s67bc_g4_t2_%j.out
#SBATCH --error=logs/s67bc_g4_t2_%j.err

set -euo pipefail

REPO=/beegfs1/home/aryp26yc/projects/kc_l_v2_clean
PY=/home/aryp26yc/venvs/kc_l_v2/bin/python

cd "$REPO" || exit 1

export PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

export OLLAMA_BIN=/beegfs1/home/aryp26yc/apps/ollama_upgrade_clean_20260425_214752/bin/ollama
export OLLAMA_MODELS=/beegfs2/scratch/aryp26yc/kc_l/ollama/models
export OLLAMA_HOST="127.0.0.1:$((29000 + SLURM_JOB_ID % 20000))"
export OLLAMA_BASE_URL="http://${OLLAMA_HOST}"
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_KEEP_ALIVE=10m

MODEL="gemma4:31b"
B="scripts/experimental/step67b_lane_aware_onepass_generic.py"
C="scripts/experimental/step67c_validate_lane_aware_drafts_generic.py"

RETRY_DIR="$(ls -1td data/work/cache/diagnostics/step67bc_think_retry2_input_* | head -n 1)"
LANES="$RETRY_DIR/retry2_lane_packets.jsonl"

RUN_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUNROOT="/beegfs2/scratch/aryp26yc/kc_l/step67bc_generic_gemma4_think_retry2_${SLURM_JOB_ID}_${RUN_STAMP}"
DIAG="data/work/cache/diagnostics/step67bc_generic_gemma4_think_retry2_${RUN_STAMP}"
DRAFT_ROOT="data/processed/step67_sidecar_lane_drafts_generic_retry/think_retry2"
VALID_ROOT="data/processed/step67_sidecar_lane_validated_generic_retry/think_retry2"

mkdir -p "$RUNROOT" "$DIAG" "$DRAFT_ROOT" "$VALID_ROOT" logs
export TMPDIR="$RUNROOT"

echo "===== job context ====="
date -u
hostname
echo "SLURM_JOB_ID=${SLURM_JOB_ID}"
echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-unset}"
echo "PY=$PY"
"$PY" --version
echo "OLLAMA_BIN=$OLLAMA_BIN"
echo "OLLAMA_MODELS=$OLLAMA_MODELS"
echo "OLLAMA_HOST=$OLLAMA_HOST"
echo "OLLAMA_BASE_URL=$OLLAMA_BASE_URL"
echo "MODEL=$MODEL"
echo "LANES=$LANES"
echo "DIAG=$DIAG"
echo "RUNROOT=$RUNROOT"

echo
echo "===== guards ====="
test -x "$OLLAMA_BIN" || { echo "FAIL: OLLAMA_BIN not executable: $OLLAMA_BIN"; exit 1; }
test -d "$OLLAMA_MODELS" || { echo "FAIL: OLLAMA_MODELS missing: $OLLAMA_MODELS"; exit 1; }
test -f "$LANES" || { echo "FAIL: LANES missing: $LANES"; exit 1; }

echo
echo "===== gpu ====="
nvidia-smi || true

echo
echo "===== compile generic B/C ====="
"$PY" -m py_compile "$B" "$C"

echo
echo "===== start Ollama server ====="
OLLAMA_LOG="logs/ollama-s67bc-g4-think-retry2-${SLURM_JOB_ID}.log"
"$OLLAMA_BIN" serve > "$OLLAMA_LOG" 2>&1 &
OLLAMA_PID=$!

cleanup() {
  status=$?
  echo
  echo "===== cleanup ====="
  echo "status=$status"
  if [ -n "${OLLAMA_PID:-}" ]; then
    kill "$OLLAMA_PID" >/dev/null 2>&1 || true
    wait "$OLLAMA_PID" >/dev/null 2>&1 || true
  fi
  exit "$status"
}
trap cleanup EXIT

echo
echo "===== wait for Ollama API ====="
READY=0
for i in $(seq 1 90); do
  if curl -fsS "http://${OLLAMA_HOST}/api/version" >/dev/null 2>&1; then
    READY=1
    echo "OLLAMA_READY_AFTER=$((i * 2))s"
    curl -sS "http://${OLLAMA_HOST}/api/version" || true
    break
  fi
  sleep 2
done

if [ "$READY" -ne 1 ]; then
  echo "FAIL: Ollama API did not become ready on ${OLLAMA_HOST}"
  tail -n 160 "$OLLAMA_LOG" || true
  exit 1
fi

echo
echo "===== model availability ====="
"$OLLAMA_BIN" list | tee "$DIAG/ollama_list.txt"
"$OLLAMA_BIN" list | grep -F "$MODEL" >/dev/null || { echo "FAIL: model not visible: $MODEL"; exit 1; }

echo
echo "===== run generic B, think retry2, num_predict 8192 ====="
set +e
"$PY" "$B" \
  --lanes "$LANES" \
  --out-root "$DRAFT_ROOT" \
  --model "$MODEL" \
  --base-url "$OLLAMA_BASE_URL" \
  --reasoning-mode think \
  --num-ctx 8192 \
  --num-predict 8192 \
  --temperature 0 \
  --timeout 1500 \
  --max-definition-items 4 \
  --max-scope-items 4 \
  --max-context-items 4 \
  --max-sibling-items 2 \
  --max-quote-chars 700 \
  --max-context-chars 1200
B_RC=$?
set -e
echo "B_RC=$B_RC"

DRAFT_DIR="$(ls -1td "$DRAFT_ROOT"/2026-* | head -n 1)"
DRAFTS="$DRAFT_DIR/onepass_drafts.jsonl"
echo "DRAFT_DIR=$DRAFT_DIR"
echo "DRAFTS=$DRAFTS"

echo
echo "===== validate generic C ====="
set +e
"$PY" "$C" \
  --lanes "$LANES" \
  --drafts "$DRAFTS" \
  --out-root "$VALID_ROOT"
C_RC=$?
set -e
echo "C_RC=$C_RC"

VALID_DIR="$(ls -1td "$VALID_ROOT"/2026-* | head -n 1)"
echo "VALID_DIR=$VALID_DIR"

cp "$DRAFT_DIR/summary.json" "$DIAG/draft_summary.json"
cp "$DRAFTS" "$DIAG/onepass_drafts.jsonl"
cp "$VALID_DIR/summary.json" "$DIAG/validation_summary.json"
cp "$VALID_DIR/validation_rows.jsonl" "$DIAG/validation_rows.jsonl"
cp "$VALID_DIR/review_snapshot.md" "$DIAG/review_snapshot.md"

cat > "$DIAG/run_paths.env" <<EOF
LANES=$LANES
DRAFT_DIR=$DRAFT_DIR
DRAFTS=$DRAFTS
VALID_DIR=$VALID_DIR
B_RC=$B_RC
C_RC=$C_RC
OLLAMA_LOG=$OLLAMA_LOG
EOF

echo
echo "===== draft summary ====="
cat "$DIAG/draft_summary.json"

echo
echo "===== validation summary ====="
cat "$DIAG/validation_summary.json"

echo
echo "===== drafts compact ====="
"$PY" - "$DRAFTS" <<'PY'
import json
import sys
from pathlib import Path

for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    row = json.loads(line)
    parsed = row.get("parsed") if isinstance(row.get("parsed"), dict) else {}
    print(json.dumps({
        "kc_id": row.get("kc_id"),
        "canonical_name": row.get("canonical_name"),
        "ok": row.get("ok"),
        "error": row.get("error"),
        "visible_content_len": row.get("visible_content_len"),
        "thinking_char_count": row.get("thinking_char_count"),
        "postprocess_notes": row.get("postprocess_notes"),
        "definition": parsed.get("definition"),
        "scope": parsed.get("scope"),
    }, indent=2, ensure_ascii=False))
PY

echo
echo "STEP67BC_GENERIC_GEMMA4_THINK_RETRY2_DONE"

if [ "$B_RC" -ne 0 ] || [ "$C_RC" -ne 0 ]; then
  echo "THINK_RETRY2_COMPLETED_WITH_ERRORS"
  exit 2
fi

echo "THINK_RETRY2_COMPLETED_CLEAN"
