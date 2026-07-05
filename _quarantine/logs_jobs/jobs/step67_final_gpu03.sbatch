#!/bin/bash
#SBATCH -J step67_final
#SBATCH -p gpu80GB
#SBATCH --nodelist=gpu03
#SBATCH --gres=gpu:a100:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=24:00:00
#SBATCH --exclusive
#SBATCH -o logs/step67_final-%j.out
#SBATCH -e logs/step67_final-%j.err

set -euo pipefail

REPO_ROOT=/beegfs1/home/aryp26yc/projects/kc_l_v2_clean
cd "${REPO_ROOT}"

export PYTHON_BIN=/home/aryp26yc/venvs/kc_l_v2/bin/python
export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
export LD_LIBRARY_PATH=/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}

export OLLAMA_HOME=/home/aryp26yc/apps/ollama_clean
export OLLAMA_BIN=/home/aryp26yc/apps/ollama_clean/bin/ollama
export OLLAMA_MODELS=/beegfs2/scratch/aryp26yc/kc_l/ollama/models
export OLLAMA_HOST=127.0.0.1:11567
export OLLAMA_NUM_PARALLEL=1

# Respect Slurm's allocated GPU if present. Fall back to logical GPU 0.
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
export GPU_DEVICE_ORDINAL="${CUDA_VISIBLE_DEVICES}"
export ROCR_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES}"

CONFIG=data/runs/2026-04-19_012531_step6_7/config_snapshot.yaml
JOB_SCRATCH=/beegfs2/scratch/aryp26yc/kc_l/slurm_tmp/step67_final_${SLURM_JOB_ID}
mkdir -p "${JOB_SCRATCH}"
export TMPDIR="${JOB_SCRATCH}"

mkdir -p logs

echo "===== node / gpu preflight ====="
hostname
date
echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES}"
nvidia-smi

echo "===== config check ====="
test -f "${CONFIG}"
echo "CONFIG=${CONFIG}"

MODEL_ALIAS=$("${PYTHON_BIN}" - <<'PY'
from pathlib import Path
import yaml
cfg = yaml.safe_load(Path("data/runs/2026-04-19_012531_step6_7/config_snapshot.yaml").read_text(encoding="utf-8"))
model_alias = (((cfg.get("model_runtime") or {}).get("generation") or {}).get("model_alias")) or ""
print(model_alias)
PY
)
echo "MODEL_ALIAS=${MODEL_ALIAS}"

# Query only the allocated logical GPU to avoid pipefail + SIGPIPE issues.
FREE_MIB=$(nvidia-smi --id=0 --query-gpu=memory.free --format=csv,noheader,nounits | tr -d ' ')
TOTAL_MIB=$(nvidia-smi --id=0 --query-gpu=memory.total --format=csv,noheader,nounits | tr -d ' ')
echo "FREE_MIB=${FREE_MIB}"
echo "TOTAL_MIB=${TOTAL_MIB}"

if [ -z "${FREE_MIB}" ]; then
  echo "ERROR: could not read free GPU memory" >&2
  exit 30
fi

if [ "${FREE_MIB}" -lt 70000 ]; then
  echo "ERROR: insufficient free VRAM for final Step 6.7 rerun. Need >= 70000 MiB, got ${FREE_MIB} MiB." >&2
  exit 31
fi

OLLAMA_LOG="logs/ollama_server_step67_final_${SLURM_JOB_ID}.log"

"${OLLAMA_BIN}" serve > "${OLLAMA_LOG}" 2>&1 &
OLLAMA_PID=$!

cleanup() {
  status=$?
  kill "${OLLAMA_PID}" >/dev/null 2>&1 || true
  wait "${OLLAMA_PID}" >/dev/null 2>&1 || true
  if [ "${status}" -eq 0 ]; then
    rm -rf "${JOB_SCRATCH}" >/dev/null 2>&1 || true
  else
    echo "Job failed, preserving scratch at: ${JOB_SCRATCH}" >&2
    echo "Ollama log preserved at: ${OLLAMA_LOG}" >&2
  fi
  exit "${status}"
}
trap cleanup EXIT

ready=0
for i in $(seq 1 120); do
  if curl -fsS "http://${OLLAMA_HOST}/api/version" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done

if [ "${ready}" -ne 1 ]; then
  echo "ERROR: Ollama API did not come up on ${OLLAMA_HOST}" >&2
  exit 32
fi

if [ -n "${MODEL_ALIAS}" ]; then
  curl -sS "http://${OLLAMA_HOST}/api/tags" | grep -F "\"name\":\"${MODEL_ALIAS}\"" >/dev/null
fi

echo "===== launching Step 6.7 rerun ====="
"${PYTHON_BIN}" steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py \
  --config "${CONFIG}"

echo "===== latest Step 6.7 set ====="
ls -1t data/processed/kc_drafts/_sets/*step6_7_kc_drafts_set.json | head -n 3
