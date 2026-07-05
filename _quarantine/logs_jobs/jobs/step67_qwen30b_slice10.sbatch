#!/bin/bash
#SBATCH -J step67_qwen30b
#SBATCH -p gpu80GB
#SBATCH --gres=gpu:a100:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH -t 08:00:00
#SBATCH -o logs/step67_qwen30b-%j.out
#SBATCH -e logs/step67_qwen30b-%j.err

set -euo pipefail

REPO=/beegfs1/home/aryp26yc/projects/kc_l_v2_clean
PYTHON_BIN=/home/aryp26yc/venvs/kc_l_v2/bin/python
OLLAMA_HOME=/home/aryp26yc/apps/ollama_clean
OLLAMA_BIN=/home/aryp26yc/apps/ollama_clean/bin/ollama
OLLAMA_MODELS=/beegfs2/scratch/aryp26yc/kc_l/ollama/models
OLLAMA_HOST=127.0.0.1:11567

cd "$REPO"
mkdir -p logs

export PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH=/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
export OLLAMA_HOME
export OLLAMA_BIN
export OLLAMA_MODELS
export OLLAMA_HOST

echo "==== job context ===="
hostname
date
pwd
echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-}"
echo "OLLAMA_BIN=$OLLAMA_BIN"
echo "OLLAMA_MODELS=$OLLAMA_MODELS"
echo "OLLAMA_HOST=$OLLAMA_HOST"

echo
echo "==== gpu status ===="
nvidia-smi || true

echo
echo "==== start ollama on compute node ===="
"$OLLAMA_BIN" serve > "logs/ollama_server_${SLURM_JOB_ID}.log" 2>&1 &
OLLAMA_PID=$!
echo "OLLAMA_PID=$OLLAMA_PID"

cleanup() {
  if kill -0 "$OLLAMA_PID" 2>/dev/null; then
    kill "$OLLAMA_PID" || true
    wait "$OLLAMA_PID" || true
  fi
}
trap cleanup EXIT

echo
echo "==== wait for ollama api ===="
for i in $(seq 1 60); do
  if curl -fsS "http://${OLLAMA_HOST}/api/version" >/dev/null 2>&1; then
    echo "ollama api is up"
    curl -sS "http://${OLLAMA_HOST}/api/version"
    break
  fi
  sleep 2
done

echo
echo "==== verify qwen3:30b visible on compute-node ollama server ===="
curl -sS "http://${OLLAMA_HOST}/api/tags"
if ! curl -sS "http://${OLLAMA_HOST}/api/tags" | grep -q '"name":"qwen3:30b"'; then
  echo "qwen3:30b not visible from compute-node ollama server"
  exit 1
fi

echo
echo "==== bounded Step 6.7 run ===="
"$PYTHON_BIN" steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py \
  --config data/work/cache/generated_configs/main_quest.hpc_gpu.slice10.yaml

echo
echo "==== latest Step 6.7 outputs ===="
LATEST_SET=$(find data/processed/kc_drafts/_sets -maxdepth 1 -type f | sort | tail -n 1)
echo "$LATEST_SET"
sed -n '1,240p' "$LATEST_SET" || true

echo
echo "==== latest Step 6.7 stats path ===="
LATEST_STATS=$("$PYTHON_BIN" - <<'PY'
import json
from pathlib import Path
p = sorted(Path("data/processed/kc_drafts/_sets").glob("*step6_7_kc_drafts_set.json"))[-1]
obj = json.loads(p.read_text(encoding="utf-8"))
print(obj["artifacts"]["draft_stats_json"])
PY
)
echo "$LATEST_STATS"

echo
echo "==== drafting runtime excerpt ===="
"$PYTHON_BIN" - <<'PY'
import json
from pathlib import Path
p = sorted(Path("data/processed/kc_drafts/_sets").glob("*step6_7_kc_drafts_set.json"))[-1]
obj = json.loads(p.read_text(encoding="utf-8"))
stats = json.loads(Path(obj["artifacts"]["draft_stats_json"]).read_text(encoding="utf-8"))
print(json.dumps(stats.get("drafting_runtime", {}), indent=2))
PY
