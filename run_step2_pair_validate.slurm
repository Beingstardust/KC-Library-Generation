#!/bin/bash
#SBATCH -J kc_step2_corpus3
#SBATCH -p big
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --time=12:00:00
#SBATCH -o /beegfs2/scratch/aryp26yc/kc_l/slurm_logs/%x_%j.out
#SBATCH -e /beegfs2/scratch/aryp26yc/kc_l/slurm_logs/%x_%j.err

set -euo pipefail

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
export DOCLING_ARTIFACTS_PATH=/beegfs2/scratch/aryp26yc/kc_l/docling_hf_models
unset TRANSFORMERS_CACHE || true

CONFIG="$REPO/steps/step_02_pdf_ingest_blockstore/resources/step2.sofja.actual_corpus.yaml"

make_doc_id () {
  python - "$1" <<'PY'
import re, sys
stem = sys.argv[1]
safe = re.sub(r"[^A-Za-z0-9_]", "_", stem)
safe = re.sub(r"_{2,}", "_", safe).strip("_")
print(f"DOC_{safe}" if safe else "DOC")
PY
}

run_one () {
  local pdf="$1"
  local base
  local stem
  local doc_id

  base=$(basename "$pdf")
  stem="${base%.pdf}"
  doc_id=$(make_doc_id "$stem")

  echo
  echo "===== STEP2 :: $base :: $doc_id ====="

  python steps/step_02_pdf_ingest_blockstore/scripts/run_step2.py \
    --config "$CONFIG" \
    --pdf "$pdf" \
    --doc-id "$doc_id"
}

run_one "$REPO/data/input/course_materials/data-preprocessing-book-Chapter 3n4.pdf"
run_one "$REPO/data/input/course_materials/data-preprocessing-book-Chapter 7.pdf"
run_one "$REPO/data/input/course_materials/introduction-to-data-mining-.pdf"
