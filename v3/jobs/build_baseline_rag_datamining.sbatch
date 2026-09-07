#!/bin/bash
#SBATCH --job-name=baseline_rag_datamining
#SBATCH --partition=big
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=01:00:00
#SBATCH --output=/path/to/kc_l/v3/logs/baseline_rag_datamining_%j.log
set -u
MIR=/path/to/kc_l
PROD=/path/to/shared
export LD_LIBRARY_PATH=/path/to/python/lib
export PYTHONPATH=$MIR/src
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
PY=/path/to/venv/bin/python
cd $MIR || exit 1
echo "host=$(hostname) start=$(date)"

RUN=v3_20260816_baseline_rag_datamining
DATA=$MIR/data/v3/runs/$RUN
mkdir -p $DATA/packets

$PY v3/pipeline/build_baseline_rag_packets.py \
  --real-packets-jsonl $MIR/data/v3/runs/v3_20260814_draft_3models_232029/packets/kc_packets.jsonl \
  --corpus-jsonl $PROD/data/processed/retrieval_sentence_overlay/20260727T022835Z_9e856df6/2026-07-27_085228/sentence_corpus.jsonl \
  --out-jsonl $DATA/packets/kc_packets.jsonl \
  --stats-json $DATA/packets/kc_packet_stats.json \
  --dense-cache-path $MIR/data/v3/runs/v3_20260812/_dense_cache/emb_0e0d7ac26a3a2a5f.npz
RC=$?
echo "=== COMPLETE rc=$RC $(date) ==="
exit $RC
