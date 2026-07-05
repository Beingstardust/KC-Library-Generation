#!/bin/bash
#SBATCH --job-name=s67g4resc
#SBATCH --partition=gpu46GB
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=01:00:00
#SBATCH --output=logs/s67g4resc-%j.out
#SBATCH --error=logs/s67g4resc-%j.err

set -euo pipefail

cd /beegfs1/home/aryp26yc/projects/kc_l_v2_clean

export PY=/home/aryp26yc/venvs/kc_l_v2/bin/python
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH=/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}

export OLLAMA_BIN=/beegfs1/home/aryp26yc/apps/ollama_upgrade_clean_20260425_214752/bin/ollama
export OLLAMA_MODELS=/beegfs2/scratch/aryp26yc/kc_l/ollama/models

PORT=$((27000 + SLURM_JOB_ID % 10000))
export OLLAMA_HOST="127.0.0.1:${PORT}"
export OLLAMA_BASE_URL="http://${OLLAMA_HOST}"
export GEMMA_MODEL="gemma4:31b"

export CUDA_VISIBLE_DEVICES=0
export GPU_DEVICE_ORDINAL=0
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_KEEP_ALIVE=10m
export OLLAMA_FLASH_ATTENTION=true

PACKETS="${PACKETS:?PACKETS env var required}"
PREV_DRAFTS="${PREV_DRAFTS:?PREV_DRAFTS env var required}"

echo "==== job context ===="
date
hostname
echo "PWD=$PWD"
echo "PY=$PY"
"$PY" --version
echo "OLLAMA_BIN=$OLLAMA_BIN"
echo "OLLAMA_MODELS=$OLLAMA_MODELS"
echo "OLLAMA_HOST=$OLLAMA_HOST"
echo "OLLAMA_BASE_URL=$OLLAMA_BASE_URL"
echo "GEMMA_MODEL=$GEMMA_MODEL"
echo "PACKETS=$PACKETS"
echo "PREV_DRAFTS=$PREV_DRAFTS"

echo
echo "==== guards ===="
test -x "$OLLAMA_BIN" || { echo "MISSING executable OLLAMA_BIN=$OLLAMA_BIN"; exit 1; }
test -f "$PACKETS" || { echo "MISSING PACKETS=$PACKETS"; exit 1; }
test -f "$PREV_DRAFTS" || { echo "MISSING PREV_DRAFTS=$PREV_DRAFTS"; exit 1; }
test -f scripts/experimental/step67b_rescue_failed_no_think.py || exit 1
test -f scripts/experimental/step67c_validate_onepass_drafts.py || exit 1

echo
echo "==== start Ollama server ===="
"$OLLAMA_BIN" serve \
  > "logs/ollama-s67g4resc-${SLURM_JOB_ID}.out" \
  2> "logs/ollama-s67g4resc-${SLURM_JOB_ID}.err" &
OLLAMA_PID=$!
echo "OLLAMA_PID=$OLLAMA_PID"

cleanup() {
  kill "$OLLAMA_PID" 2>/dev/null || true
}
trap cleanup EXIT

echo
echo "==== wait for Ollama API ===="
for i in $(seq 1 120); do
  if curl -fsS "${OLLAMA_BASE_URL}/api/version" >/tmp/ollama_version_${SLURM_JOB_ID}.json 2>/dev/null; then
    echo "OLLAMA_READY_AFTER=${i}s"
    cat /tmp/ollama_version_${SLURM_JOB_ID}.json
    echo
    break
  fi

  sleep 1

  if [ "$i" -eq 120 ]; then
    echo "FAIL: Ollama did not become ready"
    exit 1
  fi
done

echo
echo "==== model availability ===="
"$OLLAMA_BIN" list
"$OLLAMA_BIN" list | grep -F "$GEMMA_MODEL" || { echo "FAIL: $GEMMA_MODEL not found"; exit 1; }

echo
echo "==== run rescue pass, failed rows only, think=false ===="
set +e
"$PY" scripts/experimental/step67b_rescue_failed_no_think.py \
  --packets "$PACKETS" \
  --previous-drafts "$PREV_DRAFTS" \
  --base-url "$OLLAMA_BASE_URL" \
  --model "$GEMMA_MODEL" \
  --timeout 180 \
  --num-ctx 8192 \
  --num-predict 600 \
  --temperature 0.0
RESCUE_EXIT=$?
set -e

LATEST_RESCUE_DIR="$(ls -1td data/processed/step67_sidecar_rescued_drafts/2026-* | head -n 1)"
DRAFTS="$LATEST_RESCUE_DIR/onepass_drafts.jsonl"

echo
echo "RESCUE_EXIT=$RESCUE_EXIT"
echo "LATEST_RESCUE_DIR=$LATEST_RESCUE_DIR"
echo "DRAFTS=$DRAFTS"

test -f "$DRAFTS" || { echo "FAIL: no rescued drafts emitted"; exit 1; }

echo
echo "==== run deterministic validation over rescued merged rows ===="
set +e
"$PY" scripts/experimental/step67c_validate_onepass_drafts.py \
  --packets "$PACKETS" \
  --drafts "$DRAFTS"
VALIDATION_EXIT=$?
set -e

LATEST_VALIDATION_DIR="$(ls -1td data/processed/step67_sidecar_validated/2026-* | head -n 1)"

echo
echo "VALIDATION_EXIT=$VALIDATION_EXIT"
echo "LATEST_VALIDATION_DIR=$LATEST_VALIDATION_DIR"

echo
echo "==== rescue summary ===="
cat "$LATEST_RESCUE_DIR/summary.json" || true

echo
echo "==== validation summary ===="
cat "$LATEST_VALIDATION_DIR/summary.json" || true

echo
echo "==== validation snapshot ===="
sed -n '1,360p' "$LATEST_VALIDATION_DIR/review_snapshot.md" || true

echo
echo "==== rescued draft rows compact ===="
"$PY" - <<PY
import json
from pathlib import Path

p = Path("$DRAFTS")
for line in p.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    r = json.loads(line)
    parsed = r.get("parsed") or {}
    d = parsed.get("definition") if isinstance(parsed, dict) else {}
    s = parsed.get("scope") if isinstance(parsed, dict) else {}
    print()
    print("KC:", r.get("kc_id"), "|", r.get("canonical_name"))
    print("ok:", r.get("ok"), "source:", r.get("final_source"), "stage:", r.get("rescue_stage"), "error:", r.get("error"))
    print("visible_len:", r.get("visible_content_len"), "thinking_chars:", r.get("thinking_char_count"))
    print("definition:", (d or {}).get("status"), "|", (d or {}).get("text"))
    print("scope:", (s or {}).get("status"), "|", (s or {}).get("text"))
PY

echo
echo "==== Ollama tail ===="
tail -n 80 "logs/ollama-s67g4resc-${SLURM_JOB_ID}.out" || true
tail -n 120 "logs/ollama-s67g4resc-${SLURM_JOB_ID}.err" || true

echo
echo "STEP67_GEMMA4_SIDECAR_SMOKE10_RESCUE_NO_THINK_JOB_DONE"

exit 0
