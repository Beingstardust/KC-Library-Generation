#!/bin/bash
#SBATCH -J kc_extract_real
#SBATCH -p big
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --time=23:59:00
#SBATCH -o /beegfs2/scratch/aryp26yc/kc_l/slurm_logs/%x_%j.out
#SBATCH -e /beegfs2/scratch/aryp26yc/kc_l/slurm_logs/%x_%j.err

set -u

unset PROMPT_COMMAND || true
source ~/kc_l_v2_env.sh

REPO=/beegfs1/home/aryp26yc/projects/kc_l_v2_clean
cd "$REPO"

export PYTHONPATH="$REPO/src"
export LD_LIBRARY_PATH="/beegfs1/software/rh8/usr/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export MINERU_TOOLS_CONFIG_JSON=/beegfs2/scratch/aryp26yc/kc_l/config/mineru_local.json
export MINERU_MODEL_SOURCE=local
export HF_HOME=/beegfs2/scratch/aryp26yc/kc_l/cache/hf
export XDG_CACHE_HOME=/beegfs2/scratch/aryp26yc/kc_l/cache/xdg
unset TRANSFORMERS_CACHE || true

MINERU_PY=/home/aryp26yc/venvs/mineru_cli/bin/python
DOCLING_BIN=/home/aryp26yc/venvs/docling_cli/bin/docling
INPUT_DIR="$REPO/data/input/course_materials"

RUN_ID=$(date +"%Y-%m-%d_%H%M%S")
RUN_BASE="/beegfs2/scratch/aryp26yc/kc_l/extraction_runs/$RUN_ID"

mkdir -p \
  "$RUN_BASE/manifests" \
  "$RUN_BASE/logs" \
  "$RUN_BASE/mineru" \
  "$RUN_BASE/docling"

echo "RUN_ID=$RUN_ID" | tee "$RUN_BASE/logs/run_meta.txt"
echo "HOSTNAME=$(hostname)" | tee -a "$RUN_BASE/logs/run_meta.txt"
echo "PWD=$(pwd)" | tee -a "$RUN_BASE/logs/run_meta.txt"
echo "INPUT_DIR=$INPUT_DIR" | tee -a "$RUN_BASE/logs/run_meta.txt"
echo "MINERU_TOOLS_CONFIG_JSON=$MINERU_TOOLS_CONFIG_JSON" | tee -a "$RUN_BASE/logs/run_meta.txt"
echo "MINERU_MODEL_SOURCE=$MINERU_MODEL_SOURCE" | tee -a "$RUN_BASE/logs/run_meta.txt"
echo "PYTHONPATH=$PYTHONPATH" | tee -a "$RUN_BASE/logs/run_meta.txt"
echo "LD_LIBRARY_PATH=$LD_LIBRARY_PATH" | tee -a "$RUN_BASE/logs/run_meta.txt"

"$MINERU_PY" -m pip freeze > "$RUN_BASE/logs/mineru_pip_freeze.txt"
"$MINERU_PY" -m pip show \
  mineru torch torchvision transformers huggingface-hub \
  albumentations albucore tokenizers safetensors omegaconf \
  ftfy shapely pyclipper regex wcwidth \
  > "$RUN_BASE/logs/mineru_pip_show.txt" 2>&1 || true

find "$INPUT_DIR" -maxdepth 1 -type f -iname '*.pdf' | sort > "$RUN_BASE/manifests/input_pdfs.txt"
PDF_COUNT=$(wc -l < "$RUN_BASE/manifests/input_pdfs.txt")
echo "PDF_COUNT=$PDF_COUNT" | tee -a "$RUN_BASE/logs/run_meta.txt"

if [ "$PDF_COUNT" -eq 0 ]; then
  echo "No PDF files found in $INPUT_DIR" | tee -a "$RUN_BASE/logs/run_meta.txt"
  exit 1
fi

FAIL=0

echo "===== MINERU START =====" | tee "$RUN_BASE/logs/mineru_run.log"
while IFS= read -r pdf; do
  [ -n "$pdf" ] || continue
  base=$(basename "$pdf")
  echo "" | tee -a "$RUN_BASE/logs/mineru_run.log"
  echo "### MINERU :: $base" | tee -a "$RUN_BASE/logs/mineru_run.log"

  if mineru \
      --path "$pdf" \
      --output "$RUN_BASE/mineru" \
      --backend pipeline \
      --method auto \
      --formula true \
      --table true \
      >> "$RUN_BASE/logs/mineru_run.log" 2>&1; then
    echo "OK :: $base" | tee -a "$RUN_BASE/logs/mineru_status.txt"
  else
    echo "FAIL :: $base" | tee -a "$RUN_BASE/logs/mineru_status.txt"
    FAIL=1
  fi
done < "$RUN_BASE/manifests/input_pdfs.txt"

find "$RUN_BASE/mineru" -type f | sort > "$RUN_BASE/manifests/mineru_outputs.txt"

echo "===== DOCLING START =====" | tee "$RUN_BASE/logs/docling_run.log"
while IFS= read -r pdf; do
  [ -n "$pdf" ] || continue
  base=$(basename "$pdf")
  echo "" | tee -a "$RUN_BASE/logs/docling_run.log"
  echo "### DOCLING :: $base" | tee -a "$RUN_BASE/logs/docling_run.log"

  if "$DOCLING_BIN" \
      --to json \
      --output "$RUN_BASE/docling" \
      --pipeline standard \
      --pdf-backend docling_parse \
      --no-ocr \
      --tables \
      --no-abort-on-error \
      --no-show-layout \
      --artifacts-path /beegfs2/scratch/aryp26yc/kc_l/docling_hf_models \
      "$pdf" \
      >> "$RUN_BASE/logs/docling_run.log" 2>&1; then
    echo "OK :: $base" | tee -a "$RUN_BASE/logs/docling_status.txt"
  else
    echo "FAIL :: $base" | tee -a "$RUN_BASE/logs/docling_status.txt"
    FAIL=1
  fi
done < "$RUN_BASE/manifests/input_pdfs.txt"

find "$RUN_BASE/docling" -type f | sort > "$RUN_BASE/manifests/docling_outputs.txt"

echo "RUN_BASE=$RUN_BASE" | tee -a "$RUN_BASE/logs/run_meta.txt"
echo "FINAL_FAIL_FLAG=$FAIL" | tee -a "$RUN_BASE/logs/run_meta.txt"

exit "$FAIL"
