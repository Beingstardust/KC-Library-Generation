#!/bin/bash
#SBATCH -J kc_step4_3_index
#SBATCH -p big
#SBATCH --cpus-per-task=12
#SBATCH --mem=128G
#SBATCH --time=24:00:00
#SBATCH -o /beegfs2/scratch/aryp26yc/kc_l/slurm_logs/%x_%j.out
#SBATCH -e /beegfs2/scratch/aryp26yc/kc_l/slurm_logs/%x_%j.err

set -euo pipefail

unset PROMPT_COMMAND || true
source ~/kc_l_v2_env.sh

REPO=/beegfs1/home/aryp26yc/projects/kc_l_v2_clean
cd "$REPO"

export PYTHONPATH="$REPO/src"
export LD_LIBRARY_PATH="/beegfs1/software/rh8/usr/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

CONFIG="$REPO/steps/step_04_structure_retrieval_index/resources/step4.index.sofja.actual_corpus.yaml"
OLLAMA_HOST_VALUE="127.0.0.1:11434"
OLLAMA_MODEL="qwen3-embedding:8b"

export OLLAMA_HOST="$OLLAMA_HOST_VALUE"

# If your Ollama models are stored in a non-default place, uncomment and set this.
# export OLLAMA_MODELS=/beegfs2/scratch/aryp26yc/kc_l/ollama_models

echo "[step4.3] host=$(hostname)"
echo "[step4.3] config=$CONFIG"
echo "[step4.3] OLLAMA_HOST=$OLLAMA_HOST"
echo "[step4.3] OLLAMA_MODEL=$OLLAMA_MODEL"

command -v ollama
python --version

OLLAMA_STDOUT="/beegfs2/scratch/aryp26yc/kc_l/slurm_logs/ollama_step4_3_${SLURM_JOB_ID}.out"
OLLAMA_STDERR="/beegfs2/scratch/aryp26yc/kc_l/slurm_logs/ollama_step4_3_${SLURM_JOB_ID}.err"

echo "[step4.3] starting local ollama server"
ollama serve >"$OLLAMA_STDOUT" 2>"$OLLAMA_STDERR" &
OLLAMA_PID=$!

cleanup() {
  if kill -0 "$OLLAMA_PID" 2>/dev/null; then
    kill "$OLLAMA_PID" 2>/dev/null || true
    wait "$OLLAMA_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

echo "[step4.3] waiting for ollama API"
for i in $(seq 1 60); do
  if python - <<'PY'
import os, sys, urllib.request
url = f"http://{os.environ['OLLAMA_HOST']}/api/version"
try:
    with urllib.request.urlopen(url, timeout=2) as r:
        print(r.read().decode("utf-8", "replace"))
    sys.exit(0)
except Exception:
    sys.exit(1)
PY
  then
    echo "[step4.3] ollama API is up"
    break
  fi
  sleep 2
done

python - <<'PY'
import os, sys, urllib.request
url = f"http://{os.environ['OLLAMA_HOST']}/api/version"
with urllib.request.urlopen(url, timeout=10) as r:
    print("[step4.3] /api/version OK")
    print(r.read().decode("utf-8", "replace"))
PY

echo "[step4.3] checking embedding model availability"
ollama show "$OLLAMA_MODEL" >/dev/null

echo "[step4.3] launching index build"
python steps/step_04_structure_retrieval_index/scripts/run_step4_3.py \
  --config "$CONFIG"
