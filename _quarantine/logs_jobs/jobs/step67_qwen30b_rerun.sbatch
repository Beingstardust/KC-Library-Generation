#!/bin/bash
#SBATCH -J step67_qwen30b_rerun
#SBATCH -p gpu80GB
#SBATCH --gres=gpu:a100:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=02:30:00
#SBATCH -o /beegfs1/home/aryp26yc/projects/kc_l_v2_clean/logs/%x-%j.out
#SBATCH -e /beegfs1/home/aryp26yc/projects/kc_l_v2_clean/logs/%x-%j.err

set -euo pipefail

REPO=/beegfs1/home/aryp26yc/projects/kc_l_v2_clean
cd "$REPO"

export PYTHON_BIN=/home/aryp26yc/venvs/kc_l_v2/bin/python
export PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH=/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}

export OLLAMA_HOME=/home/aryp26yc/apps/ollama_clean
export OLLAMA_BIN=$OLLAMA_HOME/bin/ollama
export OLLAMA_MODELS=/beegfs2/scratch/aryp26yc/kc_l/ollama/models
export OLLAMA_HOST=127.0.0.1:11567
export PATH="$OLLAMA_HOME/bin${PATH:+:$PATH}"

cleanup() {
  if [[ -n "${OLLAMA_PID:-}" ]] && kill -0 "$OLLAMA_PID" 2>/dev/null; then
    kill "$OLLAMA_PID" || true
    wait "$OLLAMA_PID" || true
  fi
}
trap cleanup EXIT

echo "==== job metadata ===="
echo "JOB_ID=$SLURM_JOB_ID"
echo "NODELIST=$SLURM_NODELIST"
echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-unset}"
echo "HOSTNAME=$(hostname)"
echo "PWD=$PWD"

echo
echo "==== ollama env ===="
echo "OLLAMA_BIN=$OLLAMA_BIN"
echo "OLLAMA_HOST=$OLLAMA_HOST"
echo "OLLAMA_MODELS=$OLLAMA_MODELS"
ls -ld "$OLLAMA_MODELS" || true

echo
echo "==== preflight ollama binary ===="
"$OLLAMA_BIN" --version || true

echo
echo "==== start ollama on compute node ===="
"$OLLAMA_BIN" serve > "$REPO/logs/ollama_server-$SLURM_JOB_ID.log" 2>&1 &
OLLAMA_PID=$!
echo "OLLAMA_PID=$OLLAMA_PID"

echo
echo "==== wait for ollama api ===="
for i in $(seq 1 90); do
  if curl -fsS http://127.0.0.1:11567/api/version >/dev/null 2>&1; then
    echo "ollama api is up"
    curl -fsS http://127.0.0.1:11567/api/version
    echo
    break
  fi
  sleep 2
done

curl -fsS http://127.0.0.1:11567/api/version >/dev/null

echo
echo "==== model visibility via api ===="
curl -fsS http://127.0.0.1:11567/api/tags
echo

echo
echo "==== model visibility via ollama cli ===="
"$OLLAMA_BIN" list || true
echo
"$OLLAMA_BIN" show qwen3:30b || true

if ! curl -fsS http://127.0.0.1:11567/api/tags | grep -q '"name":"qwen3:30b"'; then
  echo "qwen3:30b not visible from compute-node ollama server" >&2
  exit 1
fi

echo
echo "==== run Step 6.7 bounded HPC slice10 ===="
"$PYTHON_BIN" steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py \
  --config data/work/cache/generated_configs/main_quest.hpc_gpu.slice10.yaml

echo
echo "==== refresh current artifact aliases ===="
"$PYTHON_BIN" scripts/maintenance/refresh_current_step_artifacts.py

echo
echo "==== run Step 6.8 slice10 ===="
"$PYTHON_BIN" steps/step_06_8_kc_review_packet_emission/scripts/run_step6_8_kc_review_packet_emission.py \
  --config steps/step_06_8_kc_review_packet_emission/resources/step6_8.slice10.yaml

echo
echo "==== summarize outputs ===="
"$PYTHON_BIN" - <<'PY'
import json
from pathlib import Path

p67 = sorted(Path("data/processed/kc_drafts/_sets").glob("*step6_7_kc_drafts_set.json"))[-1]
o67 = json.loads(p67.read_text(encoding="utf-8"))
stats = json.loads(Path(o67["artifacts"]["draft_stats_json"]).read_text(encoding="utf-8"))

p68 = sorted(Path("data/processed/kc_review_packets_restarted/_sets").glob("*step6_8_kc_review_packets_restarted_set.json"))[-1]
o68 = json.loads(p68.read_text(encoding="utf-8"))
summary = json.loads(Path(o68["artifacts"]["review_packet_summary_json"]).read_text(encoding="utf-8"))

print("STEP67_SET", p67.as_posix())
print("STEP68_SET", p68.as_posix())
print(json.dumps(stats.get("drafting_runtime", {}), indent=2))
print(json.dumps(stats.get("draft_status_breakdown", {}), indent=2))
print(json.dumps({
    "packet_count": summary.get("packet_count"),
    "fallback_definition_count": summary.get("fallback_definition_count"),
    "normalized_grounded_definition_count": summary.get("normalized_grounded_definition_count"),
    "low_trust_packet_count": summary.get("low_trust_packet_count"),
    "review_readiness_counts": summary.get("review_readiness_counts"),
    "trust_state_counts": summary.get("trust_state_counts"),
    "priority_counts": summary.get("priority_counts"),
    "recommendation_counts": summary.get("recommendation_counts"),
    "quarantine_count": summary.get("quarantine_count"),
    "excluded_kcs_len": len(summary.get("excluded_kcs", [])),
}, indent=2))
PY

echo
echo "==== done ===="
