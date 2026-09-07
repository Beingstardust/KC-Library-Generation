#!/bin/bash
set -euo pipefail

# Submit the R9 ablations against the latest committed pipeline worktree.
# Unlike the original R9 convenience submitter, the DOS budget-matched arm is explicitly
# dependent on the newly rebuilt data-mining packets and uses those packets as Proposed.

MIR=${MIR:-/path/to/shared}
OLD_MIR=${OLD_MIR:-/path/to/kc_l}
PROD=${PROD:-/path/to/shared}
RUN_PREFIX=${RUN_PREFIX:-r9_latest_$(date -u +%Y%m%dT%H%M%SZ)}
EXPECTED_HEAD=${EXPECTED_HEAD:-6ebcd7562ebaf8d2199b6a94eb7ec8836dd4300e}

DM_RUN=${DM_RUN:-${RUN_PREFIX}_datamining_latest}
SOC_RUN=${SOC_RUN:-${RUN_PREFIX}_sociology_latest}
MATH_RUN=${MATH_RUN:-${RUN_PREFIX}_mathematics_latest}
DOS_EXPERIMENT=${DOS_EXPERIMENT:-${RUN_PREFIX}_dos_budget_matched_latest}
DOS_MATCHED_RUN=${DOS_MATCHED_RUN:-${RUN_PREFIX}_dos_budget_matched_latest_run}

DM_CORPUS=${DM_CORPUS:-$PROD/data/processed/retrieval_sentence_overlay/20260727T022835Z_9e856df6/2026-07-27_085228/sentence_corpus.jsonl}
DM_HIER=${DM_HIER:-$OLD_MIR/data/processed/hierarchy_overlay/20260727T022835Z_9e856df6/2026-07-27_022841_hierarchy_overlay/hierarchy_overlay.jsonl}
SOC_CORPUS=${SOC_CORPUS:-$PROD/data/processed/retrieval_sentence_overlay/20260809T140541Z_01d6072f/2026-08-10_145522/sentence_corpus.jsonl}
SOC_HIER=${SOC_HIER:-$PROD/data/processed/hierarchy_overlay/20260809T140541Z_01d6072f/2026-08-09_155917_hierarchy_overlay/hierarchy_overlay.jsonl}
MATH_CORPUS=${MATH_CORPUS:-$OLD_MIR/data/processed/retrieval_sentence_overlay/20260815T010743Z_ea40e85c/2026-08-15_102628/sentence_corpus.jsonl}
MATH_HIER=${MATH_HIER:-$OLD_MIR/data/processed/hierarchy_overlay/20260815T010743Z_ea40e85c/2026-08-15_010748_hierarchy_overlay/hierarchy_overlay.jsonl}

cd "$MIR"
actual_head=$(git -C "$MIR" rev-parse HEAD)
[ "$actual_head" = "$EXPECTED_HEAD" ] || {
  echo "FATAL: latest-pipeline submitter expected $EXPECTED_HEAD but found $actual_head"
  exit 12
}

mkdir -p "$MIR/data/v3/experiments/$RUN_PREFIX" "$MIR/v3/logs"

for run in "$DM_RUN" "$SOC_RUN" "$MATH_RUN" "$DOS_MATCHED_RUN"; do
  [ ! -e "$MIR/data/v3/runs/$run" ] || { echo "FATAL: run already exists: $run"; exit 9; }
done
[ ! -e "$MIR/data/v3/experiments/$DOS_EXPERIMENT" ] || {
  echo "FATAL: experiment already exists: $DOS_EXPERIMENT"; exit 10;
}

submit_packets() {
  local run=$1 corpus=$2 hier=$3
  sbatch --parsable \
    --output="$MIR/v3/logs/r9_latest_packets_domain_%j.log" \
    --export=ALL,MIR="$MIR",RUN="$run",CORPUS="$corpus",HIER="$hier" \
    "$MIR/v3/jobs/r9_packets_domain.sbatch"
}

submit_draft() {
  local dep=$1 run=$2 profile=$3 slug=$4 final_name=$5 prompt_mode=$6 run_id=$7
  sbatch --parsable \
    --dependency=afterok:"$dep" \
    --output="$MIR/v3/logs/r9_latest_draft_kc_model_%j.log" \
    --export=ALL,MIR="$MIR",RUN="$run",MODEL_PROFILE="$profile",MODEL_SLUG="$slug",FINAL_NAME="$final_name",PROMPT_MODE="$prompt_mode",RUN_ID="$run_id" \
    "$MIR/v3/jobs/r9_draft_kc_model.sbatch"
}

dm_packets=$(submit_packets "$DM_RUN" "$DM_CORPUS" "$DM_HIER")
soc_packets=$(submit_packets "$SOC_RUN" "$SOC_CORPUS" "$SOC_HIER")
math_packets=$(submit_packets "$MATH_RUN" "$MATH_CORPUS" "$MATH_HIER")

dm_qwen=$(submit_draft "$dm_packets" "$DM_RUN" config/runtime/clusterb_ollama_qwen38_27b.env qwen38_27b kc_drafts_qwen38_27b.jsonl native_proposed kc_qwen38_27b)
dm_gemma=$(submit_draft "$dm_packets" "$DM_RUN" config/runtime/clusterb_ollama_gemma4_31b.env gemma4_31b kc_drafts_gemma4_31b.jsonl native_proposed kc_gemma4_31b)
dm_deepseek=$(submit_draft "$dm_packets" "$DM_RUN" config/runtime/clusterb_ollama_deepseek_r1_32b.env deepseek_r1_32b kc_drafts_deepseek_r1_32b.jsonl native_proposed kc_deepseek_r1_32b)
soc_qwen=$(submit_draft "$soc_packets" "$SOC_RUN" config/runtime/clusterb_ollama_qwen38_27b.env qwen38_27b kc_drafts_qwen38_27b.jsonl native_proposed kc_qwen38_27b)
math_qwen=$(submit_draft "$math_packets" "$MATH_RUN" config/runtime/clusterb_ollama_qwen38_27b.env qwen38_27b kc_drafts_qwen38_27b.jsonl native_proposed kc_qwen38_27b)

latest_proposed_packets="$MIR/data/v3/runs/$DM_RUN/packets/kc_packets.jsonl"
dos_match=$(sbatch --parsable \
  --dependency=afterok:"$dm_packets" \
  --output="$MIR/v3/logs/r9_latest_dos_budget_match_%j.log" \
  --time=12:00:00 \
  --export=ALL,MIR="$MIR",OLD_MIR="$OLD_MIR",PROD="$PROD",EXPERIMENT_ID="$DOS_EXPERIMENT",MATCHED_RUN="$DOS_MATCHED_RUN",PROPOSED_PACKETS="$latest_proposed_packets",ALLOW_OLLAMA_GENERATE_TOKEN_COUNT=1 \
  "$MIR/v3/jobs/r9_dos_budget_match.sbatch")
dos_draft=$(submit_draft "$dos_match" "$DOS_MATCHED_RUN" config/runtime/clusterb_ollama_qwen38_27b.env qwen38_27b kc_drafts_qwen38_27b.jsonl controlled_comparator dos_matched_qwen38_27b)

jobs="$dm_packets $soc_packets $math_packets $dm_qwen $dm_gemma $dm_deepseek $soc_qwen $math_qwen $dos_match $dos_draft"
labels="data-mining packets latest|sociology packets latest|mathematics packets latest|data-mining qwen3.8 latest|data-mining gemma4 latest|data-mining deepseek latest|sociology qwen3.8 latest|mathematics qwen3.8 latest|DOS matched-budget latest packet gate|DOS matched-budget latest qwen3.8"
status="$MIR/data/v3/experiments/$RUN_PREFIX/chain_status.txt"
watchdog=$(sbatch --parsable \
  --output="$MIR/v3/logs/r9_latest_chain_watchdog_%j.log" \
  --export=ALL,MIR="$MIR",JOBS="$jobs",LABELS="$labels",STATUS="$status" \
  "$MIR/v3/jobs/r9_chain_watchdog.sbatch")

manifest="$MIR/data/v3/experiments/$RUN_PREFIX/submission_manifest.json"
cat > "$manifest" <<JSON
{
  "run_prefix": "$RUN_PREFIX",
  "submitted_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "repo": "$MIR",
  "repo_head": "$actual_head",
  "expected_head": "$EXPECTED_HEAD",
  "latest_proposed_packets_for_dos": "$latest_proposed_packets",
  "runs": {
    "datamining": "$DM_RUN",
    "sociology": "$SOC_RUN",
    "mathematics": "$MATH_RUN",
    "dos_matched": "$DOS_MATCHED_RUN"
  },
  "experiments": {
    "dos_budget_matched": "$DOS_EXPERIMENT",
    "submission_root": "$MIR/data/v3/experiments/$RUN_PREFIX",
    "chain_status": "$status"
  },
  "jobs": {
    "data_mining_packets": "$dm_packets",
    "sociology_packets": "$soc_packets",
    "mathematics_packets": "$math_packets",
    "data_mining_qwen38": "$dm_qwen",
    "data_mining_gemma4": "$dm_gemma",
    "data_mining_deepseek": "$dm_deepseek",
    "sociology_qwen38": "$soc_qwen",
    "mathematics_qwen38": "$math_qwen",
    "dos_budget_match": "$dos_match",
    "dos_budget_matched_qwen38": "$dos_draft",
    "watchdog": "$watchdog"
  }
}
JSON

cat "$manifest"
