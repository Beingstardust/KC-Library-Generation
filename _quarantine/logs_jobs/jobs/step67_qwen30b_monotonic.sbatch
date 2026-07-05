#!/bin/bash
#SBATCH -J step67_qwen30b_monotonic
#SBATCH -p gpu80GB
#SBATCH --gres=gpu:a100:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=02:30:00
#SBATCH -o logs/step67_qwen30b_monotonic-%j.out
#SBATCH -e logs/step67_qwen30b_monotonic-%j.err

set -euo pipefail

cd /beegfs1/home/aryp26yc/projects/kc_l_v2_clean

export PYTHON_BIN=/home/aryp26yc/venvs/kc_l_v2/bin/python
export PYTHONPATH=/beegfs1/home/aryp26yc/projects/kc_l_v2_clean/src${PYTHONPATH:+:$PYTHONPATH}
export LD_LIBRARY_PATH=/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}

export OLLAMA_HOME=/home/aryp26yc/apps/ollama_clean
export OLLAMA_BIN=/home/aryp26yc/apps/ollama_clean/bin/ollama
export OLLAMA_MODELS=/beegfs2/scratch/aryp26yc/kc_l/ollama/models
export OLLAMA_HOST=127.0.0.1:11567

echo "==== job metadata ===="
echo "JOB_ID=${SLURM_JOB_ID}"
echo "NODELIST=${SLURM_JOB_NODELIST}"
echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-}"
echo "PWD=$(pwd)"

echo
echo "==== start ollama on compute node ===="
"${OLLAMA_BIN}" serve > "logs/ollama_server-${SLURM_JOB_ID}.log" 2>&1 &
OLLAMA_PID=$!

cleanup() {
  kill "${OLLAMA_PID}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo
echo "==== wait for ollama api ===="
for i in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:11567/api/version >/dev/null 2>&1; then
    echo "ollama api is up"
    curl -sS http://127.0.0.1:11567/api/version
    break
  fi
  sleep 2
done

echo
echo "==== verify qwen3:30b visible on this compute node ===="
curl -sS http://127.0.0.1:11567/api/tags

echo
echo "==== refresh current artifact aliases ===="
"${PYTHON_BIN}" scripts/maintenance/refresh_current_step_artifacts.py

echo
echo "==== run Step 6.7 full 144 ===="
"${PYTHON_BIN}" steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py \
  --config data/work/cache/generated_configs/main_quest.hpc_gpu.yaml

echo
echo "==== latest Step 6.7 summary ===="
"${PYTHON_BIN}" - <<'PY'
import json
from pathlib import Path

p67 = sorted(Path("data/processed/kc_drafts/_sets").glob("*step6_7_kc_drafts_set.json"))[-1]
o67 = json.loads(p67.read_text(encoding="utf-8"))
stats = json.loads(Path(o67["artifacts"]["draft_stats_json"]).read_text(encoding="utf-8"))

print("STEP67_SET:", o67["set_id"])
print()
print("AUTHORITATIVE_DEFINITION_STATUS_BREAKDOWN")
print(json.dumps(stats.get("authoritative_definition_status_breakdown", {}), indent=2))
print()
print("TRUST_STATE_BREAKDOWN")
print(json.dumps(stats.get("trust_state_breakdown", {}), indent=2))
print()
print("DRAFT_STATUS_BREAKDOWN")
print(json.dumps(stats.get("draft_status_breakdown", {}), indent=2))
print()
print("DRAFTING_RUNTIME")
print(json.dumps(stats.get("drafting_runtime", {}), indent=2))
PY
