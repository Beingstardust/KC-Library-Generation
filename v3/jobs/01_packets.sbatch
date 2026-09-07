#!/bin/bash
#SBATCH --job-name=v3_packets
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
#SBATCH --output=/path/to/kc_l/v3/logs/01_packets_%j.log
set -u
MIR=/path/to/kc_l
PROD=/path/to/shared
# RUN must be supplied at submission. It was hardcoded to v3_20260812, which meant every
# resubmission silently overwrote that run's packets - a direct violation of the
# non-destructive convention every other job in this directory follows.
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

[ -e "$DATA/packets/kc_packets.jsonl" ] && { echo "FATAL: refusing to overwrite $DATA/packets/kc_packets.jsonl"; exit 9; }
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
