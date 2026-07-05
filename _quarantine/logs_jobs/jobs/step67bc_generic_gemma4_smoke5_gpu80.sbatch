#!/bin/bash
#SBATCH --job-name=s67bc_g4_sm5
#SBATCH --partition=gpu80GB
#SBATCH --gres=gpu:a100:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=01:30:00
#SBATCH --output=logs/s67bc_g4_sm5_%j.out
#SBATCH --error=logs/s67bc_g4_sm5_%j.err

set -euo pipefail

REPO=/beegfs1/home/aryp26yc/projects/kc_l_v2_clean
PY=/home/aryp26yc/venvs/kc_l_v2/bin/python

cd "$REPO" || exit 1

export PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

export OLLAMA_BIN=/beegfs1/home/aryp26yc/apps/ollama_upgrade_clean_20260425_214752/bin/ollama
export OLLAMA_MODELS=/beegfs2/scratch/aryp26yc/kc_l/ollama/models
export OLLAMA_HOST="127.0.0.1:$((26000 + SLURM_JOB_ID % 20000))"
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
RUNROOT="/beegfs2/scratch/aryp26yc/kc_l/step67bc_generic_gemma4_smoke5_${SLURM_JOB_ID}_${RUN_STAMP}"
DIAG="data/work/cache/diagnostics/step67bc_generic_gemma4_smoke5_${RUN_STAMP}"
DRAFT_ROOT="data/processed/step67_sidecar_lane_drafts_generic_smoke"
VALID_ROOT="data/processed/step67_sidecar_lane_validated_generic_smoke"

mkdir -p "$RUNROOT" "$DIAG" "$DRAFT_ROOT" "$VALID_ROOT" logs
export TMPDIR="$RUNROOT"

echo "===== job context ====="
date -u
hostname
echo "SLURM_JOB_ID=${SLURM_JOB_ID}"
echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-unset}"
echo "REPO=$REPO"
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
OLLAMA_LOG="logs/ollama-s67bc-g4-smoke5-${SLURM_JOB_ID}.log"
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
echo "===== direct chat sanity, nothink ====="
"$PY" - <<'PY'
import json
import os
import urllib.request

host = os.environ["OLLAMA_HOST"]
model = "gemma4:31b"
body = {
    "model": model,
    "messages": [
        {"role": "system", "content": "Return only valid JSON."},
        {"role": "user", "content": "Return exactly this JSON object: {\"ok\": true}"}
    ],
    "stream": False,
    "think": False,
    "options": {"temperature": 0, "num_predict": 40, "num_ctx": 2048},
}
req = urllib.request.Request(
    f"http://{host}/api/chat",
    data=json.dumps(body).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=120) as resp:
    obj = json.loads(resp.read().decode("utf-8", errors="replace"))
print(json.dumps({
    "done": obj.get("done"),
    "message_content": (obj.get("message") or {}).get("content"),
    "thinking_len": len((obj.get("message") or {}).get("thinking") or ""),
}, ensure_ascii=False))
PY

echo
echo "===== direct chat sanity, think ====="
"$PY" - <<'PY'
import json
import os
import urllib.request

host = os.environ["OLLAMA_HOST"]
model = "gemma4:31b"
body = {
    "model": model,
    "messages": [
        {"role": "system", "content": "Return only valid JSON in the visible answer."},
        {"role": "user", "content": "Return exactly this JSON object in the visible answer: {\"ok\": true}"}
    ],
    "stream": False,
    "think": True,
    "options": {"temperature": 0, "num_predict": 120, "num_ctx": 2048},
}
req = urllib.request.Request(
    f"http://{host}/api/chat",
    data=json.dumps(body).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=180) as resp:
    obj = json.loads(resp.read().decode("utf-8", errors="replace"))
print(json.dumps({
    "done": obj.get("done"),
    "done_reason": obj.get("done_reason"),
    "message_content": (obj.get("message") or {}).get("content"),
    "content_len": len((obj.get("message") or {}).get("content") or ""),
    "thinking_len": len((obj.get("message") or {}).get("thinking") or ""),
}, ensure_ascii=False))
PY

echo
echo "===== run generic B, nothink, limit 5 ====="
set +e
"$PY" "$B" \
  --lanes "$LANES" \
  --out-root "$DRAFT_ROOT/nothink" \
  --model "$MODEL" \
  --base-url "$OLLAMA_BASE_URL" \
  --reasoning-mode nothink \
  --num-ctx 8192 \
  --num-predict 900 \
  --temperature 0 \
  --timeout 300 \
  --limit 5 \
  --max-definition-items 4 \
  --max-scope-items 4 \
  --max-context-items 4 \
  --max-sibling-items 2 \
  --max-quote-chars 700 \
  --max-context-chars 1200
B_NOTHINK_RC=$?
set -e
echo "B_NOTHINK_RC=$B_NOTHINK_RC"

NOTHINK_DRAFT_DIR="$(ls -1td "$DRAFT_ROOT/nothink"/2026-* | head -n 1)"
NOTHINK_DRAFTS="$NOTHINK_DRAFT_DIR/onepass_drafts.jsonl"
echo "NOTHINK_DRAFT_DIR=$NOTHINK_DRAFT_DIR"
echo "NOTHINK_DRAFTS=$NOTHINK_DRAFTS"

echo
echo "===== validate generic C, nothink ====="
set +e
"$PY" "$C" \
  --lanes "$LANES" \
  --drafts "$NOTHINK_DRAFTS" \
  --out-root "$VALID_ROOT/nothink"
C_NOTHINK_RC=$?
set -e
echo "C_NOTHINK_RC=$C_NOTHINK_RC"

NOTHINK_VALID_DIR="$(ls -1td "$VALID_ROOT/nothink"/2026-* | head -n 1)"
echo "NOTHINK_VALID_DIR=$NOTHINK_VALID_DIR"

echo
echo "===== run generic B, think, limit 5 ====="
set +e
"$PY" "$B" \
  --lanes "$LANES" \
  --out-root "$DRAFT_ROOT/think" \
  --model "$MODEL" \
  --base-url "$OLLAMA_BASE_URL" \
  --reasoning-mode think \
  --num-ctx 8192 \
  --num-predict 1400 \
  --temperature 0 \
  --timeout 420 \
  --limit 5 \
  --max-definition-items 4 \
  --max-scope-items 4 \
  --max-context-items 4 \
  --max-sibling-items 2 \
  --max-quote-chars 700 \
  --max-context-chars 1200
B_THINK_RC=$?
set -e
echo "B_THINK_RC=$B_THINK_RC"

THINK_DRAFT_DIR="$(ls -1td "$DRAFT_ROOT/think"/2026-* | head -n 1)"
THINK_DRAFTS="$THINK_DRAFT_DIR/onepass_drafts.jsonl"
echo "THINK_DRAFT_DIR=$THINK_DRAFT_DIR"
echo "THINK_DRAFTS=$THINK_DRAFTS"

echo
echo "===== validate generic C, think ====="
set +e
"$PY" "$C" \
  --lanes "$LANES" \
  --drafts "$THINK_DRAFTS" \
  --out-root "$VALID_ROOT/think"
C_THINK_RC=$?
set -e
echo "C_THINK_RC=$C_THINK_RC"

THINK_VALID_DIR="$(ls -1td "$VALID_ROOT/think"/2026-* | head -n 1)"
echo "THINK_VALID_DIR=$THINK_VALID_DIR"

echo
echo "===== collect summaries ====="
cp "$NOTHINK_DRAFT_DIR/summary.json" "$DIAG/nothink_draft_summary.json"
cp "$THINK_DRAFT_DIR/summary.json" "$DIAG/think_draft_summary.json"
cp "$NOTHINK_VALID_DIR/summary.json" "$DIAG/nothink_validation_summary.json"
cp "$THINK_VALID_DIR/summary.json" "$DIAG/think_validation_summary.json"
cp "$NOTHINK_VALID_DIR/review_snapshot.md" "$DIAG/nothink_review_snapshot.md"
cp "$THINK_VALID_DIR/review_snapshot.md" "$DIAG/think_review_snapshot.md"

cat > "$DIAG/run_paths.env" <<EOF
LANES=$LANES
NOTHINK_DRAFT_DIR=$NOTHINK_DRAFT_DIR
NOTHINK_DRAFTS=$NOTHINK_DRAFTS
NOTHINK_VALID_DIR=$NOTHINK_VALID_DIR
THINK_DRAFT_DIR=$THINK_DRAFT_DIR
THINK_DRAFTS=$THINK_DRAFTS
THINK_VALID_DIR=$THINK_VALID_DIR
B_NOTHINK_RC=$B_NOTHINK_RC
C_NOTHINK_RC=$C_NOTHINK_RC
B_THINK_RC=$B_THINK_RC
C_THINK_RC=$C_THINK_RC
OLLAMA_LOG=$OLLAMA_LOG
EOF

echo
echo "===== nothink draft summary ====="
cat "$DIAG/nothink_draft_summary.json"

echo
echo "===== nothink validation summary ====="
cat "$DIAG/nothink_validation_summary.json"

echo
echo "===== think draft summary ====="
cat "$DIAG/think_draft_summary.json"

echo
echo "===== think validation summary ====="
cat "$DIAG/think_validation_summary.json"

echo
echo "===== package smoke outputs ====="
RETURN="/beegfs2/scratch/aryp26yc/kc_l/sync_bundles/step67bc_generic_gemma4_smoke5_${SLURM_JOB_ID}_${RUN_STAMP}.tar.gz"
tar -czf "$RETURN" \
  "$DIAG" \
  "$NOTHINK_DRAFT_DIR" \
  "$NOTHINK_VALID_DIR" \
  "$THINK_DRAFT_DIR" \
  "$THINK_VALID_DIR" \
  "$OLLAMA_LOG" \
  "logs/s67bc_g4_sm5_${SLURM_JOB_ID}.out" \
  "logs/s67bc_g4_sm5_${SLURM_JOB_ID}.err" 2>/dev/null || true

echo "RETURN=$RETURN"
ls -lh "$RETURN" || true

echo
echo "STEP67BC_GENERIC_GEMMA4_SMOKE5_DONE"

if [ "$B_NOTHINK_RC" -ne 0 ] || [ "$C_NOTHINK_RC" -ne 0 ] || [ "$B_THINK_RC" -ne 0 ] || [ "$C_THINK_RC" -ne 0 ]; then
  echo "SMOKE_COMPLETED_WITH_ERRORS"
  exit 2
fi

echo "SMOKE_COMPLETED_CLEAN"
