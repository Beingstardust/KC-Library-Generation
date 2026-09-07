#!/bin/bash
#SBATCH --job-name=baseline_rag_dm_v2
#SBATCH --partition=big
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=01:00:00
#SBATCH --output=/path/to/kc_l/v3/logs/baseline_rag_datamining_v2_%j.log
set -u
# Rebuild of the conventional-RAG baseline packets after the evidence-budget fix.
#
# The first build (run v3_20260816_baseline_rag_datamining) budgeted only the `text` field while
# also writing an unbudgeted `source_block_text` per item. Both fields reach the drafting prompt
# (04_draft_runner.py _PROMPT_TEXT_FIELDS), so the real prompt payload was ~8x the 14,000-char
# control: median prompt 29,028 tokens for qwen3.8 and 32,691 for gemma4 against a 32,768 context,
# truncating 42/159 and 21/159 units respectively with done_reason=length. That made the baseline
# condition context-starved rather than merely noisier, so its comparison against the proposed
# system was not valid.
#
# New run directory, not an overwrite: the first build's packets and both of its drafting runs are
# kept intact as the record of the confound.
MIR=/path/to/kc_l
PROD=/path/to/shared
export LD_LIBRARY_PATH=/path/to/python/lib
export PYTHONPATH=$MIR/src
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
PY=/path/to/venv/bin/python
cd $MIR || exit 1
echo "host=$(hostname) start=$(date)"

RUN=v3_20260816_baseline_rag_datamining_budgetfix
DATA=$MIR/data/v3/runs/$RUN
[ -e "$DATA/packets/kc_packets.jsonl" ] && { echo "FATAL: refusing to overwrite $DATA/packets/kc_packets.jsonl"; exit 9; }
mkdir -p $DATA/packets

$PY v3/pipeline/build_baseline_rag_packets.py \
  --real-packets-jsonl $MIR/data/v3/runs/v3_20260814_draft_3models_232029/packets/kc_packets.jsonl \
  --corpus-jsonl $PROD/data/processed/retrieval_sentence_overlay/20260727T022835Z_9e856df6/2026-07-27_085228/sentence_corpus.jsonl \
  --out-jsonl $DATA/packets/kc_packets.jsonl \
  --stats-json $DATA/packets/kc_packet_stats.json \
  --dense-cache-path $MIR/data/v3/runs/v3_20260812/_dense_cache/emb_0e0d7ac26a3a2a5f.npz
RC=$?
[ "$RC" -ne 0 ] && { echo "=== FAILED rc=$RC ==="; exit $RC; }

# Assert the fix actually took effect before anything downstream trusts these packets: every item's
# source_block_text must equal its text, and the total prompt-consumed chars must respect the cap.
$PY - "$DATA/packets/kc_packets.jsonl" <<'PYEOF'
import json, sys
bad_mirror = 0
over_budget = 0
worst = 0
n = 0
for line in open(sys.argv[1], encoding='utf-8'):
    r = json.loads(line); n += 1
    total = 0
    for e in (r.get('evidence_for_synthesis') or []):
        t = e.get('text') or ''
        b = e.get('source_block_text') or ''
        if b != t:
            bad_mirror += 1
        total += len(t) + len(b)
    worst = max(worst, total)
    if total > 2 * 14000 + 1000:
        over_budget += 1
print('units                        :', n)
print('items where block != text    :', bad_mirror)
print('units over prompt-char budget:', over_budget)
print('worst prompt-consumed chars  :', worst)
if bad_mirror or over_budget:
    print('VERIFY_FAILED')
    sys.exit(12)
print('VERIFY_OK')
PYEOF
VRC=$?
echo "=== COMPLETE build_rc=$RC verify_rc=$VRC $(date) ==="
exit $VRC
