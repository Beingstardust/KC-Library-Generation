#!/bin/bash
#SBATCH -J s53_67_g4_r10
#SBATCH -p gpu46GB
#SBATCH --nodelist=gpu05
#SBATCH --gres=gpu:a40:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=08:00:00
#SBATCH -o logs/s53_67_g4_r10-%j.out
#SBATCH -e logs/s53_67_g4_r10-%j.err

set -euo pipefail

cd /beegfs1/home/aryp26yc/projects/kc_l_v2_clean || exit 1

export PYTHON_BIN=/home/aryp26yc/venvs/kc_l_v2/bin/python
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH=/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}

export OLLAMA_BIN=/beegfs1/home/aryp26yc/apps/ollama_upgrade_clean_20260425_214752/bin/ollama
export OLLAMA_MODELS=/beegfs2/scratch/aryp26yc/kc_l/ollama/models
export OLLAMA_HOST=127.0.0.1:11567
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_KEEP_ALIVE=0

echo "==== job context ===="
date -u
hostname
nvidia-smi || true
echo "PYTHON_BIN=$PYTHON_BIN"
echo "OLLAMA_BIN=$OLLAMA_BIN"
echo "OLLAMA_MODELS=$OLLAMA_MODELS"
echo "OLLAMA_HOST=$OLLAMA_HOST"
echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-unset}"

echo
echo "==== py_compile synced upstream files ===="
"$PYTHON_BIN" -m py_compile \
  src/kc_l/retrieval_gate/role_scoring.py \
  steps/step_05_3_evidence_recalibrated/scripts/run_step5_3.py \
  src/kc_l/kc/drafting_input_overlay.py \
  src/kc_l/kc_drafting/heuristic_core.py \
  tests/test_step53_support_composition.py

echo
echo "==== deterministic upstream tests ===="
"$PYTHON_BIN" - <<'PY'
import importlib.util, pathlib, sys
repo = pathlib.Path(".").resolve()
sys.path.insert(0, str(repo))
sys.path.insert(0, str(repo/"src"))
path = repo/"tests"/"test_step53_support_composition.py"
spec = importlib.util.spec_from_file_location("step53_tests", path)
mod = importlib.util.module_from_spec(spec)
sys.modules["step53_tests"] = mod
spec.loader.exec_module(mod)
mod.test_step53_selection_prefers_definition_anchor_and_context_before_formula_only()
mod.test_step53_formula_only_summary_marks_weak_support_pack()
mod.test_overlay_propagates_support_profile_and_step53_support_summary()
mod.test_assess_overlay_candidate_respects_upstream_support_profile()
print("STEP53_SUPPORT_TESTS_OK")
PY

echo
echo "==== render retained HPC main-quest config ===="
"$PYTHON_BIN" steps/step_06_main_quest_execution/scripts/render_step6_main_quest_config.py \
  --base steps/step_06_main_quest_execution/resources/step6_main_quest_v1.base.yaml \
  --overlay steps/step_06_main_quest_execution/resources/step6_main_quest_v1.hpc_gpu.yaml \
  --output data/work/cache/generated_configs/main_quest.hpc_gpu.yaml \
  --report data/work/cache/generated_configs/main_quest.hpc_gpu.validation.json

echo
echo "==== build Gemma regression-slice config ===="
"$PYTHON_BIN" - <<'PY'
from pathlib import Path
import yaml

base = Path("data/work/cache/generated_configs/main_quest.hpc_gpu.yaml")
dst = Path("data/work/cache/generated_configs/main_quest.hpc_gpu.gemma_regress10.yaml")

target_ids = [
    "KC_CLU_EVAL_001",
    "KC_CLU_EVAL_002",
    "KC_DE_PREP_003",
    "KC_EVAL_BASIC_005",
    "KC_EVAL_SAMP_003",
    "KC_CLU_DBS_003",
    "KC_CLF_NB_011",
    "KC_CLU_CORE_002",
    "KC_CLU_DBS_001",
    "KC_CLU_EVAL_012",
]

cfg = yaml.safe_load(base.read_text(encoding="utf-8"))
cfg.setdefault("step6_7", {}).setdefault("slice", {})
cfg["step6_7"]["slice"]["limit_kcs"] = len(target_ids)
cfg["step6_7"]["slice"]["exact_kc_ids"] = target_ids

dst.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
print("WROTE", dst)
print("TARGET_IDS", target_ids)
PY

echo
echo "==== step 5.3 full rerun ===="
"$PYTHON_BIN" steps/step_05_3_evidence_recalibrated/scripts/run_step5_3.py \
  --config steps/step_05_3_evidence_recalibrated/resources/step5_3.sofja.actual_corpus.yaml

echo
echo "==== refresh current-step artifacts after step 5.3 ===="
"$PYTHON_BIN" scripts/maintenance/refresh_current_step_artifacts.py

echo
echo "==== step 6.6 regression slice rerun ===="
"$PYTHON_BIN" steps/step_06_6_kc_drafting_input_overlay/scripts/run_step6_6_kc_drafting_input_overlay.py \
  --config steps/step_06_6_kc_drafting_input_overlay/resources/step6_6.regression_gemma_slice10.yaml

echo
echo "==== refresh current-step artifacts after step 6.6 ===="
"$PYTHON_BIN" scripts/maintenance/refresh_current_step_artifacts.py

echo
echo "==== start ollama ===="
"$OLLAMA_BIN" serve > "logs/ollama_s53_67_g4_r10_${SLURM_JOB_ID}.log" 2>&1 &
OLLAMA_PID=$!
trap 'kill $OLLAMA_PID 2>/dev/null || true' EXIT

echo
echo "==== wait for ollama ===="
READY=0
for i in $(seq 1 60); do
  if curl -fsS "http://${OLLAMA_HOST}/api/tags" >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 2
done
if [ "$READY" -ne 1 ]; then
  echo "OLLAMA_NOT_READY"
  exit 1
fi

echo
echo "==== available models ===="
"$OLLAMA_BIN" list || true

echo
echo "==== direct Gemma smoke ===="
curl -fsS "http://${OLLAMA_HOST}/api/generate" \
  -d '{
    "model":"gemma4:31b",
    "prompt":"Reply with exactly OK.",
    "stream":false,
    "options":{"temperature":0,"num_predict":2,"num_ctx":2048}
  }'

echo
echo "==== step 6.7 Gemma regression slice rerun ===="
"$PYTHON_BIN" steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py \
  --config data/work/cache/generated_configs/main_quest.hpc_gpu.gemma_regress10.yaml

echo
echo "==== latest step 6.7 stats summary ===="
"$PYTHON_BIN" - <<'PY'
from pathlib import Path
import json

sets = sorted(Path("data/processed/kc_drafts/_sets").glob("*_step6_7_kc_drafts_set.json"))
latest = sets[-1]
manifest = json.loads(latest.read_text(encoding="utf-8"))
stats = json.loads(Path(manifest["artifacts"]["draft_stats_json"]).read_text(encoding="utf-8"))

print("SET_MANIFEST", latest)
for k in [
    "definition_generation_mode",
    "definition_packet_family_recoveries",
    "definition_support_pack_auditor_recoveries",
    "verifier_abstained_definition_kcs",
    "authoritative_definition_status_breakdown",
]:
    print(k, "=", stats.get(k))
PY

echo
echo "PIPELINE_OK"
