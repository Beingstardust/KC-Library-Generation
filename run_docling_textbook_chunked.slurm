#!/bin/bash
#SBATCH -J kc_docling_chunked
#SBATCH -p big
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --time=23:59:00
#SBATCH -o /path/to/scratch/kc_l/slurm_logs/%x_%j.out
#SBATCH -e /path/to/scratch/kc_l/slurm_logs/%x_%j.err

set -euo pipefail

unset PROMPT_COMMAND || true
source ~/kc_l_v2_env.sh

REPO=/path/to/projects/kc_l_v2_clean
cd "$REPO"

export PYTHONPATH="$REPO/src"
export LD_LIBRARY_PATH="/path/to/software/rh8/usr/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export HF_HOME=/path/to/scratch/kc_l/cache/hf
export XDG_CACHE_HOME=/path/to/scratch/kc_l/cache/xdg
unset TRANSFORMERS_CACHE || true

DOCLING_BIN=/path/to/venvs/docling_cli/bin/docling
DOCLING_PY=/path/to/venvs/docling_cli/bin/python
CHUNK_PY=/path/to/venvs/mineru_cli/bin/python

PDF="$REPO/data/input/course_materials/introduction-to-data-mining-.pdf"

RUN_ID=$(date +"%Y-%m-%d_%H%M%S")
RUN_BASE="/path/to/scratch/kc_l/docling_chunked_runs/$RUN_ID"

CHUNK_DIR="$RUN_BASE/chunks"
OUT_DIR="$RUN_BASE/docling"
LOG_DIR="$RUN_BASE/logs"
MANIFEST_DIR="$RUN_BASE/manifests"

mkdir -p "$CHUNK_DIR" "$OUT_DIR" "$LOG_DIR" "$MANIFEST_DIR"

{
  echo "RUN_ID=$RUN_ID"
  echo "HOSTNAME=$(hostname)"
  echo "PWD=$(pwd)"
  echo "PDF=$PDF"
  echo "PYTHONPATH=$PYTHONPATH"
  echo "LD_LIBRARY_PATH=$LD_LIBRARY_PATH"
  echo "HF_HOME=$HF_HOME"
  echo "XDG_CACHE_HOME=$XDG_CACHE_HOME"
} | tee "$LOG_DIR/run_meta.txt"

"$DOCLING_PY" -m pip freeze > "$LOG_DIR/docling_pip_freeze.txt"
"$DOCLING_PY" -m pip show docling torch torchvision transformers huggingface-hub > "$LOG_DIR/docling_pip_show.txt" 2>&1 || true

echo "===== CHUNKING START =====" | tee "$LOG_DIR/chunking.log"
"$CHUNK_PY" scripts/local/chunk_pdf_for_docling.py \
  --input-pdf "$PDF" \
  --output-dir "$CHUNK_DIR" \
  --pages-per-chunk 100 \
  | tee -a "$LOG_DIR/chunking.log"

test -f "$CHUNK_DIR/chunk_manifest.json"
cp "$CHUNK_DIR/chunk_manifest.json" "$MANIFEST_DIR/chunk_manifest.json"

echo "===== BUILD CHUNK LIST =====" | tee "$LOG_DIR/chunk_list_build.log"
MANIFEST_JSON="$MANIFEST_DIR/chunk_manifest.json" "$CHUNK_PY" - <<'PY' > "$MANIFEST_DIR/chunk_list.tsv"
import json
import os
from pathlib import Path

manifest_path = Path(os.environ["MANIFEST_JSON"])
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

for ch in manifest["chunks"]:
    print(f"{ch['chunk_index']}\t{ch['chunk_pdf']}\t{ch['expected_docling_json']}")
PY

test -s "$MANIFEST_DIR/chunk_list.tsv"

FAIL=0
: > "$LOG_DIR/docling_chunked_status.txt"

echo "===== DOCLING CHUNKED START =====" | tee "$LOG_DIR/docling_chunked.log"



while IFS=$'\t' read -r chunk_index chunk_pdf expected_json_name; do
  [ -n "$chunk_pdf" ] || continue

  chunk_base=$(basename "$chunk_pdf")
  expected_json="$OUT_DIR/$expected_json_name"

  echo "" | tee -a "$LOG_DIR/docling_chunked.log"
  echo "### CHUNK $chunk_index :: $chunk_base" | tee -a "$LOG_DIR/docling_chunked.log"

  if "$DOCLING_BIN" \
      --to json \
      --output "$OUT_DIR" \
      --pipeline standard \
      --pdf-backend docling_parse \
      --no-ocr \
      --tables \
      --no-abort-on-error \
      --no-show-layout \
      --artifacts-path /path/to/scratch/kc_l/docling_hf_models \
      "$chunk_pdf" \
      >> "$LOG_DIR/docling_chunked.log" 2>&1
  then
    if [ -f "$expected_json" ]; then
      echo "OK :: $chunk_base" | tee -a "$LOG_DIR/docling_chunked_status.txt"
    else
      echo "FAIL :: $chunk_base :: docling exited 0 but no output JSON found" | tee -a "$LOG_DIR/docling_chunked_status.txt"
      FAIL=1
    fi
  else
    echo "FAIL :: $chunk_base :: docling returned non-zero" | tee -a "$LOG_DIR/docling_chunked_status.txt"
    FAIL=1
  fi
done < "$MANIFEST_DIR/chunk_list.tsv"

find "$OUT_DIR" -type f | sort > "$MANIFEST_DIR/docling_chunked_outputs.txt"

echo "RUN_BASE=$RUN_BASE" | tee -a "$LOG_DIR/run_meta.txt"
echo "FINAL_FAIL_FLAG=$FAIL" | tee -a "$LOG_DIR/run_meta.txt"

exit "$FAIL"
