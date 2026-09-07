#!/bin/bash
# Launch KC and topic drafting for one model against one run, together, in parallel.
#
# KC drafting reads kc_packets.jsonl; topic drafting reads topic_packets.jsonl. Neither depends
# on the other's output, so nothing should make one wait on the other - a topic script chained to
# fire only after its KC sibling finishes (the design this replaces) makes topic drafting start
# late for no real reason, and silently never starts at all for any KC job submitted before that
# chain existed (confirmed twice this session: jobs 246323/246324). Submitting both here, with no
# --dependency between them, lets SLURM schedule them onto separate GPUs concurrently whenever
# they're both available - true parallel start, not "started right after something else finished."
#
# Usage: launch_model_drafting.sh <model> <RUN>
#   model: gemma4 | qwen36 | qwen38 | deepseek | commandr
#   RUN:   a unique run id under data/v3/runs/<RUN>/packets/{kc_packets,topic_packets}.jsonl
set -u
MIR=/path/to/kc_l
cd "$MIR" || exit 1

MODEL=${1:?"usage: $0 <model: gemma4|qwen36|qwen38|deepseek|commandr> <RUN>"}
RUN=${2:?"usage: $0 <model: gemma4|qwen36|qwen38|deepseek|commandr> <RUN>"}

case "$MODEL" in
  gemma4)   KC_SCRIPT=v3/jobs/02_draft_kc_gemma4.sbatch;    TOPIC_SCRIPT=v3/jobs/03_draft_topics.sbatch ;;
  qwen36)   KC_SCRIPT=v3/jobs/02_draft_kc_qwen36.sbatch;    TOPIC_SCRIPT=v3/jobs/03_draft_topics_qwen36.sbatch ;;
  qwen38)   KC_SCRIPT=v3/jobs/02_draft_kc_qwen38.sbatch;    TOPIC_SCRIPT=v3/jobs/03_draft_topics_qwen38.sbatch ;;
  deepseek) KC_SCRIPT=v3/jobs/02_draft_kc_deepseek.sbatch;  TOPIC_SCRIPT=v3/jobs/03_draft_topics_deepseek.sbatch ;;
  commandr) KC_SCRIPT=v3/jobs/02_draft_kc_commandr.sbatch;  TOPIC_SCRIPT=v3/jobs/03_draft_topics_commandr.sbatch ;;
  *) echo "FATAL: unknown model '$MODEL' (expected gemma4|qwen36|qwen38|deepseek|commandr)"; exit 2 ;;
esac

[ -f "$MIR/data/v3/runs/$RUN/packets/kc_packets.jsonl" ] || {
  echo "FATAL: kc_packets.jsonl missing under run $RUN - build packets first"; exit 3; }
[ -f "$MIR/data/v3/runs/$RUN/packets/topic_packets.jsonl" ] || {
  echo "FATAL: topic_packets.jsonl missing under run $RUN - build packets first"; exit 4; }

KC_JOB=$(RUN="$RUN" sbatch --parsable "$KC_SCRIPT") || { echo "FATAL: KC submission failed"; exit 5; }
TOPIC_JOB=$(RUN="$RUN" sbatch --parsable "$TOPIC_SCRIPT") || { echo "FATAL: topic submission failed"; exit 6; }

echo "model=$MODEL run=$RUN"
echo "KC_JOB=$KC_JOB    ($KC_SCRIPT)"
echo "TOPIC_JOB=$TOPIC_JOB ($TOPIC_SCRIPT)"
echo "Both submitted independently - no --dependency between them, so SLURM can run them"
echo "concurrently on separate GPUs as soon as each is available. Each job's own trailing"
echo "console-sync step registers whatever is available when IT finishes; whichever of the two"
echo "finishes second is the one that ends up producing the full KC+topic bundle."
