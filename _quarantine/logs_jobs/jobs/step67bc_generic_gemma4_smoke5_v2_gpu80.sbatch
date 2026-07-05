#!/bin/bash
#SBATCH --job-name=s67bc_g4_sm5v2
#SBATCH --partition=gpu80GB
#SBATCH --gres=gpu:a100:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=01:45:00
#SBATCH --output=logs/s67bc_g4_sm5v2_%j.out
#SBATCH --error=logs/s67bc_g4_sm5v2_%j.err

set -euo pipefail

REPO=/beegfs1/home/aryp26yc/projects/kc_l_v2_clean
PY=/home/aryp26yc/venvs/kc_l_v2/bin/python

cd "$REPO" || exit 1

export PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

export OLLAMA_BIN=/beegfs1/home/aryp26yc/apps/ollama_upgrade_clean_20260425_214752/bin/ollama
export OLLAMA_MODELS=/beegfs2/scratch/aryp26yc/kc_l/ollama/models
export OLLAMA_HOST="127.0.0.1:$((28000 + SLURM_JOB_ID % 20000))"
export OLLAMA_BASE_URL="http://${OLLAMA_HOST}"
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_KEEP_ALIVE=10m

MODEL="gemma4:31b"
B="scripts/experimental/step67b_lane_aware_onepass_generic.py"
C="scripts/experimental/step67c_validate_lane_aware_drafts_generic.py"

V2_REPLAY_DIR="$(ls -1td data/work/cache/diagnostics/step67_generic_lane_policy_v2_sofja_replay/2026-* | head -n 1)"
LANES="$V2_REPLAY_DIR/lane_packets.jsonl"

RUN_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUNROOT="/beegfs2/scratch/aryp26yc/kc_l/step67bc_generic_gemma4_smoke5_v2_${SLURM_JOB_ID}_${RUN_STAMP}"
DIAG="data/work/cache/diagnostics/step67bc_generic_gemma4_smoke5_v2_${RUN_STAMP}"
DRAFT_ROOT="data/processed/step67_sidecar_lane_drafts_generic_smoke_v2"
VALID_ROOT="data/processed/step67_sidecar_lane_validated_generic_smoke_v2"

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
OLLAMA_LOG="logs/ollama-s67bc-g4-smoke5v2-${SLURM_JOB_ID}.log"
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

run_mode () {
  MODE="$1"
  NUM_PREDICT="$2"
  TIMEOUT="$3"

  echo
  echo "===== run generic B, mode=${MODE}, limit 5 ====="

  set +e
  "$PY" "$B" \
    --lanes "$LANES" \
    --out-root "$DRAFT_ROOT/$MODE" \
    --model "$MODEL" \
    --base-url "$OLLAMA_BASE_URL" \
    --reasoning-mode "$MODE" \
    --num-ctx 8192 \
    --num-predict "$NUM_PREDICT" \
    --temperature 0 \
    --timeout "$TIMEOUT" \
    --limit 5 \
    --max-definition-items 4 \
    --max-scope-items 4 \
    --max-context-items 4 \
    --max-sibling-items 2 \
    --max-quote-chars 700 \
    --max-context-chars 1200
  B_RC=$?
  set -e

  echo "B_${MODE}_RC=$B_RC"

  DRAFT_DIR="$(ls -1td "$DRAFT_ROOT/$MODE"/2026-* | head -n 1)"
  DRAFTS="$DRAFT_DIR/onepass_drafts.jsonl"

  echo "${MODE}_DRAFT_DIR=$DRAFT_DIR"
  echo "${MODE}_DRAFTS=$DRAFTS"

  echo
  echo "===== validate generic C, mode=${MODE} ====="

  set +e
  "$PY" "$C" \
    --lanes "$LANES" \
    --drafts "$DRAFTS" \
    --out-root "$VALID_ROOT/$MODE"
  C_RC=$?
  set -e

  echo "C_${MODE}_RC=$C_RC"

  VALID_DIR="$(ls -1td "$VALID_ROOT/$MODE"/2026-* | head -n 1)"
  echo "${MODE}_VALID_DIR=$VALID_DIR"

  cp "$DRAFT_DIR/summary.json" "$DIAG/${MODE}_draft_summary.json"
  cp "$VALID_DIR/summary.json" "$DIAG/${MODE}_validation_summary.json"
  cp "$VALID_DIR/validation_rows.jsonl" "$DIAG/${MODE}_validation_rows.jsonl"
  cp "$VALID_DIR/review_snapshot.md" "$DIAG/${MODE}_review_snapshot.md"

  cat > "$DIAG/${MODE}_paths.env" <<EOF
MODE=$MODE
DRAFT_DIR=$DRAFT_DIR
DRAFTS=$DRAFTS
VALID_DIR=$VALID_DIR
B_RC=$B_RC
C_RC=$C_RC
EOF

  echo
  echo "===== ${MODE} draft summary ====="
  cat "$DIAG/${MODE}_draft_summary.json"

  echo
  echo "===== ${MODE} validation summary ====="
  cat "$DIAG/${MODE}_validation_summary.json"

  echo
  echo "===== ${MODE} problem rows if any ====="
  "$PY" - "$VALID_DIR/validation_rows.jsonl" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
for line in path.read_text(encoding="utf-8").splitlines():
    row = json.loads(line)
    if row.get("errors") or row.get("warnings"):
        print(json.dumps({
            "kc_id": row.get("kc_id"),
            "canonical_name": row.get("canonical_name"),
            "definition_status": row.get("definition_status"),
            "definition_grounding_mode": row.get("definition_grounding_mode"),
            "definition_text": row.get("definition_text"),
            "definition_supporting_evidence_ids": row.get("definition_supporting_evidence_ids"),
            "definition_supporting_lanes": row.get("definition_supporting_lanes"),
            "scope_status": row.get("scope_status"),
            "scope_grounding_mode": row.get("scope_grounding_mode"),
            "scope_text": row.get("scope_text"),
            "scope_supporting_evidence_ids": row.get("scope_supporting_evidence_ids"),
            "scope_supporting_lanes": row.get("scope_supporting_lanes"),
            "errors": row.get("errors"),
            "warnings": row.get("warnings"),
        }, indent=2, ensure_ascii=False))
PY

  echo "$B_RC" > "$DIAG/${MODE}_B_RC.txt"
  echo "$C_RC" > "$DIAG/${MODE}_C_RC.txt"
}

run_mode nothink 1000 300
run_mode think 4096 900

NOTHINK_B_RC="$(cat "$DIAG/nothink_B_RC.txt")"
NOTHINK_C_RC="$(cat "$DIAG/nothink_C_RC.txt")"
THINK_B_RC="$(cat "$DIAG/think_B_RC.txt")"
THINK_C_RC="$(cat "$DIAG/think_C_RC.txt")"

echo
echo "===== package smoke outputs ====="
RETURN="/beegfs2/scratch/aryp26yc/kc_l/sync_bundles/step67bc_generic_gemma4_smoke5_v2_${SLURM_JOB_ID}_${RUN_STAMP}.tar.gz"
tar -czf "$RETURN" \
  "$DIAG" \
  "$DRAFT_ROOT" \
  "$VALID_ROOT" \
  "$OLLAMA_LOG" \
  "logs/s67bc_g4_sm5v2_${SLURM_JOB_ID}.out" \
  "logs/s67bc_g4_sm5v2_${SLURM_JOB_ID}.err" 2>/dev/null || true

echo "RETURN=$RETURN"
ls -lh "$RETURN" || true

echo
echo "STEP67BC_GENERIC_GEMMA4_SMOKE5_V2_DONE"

if [ "$NOTHINK_B_RC" -ne 0 ] || [ "$NOTHINK_C_RC" -ne 0 ] || [ "$THINK_B_RC" -ne 0 ] || [ "$THINK_C_RC" -ne 0 ]; then
  echo "SMOKE_V2_COMPLETED_WITH_ERRORS"
  exit 2
fi

echo "SMOKE_V2_COMPLETED_CLEAN"
