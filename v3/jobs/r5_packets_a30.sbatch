#!/bin/bash
#SBATCH --job-name=r5_packets
#SBATCH --partition=gpu
#SBATCH --gres=gpu:a30:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=12:00:00
#SBATCH --output=/path/to/shared%j.log
set -u
# Same shape as v3/jobs/01_packets.sbatch, pointed at the vnext repo and at the taxonomy-corrected
# hierarchy. Two differences from every previous final build, both deliberate:
#   - HIER is the split overlay: "Feature Set Generation Algorithms" replaced by "Search
#     Directions" and "Search Strategies", so SFG/SBG/BG/RG are no longer siblings of
#     Exhaustive/Heuristic/Non-Deterministic. That changes sibling_kc_names and therefore
#     rival_units_considered for those seven units, which is the whole point.
#   - the code is HEAD, carrying INT-15 through INT-19.
V=/path/to/shared
PROD=/path/to/shared
RUN=${RUN:?FATAL: submit with a unique RUN under data/v3/runs}
export LD_LIBRARY_PATH=/path/to/python/lib
export PYTHONPATH=$V/src
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
PY=/path/to/venv/bin/python
DATA=$V/data/v3/runs/$RUN
CORPUS=$PROD/data/processed/retrieval_sentence_overlay/20260727T022835Z_9e856df6/2026-07-27_085228/sentence_corpus.jsonl
HIER=$V/data/v3/hierarchy/hierarchy_overlay_taxonomy_split.jsonl
cd $V || exit 1
find $V/src -iname __pycache__ -exec rm -rf {} + 2>/dev/null
echo "host=$(hostname) run=$RUN start=$(date)"
echo "code=$(git -C $V rev-parse --short HEAD 2>/dev/null || echo '(git unavailable on compute node)')"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || true

[ -e "$DATA/packets/kc_packets.jsonl" ] && { echo "FATAL: refusing to overwrite $DATA/packets/kc_packets.jsonl"; exit 9; }
[ -e "$HIER" ] || { echo "FATAL: taxonomy-split hierarchy not found at $HIER"; exit 8; }
mkdir -p $DATA/profiles $DATA/packets $V/v3/logs

echo "=== hierarchy in use ==="
echo "  $HIER  ($(wc -l < $HIER) nodes)"
grep -c 'Feature Set Generation Algorithms' $HIER && { echo "FATAL: the conflating parent is still present"; exit 7; } || echo "  conflating parent absent, as intended"

echo "=== stage 01: profiles from the knowledge registry ==="
$PY $V/v3/pipeline/01_build_profiles.py \
  --overlay-jsonl $HIER \
  --out-jsonl $DATA/profiles/kc_profiles.jsonl || exit 2

echo "=== fix liveness (a fix that exists but does nothing fails here) ==="
$PY $V/v3/verify/verify_pipeline_fixes.py || exit 3

echo "=== stage 02: KC evidence packets ==="
$PY $V/v3/pipeline/02_build_kc_packets.py \
  --corpus-jsonl $CORPUS \
  --profile-jsonl $DATA/profiles/kc_profiles.jsonl \
  --out-jsonl $DATA/packets/kc_packets.jsonl \
  --stats-json $DATA/packets/kc_packet_stats.json \
  --bm25-pool 400 --max-passages 40 --max-chars 14000 --min-relevance 0.55 || exit 4

echo "=== stage 03: topic packets from the same evidence ==="
$PY $V/v3/pipeline/03_build_topic_packets.py \
  --hierarchy-jsonl $HIER \
  --kc-packets-jsonl $DATA/packets/kc_packets.jsonl \
  --out-jsonl $DATA/packets/topic_packets.jsonl \
  --stats-json $DATA/packets/topic_packet_stats.json || exit 5

echo "=== sanity: the seven feature-selection units must have new sibling sets ==="
$PY - "$DATA/packets/kc_packets.jsonl" <<'PYEOF'
import json, sys
want = {"Sequential Forward Generation (SFG)", "Non-Deterministic Search"}
for line in open(sys.argv[1], encoding="utf-8"):
    row = json.loads(line)
    if row.get("canonical_name") in want:
        print("  %-38s parent=%s" % (row["canonical_name"],
                                     (row.get("hierarchy") or {}).get("parent_topic_label")))
        print("      siblings: %s" % (row.get("sibling_kc_names") or [])[:8])
        print("      rivals  : %s" % (row.get("rival_units_considered") or [])[:8])
PYEOF

echo "kc packets : $(wc -l < $DATA/packets/kc_packets.jsonl)"
echo "topic packets: $(wc -l < $DATA/packets/topic_packets.jsonl)"
echo "=== R5_PACKETS_COMPLETE $(date) ==="
