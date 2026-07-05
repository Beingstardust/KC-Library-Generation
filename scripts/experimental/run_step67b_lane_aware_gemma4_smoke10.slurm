#!/bin/bash
#SBATCH --job-name=s67g4lane
#SBATCH --partition=gpu46GB
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=00:45:00
#SBATCH --output=logs/s67g4lane-%j.out
#SBATCH --error=logs/s67g4lane-%j.err

set -u

cd /beegfs1/home/aryp26yc/projects/kc_l_v2_clean || exit 1
mkdir -p logs

export PY=/home/aryp26yc/venvs/kc_l_v2/bin/python
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH=/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}

export OLLAMA_BIN=/beegfs1/home/aryp26yc/apps/ollama_upgrade_clean_20260425_214752/bin/ollama
export OLLAMA_MODELS=/beegfs2/scratch/aryp26yc/kc_l/ollama/models
export GEMMA_MODEL=gemma4:31b

PORT=$((32000 + SLURM_JOB_ID % 1000))
export OLLAMA_HOST=127.0.0.1:${PORT}
export OLLAMA_BASE_URL=http://127.0.0.1:${PORT}
export OLLAMA_FLASH_ATTENTION=true
export OLLAMA_KEEP_ALIVE=10m
export OLLAMA_NUM_PARALLEL=1

export CUDA_VISIBLE_DEVICES=0
export ROCR_VISIBLE_DEVICES=0
export GPU_DEVICE_ORDINAL=0

LANES="data/processed/step67_sidecar_lane_packets_v4/2026-04-28_155759/lane_packets.jsonl"

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
echo "LANES=$LANES"

echo
echo "==== guards ===="
test -x "$OLLAMA_BIN" || { echo "MISSING OLLAMA_BIN"; exit 10; }
test -s "$LANES" || { echo "MISSING LANES"; exit 11; }

echo
echo "==== start Ollama server ===="
"$OLLAMA_BIN" serve > "logs/ollama-s67g4lane-${SLURM_JOB_ID}.log" 2>&1 &
OLLAMA_PID=$!
echo "OLLAMA_PID=$OLLAMA_PID"

cleanup() {
  if kill -0 "$OLLAMA_PID" >/dev/null 2>&1; then
    kill "$OLLAMA_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

echo
echo "==== wait for Ollama API ===="
for i in $(seq 1 90); do
  if "$OLLAMA_BIN" list >/dev/null 2>&1; then
    echo "OLLAMA_READY_AFTER=${i}s"
    break
  fi
  sleep 1
done

"$OLLAMA_BIN" --version || true

echo
echo "==== model availability ===="
"$OLLAMA_BIN" list | sed -n '1,40p'

echo
echo "==== run lane-aware Gemma4 onepass, think=false ===="
set +e
"$PY" scripts/experimental/step67b_lane_aware_gemma4_onepass.py \
  --lanes "$LANES" \
  --model "$GEMMA_MODEL" \
  --base-url "$OLLAMA_BASE_URL" \
  --num-ctx 8192 \
  --num-predict 700 \
  --temperature 0 \
  --timeout 180
DRAFT_EXIT=$?
set -e

echo
echo "DRAFT_EXIT=$DRAFT_EXIT"

LATEST_DRAFT_DIR="$(ls -1td data/processed/step67_sidecar_lane_drafts/2026-* 2>/dev/null | head -n 1 || true)"
echo "LATEST_DRAFT_DIR=$LATEST_DRAFT_DIR"

if [ -n "$LATEST_DRAFT_DIR" ]; then
  DRAFTS="$LATEST_DRAFT_DIR/onepass_drafts.jsonl"
  echo "DRAFTS=$DRAFTS"

  echo
  echo "==== validate with existing deterministic validator ===="
  set +e
  "$PY" scripts/experimental/step67c_validate_onepass_drafts.py \
    --packets "$LANES" \
    --drafts "$DRAFTS"
  VALIDATION_EXIT=$?
  set -e
  echo "VALIDATION_EXIT=$VALIDATION_EXIT"

  echo
  echo "==== latest summaries ===="
  cat "$LATEST_DRAFT_DIR/summary.json" || true

  LATEST_VALIDATION_DIR="$(ls -1td data/processed/step67_sidecar_validated/2026-* 2>/dev/null | head -n 1 || true)"
  echo "LATEST_VALIDATION_DIR=$LATEST_VALIDATION_DIR"
  if [ -n "$LATEST_VALIDATION_DIR" ]; then
    cat "$LATEST_VALIDATION_DIR/summary.json" || true
    echo
    sed -n '1,240p' "$LATEST_VALIDATION_DIR/review_snapshot.md" || true
  fi

  echo
  echo "==== compact emitted rows ===="
  "$PY" - <<'PY'
import json
from pathlib import Path

latest = sorted(Path("data/processed/step67_sidecar_lane_drafts").glob("2026-*"))[-1]
p = latest / "onepass_drafts.jsonl"
rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]

for r in rows:
    parsed = r.get("parsed") if isinstance(r.get("parsed"), dict) else {}
    d = parsed.get("definition") if isinstance(parsed.get("definition"), dict) else {}
    s = parsed.get("scope") if isinstance(parsed.get("scope"), dict) else {}
    print()
    print("KC:", r.get("kc_id"), "|", r.get("canonical_name"))
    print("ok:", r.get("ok"), "error:", r.get("error"))
    print("visible_len:", r.get("visible_content_len"), "thinking_chars:", r.get("thinking_char_count"))
    print("definition:", d.get("status"), "|", d.get("text"))
    print("definition_support:", d.get("supporting_evidence_ids"))
    print("scope:", s.get("status"), "|", s.get("text"))
    print("scope_support:", s.get("supporting_evidence_ids"))
PY
fi

echo
echo "==== Ollama tail ===="
tail -n 120 "logs/ollama-s67g4lane-${SLURM_JOB_ID}.log" || true

echo
echo "STEP67_GEMMA4_LANE_AWARE_SMOKE10_JOB_DONE"

exit 0
