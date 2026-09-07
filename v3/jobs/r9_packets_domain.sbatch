#!/bin/bash
#SBATCH --job-name=r9_packets_domain
#SBATCH --partition=gpu80GB
#SBATCH --gres=gpu:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=12:00:00
#SBATCH --output=/path/to/shared%j.log
set -u

# Generic R8 experiment packet rebuild. This is deliberately a wrapper around the frozen R8
# implementation, not a pipeline edit. Submit with RUN, CORPUS, and HIER set to new, non-existing
# artifact paths; the job refuses to overwrite an existing packet file.
MIR=${MIR:-/path/to/shared}
RUN=${RUN:?FATAL: submit with a unique RUN under data/v3/runs}
CORPUS=${CORPUS:?FATAL: submit with CORPUS=/path/to/sentence_corpus.jsonl}
HIER=${HIER:?FATAL: submit with HIER=/path/to/hierarchy_overlay.jsonl}
VERIFY=${VERIFY:-1}

export LD_LIBRARY_PATH=/path/to/python/lib
export PYTHONPATH=$MIR/src
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

PY=${PY:-/path/to/venv/bin/python}
DATA=$MIR/data/v3/runs/$RUN

cd "$MIR" || exit 1
find "$MIR/src" -iname __pycache__ -exec rm -rf {} + 2>/dev/null
mkdir -p "$MIR/v3/logs"

echo "host=$(hostname) job=${SLURM_JOB_ID:-?} run=$RUN start=$(date)"
echo "repo_head=$(git -C "$MIR" rev-parse HEAD)"
echo "packet_builder_sha256=$(sha256sum "$MIR/v3/pipeline/02_build_kc_packets.py" | awk '{print $1}')"
echo "verifier_sha256=$(sha256sum "$MIR/v3/verify/verify_pipeline_fixes.py" | awk '{print $1}')"
echo "corpus=$CORPUS"
echo "hierarchy=$HIER"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || true

[ -f "$CORPUS" ] || { echo "FATAL: missing corpus: $CORPUS"; exit 10; }
[ -f "$HIER" ] || { echo "FATAL: missing hierarchy: $HIER"; exit 11; }
[ -e "$DATA/packets/kc_packets.jsonl" ] && {
  echo "FATAL: refusing to overwrite $DATA/packets/kc_packets.jsonl"; exit 9;
}
mkdir -p "$DATA/profiles" "$DATA/packets"

echo "=== stage 01: profiles from the knowledge registry ==="
"$PY" "$MIR/v3/pipeline/01_build_profiles.py" \
  --overlay-jsonl "$HIER" \
  --out-jsonl "$DATA/profiles/kc_profiles.jsonl" || exit 2

if [ "$VERIFY" = "1" ]; then
  echo "=== fix liveness ==="
  "$PY" "$MIR/v3/verify/verify_pipeline_fixes.py" || exit 3
fi

echo "=== stage 02: KC evidence packets ==="
"$PY" "$MIR/v3/pipeline/02_build_kc_packets.py" \
  --corpus-jsonl "$CORPUS" \
  --profile-jsonl "$DATA/profiles/kc_profiles.jsonl" \
  --out-jsonl "$DATA/packets/kc_packets.jsonl" \
  --stats-json "$DATA/packets/kc_packet_stats.json" \
  --bm25-pool 400 --max-passages 40 --max-chars 14000 --min-relevance 0.55 || exit 4

echo "=== stage 03: topic packets from the same evidence ==="
"$PY" "$MIR/v3/pipeline/03_build_topic_packets.py" \
  --hierarchy-jsonl "$HIER" \
  --kc-packets-jsonl "$DATA/packets/kc_packets.jsonl" \
  --out-jsonl "$DATA/packets/topic_packets.jsonl" \
  --stats-json "$DATA/packets/topic_packet_stats.json" || exit 5

echo "profiles_sha256=$(sha256sum "$DATA/profiles/kc_profiles.jsonl" | awk '{print $1}')"
echo "kc_packets_sha256=$(sha256sum "$DATA/packets/kc_packets.jsonl" | awk '{print $1}')"
echo "topic_packets_sha256=$(sha256sum "$DATA/packets/topic_packets.jsonl" | awk '{print $1}')"
echo "=== R9_PACKETS_DOMAIN_COMPLETE $(date) ==="
