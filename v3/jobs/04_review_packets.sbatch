#!/bin/bash
#SBATCH --job-name=v3_review
#SBATCH --partition=big
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#SBATCH --output=/path/to/kc_l/v3/logs/04_review_%j.log
set -u
MIR=/path/to/kc_l
RUN=v3_20260812
MODEL=${MODEL:-gemma4_31b}
export LD_LIBRARY_PATH=/path/to/python/lib
export PYTHONPATH=$MIR/src
PY=/path/to/venv/bin/python
DATA=$MIR/data/v3/runs/$RUN
cd $MIR || exit 1
DRAFTS=$DATA/drafts/kc_drafts.jsonl
[ -f "$DRAFTS" ] || { echo "FATAL: drafts missing: $DRAFTS"; exit 2; }
mkdir -p $DATA/review

echo '=== stage 05: postprocess drafts into the review source ==='
$PY steps/step_06_7_postprocessed_review_source/scripts/run_step67_v2_postprocess_review_source.py   --source-drafts-jsonl $DRAFTS   --accepted-baseline-run-id $RUN   --out-dir $DATA/review/_postprocess   --run-id $RUN || exit 3

echo '=== stage 06: emit review packets ==='
$PY steps/step_06_8_review_packet_emission/scripts/run_step68_v2_review_packet_emission_from_postprocessed.py   --postprocessed-jsonl $DATA/review/_postprocess/step67_v2_postprocessed_review_source.jsonl   --out-dir $DATA/review/_emit   --run-id $RUN || exit 4

# the emitter writes a v2-era filename; give it the v3 name and assert the result
RAW=$DATA/review/_emit/step68_v2_review_packets.jsonl
[ -f "$RAW" ] || { echo 'FATAL: emitter produced no packets'; exit 5; }
cp "$RAW" $DATA/review/review_packets.jsonl
cp $DATA/review/_emit/step68_v2_review_queue_index.csv $DATA/review/review_queue.csv 2>/dev/null || true
[ -s $DATA/review/review_packets.jsonl ] || { echo 'FATAL: rename produced an empty file'; exit 6; }
echo "review packets -> $DATA/review/review_packets.jsonl ($(wc -l < $DATA/review/review_packets.jsonl) units)"
echo "=== COMPLETE $(date) ==="
