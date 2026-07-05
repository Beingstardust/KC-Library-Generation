#!/bin/bash
#SBATCH -J kc_seedless_66_68
#SBATCH -p gpu80GB
#SBATCH --gres=gpu:a100:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --time=04:00:00
#SBATCH -o /beegfs1/home/aryp26yc/projects/kc_l_v2_clean/logs/%x-%j.out
#SBATCH -e /beegfs1/home/aryp26yc/projects/kc_l_v2_clean/logs/%x-%j.err

set -euo pipefail

REPO=/beegfs1/home/aryp26yc/projects/kc_l_v2_clean
PYTHON_BIN=/home/aryp26yc/venvs/kc_l_v2/bin/python
RUNROOT=/beegfs2/scratch/aryp26yc/kc_l/seedless_step66_68_${SLURM_JOB_ID}

export PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

export OLLAMA_HOST=127.0.0.1:11567
export OLLAMA_KEEP_ALIVE=0
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_MAX_LOADED_MODELS=1

mkdir -p "$RUNROOT/tmp" "$RUNROOT/logs" "$REPO/logs"
export TMPDIR="$RUNROOT/tmp"

OLLAMA_BIN=/home/aryp26yc/apps/ollama_clean/bin/ollama
SUCCESS=0
OLLAMA_PID=""

cleanup() {
  status=$?
  if [[ -n "${OLLAMA_PID}" ]] && kill -0 "${OLLAMA_PID}" 2>/dev/null; then
    kill "${OLLAMA_PID}" 2>/dev/null || true
    wait "${OLLAMA_PID}" 2>/dev/null || true
  fi
  echo "RUNROOT=$RUNROOT"
  if [[ "$SUCCESS" == "1" ]]; then
    echo "STEP66_TO_68_OK"
  else
    echo "STEP66_TO_68_FAILED"
  fi
  exit $status
}
trap cleanup EXIT

cd "$REPO"

echo "==== job context ===="
date -u
hostname
nvidia-smi || true
echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-unset}"
echo "PYTHON_BIN=$PYTHON_BIN"
echo "OLLAMA_BIN=$OLLAMA_BIN"

echo
echo "==== step 6.6 ===="
"$PYTHON_BIN" steps/step_06_6_kc_drafting_input_overlay/scripts/run_step6_6_kc_drafting_input_overlay.py \
  --config steps/step_06_6_kc_drafting_input_overlay/resources/step6_6.sofja.actual_corpus.yaml

echo
echo "==== refresh aliases after step 6.6 ===="
"$PYTHON_BIN" scripts/maintenance/refresh_current_step_artifacts.py
"$PYTHON_BIN" scripts/maintenance/refresh_current_step_artifacts.py --check

echo
echo "==== render hpc main quest config ===="
"$PYTHON_BIN" scripts/hpc/render_main_quest_config.py --mode hpc_gpu

echo
echo "==== start ollama ===="
"$OLLAMA_BIN" serve > "$RUNROOT/logs/ollama_server.log" 2>&1 &
OLLAMA_PID=$!

READY=0
for _ in $(seq 1 90); do
  if curl -sf "http://127.0.0.1:11567/api/tags" >/dev/null; then
    READY=1
    break
  fi
  sleep 2
done

if [[ "$READY" != "1" ]]; then
  echo "OLLAMA_SERVER_NOT_READY"
  tail -n 120 "$RUNROOT/logs/ollama_server.log" || true
  exit 1
fi

if ! "$OLLAMA_BIN" list | awk 'NR>1 {print $1}' | grep -Fx "qwen3:30b" >/dev/null; then
  echo "MODEL_NOT_AVAILABLE:qwen3:30b"
  "$OLLAMA_BIN" list || true
  exit 1
fi

echo
echo "==== step 6.7 ===="
"$PYTHON_BIN" steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py \
  --config data/work/cache/generated_configs/main_quest.hpc_gpu.yaml

echo
echo "==== refresh aliases after step 6.7 ===="
"$PYTHON_BIN" scripts/maintenance/refresh_current_step_artifacts.py
"$PYTHON_BIN" scripts/maintenance/refresh_current_step_artifacts.py --check

echo
echo "==== step 6.75 ===="
"$PYTHON_BIN" steps/step_06_75_kc_draft_canonicalization/scripts/run_step6_75_kc_draft_canonicalization.py \
  --config steps/step_06_75_kc_draft_canonicalization/resources/step6_75.slice10.yaml

echo
echo "==== refresh aliases after step 6.75 ===="
"$PYTHON_BIN" scripts/maintenance/refresh_current_step_artifacts.py
"$PYTHON_BIN" scripts/maintenance/refresh_current_step_artifacts.py --check

echo
echo "==== step 6.8 ===="
"$PYTHON_BIN" steps/step_06_8_kc_review_packet_emission/scripts/run_step6_8_kc_review_packet_emission.py \
  --config steps/step_06_8_kc_review_packet_emission/resources/step6_8.full128.yaml

echo
echo "==== latest set manifests ===="
ls -1t data/processed/kc_drafting_input_overlay/_sets/*_step6_6_kc_drafting_input_overlay_set.json | head -n 1
ls -1t data/processed/kc_drafts/_sets/*_step6_7_kc_drafts_set.json | head -n 1
ls -1t data/processed/kc_draft_canonicalization/_sets/*_step6_75_kc_draft_canonicalization_set.json | head -n 1
ls -1t data/processed/kc_review_packets_restarted/_sets/*_step6_8_kc_review_packets_restarted_set.json | head -n 1

SUCCESS=1
