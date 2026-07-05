#!/bin/bash
#SBATCH --job-name=step67_q30b_s20
#SBATCH --partition=gpu80GB
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=05:00:00
#SBATCH --output=/beegfs1/home/aryp26yc/projects/kc_l_v2_clean/slurm/step67_q30b_s20_%j.out
#SBATCH --error=/beegfs1/home/aryp26yc/projects/kc_l_v2_clean/slurm/step67_q30b_s20_%j.err

set -euo pipefail

cd /beegfs1/home/aryp26yc/projects/kc_l_v2_clean

unset PROMPT_COMMAND || true
hash -r || true

export PYTHON_BIN=/home/aryp26yc/venvs/kc_l_v2/bin/python
export PYTHONPATH=/beegfs1/home/aryp26yc/projects/kc_l_v2_clean/src${PYTHONPATH:+:$PYTHONPATH}
export LD_LIBRARY_PATH=/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}

export OLLAMA_BIN=/beegfs1/home/aryp26yc/apps/ollama_clean/bin/ollama
export PATH="$(dirname "$OLLAMA_BIN"):$PATH"
export OLLAMA_MODELS=/beegfs2/scratch/aryp26yc/kc_l/ollama/models
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_MAX_LOADED_MODELS=1

PORT=11567
export OLLAMA_HOST="127.0.0.1:${PORT}"

cleanup() {
  if [ -n "${OLLAMA_PID:-}" ] && kill -0 "$OLLAMA_PID" 2>/dev/null; then
    kill "$OLLAMA_PID" 2>/dev/null || true
    wait "$OLLAMA_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

echo "TIME_START=$(date)"
echo "HOSTNAME=$(hostname)"
echo "SLURM_JOB_ID=${SLURM_JOB_ID:-}"
echo "SLURM_JOB_NODELIST=${SLURM_JOB_NODELIST:-}"
echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-}"
echo "OLLAMA_HOST=${OLLAMA_HOST}"
nvidia-smi -L || true
"${PYTHON_BIN}" --version
"${OLLAMA_BIN}" --version || true

OLLAMA_LOG="slurm/ollama_step67_slice20_${SLURM_JOB_ID}.log"
"${OLLAMA_BIN}" serve > "${OLLAMA_LOG}" 2>&1 &
OLLAMA_PID=$!

sleep 8

echo "OLLAMA_PID=${OLLAMA_PID}"
ps -fp "${OLLAMA_PID}" || true
tail -n 40 "${OLLAMA_LOG}" || true

curl -sf "http://127.0.0.1:${PORT}/api/tags" | sed -n '1,120p'

TMP_CFG="slurm/step6_7_slice20_job_${SLURM_JOB_ID}.yaml"
"${PYTHON_BIN}" - <<PY
from pathlib import Path
import yaml

src = Path("step6_7.sofja.actual_corpus.qwen30b.slice20_adversarial.yaml")
dst = Path("${TMP_CFG}")
cfg = yaml.safe_load(src.read_text(encoding="utf-8"))
cfg["model"]["base_url"] = "http://127.0.0.1:${PORT}"
dst.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
print(f"WROTE {dst}")
PY

echo "STEP67_SLICE20_RUN_START=$(date)"

PYTHONFAULTHANDLER=1 "${PYTHON_BIN}" -u run_step6_7_model_draft_generation.py \
  --config "${TMP_CFG}"

STATUS=$?

echo "STEP67_SLICE20_RUN_EXIT_CODE=${STATUS}"
echo "STEP67_SLICE20_RUN_END=$(date)"

RUN=$(find data/runs -maxdepth 1 -type d | grep '_step6_7$' | sort | tail -n 1 || true)
OUT=$(find data/processed/kc_drafts -maxdepth 1 -mindepth 1 -type d ! -name '_sets' | sort | tail -n 1 || true)

echo "LATEST_RUN=${RUN}"
[ -n "${RUN}" ] && find "${RUN}" -maxdepth 1 -type f -printf "%TY-%Tm-%Td %TH:%TM:%TS %f\n" | sort || true

echo "LATEST_OUT=${OUT}"
[ -n "${OUT}" ] && find "${OUT}" -maxdepth 1 -type f -printf "%TY-%Tm-%Td %TH:%TM:%TS %f\n" | sort || true

exit "${STATUS}"
