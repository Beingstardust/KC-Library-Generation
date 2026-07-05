#!/bin/bash
#SBATCH -J step67b_012531_val
#SBATCH -p gpu80GB
#SBATCH --gres=gpu:a100:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=08:00:00
#SBATCH -o logs/step67b_012531_validation-%j.out
#SBATCH -e logs/step67b_012531_validation-%j.err

set -euo pipefail

REPO_ROOT=/beegfs1/home/aryp26yc/projects/kc_l_v2_clean
cd "${REPO_ROOT}"

mkdir -p logs

export PYTHON_BIN=/home/aryp26yc/venvs/kc_l_v2/bin/python
export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
export LD_LIBRARY_PATH=/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}

export OLLAMA_HOME=/home/aryp26yc/apps/ollama_clean
export OLLAMA_BIN=/home/aryp26yc/apps/ollama_clean/bin/ollama
export OLLAMA_MODELS=/beegfs2/scratch/aryp26yc/kc_l/ollama/models
export OLLAMA_HOST=127.0.0.1:11567

JOB_SCRATCH=/beegfs2/scratch/aryp26yc/kc_l/slurm_tmp/step67b_${SLURM_JOB_ID}
mkdir -p "${JOB_SCRATCH}"
export TMPDIR="${JOB_SCRATCH}"

echo "==== job metadata ===="
echo "JOB_ID=${SLURM_JOB_ID}"
echo "NODELIST=${SLURM_JOB_NODELIST}"
echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-unset}"
echo "PWD=$(pwd)"
echo "TMPDIR=${TMPDIR}"
echo "OLLAMA_BIN=${OLLAMA_BIN}"
echo "OLLAMA_MODELS=${OLLAMA_MODELS}"
echo "OLLAMA_HOST=${OLLAMA_HOST}"

if [ ! -x "${OLLAMA_BIN}" ]; then
  echo "ERROR: OLLAMA_BIN is not executable: ${OLLAMA_BIN}" >&2
  exit 20
fi

if [ ! -d "${OLLAMA_MODELS}" ]; then
  echo "ERROR: OLLAMA_MODELS directory not found: ${OLLAMA_MODELS}" >&2
  exit 21
fi

OLLAMA_LOG="logs/ollama_server_step67b_${SLURM_JOB_ID}.log"

echo
echo "==== start ollama on compute node ===="
"${OLLAMA_BIN}" serve > "${OLLAMA_LOG}" 2>&1 &
OLLAMA_PID=$!
echo "OLLAMA_PID=${OLLAMA_PID}"

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

echo
echo "==== wait for ollama api ===="
ready=0
for i in $(seq 1 120); do
  if curl -fsS "http://${OLLAMA_HOST}/api/version" >/dev/null 2>&1; then
    ready=1
    echo "ollama api is up"
    curl -sS "http://${OLLAMA_HOST}/api/version"
    echo
    break
  fi
  sleep 2
done

if [ "${ready}" -ne 1 ]; then
  echo "ERROR: Ollama API did not come up on ${OLLAMA_HOST}" >&2
  exit 22
fi

echo
echo "==== verify qwen3:30b visible on this compute node ===="
curl -sS "http://${OLLAMA_HOST}/api/tags"
echo
curl -sS "http://${OLLAMA_HOST}/api/tags" | grep -F '"name":"qwen3:30b"' >/dev/null

echo
echo "==== run Step 6.7B validation on 2026-04-19_012531 baseline ===="
"${PYTHON_BIN}" steps/step_06_7b_seed_floor_triage_and_rescue/scripts/run_step6_7b_seed_floor_triage_and_rescue.py \
  --config steps/step_06_7b_seed_floor_triage_and_rescue/resources/step6_7b.012531.validation.yaml

echo
echo "==== latest Step 6.7B set/runtime proof ===="
"${PYTHON_BIN}" - <<'PY'
import json
from pathlib import Path

sets_dir = Path("data/processed/kc_seed_floor_triage_and_rescue/_sets")
set_paths = sorted(sets_dir.glob("*step6_7b*set.json")) + sorted(sets_dir.glob("*.json"))
if not set_paths:
    raise SystemExit("No Step 6.7B set manifest found under data/processed/kc_seed_floor_triage_and_rescue/_sets")

picked = set_paths[-1]
manifest = json.loads(picked.read_text(encoding="utf-8"))
print("STEP67B_SET_MANIFEST:", picked.as_posix())
print(json.dumps(manifest, indent=2))

artifacts = manifest.get("artifacts", {})
stats_path = artifacts.get("triage_stats_json") or artifacts.get("stats_json")
if stats_path:
    stats = json.loads(Path(stats_path).read_text(encoding="utf-8"))
    print("==== TRIAGE STATS ====")
    print(json.dumps(stats, indent=2))
PY
