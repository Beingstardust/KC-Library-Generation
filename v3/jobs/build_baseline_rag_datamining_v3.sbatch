#!/bin/bash
#SBATCH --job-name=baseline_rag_dm_v3
#SBATCH --partition=big
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=01:00:00
#SBATCH --output=/path/to/kc_l/v3/logs/baseline_rag_datamining_v3_%j.log
set -u
# Rebuild of the conventional-RAG baseline packets after the Base Dense RAG fairness audit
# (local_audits/base_dense_rag_fairness_20260817T000000Z). Content is unchanged from
# v3_20260816_baseline_rag_datamining_budgetfix's packets - the only code change since that build
# was the packet_version tag (now "sentence_level_base_dense_rag_v1" instead of the generic
# "baseline_rag_v1"), so this run exists to carry the corrected label into a fresh RUN, and to
# pair identity fields against the CURRENT proposed-system packets rather than the older
# v3_20260814_draft_3models_232029 snapshot. Reuses the existing corpus embedding cache (same
# corpus file, same key derivation) for a fast rebuild - no re-embedding expected.
MIR=/path/to/kc_l
PROD=/path/to/shared
export LD_LIBRARY_PATH=/path/to/python/lib
export PYTHONPATH=$MIR/src
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
PY=/path/to/venv/bin/python
cd $MIR || exit 1
echo "host=$(hostname) start=$(date)"

RUN=v3_20260817_baseline_rag_datamining_promptfix
DATA=$MIR/data/v3/runs/$RUN
[ -e "$DATA/packets/kc_packets.jsonl" ] && { echo "FATAL: refusing to overwrite $DATA/packets/kc_packets.jsonl"; exit 9; }
mkdir -p $DATA/packets

$PY v3/pipeline/build_baseline_rag_packets.py \
  --real-packets-jsonl $MIR/data/v3/runs/v3_20260817_datamining_rebuild/packets/kc_packets.jsonl \
  --corpus-jsonl $PROD/data/processed/retrieval_sentence_overlay/20260727T022835Z_9e856df6/2026-07-27_085228/sentence_corpus.jsonl \
  --out-jsonl $DATA/packets/kc_packets.jsonl \
  --stats-json $DATA/packets/kc_packet_stats.json \
  --dense-cache-path $MIR/data/v3/runs/v3_20260812/_dense_cache/emb_0e0d7ac26a3a2a5f.npz
RC=$?
[ "$RC" -ne 0 ] && { echo "=== FAILED rc=$RC ==="; exit $RC; }

# Same post-build assertion as the v2 build: source_block_text must mirror text, and the total
# prompt-consumed chars must respect the shared budget.
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
