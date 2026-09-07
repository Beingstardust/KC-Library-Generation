#!/bin/bash
#SBATCH --job-name=v3_draft_kc_commandr
#SBATCH --partition=gpu80GB
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --gres=gpu:1
#SBATCH --time=24:00:00
#SBATCH --output=/path/to/kc_l/v3/logs/02_draft_kc_commandr_%j.log
set -u
MIR=/path/to/kc_l
PROD=/path/to/shared
RUN=${RUN:?FATAL: submit with a unique RUN under data/v3/runs}
export LD_LIBRARY_PATH=/path/to/python/lib
export PYTHONPATH=$MIR/src
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
PY=/path/to/venv/bin/python
DATA=$MIR/data/v3/runs/$RUN
CORPUS=$PROD/data/processed/retrieval_sentence_overlay/20260727T022835Z_9e856df6/2026-07-27_085228/sentence_corpus.jsonl
HIER=$MIR/data/processed/hierarchy_overlay/20260727T022835Z_9e856df6/2026-07-27_022841_hierarchy_overlay/hierarchy_overlay.jsonl
cd $MIR || exit 1
find $MIR/src -iname __pycache__ -exec rm -rf {} + 2>/dev/null
echo "host=$(hostname) run=$RUN start=$(date)"

mkdir -p $DATA/drafts $MIR/v3/logs
source $MIR/config/runtime/clusterb_ollama_command_r_35b.env

# unique ollama port per job: these GPU nodes hold two cards, so two drafting jobs can share a
# node, and a fixed port made the second silently use the first job's server
BASE_PORT=$(( 21000 + (${SLURM_JOB_ID:-0} % 8000) ))
for OFFSET in $(seq 0 40); do
  CAND=$(( BASE_PORT + OFFSET ))
  if ! (exec 3<>/dev/tcp/127.0.0.1/$CAND) 2>/dev/null; then export OLLAMA_HOST="127.0.0.1:$CAND"; break; fi
done
echo "ollama port: $OLLAMA_HOST"

PKT=$DATA/packets/kc_packets.jsonl
OUT=$DATA/drafts/kc_work_command_r_35b
FINAL=$DATA/drafts/kc_drafts_command_r_35b.jsonl
[ -f "$PKT" ] || { echo "FATAL: packets missing: $PKT"; exit 2; }
[ ! -e "$OUT" ] && [ ! -e "$FINAL" ] || {
  echo "FATAL: refusing to overwrite existing Command-R artifacts under run $RUN"; exit 8;
}
mkdir -p $OUT

OLLAMA_PID=""
cleanup(){ [ -n "$OLLAMA_PID" ] && kill $OLLAMA_PID 2>/dev/null || true; }
trap cleanup EXIT

"$KC_L_OLLAMA_BIN" serve > $OUT/ollama_serve.log 2>&1 &
OLLAMA_PID=$!
UP=0
for i in $(seq 1 120); do curl -sf http://$OLLAMA_HOST/api/tags >/dev/null 2>&1 && { UP=1; break; }; sleep 2; done
[ "$UP" = "1" ] || { echo "FATAL: ollama did not start"; exit 3; }

"$KC_L_OLLAMA_BIN" show "$KC_L_PROFILE_MODEL" >/dev/null 2>&1 || { echo "FATAL: model absent: $KC_L_PROFILE_MODEL"; exit 4; }
curl -sf http://$OLLAMA_HOST/api/generate -d "{\"model\":\"$KC_L_PROFILE_MODEL\",\"prompt\":\"ready\",\"stream\":false}" >/dev/null 2>&1 \
  || { echo "FATAL: model failed preflight"; exit 5; }
echo "preflight OK: $KC_L_PROFILE_MODEL"

echo '{}' > $OUT/plan.json
$PY steps/step_06_7_kc_draft_generation/scripts/v2_chain/run_step67_v2_schema_contract_probe.py \
  --base-runner $MIR/v3/pipeline/04_draft_runner.py \
  --selected-packets-jsonl $PKT \
  --plan-json $OUT/plan.json \
  --out-dir $OUT \
  --run-id kc_command_r_35b \
  --model "$KC_L_PROFILE_MODEL" \
  --num-ctx 32768 --num-predict 16000 --timeout-s 1200 \
  --ollama-host "$OLLAMA_HOST" --seed 20260812
echo "probe rc=$? (informational: a correct abstention makes this non-zero)"

# the probe writes a v2-era filename; give it the v3 name and assert the rename happened
RAW=$OUT/step67_v2_tiny_smoke_drafts.jsonl
[ -f "$RAW" ] || { echo "FATAL: no drafts produced"; exit 6; }
cp "$RAW" "$FINAL"
[ -s "$FINAL" ] || { echo "FATAL: rename produced an empty file"; exit 7; }
echo "drafts -> $FINAL ($(wc -l < $FINAL) rows)"

# archive this attempt permanently, job-ID-stamped: $FINAL itself gets overwritten by the next
# resubmission under the same fixed $RUN, which otherwise makes historical run comparison
# impossible - this is purely additive and does not change $FINAL or any downstream stage.
mkdir -p $DATA/drafts/archive
ARCHIVE_BASE=$DATA/drafts/archive/$(basename "$FINAL" .jsonl)_job${SLURM_JOB_ID:-unknown}
cp "$FINAL" "${ARCHIVE_BASE}.jsonl"
[ -f "$OUT/STEP67_V2_TINY_SMOKE_SUMMARY.json" ] && cp "$OUT/STEP67_V2_TINY_SMOKE_SUMMARY.json" "${ARCHIVE_BASE}_summary.json"
echo "archived -> ${ARCHIVE_BASE}.jsonl"

$PY $MIR/v3/verify/validate_drafts.py --drafts-jsonl "$FINAL" --packets-jsonl "$PKT" --run-id kc_command_r_35b
VAL=$?
echo "=== validation rc=$VAL model=$KC_L_PROFILE_MODEL $(date) ==="

# Best-effort: make this run visible in the review console. Never affects this job's own
# exit code (drafting succeeding is the real contract; console registration is a
# downstream convenience). Idempotent and safe to run from multiple concurrent jobs - it
# scans every run under data/v3/runs/ each time, not just this one.
"$PY" "$MIR/v3/pipeline/06_sync_console_registry.py" \
  || echo "WARNING: console registry sync failed (non-fatal, drafting itself succeeded)"

exit $VAL
