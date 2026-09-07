#!/bin/bash
#SBATCH --job-name=v3_packets_mathematics
# GPU requested for the relevance models only. Every previous build logged
# "reranker=True device=cpu" and spent ~150-250 s per unit almost entirely on cross-encoder
# scoring; CrossEncoderReranker/DenseIndex auto-select CUDA when it is visible, so this is a
# hardware change with no change to retrieval logic. TF32 is disabled in retrieval.py so the
# scores that face the 0.55 admission floor do not depend on the device.
#SBATCH --partition=gpu80GB
#SBATCH --gres=gpu:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=12:00:00
#SBATCH --output=/path/to/kc_l/v3/logs/01_packets_mathematics_%j.log
set -u
MIR=/path/to/kc_l
RUN=${RUN:?FATAL: submit with a unique RUN under data/v3/runs}
export LD_LIBRARY_PATH=/path/to/python/lib
export PYTHONPATH=$MIR/src
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
PY=/path/to/venv/bin/python
DATA=$MIR/data/v3/runs/$RUN
# mathematics-specific corpus + hierarchy overlay, both built by the orchestrator's own PDF
# ingestion chain (steps 02-04.5 and hierarchy_registry) for run_id 20260815T010743Z_ea40e85c -
# NOT the orchestrator's own step_05x/06_x evidence stages, which use a separate, less-audited
# evidence-building module (evidence_stage_v3_candidate_bank.py, 5 commits of fix history) instead
# of this project's actual verified pipeline (evidence_pack.py, 18 commits, the full v3-v47 fix
# cycle documented in FAILURE_CYCLE_2.md, gated by verify_pipeline_fixes.py below). Same code path
# as sociology and data-mining, just pointed at mathematics' own corpus/hierarchy inputs.
CORPUS=$MIR/data/processed/retrieval_sentence_overlay/20260815T010743Z_ea40e85c/2026-08-15_102628/sentence_corpus.jsonl
HIER=$MIR/data/processed/hierarchy_overlay/20260815T010743Z_ea40e85c/2026-08-15_010748_hierarchy_overlay/hierarchy_overlay.jsonl
cd $MIR || exit 1
find $MIR/src -iname __pycache__ -exec rm -rf {} + 2>/dev/null
echo "host=$(hostname) run=$RUN start=$(date)"

[ -f "$CORPUS" ] || { echo "FATAL: mathematics corpus missing: $CORPUS"; exit 10; }
[ -f "$HIER" ] || { echo "FATAL: mathematics hierarchy overlay missing: $HIER"; exit 11; }

mkdir -p $DATA/profiles $DATA/packets $MIR/v3/logs

echo "=== stage 01: profiles from the knowledge registry ==="
$PY $MIR/v3/pipeline/01_build_profiles.py \
  --overlay-jsonl $HIER \
  --out-jsonl $DATA/profiles/kc_profiles.jsonl || exit 2

echo "=== fix liveness (a fix that exists but does nothing fails here) ==="
$PY $MIR/v3/verify/verify_pipeline_fixes.py || exit 3

echo "=== stage 02: KC evidence packets ==="
$PY $MIR/v3/pipeline/02_build_kc_packets.py \
  --corpus-jsonl $CORPUS \
  --profile-jsonl $DATA/profiles/kc_profiles.jsonl \
  --out-jsonl $DATA/packets/kc_packets.jsonl \
  --stats-json $DATA/packets/kc_packet_stats.json \
  --bm25-pool 400 --max-passages 40 --max-chars 14000 --min-relevance 0.55 || exit 4

echo "=== stage 03: topic packets from the same evidence ==="
$PY $MIR/v3/pipeline/03_build_topic_packets.py \
  --hierarchy-jsonl $HIER \
  --kc-packets-jsonl $DATA/packets/kc_packets.jsonl \
  --out-jsonl $DATA/packets/topic_packets.jsonl \
  --stats-json $DATA/packets/topic_packet_stats.json || exit 5

echo "=== COMPLETE $(date) ==="
