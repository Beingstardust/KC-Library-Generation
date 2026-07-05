#!/bin/bash
#SBATCH -J kc_seedless_authoritative
#SBATCH -p gpu80GB
#SBATCH --gres=gpu:a100:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --time=08:00:00
#SBATCH --exclusive
#SBATCH -o /beegfs1/home/aryp26yc/projects/kc_l_v2_clean/logs/%x-%j.out
#SBATCH -e /beegfs1/home/aryp26yc/projects/kc_l_v2_clean/logs/%x-%j.err

set -euo pipefail

REPO=/beegfs1/home/aryp26yc/projects/kc_l_v2_clean
PYTHON_BIN=/home/aryp26yc/venvs/kc_l_v2/bin/python
SCRATCH_ROOT=/beegfs2/scratch/aryp26yc/kc_l
RUNROOT="$SCRATCH_ROOT/seedless_authoritative_${SLURM_JOB_ID}"

export PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

export OLLAMA_HOST=127.0.0.1:11567
export OLLAMA_KEEP_ALIVE=0
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_MAX_LOADED_MODELS=1

if command -v ollama >/dev/null 2>&1; then
  OLLAMA_BIN="$(readlink -f "$(command -v ollama)")"
elif [ -x /home/aryp26yc/apps/ollama_clean/bin/ollama ]; then
  OLLAMA_BIN=/home/aryp26yc/apps/ollama_clean/bin/ollama
else
  echo "Could not locate ollama binary" >&2
  exit 1
fi

if [ -d /beegfs2/scratch/aryp26yc/kc_l/ollama/models ]; then
  export OLLAMA_MODELS=/beegfs2/scratch/aryp26yc/kc_l/ollama/models
fi

mkdir -p "$RUNROOT/tmp" "$RUNROOT/logs" "$REPO/logs"
export TMPDIR="$RUNROOT/tmp"

OLLAMA_PID=""

cleanup() {
  status=$?
  if [[ -n "${OLLAMA_PID}" ]] && kill -0 "${OLLAMA_PID}" 2>/dev/null; then
    kill "${OLLAMA_PID}" 2>/dev/null || true
    wait "${OLLAMA_PID}" 2>/dev/null || true
  fi
  echo "RUNROOT=$RUNROOT"
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
"$PYTHON_BIN" --version
"$OLLAMA_BIN" --version || true

echo "==== seedless sanity check ===="
if grep -nE 'seed_definition|seed_keyword|strong_seed_overlap_min' \
  steps/step_05_3_evidence_recalibrated/scripts/run_step5_3.py \
  steps/step_05_3_evidence_recalibrated/resources/step5_3.default.yaml \
  steps/step_05_3_evidence_recalibrated/resources/step5_3.sofja.actual_corpus.yaml
then
  echo "Unexpected seed residue in active Step 5.3 files" >&2
  exit 1
fi

if grep -nE '"definition"[[:space:]]*:' data/input/hierarchy/data_mining_kc_hierarchy_revised_.json
then
  echo "KC leaf definitions still present in hierarchy input" >&2
  exit 1
fi

echo "==== step 1 ===="
"$PYTHON_BIN" steps/step_01_hierarchy/scripts/01_hierarchy_normalize.py \
  --hierarchy data/input/hierarchy/data_mining_kc_hierarchy_revised_.json \
  --out_root data/processed/hierarchy \
  --runs_dir data/runs \
  --print_summary

STEP1_DIR="$(ls -1dt data/processed/hierarchy/*/ | head -n 1)"
STEP1_DIR="${STEP1_DIR%/}"
echo "STEP1_DIR=$STEP1_DIR"

test -f "$STEP1_DIR/kc_registry.jsonl"
test -f "$STEP1_DIR/hierarchy_manifest.json"

echo "==== step 1.5 ===="
"$PYTHON_BIN" steps/step_01_5_hierarchy_overlay/scripts/run_step01_5_hierarchy_overlay.py \
  --hierarchy data/input/hierarchy/data_mining_kc_hierarchy_revised_.json \
  --normalized_registry "$STEP1_DIR/kc_registry.jsonl" \
  --normalized_manifest "$STEP1_DIR/hierarchy_manifest.json" \
  --out_root data/processed/hierarchy_overlay \
  --runs_dir data/runs \
  --print_summary

echo "==== refresh aliases after step 1.5 ===="
"$PYTHON_BIN" scripts/maintenance/refresh_current_step_artifacts.py

echo "==== step 5.3 ===="
"$PYTHON_BIN" steps/step_05_3_evidence_recalibrated/scripts/run_step5_3.py \
  --config steps/step_05_3_evidence_recalibrated/resources/step5_3.sofja.actual_corpus.yaml

echo "==== step 6.6 ===="
"$PYTHON_BIN" steps/step_06_6_kc_drafting_input_overlay/scripts/run_step6_6_kc_drafting_input_overlay.py \
  --config steps/step_06_6_kc_drafting_input_overlay/resources/step6_6.sofja.actual_corpus.yaml

echo "==== refresh aliases after step 6.6 ===="
"$PYTHON_BIN" scripts/maintenance/refresh_current_step_artifacts.py

echo "==== render hpc main quest config ===="
"$PYTHON_BIN" scripts/hpc/render_main_quest_config.py --mode hpc_gpu

echo "==== start ollama server ===="
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

echo "==== step 6.7 ===="
"$PYTHON_BIN" steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py \
  --config data/work/cache/generated_configs/main_quest.hpc_gpu.yaml

echo "==== refresh aliases after step 6.7 ===="
"$PYTHON_BIN" scripts/maintenance/refresh_current_step_artifacts.py

echo "==== step 6.75 ===="
"$PYTHON_BIN" steps/step_06_75_kc_draft_canonicalization/scripts/run_step6_75_kc_draft_canonicalization.py \
  --config steps/step_06_75_kc_draft_canonicalization/resources/step6_75.slice10.yaml

echo "==== refresh aliases after step 6.75 ===="
"$PYTHON_BIN" scripts/maintenance/refresh_current_step_artifacts.py

echo "==== step 6.8 ===="
"$PYTHON_BIN" steps/step_06_8_kc_review_packet_emission/scripts/run_step6_8_kc_review_packet_emission.py \
  --config steps/step_06_8_kc_review_packet_emission/resources/step6_8.full128.yaml

echo "==== latest set manifests ===="
ls -1t data/processed/kc_evidence_recalibrated/_sets/*_step5_3_kc_evidence_recalibrated_set.json | head -n 1
ls -1t data/processed/kc_drafting_input_overlay/_sets/*_step6_6_kc_drafting_input_overlay_set.json | head -n 1
ls -1t data/processed/kc_drafts/_sets/*_step6_7_kc_drafts_set.json | head -n 1
ls -1t data/processed/kc_draft_canonicalization/_sets/*_step6_75_kc_draft_canonicalization_set.json | head -n 1
ls -1t data/processed/kc_review_packets_restarted/_sets/*_step6_8_kc_review_packets_restarted_set.json | head -n 1
