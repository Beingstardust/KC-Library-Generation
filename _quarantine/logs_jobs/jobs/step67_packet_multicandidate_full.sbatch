#!/bin/bash
#SBATCH -J step67_pktfull
#SBATCH -p gpu80GB
#SBATCH --gres=gpu:a100:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=24:00:00
#SBATCH --exclusive
#SBATCH -o logs/step67_pktfull-%j.out
#SBATCH -e logs/step67_pktfull-%j.err

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

CONFIG=steps/step_06_7_kc_draft_generation/resources/step6_7.012531.packet_multicandidate_full.yaml

JOB_SCRATCH=/beegfs2/scratch/aryp26yc/kc_l/slurm_tmp/step67_pktfull_${SLURM_JOB_ID}
mkdir -p "${JOB_SCRATCH}"
export TMPDIR="${JOB_SCRATCH}"

mkdir -p logs

echo "===== node / gpu preflight ====="
hostname
date
nvidia-smi

echo "===== config check ====="
test -f "${CONFIG}"
echo "CONFIG=${CONFIG}"

mapfile -t GPU_FREE_LINES < <(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits)
mapfile -t GPU_TOTAL_LINES < <(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits)

FREE_MIB=$(printf '%s' "${GPU_FREE_LINES[0]}" | tr -d ' ')
TOTAL_MIB=$(printf '%s' "${GPU_TOTAL_LINES[0]}" | tr -d ' ')

echo "FREE_MIB=${FREE_MIB}"
echo "TOTAL_MIB=${TOTAL_MIB}"

if [ -z "${FREE_MIB}" ]; then
  echo "ERROR: could not read free GPU memory" >&2
  exit 30
fi

if [ "${FREE_MIB}" -lt 70000 ]; then
  echo "ERROR: insufficient free VRAM for full Step 6.7 rerun. Need >= 70000 MiB, got ${FREE_MIB} MiB." >&2
  exit 31
fi

OLLAMA_LOG="logs/ollama_server_step67_pktfull_${SLURM_JOB_ID}.log"

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

echo "===== launching full Step 6.7 rerun ====="
"${PYTHON_BIN}" steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py \
  --config "${CONFIG}"

echo "===== latest Step 6.7 set ====="
ls -1t data/processed/kc_drafts/_sets/*step6_7_kc_drafts_set.json | head -n 5
